"""
환경 설정 (config.py)   [기능 F00 · 담당 A]

서버가 쓰는 모든 설정값을 한 곳에 모아둔 파일.
값은 아래 순서로 정해진다 (위에 있을수록 우선).
  1) OS 환경변수            예) set DATABASE_URL=...
  2) backend/.env 파일       예) DATABASE_URL=...   (.env.example 을 복사해서 만든다)
  3) 이 파일에 적힌 기본값

다른 파일에서는 `from .config import settings` 로 가져와서 `settings.STORAGE_DIR` 처럼 쓴다.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env 파일을 읽고, 여기에 정의되지 않은 키가 있어도 에러 없이 무시
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------- DB ----------
    # SQLAlchemy 접속 문자열. 형식: mysql+pymysql://아이디:비밀번호@호스트:포트/DB이름?charset=utf8mb4
    # (테스트에서는 sqlite:///파일경로 로 바꿔서 MySQL 없이 돌린다)
    DATABASE_URL: str = "mysql+pymysql://mes_user:mes_pass@localhost:3306/visionqc_mes?charset=utf8mb4"

    # ---------- 이미지 저장 ----------
    # 검사 이미지를 저장할 로컬 폴더. 이 아래에 yyyy-mm-dd 폴더가 날짜별로 생긴다
    STORAGE_DIR: Path = Path("./storage/images")
    # 업로드 이미지 1장 최대 크기 (MB)
    MAX_IMAGE_MB: int = 20

    # ---------- 로그인 토큰 (JWT) ----------
    # 토큰 서명 키. 이 값이 노출되면 누구나 토큰을 만들 수 있으므로 운영 시 반드시 바꿀 것
    # (이미지 주소 서명에도 같은 키를 쓴다)
    JWT_SECRET: str = "change-this-secret"
    JWT_ALGORITHM: str = "HS256"
    # 로그인 유지 시간(분). 480분 = 8시간 = 한 근무조
    JWT_EXPIRE_MINUTES: int = 480

    # 이미지 주소 서명 유효시간(초). 로그인한 사람만 받은 주소로 이미지를 볼 수 있게
    IMAGE_URL_TTL_SECONDS: int = 3600

    # 검사 PC(비전 프로그램)가 로그인 없이 결과를 올릴 때 쓰는 키 (X-API-Key 헤더)
    INGEST_API_KEY: str = "change-this-ingest-key"

    # 프론트엔드 주소 (CORS). 브라우저가 다른 주소에서 API를 부를 때 허용할 목록. 여러 개면 쉼표로 구분
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """'a, b' 형태의 문자열을 ['a', 'b'] 리스트로 바꿔준다"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


# 앱 전체에서 공유하는 설정 객체 (import 할 때 한 번만 만들어진다)
settings = Settings()
# 이미지 폴더가 없으면 미리 만들어 둔다
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
