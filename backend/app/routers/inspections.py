"""
검사 데이터 조회 API (routers/inspections.py)

GET    /api/inspections                                   목록 (제품/최종결과/기간/식별번호 필터, 페이징)
GET    /api/inspections/export                            같은 필터로 CSV 다운로드 (엑셀에서 바로 열림)
GET    /api/inspections/{inspection_id}                   상세 (치수, PatchCore, YOLO 결함, 사진 전부)
PUT    /api/inspections/{inspection_id}/defects/{index}   결함 1개에 불량 코드(D01~D05) 지정 (관리자)
DELETE /api/inspections/{inspection_id}                   삭제 (관리자, 사진 파일 포함)
GET    /api/products                                      검사에 등장한 제품 모델명 목록

검사 결과 '등록'(PUT/POST)은 routers/ingest.py.

주의: /inspections/export 는 /inspections/{inspection_id} 보다 위에 있어야 한다.
      (아래에 있으면 'export' 를 검사번호로 해석한다)
"""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, DefectType, ProductInspection
from ..schemas import DefectCodeIn, InspectionDetailOut, InspectionPage
from ..security import get_current_user, require_admin
from ..services.query import (apply_filters, date_range, get_or_404, refresh_recommended, to_detail,
                              to_summary)
from ..storage import delete_image

router = APIRouter(prefix="/api", tags=["inspections"])

# CSV 한 번에 내보낼 최대 행 수 (서버 메모리 보호)
EXPORT_LIMIT = 100_000


def _filters(product_name: str | None = None, final_result: str | None = None,
             serial: str | None = None, date_from: date | None = None, date_to: date | None = None):
    """목록/CSV 공통 필터. 기간을 안 주면 전체 기간.
    final_result 는 6가지 값 외에 DEFECT(불량 전체), PENDING(판정 전 전체)도 받는다"""
    start = end = None
    if date_from or date_to:
        start, end = date_range(date_from, date_to)
    return dict(product_name=product_name, final_result=final_result, serial=serial, start=start, end=end)


# -------------------------------------------------------------------------
# 조회
# -------------------------------------------------------------------------
@router.get("/inspections", response_model=InspectionPage)
def list_inspections(
    f: dict = Depends(_filters),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    q = apply_filters(select(ProductInspection), **f)
    total = db.scalar(select(func.count()).select_from(q.subquery()))  # 전체 건수 (페이지 수 계산용)
    rows = db.scalars(
        q.order_by(ProductInspection.created_at.desc(), ProductInspection.id.desc())
         .offset((page - 1) * size).limit(size)
    ).all()
    return InspectionPage(total=total, page=page, size=size, items=[to_summary(r) for r in rows])


@router.get("/inspections/export")
def export_inspections(
    f: dict = Depends(_filters),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    rows = db.scalars(apply_filters(select(ProductInspection), **f)
                      .order_by(ProductInspection.created_at, ProductInspection.id).limit(EXPORT_LIMIT)).all()
    header = ["inspection_id", "created_at", "product_name", "product_serial",
              "dimension_result", "width_mm", "length_mm", "height_mm",
              "patchcore_result", "patchcore_score", "patchcore_threshold",
              "yolo_status", "defect_count", "defect_classes", "defect_codes", "max_confidence",
              "final_result", "capture_count"]

    def generate():
        """CSV 를 조금씩 만들어서 흘려보냄 (큰 파일도 메모리에 한 번에 올리지 않게)"""
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("﻿")  # 엑셀에서 한글 안 깨지게 BOM
        w.writerow(header)
        for r in rows:
            d = r.dimension
            defects = r.yolo_defect_data or []
            w.writerow([
                r.inspection_id, r.created_at.isoformat(sep=" "), r.product_name, r.product_serial or "",
                _v(r.dimension_result), d.width_mm if d else "", d.length_mm if d else "", d.height_mm if d else "",
                _v(r.patchcore_result), r.patchcore_score if r.patchcore_score is not None else "",
                r.patchcore_threshold if r.patchcore_threshold is not None else "",
                _v(r.yolo_status), len(defects),
                ";".join(sorted({x.get("defect_class") or "" for x in defects})),   # 여러 개는 ; 로
                ";".join(sorted({x["defect_code"] for x in defects if x.get("defect_code")})),
                max((x.get("confidence") or 0) for x in defects) if defects else "",
                r.final_result, len(r.image_files or []),
            ])
            if buf.tell() > 64_000:  # 64KB 쌓이면 내보내고 비우기
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    filename = f"inspections_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _v(x) -> str:
    """Enum 이면 값, 아니면 그대로 (CSV 용)"""
    return getattr(x, "value", x) or ""


@router.get("/inspections/{inspection_id}", response_model=InspectionDetailOut)
def get_inspection(inspection_id: str, db: Session = Depends(get_db),
                   _user: AdminUser = Depends(get_current_user)):
    return to_detail(get_or_404(db, inspection_id), db)


# -------------------------------------------------------------------------
# 불량 코드 지정 (관리자) - YOLO 검출만으로는 D01~D05 공정 케이스가 자동 분류되지 않아 사람이 확인해 지정
# -------------------------------------------------------------------------
@router.put("/inspections/{inspection_id}/defects/{index}", response_model=InspectionDetailOut)
def set_defect_code(inspection_id: str, index: int, body: DefectCodeIn,
                    db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    insp = get_or_404(db, inspection_id)
    defects = [dict(d) for d in (insp.yolo_defect_data or [])]
    if not 0 <= index < len(defects):
        raise HTTPException(404, "해당 결함이 없습니다")
    if body.defect_code:
        t = db.get(DefectType, body.defect_code)
        if t is None or not t.is_active:
            raise HTTPException(400, "사용할 수 없는 불량 코드입니다")
    defects[index]["defect_code"] = body.defect_code
    insp.yolo_defect_data = defects        # 새 리스트를 넣어야 JSON 변경이 저장된다
    refresh_recommended(insp, db)          # 원인 후보·권장 조치 다시 모으기
    db.commit()
    db.refresh(insp)
    return to_detail(insp, db)


# -------------------------------------------------------------------------
# 삭제 (관리자)
# -------------------------------------------------------------------------
@router.delete("/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: str, db: Session = Depends(get_db),
                      _admin: AdminUser = Depends(require_admin)):
    insp = get_or_404(db, inspection_id)
    paths = [p for f in (insp.image_files or [])
             for p in (f.get("original_path"), f.get("annotated_path"), f.get("metadata_path")) if p]
    db.delete(insp)       # 치수 행은 cascade 로 같이 삭제
    db.commit()
    for p in paths:       # DB 삭제가 끝난 뒤 파일 삭제
        delete_image(p)


@router.get("/products", response_model=list[str])
def list_products(db: Session = Depends(get_db), _user: AdminUser = Depends(get_current_user)):
    """검사 데이터에 등장한 제품 모델명 (화면의 선택 상자용)"""
    return db.scalars(select(ProductInspection.product_name).distinct()
                      .order_by(ProductInspection.product_name)).all()
