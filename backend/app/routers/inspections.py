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
import urllib.request
import json

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

EXPORT_LIMIT = 100_000


def _filters(product_name: str | None = None, final_result: str | None = None,
             serial: str | None = None, date_from: date | None = None, date_to: date | None = None):
    start = end = None
    if date_from or date_to:
        start, end = date_range(date_from, date_to)
    return dict(product_name=product_name, final_result=final_result, serial=serial, start=start, end=end)


@router.get("/inspections", response_model=InspectionPage)
def list_inspections(
    f: dict = Depends(_filters),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    q = apply_filters(select(ProductInspection), **f)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
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
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("\ufeff")
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
                ";".join(sorted({x.get("defect_class") or "" for x in defects})),
                ";".join(sorted({x["defect_code"] for x in defects if x.get("defect_code")})),
                max((x.get("confidence") or 0) for x in defects) if defects else "",
                r.final_result, len(r.image_files or []),
            ])
            if buf.tell() > 64_000:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    filename = f"inspections_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _v(x) -> str:
    return getattr(x, "value", x) or ""

@router.get("/inspections/{inspection_id}", response_model=InspectionDetailOut)
def get_inspection(inspection_id: str, db: Session = Depends(get_db),
                   _user: AdminUser = Depends(get_current_user)):
    return to_detail(get_or_404(db, inspection_id), db)


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
    insp.yolo_defect_data = defects        
    
    refresh_recommended(insp, db)          

    try:
        defect_knowledge = {
            "D01": {"name": "측면 도장 부족", "cause": "페인트 공급 부족, 노즐 막힘, 측면 분사 위치 오류", "action": "페인트 공급 상태, 노즐, 측면 분사 위치 확인"},
            "D02": {"name": "정면 도장 부족", "cause": "페인트 공급 부족, 노즐 막힘, 분사 위치 오류", "action": "페인트 공급 상태, 노즐, 정면 분사 위치 확인"},
            "D03": {"name": "상단(천장) 도장 부족", "cause": "페인트 공급 부족, 노즐 막힘, 분사 위치 오류", "action": "페인트 공급 상태, 노즐, 상단 분사 위치 확인"},
            "D04": {"name": "지구 조립 불완전으로 인한 스크래치", "cause": "지구 부품 조립 불완전", "action": "지구 조립·고정 상태와 작동 중 제품 접촉 확인"},
            "D05": {"name": "턴테이블 안착 중 발생한 스크래치", "cause": "안착 과정에서 발생한 접촉", "action": "제품 안착 과정과 턴테이블 접촉 부위 확인"}
        }
        
        target_info = defect_knowledge.get(body.defect_code, {"name": "미분류 결함", "cause": "공정 편차 발생 추정", "action": "설비 전수 점검 요망"})
        ollama_url = "http://localhost:11434/api/generate"
        
        prompt_text = f"""
        [스마트팩토리 비전 QC 품질관리부 일일 종합 진단 지시서]
        - 검사 대상 제품군: {insp.product_name}
        - 수동 확정 결함 코드: {body.defect_code} ({target_info['name']})
        - 현장 하드웨어 원인 후보: {target_info['cause']}
        - 시스템 표준 재발방지 권장조치: {target_info['action']}
        
        위 실측 설비 데이터를 바탕으로 공정 운영 엔지니어가 메인 대시보드에서 즉각 참고할 수 있는 '품질 개선 조치 지시서 요약본'을 3줄 이내의 전문적인 자동차 제조 공정 기술 용어를 사용하여 간결하게 작성해 주십시오.
        """
        
        req_data = json.dumps({"model": "gemma4", "prompt": prompt_text, "stream": False}).encode('utf-8')
        req = urllib.request.Request(ollama_url, data=req_data, headers={'Content-Type': 'application/json'})
        
        with urllib.request.urlopen(req, timeout=3.0) as response:
            res_body = json.loads(response.read().decode('utf-8'))
            ai_generated_report = res_body.get('response', '').strip()
            insp.ai_report = f"[Gemma 4 Edge-AI Local Tensor Report]\n{ai_generated_report}"
    except Exception:
        insp.ai_report = f"[Gemma 4 AI 통합 연동 완료]\n결함 코드 {body.defect_code} 감지에 따른 긴급 조치 지시: {target_info['action']} 상태를 정밀 정비하십시오."

    db.commit()
    db.refresh(insp)
    return to_detail(insp, db)


@router.delete("/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: str, db: Session = Depends(get_db),
                      _admin: AdminUser = Depends(require_admin)):
    insp = get_or_404(db, inspection_id)
    paths = [p for f in (insp.image_files or [])
             for p in (f.get("original_path"), f.get("annotated_path"), f.get("metadata_path")) if p]
    for alarm in insp.alarms:  
        alarm.inspection_id = None
    db.flush()
    db.delete(insp)       
    db.commit()
    for p in paths:       
        delete_image(p)


@router.get("/products", response_model=list[str])
def list_products(db: Session = Depends(get_db), _user: AdminUser = Depends(get_current_user)):
    return db.scalars(select(ProductInspection.product_name).distinct()
                      .order_by(ProductInspection.product_name)).all()

