"""
제품(시리얼) 단위 집계 (services/products.py)   [기능 F09 · 담당 C]

inspections 테이블은 "검사 1건(이미지 1장)" 단위라서,
"제품 1개가 지금 어떤 상태인가" 를 보려면 같은 시리얼끼리 묶어야 한다. 그 일을 여기서 한다.
(제품 추적 화면, 대시보드 KPI·품목별 표·일별 차트가 모두 이 함수를 쓴다)

제품 상태
  - IN_PROGRESS : 아직 3개 공정을 다 거치지 않음 (단, 이미 NG가 난 공정이 있으면 NG)
  - NG          : 공정별 '마지막' 검사 중 하나라도 NG
  - OK          : 3개 공정의 마지막 검사가 모두 OK
재검사가 있으면 그 공정의 마지막 결과를 쓴다.

DB 종류(MySQL/SQLite)에 상관없이 똑같이 동작하도록, 묶는 계산은 SQL 이 아니라 파이썬에서 한다.
하루 수천 개 수준까지는 충분히 빠르다.
"""
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PROCESS_ORDER, Inspection, Judge
from ..schemas import ProductOut, ProductStep


@dataclass
class _Acc:
    """집계 중인 제품 1개의 임시 저장소"""
    serial_no: str
    item: str
    first_at: datetime
    last_at: datetime
    steps: dict = field(default_factory=dict)  # process -> [id, result, inspected_at, attempts]


def product_status(steps: dict) -> str:
    """공정별 마지막 결과(steps) → 제품 상태"""
    if any(s[1] == Judge.NG for s in steps.values()):
        return "NG"
    if all(p in steps for p in PROCESS_ORDER):
        return "OK"
    return "IN_PROGRESS"


def aggregate_products(db: Session, start: datetime, end: datetime,
                       item: str | None = None, serial_no: str | None = None) -> list[ProductOut]:
    """기간 안에 '첫 검사'가 들어온 제품 기준으로 묶는다 (제품이 날짜를 넘겨도 하루에만 잡히게)"""
    # 1) 기간 안에 검사가 하나라도 있는 시리얼 목록
    first_q = (select(Inspection.serial_no)
               .where(Inspection.inspected_at >= start, Inspection.inspected_at < end))
    if item:
        first_q = first_q.where(Inspection.item == item)
    if serial_no:
        first_q = first_q.where(Inspection.serial_no.contains(serial_no, autoescape=True))
    serials = set(db.scalars(first_q.distinct()).all())
    if not serials:
        return []

    # 2) 그 시리얼들의 전체 검사 이력 (기간 밖 검사도 포함해야 정확한 상태가 나옴). 필요한 컬럼만 가볍게
    rows = []
    serial_list = list(serials)
    for i in range(0, len(serial_list), 1000):  # IN 절이 너무 길어지지 않게 나눠서
        chunk = serial_list[i:i + 1000]
        rows += db.execute(
            select(Inspection.id, Inspection.serial_no, Inspection.item, Inspection.process,
                   Inspection.result, Inspection.inspected_at)
            .where(Inspection.serial_no.in_(chunk))
            .order_by(Inspection.inspected_at, Inspection.id)
        ).all()

    # 3) 시간순으로 훑으면서 시리얼별로 묶기. 같은 공정은 나중 값이 덮어써서 '마지막 결과'가 남는다
    acc: dict[str, _Acc] = {}
    for iid, serial, it, proc, res, ts in rows:
        a = acc.get(serial)
        if a is None:
            a = acc[serial] = _Acc(serial, it, ts, ts)
        a.last_at = ts
        prev = a.steps.get(proc)
        a.steps[proc] = [iid, res, ts, (prev[3] + 1) if prev else 1]  # 시간순이라 마지막 값이 남음

    # 4) 응답 형식으로 변환
    products = []
    for a in acc.values():
        if not (start <= a.first_at < end):
            continue  # 기간 이전에 시작한 제품은 제외
        steps = [ProductStep(process=p, inspection_id=s[0], result=s[1], inspected_at=s[2], attempts=s[3])
                 for p in PROCESS_ORDER if (s := a.steps.get(p))]
        products.append(ProductOut(serial_no=a.serial_no, item=a.item, first_at=a.first_at,
                                   last_at=a.last_at, status=product_status(a.steps), steps=steps))
    products.sort(key=lambda p: p.last_at, reverse=True)  # 최근에 움직인 제품이 위로
    return products


def count_status(products: list[ProductOut]) -> dict[str, int]:
    """상태별 개수 {'OK': n, 'NG': n, 'IN_PROGRESS': n}"""
    c = {"OK": 0, "NG": 0, "IN_PROGRESS": 0}
    for p in products:
        c[p.status] += 1
    return c


def defect_rate(c: dict[str, int]) -> float:
    """불량률(%) = 불량 / (양품 + 불량). 진행중 제품은 아직 결과가 없으니 뺀다"""
    done = c["OK"] + c["NG"]
    return round(c["NG"] / done * 100, 2) if done else 0.0
