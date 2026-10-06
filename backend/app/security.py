"""
인증 / 권한 (security.py)   [기능 F03 · 담당 A]

1) 비밀번호     : bcrypt 해시로 저장하고 비교 (원문은 어디에도 저장하지 않음)
2) 로그인 토큰  : JWT. 로그인하면 토큰을 주고, 이후 요청은 "Authorization: Bearer <토큰>" 헤더로 확인
3) 권한 체크    : API 함수에 Depends(...) 로 붙여서 사용
     get_current_user     로그인한 사용자만 (조회)
     require_admin        관리자·최고관리자 (불량 분류, 불량 종류 수정, 검사 삭제)
     require_super_admin  최고관리자 (계정 관리)
     require_ingest_auth  검사 PC(API Key) 또는 로그인 사용자
"""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AdminUser, Role

# Authorization: Bearer 헤더를 읽어오는 도구. auto_error=False → 헤더가 없어도 바로 에러 내지 않고 None 을 줌
# (/docs 화면 오른쪽 위 Authorize 버튼도 이것 덕분에 생긴다)
bearer = HTTPBearer(auto_error=False)


# ---------- 비밀번호 ----------
def hash_password(raw: str) -> str:
    """비밀번호 → bcrypt 해시 (같은 비밀번호라도 매번 다른 값이 나옴: salt)"""
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    """입력한 비밀번호가 저장된 해시와 맞는지"""
    return bcrypt.checkpw(raw.encode(), hashed.encode())


# ---------- JWT ----------
def create_access_token(username: str) -> str:
    """로그인 성공 시 발급하는 토큰. sub=아이디, exp=만료시각"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": username, "exp": expire},
                      settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _unauthorized(msg: str = "인증이 필요합니다") -> HTTPException:
    """401 에러. 프론트는 401 을 받으면 로그인 화면으로 보낸다"""
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    """토큰을 검사해서 로그인한 사용자를 돌려준다. 토큰이 없거나/틀리거나/만료/비활성 계정이면 401"""
    if cred is None:
        raise _unauthorized()
    try:
        data = jwt.decode(cred.credentials, settings.JWT_SECRET,
                          algorithms=[settings.JWT_ALGORITHM])  # 서명·만료 자동 검사
    except jwt.ExpiredSignatureError:
        raise _unauthorized("로그인이 만료되었습니다")
    except jwt.PyJWTError:
        raise _unauthorized()
    user = db.query(AdminUser).filter(AdminUser.username == data.get("sub")).first()
    if user is None or not user.is_active:  # 토큰 발급 후 계정이 중지된 경우도 막음
        raise _unauthorized()
    return user


def require_admin(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """관리자(ADMIN)·최고관리자만 통과. 조회 전용(VIEWER)은 403"""
    if user.role not in (Role.ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자 권한이 필요합니다")
    return user


def require_super_admin(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """최고관리자만 통과 (계정 관리)"""
    if user.role != Role.SUPER_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "최고관리자 권한이 필요합니다")
    return user


def require_ingest_auth(
    x_api_key: str | None = Header(default=None),  # 헤더 이름 X-API-Key (FastAPI 가 _ → - 로 바꿔 읽음)
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> str:
    """업로드 API: 검사 PC는 X-API-Key, 사람은 로그인 토큰 둘 중 하나로 통과"""
    if x_api_key is not None:
        # compare_digest : 문자열 비교 시간을 일정하게 해서 키를 한 글자씩 추측하는 공격을 막음
        if secrets.compare_digest(x_api_key, settings.INGEST_API_KEY):
            return "machine"
        raise _unauthorized("API Key 가 올바르지 않습니다")
    return get_current_user(cred, db).username
