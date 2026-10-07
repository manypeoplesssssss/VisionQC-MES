"""
d435_common.py — RealSense D435(스캔용 2대) 공통 함수 모음

단독 실행 시 연결된 카메라 목록(시리얼, USB 연결 규격)을 보여줍니다:
    python d435_common.py
USB 타입이 3.x 가 아니면 케이블/포트를 바꾸세요.

해상도: 컬러 config.COLOR_RES(1920x1080), depth config.DEPTH_RES(848x480).
depth는 컬러 화면에 맞춰 정렬(align)해서 쓰므로, 모든 계산은 컬러 좌표계와
컬러 내부 파라미터 기준이다.
"""

import os
import time

import cv2
import numpy as np
import pyrealsense2 as rs

import config
from rig import deproject_depth


# ---------------------------------------------------------------------------
# 장치
# ---------------------------------------------------------------------------
def list_devices():
    out = []
    for d in rs.context().query_devices():
        info = lambda k: d.get_info(k) if d.supports(k) else "?"
        out.append(dict(
            serial=info(rs.camera_info.serial_number),
            name=info(rs.camera_info.name),
            usb=info(rs.camera_info.usb_type_descriptor),
            firmware=info(rs.camera_info.firmware_version),
        ))
    return out


def _print_devices(devs):
    print("연결된 RealSense 카메라:")
    for d in devs:
        warn = "" if str(d["usb"]).startswith("3") else "   <-- USB 3.x 아님! 케이블/포트 확인"
        print(f"  시리얼 {d['serial']}  {d['name']}  USB {d['usb']}  FW {d['firmware']}{warn}")
    if not devs:
        print("  (없음)")


def _saved_rig_serials():
    """이전 캘리브레이션 때 저장된 A/B 시리얼 (있으면)."""
    if not os.path.exists(config.RIG_CALIB_PATH):
        return None, None
    try:
        from rig import RigCalibration
        info = RigCalibration.load(config.RIG_CALIB_PATH).info
        return info.get("serial_a"), info.get("serial_b")
    except Exception:
        return None, None


def resolve_scan_serials():
    """스캔 카메라 A/B 시리얼을 정한다.
    우선순위: config 지정값 → 저장된 캘리브레이션의 시리얼 → 연결 순서(2대일 때만)."""
    devs = list_devices()
    serials = [d["serial"] for d in devs]
    a, b = config.CAM_A_SERIAL, config.CAM_B_SERIAL
    source = "config.py"
    if not (a and b):
        sa, sb = _saved_rig_serials()
        if sa and sb and sa in serials and sb in serials:
            a, b, source = sa, sb, "저장된 캘리브레이션"
    if not (a and b):
        if len(serials) != 2:
            _print_devices(devs)
            raise RuntimeError(f"D435가 2대 연결되어야 합니다 (현재 {len(serials)}대).")
        a, b, source = serials[0], serials[1], "연결 순서"
        print("[주의] config.py에 시리얼이 없어 연결 순서로 A/B를 정했습니다. "
              f"A={a}, B={b}. 어느 쪽이 A인지 화면 제목으로 확인하고, "
              "가능하면 config.py에 CAM_A_SERIAL / CAM_B_SERIAL을 적어 두세요.")
    for s, role in ((a, "A"), (b, "B")):
        if s not in serials:
            _print_devices(devs)
            raise RuntimeError(f"카메라 {role}({s})가 연결되어 있지 않습니다.")
    print(f"스캔 카메라: A={a}, B={b} ({source})")
    return a, b


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------
def start_pipeline(serial, color_res=config.COLOR_RES, depth_res=config.DEPTH_RES,
                   fps=config.SCAN_FPS, max_retries=3):
    """카메라 시작. USB 초기화 타이밍 문제로 실패하면 정리 후 재시도한다."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        pipeline = rs.pipeline()
        cfg = rs.config()
        cfg.enable_device(serial)
        cfg.enable_stream(rs.stream.color, color_res[0], color_res[1], rs.format.bgr8, fps)
        cfg.enable_stream(rs.stream.depth, depth_res[0], depth_res[1], rs.format.z16, fps)
        try:
            profile = pipeline.start(cfg)
            align = rs.align(rs.stream.color)
            for _ in range(15):  # 노출/화이트밸런스 안정화
                pipeline.wait_for_frames(timeout_ms=5000)
            return pipeline, align, profile
        except RuntimeError as e:
            last_err = e
            print(f"카메라({serial}) 시작 {attempt}/{max_retries}회차 실패: {e}")
            try:
                pipeline.stop()
            except RuntimeError:
                pass
            time.sleep(2)
    raise RuntimeError(
        f"카메라({serial})를 시작하지 못했습니다: {last_err}\n"
        f"  컬러 {color_res}, depth {depth_res}, {fps}fps 조합을 지원하는지, USB 3.x로 연결됐는지 확인하세요.")


class Cam:
    """스캔 카메라 한 대."""

    def __init__(self, role, serial):
        self.role = role
        self.serial = serial
        self.pipe, self.align, self.profile = start_pipeline(serial)
        self.intr = get_intrinsics(self.profile)
        self.depth_scale = get_depth_scale(self.profile)

    def stop(self):
        try:
            self.pipe.stop()
        except RuntimeError:
            pass

    def frames(self):
        """depth를 컬러에 정렬한 (color_frame, depth_frame)."""
        return get_aligned_frames(self.pipe, self.align)

    def color(self):
        """컬러 이미지만 (정렬 계산 생략 → 빠름)."""
        f = self.pipe.wait_for_frames()
        return np.asanyarray(f.get_color_frame().get_data()).copy()

    def set_emitter(self, on):
        sensor = self.profile.get_device().first_depth_sensor()
        if sensor.supports(rs.option.emitter_enabled):
            sensor.set_option(rs.option.emitter_enabled, 1 if on else 0)


def open_scan_cams():
    a, b = resolve_scan_serials()
    cam_a = Cam("A", a)
    time.sleep(1.5)  # 동시 초기화 시 USB 충돌 방지
    cam_b = Cam("B", b)
    return cam_a, cam_b


def get_aligned_frames(pipeline, align):
    frames = pipeline.wait_for_frames()
    aligned = align.process(frames)
    return aligned.get_color_frame(), aligned.get_depth_frame()


def get_intrinsics(profile):
    """컬러 스트림 내부 파라미터를 dict로 (json 저장 가능)."""
    i = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    return dict(width=i.width, height=i.height, fx=i.fx, fy=i.fy, ppx=i.ppx, ppy=i.ppy,
                coeffs=list(i.coeffs), model=str(i.model))


def get_depth_scale(profile):
    return profile.get_device().first_depth_sensor().get_depth_scale()


def K_matrix(intr):
    return np.array([[intr["fx"], 0, intr["ppx"]], [0, intr["fy"], intr["ppy"]], [0, 0, 1]])


# ---------------------------------------------------------------------------
# depth 캡처 / 배경 차분
# ---------------------------------------------------------------------------
def capture_median_depth_m(cam, n_frames):
    """n_frames장의 (컬러에 정렬된) depth 픽셀별 중앙값(m). 0(무효)은 제외."""
    stack = []
    for _ in range(n_frames):
        _, df = cam.frames()
        stack.append(np.asanyarray(df.get_data()).astype(np.float32))
    arr = np.stack(stack, axis=0)
    arr[arr == 0] = np.nan
    with np.errstate(all="ignore"):
        med = np.nanmedian(arr, axis=0)
    return np.nan_to_num(med, nan=0.0) * cam.depth_scale


def depth_edge_mask(depth_m, kernel_px=None, jump_m=None):
    """깊이 경계(물체 윤곽 뒤로 배경이 보이는 곳) 픽셀 마스크 (H,W) bool.
    kernel_px×kernel_px 이웃의 depth 최댓값−최솟값이 jump_m를 넘으면 경계로 본다.
    D435는 이런 경계에서 앞뒤 거리를 섞은 '날아다니는 점'을 만들어 물체 끝에 회색
    커튼이 붙는다(10-01 자동차 스캔 P-32). 빈 depth(0) 옆 픽셀도 경계로 처리."""
    kernel_px = kernel_px or getattr(config, "DEPTH_EDGE_KERNEL_PX", 7)
    jump_m = jump_m or getattr(config, "DEPTH_EDGE_JUMP_M", 0.010)
    z = depth_m.astype(np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_px, kernel_px))
    zmax = cv2.dilate(z, k)
    zmin = cv2.erode(np.where(z > 0, z, 1e3).astype(np.float32), k)
    return (zmax - zmin) > jump_m


def capture_frame(cam, bg_depth_m=None, n_frames=config.OBJ_FRAMES):
    """물체 한 컷. 반환 dict:
        verts  (H*W,3)  카메라 좌표 점 (픽셀 순서, 중앙값 depth로 계산)
        colors (H*W,3)  RGB 0~1
        color  (H,W,3)  BGR 원본 컬러 이미지 (마스크 적용 전)
        valid  (H*W,)   depth 유효 & MAX_DISTANCE 이내
        fg     (H*W,)   배경보다 BG_MARGIN_M 이상 가까운 픽셀 (bg 없으면 valid와 같음)
        edge   (H*W,)   깊이 경계 픽셀 (점 저장에서 제외, 실루엣 마스크에는 사용)
    배경에 depth가 없던 픽셀에 물체가 들어오면 전경으로 인정한다."""
    depth_m = capture_median_depth_m(cam, n_frames)
    color = cam.color()
    verts = deproject_depth(depth_m, cam.intr)
    colors = color.reshape(-1, 3)[:, ::-1].astype(np.float32) / 255.0
    cur = depth_m.reshape(-1)
    valid = (cur > 0) & (cur < config.MAX_DISTANCE_M)
    if bg_depth_m is None:
        fg = valid.copy()
    else:
        bg = bg_depth_m.reshape(-1)
        fg = valid & ((bg <= 0) | ((bg - cur) > config.BG_MARGIN_M))
    edge = depth_edge_mask(depth_m).reshape(-1)
    return dict(verts=verts, colors=colors, color=color, valid=valid, fg=fg, edge=edge,
                shape=depth_m.shape)


def capture_pair(cam_a, cam_b, bg_a=None, bg_b=None, alternate_emitter=False):
    """두 카메라로 한 컷씩. alternate_emitter=True면 한 대씩 IR 프로젝터를 꺼서
    패턴 간섭을 피한다."""
    if not alternate_emitter:
        return capture_frame(cam_a, bg_a), capture_frame(cam_b, bg_b)
    cam_b.set_emitter(False)
    time.sleep(0.3)
    fa = capture_frame(cam_a, bg_a)
    cam_b.set_emitter(True)
    cam_a.set_emitter(False)
    time.sleep(0.3)
    fb = capture_frame(cam_b, bg_b)
    cam_a.set_emitter(True)
    return fa, fb


def capture_background_pair(cam_a, cam_b, alternate_emitter=False):
    if not alternate_emitter:
        return (capture_median_depth_m(cam_a, config.BG_FRAMES),
                capture_median_depth_m(cam_b, config.BG_FRAMES))
    cam_b.set_emitter(False)
    time.sleep(0.3)
    bg_a = capture_median_depth_m(cam_a, config.BG_FRAMES)
    cam_b.set_emitter(True)
    cam_a.set_emitter(False)
    time.sleep(0.3)
    bg_b = capture_median_depth_m(cam_b, config.BG_FRAMES)
    cam_a.set_emitter(True)
    return bg_a, bg_b


# ---------------------------------------------------------------------------
# 체커보드
# ---------------------------------------------------------------------------
def detect_checkerboard(img_bgr, fast=False):
    """코너 (N,1,2) 또는 None. fast=True는 미리보기용(서브픽셀 생략)."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    if fast:
        flags |= cv2.CALIB_CB_FAST_CHECK
    found, corners = cv2.findChessboardCorners(gray, config.CHECKERBOARD, flags=flags)
    if not found:
        return None
    if fast:
        return corners
    return cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1),
                            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))


def _corner_depth_points(cam, corners, df):
    pts = []
    for x, y in corners.reshape(-1, 2):
        d = df.get_distance(int(round(x)), int(round(y)))
        if d == 0:
            return None
        pts.append(((x - cam.intr["ppx"]) / cam.intr["fx"] * d,
                    (y - cam.intr["ppy"]) / cam.intr["fy"] * d, d))
    return np.array(pts)


def checkerboard_3d_depth(cam, n_frames=config.AB_FRAMES_PER_POSE, tries=40):
    """체커보드 코너 3D 좌표를 depth로 구한다(카메라 간 정합용).
    n_frames장의 결과를 코너별 중앙값으로 합쳐 depth 노이즈를 줄인다.
    코너 하나라도 depth가 빈 프레임은 버린다."""
    results = []
    for _ in range(tries):
        cf, df = cam.frames()
        corners = detect_checkerboard(np.asanyarray(cf.get_data()))
        if corners is None:
            continue
        pts = _corner_depth_points(cam, corners, df)
        if pts is None:
            continue
        if results:  # 프레임 사이 코너 순서가 뒤집혔으면 맞춰 준다
            from rig import align_corner_order
            pts = align_corner_order(results[0], pts)
        results.append(pts)
        if len(results) >= n_frames:
            break
    if not results:
        return None
    return np.median(np.stack(results), axis=0)


def board_object_points():
    cols, rows = config.CHECKERBOARD
    grid = np.zeros((rows * cols, 3), np.float32)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * config.SQUARE_SIZE_M
    return grid


def checkerboard_3d_pnp(cam, n_good=5, tries=40):
    """체커보드 자세를 컬러 영상 PnP로 구해 코너 3D 좌표를 반환한다(회전축 추정용).
    depth 노이즈의 영향을 받지 않는다. 여러 프레임 결과의 중앙값."""
    from rig import align_corner_order
    obj = board_object_points()
    K = K_matrix(cam.intr)
    dist = np.array(cam.intr["coeffs"], dtype=np.float64)
    results = []
    for _ in range(tries):
        corners = detect_checkerboard(cam.color())
        if corners is None:
            continue
        ok, rvec, tvec = cv2.solvePnP(obj, corners, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            continue
        R, _ = cv2.Rodrigues(rvec)
        pts = (R @ obj.T).T + tvec.reshape(1, 3)
        if results:
            pts = align_corner_order(results[0], pts)
        results.append(pts)
        if len(results) >= n_good:
            break
    if not results:
        return None
    return np.median(np.stack(results), axis=0)


# ---------------------------------------------------------------------------
# 미리보기
# ---------------------------------------------------------------------------
def preview_and_wait(cams, message="", show_checkerboard=False, extra_keys=""):
    """카메라 화면을 띄우고 키 입력을 기다린다.
    Space → "space", extra_keys에 든 글자 → 그 글자, Esc → 중단(KeyboardInterrupt).
    1920x1080은 PREVIEW_WIDTH로 줄여서 보여주고, 체커보드 표시도 줄인 영상으로 빠르게 한다."""
    names = [f"Camera {c.role} ({c.serial})" for c in cams]
    for n in names:
        cv2.namedWindow(n, cv2.WINDOW_NORMAL)
    if message:
        print(message)
    try:
        while True:
            for cam, name in zip(cams, names):
                img = cam.color()
                s = config.PREVIEW_WIDTH / img.shape[1]
                small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                if show_checkerboard:
                    corners = detect_checkerboard(small, fast=True)
                    ok = corners is not None
                    if ok:
                        cv2.drawChessboardCorners(small, config.CHECKERBOARD, corners, True)
                    cv2.putText(small, "FOUND" if ok else "not found", (15, 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0) if ok else (0, 0, 255), 2)
                cv2.imshow(name, small)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                raise KeyboardInterrupt("사용자가 Esc를 눌러 중단했습니다.")
            if key == 32:
                return "space"
            if key != 255 and chr(key).lower() in extra_keys:
                return chr(key).lower()
    finally:
        for n in names:
            cv2.destroyWindow(n)


if __name__ == "__main__":
    _print_devices(list_devices())
    sa, sb = _saved_rig_serials()
    if sa:
        print(f"저장된 캘리브레이션의 카메라: A={sa}, B={sb}")
