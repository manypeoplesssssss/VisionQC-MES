"""
calibrate_rig.py — 스캔 리그 캘리브레이션

세 가지를 차례로 구해 rig_calibration.npz 로 저장합니다.
    [1/3] 카메라 B → A 상대위치 (R, t)
          체커보드를 두 카메라가 동시에 보는 곳에 여러 자세(권장 6~8)로 두고 찍는다.
          자세마다 코너 3D 좌표(depth, 5프레임 중앙값)를 모아 한꺼번에 Kabsch로 계산.
          코너 순서 뒤집힘은 자동 보정, 오차 큰 자세는 자동 제외.
    [2/3] 턴테이블 회전축 (방향 + 위치)
          체커보드를 턴테이블 위에 세워 두고 아두이노로 0/10/20/30/40도 돌려가며
          카메라 A로 보드 자세를 잰다(PnP). 코너들이 그리는 원호로 축을 구한다.
    [3/3] 원판 윗면 높이 (= 높이 0의 기준)
          빈 턴테이블을 찍어 회전축 근처 원판 윗면 위치를 잰다.

실행:
    python calibrate_rig.py                 # 저장값이 있으면 체커보드 1자세로 검증만, 틀어졌으면 재측정
    python calibrate_rig.py --recalibrate   # 카메라/턴테이블을 옮겼을 때: 전부 새로 측정
    python calibrate_rig.py --axis-only     # 카메라 간 정합은 두고 회전축·원판만 다시 측정
    python calibrate_rig.py --check         # 저장값으로 물체 한 컷을 찍어 두 카메라 정합을 눈으로 확인
    python calibrate_rig.py --manual        # 아두이노 없이 손으로 각도를 맞춰 축 측정
"""

import argparse
import os

import numpy as np

import config
import d435_common as dc
from rig import (RigCalibration, estimate_ab_multi, estimate_plate_height, grid_square_size,
                 estimate_turntable_axis, make_basis,
                 rigid_rmse, roi_mask_tt)

PLATE_SAMPLE_RADIUS_M = 0.05   # 원판 높이를 잴 때 쓰는 축 주변 반경


# ---------------------------------------------------------------------------
# [1/3] 카메라 간 정합
# ---------------------------------------------------------------------------
def capture_board_pair(cam_a, cam_b):
    pa = dc.checkerboard_3d_depth(cam_a)
    pb = dc.checkerboard_3d_depth(cam_b)
    return pa, pb


SQUARE_CHECK_TOL = 0.08   # depth로 잰 칸 크기가 config와 8% 넘게 다르면 중단


def check_square_size(depth_boards):
    """depth로 구한 체커보드 코너들로 한 칸 크기를 재서 config.SQUARE_SIZE_M과 비교.
    (10-01 실기에서 20mm 보드에 0.015가 남아 회전축 위치가 약 8cm 틀어진 문제 재발 방지)
    PnP(회전축 측정)는 칸 크기를 그대로 믿으므로 값이 틀리면 축 위치가 같은 비율로 틀어진다."""
    sizes = [grid_square_size(p, config.CHECKERBOARD) for p in depth_boards if p is not None]
    if not sizes:
        return
    meas = float(np.median(sizes))
    cfg = config.SQUARE_SIZE_M
    print(f"  체커보드 한 칸: depth 실측 {meas * 1000:.1f} mm / config.SQUARE_SIZE_M {cfg * 1000:.1f} mm")
    if abs(meas - cfg) / cfg > SQUARE_CHECK_TOL:
        raise RuntimeError(
            f"config.SQUARE_SIZE_M({cfg * 1000:.1f}mm)이 실제 보드 칸 크기(depth 실측 약 {meas * 1000:.1f}mm)와 "
            "다릅니다. 보드를 캘리퍼스로 8칸 재서 ÷8 한 값을 config.py에 넣고 다시 실행하세요.")


def calibrate_ab(cam_a, cam_b):
    print("\n[1/3] 카메라 간 정합")
    print("  체커보드를 턴테이블 위(차가 놓일 자리)에 두 카메라가 모두 보도록 세워 두세요.")
    print(f"  자세를 바꿔가며 Space로 한 장씩 찍습니다 (최소 {config.AB_MIN_POSES}, 권장 6~8).")
    print("  예: 중앙 → 좌/우 3~5cm → 앞/뒤 3~5cm → 3~5cm 높여서 → 15~20도 돌려서/눕혀서")
    print("  다 찍었으면 F 를 누르세요. 보드는 손으로 들지 말고 받침에 세워 완전히 멈춘 상태로.")
    poses_a, poses_b = [], []
    while True:
        key = dc.preview_and_wait(
            [cam_a, cam_b],
            f"  현재 {len(poses_a)}자세. 두 창 모두 FOUND면 Space(촬영) / F(완료) / Esc(중단)",
            show_checkerboard=True, extra_keys="f")
        if key == "f":
            if len(poses_a) >= config.AB_MIN_POSES:
                break
            print(f"  아직 {len(poses_a)}자세입니다. 최소 {config.AB_MIN_POSES}자세가 필요합니다.")
            continue
        pa, pb = capture_board_pair(cam_a, cam_b)
        if pa is None or pb is None:
            print("  ✗ 이 자세는 인식 실패 (보드가 한쪽 화면에서 잘렸거나 반사가 있음). 다시 놓고 찍으세요.")
            continue
        poses_a.append(pa)
        poses_b.append(pb)
        print(f"  ✓ {len(poses_a)}번째 자세 저장 (보드까지 거리 A {pa[:, 2].mean() * 100:.0f}cm, "
              f"B {pb[:, 2].mean() * 100:.0f}cm)")

    # 카메라별 칸 크기(depth 스케일) 비교: 두 카메라 depth 스케일이 다르면 강체 정합으로는
    # 맞출 수 없어 자세별 오차가 고르게 커진다(10-01 RMSE 3.2mm 진단용)
    sa = np.median([grid_square_size(p, config.CHECKERBOARD) for p in poses_a])
    sb = np.median([grid_square_size(p, config.CHECKERBOARD) for p in poses_b])
    print(f"  카메라별 칸 크기(depth): A {sa * 1000:.2f} mm / B {sb * 1000:.2f} mm "
          f"(차이 {abs(sa - sb) / max(sa, sb) * 100:.1f}%, 1% 넘으면 depth 스케일 차이 의심)")
    check_square_size(poses_a + poses_b)
    res = estimate_ab_multi(poses_a, poses_b, reject_m=config.AB_POSE_REJECT_M,
                            min_poses=config.AB_MIN_POSES - 1)
    print("\n  자세별 오차:")
    for i, (e, u, f) in enumerate(zip(res["pose_rmse_m"], res["used"], res["flipped"])):
        note = ("" if u else "  ← 제외됨") + ("  (코너 순서 뒤집힘 보정)" if f else "")
        print(f"    {i + 1}: {e * 1000:5.2f} mm{note}")
    print(f"  전체 오차(RMSE): {res['rmse_m'] * 1000:.2f} mm "
          f"(2~3mm 이내 양호, 5mm 초과면 다시)  / 두 카메라 사이 각도 {res['rotation_deg']:.1f}도")
    if res["rmse_m"] > config.AB_POSE_REJECT_M:
        raise RuntimeError("카메라 간 정합 오차가 큽니다. 보드를 단단히 고정하고 조명 반사를 없앤 뒤 다시 하세요.")
    return res["R"], res["t"], res["rmse_m"], sum(res["used"])


def verify_ab(cam_a, cam_b, R, t):
    dc.preview_and_wait(
        [cam_a, cam_b],
        "\n저장된 카메라 간 정합을 검증합니다: 체커보드를 두 카메라가 모두 보게 두고 Space.",
        show_checkerboard=True)
    pa, pb = capture_board_pair(cam_a, cam_b)
    if pa is None or pb is None:
        print("  체커보드 인식 실패 → 안전하게 재캘리브레이션합니다.")
        return False
    rmse = min(rigid_rmse(R, t, pb, pa), rigid_rmse(R, t, pb[::-1], pa))  # 순서 뒤집힘 허용
    print(f"  검증 오차: {rmse * 1000:.2f} mm (기준 {config.EXTRINSICS_RMSE_WARN_M * 1000:.0f} mm)")
    return rmse <= config.EXTRINSICS_RMSE_WARN_M


# ---------------------------------------------------------------------------
# [2/3] 회전축
# ---------------------------------------------------------------------------
def calibrate_axis(cam_a, manual=False):
    angles = list(config.AXIS_CALIB_ANGLES_DEG)
    span = angles[-1] - angles[0]
    tt = None
    if not manual:
        from turntable import Turntable
        tt = Turntable()
    try:
        dc.preview_and_wait(
            [cam_a],
            "\n[2/3] 회전축 측정 (카메라 A만 사용)\n"
            "  체커보드를 받침에 붙여 턴테이블 위에 단단히 고정하세요(뒤로 20~30도 눕히면 잘 보임).\n"
            f"  보드를 원판 위에서 돌려, 카메라 A 정면에서 '회전 방향 반대쪽'으로 약 {span / 2:.0f}도 비껴 있게\n"
            f"  놓으면 {angles[0]}→{angles[-1]}도 도는 동안 계속 보입니다. (원판 자체를 손으로 거꾸로 돌리면\n"
            "  기어 유격이 생기고 기어에도 무리가 갑니다. Space 뒤 자동으로 유격을 없애지만 가급적 보드를 돌리세요.)\n"
            "  FOUND가 뜨면 Space.",
            show_checkerboard=True)
        if tt:
            # 보드를 놓다가 원판을 손으로 돌렸어도 첫 회전이 정확하도록 측정 직전에 유격 제거 (P-31)
            tt.take_up_backlash()
        check_square_size([dc.checkerboard_3d_depth(cam_a)])   # --axis-only 실행 때도 칸 크기 검증
        boards = []
        for i, ang in enumerate(angles):
            if i > 0:
                if tt:
                    tt.rotate(ang - angles[i - 1])
                else:
                    dc.preview_and_wait([cam_a], f"  턴테이블을 {ang}도로 돌리고 Space.", True)
            pts = dc.checkerboard_3d_pnp(cam_a)
            if pts is None:
                raise RuntimeError(f"{ang}도에서 체커보드를 찾지 못했습니다. 보드 방향을 조정해 다시 하세요.")
            boards.append(pts)
            print(f"  {ang:5.1f}도 촬영 완료")
        if tt:
            tt.finish_turn()  # 정방향으로 한 바퀴 채워 0도로 복귀
    finally:
        if tt:
            tt.close()

    res = estimate_turntable_axis(boards, angles)
    tilt = np.degrees(np.arccos(abs(res["axis"] @ np.array([0, 1.0, 0]))))
    print("  명령 각도 vs 실측 각도:")
    for c, m in zip(res["commanded_deg"], res["measured_deg"]):
        print(f"    {c:6.1f}도 → {m:6.2f}도 (차이 {m - c:+.2f}, 기준 ±0.5)")
    print(f"  회전축과 카메라 A 세로축 사이 각도: {tilt:.1f}도 (카메라를 내려다보게 기울인 만큼)")
    print(f"  축 모델 잔차: {res['rmse_m'] * 1000:.2f} mm (기준 3mm 이내)")
    if res["rmse_m"] > 0.003:
        print("  [경고] 잔차가 3mm를 넘습니다. 보드가 흔들렸거나 미끄러졌을 수 있습니다. 다시 하세요.")
    return res, boards[0]


# ---------------------------------------------------------------------------
# [3/3] 원판 높이
# ---------------------------------------------------------------------------
def calibrate_plate(cam_a, cam_b, R_ab, t_ab, axis, point, board0):
    dc.preview_and_wait(
        [cam_a, cam_b],
        "\n[3/3] 원판 높이 측정: 체커보드와 받침을 치우고 턴테이블을 완전히 비운 뒤 Space.")
    bg_a, bg_b = dc.capture_background_pair(cam_a, cam_b)
    from rig import deproject_depth
    pa = deproject_depth(bg_a, cam_a.intr)
    pb = deproject_depth(bg_b, cam_b.intr)
    pts = np.vstack([pa[pa[:, 2] > 0], ((R_ab @ pb[pb[:, 2] > 0].T).T + t_ab)])
    s_plate, n = estimate_plate_height(pts, axis, point, PLATE_SAMPLE_RADIUS_M)
    if s_plate is None or n < 200:
        raise RuntimeError(
            f"원판 윗면 점이 부족합니다({n}개). 카메라가 원판 윗면을 볼 수 있게 내려다보는지 확인하세요.")
    s_board = float(np.median((board0 - point) @ axis))   # 위쪽 = 보드가 있던 쪽
    up = axis if s_board > s_plate else -axis
    origin = point + s_plate * axis
    print(f"  원판 윗면 점 {n}개로 높이 0 기준 결정 완료")
    return origin, up


# ---------------------------------------------------------------------------
def check_capture(cam_a, cam_b, rig):
    """저장값 확인: 물체 한 컷을 두 카메라로 찍어 턴테이블 좌표로 합쳐 본다."""
    import open3d as o3d
    dc.preview_and_wait([cam_a, cam_b], "\n[확인] 턴테이블을 비우고 Space (배경 촬영).")
    bg_a, bg_b = dc.capture_background_pair(cam_a, cam_b)
    dc.preview_and_wait([cam_a, cam_b], "물체를 올려두고 Space.")
    fa, fb = dc.capture_pair(cam_a, cam_b, bg_a, bg_b)
    clouds = []
    for f, is_b, color in ((fa, False, (1, 0.4, 0.2)), (fb, True, (0.2, 0.6, 1))):
        pts = f["verts"]
        if is_b:
            pts = rig.b_to_a(pts)
        tt = rig.cam_a_to_tt(pts, 0.0)
        keep = f["fg"] & roi_mask_tt(tt, config.ROI_RADIUS_M, config.ROI_HEIGHT_M, config.PLATE_MARGIN_M)
        pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(tt[keep]))
        pc.paint_uniform_color(color)
        clouds.append(pc.voxel_down_sample(config.VOXEL_DOWNSAMPLE_M))
        print(f"  카메라 {'B' if is_b else 'A'}: {keep.sum()} 포인트")
    print("주황=카메라 A, 파랑=카메라 B. 두 색이 한 형상으로 겹치면 정합 성공입니다.")
    o3d.visualization.draw_geometries(clouds + [o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.05)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recalibrate", action="store_true", help="저장값 무시하고 전부 새로 측정")
    ap.add_argument("--axis-only", action="store_true", help="회전축·원판만 다시 측정")
    ap.add_argument("--check", action="store_true", help="저장값으로 물체 한 컷 정합 확인")
    ap.add_argument("--manual", action="store_true", help="아두이노 없이 손으로 돌려 축 측정")
    args = ap.parse_args()

    cam_a, cam_b = dc.open_scan_cams()
    try:
        saved = None
        if os.path.exists(config.RIG_CALIB_PATH) and not args.recalibrate:
            saved = RigCalibration.load(config.RIG_CALIB_PATH)

        if args.check:
            if saved is None:
                raise RuntimeError("저장된 리그 캘리브레이션이 없습니다. 먼저 캘리브레이션하세요.")
            check_capture(cam_a, cam_b, saved)
            return

        n_poses = None
        if saved is not None and (args.axis_only or verify_ab(cam_a, cam_b, saved.R_ab, saved.t_ab)):
            R_ab, t_ab = saved.R_ab, saved.t_ab
            ab_rmse = float(saved.info.get("ab_rmse_m", np.nan))
            n_poses = saved.info.get("ab_poses")
            if not args.axis_only:
                print("  카메라 간 정합 검증 통과. 회전축·원판도 저장값을 그대로 씁니다.")
                print("  (턴테이블을 옮겼다면 --axis-only, 카메라를 옮겼다면 --recalibrate)")
                return
        else:
            R_ab, t_ab, ab_rmse, n_poses = calibrate_ab(cam_a, cam_b)

        res, board0 = calibrate_axis(cam_a, manual=args.manual)
        origin, up = calibrate_plate(cam_a, cam_b, R_ab, t_ab, res["axis"], res["point"], board0)

        rig = RigCalibration(
            R_ab, t_ab, res["axis"], origin, make_basis(up),
            info=dict(ab_rmse_m=ab_rmse, ab_poses=n_poses, axis_rmse_m=res["rmse_m"],
                      commanded_deg=res["commanded_deg"], measured_deg=res["measured_deg"],
                      serial_a=cam_a.serial, serial_b=cam_b.serial,
                      square_size_m=config.SQUARE_SIZE_M,
                      color_res=list(config.COLOR_RES), depth_res=list(config.DEPTH_RES)))
        rig.save(config.RIG_CALIB_PATH)
        print(f"\n리그 캘리브레이션을 '{config.RIG_CALIB_PATH}'에 저장했습니다.")
        print("다음: python calibrate_rig.py --check 로 정합을 눈으로 확인 → turntable_scan.py")
    finally:
        cam_a.stop()
        cam_b.stop()


if __name__ == "__main__":
    main()
