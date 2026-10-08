"""
메인 페이지(대시보드)용 API (routers/dashboard.py)

GET /api/dashboard/summary?date=YYYY-MM-DD      그날 검사 수·정상·불량·대기·불량률, 최종 결과별, 단계별,
                                                 제품 모델별, YOLO 결함 종류, 불량 코드, 최근 불량
GET /api/dashboard/hourly?date=YYYY-MM-DD       시간대별 검사·불량 수 (하루)
GET /api/dashboard/daily?date_from=&date_to=    일별 검사·불량 수 (기간, 기본 최근 14일)

검사 1회 = product_inspection 1행. 시각은 created_at(검사 시작 시각) 기준.
불량 = 치수 불합격(DIMENSION_DEFECT) + PatchCore 불합격(YOLO_PENDING, PROCESS_DEFECT)
대기 = DIMENSION_PENDING + PATCHCORE_PENDING
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
import pymysql

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminUser, AlarmStatus, EquipmentSafetyAlarm, FinalResult, ProductInspection
from ..schemas import DashboardSummary, LabelCount, ProductSummary, StageCount, TrendPoint
from ..security import get_current_user
from ..services.query import DEFECT_RESULTS, PENDING_RESULTS, date_range, to_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _rows(db: Session, start, end) -> list[ProductInspection]:
    P = ProductInspection
    return db.scalars(select(P).where(P.created_at >= start, P.created_at < end)
                      .order_by(P.created_at.desc(), P.id.desc())).all()


def defect_rate(defect: int, normal: int) -> float:
    done = defect + normal
    return round(defect / done * 100, 2) if done else 0.0


def _v(x) -> str:
    return getattr(x, "value", x)


@router.get("/hourly", response_model=list[TrendPoint])
def hourly(
    d: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    d = d or date.today()
    start, end = date_range(d, d)
    P = ProductInspection
    rows = db.execute(select(P.created_at, P.final_result)
                      .where(P.created_at >= start, P.created_at < end)).all()
    buckets = {h: [0, 0] for h in range(24)}
    for ts, res in rows:
        buckets[ts.hour][0] += 1
        if res in DEFECT_RESULTS:
            buckets[ts.hour][1] += 1
    return [TrendPoint(label=f"{h:02d}", total=t, defect=n) for h, (t, n) in buckets.items()]


@router.get("/daily", response_model=list[TrendPoint])
def daily(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    date_to = date_to or date.today()
    date_from = date_from or (date_to - timedelta(days=13))
    start, end = date_range(date_from, date_to)
    P = ProductInspection
    rows = db.execute(select(P.created_at, P.final_result)
                      .where(P.created_at >= start, P.created_at < end)).all()
    days = {(date_from + timedelta(days=i)).isoformat(): [0, 0]
            for i in range((date_to - date_from).days + 1)}
    for ts, res in rows:
        k = ts.date().isoformat()
        if k in days:
            days[k][0] += 1
            if res in DEFECT_RESULTS:
                days[k][1] += 1
    return [TrendPoint(label=k, total=t, defect=n) for k, (t, n) in days.items()]

@router.get("/summary", response_model=DashboardSummary)
def summary(
    d: date | None = Query(None, alias="date"),
    recent: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: AdminUser = Depends(get_current_user),
):
    d = d or date.today()
    start, end = date_range(d, d)
    rows = _rows(db, start, end)
    A = EquipmentSafetyAlarm
    active_alarms = db.scalar(select(func.count()).select_from(A).where(A.alarm_status == AlarmStatus.ACTIVE))
    alarms_today = db.scalar(select(func.count()).select_from(A).where(A.occurred_at >= start, A.occurred_at < end))

    by_final = {f.value: 0 for f in FinalResult}
    stages = {"DIMENSION": Counter(), "PATCHCORE": Counter(), "YOLO": Counter()}
    products: dict[str, Counter] = defaultdict(Counter)
    classes, codes = Counter(), Counter()
    
    # 💡 [핵심 통합] 당일 리포트 요약을 축적하기 위한 버퍼 배열 초기화
    daily_ai_insights = []

    for r in rows:
        by_final[r.final_result] += 1
        stages["DIMENSION"][_v(r.dimension_result)] += 1
        stages["PATCHCORE"][_v(r.patchcore_result)] += 1
        stages["YOLO"][_v(r.yolo_status)] += 1
        group = "defect" if r.final_result in DEFECT_RESULTS else "pending" if r.final_result in PENDING_RESULTS else "normal"
        products[r.product_name][group] += 1
        
        # 데이터 정합성을 체크하여 기적재된 Gemma 4 AI 리포트 이력 추출
        if hasattr(r, 'ai_report') and r.ai_report:
            daily_ai_insights.append(r.ai_report)
            
        for x in r.yolo_defect_data or []:
            classes[x.get("defect_class") or "unknown"] += 1
            codes[x.get("defect_code") or "미분류"] += 1

    normal = by_final[FinalResult.NORMAL.value]
    defect = sum(by_final[k] for k in DEFECT_RESULTS)
    pending = sum(by_final[k] for k in PENDING_RESULTS)
    
    response_data = DashboardSummary(
        date=d.isoformat(), total=len(rows), normal=normal, defect=defect, pending=pending,
        defect_rate=defect_rate(defect, normal),
        by_final=by_final,
        by_stage=[StageCount(stage=k, counts=dict(v)) for k, v in stages.items()],
        by_product=[ProductSummary(product_name=k, total=sum(v.values()), normal=v["normal"],
                                   defect=v["defect"], pending=v["pending"]) for k, v in sorted(products.items())],
        defect_classes=[LabelCount(label=k, count=n) for k, n in classes.most_common()],
        defect_codes=[LabelCount(label=k, count=n) for k, n in sorted(codes.items())],
        recent_defects=[to_summary(r) for r in rows if r.final_result in DEFECT_RESULTS][:recent],
        active_alarms=active_alarms or 0, alarms_today=alarms_today or 0,
    )
    
    # 💡 React 프론트엔드 메인 종합 보드 스키마 확장을 위한 동적 컴포넌트 데이터 바인딩
    response_data.__dict__["daily_ai_reports"] = daily_ai_insights[:5]
    
    return response_data
