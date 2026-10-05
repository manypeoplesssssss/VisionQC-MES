"""
검사 결과 등록 API - 검사 PC → MES (routers/ingest.py)   [기능 F05 · 담당 B]

POST /api/inspections    검사 결과 + 이미지 등록

조회 API(GET /api/inspections ...)는 routers/inspections.py (담당 D).
같은 주소지만 등록과 조회를 파일로 나눠서, 두 사람이 같은 파일을 동시에 고치지 않게 했다.

처리 순서: payload 검증 → 판정(services/judge.py) → 이미지 저장(storage.py) → DB 기록
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DefectResult, DimensionResult, Inspection
from ..schemas import InspectionOut, InspectionPayload
from ..security import require_ingest_auth
from ..services.judge import judge_inspection
from ..services.query import to_out
from ..storage import delete_image, save_image

log = logging.getLogger("mes.ingest")
router = APIRouter(prefix="/api", tags=["ingest"])


def _local_naive(dt: datetime) -> datetime:
    """시간대 정보가 붙어 오면 서버 로컬 시각으로 바꿔서 저장 (DB는 로컬 시각 기준)"""
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


@router.post("/inspections", response_model=InspectionOut, status_code=201)
def create_inspection(
    image: UploadFile = File(...),                                               # 이미지 파일
    payload: str = Form(..., description="InspectionPayload JSON 문자열"),        # 결과 데이터(JSON 문자열)
    db: Session = Depends(get_db),
    who: str = Depends(require_ingest_auth),                                     # API Key 또는 로그인
):
    # 1) payload 문자열 → JSON → 형식 검증
    try:
        data = InspectionPayload.model_validate(json.loads(payload))
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"payload 가 JSON 이 아닙니다: {e}")
    except ValidationError as e:
        raise HTTPException(422, json.loads(e.json(include_url=False)))

    # 2) 판정 (규격 문제로 에러가 나면 이미지를 저장하기 전에 멈추도록 먼저 한다)
    result, dim_status = judge_inspection(data, db)  # 저장 전에 판정 (규격 오류면 파일 안 남김)

    # 3) 검사 시각 결정 후 이미지 저장 (파일명에 날짜가 들어가므로 시각이 먼저 필요)
    inspected_at = _local_naive(data.inspected_at) if data.inspected_at else datetime.now()
    filename, rel_path = save_image(image, inspected_at, data.item, data.process.value, data.serial_no)

    # 4) DB 기록
    try:
        insp = Inspection(
            serial_no=data.serial_no, item=data.item, process=data.process,
            inspected_at=inspected_at, result=result, model_version=data.model_version,
            image_filename=filename, image_path=rel_path,
        )
        if data.dimension:
            insp.dimension = DimensionResult(
                width_mm=data.dimension.width_mm, length_mm=data.dimension.length_mm,
                height_mm=data.dimension.height_mm, status=dim_status,
                reported_status=data.dimension.status,
            )
        insp.defects = [DefectResult(**d.model_dump()) for d in data.defects]
        db.add(insp)
        db.commit()
    except Exception:
        db.rollback()
        delete_image(rel_path)  # DB 기록 실패 시 고아 파일이 남지 않게
        log.exception("검사 저장 실패: %s", filename)
        raise
    db.refresh(insp)
    log.info("검사 등록 %s %s by %s", filename, result.value, who)
    return to_out(insp)
