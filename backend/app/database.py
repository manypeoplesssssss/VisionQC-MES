"""
DB 연결 (database.py)   [기능 F00 · 담당 A]

- engine       : DB 와 실제로 연결하는 객체 (커넥션 풀 관리)
- SessionLocal : 요청 1건마다 하나씩 만들어 쓰는 DB 세션 공장
- Base         : 모든 테이블 클래스(models.py)의 부모 클래스
- get_db()     : FastAPI 의존성. API 함수가 `db: Session = Depends(get_db)` 로 받아 쓴다
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# SQLite 는 기본적으로 "만든 스레드에서만 사용" 제한이 있어서, 테스트(SQLite)일 때만 그 제한을 끈다
_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping=True : 오래 쉬어서 끊긴 MySQL 연결을 쓰기 전에 확인하고 다시 연결 (MySQL 8시간 타임아웃 대비)
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)

# autoflush=False : 쿼리할 때마다 자동으로 DB 에 밀어넣지 않음 (commit 시점에 한 번에 반영)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """모든 테이블 클래스가 상속받는 기본 클래스"""
    pass


def get_db():
    """
    API 요청 하나가 들어올 때 DB 세션을 열어주고, 응답이 끝나면 반드시 닫는다.
    yield 앞: 요청 시작 / yield 뒤(finally): 요청 끝 (에러가 나도 실행됨)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
