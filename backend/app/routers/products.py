"""
제품(시리얼) 단위 조회 - 제품 1개가 3개 공정을 어떻게 거쳤는지 추적 (routers/products.py)   [기능 F09 · 담당 C]

GET /api/products                       기간 내 제품 목록 (상태: OK / NG / IN_PROGRESS)
GET /api/products/{serial_no}/history   제품 1개의 전체 검사 이력 (재검사 포함, 시간순)
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Inspection, User
from ..schemas import InspectionOut, ProductPage
from ..security import get_current_user
from ..services.products import aggregate_products
from ..services.query import date_range, to_out

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=ProductPage)
def list_products(
    date_from: date | None = None,
    date_to: date | None = None,
    item: str | None = None,
    serial_no: str | None = None,
    status: Literal["OK", "NG", "IN_PROGRESS"] | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    start, end = date_range(date_from, date_to)  # 기간 없으면 오늘
    products = aggregate_products(db, start, end, item=item, serial_no=serial_no)
    # 상태는 집계 후에야 알 수 있어서 파이썬에서 거른다
    if status:
        products = [p for p in products if p.status == status]
    s = (page - 1) * size
    return ProductPage(total=len(products), page=page, size=size, items=products[s:s + size])


@router.get("/{serial_no}/history", response_model=list[InspectionOut])
def product_history(serial_no: str, db: Session = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Inspection).where(Inspection.serial_no == serial_no)
        .order_by(Inspection.inspected_at, Inspection.id)  # 공정을 거친 순서대로
    ).all()
    if not rows:
        raise HTTPException(404, "해당 시리얼의 검사 이력이 없습니다")
    return [to_out(r) for r in rows]
