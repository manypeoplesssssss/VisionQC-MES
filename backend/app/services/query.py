"""
검사 조회 공통 (services/query.py)

여러 API(목록, CSV, 대시보드, 상세)가 같이 쓰는 기능
- date_range()         : 날짜 → [시작시각, 끝시각) 범위
- apply_filters()      : 제품/최종결과/시리얼/기간 조건을 쿼리에 붙이기
- to_summary()         : DB 객체 → 목록 한 줄 (첫 사진 서명 주소 포함)
- to_detail()          : DB 객체 → 상세 (사진 전부, 결함별 불량 코드 이름 포함)
- refresh_recommended(): 지정된 불량 코드들의 원인 후보·권장 조치를 recommended_action 에 모은다
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models import AlarmStatus, DefectType, FinalResult, ProductInspection
from ..schemas import (AlarmOut, DimensionOut, ImageFileOut, InspectionDetailOut, InspectionSummaryOut,
                       YoloDefectOut)
from ..storage import image_url

# 한 번에 조회할 수 있는 최대 기간 (너무 긴 기간 조회로 서버가 느려지는 것 방지)
MAX_RANGE_DAYS = 366

# 최종 결과 묶음 (대시보드·불량률 계산)
DEFECT_RESULTS = {FinalResult.DIMENSION_DEFECT.value, FinalResult.YOLO_PENDING.value,
                  FinalResult.PROCESS_DEFECT.value}       # 불량 (치수 불합격 또는 PatchCore 불합격)
PENDING_RESULTS = {FinalResult.DIMENSION_PENDING.value, FinalResult.PATCHCORE_PENDING.value}  # 판정 전


def day_start(d: date) -> datetime:
    """날짜 → 그날 00:00:00"""
    return datetime.combine(d, datetime.min.time())


def date_range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    """
    [시작, 끝) 범위. 끝은 '종료일 다음날 00시' 라서 종료일 하루 전체가 포함된다.
    둘 다 없으면 오늘 하루, 하나만 있으면 그 하루.
    """
    date_from = date_from or date_to or date.today()
    date_to = date_to or date_from
    if date_to < date_from:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"조회 기간은 최대 {MAX_RANGE_DAYS}일입니다")
    return day_start(date_from), day_start(date_to + timedelta(days=1))


def apply_filters(q: Select, *, product_name: str | None = None, final_result: str | None = None,
                  serial: str | None = None, start: datetime | None = None,
                  end: datetime | None = None) -> Select:
    """값이 있는 조건만 WHERE 절로 붙인다"""
    P = ProductInspection
    if product_name:
        q = q.where(P.product_name == product_name)
    if final_result == "DEFECT":          # 불량 전체 (3가지 묶음)
        q = q.where(P.final_result.in_(DEFECT_RESULTS))
    elif final_result == "PENDING":       # 판정 전 전체
        q = q.where(P.final_result.in_(PENDING_RESULTS))
    elif final_result:
        q = q.where(P.final_result == final_result)
    if serial:
        # 부분 검색 (LIKE '%값%'). 제품 식별번호와 검사번호 둘 다에서 찾는다
        q = q.where(P.product_serial.contains(serial, autoescape=True)
                    | P.inspection_id.contains(serial, autoescape=True))
    if start:
        q = q.where(P.created_at >= start)
    if end:
        q = q.where(P.created_at < end)
    return q


def get_or_404(db: Session, inspection_id: str) -> ProductInspection:
    insp = db.scalar(select(ProductInspection).where(ProductInspection.inspection_id == inspection_id))
    if insp is None:
        raise HTTPException(404, "검사 데이터를 찾을 수 없습니다")
    return insp


def _url(path: str | None) -> str | None:
    return image_url(path) if path else None


def to_summary(insp: ProductInspection) -> InspectionSummaryOut:
    """DB 검사 객체 → 목록 한 줄"""
    defects = insp.yolo_defect_data or []
    images = insp.image_files or []
    first = images[0] if images else None
    return InspectionSummaryOut(
        id=insp.id,
        inspection_id=insp.inspection_id,
        product_name=insp.product_name,
        product_serial=insp.product_serial,
        dimension_result=insp.dimension_result,
        patchcore_result=insp.patchcore_result,
        yolo_status=insp.yolo_status,
        final_result=insp.final_result,
        centering_state=insp.centering_state,
        interlock_state=insp.interlock_state,
        active_alarms=sum(1 for a in insp.alarms if getattr(a.alarm_status, "value", a.alarm_status) == AlarmStatus.ACTIVE.value),
        defect_count=len(defects),
        defect_classes=sorted({d.get("defect_class") or "unknown" for d in defects}),
        capture_count=len(images),
        thumbnail_url=_url(first.get("annotated_path") or first.get("original_path")) if first else None,
        created_at=insp.created_at,
    )


def to_detail(insp: ProductInspection, db: Session) -> InspectionDetailOut:
    """DB 검사 객체 → 상세. 결함에 지정된 불량 코드의 이름을 같이 붙인다"""
    names = {t.defect_code: t.defect_name for t in db.scalars(select(DefectType)).all()}
    defects = [
        YoloDefectOut(index=i, capture_number=d.get("capture_number", 0),
                      defect_class=d.get("defect_class") or "unknown",
                      confidence=d.get("confidence") or 0.0, box=d.get("box"),
                      angle_deg=d.get("angle_deg"), defect_code=d.get("defect_code"),
                      defect_name=names.get(d.get("defect_code")))
        for i, d in enumerate(insp.yolo_defect_data or [])
    ]
    images = [
        ImageFileOut(**f, original_url=image_url(f["original_path"]),
                     annotated_url=_url(f.get("annotated_path")))
        for f in (insp.image_files or [])
    ]
    return InspectionDetailOut(
        **to_summary(insp).model_dump(),
        dimension_data=insp.dimension_data,
        scan_file_path=insp.scan_file_path,
        patchcore_score=insp.patchcore_score,
        patchcore_threshold=insp.patchcore_threshold,
        patchcore_model_version=insp.patchcore_model_version,
        yolo_model_version=insp.yolo_model_version,
        capture_folder=insp.capture_folder,
        recommended_action=insp.recommended_action,
        report_path=insp.report_path,
        report_sent_at=insp.report_sent_at,
        updated_at=insp.updated_at,
        dimension=DimensionOut.model_validate(insp.dimension) if insp.dimension else None,
        defects=defects,
        images=images,
        alarms=[AlarmOut.model_validate(a) for a in insp.alarms],
    )


def refresh_recommended(insp: ProductInspection, db: Session) -> None:
    """결함에 지정된 불량 코드들 → '[D01 측면 도장 부족] 원인 후보: ... / 권장 조치: ...' 문장으로 모은다.
    원인은 확정이 아닌 후보로만 표시한다. 지정된 코드가 없으면 비운다"""
    codes = sorted({d["defect_code"] for d in (insp.yolo_defect_data or []) if d.get("defect_code")})
    if not codes:
        insp.recommended_action = None
        return
    types = {t.defect_code: t for t in db.scalars(select(DefectType).where(DefectType.defect_code.in_(codes)))}
    lines = []
    for c in codes:
        t = types.get(c)
        if t is None:
            continue
        causes = ", ".join(t.cause_candidates or []) or "-"
        lines.append(f"[{c} {t.defect_name}] 원인 후보: {causes} / 권장 조치: {t.recommended_action or '-'}")
    insp.recommended_action = "\n".join(lines) or None
