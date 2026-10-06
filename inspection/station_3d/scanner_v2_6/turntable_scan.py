"""
turntable_scan.py — 아두이노 턴테이블 자동 36뷰 스캔

calibrate_rig.py로 만든 rig_calibration.npz를 사용합니다. 사람은 처음에 배경과
물체 배치만 확인하고, 이후 36뷰는 PC ↔ 아두이노 핸드셰이크로 자동 촬영됩니다.

    PC: R10 전송 → 아두이노: 10도 회전 + 400ms 대기 → DONE → PC: 촬영 → 반복

결과 (scans/<날짜_시간>[_이름]/):
    views/view_00_000deg.ply ...   각 뷰 포인트클라우드. 이미 "턴테이블 좌표계, 0도 기준"
                                   으로 되돌려 저장하므로 merge는 합치기만 하면 된다.
    images/view_00_000deg_camA.jpg  원본 컬러 (Visual Hull 확인·발표 자료용)
    masks/view_00_000deg_camA.png   실루엣 마스크 (Visual Hull 입력)
    meta.json                       각도, 카메라 내부 파라미터, 시리얼, 설정값
    rig_calibration.npz             이 스캔에 쓴 캘리브레이션 사본 (재현용)

실행:
    python turntable_scan.py                      # 자동 (아두이노 연결)
    python turntable_scan.py --name sample01      # 세션 이름 붙이기
    python turntable_scan.py --placement          # 스캔 전 레이저 놓임 검사 (물체가 중앙에 놓였는지, v2.6)
    python turntable_scan.py --manual             # 아두이노 없이 손으로 돌리기 (Space)
    python turntable_scan.py --alternate-emitter  # 두 카메라 IR 패턴 간섭이 보일 때

스캔 카메라 컬러 사진은 Visual Hull 확인·발표 자료용이며 결함 모델 학습에는 쓰지 않습니다.
PatchCore/YOLO 데이터 수집과 결함 검출은 결함진단 카메라(아이폰 14 Pro)로 따로 합니다.
"""

import argparse
import datetime as dt
import json
import os
import shutil

import cv2
import numpy as np

import config
import d435_common as dc
from rig import RigCalibration, roi_mask_tt


def make_session_dir(name=None):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(config.SCAN_ROOT, stamp + (f"_{name}" if name else ""))
    for sub in ("views", "images", "masks"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def clean_mask(mask):
    """depth 기반 전경 마스크 정리: 작은 점 제거 → 틈 메우기 → 내부 구멍 채우기.
    (어두운 면·반사면은 depth가 비어 구멍이 생기므로 외곽선 기준으로 채운다)"""
    m = mask.astype(np.uint8) * 255
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    k7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k3)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k7)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return m
    areas = [cv2.contourArea(c) for c in contours]
    big = max(areas)
    filled = np.zeros_like(m)
    for c, a in zip(contours, areas):
        if a >= 0.05 * big:           # 너무 작은 조각(노이즈)은 버림
            cv2.drawContours(filled, [c], -1, 255, thickness=cv2.FILLED)
    return filled


def process_view(frame, rig, theta, is_cam_b):
    """한 카메라 프레임 → (턴테이블 좌표 점, 색, 실루엣 마스크)."""
    pts = frame["verts"]
    if is_cam_b:
        pts = rig.b_to_a(pts)
    tt = rig.cam_a_to_tt(pts, theta)
    keep = frame["fg"] & roi_mask_tt(tt, config.ROI_RADIUS_M, config.ROI_HEIGHT_M,
                                     config.PLATE_MARGIN_M)
    mask = clean_mask(keep.reshape(frame["shape"]))       # 실루엣(Visual Hull)은 경계 포함
    if getattr(config, "DEPTH_EDGE_FILTER", True) and "edge" in frame:
        keep = keep & ~frame["edge"]                         # 점에서는 깊이 경계 제외 (P-32)
    return tt[keep], frame["colors"][keep].astype(np.float64), mask


def ensure_placed(tt):
    """놓임 검사(레이저)가 OK일 때까지 반복. 통과해야 스캔을 시작한다.
    시나리오: 로봇팔이 물체를 놓음 → 놓임 검사 OK → 3D 스캔 시작.
    반환: {"ok": True, "attempts": n, "errors": [코드...]} (meta.json에 기록)"""
    from turntable import PLACEMENT_MESSAGES
    errors = []
    while True:
        ok, code = tt.check_placement()
        if ok:
            print("   놓임 검사 OK → 스캔을 시작합니다.")
            return dict(ok=True, attempts=len(errors) + 1, errors=errors)
        errors.append(code)
        print(f"   [놓임 불량] {code}: {PLACEMENT_MESSAGES.get(code, '')}")
        ans = input("   물체를 다시 놓은 뒤 Enter (q=중단): ").strip().lower()
        if ans == "q":
            raise RuntimeError("놓임 검사 통과 전에 사용자가 스캔을 중단했습니다.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=None, help="세션 폴더 이름 뒤에 붙일 이름 (예: sample01)")
    ap.add_argument("--views", type=int, default=config.N_VIEWS)
    ap.add_argument("--manual", action="store_true", help="아두이노 없이 손으로 돌리기")
    ap.add_argument("--placement", action="store_true",
                    default=getattr(config, "PLACEMENT_CHECK", False),
                    help="스캔 시작 전 레이저 놓임 검사 (펌웨어 v2.6 필요). config.PLACEMENT_CHECK로 기본값 설정")
    ap.add_argument("--alternate-emitter", action="store_true",
                    help="촬영 시 한 대씩 IR 프로젝터를 꺼 패턴 간섭 방지 (느려짐)")
    args = ap.parse_args()

    import open3d as o3d

    if not os.path.exists(config.RIG_CALIB_PATH):
        raise RuntimeError(f"'{config.RIG_CALIB_PATH}'가 없습니다. 먼저 python calibrate_rig.py 를 실행하세요.")
    rig = RigCalibration.load(config.RIG_CALIB_PATH)
    step = 360.0 / args.views

    cam_a, cam_b = dc.open_scan_cams()
    tt = None
    try:
        if str(rig.info.get("serial_a", cam_a.serial)) != cam_a.serial or \
                str(rig.info.get("serial_b", cam_b.serial)) != cam_b.serial:
            raise RuntimeError("캘리브레이션 때와 카메라 A/B 시리얼이 다릅니다. config.py 시리얼 설정을 "
                               "확인하거나 calibrate_rig.py --recalibrate 를 실행하세요.")

        if not args.manual:
            from turntable import Turntable
            tt = Turntable()

        session = make_session_dir(args.name)
        shutil.copy(config.RIG_CALIB_PATH, os.path.join(session, "rig_calibration.npz"))
        print(f"세션 폴더: {session}")

        dc.preview_and_wait([cam_a, cam_b],
                            "\n1) 턴테이블을 비우고 펜 마킹을 0도에 맞추세요. 준비되면 Space (배경 촬영).")
        if tt:
            tt.zero()
        bg_a, bg_b = dc.capture_background_pair(cam_a, cam_b, args.alternate_emitter)
        print("   배경 촬영 완료.")
        if tt and args.placement:
            print("   놓임 검사 보정 중 (빔 사이가 비어 있어야 합니다)...")
            tt.calibrate_placement()

        dc.preview_and_wait([cam_a, cam_b],
                            "\n2) 물체를 턴테이블 중앙에 올리세요(자석 고정). Space를 누르면 자동 스캔 시작.")
        placement_result = None
        if tt and args.placement:
            placement_result = ensure_placed(tt)
        if tt:
            tt.take_up_backlash()   # 물체를 올리며 원판이 밀렸어도 첫 회전 각도가 정확하도록 (P-31)

        records = []
        for i in range(args.views):
            theta = i * step
            if i > 0:
                if tt:
                    tt.rotate(step)
                else:
                    dc.preview_and_wait([cam_a, cam_b], f"   턴테이블을 {theta:.0f}도로 돌리고 Space.")
            fa, fb = dc.capture_pair(cam_a, cam_b, bg_a, bg_b, args.alternate_emitter)

            stem = f"view_{i:02d}_{theta:03.0f}deg"
            clouds = []
            for f, label, is_b in ((fa, "A", False), (fb, "B", True)):
                pts, cols, mask = process_view(f, rig, theta, is_b)
                cv2.imwrite(os.path.join(session, "images", f"{stem}_cam{label}.jpg"), f["color"],
                            [cv2.IMWRITE_JPEG_QUALITY, config.IMAGE_JPEG_QUALITY])
                cv2.imwrite(os.path.join(session, "masks", f"{stem}_cam{label}.png"), mask)
                pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
                pc.colors = o3d.utility.Vector3dVector(cols)
                clouds.append(pc)
            view = (clouds[0] + clouds[1]).voxel_down_sample(config.VOXEL_DOWNSAMPLE_M)
            o3d.io.write_point_cloud(os.path.join(session, "views", stem + ".ply"), view)
            records.append(dict(index=i, theta_deg=theta, stem=stem,
                                n_points_a=len(clouds[0].points), n_points_b=len(clouds[1].points)))
            print(f"  {i + 1:2d}/{args.views}  {theta:5.1f}도  A={len(clouds[0].points):6d}  "
                  f"B={len(clouds[1].points):6d}  → {len(view.points)} 포인트")
            if len(clouds[0].points) + len(clouds[1].points) < 500:
                print("     [경고] 점이 너무 적습니다. ROI 반경/높이나 물체 위치를 확인하세요.")

        if tt:
            tt.finish_turn()   # 정방향으로 360도를 채우고 0도로 리셋

        meta = dict(
            created=dt.datetime.now().isoformat(timespec="seconds"),
            views=records, angle_step_deg=step, manual=args.manual,
            alternate_emitter=args.alternate_emitter,
            interlock_events=(tt.interlock_events if tt else 0),
            placement_check=placement_result,
            cameras=dict(A=dict(serial=cam_a.serial, intrinsics=cam_a.intr),
                         B=dict(serial=cam_b.serial, intrinsics=cam_b.intr)),
            roi=dict(radius_m=config.ROI_RADIUS_M, height_m=config.ROI_HEIGHT_M,
                     plate_margin_m=config.PLATE_MARGIN_M),
        )
        with open(os.path.join(session, "meta.json"), "w", encoding="utf-8") as fp:
            json.dump(meta, fp, ensure_ascii=False, indent=2)
        print(f"\n스캔 완료: {session}")
        print("다음: python merge_turntable_scans.py → python measure_object.py")
    finally:
        if tt:
            tt.close()
        cam_a.stop()
        cam_b.stop()


if __name__ == "__main__":
    main()
