"""
visual_hull.py — 실루엣 기반 3D 복원 (스트레치 목표) + 포인트클라우드와 겹쳐 보기

turntable_scan.py가 저장한 실루엣 마스크(masks/)와 리그 캘리브레이션으로
복셀을 깎아(voxel carving) 물체 외형을 만든 뒤, Open3D로 depth 병합 모델과
같은 좌표계에 겹쳐 보여주고 두 방식의 치수를 비교합니다.

카빙 방식
    턴테이블 좌표계에 복셀 격자를 만들고, 각 뷰·카메라마다 복셀 중심을 이미지에
    투영해 실루엣 밖에 떨어지면 "miss"를 센다. miss가 VH_MISS_TOLERANCE(기본 2)를
    넘는 복셀만 제거한다 — 마스크 한두 장이 잘못돼도 물체가 깎여 나가지 않게 하기
    위함이다(Open3D의 carve_silhouette는 한 장만 틀려도 바로 지운다).
    계산은 numpy로 하고, 결과 복셀은 Open3D VoxelGrid로 표시한다.

한계: 윤곽에 드러나지 않는 오목한 부분(찌그러짐)은 복원되지 않는다.
      치수 판정의 기준은 depth 병합 모델(measure_object.py)이다.

실행:
    python visual_hull.py                       # 최근 세션
    python visual_hull.py scans/20261001_1030
    python visual_hull.py --side-by-side        # 겹치지 않고 나란히 보기
    python visual_hull.py --voxel 0.002 --no-view
결과: <세션>/visual_hull.ply (복셀 중심 점), <세션>/visual_hull.json (치수 비교)
"""

import argparse
import glob
import json
import os

import cv2
import numpy as np

import config
from rig import RigCalibration, project_points


def voxel_grid(bounds_min, bounds_max, voxel):
    axes = [np.arange(lo + voxel / 2, hi, voxel) for lo, hi in zip(bounds_min, bounds_max)]
    g = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return g.astype(np.float32)


def carve(centers, views, miss_tolerance=config.VH_MISS_TOLERANCE, log=print):
    """centers: (N,3) 턴테이블 좌표 복셀 중심
    views: [(mask(H,W) bool, R(3x3), t(3,), intr dict)] — R,t: 턴테이블 좌표 → 카메라 좌표
    반환: 남은 복셀 중심 (M,3)"""
    alive = np.arange(len(centers))
    miss = np.zeros(len(centers), dtype=np.int16)
    for i, (mask, R, t, intr) in enumerate(views):
        p = centers[alive] @ R.T.astype(np.float32) + t.astype(np.float32)
        u, v, z = project_points(p, intr)
        h, w = mask.shape
        inside = (z > 0) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
        ui = np.clip(u, 0, w - 1).astype(np.int32)
        vi = np.clip(v, 0, h - 1).astype(np.int32)
        out_sil = inside & ~mask[vi, ui]          # 이미지 안인데 실루엣 밖 → miss
        miss[alive[out_sil]] += 1
        alive = alive[miss[alive] <= miss_tolerance]
        if log and (i + 1) % 12 == 0:
            log(f"  {i + 1}/{len(views)} 뷰 처리, 남은 복셀 {len(alive)}")
    return centers[alive]


def load_views(session, rig, dilate_px=config.VH_MASK_DILATE_PX):
    with open(os.path.join(session, "meta.json"), encoding="utf-8") as fp:
        meta = json.load(fp)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1,) * 2) if dilate_px else None
    views = []
    for rec in meta["views"]:
        for cam in ("A", "B"):
            path = os.path.join(session, "masks", f"{rec['stem']}_cam{cam}.png")
            m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if m is None:
                print(f"  [경고] 마스크 없음: {path}")
                continue
            if kernel is not None:
                m = cv2.dilate(m, kernel)
            R, t = rig.extrinsic(cam, rec["theta_deg"])
            views.append((m > 0, R, t, meta["cameras"][cam]["intrinsics"]))
    return views


def hull_bounds(session, margin=0.01):
    """병합 모델이 있으면 그 범위 + 여유로 격자를 줄여 계산을 빠르게 한다."""
    r, h = config.ROI_RADIUS_M, config.ROI_HEIGHT_M
    lo, hi = np.array([-r, config.PLATE_MARGIN_M, -r]), np.array([r, h, r])
    merged = os.path.join(session, "merged_model.ply")
    if os.path.exists(merged):
        import open3d as o3d
        pts = np.asarray(o3d.io.read_point_cloud(merged).points)
        if len(pts):
            lo = np.maximum(lo, pts.min(axis=0) - margin)
            hi = np.minimum(hi, pts.max(axis=0) + margin)
    return lo, hi


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", default=None)
    ap.add_argument("--voxel", type=float, default=config.VH_VOXEL_M)
    ap.add_argument("--side-by-side", action="store_true")
    ap.add_argument("--no-view", action="store_true")
    args = ap.parse_args()

    import open3d as o3d
    from measure_object import DIM_KEYS, DIM_KO, measure_points
    from merge_turntable_scans import latest_session

    session = args.session or latest_session()
    rig_path = os.path.join(session, "rig_calibration.npz")
    rig = RigCalibration.load(rig_path if os.path.exists(rig_path) else config.RIG_CALIB_PATH)

    views = load_views(session, rig)
    lo, hi = hull_bounds(session)
    centers = voxel_grid(lo, hi, args.voxel)
    print(f"세션: {session}\n뷰(마스크) {len(views)}장, 초기 복셀 {len(centers):,}개 ({args.voxel * 1000:.1f}mm)")
    kept = carve(centers, views)
    print(f"카빙 완료: {len(kept):,}개 복셀 남음")
    if len(kept) == 0:
        raise RuntimeError("복셀이 모두 깎였습니다. 마스크(masks/)와 캘리브레이션을 확인하세요.")

    hull_pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(kept.astype(np.float64)))
    o3d.io.write_point_cloud(os.path.join(session, "visual_hull.ply"), hull_pcd)

    # 치수 비교 (보정계수는 두 방식에 똑같이 적용)
    hull_dims = measure_points(kept.astype(np.float64), scale=config.SCALE_CORRECTION)
    report = dict(voxel_m=args.voxel, n_voxels=int(len(kept)), n_views=len(views),
                  visual_hull={k: round(hull_dims[k], 2) for k in DIM_KEYS})
    merged_path = os.path.join(session, "merged_model.ply")
    merged = o3d.io.read_point_cloud(merged_path) if os.path.exists(merged_path) else None
    print("\n=== 치수 비교 (mm) ===")
    if merged is not None and len(merged.points):
        pc_dims = measure_points(np.asarray(merged.points), scale=config.SCALE_CORRECTION)
        report["point_cloud"] = {k: round(pc_dims[k], 2) for k in DIM_KEYS}
        print(f"  {'':10s} {'포인트클라우드':>12s} {'Visual Hull':>12s} {'차이':>8s}")
        for k in DIM_KEYS:
            print(f"  {DIM_KO[k]:10s} {pc_dims[k]:12.2f} {hull_dims[k]:12.2f} {hull_dims[k] - pc_dims[k]:+8.2f}")
    else:
        for k in DIM_KEYS:
            print(f"  {DIM_KO[k]:10s} {hull_dims[k]:8.2f}")
    print("  (Visual Hull은 실루엣의 교집합이라 오목한 곳을 메우므로 보통 같거나 약간 크게 나옵니다)")
    with open(os.path.join(session, "visual_hull.json"), "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)

    if args.no_view:
        return
    grid_pcd = o3d.geometry.PointCloud(hull_pcd)
    grid_pcd.paint_uniform_color((1.0, 0.55, 0.1))  # 주황 = Visual Hull
    if args.side_by_side and merged is not None:
        width = (hi[0] - lo[0]) + 0.03
        grid_pcd.translate((width, 0, 0))
    vg = o3d.geometry.VoxelGrid.create_from_point_cloud(grid_pcd, voxel_size=args.voxel)
    geoms = [vg, o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.03)]
    if merged is not None:
        geoms.insert(0, merged)  # 원래 색 = depth 포인트클라우드
    print("\n주황 복셀 = Visual Hull, 컬러 점 = depth 병합 모델. 창을 닫으면 종료합니다.")
    o3d.visualization.draw_geometries(geoms)


if __name__ == "__main__":
    main()
