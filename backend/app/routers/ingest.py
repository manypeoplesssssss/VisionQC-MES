"""
검사 결과 등록 API - 검사 PC → MES (routers/ingest.py)

검사 1회(product_inspection 1행)를 만들고, 단계가 끝날 때마다 결과를 채워 넣는다.
모두 X-API-Key(검사 PC) 또는 로그인 토큰으로 호출할 수 있다.

PUT  /api/inspections/{inspection_id}                     검사 시작 / 기본 정보 (제품 모델명, 식별번호, 사진 폴더)
PUT  /api/inspections/{inspection_id}/dimension           3D 치수 측정값 → 축별·종합 합불은 DB 가 자동 계산
PUT  /api/inspections/{inspection_id}/patchcore           PatchCore 점수·기준 → 점수 >= 기준이면 불합격
POST /api/inspections/{inspection_id}/yolo/captures       결함 사진 1장 (원본 + 표시 사진 + 결함 목록)
PUT  /api/inspections/{inspection_id}/yolo/complete       YOLO 분류 완료

final_result(최종 결과)는 DB 가 dimension_result → patchcore_result → yolo_status 순서로 자동 계산한다.
단계 API 는 검사 행이 없으면 만들어 주므로(product_name 쿼리 필요), 순서가 섞여 들어와도 된다.

사진 파일명: 일자-제품-시각-공정-검사번호_c사진번호[_annotated].확장자
  예) 2026-10-06-redcar-143005-YOLO-20261006_inspection_143000_001_c001.jpg
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (DIM_RECHECK_MM, DIM_TOLERANCE_MM, ProductDimensionInspection, ProductInspection,
                      InspectionStage, StageResult, YoloStatus)
from ..schemas import (ID_PATTERN, NAME_PATTERN, DimensionIn, InspectionDetailOut, InspectionUpsert,
                       PatchCoreIn, YoloCaptureIn, YoloCompleteIn)
from ..security import require_ingest_auth
from ..services.query import to_detail
from ..services.safety import record_safety
from ..storage import delete_image, read_image, save_bytes

log = logging.getLogger("mes.ingest")
router = APIRouter(prefix="/api/inspections", tags=["ingest"])

InspectionId = Path(pattern=ID_PATTERN, description="검사 고유번호 (날짜 포함 권장)")


def _local_naive(dt: datetime | None) -> datetime:
    """시간대 정보가 붙어 오면 서버 로컬 시각으로 바꿔서 저장 (DB 는 로컬 시각 기준). 없으면 지금"""
    if dt is None:
        return datetime.now().replace(microsecond=0)
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _get_or_create(db: Session, inspection_id: str, product_name: str | None) -> ProductInspection:
    """검사 행을 찾고, 없으면 product_name 으로 새로 만든다"""
    insp = db.query(ProductInspection).filter_by(inspection_id=inspection_id).first()
    if insp is not None:
        return insp
    if not product_name:
        raise HTTPException(404, "검사가 없습니다. 먼저 검사를 시작하거나 product_name 을 같이 보내세요")
    insp = ProductInspection(inspection_id=inspection_id, product_name=product_name,
                             yolo_defect_data=[], image_files=[])
    db.add(insp)
    db.flush()
    return insp


def _done(db: Session, insp: ProductInspection) -> InspectionDetailOut:
    """저장 후 DB 가 계산한 자동 컬럼까지 다시 읽어서 응답"""
    db.commit()
    db.refresh(insp)
    if insp.dimension is not None:
        db.refresh(insp.dimension)
    return to_detail(insp, db)


@router.put("/{inspection_id}", response_model=InspectionDetailOut)
def upsert_inspection(body: InspectionUpsert, inspection_id: str = InspectionId,
                      db: Session = Depends(get_db), who: str = Depends(require_ingest_auth)):
    insp = _get_or_create(db, inspection_id, body.product_name)
    insp.product_name = body.product_name
    if body.product_serial is not None:
        insp.product_serial = body.product_serial
    if body.capture_folder is not None:
        insp.capture_folder = body.capture_folder
    if body.started_at is not None:
        insp.created_at = _local_naive(body.started_at)
    log.info("검사 시작/수정 %s by %s", inspection_id, who)
    return _done(db, insp)


@router.put("/{inspection_id}/dimension", response_model=InspectionDetailOut)
def put_dimension(body: DimensionIn, inspection_id: str = InspectionId,
                  product_name: str | None = Query(None, pattern=NAME_PATTERN),
                  db: Session = Depends(get_db), _who: str = Depends(require_ingest_auth)):
    insp = _get_or_create(db, inspection_id, product_name)
    # 기준 치수: 보낸 값 > 서버 설정(제품 모델별). 검사 당시 값으로 치수 행에 남긴다
    std = {k.lower(): v for k, v in settings.PRODUCT_STANDARDS.items()}.get(insp.product_name.lower(), [None] * 3)
    dim = insp.dimension or ProductDimensionInspection()
    dim.width_mm, dim.length_mm, dim.height_mm = body.width_mm, body.length_mm, body.height_mm
    dim.standard_width_mm = body.standard_width_mm or std[0]
    dim.standard_length_mm = body.standard_length_mm or std[1]
    dim.standard_height_mm = body.standard_height_mm or std[2]
    dim.scan_file_path = body.scan_file_path
    dim.centering_state, dim.interlock_state = body.centering_state, body.interlock_state  # 측정 시점 장비 상태
    insp.dimension = dim
    # 장비 상태를 검사 행에도 기록하고, 이상(ON / 1 / 미확인)이면 알람 기록
    record_safety(db, insp, InspectionStage.DIMENSION, body.centering_state, body.interlock_state,
                  "치수 측정 시점 상태")
    db.flush()
    db.refresh(dim)  # DB 가 계산한 축별·종합 합불 읽기

    # 치수 테이블의 판정을 전체 검사 행으로 반영 (요약 JSON 포함)
    insp.dimension_result = dim.dimension_result
    insp.scan_file_path = body.scan_file_path
    insp.dimension_data = {
        "tolerance_mm": DIM_TOLERANCE_MM,   # 축별 불량 한계
        "recheck_mm": DIM_RECHECK_MM,       # 축별 정상(재검) 한계
        **{f"{a}_mm": getattr(dim, f"{a}_mm") for a in ("width", "length", "height")},
        **{f"standard_{a}_mm": getattr(dim, f"standard_{a}_mm") for a in ("width", "length", "height")},
        **{f"{a}_result": getattr(dim, f"{a}_result") for a in ("width", "length", "height")},
    }
    return _done(db, insp)


@router.put("/{inspection_id}/patchcore", response_model=InspectionDetailOut)
def put_patchcore(body: PatchCoreIn, inspection_id: str = InspectionId,
                  product_name: str | None = Query(None, pattern=NAME_PATTERN),
                  db: Session = Depends(get_db), _who: str = Depends(require_ingest_auth)):
    insp = _get_or_create(db, inspection_id, product_name)
    insp.patchcore_score = body.score
    insp.patchcore_threshold = body.threshold  # 검사 당시 기준을 같이 남긴다
    insp.patchcore_model_version = body.model_version
    insp.patchcore_result = StageResult.FAIL if body.score >= body.threshold else StageResult.PASS
    return _done(db, insp)


@router.post("/{inspection_id}/yolo/captures", response_model=InspectionDetailOut, status_code=201)
def add_yolo_capture(
    inspection_id: str = InspectionId,
    original: UploadFile = File(..., description="원본 사진"),
    annotated: UploadFile | None = File(None, description="검출 표시 사진 (선택)"),
    payload: str = Form(..., description="YoloCaptureIn JSON 문자열"),
    product_name: str | None = Query(None, pattern=NAME_PATTERN),
    db: Session = Depends(get_db),
    _who: str = Depends(require_ingest_auth),
):
    # 1) payload 문자열 → JSON → 형식 검증
    try:
        data = YoloCaptureIn.model_validate(json.loads(payload))
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"payload 가 JSON 이 아닙니다: {e}")
    except ValidationError as e:
        raise HTTPException(422, json.loads(e.json(include_url=False)))

    insp = _get_or_create(db, inspection_id, product_name)
    if any(f.get("capture_number") == data.capture_number for f in insp.image_files or []):
        raise HTTPException(409, f"사진 번호 {data.capture_number} 는 이미 등록되어 있습니다")

    # 2) 파일 저장: 원본, 표시 사진, 검출 정보(json)
    at = _local_naive(data.captured_at)
    ident = f"{inspection_id}_c{data.capture_number:03d}"
    saved = []
    try:
        body, ext = read_image(original)
        saved.append(save_bytes(body, ext, at, insp.product_name, "YOLO", ident)[1])
        annotated_path = None
        if annotated is not None and annotated.filename:
            body, ext = read_image(annotated)
            annotated_path = save_bytes(body, ext, at, insp.product_name, "YOLO", ident + "_annotated")[1]
            saved.append(annotated_path)
        meta = {"inspection_id": inspection_id, **data.model_dump(mode="json")}
        metadata_path = save_bytes(json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
                                   ".json", at, insp.product_name, "YOLO", ident)[1]
        saved.append(metadata_path)

        # 3) 검사 행에 추가 (JSON 컬럼은 새 리스트를 넣어야 변경이 저장된다)
        insp.image_files = [*(insp.image_files or []), {
            "capture_number": data.capture_number, "original_path": saved[0],
            "annotated_path": annotated_path, "metadata_path": metadata_path}]
        insp.yolo_defect_data = [*(insp.yolo_defect_data or []), *[
            {"capture_number": data.capture_number, "defect_class": d.defect_class,
             "confidence": round(d.confidence, 4), "box": d.box, "angle_deg": data.angle_deg,
             "defect_code": None} for d in data.defects]]
        if data.model_version:
            insp.yolo_model_version = data.model_version
        if insp.yolo_status == YoloStatus.NOT_STARTED:
            insp.yolo_status = YoloStatus.IN_PROGRESS
        return _done(db, insp)
    except Exception:
        db.rollback()
        for rel in saved:  # DB 기록 실패 시 고아 파일이 남지 않게
            delete_image(rel)
        raise


@router.put("/{inspection_id}/yolo/complete", response_model=InspectionDetailOut)
def complete_yolo(body: YoloCompleteIn, inspection_id: str = InspectionId,
                  product_name: str | None = Query(None, pattern=NAME_PATTERN),
                  db: Session = Depends(get_db), _who: str = Depends(require_ingest_auth)):
    insp = _get_or_create(db, inspection_id, product_name)
    insp.yolo_status = YoloStatus.COMPLETED
    if body.model_version:
        insp.yolo_model_version = body.model_version
    return _done(db, insp)
