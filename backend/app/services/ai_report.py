"""
AI 조치 요약 (services/ai_report.py)

불량 코드(D01~D05)를 지정하면 그 코드의 원인 후보·권장 조치로 '품질 개선 조치 요약'을 만들어
검사 행의 ai_report 컬럼에 저장한다.

- 지정한 순간 :  불량 종류 표(defect_type)의 내용으로 만든 기본 요약을 바로 저장한다 (기다림 없음)
- 그 뒤 백그라운드 : Ollama(로컬 AI)가 켜져 있으면 AI 가 쓴 요약으로 바꾼다. 꺼져 있거나 실패하면 기본 요약을 그대로 둔다
요청이 AI 때문에 느려지지 않도록, AI 호출은 응답을 보낸 뒤에 한다.

설정(.env):  OLLAMA_URL (기본 http://localhost:11434, 비우면 AI 를 아예 안 부름),
             OLLAMA_MODEL (기본 gemma4), OLLAMA_TIMEOUT_S (기본 30)
"""
import json
import logging
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import DefectType, ProductInspection

log = logging.getLogger(__name__)

HEADER_AUTO = "[자동 요약]"        # 불량 종류 표 내용으로 만든 기본 요약
HEADER_AI = "[AI 요약 · Ollama]"   # 로컬 AI 가 쓴 요약


def assigned_codes(insp: ProductInspection) -> list[str]:
    """이 검사의 결함에 지정된 불량 코드들 (중복 없이, 정렬)"""
    return sorted({d["defect_code"] for d in (insp.yolo_defect_data or []) if d.get("defect_code")})


def _types(db: Session, codes: list[str]) -> list[DefectType]:
    found = {t.defect_code: t for t in db.scalars(select(DefectType).where(DefectType.defect_code.in_(codes)))}
    return [found[c] for c in codes if c in found]


def auto_report(types: list[DefectType]) -> str | None:
    """불량 종류 표의 원인 후보·권장 조치를 짧게 정리한 기본 요약 (AI 없이도 항상 만들 수 있음)"""
    if not types:
        return None
    lines = [HEADER_AUTO]
    for t in types:
        causes = ", ".join(t.cause_candidates or []) or "-"
        lines.append(f"{t.defect_code} {t.defect_name}: 원인 후보 {causes} → 조치 {t.recommended_action or '-'}")
    return "\n".join(lines)


def _prompt(product_name: str, types: list[DefectType]) -> str:
    items = "\n".join(
        f"- {t.defect_code} {t.defect_name} (위치: {t.defect_location or '-'}) / 원인 후보: "
        f"{', '.join(t.cause_candidates or []) or '-'} / 표준 조치: {t.recommended_action or '-'}" for t in types)
    return (
        "스마트팩토리 비전 품질관리부 불량 조치 요약을 작성한다.\n"
        f"제품: {product_name}\n작업자가 확정한 불량 코드:\n{items}\n\n"
        "위 정보만 근거로 현장 엔지니어가 바로 참고할 조치 요약을 3줄 이내의 간결한 한국어로 쓴다. "
        "원인은 확정이 아니라 후보로 표현하고, 주어진 정보에 없는 수치나 사실은 만들지 않는다.")


def ask_ollama(prompt: str) -> str | None:
    """Ollama 에 요약을 요청한다. 설정이 비었거나 연결 실패·시간 초과면 None (조용히 기본 요약 사용)"""
    if not settings.OLLAMA_URL:
        return None
    body = json.dumps({"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(settings.OLLAMA_URL.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=settings.OLLAMA_TIMEOUT_S) as res:
            text = (json.loads(res.read().decode("utf-8")).get("response") or "").strip()
        return text or None
    except Exception as exc:  # 연결 거부, 시간 초과, 모델 없음 등 — AI 는 선택 기능이라 실패해도 검사 기능에 영향 없음
        log.info("Ollama 요약을 건너뜁니다: %s", exc)
        return None


def set_auto_report(insp: ProductInspection, db: Session) -> None:
    """지정된 코드로 기본 요약을 만들어 검사 행에 넣는다 (커밋은 호출한 쪽). 지정된 코드가 없으면 비운다"""
    insp.ai_report = auto_report(_types(db, assigned_codes(insp)))


def upgrade_with_ai(inspection_id: str) -> None:
    """백그라운드 작업: Ollama 요약으로 바꾼다. 자기 DB 세션을 따로 연다 (요청의 세션은 이미 닫힘)"""
    with SessionLocal() as db:
        insp = db.scalars(select(ProductInspection).where(ProductInspection.inspection_id == inspection_id)).first()
        if insp is None:
            return
        codes = assigned_codes(insp)
        types = _types(db, codes)
        if not types:
            return
        before = insp.ai_report
        text = ask_ollama(_prompt(insp.product_name, types))
        if not text:
            return
        db.refresh(insp)
        if insp.ai_report != before or assigned_codes(insp) != codes:
            return  # 그 사이 코드를 또 바꿨으면 오래된 요약으로 덮어쓰지 않는다
        insp.ai_report = f"{HEADER_AI}\n{text}"
        db.commit()
