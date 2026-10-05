"""
검사 라인 한 사이클 예시 (example_pipeline.py)   [기능 F08 · 담당 B]
제품 1개 → 3D 치수 → PatchCore → YOLO → MES 기록
실제 모델 호출 부분(measure_3d, run_patchcore, run_yolo)만 팀 코드로 바꾸면 된다.

  python example_pipeline.py SN0001 Redcar sample.png

앞 공정에서 NG 가 나면 다음 공정은 하지 않는다 (불량품은 라인에서 빠진다고 가정).
"""
import logging
import sys

from mes_client import MESClient, patchcore_to_detections

logging.basicConfig(level=logging.INFO)  # 전송 성공/실패 로그를 화면에 보이게

# 서버 주소와 키는 실제 환경에 맞게 바꿀 것
mes = MESClient("http://localhost:8000", api_key="change-this-ingest-key", model_version="v1.0")


def measure_3d(image_path):          # ← 3D 모델링 치수 측정 코드로 교체
    return 40.12, 89.95, 30.03


def run_patchcore(image_path):       # ← PatchCore 추론 코드로 교체 (점수, 박스)
    return 0.31, None


def run_yolo(image_path):            # ← YOLO 추론 코드로 교체 (yolo_to_detections 사용 권장)
    return [{"type": "scratch", "confidence": 0.91, "box": [120, 80, 180, 130]}]


def inspect(serial, item, image_path):
    """제품 1개 검사. 최종 결과 문자열을 돌려준다"""
    # 1) 3D 치수
    w, l, h = measure_3d(image_path)
    r = mes.send_dimension(serial, item, image_path, width=w, length=l, height=h)
    if r and r["result"] == "NG":
        return "NG (치수)"

    # 2) PatchCore
    score, box = run_patchcore(image_path)
    r = mes.send_defects(serial, item, "PATCHCORE", image_path,
                         patchcore_to_detections(score, threshold=0.5, box=box))
    if r and r["result"] == "NG":
        return "NG (PatchCore)"

    # 3) YOLO
    r = mes.send_defects(serial, item, "YOLO", image_path, run_yolo(image_path))
    if r and r["result"] == "NG":
        return "NG (YOLO)"
    # r 이 None 이면 서버에 못 보내고 큐에 쌓인 상태
    return "OK" if r else f"서버 연결 안 됨 - 큐에 {mes.pending()}건 대기"


if __name__ == "__main__":
    serial, item, img = sys.argv[1:4]  # 명령줄 인자: 시리얼 품목 이미지경로
    print(inspect(serial, item, img))
