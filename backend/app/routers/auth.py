"""
로그인 API (routers/auth.py)   [기능 F03·F04 · 담당 A]

POST /api/auth/login     아이디/비밀번호 → 토큰
GET  /api/auth/me        현재 로그인한 사용자 정보 (프론트가 새로고침 후 로그인 유지 확인용)
PUT  /api/auth/password  본인 비밀번호 변경
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, PasswordChange, TokenResponse, UserOut
from ..security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    # 아이디가 없는 경우와 비밀번호가 틀린 경우를 같은 메시지로 → 어떤 아이디가 있는지 알려주지 않음
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    if not user.is_active:
        raise HTTPException(403, "비활성화된 계정입니다. 관리자에게 문의하세요")
    return TokenResponse(access_token=create_access_token(user.username))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.put("/password", status_code=204)
def change_password(body: PasswordChange, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "현재 비밀번호가 올바르지 않습니다")
    user.password_hash = hash_password(body.new_password)
    db.commit()
