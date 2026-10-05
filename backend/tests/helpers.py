"""
테스트 공용 도우미 (tests/helpers.py)

여러 기능의 테스트가 같이 쓰는 payload 생성 함수.
사용: from tests.helpers import TODAY, dim, defect
"""
from datetime import date

TODAY = date.today().isoformat()


def dim(serial, w=40.0, length=90.0, h=30.0, item="Redcar", status=None, at=None):
    """DIM3D 업로드 payload (기본값은 Redcar 규격 정중앙 → OK)"""
    d = {"width_mm": w, "length_mm": length, "height_mm": h}
    if status:
        d["status"] = status
    p = {"serial_no": serial, "item": item, "process": "DIM3D", "dimension": d}
    if at:
        p["inspected_at"] = at
    return p


def defect(serial, process, found=(), item="Redcar"):
    """PATCHCORE/YOLO 업로드 payload. found 가 비어 있으면 결함 없음"""
    defects = [{"defect_detected": True, **f} for f in found] or [{"defect_detected": False}]
    return {"serial_no": serial, "item": item, "process": process, "defects": defects}
