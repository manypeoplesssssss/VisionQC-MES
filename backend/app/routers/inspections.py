"""
검사 데이터 조회 API (routers/inspections.py)   [기능 F12·F13·F14 · 담당 D]

GET    /api/inspections              목록 (공정/품목/판정/기간/시리얼 필터, 페이징)
GET    /api/inspections/export       같은 필터로 CSV 다운로드 (엑셀에서 바로 열림)
GET    /api/inspections/{id}         상세
DELETE /api/inspections/{id}         삭제 (관리자, 이미지 파일 포함)
GET    /api/items                    등록된 검사 품목 목록

검사 결과 '등록'(POST /api/inspections)은 routers/ingest.py (담당 B).

주의: /inspections/export 는 /inspections/{id} 보다 위에 있어야 한다.
      (아래에 있으면 'export' 를 id 로 해석하려다 422 에러가 남)
"""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Inspection, Judge, Process, User
from ..schemas import InspectionOut, InspectionPage
from ..security import get_current_user, require_admin
from ..services.query import apply_filters, date_range, to_out
from ..storage import delete_image

router = APIRouter(prefix="/api", tags=["inspections"])

# CSV 한 번에 내보낼 최대 행 수 (서버 메모리 보호)
EXPORT_LIMIT = 100_000


def _filters(process: Process | None = None, item: str | None = None, result: Judge | None = None,
             serial_no: str | None = None, date_from: date | None = None, date_to: date | None = None):
    """목록/CSV 공통 필터. 기간을 안 주면 전체 기간"""
    # 이 함수를 Depends(_filters) 로 쓰면 FastAPI 가 쿼리스트링(?process=..&item=..)을 읽어서 넣어준다
    start = end = None
    if date_from or date_to:
        start, end = date_range(date_from, date_to)
    return dict(process=process, item=item, result=result, serial_no=serial_no, start=start, end=end)



# -------------------------------------------------------------------------
# 조회
# -------------------------------------------------------------------------
@router.get("/inspections", response_model=InspectionPage)
def list_inspections(
    f: dict = Depends(_filters),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = apply_filters(select(Inspection), **f)
    # 전체 건수 (페이지 수 계산용)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    # 최신순으로 한 페이지만
    rows = db.scalars(
        q.order_by(Inspection.inspected_at.desc(), Inspection.id.desc())
         .offset((page - 1) * size).limit(size)
    ).all()
    return InspectionPage(total=total, page=page, size=size, items=[to_out(r) for r in rows])


@router.get("/inspections/export")
def export_inspections(
    f: dict = Depends(_filters),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = (apply_filters(select(Inspection), **f)
         .order_by(Inspection.inspected_at, Inspection.id).limit(EXPORT_LIMIT))
    rows = db.scalars(q).all()

    header = ["id", "inspected_at", "serial_no", "item", "process", "result",
              "width_mm", "length_mm", "height_mm", "dim_status", "reported_status",
              "defect_types", "max_confidence", "model_version", "image_filename"]

    def generate():
        """CSV 를 조금씩 만들어서 흘려보냄 (큰 파일도 메모리에 한 번에 올리지 않게)"""
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("﻿")  # 엑셀에서 한글 안 깨지게 BOM
        w.writerow(header)
        for r in rows:
            d = r.dimension
            found = [x for x in r.defects if x.defect_detected]
            w.writerow([
                r.id, r.inspected_at.isoformat(sep=" "), r.serial_no, r.item, r.process.value,
                r.result.value,
                d.width_mm if d else "", d.length_mm if d else "", d.height_mm if d else "",
                d.status.value if d else "", d.reported_status.value if d and d.reported_status else "",
                ";".join(x.type or "" for x in found),                       # 결함 유형 여러 개는 ; 로
                max((x.confidence or 0) for x in found) if found else "",   # 가장 높은 신뢰도
                r.model_version or "", r.image_filename,
            ])
            if buf.tell() > 64_000:  # 64KB 쌓이면 내보내고 비우기
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    filename = f"inspections_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/inspections/{inspection_id}", response_model=InspectionOut)
def get_inspection(inspection_id: int, db: Session = Depends(get_db),
                   _user: User = Depends(get_current_user)):
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(404, "검사 데이터를 찾을 수 없습니다")
    return to_out(insp)


# -------------------------------------------------------------------------
# 삭제 (관리자)
# -------------------------------------------------------------------------
@router.delete("/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: int, db: Session = Depends(get_db),
                      _admin: User = Depends(require_admin)):
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(404, "검사 데이터를 찾을 수 없습니다")
    rel_path = insp.image_path
    db.delete(insp)       # 치수/결함 행은 cascade 로 같이 삭제
    db.commit()
    delete_image(rel_path)  # DB 삭제가 끝난 뒤 파일 삭제


@router.get("/items", response_model=list[str])
def list_items(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """검사 데이터에 등장한 품목 이름들 (화면의 품목 선택 상자용)"""
    return db.scalars(select(Inspection.item).distinct().order_by(Inspection.item)).all()
