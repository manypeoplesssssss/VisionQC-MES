"""
F08 검사 PC 연동 클라이언트 테스트 (vision_client/test_mes_client.py)   담당 B

MES 서버 없이, 이 파일 안에서 가짜 서버를 띄워서 mes_client 의 동작을 확인한다.
  pip install requests pytest numpy
  cd vision_client
  pytest -v

확인하는 것
  - 서버가 꺼져 있으면 큐에 쌓이고, 켜지면 오래된 순서대로 재전송 (검사 시각은 처음 값 유지)
  - 검사 시각을 직접 넘기면 그대로 전송, 치수는 소수 3자리
  - 서버가 형식 오류(4xx)로 거부하면 MESError
  - YOLO / PatchCore 결과 변환 함수
"""
import json
import socket
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from mes_client import (MESClient, MESError, anomaly_map_to_box, patchcore_to_detections,
                        yolo_to_detections)

API_KEY = "test-key"


class _FakeMES(BaseHTTPRequestHandler):
    """POST /api/inspections 만 흉내 내는 가짜 서버. 받은 payload 를 server.received 에 모은다"""

    def log_message(self, *args):  # 테스트 출력 조용히
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        # multipart 본문에서 payload 필드만 꺼냄 (테스트용 간이 파싱)
        payload = json.loads(body.split(b'name="payload"\r\n\r\n')[1].split(b"\r\n--")[0])
        if self.headers.get("X-API-Key") != API_KEY:
            code, out = 401, {"detail": "bad key"}
        elif payload["item"] == "Bad":  # 이 품목은 서버가 거부하는 것으로
            code, out = 422, {"detail": "bad payload"}
        else:
            code, out = 201, {"image_filename": payload["serial_no"], "result": "OK"}
            self.server.received.append(payload)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(out).encode())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> HTTPServer:
    srv = HTTPServer(("127.0.0.1", port), _FakeMES)
    srv.received = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def image(tmp_path) -> Path:
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG fake")
    return p


def test_queue_when_server_down_then_resend_in_order(tmp_path, image):
    port = _free_port()
    mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2)

    # 1) 서버 꺼짐 → None 반환, 큐에 2건
    assert mes.send_dimension("S1", "Redcar", image, 40, 90, 30) is None
    assert mes.send_defects("S1", "Redcar", "YOLO", image,
                            [{"type": "scratch", "confidence": 0.9, "box": [1, 2, 3, 4]}]) is None
    assert mes.pending() == 2
    first_job = sorted((tmp_path / "q").iterdir())[0]
    first_time = json.loads((first_job / "payload.json").read_text(encoding="utf-8"))["inspected_at"]

    # 2) 서버 켬 → 다음 전송 때 밀린 것부터 순서대로
    srv = _start_server(port)
    try:
        res = mes.send_defects("S2", "Redcar", "PATCHCORE", image, [])
        assert res == {"image_filename": "S2", "result": "OK"}
        assert mes.pending() == 0
        assert [(p["serial_no"], p["process"]) for p in srv.received] == [
            ("S1", "DIM3D"), ("S1", "YOLO"), ("S2", "PATCHCORE")]
        # 원래 검사 시각 유지: 큐에 넣을 때 찍힌 시각이 그대로 가고, 시간대가 붙은 실제 시각이어야 함
        assert srv.received[0]["inspected_at"] == first_time
        t0 = datetime.fromisoformat(first_time)
        assert t0.tzinfo is not None
        assert t0 <= datetime.fromisoformat(srv.received[2]["inspected_at"])  # 나중에 보낸 S2 보다 이르거나 같음
        assert srv.received[2]["defects"] == [{"defect_detected": False}]  # 결함 없음 표현
    finally:
        srv.shutdown()


def test_explicit_inspected_at_is_sent(tmp_path, image):
    """검사 시각을 직접 넘기면 그 값이 그대로 서버로 간다"""
    port = _free_port()
    srv = _start_server(port)
    try:
        mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2,
                        model_version="v9")
        at = datetime(2026, 10, 5, 9, 30, tzinfo=timezone(timedelta(hours=9)))
        mes.send_dimension("S4", "Redcar", image, 40.12345, 90, 30, inspected_at=at)
        p = srv.received[0]
        assert p["inspected_at"] == "2026-10-05T09:30:00+09:00"
        assert p["model_version"] == "v9"
        assert p["dimension"] == {"width_mm": 40.123, "length_mm": 90.0, "height_mm": 30.0}
    finally:
        srv.shutdown()


def test_rejected_payload_raises(tmp_path, image):
    port = _free_port()
    srv = _start_server(port)
    try:
        mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2)
        with pytest.raises(MESError):
            mes.send_dimension("S3", "Bad", image, 1, 1, 1)
        assert mes.pending() == 0  # 거부된 건 큐에 쌓지 않음
    finally:
        srv.shutdown()


def test_yolo_to_detections():
    class _Arr:  # ultralytics 텐서의 .tolist() 흉내
        def __init__(self, v):
            self.v = v

        def tolist(self):
            return self.v

    class _Boxes:
        xyxy = _Arr([[10.04, 20, 30, 40], [1, 1, 2, 2]])
        conf = _Arr([0.91, 0.2])
        cls = _Arr([0, 1])

    class _Result:
        boxes = _Boxes()
        names = {0: "scratch", 1: "dent"}

    assert yolo_to_detections(_Result(), conf_min=0.5) == [
        {"type": "scratch", "confidence": 0.91, "box": [10.0, 20.0, 30.0, 40.0]}]


def test_patchcore_to_detections():
    assert patchcore_to_detections(0.3, threshold=0.5) == []
    assert patchcore_to_detections(1.4, threshold=0.5, box=[1, 2, 3, 4]) == [
        {"type": "anomaly", "confidence": 1.0, "box": [1, 2, 3, 4]}]


def test_anomaly_map_to_box():
    np = pytest.importorskip("numpy")
    m = np.zeros((10, 10))
    m[2:5, 3:7] = 0.9
    assert anomaly_map_to_box(m, 0.5) == [3.0, 2.0, 6.0, 4.0]
    assert anomaly_map_to_box(np.zeros((4, 4)), 0.5) is None
