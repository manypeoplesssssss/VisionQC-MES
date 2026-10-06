"""
검사 PC 연동 클라이언트 테스트 (vision_client/test_mes_client.py)

MES 서버 없이, 이 파일 안에서 가짜 서버를 띄워서 mes_client 의 동작을 확인한다.
  pip install requests pytest
  cd vision_client
  pytest -v

확인하는 것
  - 서버가 꺼져 있으면 큐에 쌓이고, 켜지면 보낸 순서대로 재전송 (사진 포함, 시각은 처음 값 유지)
  - 단계별 요청 주소·내용 (치수 소수 3자리, product_name 쿼리)
  - 서버가 형식 오류(4xx)로 거부하면 MESError
  - YOLO 결과 변환 함수
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from mes_client import MESClient, MESError, yolo_to_defects

API_KEY = "test-key"


class _FakeMES(BaseHTTPRequestHandler):
    """/api/inspections/... 를 흉내 내는 가짜 서버. 받은 요청을 server.received 에 모은다"""

    def log_message(self, *args):  # 테스트 출력 조용히
        pass

    def _handle(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        url = urlparse(self.path)
        if b'name="payload"' in body:  # multipart 본문에서 payload 와 파일 이름만 꺼냄 (테스트용 간이 파싱)
            data = json.loads(body.split(b'name="payload"\r\n\r\n')[1].split(b"\r\n--")[0])
            data["_files"] = [f for f in ("original", "annotated") if f'name="{f}"'.encode() in body]
        else:
            data = json.loads(body or b"{}")
        if self.headers.get("X-API-Key") != API_KEY:
            code, out = 401, {"detail": "bad key"}
        elif "BAD" in url.path:  # 이 검사번호는 서버가 거부하는 것으로
            code, out = 422, {"detail": "bad payload"}
        else:
            code, out = 200, {"inspection_id": url.path.split("/")[3], "final_result": "DIMENSION_PENDING"}
            self.server.received.append((self.command, url.path, parse_qs(url.query), data))
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(out).encode())

    do_PUT = do_POST = _handle


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

    # 1) 서버 꺼짐 → None 반환, 큐에 3건 (사진은 큐 폴더로 복사)
    assert mes.start("I1", "redcar", product_serial="RC-1") is None
    assert mes.send_yolo_capture("I1", 1, image, image,
                                 defects=[{"defect_class": "scratch", "confidence": 0.9, "box": [1, 2, 3, 4]}],
                                 angle_deg=12.5) is None
    assert mes.send_dimension("I1", 40.12345, 90, None) is None
    assert mes.pending() == 3
    first_job = sorted((tmp_path / "q").iterdir())[0]
    started = json.loads((first_job / "request.json").read_text(encoding="utf-8"))["json"]["started_at"]
    image.unlink()  # 원본 사진을 지워도 큐에 복사본이 있으니 재전송 가능

    # 2) 서버 켬 → 다음 전송 때 밀린 것부터 순서대로
    srv = _start_server(port)
    try:
        res = mes.complete_yolo("I1")
        assert res["inspection_id"] == "I1"
        assert mes.pending() == 0
        assert [(m, p) for m, p, _, _ in srv.received] == [
            ("PUT", "/api/inspections/I1"), ("POST", "/api/inspections/I1/yolo/captures"),
            ("PUT", "/api/inspections/I1/dimension"), ("PUT", "/api/inspections/I1/yolo/complete")]
        assert srv.received[0][3]["started_at"] == started          # 처음 시각 유지
        cap = srv.received[1][3]
        assert cap["capture_number"] == 1 and cap["angle_deg"] == 12.5
        assert cap["defects"][0]["defect_class"] == "scratch" and cap["_files"] == ["original", "annotated"]
        assert srv.received[2][3] == {"width_mm": 40.123, "length_mm": 90.0, "height_mm": None,
                                      "scan_file_path": None}
        # 단계 API 에는 product_name 이 같이 가서, 서버에 검사 행이 없어도 만들어진다
        assert srv.received[3][2] == {"product_name": ["redcar"]}
    finally:
        srv.shutdown()


def test_patchcore_and_standards(tmp_path):
    port = _free_port()
    srv = _start_server(port)
    try:
        mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2,
                        model_version="v9")
        mes.send_patchcore("P1", 0.81, 0.6)
        mes.send_dimension("P1", 40, 90, 30, standards=(41, 91, 31))
        assert srv.received[0][3] == {"score": 0.81, "threshold": 0.6, "model_version": "v9"}
        assert srv.received[1][3]["standard_length_mm"] == 91
        assert srv.received[0][2] == {}  # start() 를 안 했으면 product_name 쿼리 없음
    finally:
        srv.shutdown()


def test_rejected_and_missing_file(tmp_path, image):
    port = _free_port()
    srv = _start_server(port)
    try:
        mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2)
        with pytest.raises(MESError):
            mes.send_dimension("BAD1", 1, 1, 1)
        assert mes.pending() == 0  # 거부된 건 큐에 쌓지 않음
        with pytest.raises(FileNotFoundError):
            mes.send_yolo_capture("I2", 1, tmp_path / "none.jpg")
    finally:
        srv.shutdown()


def test_yolo_to_defects():
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
        names = {0: "scratch", 1: "white_paint"}

    assert yolo_to_defects(_Result(), conf_min=0.5) == [
        {"defect_class": "scratch", "confidence": 0.91, "box": [10.0, 20.0, 30.0, 40.0]}]


def test_safety_check_and_local_rule(tmp_path):
    """안전 확인은 /api/safety/check 로, 허용 판단은 이 PC 에서 (센터링 OFF + 인터락 0 만)"""
    from mes_client import safety_ok
    assert safety_ok("OFF", "0") and not safety_ok("ON", "0") and not safety_ok("OFF", "UNKNOWN")
    port = _free_port()
    srv = _start_server(port)
    try:
        mes = MESClient(f"http://127.0.0.1:{port}", api_key=API_KEY, queue_dir=tmp_path / "q", timeout=2)
        mes.start("I9", "redcar")
        mes.check_safety("YOLO", "OFF", "1", inspection_id="I9", message="테스트")
        mes.send_dimension("I9", 194.5, 84.96, 58.68, centering="OFF", interlock="0")
        method, path, _, body = srv.received[1]
        assert (method, path) == ("POST", "/api/safety/check")
        assert body == {"stage": "YOLO", "centering_state": "OFF", "interlock_state": "1", "message": "테스트",
                        "inspection_id": "I9", "product_name": "redcar"}
        assert srv.received[2][3]["centering_state"] == "OFF" and srv.received[2][3]["interlock_state"] == "0"
    finally:
        srv.shutdown()
