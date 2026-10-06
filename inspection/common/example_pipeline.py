"""
검사 라인 한 사이클 예시 (example_pipeline.py)
제품 1개 → 3D 치수 → PatchCore → (불합격이면) YOLO → MES 기록
실제 모델 호출 부분(measure_3d, run_patchcore, run_yolo)만 팀 코드로 바꾸면 된다.

  python example_pipeline.py RC-0001 sample.jpg

치수가 불합격이면 검사 종료, PatchCore 가 합격이면 정상(YOLO 생략).
최종 결과(final_result)는 MES 서버가 자동으로 계산한다.
"""
import logging
import sys
from datetime import datetime

from mes_client import MESClient

logging.basicConfig(level=logging.INFO)  # 전송 성공/실패 로그를 화면에 보이게

# 서버 주소와 키는 실제 환경에 맞게 바꿀 것
mes = MESClient("http://127.0.0.1:8000", api_key="change-this-ingest-key", model_version="v1.0")
PATCHCORE_THRESHOLD = 0.6


def measure_3d(image_path):          # ← 3D 스캔 치수 측정 코드로 교체 (가로, 길이, 높이 mm)
    return 40.12, 89.95, 30.03


def run_patchcore(image_path):       # ← PatchCore 추론 코드로 교체 (이상 점수)
    return 0.71


def run_yolo(image_path):            # ← YOLO 추론 코드로 교체 (yolo_to_defects 사용 권장)
    return [{"defect_class": "scratch", "confidence": 0.91, "box": [120, 80, 180, 130]}]


def inspect(serial, image_path):
    """제품 1개 검사. 마지막으로 서버가 알려준 최종 결과를 돌려준다"""
    iid = datetime.now().strftime("%Y%m%d_inspection_%H%M%S_001")  # 날짜 포함 검사번호
    mes.start(iid, "redcar", product_serial=serial)

    # 1) 3D 치수
    r = mes.send_dimension(iid, *measure_3d(image_path))
    if r and r["dimension_result"] != "PASS":
        return r["final_result"]

    # 2) PatchCore
    r = mes.send_patchcore(iid, run_patchcore(image_path), PATCHCORE_THRESHOLD)
    if r and r["patchcore_result"] == "PASS":
        return r["final_result"]  # NORMAL

    # 3) YOLO (PatchCore 불합격일 때 불량 분류)
    mes.send_yolo_capture(iid, 1, image_path, defects=run_yolo(image_path))
    r = mes.complete_yolo(iid)
    # r 이 None 이면 서버에 못 보내고 큐에 쌓인 상태
    return r["final_result"] if r else f"서버 연결 안 됨 - 큐에 {mes.pending()}건 대기"


if __name__ == "__main__":
    serial, img = sys.argv[1:3]  # 명령줄 인자: 제품식별번호 사진경로
    print(inspect(serial, img))
