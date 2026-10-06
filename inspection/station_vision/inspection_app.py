"""
inspection_app.py — 버튼으로 조작하는 턴테이블 + YOLO 검사 프로그램

yolo_live.py 의 검사 로직(검사 영역, YOLO 검출, 정지·재촬영, 사진 저장)을 그대로 쓰고
키보드 대신 화면 버튼으로 조작한다. 검사 결과는 mes_client.py 로 MES 서버에 보낸다.

    python inspection_app.py          # 실제 카메라 + 턴테이블
    python inspection_app.py --sim    # 장비 없이 시험 (captures 사진을 카메라 대신 사용)

MES 전송 (MES 는 검사 1회 = product_inspection 1행)
    - 한 바퀴 검사 1회 = MES 검사 1회. 검사번호 = 날짜_검사폴더이름 (예: 20261006_inspection_143000_001)
    - [검사 시작]  → 검사 행 생성 (제품 모델명, 제품 식별번호, 사진 폴더)
    - 결함 사진 저장 → 원본 + 표시 사진 + 결함 목록 (yolo_defect_data, image_files 에 추가)
    - 한 바퀴 완료  → YOLO 분류 완료 (yolo_status = COMPLETED)
    - 수동 정지로 중간에 끝낸 검사는 완료를 보내지 않는다 (YOLO 진행 중으로 남음)
    - 서버가 꺼져 있으면 mes_queue 폴더에 쌓아 두었다가 다음 전송 때 순서대로 다시 보낸다
    최종 결과(final_result)는 MES 가 3D 치수 → PatchCore → YOLO 결과로 자동 계산한다.
    이 프로그램은 YOLO 단계만 보내므로, 3D 치수·PatchCore 결과가 들어오기 전까지는 '치수 검사 대기'로 보인다.
설정값(MES_URL, MES_API_KEY, MES_PRODUCT)은 config.py 에 적으면 그 값을 쓰고,
없으면 아래 기본값을 쓴다. 화면에서도 바꿀 수 있다.
"""
import argparse
import json
import queue
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
# 공용 모듈(inspection/common/mes_client.py)을 import 할 수 있게 경로 추가
sys.path.insert(0, str(ROOT.parent / "common"))

import config  # noqa: E402
import yolo_live as live  # noqa: E402
from mes_client import MESClient, MESError  # noqa: E402

MES_URL = getattr(config, "MES_URL", "http://127.0.0.1:8000")
MES_API_KEY = getattr(config, "MES_API_KEY", "change-this-ingest-key")
MES_PRODUCT = getattr(config, "MES_PRODUCT", "redcar")   # 제품 모델명 (MES 의 product_name)
VIEW_MAX = (960, 720)  # 화면에 보여 줄 영상 최대 크기
# 3D 검사(bridge_3d/send_3d_to_mes.py)가 남긴 검사번호. 이어받으면 consumed=true 로 바꿔 두 번 쓰지 않는다
HANDOFF = ROOT.parent / "handoff" / "latest.json"


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

    def reported_angle(self):
        return self._now_angle()

    def close(self):
        pass


class SimCamera:
    """LatestCamera 와 같은 fresh()/close() 를 가진 가짜 카메라. 저장된 원본 사진을 돌려 가며 보여 준다"""
    def __init__(self, interval=1.5):
        files = sorted(p for p in (ROOT / "captures").rglob("*.jpg") if "_annotated" not in p.stem)
        self.frames = [f for f in (imread(p) for p in files[:40]) if f is not None]
        if not self.frames:
            raise RuntimeError("시뮬레이션에 쓸 사진이 captures 폴더에 없습니다")
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


# ---------------------------------------------------------------- MES 전송 (별도 스레드)
class Sender(threading.Thread):
    """검사 루프가 전송 때문에 멈추지 않도록 MES 전송은 이 스레드가 한다"""
    def __init__(self, events):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.events = events
        self.client = None
        self.client_key = None

    def submit(self, url, api_key, action, **kwargs):
        """action: MESClient 메서드 이름 (start / send_yolo_capture / complete_yolo)"""
        self.jobs.put((url, api_key, action, kwargs))

    def run(self):
        while True:
            url, api_key, action, kwargs = self.jobs.get()
            try:
                if self.client_key != (url, api_key):
                    product_names = self.client.product_name if self.client else {}
                    self.client = MESClient(url, api_key, queue_dir=ROOT / "mes_queue")
                    self.client.product_name.update(product_names)  # 진행 중인 검사의 제품명 유지
                    self.client_key = (url, api_key)
                res = getattr(self.client, action)(**kwargs)
                what = {"start": "검사 시작", "send_yolo_capture": f"결함 사진 {kwargs.get('capture_number')}",
                        "complete_yolo": "YOLO 완료"}[action]
                if res is None:
                    self.events.put(("log", f"MES 연결 실패 → 대기열에 저장 ({self.client.pending()}건 대기)"))
                else:
                    self.events.put(("log", f"MES 전송 완료: {what} → {res.get('final_result')}"))
                self.events.put(("pending", self.client.pending()))
            except MESError as exc:
                self.events.put(("log", f"MES 가 거부함: {exc}"))
            except Exception as exc:  # 전송 오류가 검사 프로그램을 멈추지 않게
                self.events.put(("log", f"MES 전송 오류: {exc}"))


# ---------------------------------------------------------------- 검사 루프 (별도 스레드)
class Engine(threading.Thread):
    """카메라·턴테이블·YOLO 를 다루는 스레드. 화면(Tk)은 건드리지 않고 events 큐로만 알린다.
    흐름은 yolo_live.main() 과 같다: 시작 → 연속 회전 → 0.80 이상 결함 → 정지·재검출·저장 → 재회전"""
    def __init__(self, sim, events, sender, mes_settings):
        super().__init__(daemon=True)
        self.sim = sim
        self.events = events
        self.sender = sender
        self.mes_settings = mes_settings  # 화면 입력값을 읽어 오는 함수
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

    def run(self):
        camera = table = None
        try:
            self._log("YOLO 모델 불러오는 중...")
            model = live.YOLO(str(ROOT / "best.pt"))
            names = set(model.names.values())
            if not live.DEFECT_CLASSES.intersection(names):
                raise RuntimeError(f"모델에 결함 클래스가 없습니다: {names}")
            if self.sim:
                camera, table = SimCamera(), SimTurntable()
                self._log("시뮬레이션 모드: captures 사진을 카메라 대신 사용합니다")
            else:
                camera = live.LatestCamera()
                table = live.Turntable(port=config.SERIAL_PORT)
                table.stop()  # 이미 회전 중인 보드도 정지 상태로 맞춘다
            frame, last_frame = camera.fresh()
            live.ROI_NORMALIZED = live.load_roi(frame)
            self._log("연결 완료" + ("" if live.ROI_NORMALIZED else " - [검사 영역 설정]을 먼저 하세요"))
            self._loop(model, camera, table, last_frame)
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            if table is not None:
                try:
                    table.stop()
                except Exception as exc:
                    self._log(f"정지 응답 확인 실패: {exc}. 턴테이블 상태를 확인하세요.")
                finally:
                    table.close()
            if camera is not None:
                camera.close()
            self.stopped.set()

    def _begin_job(self, folder, handoff=None):
        """한 바퀴 시작 → MES 에 검사 1회 생성. 설정은 이 순간 값으로 고정 (도중에 화면 값을 바꿔도 섞이지 않게)
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
        """한 바퀴 완료 → MES 에 YOLO 분류 완료"""
        verdict = "FAIL" if captures else "PASS"
        self._log(f"한 바퀴 검사 완료: {verdict} / 촬영 {captures}회")
        self._state(status="완료", verdict=verdict)
        self._submit("complete_yolo")

    def _submit(self, action, **kwargs):
        job = getattr(self, "job", None)
        if not job or not job["enabled"]:
            return
        self.sender.submit(job["url"], job["api_key"], action, inspection_id=job["inspection_id"], **kwargs)

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
        last_capture_angle = None
        angle = 0.0
        captures = 0
        folder = None
        last_poll = 0.0
        while True:
            frame, last_frame = camera.fresh(after=last_frame)
            result = live.inspect_roi(model, frame) if live.ROI_NORMALIZED else None
            found = live.capture_defects(result) if result is not None else []
            picture = live.annotated_frame(result) if result is not None else frame.copy()
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
                    self._log("검사 수동 정지 (이 검사는 MES 에 YOLO 완료를 보내지 않음)")
                self._state(status="정지", angle=table.position_deg)
                continue
            if command == "roi":
                live.ROI_NORMALIZED = value
                self._log("검사 영역을 적용했습니다")
                self._state(status="대기")
                continue
            if command == "start" and not running:
                if not live.ROI_NORMALIZED:
                    self._log("[검사 영역 설정]을 먼저 하세요")
                    continue
                # 3D 검사에서 넘어온 검사번호가 있으면 이어받는다. 치수 불합격 제품은 비전 검사를 하지 않음
                handoff = peek_handoff()
                if handoff and handoff.get("dimension_result") == "FAIL":
                    consume_handoff(handoff)
                    self._log(f"3D 치수 불합격 제품({handoff['inspection_id']})이라 비전 검사를 하지 않습니다")
                    continue
                if handoff and handoff.get("dimension_result") == "RECHECK":
                    self._log("주의: 3D 치수가 재검입니다. 다시 스캔하기 전까지 MES 최종 결과는 '치수 대기·재검'")
                table.zero()
                folder = live.new_inspection_folder()
                captures, last_capture_angle, angle = 0, None, 0.0
                table.start()
                running = True
                last_poll = 0.0
                last_frame = time.monotonic()  # 시작 전 정지 영상으로 검출하지 않도록
                self._log(f"한 바퀴 검사 시작: {folder.name}")
                self._begin_job(folder, handoff)
                self._state(status="검사 중", angle=0.0, captures=0, verdict="-", folder=folder.name)
                continue
            if not running:
                continue

            # ---- 회전 각도 확인
            if time.monotonic() - last_poll >= 0.5:
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
                    # 원본, 표시 사진, json 저장 (yolo_live 와 같은 파일 구성). MES 에는 원본과 표시 사진을 보낸다
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
    def __init__(self, root, sim):
        self.root = root
        self.events = queue.Queue()
        self.sender = Sender(self.events)
        self.sender.start()
        self.engine = Engine(sim, self.events, self.sender, self.mes_settings)
        self.editing = False     # 검사 영역 지정 중
        self.edit_frame = None
        self.points = []
        self.photo = None
        self.view_scale = 1.0
        self._mes_cache = {}

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
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Button-3>", self._undo)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        side = ttk.Frame(main, padding=(10, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")

        box = ttk.LabelFrame(side, text="검사", padding=8)
        box.pack(fill="x")
        self.btn_start = ttk.Button(box, text="▶ 검사 시작", command=lambda: self.engine.send("start"))
        self.btn_stop = ttk.Button(box, text="■ 정지", command=lambda: self.engine.send("stop"))
        self.btn_roi = ttk.Button(box, text="검사 영역 설정", command=self.begin_roi)
        for b in (self.btn_start, self.btn_stop, self.btn_roi):
            b.pack(fill="x", pady=2)

        self.roi_box = ttk.LabelFrame(side, text="검사 영역 설정", padding=8)
        ttk.Label(self.roi_box, text="영상에서 가장자리를 순서대로 클릭\n우클릭: 마지막 점 취소",
                  justify="left").pack(anchor="w")
        row = ttk.Frame(self.roi_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="저장", command=self.save_roi).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="초기화", command=lambda: self.points.clear()).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="취소", command=self.end_roi).pack(side="left", expand=True, fill="x")

        info = ttk.LabelFrame(side, text="상태", padding=8)
        info.pack(fill="x", pady=(8, 0))
        self.vars = {k: tk.StringVar(value=v) for k, v in
                     dict(status="연결 중", angle="0.0°", captures="0", verdict="-", folder="-", job="-", pending="0").items()}
        for label, key in (("상태", "status"), ("각도", "angle"), ("결함 촬영", "captures"),
                           ("판정", "verdict"), ("검사 폴더", "folder"), ("검사번호", "job"), ("MES 대기", "pending")):
            r = ttk.Frame(info)
            r.pack(fill="x")
            ttk.Label(r, text=label, width=9).pack(side="left")
            ttk.Label(r, textvariable=self.vars[key]).pack(side="left")

        mes = ttk.LabelFrame(side, text="MES 전송", padding=8)
        mes.pack(fill="x", pady=(8, 0))
        self.mes_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(mes, text="검사 결과를 MES 로 보내기", variable=self.mes_enabled,
                        command=self._read_mes_fields).pack(anchor="w")
        self.mes_vars = {}
        for label, key, value in (("서버", "url", MES_URL), ("API 키", "api_key", MES_API_KEY),
                                  ("제품 모델", "product", MES_PRODUCT), ("제품 번호", "serial", "")):
            r = ttk.Frame(mes)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=label, width=9).pack(side="left")
            var = tk.StringVar(value=value)
            var.trace_add("write", lambda *_: self._read_mes_fields())
            ttk.Entry(r, textvariable=var, width=26, show="*" if key == "api_key" else "").pack(side="left")
            self.mes_vars[key] = var

        logbox = ttk.LabelFrame(main, text="기록", padding=4)
        logbox.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.log = tk.Listbox(logbox, height=8)
        self.log.pack(fill="both", expand=True)

    # ---- MES 설정 (Tk 변수는 화면 스레드에서만 읽고, 검사 스레드에는 복사본을 준다)
    def _read_mes_fields(self):
        values = {k: v.get().strip() for k, v in getattr(self, "mes_vars", {}).items()}
        values["enabled"] = self.mes_enabled.get() if hasattr(self, "mes_enabled") else True
        self._mes_cache = values

    def mes_settings(self):
        return dict(self._mes_cache)

    def add_log(self, text):
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}")
        self.log.see("end")

    # ---- 검사 영역 지정 (yolo_live.select_roi 를 화면 안에서 하는 버전)
    def begin_roi(self):
        self.engine.send("stop")
        _, raw = self.engine.latest()
        if raw is None:
            return
        self.edit_frame = raw.copy()
        self.points.clear()
        self.editing = True
        self.roi_box.pack(fill="x", pady=(8, 0), after=self.btn_roi.master)
        for b in (self.btn_start, self.btn_stop, self.btn_roi):
            b.state(["disabled"])

    def end_roi(self):
        self.editing = False
        self.roi_box.pack_forget()
        for b in (self.btn_start, self.btn_stop, self.btn_roi):
            b.state(["!disabled"])

    def save_roi(self):
        try:
            selected = live.validate_roi(self.points)
            live.save_roi(selected, self.edit_frame)
        except (ValueError, OSError) as exc:
            messagebox.showwarning("검사 영역", str(exc))
            return
        self.engine.send("roi", selected)
        self.end_roi()

    def _click(self, event):
        if self.editing and self.photo is not None:
            w, h = self.photo.width(), self.photo.height()
            if 0 <= event.x < w and 0 <= event.y < h:
                self.points.append((event.x / (w - 1), event.y / (h - 1)))

    def _undo(self, _event):
        if self.editing and self.points:
            self.points.pop()

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
                    self.vars[k].set(f"{v:.1f}°" if k == "angle" else str(v))
            elif kind == "pending":
                self.vars["pending"].set(str(value))
            elif kind == "error":
                self.add_log(f"오류: {value}")
                self.vars["status"].set("오류")
                messagebox.showerror("VisionQC", value)
        if self.vars["status"].get() == "연결 중" and self.engine.latest()[0] is not None:
            self.vars["status"].set("대기")

        picture = self._roi_preview() if self.editing else self.engine.latest()[0]
        if picture is not None:
            self._show(picture)
        self.root.after(30, self._tick)

    def _roi_preview(self):
        picture = self.edit_frame.copy()
        h, w = picture.shape[:2]
        if self.points:
            vertices = np.array([(round(x * (w - 1)), round(y * (h - 1))) for x, y in self.points], np.int32)
            if len(self.points) >= 3:
                overlay = picture.copy()
                cv2.fillPoly(overlay, [vertices], (80, 210, 150))
                picture = cv2.addWeighted(overlay, 0.2, picture, 0.8, 0)
            cv2.polylines(picture, [vertices], len(self.points) >= 3, (80, 210, 150), 2)
            for v in vertices:
                cv2.circle(picture, tuple(int(c) for c in v), 5, (80, 210, 150), -1)
        return picture

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
    ap.add_argument("--sim", action="store_true", help="카메라·턴테이블 없이 captures 사진으로 시험")
    args = ap.parse_args()
    root = tk.Tk()
    root.geometry("1100x760")
    App(root, args.sim)
    root.mainloop()


if __name__ == "__main__":
    main()
