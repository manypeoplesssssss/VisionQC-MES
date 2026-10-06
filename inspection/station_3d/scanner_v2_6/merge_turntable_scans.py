"""
merge_turntable_scans.py — 36뷰를 하나의 3D 모델로 병합

turntable_scan.py가 이미 각 뷰를 "턴테이블 좌표계, 0도 기준"으로 되돌려 저장하므로,
기본적으로는 합치기만 하면 됩니다. 구버전과 달라진 점:
    - 회전축을 캘리브레이션으로 알고, 각도도 스텝모터가 정확히 돌리므로
      "첫 뷰 물체 중심을 회전중심으로 근사 + 큰 거리 ICP"가 필요 없어졌다.
    - ICP는 선택적 미세 보정으로만 쓰고, 보정량이 비정상적으로 크면(오정합)
      버리고 캘리브레이션 자세를 그대로 쓴다. (ROTATION_SIGN 수동 조정도 불필요)
    - 결과는 턴테이블 좌표계(원판 윗면 = y 0)로 저장되어 measure가 바로 쓴다.

실행:
    python merge_turntable_scans.py                      # 가장 최근 세션
    python merge_turntable_scans.py scans/20261001_1030  # 세션 지정
    python merge_turntable_scans.py --no-icp --no-view
결과: <세션>/merged_model.ply
"""

import argparse
import glob
import json
import os

import numpy as np

import config


def latest_session():
    # views/ 폴더가 있는 진짜 스캔 세션만 (10-02: scans/_analysis_tmp 같은 다른 폴더가 이름순 맨 뒤로 와서
    # "최신 세션"으로 잘못 잡히던 문제 수정). 세션 이름이 날짜_시각으로 시작하므로 이름순 = 시간순.
    sessions = sorted(d for d in glob.glob(os.path.join(config.SCAN_ROOT, "*"))
                      if os.path.isdir(os.path.join(d, "views")))
    if not sessions:
        raise RuntimeError(f"'{config.SCAN_ROOT}'에 스캔 세션이 없습니다. turntable_scan.py를 먼저 실행하세요.")
    return sessions[-1]


def rotation_angle_deg(T):
    R = T[:3, :3]
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def icp_refine(o3d, source, target):
    """작은 거리 point-to-plane ICP. 보정량이 한도를 넘거나 fitness가 낮으면 None."""
    reg = o3d.pipelines.registration
    param = o3d.geometry.KDTreeSearchParamHybrid(radius=0.01, max_nn=30)
    source.estimate_normals(param)
    target.estimate_normals(param)
    r = reg.registration_icp(source, target, config.ICP_MAX_CORR_DIST_M, np.eye(4),
                             reg.TransformationEstimationPointToPlane())
    shift = float(np.linalg.norm(r.transformation[:3, 3]))
    ang = rotation_angle_deg(r.transformation)
    ok = (r.fitness >= config.ICP_MIN_FITNESS and shift <= config.ICP_MAX_CORRECTION_M
          and ang <= config.ICP_MAX_CORRECTION_DEG)
    return (r.transformation if ok else None), r.fitness, shift, ang


def multiview_support(view_points, query, vox):
    """query 각 점 주변(3×3×3 격자, 격자 크기 vox)에 점을 가진 뷰의 개수.
    진짜 표면은 여러 뷰가 함께 보지만, 깊이 경계 잡음은 시점마다 위치가 달라 적은 뷰만 가짐."""
    offs = np.array([(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)])

    def enc(k):
        k = k + (1 << 19)
        return (k[:, 0] << 40) | (k[:, 1] << 20) | k[:, 2]

    keys = []
    for pts in view_points:
        k = np.unique(np.floor(pts / vox).astype(np.int64), axis=0)
        keys.append(np.unique(enc((k[:, None, :] + offs[None]).reshape(-1, 3))))
    uk, cnt = np.unique(np.concatenate(keys), return_counts=True)
    q = enc(np.floor(query / vox).astype(np.int64))
    idx = np.clip(np.searchsorted(uk, q), 0, len(uk) - 1)
    return np.where(uk[idx] == q, cnt[idx], 0)


def clean_model(o3d, pcd):
    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=1.5)
    labels = np.array(pcd.cluster_dbscan(eps=0.008, min_points=8, print_progress=False))
    valid = labels[labels >= 0]
    if len(valid):
        pcd = pcd.select_by_index(np.where(labels == np.bincount(valid).argmax())[0])
    return pcd


def merge_session(session, use_icp=config.ICP_REFINE):
    import open3d as o3d
    files = sorted(glob.glob(os.path.join(session, "views", "view_*.ply")))
    if not files:
        raise RuntimeError(f"'{session}/views'에 뷰 파일이 없습니다.")
    merged = o3d.io.read_point_cloud(files[0])
    view_points = [np.asarray(merged.points).copy()]
    rejected = 0
    for f in files[1:]:
        pcd = o3d.io.read_point_cloud(f)
        note = ""
        if use_icp and len(pcd.points) > 100:
            T, fit, shift, ang = icp_refine(o3d, pcd, merged)
            if T is not None:
                pcd.transform(T)
                note = f"ICP 보정 {shift * 1000:.1f}mm/{ang:.2f}도 (fitness {fit:.2f})"
            else:
                rejected += 1
                note = f"ICP 결과 무시 (fitness {fit:.2f}, {shift * 1000:.1f}mm/{ang:.2f}도) → 캘리브레이션 자세 사용"
        view_points.append(np.asarray(pcd.points).copy())
        print(f"  {os.path.basename(f)}: {len(pcd.points):6d} 포인트  {note}")
        merged = (merged + pcd).voxel_down_sample(config.VOXEL_DOWNSAMPLE_M)
    if rejected > len(files) // 3:
        print(f"  [경고] {rejected}개 뷰의 ICP가 무시되었습니다. 캘리브레이션이 틀어졌을 수 있으니 "
              "calibrate_rig.py 검증을 권장합니다.")
    n0 = len(merged.points)
    if getattr(config, "MV_SUPPORT_FILTER", True) and len(view_points) >= 6:
        min_views = max(2, int(round(getattr(config, "MV_MIN_VIEW_FRAC", 0.12) * len(view_points))))
        sup = multiview_support(view_points, np.asarray(merged.points),
                                getattr(config, "MV_SUPPORT_VOXEL_M", 0.003))
        keep = np.where(sup >= min_views)[0]
        print(f"  다시점 지지 필터: {min_views}개 뷰 미만이 본 점 {n0 - len(keep)}개 제거 (P-32)")
        merged = merged.select_by_index(keep)
    n1 = len(merged.points)
    merged = clean_model(o3d, merged)
    print(f"병합 완료: {n0} → 지지 필터 {n1} → 정리 후 {len(merged.points)} 포인트")
    out = os.path.join(session, "merged_model.ply")
    o3d.io.write_point_cloud(out, merged)
    return out, merged


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", default=None)
    ap.add_argument("--no-icp", action="store_true")
    ap.add_argument("--no-view", action="store_true")
    args = ap.parse_args()

    session = args.session or latest_session()
    print(f"세션: {session}")
    out, merged = merge_session(session, use_icp=config.ICP_REFINE and not args.no_icp)
    print(f"'{out}'로 저장했습니다.")

    meta_path = os.path.join(session, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fp:
            meta = json.load(fp)
        meta["merged"] = dict(path="merged_model.ply", n_points=len(merged.points),
                              icp=config.ICP_REFINE and not args.no_icp)
        with open(meta_path, "w", encoding="utf-8") as fp:
            json.dump(meta, fp, ensure_ascii=False, indent=2)

    if not args.no_view:
        import open3d as o3d
        frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.03)  # 원판 중심, Y=위
        o3d.visualization.draw_geometries([merged, frame])


if __name__ == "__main__":
    main()
