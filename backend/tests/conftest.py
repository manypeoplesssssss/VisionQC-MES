"""
테스트 공통 준비 (tests/conftest.py) - pytest 가 자동으로 먼저 읽는 파일   [기능 F00 · 담당 A]

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
# backend 폴더를 import 경로에 추가 (어디서 pytest 를 실행해도 app 패키지를 찾게)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 2) 환경변수를 바꾼 다음에 앱을 import
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ItemSpec, Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

# 업로드에 쓸 진짜 1x1 PNG 이미지 바이트
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def fresh_db():
    """테스트 하나마다 DB 를 비우고 기본 데이터(관리자, 작업자, Redcar 규격)를 다시 넣는다"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(User(username="admin", password_hash=hash_password("admin1234"), name="관리자", role=Role.ADMIN))
        db.add(User(username="op", password_hash=hash_password("op123456"), name="작업자", role=Role.OPERATOR))
        db.add(ItemSpec(item="Redcar", width_nominal=40, width_tol=0.5, length_nominal=90, length_tol=0.5,
                        height_nominal=30, height_tol=0.5))
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
    return _login(client, "admin", "admin1234")


@pytest.fixture
def operator(client):
    return _login(client, "op", "op123456")


@pytest.fixture
def upload(client):
    """검사 PC 처럼 업로드하는 헬퍼"""
    def _upload(payload: dict, filename="img.png", key="test-key", expect=201):
        # multipart: image(파일) + payload(JSON 문자열), 헤더 X-API-Key
        r = client.post("/api/inspections", headers={"X-API-Key": key},
                        files={"image": (filename, io.BytesIO(PNG), "image/png")},
                        data={"payload": json.dumps(payload)})
        assert r.status_code == expect, r.text
        return r.json()
    return _upload
