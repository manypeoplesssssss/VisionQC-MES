"""
DB 직접 저장 모듈 테스트 (inspection/common/test_db_client.py)

MES 서버 코드(backend)로 임시 SQLite DB 에 테이블을 만들고, db_client 로 저장한 뒤
MES API 로 읽었을 때 같은 결과가 나오는지 확인한다 (검사 PC → DB → MES).
  cd inspection\\common
  ..\\..\\backend\\.venv\\Scripts\\python.exe -m pytest -q
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="vqc_dbclient_"))
DB_URL = f"sqlite:///{(_tmp / 'mes.db').as_posix()}"
STORAGE = _tmp / "images"
BACKEND = Path(__file__).resolve().parents[2] / "backend"


@pytest.fixture(scope="module")
def mes_app():
    """backend 앱을 임시 DB·임시 사진 폴더로 띄워서 테이블을 만든다"""
    os.environ.update(DATABASE_URL=DB_URL, STORAGE_DIR=str(STORAGE), JWT_SECRET="t" * 32,
                      INGEST_API_KEY="k")
    sys.path.insert(0, str(BACKEND))
    from fastapi.testclient import TestClient
    from app.database import Base, SessionLocal, engine
    from app.main import app
    from app.models import AdminUser, Role
    from app.security import hash_password
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(AdminUser(username="admin", password_hash=hash_password("admin1234"), name="a", role=Role.SUPER_ADMIN))
        db.commit()
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"}).json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(mes_app, tmp_path):
    from db_client import DBClient
    return DBClient(DB_URL, storage_dir=STORAGE, queue_dir=tmp_path / "q")


def test_full_flow_written_to_db_and_read_by_mes(db, mes_app, tmp_path):
    client, auth = mes_app
    iid = "20261006_inspection_120000_001"
    r = db.start(iid, "redcar", product_serial="RC-1", capture_folder="captures/x")
    assert r["final_result"] == "DIMENSION_PENDING" and r["centering_state"] == "UNKNOWN"
    r = db.send_dimension(iid, 195.0, 85.0, 58.7, standards=(194.5, 84.96, 58.68), centering="OFF", interlock="0")
    assert r["dimension_result"] == "PASS" and r["final_result"] == "PATCHCORE_PENDING" and r["active_alarms"] == 0
    r = db.send_patchcore(iid, 0.9, 0.6)
    assert r["patchcore_result"] == "FAIL" and r["final_result"] == "YOLO_PENDING"
    img = tmp_path / "c001.jpg"
    img.write_bytes(b"\xff\xd8 fake jpg")
    r = db.send_yolo_capture(iid, 1, img, img, defects=[{"defect_class": "scratch", "confidence": 0.91, "box": [1, 2, 3, 4]}],
                             angle_deg=12.0)
    assert r["capture_count"] == 1 and r["defect_count"] == 1 and r["yolo_status"] == "IN_PROGRESS"
    with pytest.raises(Exception):
        db.send_yolo_capture(iid, 1, img)  # 같은 사진 번호 중복
    r = db.complete_yolo(iid)
    assert r["final_result"] == "PROCESS_DEFECT"

    # MES 가 DB 에서 읽은 결과
    d = client.get(f"/api/inspections/{iid}", headers=auth).json()
    assert d["final_result"] == "PROCESS_DEFECT" and d["product_serial"] == "RC-1"
    assert d["dimension"]["standard_length_mm"] == 84.96 and d["dimension"]["centering_state"] == "OFF"
    assert d["defects"][0]["defect_class"] == "scratch"
    assert "-redcar-" in d["images"][0]["original_path"] and "-YOLO-" in d["images"][0]["original_path"]
    assert client.get(d["images"][0]["original_url"]).status_code == 200  # MES 가 복사된 사진을 서비스


def test_safety_alarms(db, mes_app):
    client, auth = mes_app
    iid = "20261006_inspection_130000_001"
    db.start(iid, "redcar")
    r = db.check_safety("YOLO", "OFF", "1", inspection_id=iid, message="테스트")
    assert r["allowed"] is False and [a["alarm_type"] for a in r["alarms"]] == ["INTERLOCK"]
    assert db.check_safety("YOLO", "OFF", "1", inspection_id=iid)["alarms"] == []  # 같은 상태 중복 안 만듦
    assert db.check_safety("PRECHECK", "OFF", "0")["allowed"] is True
    alarms = client.get("/api/safety/alarms", headers=auth, params={"inspection_id": iid}).json()
    assert alarms["total"] == 1 and alarms["items"][0]["interlock_state"] == "1"


def test_queue_when_db_unreachable(tmp_path):
    """DB 에 연결이 안 되면 큐에 쌓이고 None"""
    from db_client import DBClient
    bad = DBClient(f"sqlite:///{(tmp_path / 'no_dir' / 'x.db').as_posix()}", storage_dir=tmp_path,
                   queue_dir=tmp_path / "q")
    assert bad.start("Q1", "redcar") is None
    assert bad.pending() == 1
