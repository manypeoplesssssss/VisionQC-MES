"""
F03 로그인·인증 테스트 (tests/test_auth.py)   담당 A

실행: backend 폴더에서  pytest tests/test_auth.py -v
"""
def test_login_fail(client):
    """비밀번호가 틀리면 401"""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_protected_without_token(client):
    """토큰 없이 조회하면 401"""
    assert client.get("/api/inspections").status_code == 401
