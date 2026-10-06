"""
테스트 공통 준비 (tests/conftest.py) - pytest 가 자동으로 먼저 읽는 파일

테스트는 MySQL 없이 SQLite 임시 파일로 돈다.
  cd backend
  pip install -r requirements-dev.txt
  pytest -q

순서가 중요하다: 앱(app.*)을 import 하기 전에 환경변수를 먼저 바꿔야
config.py 가 실제 MySQL 대신 임시 SQLite/임시 폴더를 쓴다.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 1) 임시 폴더를 만들고 DB·이미지 경로를 그쪽으로 돌린다 (실제 데이터는 건드리지 않음)
_tmp = Path(tempfile.mkdtemp(prefix="vqc_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_tmp / "images")
os.environ["INGEST_API_KEY"] = "test-key"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["PRODUCT_STANDARDS"] = '{"redcar": [194.5, 84.96, 58.68]}'
# backend 폴더를 import 경로에 추가 (어디서 pytest 를 실행해도 app 패키지를 찾게)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 2) 환경변수를 바꾼 다음에 앱을 import
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AdminUser, DefectType, Role  # noqa: E402
from app.security import hash_password  # noqa: E402
from seed import DEFECT_TYPES  # noqa: E402

# 업로드에 쓸 진짜 1x1 PNG 이미지 바이트
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
KEY = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def fresh_db():
    """테스트 하나마다 DB 를 비우고 기본 데이터(계정 3개, 불량 종류 D01~D05)를 다시 넣는다"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for username, pw, role in [("admin", "admin1234", Role.SUPER_ADMIN),
                                   ("manager", "manager1234", Role.ADMIN),
                                   ("viewer", "viewer1234", Role.VIEWER)]:
            db.add(AdminUser(username=username, password_hash=hash_password(pw), name=username, role=role))
        for t in DEFECT_TYPES:
            db.add(DefectType(**t))
        db.commit()
    yield


@pytest.fixture
def client():
    """서버를 실제로 띄우지 않고 API 를 호출하는 테스트 클라이언트"""
    return TestClient(app)


def _login(client, username, password):
    """로그인해서 Authorization 헤더 dict 를 돌려준다"""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client):
    """최고관리자"""
    return _login(client, "admin", "admin1234")


@pytest.fixture
def manager(client):
    """관리자"""
    return _login(client, "manager", "manager1234")


@pytest.fixture
def viewer(client):
    """조회 전용"""
    return _login(client, "viewer", "viewer1234")


@pytest.fixture
def mes(client):
    """검사 PC 처럼 단계별 결과를 보내는 도우미"""
    class Mes:
        def start(self, iid, product="redcar", serial=None, expect=200, **kw):
            r = client.put(f"/api/inspections/{iid}", headers=KEY,
                           json={"product_name": product, "product_serial": serial, **kw})
            assert r.status_code == expect, r.text
            return r.json()

        def dimension(self, iid, w=194.5, length=84.96, h=58.68, expect=200, **kw):
            r = client.put(f"/api/inspections/{iid}/dimension", headers=KEY,
                           json={"width_mm": w, "length_mm": length, "height_mm": h, **kw})
            assert r.status_code == expect, r.text
            return r.json()

        def patchcore(self, iid, score, threshold=0.6, expect=200):
            r = client.put(f"/api/inspections/{iid}/patchcore", headers=KEY,
                           json={"score": score, "threshold": threshold})
            assert r.status_code == expect, r.text
            return r.json()

        def capture(self, iid, n, defects=(), annotated=True, expect=201, key=KEY):
            files = {"original": ("o.png", io.BytesIO(PNG), "image/png")}
            if annotated:
                files["annotated"] = ("a.png", io.BytesIO(PNG), "image/png")
            payload = {"capture_number": n, "angle_deg": 10.0 * n, "defects": list(defects)}
            r = client.post(f"/api/inspections/{iid}/yolo/captures", headers=key, files=files,
                            data={"payload": json.dumps(payload)})
            assert r.status_code == expect, r.text
            return r.json()

        def complete(self, iid, expect=200):
            r = client.put(f"/api/inspections/{iid}/yolo/complete", headers=KEY, json={})
            assert r.status_code == expect, r.text
            return r.json()

    return Mes()
