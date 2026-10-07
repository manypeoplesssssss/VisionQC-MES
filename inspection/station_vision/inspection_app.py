"""
inspection_app.py — 3D 치수 검사 + YOLO 결함 검사를 한 화면에서 버튼으로 조작하는 프로그램

검사 순서
    1. [① 3D 검사]  스캔 → 병합 → 측정 → DB 저장. 3D 코드(station_3d)는 같은 가상환경의 파이썬으로
                  그대로 실행만 한다 (코드를 고치지 않음). 치수 판정은 DB 가 한다
    2. 치수 합격 → [② 검사 시작] 버튼이 켜진다. 불합격·재검이면 켜지지 않는다 (다시 스캔)
    3. [② 검사 시작] PatchCore: 설정한 각도(기본 30도)씩 멈추고 찍어서 이상 점수 계산 → 가장 높은 점수로 판정
       (각 사진의 원본·ROI·히트맵·점수 json 은 검사 폴더/patchcore 에 저장)
    4. PatchCore 합격 → 검사 끝 (최종 정상). 불합격 → 이어서 YOLO 한 바퀴로 결함 종류·위치 촬영
    [PatchCore 먼저] 를 끄면 YOLO 만 한다 (명시적인 YOLO 단독 모드).
    검사 영역은 학습 때 쓴 고정 ROI(config.py 의 ROI_X/ROI_Y, 600×320 픽셀)이고 PatchCore·YOLO 가 같은 ROI 를 쓴다
    (자세한 입력 조건은 추가 수정/추가/PREPROCESSING.md 참고)

yolo_live.py 의 검사 로직(검사 영역, YOLO 검출, 정지·재촬영, 사진 저장)을 그대로 쓰고
키보드 대신 화면 버튼으로 조작한다. 검사 결과는 db_client.py 로 DB(MySQL)에 바로 저장하고,
MES 서버와 화면은 DB 에서 읽어서 보여 준다 (검사 PC → DB → MES).

    python inspection_app.py          # 실제 카메라 + 턴테이블
    python inspection_app.py --sim    # 장비 없이 시험 (captures 사진을 카메라 대신, 3D 는 가짜 측정값)
    python inspection_app.py --no-gate  # 3D 없이 시험 (치수 합격 잠금 해제)
    python inspection_app.py --patchcore-only  # PatchCore 만 (3D·YOLO 없이)

DB 저장 (검사 1회 = product_inspection 1행)
    - 한 바퀴 검사 1회 = DB 검사 1행. 검사번호 = 날짜_검사폴더이름 (예: 20261006_inspection_143000_001)
      3D 검사가 handoff 에 남긴 검사번호가 있으면 그 행을 이어받는다
    - [검사 시작]  → 검사 행 생성 (제품 모델명, 제품 번호, 사진 폴더)
    - 결함 사진 저장 → 원본 + 표시 사진을 MES 사진 폴더로 복사, 결함 목록과 경로를 DB 에 추가
    - 한 바퀴 완료  → YOLO 분류 완료 (yolo_status = COMPLETED)
    - 수동 정지로 중간에 끝낸 검사는 완료를 저장하지 않는다 (YOLO 진행 중으로 남음)
    - DB 에 연결이 안 되면 db_queue 폴더에 쌓아 두었다가 순서대로 다시 저장하고, 화면에 경고를 띄운다
    최종 결과(final_result)는 DB 가 3D 치수 → YOLO 결과로 자동 계산한다.
DB 주소·사진 폴더는 화면에서 바꾸거나 config.py 에 DB_URL, STORAGE_DIR, PRODUCT 를 적는다.
없으면 backend/.env 의 DATABASE_URL 과 backend/storage/images 를 쓴다 (MES 와 같은 PC 일 때).
"""
import argparse
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
# 공용 모듈(inspection/common/db_client.py)을 import 할 수 있게 경로 추가
sys.path.insert(0, str(ROOT.parent / "common"))

import config  # noqa: E402
import yolo_live as live  # noqa: E402
from db_client import DEFAULT_STORAGE_DIR, DBClient, DBError, default_db_url, safety_ok  # noqa: E402

DB_URL = getattr(config, "DB_URL", None) or default_db_url()                    # MES 와 같은 DB
STORAGE_DIR = str(getattr(config, "STORAGE_DIR", None) or DEFAULT_STORAGE_DIR)     # MES 가 사진을 읽는 폴더
PRODUCT = getattr(config, "PRODUCT", getattr(config, "MES_PRODUCT", "redcar"))     # 제품 모델명 (product_name)
VIEW_MAX = (960, 720)  # 화면에 보여 줄 영상 최대 크기
# 3D 검사: station_3d 의 스크립트를 이 폴더에서 그대로 실행한다 (코드는 건드리지 않음)
STATION_3D = Path(getattr(config, "STATION_3D_DIR", None) or ROOT.parent / "station_3d")
BRIDGE_3D = ROOT.parent / "bridge_3d" / "save_3d_to_db.py"
GO_FILE = ROOT / "captures" / "3d_go.flag"  # 화면 버튼 → 3D 스캔 대기 해제 신호 (wait_patch.py 가 이 파일을 본다)
RUN_3D = ROOT.parent / "bridge_3d" / "run_3d_script.py"  # 3D 스크립트 실행기 (3D 코드 수정 없이 포트만 덮어씀)
PYTHON_3D = str(getattr(config, "PYTHON_3D", None) or sys.executable)  # 3D 스크립트를 돌릴 파이썬 (기본: 이 프로그램과 같은 환경)
# PatchCore (1단계): 턴테이블을 360/VIEWS 도씩 멈추며 찍고, 가장 높은 이상 점수로 합격/불합격
PATCHCORE_VIEWS = int(getattr(config, "PATCHCORE_VIEWS", 12))          # 12 → 30도씩 12장
PATCHCORE_MODEL = getattr(config, "PATCHCORE_MODEL", None)            # 없으면 visionPatchCore 의 models/v3
# 연속 회전(S/X)이 없는 펌웨어(3D 용 v2.6)일 때 YOLO 를 몇 도씩 멈춰 가며 검사할지
YOLO_STEP_DEG = float(getattr(config, "YOLO_STEP_DEG", 5.0))
# 이 상태일 때는 검사 시작 버튼을 잠근다 ("PatchCore 3/72" 같은 진행 표시도 포함)
BUSY = ("3D 검사 중", "PatchCore 검사 중", "YOLO 검사 중")
# 3D 검사(bridge_3d/save_3d_to_db.py)가 남긴 검사번호. 이어받으면 consumed=true 로 바꿔 두 번 쓰지 않는다
HANDOFF = ROOT.parent / "handoff" / "latest.json"
# 장비 안전 상태 표시 이름. 검사 허용: 센터링 OFF(정위치) + 인터락 0(정상)
CENTERING_KO = {"OFF": "정위치", "ON": "위치 이상", "UNKNOWN": "미확인"}
INTERLOCK_KO = {"0": "정상", "1": "비정상", "UNKNOWN": "미확인"}
DIM_KO = {"PASS": "합격", "FAIL": "불합격", "RECHECK": "재검", "PENDING": "대기"}


# ---------------------------------------------------------------- 3D → 비전 검사번호 이어받기
def peek_handoff():
    """아직 안 쓴 3D 검사 정보 (없거나 이미 썼으면 None)"""
    try:
        info = json.loads(HANDOFF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None if info.get("consumed") else info


def consume_handoff(info):
    """이어받았다고 표시 (임시 파일에 쓴 뒤 교체)"""
    info = {**info, "consumed": True, "consumed_at": datetime.now().isoformat(timespec="seconds")}
    tmp = HANDOFF.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HANDOFF)


# ---------------------------------------------------------------- 한글 경로용 사진 읽기
# cv2.imread 는 Windows 에서 경로에 한글(예: 사용자 폴더 이름)이 있으면 실패한다.
# 그래서 파일 읽기는 numpy 로 하고 OpenCV 는 디코딩만 한다. (쓰기는 yolo_live.imwrite)
def imread(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


# ---------------------------------------------------------------- 시뮬레이션 장비
class SimTurntable:
    """Turntable 과 같은 메서드를 가진 가짜 턴테이블 (초당 30도)"""
    SPEED = 30.0

    def __init__(self):
        self.position_deg = 0.0
        self._started = None

    def _now_angle(self):
        if self._started is None:
            return self.position_deg
        return self.position_deg + (time.monotonic() - self._started) * self.SPEED

    def start(self):
        self._started = time.monotonic()

    def stop(self):
        self.position_deg = self._now_angle()
        self._started = None
        time.sleep(0.3)  # 안정화 대기 흉내

    def zero(self):
        self.stop()
        self.position_deg = 0.0

    def rotate(self, deg):
        """정해진 각도만큼 돌고 멈춤 (PatchCore 각도별 촬영용)"""
        time.sleep(abs(deg) / self.SPEED)
        self.position_deg += deg

    def finish_turn(self):
        self.position_deg = 0.0

    def reported_angle(self):
        return self._now_angle()

    def close(self):
        pass


class SimCamera:
    """LatestCamera 와 같은 fresh()/close() 를 가진 가짜 카메라. 저장된 원본 사진을 돌려 가며 보여 준다"""
    def __init__(self, interval=1.5):
        files = sorted(p for p in (ROOT / "captures").rglob("*.jpg") if not p.stem.endswith(("_annotated", "_heatmap")))
        self.frames = []
        for p in files:
            f = imread(p)
            if f is not None and f.shape == (config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3):
                self.frames.append(f)
                if len(self.frames) == 40:
                    break
        if not self.frames:
            raise RuntimeError("시뮬레이션에는 1920×1080 원본 사진이 필요합니다. 작은 사진을 확대하지 않습니다.")
        self.interval = interval
        self.t0 = time.monotonic()

    def fresh(self, after=0.0, timeout=3.0):
        wait = after - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        time.sleep(1 / 30)
        now = time.monotonic()
        index = int((now - self.t0) / self.interval) % len(self.frames)
        return self.frames[index].copy(), now

    def close(self):
        pass


# ---------------------------------------------------------------- 3D 카메라(인텔 2대) 미리보기
def serials_3d():
    """3D 코드 설정(station_3d config.py)의 카메라 시리얼 2개. 읽기만 한다 (파일을 만들거나 고치지 않음)"""
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("cfg3d_readonly", STATION_3D / "config.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    return mod.CAM_A_SERIAL, mod.CAM_B_SERIAL


class RealSensePreview:
    """3D 스캔 전에 인텔 카메라 2대의 컬러 영상을 나란히 보여 준다 (3D 스캔을 시작하기 전에 반드시 close)"""
    TILE = (640, 360)

    def __init__(self, serials):
        import pyrealsense2 as rs
        self.pipes, self.last = [], [None] * len(serials)
        try:
            for serial in serials:
                pipe, cfg = rs.pipeline(), rs.config()
                cfg.enable_device(serial)
                cfg.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 15)
                pipe.start(cfg)
                self.pipes.append(pipe)
        except Exception:
            self.close()
            raise
        self.serials = serials

    def read(self):
        tiles = []
        for i, pipe in enumerate(self.pipes):
            frames = pipe.poll_for_frames()
            if frames:
                color = frames.get_color_frame()
                if color:
                    self.last[i] = np.asanyarray(color.get_data()).copy()
            tile = np.zeros((self.TILE[1], self.TILE[0], 3), np.uint8) if self.last[i] is None \
                else cv2.resize(self.last[i], self.TILE)
            cv2.putText(tile, f"3D camera {'AB'[i]}  {self.serials[i]}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 255), 2)
            tiles.append(tile)
        return np.hstack(tiles)

    def close(self):
        for pipe in self.pipes:
            try:
                pipe.stop()
            except Exception:
                pass
        self.pipes = []


# ---------------------------------------------------------------- DB 저장 (별도 스레드)
class Sender(threading.Thread):
    """검사 루프가 저장 때문에 멈추지 않도록 DB 저장은 이 스레드가 한다"""
    def __init__(self, events):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.events = events
        self.client = None
        self.client_key = None

    def submit(self, db_url, storage_dir, action, **kwargs):
        """action: DBClient 메서드 이름 (start / send_yolo_capture / complete_yolo / check_safety)"""
        self.jobs.put((db_url, storage_dir, action, kwargs))

    def run(self):
        while True:
            db_url, storage_dir, action, kwargs = self.jobs.get()
            try:
                if self.client_key != (db_url, storage_dir):
                    product_names = self.client.product_name if self.client else {}
                    self.client = DBClient(db_url, storage_dir, queue_dir=ROOT / "db_queue")
                    self.client.product_name.update(product_names)  # 진행 중인 검사의 제품명 유지
                    self.client_key = (db_url, storage_dir)
                res = getattr(self.client, action)(**kwargs)
                what = {"start": "검사 시작", "send_patchcore": "PatchCore 판정", "send_yolo_capture": f"결함 사진 {kwargs.get('capture_number')}",
                        "complete_yolo": "YOLO 완료", "check_safety": "안전 상태"}[action]
                if res is None:
                    self.events.put(("log", f"DB 연결 실패 → 대기열에 저장 ({self.client.pending()}건). DB 를 확인하세요"))
                elif action == "check_safety":
                    n = len(res.get("alarms", []))
                    self.events.put(("log", "DB 안전 상태 기록: " + ("정상" if res.get("allowed") else f"이상 → 알람 {n}건 기록")))
                else:
                    self.events.put(("log", f"DB 저장 완료: {what} → {res.get('final_result')}"))
                self.events.put(("pending", self.client.pending()))
            except DBError as exc:
                self.events.put(("log", f"DB 가 거부함: {exc}"))
            except Exception as exc:  # 전송 오류가 검사 프로그램을 멈추지 않게
                self.events.put(("log", f"DB 저장 오류: {exc}"))


# ---------------------------------------------------------------- 검사 루프 (별도 스레드)
class Engine(threading.Thread):
    """카메라·턴테이블·YOLO 를 다루는 스레드. 화면(Tk)은 건드리지 않고 events 큐로만 알린다.
    흐름은 yolo_live.main() 과 같다: 시작 → 연속 회전 → 0.80 이상 결함 → 정지·재검출·저장 → 재회전"""
    def __init__(self, sim, events, sender, mes_settings, safety=lambda: ("UNKNOWN", "UNKNOWN"),
                 gate_3d=True, sim_3d="pass", patchcore_on=lambda: True, patchcore_only=False):
        super().__init__(daemon=True)
        self.patchcore_only = patchcore_only  # True: PatchCore 판정까지만 하고 YOLO 는 하지 않는다
        self.patchcore_on = patchcore_on  # 화면의 [PatchCore 먼저] 체크 상태
        self.patchcore = None             # PatchCoreInspector (불러오기 실패하면 None → PatchCore 검사 보류)
        self.sim = sim
        self.gate_3d = gate_3d  # True: 3D 치수 합격 뒤에만 YOLO 시작
        self.sim_3d = sim_3d    # 시뮬레이션의 가짜 3D 측정 결과 (pass / recheck / fail)
        self.camera = self.table = None
        self.log3d = None           # 3D 출력 전체를 남기는 파일 (captures/3d_logs/)
        self.ready = not gate_3d    # 치수 합격으로 YOLO 검사가 가능한 상태인가
        self.force_yolo_view = False  # [YOLO 카메라 연결]을 눌렀으면 3D 검사 전에도 YOLO 카메라 영상을 보여 줌
        self.preview = None         # 3D 카메라 미리보기 (인텔 2대)
        self.preview_try = 0.0
        self.events = events
        self.sender = sender
        self.mes_settings = mes_settings  # 화면 입력값을 읽어 오는 함수
        # 장비 안전 상태 (센터링, 인터락) 를 돌려주는 함수. 센서가 없어서 지금은 화면에서 작업자가 고른 값.
        # 센서를 붙이면 이 함수만 센서 값을 읽도록 바꾸면 된다 (응답이 끊기면 "UNKNOWN" 을 돌려줄 것)
        self.safety = safety
        self.commands = queue.Queue()
        self.frame_lock = threading.Lock()
        self.view = None        # 화면에 보여 줄 그림
        self.raw = None         # 검사 영역 지정용 원본
        self.stopped = threading.Event()

    def send(self, command, value=None):
        self.commands.put((command, value))

    def latest(self):
        with self.frame_lock:
            return self.view, self.raw

    def _log(self, text):
        self.events.put(("log", text))

    def _state(self, **values):
        self.events.put(("state", values))

    def _open_table(self):
        """턴테이블 연결 (3D 검사 뒤에 다시 연결할 때도 쓴다)"""
        if self.sim:
            self.table = SimTurntable()
        else:
            self.table = live.Turntable(port=config.SERIAL_PORT)
            self.table.stop()  # 이미 회전 중인 보드도 정지 상태로 맞춘다
            if not self.table.continuous:
                self._log("연결된 아두이노는 3D 펌웨어(연속 회전 없음)입니다 → PatchCore 는 그대로, YOLO 는 "
                          f"{YOLO_STEP_DEG:g}도씩 멈춰 가며 검사합니다")
        return self.table

    def _open_camera(self):
        """YOLO 카메라 연결. 아직 안 켜져 있으면 None (아이폰 카메라 등은 나중에 켜도 된다)"""
        if self.camera is not None:
            return self.camera
        try:
            self.camera = SimCamera() if self.sim else live.LatestCamera()
        except (RuntimeError, ValueError) as exc:  # ValueError: 카메라가 1920×1080 이 아닌 크기를 돌려줌
            self.camera = None
            self._log(f"YOLO 카메라(번호 {getattr(config, 'CAMERA_INDEX', 1)})를 열지 못했습니다: {exc}. "
                      "카메라(아이폰 등)를 켠 뒤 [카메라 연결]이나 ② 를 누르세요")
        return self.camera

    def _camera_ready(self, camera, last_frame):
        """카메라를 새로 연결했을 때 검사 영역을 불러오고 화면 갱신용 프레임을 받는다. 반환 (camera, last_frame)"""
        if camera is None:
            return None, last_frame
        frame, last_frame = camera.fresh()
        try:
            live.ROI_NORMALIZED = live.load_roi(frame)
            self._log(live.input_description(frame))
        except ValueError as exc:  # 카메라 크기 또는 config.py 의 ROI_X/ROI_Y 문제
            self._log(f"검사 영역을 쓸 수 없습니다: {exc}")
            self.camera = None
            camera.close()
            return None, last_frame
        self._log("YOLO 카메라 연결 완료: 학습 좌표의 고정 600×320 ROI 적용")
        return camera, last_frame

    def _show_3d_view(self, running):
        """3D 검사 전(치수 합격 전)에는 화면에 3D 카메라 2대 영상을 보여 준다. 시뮬레이션·--no-gate 는 해당 없음"""
        return (not self.sim and self.gate_3d and not self.ready and not self.force_yolo_view and not running)

    def _close_preview(self):
        if self.preview is not None:
            self.preview.close()
            self.preview = None

    def _update_3d_preview(self):
        """인텔 카메라 2대 영상을 화면에 올린다. 못 열면 5초마다 다시 시도"""
        if self.preview is None and time.monotonic() - self.preview_try >= 5:
            self.preview_try = time.monotonic()
            try:
                self.preview = RealSensePreview(serials_3d())
            except Exception as exc:
                self._log(f"3D 카메라 미리보기를 열지 못했습니다: {exc}. USB 3 포트 연결을 확인하세요 (5초 뒤 다시 시도)")
        picture = self.preview.read() if self.preview is not None else self._no_camera_picture("3D cameras not available")
        with self.frame_lock:
            self.view, self.raw = picture, None
        time.sleep(0.03)

    @staticmethod
    def _no_camera_picture(title="YOLO camera not connected"):
        picture = np.full((360, 640, 3), 30, np.uint8)
        cv2.putText(picture, title, (90, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)
        cv2.putText(picture, "turn it on, then press Connect", (110, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1)
        return picture

    def _close_hw(self):
        """연결을 닫는다. 3D 스크립트가 같은 턴테이블 포트·카메라를 쓰기 때문에 3D 검사 동안은 놓아 준다"""
        table, camera = self.table, self.camera
        self.table = self.camera = None
        if table is not None:
            try:
                table.stop()
            except Exception as exc:
                self._log(f"정지 응답 확인 실패: {exc}. 턴테이블 상태를 확인하세요.")
            finally:
                table.close()
        if camera is not None:
            camera.close()

    def run(self):
        try:
            self._log("YOLO 모델 불러오는 중...")
            model = live.YOLO(str(ROOT / "best.pt"))
            names = set(model.names.values())
            if not live.DEFECT_CLASSES.intersection(names):
                raise RuntimeError(f"모델에 결함 클래스가 없습니다: {names}")
            self._load_patchcore()
            table = self._open_table()
            if self.sim:
                self._log("시뮬레이션 모드: captures 사진을 카메라 대신, 가짜 3D 측정값을 사용합니다")
            if self.sim or not self.gate_3d:
                camera, last_frame = self._camera_ready(self._open_camera(), 0.0)
            else:  # 3D 검사 먼저: 화면은 3D 카메라 2대. YOLO(아이폰) 카메라는 치수 합격 뒤에 연결
                camera, last_frame = None, 0.0
                self._log("먼저 [① 3D 검사]를 하세요. 화면에는 3D 카메라 2대 영상이 나옵니다")
            self._refresh_gate()
            self._loop(model, camera, table, last_frame)
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self._close_preview()
            self._close_hw()
            self.stopped.set()

    # ---- 3D 검사 (station_3d 스크립트를 순서대로 실행)
    def _refresh_gate(self):
        """3D 결과(handoff)를 읽어 화면의 3D 결과 표시와 [YOLO 검사] 버튼 활성화를 갱신"""
        handoff = peek_handoff()
        result = handoff.get("dimension_result") if handoff else None
        ready = (not self.gate_3d) or bool(handoff and result == "PASS" and handoff.get("safety_ok") is not False)
        self.ready = ready
        self._state(dimension=DIM_KO.get(result, "-") if handoff else "-", yolo_ready=ready)
        return handoff, ready

    def _run_proc(self, args, cwd, env):
        """프로그램을 실행해 출력 줄을 기록란에 보여 준다. 반환: 종료 코드, [정지]·창 닫기로 끊으면 None"""
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(args, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", creationflags=flags)
        lines = queue.Queue()

        def pump():
            for line in proc.stdout:
                lines.put(line.rstrip())
            lines.put(None)  # 출력 끝

        threading.Thread(target=pump, daemon=True).start()
        while True:
            try:
                command, value = self.commands.get_nowait()
            except queue.Empty:
                command = value = None
            if command == "go3d":  # [배경 촬영]·[스캔 시작] 버튼: 3D 스캔의 Space 대기를 넘긴다
                GO_FILE.parent.mkdir(parents=True, exist_ok=True)
                GO_FILE.write_text("go", encoding="utf-8")
            if command in ("stop", "quit"):
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if command == "quit":
                    self.commands.put((command, value))  # 바깥 루프가 종료하도록 다시 넣는다
                return None
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                return proc.wait()
            if line.startswith("@@WAIT "):  # 3D 스캔이 Space 를 기다리는 중 → 해당 버튼을 켠다
                kind = line.split()[1]
                label, hint = {
                    "background": ("① 배경 촬영", "턴테이블을 비운 뒤 [① 배경 촬영]을 누르세요 (카메라 창에서 Space 도 됨)"),
                    "scan": ("② 스캔 시작", "물체를 턴테이블 중앙에 올린 뒤 [② 스캔 시작]을 누르세요. 누르면 턴테이블이 돌며 스캔합니다"),
                }.get(kind, ("진행", "준비되면 [진행]을 누르세요"))
                self._state(go_label=label)
                self._log("3D 대기: " + hint)
                continue
            if line.startswith("@@GO"):
                self._state(go_label="")
                continue
            if line.strip():
                self._log("  3D | " + line[:160])
                if self.log3d is not None:  # 화면 기록은 지워지므로 3D 출력 전체를 파일에도 남긴다
                    self.log3d.write(line + "\n")
                    self.log3d.flush()

    def _newest_session(self, before):
        scans = STATION_3D / "scans"
        new = [d for d in scans.glob("*") if d.is_dir() and d.name not in before] if scans.is_dir() else []
        return max(new, key=lambda d: d.stat().st_mtime) if new else None

    def _fake_3d_session(self):
        """시뮬레이션: 장비·카메라 없이 가짜 측정 결과(measurement.json)를 만든다 (저장·판정 흐름 시험용)"""
        nominal = getattr(config, "NOMINAL_MM", None) or {"width": 194.50, "depth": 84.96, "height": 58.68}
        offset = {"pass": 0.3, "recheck": 2.0, "fail": 4.0}[self.sim_3d]  # 가로 편차(mm): 정상 한계 1.5 / 불량 한계 2.5
        now = datetime.now().astimezone()
        session = ROOT / "captures" / "sim_3d" / now.strftime("%Y%m%d_%H%M%S")
        session.mkdir(parents=True, exist_ok=True)
        dims = {"width": nominal["width"] + offset, "depth": nominal["depth"] - 0.2, "height": nominal["height"] + 0.1}
        (session / "measurement.json").write_text(json.dumps(
            {"timestamp": now.isoformat(timespec="seconds"), "unit": "mm",
             "dimensions": {k: round(v, 2) for k, v in dims.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return session

    def _scan_3d(self, camera, table, last_frame):
        """[3D 검사]: 안전 확인 → 장비 연결을 3D 에 넘김 → 스캔·병합·측정·DB 저장 → 장비 다시 연결.
        반환: 새 (camera, table, last_frame)"""
        centering, interlock = self.safety()
        if not safety_ok(centering, interlock):
            self._log(f"3D 검사 금지: 센터링 {CENTERING_KO.get(centering, centering)} / "
                      f"인터락 {INTERLOCK_KO.get(interlock, interlock)} → 상태 확인 후 다시 시작하세요")
            self._state(status="시작 불가(안전)")
            self._submit_safety("PRECHECK", centering, interlock, None, "3D 검사 시작 전 확인")
            return camera, table, last_frame
        settings = self.mes_settings()
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "VISIONQC_DB_URL": settings["db_url"],
               "VISIONQC_3D_SERIAL_PORT": config.SERIAL_PORT, "VISIONQC_3D_GO_FILE": str(GO_FILE),
               "VISIONQC_3D_LIMITS": json.dumps(getattr(config, "DIM_LIMITS_3D", {}))}  # 턴테이블은 3D·YOLO 가 같은 아두이노
        bridge = [PYTHON_3D, "-u", str(BRIDGE_3D), "--product", settings["product"],
                  "--centering", centering, "--interlock", interlock]
        if settings["serial"]:
            bridge += ["--serial", settings["serial"]]
        logs = ROOT / "captures" / "3d_logs"
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"{datetime.now():%Y%m%d_%H%M%S}.log"
        self.log3d = open(log_path, "w", encoding="utf-8")
        self._log(f"3D 출력 전체는 파일에도 저장됩니다: {log_path}")
        self._close_preview()  # 3D 스캔이 같은 인텔 카메라를 쓰므로 먼저 놓아 준다
        self.force_yolo_view = False
        self._state(status="3D 검사 중", dimension="-", yolo_ready=False, angle=0.0)
        self._log("3D 검사 시작" + ("" if self.sim else ": 카메라·턴테이블을 3D 스캔에 넘깁니다. 열리는 3D 창의 안내(Space 등)를 따르세요"))
        done = False
        try:
            if self.sim:
                session = self._fake_3d_session()
                self._log(f"  3D | (시뮬레이션) 가짜 측정값 '{self.sim_3d}' 사용: {session.name}")
                done = self._run_proc(bridge + [str(session)], ROOT, env) == 0
            else:
                self._close_hw()
                camera = table = None
                scans = STATION_3D / "scans"
                before = {d.name for d in scans.glob("*")} if scans.is_dir() else set()
                done = self._run_proc([PYTHON_3D, "-u", str(RUN_3D), str(STATION_3D), "turntable_scan.py"], ROOT, env) == 0
                session = self._newest_session(before) if done else None
                for step in ("merge_turntable_scans.py", "measure_object.py"):
                    if not session:
                        break
                    self._log(f"3D 단계: {step}")
                    extra = ["--no-view"] if step.startswith("merge") else []
                    done = self._run_proc([PYTHON_3D, "-u", str(RUN_3D), str(STATION_3D), step, str(session), *extra],
                                          ROOT, env) == 0
                    if not done:
                        break
                done = bool(session) and done and self._run_proc(bridge + [str(session)], ROOT, env) == 0
        finally:
            self._state(go_label="")
            self.log3d.close()
            self.log3d = None
            if not self.sim:
                table = self._open_table()  # 3D 가 놓아 준 턴테이블을 다시 연결. 카메라는 ② 를 누를 때 연결
        handoff, ready = self._refresh_gate()
        if not done:
            self._log("3D 검사가 끝까지 되지 않았습니다 (정지했거나 오류). 위 3D 출력과 DB 연결을 확인하세요")
            self._state(status="3D 실패")
        elif ready:
            self._log(f"3D 치수 합격 ({handoff['inspection_id']}) → [YOLO 검사]를 시작할 수 있습니다")
            self._state(status="3D 완료")
            if camera is None:  # 이미 켜 둔 YOLO 카메라(아이폰 등)가 있으면 연결, 아니면 켠 뒤 [YOLO 카메라 연결]
                camera, last_frame = self._camera_ready(self._open_camera(), last_frame)
        else:
            why = {"FAIL": "치수 불합격", "RECHECK": "치수 재검 (다시 스캔)"}.get((handoff or {}).get("dimension_result"), "판정 없음")
            if handoff and handoff.get("safety_ok") is False:
                why = "측정 때 장비 안전 이상"
            self._log(f"3D 결과: {why} → [YOLO 검사]는 켜지지 않습니다")
            self._state(status="3D 완료")
        return camera, table, last_frame

    def _load_patchcore(self):
        """PatchCore 모델(v3)을 CPU로 불러온다. 실패 시 자동 YOLO 우회는 하지 않는다."""
        self._log("PatchCore 모델 불러오는 중... (CPU, 처음에는 시간이 걸림)")
        try:
            from patchcore_infer import PatchCoreInspector
            self.patchcore = PatchCoreInspector(PATCHCORE_MODEL, device="cpu")
            self._log(f"PatchCore 준비 완료: {self.patchcore.model_path.parent.name} "
                      f"(판정 기준 {self.patchcore.threshold:.3f})")
        except Exception as exc:
            self.patchcore = None
            self._log(f"PatchCore 모델을 불러오지 못했습니다 → PatchCore 검사 보류: {exc}")

    @staticmethod
    def _annotate_score(picture, view, angle, result):
        """히트맵 사진 위에 띠를 붙여 이 사진의 점수와 판정 기준, 합격/불합격을 적고 기준선 막대를 그린다.
        (OpenCV 글꼴은 한글을 못 그려서 영문 표기)"""
        h, w = picture.shape[:2]
        out = np.full((54 + h, w, 3), 255, np.uint8)  # 사진 위에 흰 띠를 붙여서 사진 내용을 가리지 않는다
        out[54:] = picture
        score, threshold = result["score"], result["threshold"]
        bad = result["anomalous"]
        color = (0, 0, 255) if bad else (0, 160, 0)  # BGR: 불합격 빨강 / 합격 초록
        cv2.rectangle(out, (0, 0), (w, 54), (255, 255, 255), -1)
        cv2.putText(out, f"view {view}  angle {angle:.0f}deg", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
        cv2.putText(out, f"score {score:.3f}  threshold {threshold:.3f}  {'FAIL' if bad else 'PASS'}", (8, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        # 점수 막대 (0~1) 와 기준선
        x0, x1, y = int(w * 0.62), w - 10, 30
        cv2.rectangle(out, (x0, y - 8), (x1, y + 8), (200, 200, 200), -1)
        cv2.rectangle(out, (x0, y - 8), (x0 + int((x1 - x0) * min(max(score, 0.0), 1.0)), y + 8), color, -1)
        tx = x0 + int((x1 - x0) * min(max(threshold, 0.0), 1.0))
        cv2.line(out, (tx, y - 14), (tx, y + 14), (0, 0, 0), 2)
        return out

    def _patchcore_crop(self, frame):
        return live.crop_roi(frame)

    def _patchcore_turn(self, camera, table, folder):
        """PatchCore 1단계: 360/VIEWS 도씩 멈춰서 찍고 사진마다 이상 점수를 낸다. 가장 높은 점수로 판정.
        반환 ("done", 최고 점수) / ("stop", None) / ("quit", None)"""
        pc = self.patchcore
        out = folder / "patchcore"
        out.mkdir(parents=True, exist_ok=True)
        step = 360.0 / PATCHCORE_VIEWS
        scores = []
        for i in range(PATCHCORE_VIEWS):
            # 촬영 사이에도 [정지]·창 닫기를 받는다 (검사 영역 변경 등 다른 명령은 무시)
            try:
                command, _ = self.commands.get_nowait()
            except queue.Empty:
                command = None
            if command in ("stop", "quit"):
                if command == "stop":
                    self._log("PatchCore 검사 수동 정지 (이 검사는 DB 에 PatchCore 결과를 저장하지 않음)")
                    self._state(status="정지", angle=table.position_deg)
                return command, None
            # 회전 전 장비 안전 확인. 이상이면 멈추고 보류 + 알람 (자동 재시작 안 함)
            centering, interlock = self.safety()
            if not safety_ok(centering, interlock):
                self._log(f"안전 이상으로 정지·보류: 센터링 {CENTERING_KO.get(centering, centering)} / "
                          f"인터락 {INTERLOCK_KO.get(interlock, interlock)} (자동 재시작 안 함)")
                self._state(status="보류(안전)", angle=table.position_deg)
                self._submit_safety("PATCHCORE", centering, interlock, self.job["inspection_id"], "PatchCore 중 이상 감지")
                return "stop", None
            if i:
                table.rotate(step)
            angle = table.position_deg
            self._state(angle=angle, status=f"PatchCore {i + 1}/{PATCHCORE_VIEWS}")
            frame, _ = camera.fresh(after=time.monotonic() + 0.2)  # 멈춘 뒤의 새 프레임
            roi = self._patchcore_crop(frame)
            result = pc.inspect(roi)
            result["heatmap"] = self._annotate_score(result["heatmap"], i + 1, angle, result)  # 점수·기준을 사진에 적는다
            if i == 0:
                self._log(f"PatchCore frame shape={frame.shape}; ROI shape={roi.shape}; "
                          f"tensor={pc.last_input_shape}; feature input={pc.last_feature_input_shape}")
            scores.append(result["score"])
            stem = out / f"{folder.name}_pc{i + 1:02d}"
            if not (live.imwrite(stem.with_suffix(".jpg"), frame)
                    and live.imwrite(stem.parent / (stem.name + "_roi.png"), roi)
                    and live.imwrite(stem.parent / (stem.name + "_heatmap.jpg"), result["heatmap"])):
                raise RuntimeError("PatchCore 사진 저장 실패")
            stem.with_suffix(".json").write_text(json.dumps(
                {"time": datetime.now().isoformat(), "angle_deg": angle, "view": i + 1,
                 "score": result["score"], "threshold": result["threshold"], "anomalous": result["anomalous"],
                 "crop": "fixed_roi", "roi_normalized": live.ROI_NORMALIZED,
                 "roi_xywh": list(live.roi_bounds()), "frame_shape": list(frame.shape),
                 "roi_shape": list(roi.shape), "input_shape": list(pc.last_input_shape),
                 "feature_input_shape": list(pc.last_feature_input_shape),
                 "model": str(pc.model_path)}, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.frame_lock:
                self.view, self.raw = result["heatmap"], frame
            self._log(f"PatchCore {i + 1}/{PATCHCORE_VIEWS} ({angle:.0f}°): 점수 {result['score']:.3f}"
                      + (" ← 기준 이상" if result["anomalous"] else ""))
            self._state(pc_score=f"{max(scores):.3f} / {pc.threshold:.3f}")
        table.finish_turn()  # 남은 각도를 돌아 0도로
        return "done", max(scores)

    def _begin_job(self, folder, handoff=None):
        """한 바퀴 시작 → DB 에 검사 1회 생성. 설정은 이 순간 값으로 고정 (도중에 화면 값을 바꿔도 섞이지 않게)
        handoff 가 있으면 3D 검사의 검사번호를 이어받아 같은 검사에 결과를 붙인다 (검사 시작 시각도 3D 측정 시각 유지)"""
        self.job = self.mes_settings()
        if handoff:
            self.job["inspection_id"] = handoff["inspection_id"]
            product = handoff.get("product_name") or self.job["product"]
            serial = handoff.get("product_serial") or self.job["serial"] or None
            started = datetime.fromisoformat(handoff["measured_at"])
            consume_handoff(handoff)
            self._log(f"3D 검사 이어받음: {handoff['inspection_id']}")
        else:
            self.job["inspection_id"] = f"{folder.parent.name}_{folder.name}"  # 날짜 포함 새 검사번호
            product, serial, started = self.job["product"], self.job["serial"] or None, datetime.now().astimezone()
        self._state(job=self.job["inspection_id"])
        self._submit("start", product_name=product, product_serial=serial,
                     capture_folder=str(folder), started_at=started)

    def _finish_job(self, captures):
        """한 바퀴 완료 → DB 에 YOLO 분류 완료"""
        # PatchCore 가 불합격이었으면 YOLO 가 결함을 못 찾아도 최종은 불량 (DB 규칙과 같음)
        verdict = "FAIL" if captures or getattr(self, "pc_failed", False) else "PASS"
        self._log(f"한 바퀴 검사 완료: {verdict} / 촬영 {captures}회")
        self._state(status="완료", verdict=verdict, yolo_ready=not self.gate_3d)  # 다음 제품은 3D 부터
        self._submit("complete_yolo")

    def _submit_safety(self, stage, centering, interlock, inspection_id=None, message=None):
        """장비 안전 상태를 DB 에 기록 (이상이면 알람 행 추가). 검사 전이라 job 이 없어도 저장한다"""
        settings = self.mes_settings()
        self.sender.submit(settings["db_url"], settings["storage_dir"], "check_safety", stage=stage,
                           centering=centering, interlock=interlock, inspection_id=inspection_id, message=message)

    def _submit(self, action, **kwargs):
        job = getattr(self, "job", None)
        if not job:
            return
        self.sender.submit(job["db_url"], job["storage_dir"], action, inspection_id=job["inspection_id"], **kwargs)

    def _submit_capture(self, folder, number, found, angle):
        """결함 사진 1장: 원본 + 표시 사진 + 결함 목록"""
        stem = folder / f"{folder.name}_{number:03d}"
        defects = [{"defect_class": d["class"], "confidence": round(d["confidence"], 4),
                    "box": [round(v, 1) for v in d["xyxy"]]} for d in found]
        self._submit("send_yolo_capture", capture_number=number, original=stem.with_suffix(".jpg"),
                     annotated=stem.parent / (stem.name + "_annotated.jpg"), defects=defects,
                     angle_deg=round(angle, 1), captured_at=datetime.now().astimezone())

    def _loop(self, model, camera, table, last_frame):
        running = False
        stepping = False
        last_capture_angle = None
        angle = 0.0
        captures = 0
        folder = None
        last_poll = 0.0
        while True:
            if self._show_3d_view(running):
                self._update_3d_preview()
                result, found = None, []
            elif camera is None:
                self._close_preview()
                time.sleep(0.1)
                result, found = None, []
                with self.frame_lock:
                    self.view, self.raw = self._no_camera_picture(), None
            else:
                self._close_preview()
                frame, last_frame = camera.fresh(after=last_frame)
                # YOLO 는 PatchCore 불합격 뒤(running)나 YOLO 단독 모드에서만 돌린다
                use_yolo = running or not self.patchcore_on()
                result = live.inspect_roi(model, frame) if live.ROI_NORMALIZED and use_yolo else None
                found = live.capture_defects(result) if result is not None else []
                picture = live.annotated_frame(result) if result is not None else frame.copy()
                if result is None:
                    cv2.polylines(picture, [live.roi_polygon(frame)], True, (80, 210, 150), 2)
                with self.frame_lock:
                    self.view, self.raw = picture, frame

            # ---- 버튼 명령 처리
            try:
                command, value = self.commands.get_nowait()
            except queue.Empty:
                command, value = None, None
            if command == "quit":
                return
            if command == "stop":
                if running:
                    table.stop()
                    running = False
                    self._log("검사 수동 정지 (이 검사는 DB 에 YOLO 완료를 저장하지 않음)")
                self._state(status="정지", angle=table.position_deg)
                continue
            if command == "scan3d":
                if not running:
                    camera, table, last_frame = self._scan_3d(camera, table, last_frame)
                continue
            if command == "camera":
                self.force_yolo_view = True
                if camera is None:
                    camera, last_frame = self._camera_ready(self._open_camera(), last_frame)
                continue
            if command == "start" and not running:
                if camera is None:
                    camera, last_frame = self._camera_ready(self._open_camera(), last_frame)
                    if camera is None:
                        continue
                if not live.ROI_NORMALIZED:
                    self._log("config.py의 학습 ROI 시작 좌표를 확인하세요")
                    continue
                # 3D 검사에서 넘어온 검사번호가 있으면 이어받는다. 치수 불합격 제품은 비전 검사를 하지 않음
                # 3D 잠금을 푼 시험 모드(--no-gate, --patchcore-only)는 예전 3D 검사번호에 붙이지 않고 새 검사로 저장한다
                handoff = peek_handoff() if self.gate_3d else None
                if handoff and handoff.get("safety_ok") is False:
                    consume_handoff(handoff)
                    self._log(f"3D 측정 때 장비 안전 이상({handoff['inspection_id']})이라 이어받지 않습니다. 다시 스캔하세요")
                    continue
                if handoff and handoff.get("dimension_result") == "FAIL":
                    consume_handoff(handoff)
                    self._log(f"3D 치수 불합격 제품({handoff['inspection_id']})이라 비전 검사를 하지 않습니다")
                    continue
                if handoff and handoff.get("dimension_result") == "RECHECK":
                    self._log("주의: 3D 치수가 재검입니다. 다시 스캔하기 전까지 최종 결과는 '치수 대기·재검'")
                # 3D 치수 합격 뒤에만 YOLO 검사 (--no-gate 로 풀 수 있음)
                if self.gate_3d and not (handoff and handoff.get("dimension_result") == "PASS"):
                    self._log("먼저 [3D 검사]를 하세요. 치수가 합격이어야 YOLO 검사를 시작할 수 있습니다")
                    self._refresh_gate()
                    continue
                # 장비 안전 사전 확인: 센터링 OFF + 인터락 0 이 아니면 시작하지 않고 DB 에 알람 기록
                centering, interlock = self.safety()
                if not safety_ok(centering, interlock):
                    self._log(f"검사 금지: 센터링 {CENTERING_KO.get(centering, centering)} / "
                              f"인터락 {INTERLOCK_KO.get(interlock, interlock)} → 상태 확인 후 다시 시작하세요")
                    self._state(status="시작 불가(안전)")
                    self._submit_safety("PRECHECK", centering, interlock,
                                        handoff["inspection_id"] if handoff else None, "검사 시작 전 확인")
                    continue
                table.zero()
                folder = live.new_inspection_folder()
                self.pc_failed = False
                self._begin_job(folder, handoff)
                self._state(status="PatchCore 검사 중", angle=0.0, captures=0, verdict="-", pc_score="-",
                            folder=folder.name, yolo_ready=False)

                # ---- 1단계 PatchCore: 설정한 각도(기본 30도)씩 멈춰 찍고 최고 점수로 판정. 합격이면 YOLO 없이 끝
                if self.patchcore is not None and self.patchcore_on():
                    pc = self.patchcore
                    self._log(f"PatchCore 검사 시작: {folder.name} ({PATCHCORE_VIEWS}장, {360 / PATCHCORE_VIEWS:g}도씩)")
                    self._submit_safety("PATCHCORE", centering, interlock, self.job["inspection_id"], "검사 시작 시 정상")
                    outcome, score = self._patchcore_turn(camera, table, folder)
                    if outcome == "quit":
                        return
                    if outcome == "stop":
                        continue
                    self._submit("send_patchcore", score=score, threshold=pc.threshold, model_version=pc.version)
                    if score < pc.threshold:
                        self._log(f"PatchCore 합격 (최고 점수 {score:.3f} < 기준 {pc.threshold:.3f}) → YOLO 생략, 검사 완료")
                        self._state(status="완료", verdict="PASS", angle=0.0, yolo_ready=not self.gate_3d)
                        continue
                    self.pc_failed = True
                    if self.patchcore_only:
                        self._log(f"PatchCore 불합격 (최고 점수 {score:.3f} ≥ 기준 {pc.threshold:.3f}) → PatchCore 전용 모드라 YOLO 는 하지 않음")
                        self._state(status="완료", verdict="FAIL", angle=0.0, yolo_ready=not self.gate_3d)
                        continue
                    self._log(f"PatchCore 불합격 (최고 점수 {score:.3f} ≥ 기준 {pc.threshold:.3f}) → YOLO 로 결함 확인")
                    self._state(verdict="PatchCore 불합격")
                    centering, interlock = self.safety()
                    if not safety_ok(centering, interlock):
                        self._log("안전 이상으로 YOLO 를 시작하지 않습니다 (보류)")
                        self._state(status="보류(안전)")
                        self._submit_safety("YOLO", centering, interlock, self.job["inspection_id"], "YOLO 시작 전 이상")
                        continue
                elif self.patchcore_on():
                    self._log("PatchCore 모델이 없어 검사를 보류합니다. 자동으로 YOLO를 실행하지 않습니다.")
                    self._state(status="PatchCore 준비 필요")
                    continue

                # ---- 2단계 YOLO: 연속 회전하며 결함 종류·위치 촬영
                captures, last_capture_angle, angle = 0, None, 0.0
                stepping = not getattr(table, "continuous", True)  # 3D 펌웨어: 연속 회전이 없어 한 칸씩
                if not stepping:
                    table.start()
                running = True
                last_poll = 0.0
                last_frame = time.monotonic()  # 시작 전 정지 영상으로 검출하지 않도록
                self._log(f"YOLO 한 바퀴 검사 시작: {folder.name}")
                self._submit_safety("YOLO", centering, interlock, self.job["inspection_id"], "YOLO 시작 시 정상")
                self._state(status="YOLO 검사 중", angle=0.0)
                continue
            if not running:
                continue

            if stepping:
                # ---- 단계 모드: 한 칸 돌고(안정화까지 기다림) → 멈춘 영상으로 검사 → 다음 칸
                centering, interlock = self.safety()
                if not safety_ok(centering, interlock):
                    running = False
                    self._log(f"안전 이상으로 정지·보류: 센터링 {CENTERING_KO.get(centering, centering)} / "
                              f"인터락 {INTERLOCK_KO.get(interlock, interlock)} (자동 재시작 안 함)")
                    self._state(status="보류(안전)", angle=table.position_deg)
                    self._submit_safety("YOLO", centering, interlock, self.job["inspection_id"], "검사 중 이상 감지")
                    continue
                angle = table.position_deg
                self._state(angle=angle)
                if found and live.capture_allowed(angle, last_capture_angle):
                    stopped_frame, last_frame = camera.fresh(after=time.monotonic() + 0.2)
                    stopped_result = live.inspect_roi(model, stopped_frame)
                    confirmed = live.capture_defects(stopped_result)
                    if confirmed:
                        captures += 1
                        live.save_capture(stopped_frame, stopped_result, angle, folder, captures)
                        self._log(f"결함 촬영 {captures}: " + ", ".join(
                            f"{d['class']} {d['confidence']:.2f}" for d in confirmed))
                        self._state(captures=captures)
                        self._submit_capture(folder, captures, confirmed, angle)
                    last_capture_angle = angle
                if angle >= 360.0 - 1e-6:
                    table.finish_turn()
                    running = False
                    self._finish_job(captures)
                    continue
                table.rotate(min(YOLO_STEP_DEG, 360.0 - angle))
                last_frame = time.monotonic()  # 돌린 뒤의 새 영상으로 검사
                continue

            # ---- 회전 각도 확인 + 검사 중 장비 안전 확인 (0.5초마다)
            if time.monotonic() - last_poll >= 0.5:
                centering, interlock = self.safety()
                if not safety_ok(centering, interlock):
                    # 이상 감지 → 장비 정지 → 검사 보류 → 알람 저장. 상태가 돌아와도 자동으로 다시 돌지 않음
                    table.stop()
                    running = False
                    self._log(f"안전 이상으로 정지·보류: 센터링 {CENTERING_KO.get(centering, centering)} / "
                              f"인터락 {INTERLOCK_KO.get(interlock, interlock)} (자동 재시작 안 함)")
                    self._state(status="보류(안전)", angle=table.position_deg)
                    self._submit_safety("YOLO", centering, interlock, self.job["inspection_id"], "검사 중 이상 감지")
                    continue
                angle = table.reported_angle()
                last_poll = time.monotonic()
                self._state(angle=angle)
                if angle >= 360.0:
                    table.stop()
                    running = False
                    self._finish_job(captures)
                    continue

            # ---- 결함 발견 → 정지 → 새 프레임으로 재검출 → 저장
            if found and live.capture_allowed(angle, last_capture_angle):
                table.stop()
                running = False
                stopped_frame, last_frame = camera.fresh(after=time.monotonic() + 0.2)
                stopped_result = live.inspect_roi(model, stopped_frame)
                confirmed = live.capture_defects(stopped_result)
                if confirmed:
                    captures += 1
                    # 원본, 표시 사진, json 저장 (yolo_live 와 같은 파일 구성). DB 저장 때 원본과 표시 사진을 MES 사진 폴더로 복사
                    live.save_capture(stopped_frame, stopped_result, table.position_deg, folder, captures)
                    self._log(f"결함 촬영 {captures}: " + ", ".join(
                        f"{d['class']} {d['confidence']:.2f}" for d in confirmed))
                    self._state(captures=captures)
                    self._submit_capture(folder, captures, confirmed, table.position_deg)
                else:
                    self._log("정지 후 신뢰도 0.80 이상 결함 없음: 저장 없이 계속")
                last_capture_angle = angle = table.position_deg
                last_poll = 0.0
                if table.position_deg >= 360.0:
                    self._finish_job(captures)
                else:
                    table.start()
                    running = True
                    last_frame = time.monotonic()


# ---------------------------------------------------------------- 화면
class App:
    def __init__(self, root, sim, gate_3d=True, sim_3d="pass", patchcore_only=False):
        self.root = root
        self.events = queue.Queue()
        self.sender = Sender(self.events)
        self.sender.start()
        self._patchcore_on = True
        self.engine = Engine(sim, self.events, self.sender, self.mes_settings, self.safety_state, gate_3d, sim_3d,
                             lambda: self._patchcore_on, patchcore_only)
        self.yolo_ready = not gate_3d
        self.photo = None
        self.view_scale = 1.0
        self._mes_cache = {}

        self.sim = sim
        root.title("VisionQC 검사" + (" (시뮬레이션)" if sim else ""))
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._build()
        self._read_mes_fields()
        self.engine.start()
        self.root.after(30, self._tick)

    # ---- 화면 구성
    def _build(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(main, width=VIEW_MAX[0] * 2 // 3, height=VIEW_MAX[1] * 2 // 3,
                                bg="#1e1e1e", highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        side = ttk.Frame(main, padding=(10, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")

        box = ttk.LabelFrame(side, text="검사", padding=8)
        box.pack(fill="x")
        self.btn_3d = ttk.Button(box, text="① 3D 검사", command=lambda: self.engine.send("scan3d"))
        self.btn_go = ttk.Button(box, text="3D 진행 버튼 (스캔 중 켜짐)", command=lambda: self.engine.send("go3d"))
        self.btn_start = ttk.Button(box, text="② ▶ 검사 시작 (PatchCore → YOLO)", command=lambda: self.engine.send("start"))
        self.btn_stop = ttk.Button(box, text="■ 정지", command=lambda: self.engine.send("stop"))
        self.btn_roi = ttk.Button(box, text="고정 검사 영역 확인", command=self.begin_roi)
        self.btn_cam = ttk.Button(box, text="YOLO 카메라 연결", command=lambda: self.engine.send("camera"))
        for b in (self.btn_3d, self.btn_go, self.btn_start, self.btn_stop, self.btn_roi, self.btn_cam):
            b.pack(fill="x", pady=2)
        self.go_label = ""
        ttk.Label(box, text="3D 치수가 합격이면 ② 가 켜집니다", foreground="#6b7686").pack(anchor="w")
        # 끄면 PatchCore 없이 YOLO 만 (YOLO 단독 모드). 검사 시작 순간의 값으로 정해진다
        self.pc_var = tk.BooleanVar(value=True)
        self.pc_var.trace_add("write", lambda *_: setattr(self, "_patchcore_on", bool(self.pc_var.get())))
        ttk.Checkbutton(box, text=f"PatchCore 먼저 ({PATCHCORE_VIEWS}장)", variable=self.pc_var).pack(anchor="w", pady=(4, 0))

        info = ttk.LabelFrame(side, text="상태", padding=8)
        info.pack(fill="x", pady=(8, 0))
        self.vars = {k: tk.StringVar(value=v) for k, v in
                     dict(status="연결 중", dimension="-", angle="0.0°", pc_score="-", captures="0", verdict="-", folder="-", job="-", pending="0").items()}
        for label, key in (("상태", "status"), ("3D 치수", "dimension"), ("각도", "angle"), ("PC 점수", "pc_score"), ("결함 촬영", "captures"),
                           ("판정", "verdict"), ("검사 폴더", "folder"), ("검사번호", "job"), ("DB 대기", "pending")):
            r = ttk.Frame(info)
            r.pack(fill="x")
            ttk.Label(r, text=label, width=9).pack(side="left")
            ttk.Label(r, textvariable=self.vars[key]).pack(side="left")

        # 장비 안전 상태: 센서가 아직 없어서 작업자가 확인 후 고른다. 미확인이면 검사를 시작할 수 없다.
        # (검사 중에 이상으로 바꾸면 즉시 정지·보류되고 DB 에 알람이 남는다)
        safe = ttk.LabelFrame(side, text="장비 안전 상태", padding=8)
        safe.pack(fill="x", pady=(8, 0))
        self.safety_vars = {}
        default = ("OFF", "0") if self.sim else ("UNKNOWN", "UNKNOWN")  # 시뮬레이션은 정상으로 시작
        for label, key, choices, value in (
                ("센터링", "centering", [("UNKNOWN", "미확인"), ("OFF", "OFF 정위치"), ("ON", "ON 위치 이상")], default[0]),
                ("인터락", "interlock", [("UNKNOWN", "미확인"), ("0", "0 정상"), ("1", "1 비정상")], default[1])):
            r = ttk.Frame(safe)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=label, width=9).pack(side="left")
            names = [n for _, n in choices]
            var = tk.StringVar(value=dict(choices)[value])
            box = ttk.Combobox(r, textvariable=var, values=names, state="readonly", width=16)
            box.pack(side="left")
            var.trace_add("write", lambda *_: self._read_safety())
            self.safety_vars[key] = (var, {n: c for c, n in choices})
        ttk.Label(safe, text="센터링 OFF + 인터락 0 일 때만 검사", foreground="#6b7686").pack(anchor="w", pady=(4, 0))
        self._read_safety()

        mes = ttk.LabelFrame(side, text="DB 저장 (MES 는 DB 에서 읽음)", padding=8)
        mes.pack(fill="x", pady=(8, 0))
        self.mes_vars = {}
        for label, key, value in (("DB 주소", "db_url", DB_URL), ("사진 폴더", "storage_dir", STORAGE_DIR),
                                  ("제품 모델", "product", PRODUCT), ("제품 번호", "serial", "")):
            r = ttk.Frame(mes)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=label, width=9).pack(side="left")
            var = tk.StringVar(value=value)
            var.trace_add("write", lambda *_: self._read_mes_fields())
            ttk.Entry(r, textvariable=var, width=26).pack(side="left")
            self.mes_vars[key] = var

        logbox = ttk.LabelFrame(main, text="기록", padding=4)
        logbox.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.log = tk.Listbox(logbox, height=8)
        self.log.pack(fill="both", expand=True)

    # ---- DB 저장 설정 (Tk 변수는 화면 스레드에서만 읽고, 검사 스레드에는 복사본을 준다)
    def _read_mes_fields(self):
        self._mes_cache = {k: v.get().strip() for k, v in getattr(self, "mes_vars", {}).items()}

    def mes_settings(self):
        return dict(self._mes_cache)

    # ---- 장비 안전 상태 (화면에서 고른 값 → 검사 스레드에는 복사본)
    def _read_safety(self):
        self._safety_cache = tuple(codes[var.get()] for var, codes in
                                   (self.safety_vars["centering"], self.safety_vars["interlock"]))

    def safety_state(self):
        return getattr(self, "_safety_cache", ("UNKNOWN", "UNKNOWN"))

    def add_log(self, text):
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}")
        if self.log.size() > 600:
            self.log.delete(0, self.log.size() - 600)
        self.log.see("end")

    # ---- 학습 좌표 확인 (임의 다각형 ROI 로 바꾸지 않는다)
    def begin_roi(self):
        messagebox.showinfo("고정 ROI", "ROI 크기: 가로 600 × 세로 320\n"
                            f"시작 좌표: x={config.ROI_X}, y={config.ROI_Y}\n"
                            "위치 변경은 config.py의 ROI_X / ROI_Y를 학습 당시 값으로 설정한 뒤 재시작하세요.")

    def _sync_buttons(self):
        """버튼 잠금: 검사 영역 지정 중엔 전부 잠금. 3D·YOLO 검사 중엔 시작 버튼 잠금. YOLO 는 치수 합격 뒤에만"""
        status = self.vars["status"].get()
        busy = status in BUSY or status.startswith("PatchCore ")
        locked = False
        enabled = {self.btn_3d: not locked and not busy,
                   self.btn_go: not locked and bool(self.go_label),
                   self.btn_start: not locked and not busy and self.yolo_ready,
                   self.btn_stop: not locked, self.btn_roi: not locked and not busy,
                   self.btn_cam: not locked and not busy}
        for b, ok in enabled.items():
            b.state(["!disabled"] if ok else ["disabled"])

    # ---- 화면 갱신
    def _tick(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.add_log(value)
            elif kind == "state":
                for k, v in value.items():
                    if k == "yolo_ready":
                        self.yolo_ready = bool(v)
                    elif k == "go_label":
                        self.go_label = v
                        self.btn_go.config(text=v or "3D 진행 버튼 (스캔 중 켜짐)")
                    else:
                        self.vars[k].set(f"{v:.1f}°" if k == "angle" else str(v))
            elif kind == "pending":
                self.vars["pending"].set(str(value))
            elif kind == "error":
                self.add_log(f"오류: {value}")
                self.vars["status"].set("오류")
                messagebox.showerror("VisionQC", value)
        if self.vars["status"].get() == "연결 중" and self.engine.latest()[0] is not None:
            self.vars["status"].set("대기")

        self._sync_buttons()
        picture = self.engine.latest()[0]
        if picture is not None:
            self._show(picture)
        self.root.after(30, self._tick)

    def _show(self, picture):
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        h, w = picture.shape[:2]
        scale = min(cw / w, ch / h)
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        rgb = cv2.cvtColor(cv2.resize(picture, size), cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    def quit(self):
        self.engine.send("quit")
        self.engine.stopped.wait(timeout=5)
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="VisionQC 버튼 검사 프로그램")
    ap.add_argument("--sim", action="store_true", help="카메라·턴테이블 없이 captures 사진으로 시험 (3D 는 가짜 측정값)")
    ap.add_argument("--sim-3d", choices=["pass", "recheck", "fail"], default="pass", help="--sim 일 때 가짜 3D 치수 결과")
    ap.add_argument("--no-gate", action="store_true", help="3D 검사 없이 [검사 시작]을 바로 누를 수 있게 함 (시험용)")
    ap.add_argument("--patchcore-only", action="store_true", help="PatchCore 만 실행 (3D 검사·YOLO 없이. 판정까지만)")
    args = ap.parse_args()
    root = tk.Tk()
    root.geometry("1100x760")
    only = args.patchcore_only
    App(root, args.sim, gate_3d=not (args.no_gate or only), sim_3d=args.sim_3d, patchcore_only=only)
    root.mainloop()


if __name__ == "__main__":
    main()
