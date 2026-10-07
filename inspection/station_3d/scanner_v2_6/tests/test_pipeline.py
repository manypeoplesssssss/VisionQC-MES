"""
카메라·아두이노 없이 돌려볼 수 있는 합성 데이터 테스트.

    python -m pytest tests -q        (또는)   python tests/test_pipeline.py

검증 내용
    1) 회전축 추정: 기울어진 축 + depth 수준 노이즈에서 축 방향·위치·각도 복원
    2) 좌표 변환 왕복 (카메라 A/B ↔ 턴테이블 좌표)
    3) 원판 높이 추정
    4) 치수 측정: 비스듬히 놓인 상자의 가로/세로/높이
    5) Visual Hull: 좌우 배치 카메라 2대 x 36뷰 합성 실루엣 → 상자 치수 복원,
       마스크 1장이 망가져도 miss 허용치 덕분에 형상 유지
    6) 공차 판정 / 캘리퍼스 보정계수
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from measure_object import compare_reference, judge, measure_points  # noqa: E402
from rig import (RigCalibration, estimate_plate_height, estimate_turntable_axis,  # noqa: E402
                 kabsch, make_basis, project_points, rot_axis)
from visual_hull import carve, voxel_grid  # noqa: E402

RNG = np.random.default_rng(0)
INTR = dict(width=1280, height=720, fx=910.0, fy=910.0, ppx=640.0, ppy=360.0)
BOX = (0.060, 0.080, 0.040)   # 가로(x), 높이(y), 세로(z) m
BOX_YAW = 20.0                # 턴테이블 위에 비스듬히 놓은 각도


def look_at(pos, target, up=np.array([0, 1.0, 0])):
    """월드(턴테이블) → 카메라 (R, t). 카메라: x 오른쪽, y 아래, z 앞."""
    z = target - pos
    z /= np.linalg.norm(z)
    y = -(up - (up @ z) * z)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    R = np.vstack([x, y, z])
    return R, -R @ pos


def make_rig():
    """좌우 배치: 두 카메라가 ±40도 방위, 40cm 거리, 15cm 높이에서 내려다봄."""
    target = np.array([0, 0.04, 0])
    cams = {}
    for name, az in (("A", -40.0), ("B", 40.0)):
        a = np.deg2rad(az)
        pos = np.array([0.40 * np.sin(a), 0.15, -0.40 * np.cos(a)])
        cams[name] = look_at(pos, target)
    (RA, tA), (RB, tB) = cams["A"], cams["B"]
    R_ab = RA @ RB.T
    t_ab = tA - R_ab @ tB
    rig = RigCalibration(R_ab, t_ab, axis=RA[:, 1], origin=tA, basis=RA)
    return rig, cams


def box_surface(step=0.001):
    w, h, d = BOX
    xs, ys, zs = (np.arange(-w / 2, w / 2 + 1e-9, step), np.arange(0, h + 1e-9, step),
                  np.arange(-d / 2, d / 2 + 1e-9, step))
    pts = []
    for x in (-w / 2, w / 2):
        Y, Z = np.meshgrid(ys, zs)
        pts.append(np.column_stack([np.full(Y.size, x), Y.ravel(), Z.ravel()]))
    for z in (-d / 2, d / 2):
        X, Y = np.meshgrid(xs, ys)
        pts.append(np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, z)]))
    for y in (0, h):
        X, Z = np.meshgrid(xs, zs)
        pts.append(np.column_stack([X.ravel(), np.full(X.size, y), Z.ravel()]))
    P = np.vstack(pts)
    return P @ rot_axis([0, 1, 0], BOX_YAW).T


def render_mask(pts_tt, R, t):
    u, v, z = project_points(pts_tt @ R.T + t, INTR)
    hull = cv2.convexHull(np.column_stack([u, v]).astype(np.float32)).astype(np.int32)
    m = np.zeros((INTR["height"], INTR["width"]), np.uint8)
    cv2.fillConvexPoly(m, hull, 255)
    return m > 0


# ---------------------------------------------------------------------------
def test_axis_estimation():
    true_axis = rot_axis([1, 0, 0], 8.0) @ np.array([0, -1.0, 0])   # 8도 기운 축
    true_pt = np.array([0.01, 0.05, 0.42])
    cols, rows, sq = 9, 6, 0.025
    grid = np.zeros((cols * rows, 3))
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * sq
    board0 = grid - grid.mean(0) + true_pt + np.array([0.0, 0.0, -0.03])
    angles = [0, 10, 20, 30, 40]
    boards = []
    for a in angles:
        pts = (rot_axis(true_axis, a) @ (board0 - true_pt).T).T + true_pt
        boards.append(pts + RNG.normal(0, 0.0005, pts.shape))       # 0.5mm 노이즈
    res = estimate_turntable_axis(boards, angles)
    err_deg = np.degrees(np.arccos(np.clip(res["axis"] @ true_axis, -1, 1)))
    rel = res["point"] - true_pt
    dist = np.linalg.norm(rel - (rel @ true_axis) * true_axis)
    assert err_deg < 1.0, err_deg
    assert dist < 0.002, dist
    assert np.allclose(res["measured_deg"], [10, 20, 30, 40], atol=0.5)


def test_transform_roundtrip():
    rig, cams = make_rig()
    pts = RNG.uniform(-0.05, 0.05, (100, 3))
    for th in (0, 37, 250):
        back = rig.cam_a_to_tt(rig.tt_to_cam_a(pts, th), th)
        assert np.allclose(back, pts, atol=1e-9)
        # 카메라 B extrinsic이 B→A 변환과 일치하는지
        RB, tB = rig.extrinsic("B", th)
        pb = pts @ RB.T + tB
        assert np.allclose(rig.b_to_a(pb), rig.tt_to_cam_a(pts, th), atol=1e-9)
    # θ=0 extrinsic이 합성 카메라 포즈와 같은지
    RA, tA = rig.extrinsic("A", 0)
    assert np.allclose(RA, cams["A"][0]) and np.allclose(tA, cams["A"][1])


def test_plate_height():
    axis, point = np.array([0, -1.0, 0]), np.array([0, 0, 0.4])
    plate = np.column_stack([RNG.uniform(-0.08, 0.08, 5000), np.full(5000, 0.07),
                             0.4 + RNG.uniform(-0.08, 0.08, 5000)])
    plate[:, 1] += RNG.normal(0, 0.001, 5000)
    s, n = estimate_plate_height(plate, axis, point, 0.05)
    assert abs(s - (-0.07)) < 0.001 and n > 1000


def test_measure_box():
    dims = measure_points(box_surface())
    assert abs(dims["width"] - 60) < 1.0
    assert abs(dims["depth"] - 40) < 1.0
    assert abs(dims["height"] - 80) < 0.5


def test_visual_hull_box():
    rig, _ = make_rig()
    surface = box_surface(0.0015)
    views = []
    for i in range(36):
        th = i * 10.0
        for cam in ("A", "B"):
            # 고정 카메라로 θ만큼 돌아간 물체를 본 실루엣
            #   = 0도 물체를 extrinsic(θ)로 투영한 것 (rig.extrinsic의 정의)
            R0, t0 = rig.extrinsic(cam, 0.0)
            rotated = surface @ rot_axis([0, 1, 0], th).T
            mask = render_mask(rotated, R0, t0)
            R, t = rig.extrinsic(cam, th)
            views.append((mask, R, t, INTR))
    centers = voxel_grid(np.array([-0.06, 0.002, -0.06]), np.array([0.06, 0.1, 0.06]), 0.0015)
    kept = carve(centers, views, miss_tolerance=0, log=None)
    dims = measure_points(kept.astype(np.float64))
    # Visual Hull은 물체를 "포함"하는 외형이라 실제보다 작아지면 안 되고,
    # 유한한 뷰(10도 간격)·내려다보는 시점 때문에 몇 mm 크게 나오는 것이 정상이다.
    for k, true in (("width", 60), ("depth", 40), ("height", 80)):
        assert true - 1.0 <= dims[k] <= true + 6.0, (k, dims)

    # 마스크 1장을 망가뜨려도(절반 지움) miss 허용치 2면 형상 유지
    bad = list(views)
    m, R, t, intr = bad[5]
    m = m.copy()
    m[:, : INTR["width"] // 2 + 40] = False
    bad[5] = (m, R, t, intr)
    strict = measure_points(carve(centers, bad, miss_tolerance=0, log=None).astype(np.float64))
    tolerant = measure_points(carve(centers, bad, miss_tolerance=2, log=None).astype(np.float64))
    assert abs(tolerant["width"] - dims["width"]) < 1.5
    assert strict["n_points"] < tolerant["n_points"]


def test_judge_and_reference():
    dims = dict(width=60.8, depth=40.1, height=78.5)
    j = judge(dims, dict(width=60, depth=40, height=80), 1.0)
    assert j["width"]["ok"] and j["depth"]["ok"] and not j["height"]["ok"] and not j["pass"]
    # 3단계 판정(축별 한계): 정상 / 재검 / 불량 (10-02)
    nom = dict(width=194.5, depth=84.96, height=58.68)
    ng, rc = dict(width=2.5, depth=3.5, height=2.0), dict(width=1.5, depth=2.0, height=1.5)
    assert judge(dict(width=195.5, depth=85.5, height=58.0), nom, ng, rc)["result"] == "OK"
    j = judge(dict(width=194.5, depth=87.5, height=58.68), nom, ng, rc)
    assert j["depth"]["status"] == "RECHECK" and j["result"] == "RECHECK" and j["pass"]
    j = judge(dict(width=194.5, depth=91.0, height=58.68), nom, ng, rc)
    assert j["depth"]["status"] == "NG" and j["result"] == "NG" and not j["pass"]
    rows, scale = compare_reference(dict(width=61.2, depth=40.8, height=81.6), (60, 40, 80))
    assert abs(scale - 0.9804) < 0.001 and rows["height"]["error"] == 1.6


def test_kabsch_reflection_safe():
    A = RNG.normal(size=(20, 3))
    R_true = rot_axis([0.3, 1, 0.2], 33)
    B = A @ R_true.T + np.array([0.1, -0.2, 0.3])
    R, t = kabsch(A, B)
    assert np.allclose(R, R_true, atol=1e-9) and np.linalg.det(R) > 0


def test_rig_save_load(tmp_path=None):
    import tempfile
    rig, _ = make_rig()
    rig.info = dict(ab_rmse_m=0.0012, measured_deg=[10.1, 20.0], serial_a="123456")
    path = os.path.join(tmp_path or tempfile.mkdtemp(), "rig.npz")
    rig.save(path)
    back = RigCalibration.load(path)
    assert np.allclose(back.basis, rig.basis) and back.info["serial_a"] == "123456"
    assert back.info["measured_deg"] == [10.1, 20.0]


def test_turntable_protocol():
    """가짜 아두이노로 핸드셰이크·백래시 방지 복귀(finish_turn) 확인."""
    import turntable as ttmod

    class FakeSerial:
        def __init__(self, *a, **k):
            self.timeout, self.out, self.log, self.pos = k.get("timeout"), [b"READY\n"], [], 0.0

        def readline(self):
            return self.out.pop(0) if self.out else b""

        def reset_input_buffer(self):
            pass

        def write(self, data):
            cmd = data.decode().strip()
            if not cmd:              # _sync()가 보내는 빈 줄 → 아두이노도 무시
                return
            self.log.append(cmd)
            if cmd[0] == "R":
                self.pos += float(cmd[1:])
                self.out.append(b"DONE\n")
            elif cmd == "Z":
                self.pos = 0.0
                self.out.append(b"DONE\n")
            elif cmd == "P":
                self.out.append(f"{self.pos:.2f}\n".encode())

        def close(self):
            pass

    class FakeModule:
        Serial = FakeSerial

    orig = ttmod.serial
    ttmod.serial = FakeModule
    try:
        tt = ttmod.Turntable("FAKE")
        tt.zero()
        for _ in range(5):
            tt.rotate(10)
        tt.finish_turn()
        cmds = tt.ser.log
        assert all(not c.startswith("R-") for c in cmds)       # 역회전 없음
        assert cmds[-2] == "R310.000" and cmds[-1] == "Z"
    finally:
        ttmod.serial = orig


def _make_interlock_serial(trip_at_deg=None, refuse_first=False):
    """turntable.ino(인터락 병합본)를 흉내 낸 가짜 시리얼.
    - 0.5초 주기 STAT 줄 대신, 매 readline마다 가끔 STAT 줄을 끼워 넣음
    - R 이동 중 trip_at_deg를 지나면 그 각도에서 멈추고 ERR,INTERLOCK,<각도> 전송
    - 이후 RUN 복귀(EVT,RUN) 전까지 R/A는 ERR,INTERLOCK으로 거부"""
    class Ser:
        def __init__(self, *a, **k):
            self.out = [b"READY\n", b"EVT,RUN\n"]
            self.pos, self.log = 0.0, []
            self.tripped = refuse_first
            self.trip_at = trip_at_deg
            self.tick = 0
            self.release_after = 3        # RUN 복귀까지 STAT,TRIPPED 줄 개수
            self.counting = not refuse_first   # 첫 거부 응답 후부터 복귀 카운트

        def readline(self):
            self.tick += 1
            if self.out:
                return self.out.pop(0)
            if self.tripped and not self.counting:
                return b"STAT,TRIPPED,20,90\n" if self.tick % 2 == 0 else b""
            if self.tripped:               # 대기 중 상태 줄만 흘러나옴
                self.release_after -= 1
                if self.release_after <= 0:
                    self.tripped = False
                    return b"EVT,RUN\n"
                return b"STAT,TRIPPED,20,90\n"
            if self.tick % 2 == 0:
                return b"STAT,RUN,80,90\n"
            return b""

        def reset_input_buffer(self):
            pass

        def write(self, data):
            cmd = data.decode().strip()
            if not cmd:
                return
            self.log.append(cmd)
            c = cmd[0].upper()
            if c == "R":
                if self.tripped:
                    self.counting = True
                    self.out.append(b"ERR,INTERLOCK\n")
                    return
                tgt = self.pos + float(cmd[1:])
                if self.trip_at is not None and self.pos < self.trip_at < tgt:
                    self.pos = self.trip_at
                    self.tripped, self.trip_at, self.counting = True, None, True
                    self.release_after = 3
                    self.out.append(f"ERR,INTERLOCK,{self.pos:.2f}\n".encode())
                else:
                    self.pos = tgt
                    self.out.append(b"STAT,RUN,80,90\n")   # DONE 앞에 상태 줄이 끼어도 무시돼야 함
                    self.out.append(b"DONE\n")
            elif c == "Z":
                self.pos = 0.0
                self.out.append(b"DONE\n")
            elif c == "P":
                self.out.append(f"{self.pos:.2f}\n".encode())
            else:
                self.out.append(b"ERR\n")

        def close(self):
            pass
    return Ser


def test_turntable_interlock_resume():
    """회전 중 인터락 → 정지 각도 읽기 → 리셋 후 남은 각도만 이어서 회전, 최종 위치 정확."""
    import turntable as ttmod
    orig = ttmod.serial

    class M:
        Serial = _make_interlock_serial(trip_at_deg=4.25)
    ttmod.serial = M
    try:
        tt = ttmod.Turntable("FAKE")
        tt.zero()
        tt.rotate(10)
        assert abs(tt.ser.pos - 10.0) < 1e-6 and abs(tt.position_deg - 10.0) < 1e-9
        assert tt.interlock_events == 1
        rs = [c for c in tt.ser.log if c.startswith("R")]
        assert rs == ["R10.000", "R5.750"], rs      # 정지한 4.25도에서 남은 5.75도만
        tt.rotate(10)                                # 이후는 정상 동작
        assert abs(tt.ser.pos - 20.0) < 1e-6
    finally:
        ttmod.serial = orig


def test_turntable_interlock_refused_and_status_lines():
    """정지 상태에서 명령이 거부(ERR,INTERLOCK)돼도 RUN 복귀 후 전체 각도 수행, STAT 줄은 응답으로 오인하지 않음."""
    import turntable as ttmod
    orig = ttmod.serial

    class M:
        Serial = _make_interlock_serial(refuse_first=True)
    ttmod.serial = M
    try:
        tt = ttmod.Turntable("FAKE")
        tt.zero()
        for _ in range(3):
            tt.rotate(10)
        assert abs(tt.ser.pos - 30.0) < 1e-6 and tt.interlock_events == 1
        assert abs(tt.reported_angle() - 30.0) < 1e-6
    finally:
        ttmod.serial = orig


def test_basis_right_handed():
    Bm = make_basis(np.array([0.1, -1.0, 0.05]))
    assert np.allclose(Bm.T @ Bm, np.eye(3), atol=1e-9) and np.linalg.det(Bm) > 0




def _board(n_cols=9, n_rows=6, sq=0.015):
    g = np.zeros((n_cols * n_rows, 3))
    g[:, :2] = np.mgrid[0:n_cols, 0:n_rows].T.reshape(-1, 2) * sq
    return g - g.mean(0)


def test_ab_multi_pose_with_flips():
    """수평 일직선 배치(두 카메라가 같은 방향, 약 35도 벌어짐) + 일부 자세 코너 순서 뒤집힘 +
    depth 노이즈 + 이상한 자세 1개 → 올바른 R,t 복원, 이상 자세 제외."""
    R_true = rot_axis([0, 1, 0], -35.0)
    t_true = np.array([0.25, 0.0, 0.05])
    board = _board()
    poses_a, poses_b = [], []
    for i in range(7):
        R_pose = rot_axis([0, 1, 0], RNG.uniform(-20, 20)) @ rot_axis([1, 0, 0], RNG.uniform(-20, 20))
        pa = board @ R_pose.T + np.array([RNG.uniform(-0.04, 0.04), RNG.uniform(-0.03, 0.03), 0.42])
        pb = (pa - t_true) @ R_true            # B 좌표: pa = R pb + t
        pa = pa + RNG.normal(0, 0.0007, pa.shape)
        pb = pb + RNG.normal(0, 0.0007, pb.shape)
        if i in (1, 4):
            pb = pb[::-1]                      # 코너 순서 뒤집힘
        if i == 6:
            pb = pb + np.array([0.01, 0, 0])   # 보드가 흔들린 자세
        poses_a.append(pa)
        poses_b.append(pb)
    from rig import estimate_ab_multi, rotation_angle_deg
    res = estimate_ab_multi(poses_a, poses_b, reject_m=0.005, min_poses=3)
    assert res["flipped"][1] and res["flipped"][4] and not res["flipped"][0]
    assert res["used"][6] is False and all(res["used"][:6])
    assert rotation_angle_deg(res["R"] @ R_true.T) < 0.5
    assert np.linalg.norm(res["t"] - t_true) < 0.002
    assert res["rmse_m"] < 0.002


def test_axis_with_flipped_order():
    true_axis = rot_axis([1, 0, 0], 35.0) @ np.array([0, -1.0, 0])
    true_pt = np.array([0.0, 0.12, 0.40])
    board0 = _board() @ rot_axis([1, 0, 0], -25).T + true_pt + np.array([0.02, -0.03, 0.0])
    angles = [0, 10, 20, 30, 40]
    boards = []
    for k, a in enumerate(angles):
        p = (rot_axis(true_axis, a) @ (board0 - true_pt).T).T + true_pt
        p = p + RNG.normal(0, 0.0003, p.shape)
        boards.append(p[::-1] if k in (2, 3) else p)   # 중간 각도에서 순서 뒤집힘
    res = estimate_turntable_axis(boards, angles)
    err = np.degrees(np.arccos(np.clip(abs(res["axis"] @ true_axis), -1, 1)))
    assert err < 1.0 and np.allclose(res["measured_deg"], [10, 20, 30, 40], atol=0.5)
    assert res["rmse_m"] < 0.002


def test_turntable_noise_recovery():
    """포트 연결 직후 아두이노 버퍼에 잡음 바이트가 남아 첫 명령이 ERR이 되는 경우 복구."""
    import turntable as ttmod

    class NoisySerial:
        """실제 펌웨어처럼 '\\n'까지 한 줄로 읽고, 첫 글자가 명령이 아니면 ERR."""
        def __init__(self, *a, **k):
            self.timeout, self.out, self.pos = k.get("timeout"), [b"READY\n"], 0.0
            self.rx = "\x00"          # 연결 직후 남은 잡음
        def readline(self):
            return self.out.pop(0) if self.out else b""
        def reset_input_buffer(self):
            self.out.clear()
        def write(self, data):
            self.rx += data.decode()
            while "\n" in self.rx:
                line, self.rx = self.rx.split("\n", 1)
                line = line.strip(" \r\t")
                if not line:
                    continue
                c = line[0].upper()
                if c == "P":
                    self.out.append(f"{self.pos:.2f}\n".encode())
                elif c == "R":
                    self.pos += float(line[1:]); self.out.append(b"DONE\n")
                elif c == "Z":
                    self.pos = 0.0; self.out.append(b"DONE\n")
                else:
                    self.out.append(b"ERR\n")
        def close(self):
            pass

    class FakeModule:
        Serial = NoisySerial

    orig = ttmod.serial
    ttmod.serial = FakeModule
    try:
        tt = ttmod.Turntable("FAKE")
        assert tt.reported_angle() == 0.0
        tt.rotate(10)
        assert abs(tt.reported_angle() - 10.0) < 1e-6
    finally:
        ttmod.serial = orig


def test_turntable_no_port_reconfigure():
    """포트 timeout을 바꿀 때마다 아두이노에 잡음이 들어가는 환경(Windows 실측 증상)에서도 동작."""
    import turntable as ttmod

    class ReconfigNoisySerial:
        def __init__(self, *a, **k):
            self._timeout, self.out, self.pos, self.rx = k.get("timeout"), [b"READY\n"], 0.0, ""
            self.reconfigs = 0
        @property
        def timeout(self):
            return self._timeout
        @timeout.setter
        def timeout(self, v):            # 설정 변경 → 아두이노 쪽에 잡음 1바이트
            self._timeout = v
            self.reconfigs += 1
            self.rx += "\x00"
        def readline(self):
            return self.out.pop(0) if self.out else b""
        def reset_input_buffer(self):
            self.out.clear()
        def write(self, data):
            self.rx += data.decode()
            while "\n" in self.rx:
                line, self.rx = self.rx.split("\n", 1)
                line = line.strip(" \r\t")
                if not line:
                    continue
                c = line[0].upper()
                if c == "P":
                    self.out.append(f"{self.pos:.2f}\n".encode())
                elif c == "R":
                    self.pos += float(line[1:]); self.out.append(b"DONE\n")
                elif c == "Z":
                    self.pos = 0.0; self.out.append(b"DONE\n")
                else:
                    self.out.append(b"ERR\n")
        def close(self):
            pass

    class FakeModule:
        Serial = ReconfigNoisySerial

    orig = ttmod.serial
    ttmod.serial = FakeModule
    try:
        tt = ttmod.Turntable("FAKE")
        assert tt.reported_angle() == 0.0
        tt.zero()
        tt.rotate(10)
        assert abs(tt.reported_angle() - 10.0) < 1e-6
        assert tt.ser.reconfigs == 0, "연 뒤에 포트 설정을 바꾸면 안 됨"
    finally:
        ttmod.serial = orig


def test_square_size_check():
    """depth 코너로 칸 크기를 재서 config와 다르면 캘리브레이션을 멈추는지 (10-01 P-28 재발 방지)."""
    try:
        import pyrealsense2  # noqa: F401
    except ImportError:          # 카메라 SDK 없는 환경에서도 이 함수만 시험
        import types
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    import calibrate_rig as cr
    import config
    cols, rows = config.CHECKERBOARD
    rng = np.random.default_rng(0)
    def board(sq):
        obj = np.array([[x * sq, y * sq, 0.0] for y in range(rows) for x in range(cols)])
        return obj + [0, 0, 0.35] + rng.normal(0, 0.0008, obj.shape)
    orig = config.SQUARE_SIZE_M
    try:
        config.SQUARE_SIZE_M = 0.020
        cr.check_square_size([board(0.020), board(0.020)])          # 맞으면 통과
        config.SQUARE_SIZE_M = 0.015
        try:
            cr.check_square_size([board(0.020)])                     # 20mm 보드에 0.015 → 중단
            raise AssertionError("칸 크기 불일치를 잡지 못함")
        except RuntimeError:
            pass
    finally:
        config.SQUARE_SIZE_M = orig


def test_backlash_takeup():
    """손으로 원판을 거꾸로 돌려 기어 유격이 생긴 상태에서도 take_up_backlash 후 첫 10도가 정확한지 (P-31)."""
    import turntable as ttmod

    class GearSerial:
        """정방향 명령은 남은 유격(slack)을 먼저 메운 뒤에야 원판을 돌린다."""
        def __init__(self, *a, **k):
            self.timeout, self.out, self.plate, self.slack = k.get("timeout"), [b"READY\n"], 0.0, 4.6
        def readline(self):
            return self.out.pop(0) if self.out else b""
        def reset_input_buffer(self):
            self.out.clear()
        def write(self, data):
            cmd = data.decode().strip()
            if not cmd:
                return
            if cmd[0] == "R":
                d = float(cmd[1:]); used = min(self.slack, d)
                self.slack -= used; self.plate += d - used
                self.out.append(b"DONE\n")
            elif cmd == "Z":
                self.out.append(b"DONE\n")
            elif cmd == "P":
                self.out.append(b"0.00\n")
        def close(self):
            pass

    class FakeModule:
        Serial = GearSerial

    orig = ttmod.serial
    ttmod.serial = FakeModule
    try:
        tt = ttmod.Turntable("FAKE")          # 유격 4.6도가 남은 상태
        tt.rotate(10)
        assert abs(tt.ser.plate - 5.4) < 1e-6  # 보정 없이: 첫 10도 명령 → 5.4도 (실측과 같은 현상)
        tt = ttmod.Turntable("FAKE")
        tt.take_up_backlash(8.0)
        start = tt.ser.plate
        tt.rotate(10)
        assert abs(tt.ser.plate - start - 10.0) < 1e-6   # 유격 제거 후: 정확히 10도
    finally:
        ttmod.serial = orig


def test_depth_edge_and_multiview_filters():
    """깊이 경계 마스크와 다시점 지지 필터 (P-32)."""
    try:
        import pyrealsense2  # noqa: F401
    except ImportError:
        import types
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    import d435_common as dc
    from merge_turntable_scans import multiview_support
    z = np.full((60, 80), 0.60, np.float32)      # 배경 60cm
    z[20:40, 20:60] = 0.40                       # 물체 40cm
    e = dc.depth_edge_mask(z, 7, 0.010)
    assert e[30, 20] and e[30, 59] and not e[30, 40] and not e[5, 5]   # 윤곽만 경계
    rng = np.random.default_rng(0)
    surf = rng.uniform(-0.05, 0.05, (2000, 3)); surf[:, 2] = 0.0         # 평면 표면
    views = [surf + rng.normal(0, 0.0005, surf.shape) for _ in range(20)]
    stray = np.array([[0.0, 0.0, 0.02]])                                 # 한 뷰에만 있는 떠 있는 점
    views[0] = np.vstack([views[0], stray])
    sup = multiview_support(views, np.vstack([surf[:5], stray]), 0.003)
    assert sup[:5].min() >= 15 and sup[5] <= 1


def test_measure_trim_tail():
    """물체 끝에 얇은 잡음 꼬리(1% 미만)가 붙어도 가로/세로가 실제 크기에 가까운지 (P-32, 10-01)."""
    rng = np.random.default_rng(3)
    L, W, H0, H1 = 0.195, 0.0838, 0.01, 0.05

    def face(n, fix_axis, fix_val):                       # 상자 표면 한 면의 점 (스캔은 표면만 찍힘)
        p = np.column_stack([rng.uniform(-L / 2, L / 2, n), rng.uniform(H0, H1, n), rng.uniform(-W / 2, W / 2, n)])
        p[:, fix_axis] = fix_val
        return p
    body = np.vstack([face(4000, 0, -L / 2), face(4000, 0, L / 2), face(9000, 2, -W / 2),
                      face(9000, 2, W / 2), face(9000, 1, H1)])
    tail = np.column_stack([rng.uniform(0.0975, 0.105, 120), rng.uniform(0.01, 0.03, 120),
                            rng.uniform(-0.02, 0.02, 120)])              # 차 끝 7.5mm 회색 층 (0.6%)
    dims = measure_points(np.vstack([body, tail]))
    assert dims["raw_width"] > 201                       # 최소~최대는 꼬리만큼 부풀고
    assert abs(dims["width"] - 195.0) < 2.5 and abs(dims["depth"] - 83.8) < 2.0   # 잘라낸 값은 실측에 근접


def _make_placement_serial(results, interlock_first_check=False, cal_reply="CAL,OK"):
    """turntable.ino v2.6(놓임 검사 포함)을 흉내 낸 가짜 시리얼.
    results: C 명령마다 차례로 돌려줄 코드 리스트 ("OK" 또는 OFFSET_X 등).
    interlock_first_check: 첫 C가 PLACE,ERR,INTERLOCK으로 끝나고, 몇 줄 뒤 EVT,RUN으로 복귀."""
    class Ser:
        def __init__(self, *a, **k):
            self.out = [b"READY\n", b"EVT,RUN\n"]
            self.log, self.calibrated = [], False
            self.tripped, self.wait = False, 0
            self.results = list(results)
            self.pending_trip = interlock_first_check
            self.tick = 0

        def readline(self):
            self.tick += 1
            if self.out:
                return self.out.pop(0)
            if self.tripped:
                self.wait -= 1
                if self.wait <= 0:
                    self.tripped = False
                    return b"EVT,RUN\n"
                return b"STAT,TRIPPED,20,90\n"
            return b"STAT,RUN,80,90\n" if self.tick % 2 == 0 else b""

        def reset_input_buffer(self):
            pass

        def write(self, data):
            cmd = data.decode().strip()
            if not cmd:
                return
            self.log.append(cmd)
            c = cmd[0].upper()
            if c == "K":
                self.out.append(b"HINT,CAL0 off=100 on=700\n")
                self.out.append((cal_reply + "\n").encode())
                self.calibrated = cal_reply == "CAL,OK"
            elif c == "C":
                if self.pending_trip:
                    self.pending_trip, self.tripped, self.wait = False, True, 3
                    self.out.append(b"PLACE,ERR,INTERLOCK\n")
                elif not self.calibrated:
                    self.out.append(b"PLACE,ERR,BEAM_FAULT\n")
                else:
                    r = self.results.pop(0)
                    self.out.append(b"BEAM,50,50\n")             # 상태 줄이 끼어도 무시돼야 함
                    self.out.append(b"PLACE,OK\n" if r == "OK" else f"PLACE,ERR,{r}\n".encode())
            elif c == "P":
                self.out.append(b"0.00\n")
            else:
                self.out.append(b"ERR\n")

        def close(self):
            pass
    return Ser


def _with_fake(ser_cls):
    import turntable as ttmod
    orig = ttmod.serial

    class M:
        Serial = ser_cls
    ttmod.serial = M
    return ttmod, orig


def test_placement_check_ok_and_offset():
    """보정 후 놓임 검사: OFFSET_X 불량 → OK, BEAM,/STAT 줄은 응답으로 오인하지 않음. 보정 전엔 BEAM_FAULT."""
    ttmod, orig = _with_fake(_make_placement_serial(["OFFSET_X", "OK"]))
    try:
        tt = ttmod.Turntable("FAKE")
        assert tt.check_placement() == (False, "BEAM_FAULT")      # 아직 보정 안 함
        assert tt.calibrate_placement() is True
        assert tt.check_placement() == (False, "OFFSET_X")
        assert tt.check_placement() == (True, "OK")
        assert [c for c in tt.ser.log if c in ("K", "C")] == ["C", "K", "C", "C"]
    finally:
        ttmod.serial = orig


def test_placement_interlock_during_check():
    """검사 중 인터락(PLACE,ERR,INTERLOCK) → RUN 복귀까지 기다린 뒤 검사를 다시 해서 OK를 받는다."""
    ttmod, orig = _with_fake(_make_placement_serial(["OK"], interlock_first_check=True))
    try:
        tt = ttmod.Turntable("FAKE")
        tt.calibrate_placement()
        assert tt.check_placement() == (True, "OK")
        assert tt.interlock_events == 1
        assert [c for c in tt.ser.log if c == "C"] == ["C", "C"]
    finally:
        ttmod.serial = orig


def test_placement_calibration_failure():
    """보정 실패(CAL,ERR,<마스크>)는 원인을 알리는 RuntimeError."""
    ttmod, orig = _with_fake(_make_placement_serial([], cal_reply="CAL,ERR,1"))
    try:
        tt = ttmod.Turntable("FAKE")
        try:
            tt.calibrate_placement()
            raise AssertionError("보정 실패인데 예외가 없음")
        except RuntimeError as e:
            assert "보정 실패" in str(e)
    finally:
        ttmod.serial = orig


def test_scan_ensure_placed_retry():
    """turntable_scan.ensure_placed: 놓임 불량이면 다시 놓은 뒤 재검사, 통과하면 기록(시도 횟수·오류 코드)."""
    import builtins
    import sys
    if "pyrealsense2" not in sys.modules:
        import types
        sys.modules["pyrealsense2"] = types.ModuleType("pyrealsense2")
    import turntable_scan as scan
    ttmod, orig = _with_fake(_make_placement_serial(["MISSING", "OFFSET_Y", "OK"]))
    old_input = builtins.input
    builtins.input = lambda *a, **k: ""            # 다시 놓고 Enter
    try:
        tt = ttmod.Turntable("FAKE")
        tt.calibrate_placement()
        res = scan.ensure_placed(tt)
        assert res == dict(ok=True, attempts=3, errors=["MISSING", "OFFSET_Y"]), res
        builtins.input = lambda *a, **k: "q"       # 중단
        tt2 = ttmod.Turntable("FAKE")
        tt2.ser.results = ["MISSING"]
        tt2.calibrate_placement()
        try:
            scan.ensure_placed(tt2)
            raise AssertionError("q 입력인데 중단되지 않음")
        except RuntimeError:
            pass
    finally:
        builtins.input = old_input
        ttmod.serial = orig


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("통과:", name)
