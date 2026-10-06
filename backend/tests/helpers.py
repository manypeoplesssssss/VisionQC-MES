"""
테스트 공용 도우미 (tests/helpers.py)

사용: from tests.helpers import TODAY, SCRATCH
"""
from datetime import date

TODAY = date.today().isoformat()

# YOLO 결함 1개 예시
SCRATCH = {"defect_class": "scratch", "confidence": 0.91, "box": [10, 20, 40, 60]}
WHITE_PAINT = {"defect_class": "white_paint", "confidence": 0.85, "box": [5, 5, 15, 25]}
