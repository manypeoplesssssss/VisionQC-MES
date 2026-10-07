"""
FastAPI 앱 시작점 (main.py)   [기능 F00 · 담당 A]

실행: uvicorn app.main:app --reload --port 8000
      → app 폴더의 main.py 안에 있는 app 객체를 띄운다는 뜻
API 문서(자동 생성): http://localhost:8000/docs

하는 일
  1) 로그 설정
  2) DB 테이블 자동 생성 (없는 테이블만)
  3) CORS 설정 (브라우저에서 다른 주소의 프론트가 API 를 부를 수 있게)
  4) 각 기능별 라우터(routers/*.py) 등록
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .database import Base, SessionLocal, engine
from .routers import auth, dashboard, defect_types, images, ingest, inspections, safety, users

# 콘솔에 "시각 레벨 이름: 메시지" 형식으로 로그 출력
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# 테이블이 없으면 자동 생성 (컬럼 변경은 반영 안 됨 → README '스키마 변경' 참고)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="VisionQC AI MES API",
    version="1.0.0",
    description="비전 검사(3D 치수 → YOLO) 결과 수집·조회 API. 검사 1회 = product_inspection 1행",
)

# CORS: 개발 중에는 Vite 프록시를 써서 필요 없지만, 프론트를 다른 주소에서 띄울 때를 대비
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 기능별 API 묶음 등록 (각 파일의 router 객체)
#   auth 로그인 · users 관리자 계정 · ingest 검사 PC 결과 등록 · inspections 조회·불량 코드·삭제
#   defect_types 불량 종류 · safety 센터링·인터락 알람 · dashboard 대시보드 · images 사진 파일
for r in (auth, users, ingest, inspections, defect_types, safety, dashboard, images):
    app.include_router(r.router)


@app.get("/api/health", tags=["system"])
def health():
    """서버와 DB 가 살아있는지 확인 (DB 에 SELECT 1 을 날려봄)"""
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
