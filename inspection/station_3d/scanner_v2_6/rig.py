"""
rig.py — 카메라 2대 + 턴테이블 "리그"의 좌표 변환 수학 (numpy만 사용)

좌표계 정리
    카메라 A 좌표계 : RealSense 기준 (X 오른쪽, Y 아래, Z 앞). 모든 원본 점의 기준.
    카메라 B 좌표계 : p_A = R_ab @ p_B + t_ab 로 A 좌표계로 옮긴다.
    턴테이블 좌표계 : 원점 = 회전축과 원판 윗면의 교점, Y = 회전축 위쪽,
                      X/Z = 원판 평면. 스캔 결과(.ply)는 전부 이 좌표계로
                      저장되므로, 높이 = y, 원판 위 물체만 = y > 0 이 된다.

턴테이블을 θ만큼 돌리면 물체 위의 한 점 q(0도 기준)는 카메라 A에서
    p = Rot(axis, θ) @ (q - o) + o
위치에 보인다(o: 원점). 이를 거꾸로 풀어 모든 뷰를 0도 기준으로 되돌린다.
카메라를 수평으로 놓았다는 가정(구버전의 "회전축 = 카메라 Y축")은 더 이상
필요 없다 — 회전축을 체커보드로 직접 측정한다.
"""

import json

import numpy as np

try:  # 캘리브레이션 스크립트에서만 필요, 순수 수학 테스트에는 불필요
    import config
except ImportError:  # pragma: no cover
    config = None


# ---------------------------------------------------------------------------
# 기본 수학
# ---------------------------------------------------------------------------
def kabsch(A, B):
    """A, B: (N,3) 대응점. B ≈ R @ A + t 를 만족하는 R, t를 구한다."""
    ca, cb = A.mean(axis=0), B.mean(axis=0)
    H = (A - ca).T @ (B - cb)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    t = cb - R @ ca
    return R, t


def rigid_rmse(R, t, A, B):
    return float(np.sqrt(np.mean(np.sum(((R @ A.T).T + t - B) ** 2, axis=1))))


def rot_axis(axis, angle_deg):
    """단위벡터 axis를 중심으로 angle_deg(오른손 법칙) 회전하는 3x3 행렬."""
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    th = np.deg2rad(angle_deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)


def rotvec_from_matrix(R):
    """회전행렬 → (단위 회전축, 각도[deg])."""
    cos_th = np.clip((np.trace(R) - 1) / 2, -1.0, 1.0)
    th = np.arccos(cos_th)
    if th < 1e-9:
        return np.array([0.0, 1.0, 0.0]), 0.0
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return v / np.linalg.norm(v), float(np.rad2deg(th))


# ---------------------------------------------------------------------------
# 체커보드 코너 순서 뒤집힘 처리
# ---------------------------------------------------------------------------
# 9x6처럼 한쪽 짝수·한쪽 홀수인 보드도, 비스듬히 보거나 크게 돌아가면 OpenCV가
# 코너 순서를 180도 뒤집어(= 리스트를 거꾸로) 돌려주는 경우가 있다. 두 카메라나
# 두 각도 사이에 순서가 어긋나면 계산이 완전히 틀어지므로 자동으로 맞춘다.
def align_corner_order(ref, pts):
    """pts(N,3)의 순서를 ref(N,3)에 맞춘다: 원래 순서와 뒤집은 순서 중
    ref와 대응점끼리 더 가까운 쪽을 고른다(작은 이동·회전 사이에서만 유효)."""
    d_same = np.linalg.norm(ref - pts, axis=1).mean()
    d_flip = np.linalg.norm(ref - pts[::-1], axis=1).mean()
    return pts if d_same <= d_flip else pts[::-1]


def rotation_angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1.0, 1.0))))


def order_for_small_rotation(pts_b, pts_a):
    """카메라 B 코너 순서를 A에 맞춘다(카메라 간 정합용).
    평면 격자는 순서를 뒤집어도(보드를 180도 돌린 것과 같음) 오차 없이 맞아떨어지는
    '가짜 해'가 생기므로 오차로는 구분할 수 없다. 대신 두 카메라가 같은 쪽에서
    같은 방향을 보고 있으니(수평 일직선 배치) 진짜 해는 회전이 작고(< 90도),
    가짜 해는 회전이 크다(> 90도)는 점으로 고른다.
    반환: (순서 맞춘 pts_b, 뒤집었는지)"""
    R0, _ = kabsch(pts_b, pts_a)
    R1, _ = kabsch(pts_b[::-1], pts_a)
    if rotation_angle_deg(R1) < rotation_angle_deg(R0):
        return pts_b[::-1], True
    return pts_b, False


def estimate_ab_multi(poses_a, poses_b, reject_m=0.005, min_poses=3):
    """여러 자세의 체커보드 3D 코너로 카메라 B→A 변환을 구한다.

    poses_a, poses_b : 자세별 (N,3) 코너 (카메라 A / B 좌표계)
    1) 자세마다 B 코너 순서를 A에 맞춘다 (뒤집힘 보정, 회전이 작은 해 선택)
    2) 모든 자세를 합쳐 한 번에 Kabsch
    3) 전체 결과 기준 오차가 reject_m를 넘는 자세를 빼고 다시 계산(1회)
    반환: dict(R, t, rmse_m, pose_rmse_m, used, flipped, rotation_deg)
    """
    fixed_b, flipped = [], []
    for pa, pb in zip(poses_a, poses_b):
        pb2, f = order_for_small_rotation(pb, pa)
        fixed_b.append(pb2)
        flipped.append(f)
    used = [True] * len(poses_a)

    def solve():
        A = np.vstack([pb for pb, u in zip(fixed_b, used) if u])
        B = np.vstack([pa for pa, u in zip(poses_a, used) if u])
        R, t = kabsch(A, B)
        per = [rigid_rmse(R, t, pb, pa) for pb, pa in zip(fixed_b, poses_a)]
        return R, t, per, rigid_rmse(R, t, A, B)

    R, t, per, total = solve()
    bad = [i for i, e in enumerate(per) if e > reject_m]
    if bad and len(poses_a) - len(bad) >= min_poses:
        for i in bad:
            used[i] = False
        R, t, per, total = solve()
    return dict(R=R, t=t, rmse_m=total, pose_rmse_m=per, used=used, flipped=flipped,
                rotation_deg=rotation_angle_deg(R))


# ---------------------------------------------------------------------------
# 턴테이블 회전축 추정
# ---------------------------------------------------------------------------
def estimate_turntable_axis(board_points, angles_deg):
    """턴테이블 위 체커보드를 여러 각도에서 본 3D 코너들로 회전축을 구한다.

    board_points : 각 각도에서의 코너 좌표 (N,3) 리스트 (카메라 A 좌표계, 같은 코너 순서)
    angles_deg   : 명령한 턴테이블 각도 리스트 (첫 번째가 기준)

    반환: dict(axis=단위벡터(명령 +θ 방향이 오른손 +회전), point=축 위의 한 점,
               measured_deg=실측 회전각 리스트, commanded_deg=명령각 리스트,
               rmse_m=모델 잔차)
    """
    # 각도 사이에 코너 순서가 뒤집혔으면 바로 앞 각도에 맞춰 바로잡는다
    board_points = [np.asarray(board_points[0], dtype=float)] + \
        [np.asarray(p, dtype=float) for p in board_points[1:]]
    for k in range(1, len(board_points)):
        board_points[k] = align_corner_order(board_points[k - 1], board_points[k])
    P0 = board_points[0]
    axes, weights, Rs, ts, cmd = [], [], [], [], []
    for pts, ang in zip(board_points[1:], angles_deg[1:]):
        R, t = kabsch(P0, np.asarray(pts, dtype=float))
        ax, th = rotvec_from_matrix(R)
        Rs.append(R)
        ts.append(t)
        axes.append(ax)
        weights.append(th)
        cmd.append(ang - angles_deg[0])
    if not axes:
        raise ValueError("회전축을 구하려면 각도가 2개 이상 필요합니다.")

    # 부호 맞추기: 첫 축과 반대 방향인 것은 뒤집어서 평균
    ref = axes[0]
    aligned = [a if np.dot(a, ref) >= 0 else -a for a in axes]
    axis = np.average(aligned, axis=0, weights=weights)
    axis /= np.linalg.norm(axis)

    # 명령한 +θ가 axis 기준 +회전이 되도록 부호 결정
    signed = []
    for R in Rs:
        ax, th = rotvec_from_matrix(R)
        signed.append(th if np.dot(ax, axis) >= 0 else -th)
    if np.mean(np.sign(signed) * np.sign(cmd)) < 0:
        axis = -axis
        signed = [-s for s in signed]

    # 축 위의 점: 각 회전에 대해 (I - R) c = t. 축 방향 성분은 정해지지 않으므로
    # 최소 노름 해를 구한다(축 방향 위치는 나중에 원판 높이로 정한다).
    A = np.vstack([np.eye(3) - R for R in Rs])
    b = np.concatenate(ts)
    c, *_ = np.linalg.lstsq(A, b, rcond=None)

    # 잔차: 추정 모델(축 + 명령각이 아닌 실측각)로 P0를 돌렸을 때 오차
    res = []
    for pts, th in zip(board_points[1:], signed):
        pred = (rot_axis(axis, th) @ (P0 - c).T).T + c
        res.append(np.sum((pred - pts) ** 2, axis=1))
    rmse = float(np.sqrt(np.mean(np.concatenate(res))))
    return dict(axis=axis, point=c, measured_deg=signed, commanded_deg=cmd, rmse_m=rmse)


def estimate_plate_height(bg_points, axis, point, sample_radius):
    """빈 턴테이블 배경 점들 중 회전축 근처(sample_radius 이내) 점들의
    축 방향 위치(중앙값)로 원판 윗면 높이를 구한다."""
    rel = bg_points - point
    s = rel @ axis
    radial = np.linalg.norm(rel - np.outer(s, axis), axis=1)
    sel = s[radial < sample_radius]
    return (float(np.median(sel)) if len(sel) else None), int(len(sel))


def make_basis(up):
    """Y=up 인 오른손 좌표계 기저 (열벡터 [x, y, z]). X는 카메라 X축에 가깝게."""
    y = up / np.linalg.norm(up)
    ex = np.array([1.0, 0.0, 0.0])
    x = ex - np.dot(ex, y) * y
    if np.linalg.norm(x) < 1e-6:
        ez = np.array([0.0, 0.0, 1.0])
        x = ez - np.dot(ez, y) * y
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    return np.column_stack([x, y, z])


# ---------------------------------------------------------------------------
# 리그 캘리브레이션 묶음
# ---------------------------------------------------------------------------
class RigCalibration:
    """R_ab, t_ab : 카메라 B → A 변환
    axis        : 회전축 단위벡터 (카메라 A 좌표계, 명령 +θ = 오른손 +회전)
    origin      : 턴테이블 좌표 원점 (축 위, 원판 윗면 높이)
    basis       : 턴테이블 좌표계 기저 (열: x, y(위), z) — 카메라 A 좌표계 표현
    """

    def __init__(self, R_ab, t_ab, axis, origin, basis, info=None):
        self.R_ab = np.asarray(R_ab, dtype=float)
        self.t_ab = np.asarray(t_ab, dtype=float)
        self.axis = np.asarray(axis, dtype=float)
        self.origin = np.asarray(origin, dtype=float)
        self.basis = np.asarray(basis, dtype=float)
        self.info = dict(info or {})

    # ---- 저장/불러오기 --------------------------------------------------
    def save(self, path):
        info_json = json.dumps(self.info, ensure_ascii=False,
                               default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        np.savez(path, R_ab=self.R_ab, t_ab=self.t_ab, axis=self.axis,
                 origin=self.origin, basis=self.basis, info_json=np.array(info_json))

    @classmethod
    def load(cls, path):
        d = np.load(path)
        info = json.loads(str(d["info_json"])) if "info_json" in d else {}
        return cls(d["R_ab"], d["t_ab"], d["axis"], d["origin"], d["basis"], info)

    # ---- 변환 -----------------------------------------------------------
    def b_to_a(self, pts_b):
        return (self.R_ab @ pts_b.T).T + self.t_ab

    def cam_a_to_tt(self, pts_a, theta_deg=0.0):
        """카메라 A 좌표 점(턴테이블 θ 상태에서 찍힘) → 0도 기준 턴테이블 좌표."""
        M = self.basis.T @ rot_axis(self.axis, -theta_deg)
        return (M @ (pts_a - self.origin).T).T

    def tt_to_cam_a(self, pts_tt, theta_deg=0.0):
        M = rot_axis(self.axis, theta_deg) @ self.basis
        return (M @ pts_tt.T).T + self.origin

    def extrinsic(self, cam, theta_deg):
        """턴테이블 좌표(0도 기준 물체 좌표) → 카메라 좌표 변환 (R, t).
        cam: 'A' 또는 'B'."""
        R_a = rot_axis(self.axis, theta_deg) @ self.basis
        t_a = self.origin.copy()
        if cam == "A":
            return R_a, t_a
        R_ba = self.R_ab.T
        return R_ba @ R_a, R_ba @ (t_a - self.t_ab)


def roi_mask_tt(pts_tt, radius, height, plate_margin):
    """턴테이블 좌표계 원기둥 ROI: 축에서 radius 이내, 원판 위 plate_margin~height."""
    r = np.sqrt(pts_tt[:, 0] ** 2 + pts_tt[:, 2] ** 2)
    y = pts_tt[:, 1]
    return (r <= radius) & (y >= plate_margin) & (y <= height)


def project_points(pts_cam, intr):
    """카메라 좌표 점 → 픽셀 (u, v), z. intr: dict(fx, fy, ppx, ppy)."""
    z = pts_cam[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = intr["fx"] * pts_cam[:, 0] / z + intr["ppx"]
        v = intr["fy"] * pts_cam[:, 1] / z + intr["ppy"]
    return u, v, z


def deproject_depth(depth_m, intr):
    """(H,W) depth(m) → (H*W,3) 카메라 좌표 점 (픽셀 순서 유지, 왜곡 무시:
    D435 컬러 스트림 왜곡계수는 사실상 0)."""
    h, w = depth_m.shape
    u, v = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    z = depth_m.astype(np.float32)
    x = (u - intr["ppx"]) / intr["fx"] * z
    y = (v - intr["ppy"]) / intr["fy"] * z
    return np.stack([x, y, z], axis=-1).reshape(-1, 3)


def grid_square_size(pts, pattern):
    """체커보드 코너 3D 좌표(N,3, OpenCV 행 우선 순서)에서 이웃 코너 간격의 중앙값(m).
    depth로 구한 코너에 쓰면 config.SQUARE_SIZE_M 입력이 맞는지 검증할 수 있다."""
    cols, rows = pattern
    g = np.asarray(pts, dtype=np.float64).reshape(rows, cols, 3)
    d = np.concatenate([np.linalg.norm(np.diff(g, axis=1), axis=2).ravel(),
                        np.linalg.norm(np.diff(g, axis=0), axis=2).ravel()])
    return float(np.median(d))
