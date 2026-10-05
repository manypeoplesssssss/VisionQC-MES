"""
검사 PC(3D 치수 / PatchCore / YOLO 프로그램) → MES 결과 전송 클라이언트 (mes_client.py)   [기능 F08 · 담당 B]

이미 만들어 둔 AI 코드에서 이 파일 하나만 import 해서 쓰면 된다.
  pip install requests        (anomaly_map_to_box 를 쓰면 numpy 도 필요)

    from mes_client import MESClient, yolo_to_detections, patchcore_to_detections

    mes = MESClient("http://MES서버IP:8000", api_key="change-this-ingest-key")

    # 1) 3D 치수 (규격은 서버에 있으면 서버가 판정, status 는 생략 가능)
    mes.send_dimension("SN0001", "Redcar", "scan.png", width=40.1, length=90.0, height=30.0)

    # 2) PatchCore
    mes.send_defects("SN0001", "Redcar", "PATCHCORE", "pc.png",
                     patchcore_to_detections(score=0.82, threshold=0.5, box=[100, 80, 160, 140]))

    # 3) YOLO (ultralytics 결과 그대로)
    r = model("img.png")[0]
    mes.send_defects("SN0001", "Redcar", "YOLO", "img.png", yolo_to_detections(r, conf_min=0.5))

서버가 꺼져 있거나 네트워크가 끊기면 결과를 queue 폴더에 쌓아두고,
다음 전송 때(또는 flush_queue() 호출 시) 순서대로 다시 보낸다. 검사 시각은 처음 검사한 시각 그대로 유지된다.

반환값
  dict  : 서버가 저장한 결과 (result 로 OK/NG 확인 가능)
  None  : 서버에 못 보내서 큐에 쌓아둠
  예외  : MESError (서버가 형식 오류로 거부), FileNotFoundError (이미지 경로 틀림)

큐 폴더 구조
  mes_queue/<시각ns>_<랜덤>/payload.json + 이미지    ← 폴더 이름순 = 보낼 순서
  mes_queue_failed/...                                 ← 서버가 거부한 건 (사람이 확인 필요)
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("mes_client")

PROCESSES = ("DIM3D", "PATCHCORE", "YOLO")


class MESError(Exception):
    """서버가 데이터를 거부함 (형식 오류 등). 큐에 쌓지 않고 바로 알려준다"""


class MESClient:
    def __init__(self, base_url: str, api_key: str, queue_dir: str | Path = "./mes_queue",
                 timeout: float = 10.0, model_version: str | None = None):
        """
        base_url      : MES 서버 주소 (예: http://192.168.0.10:8000)
        api_key       : 서버 .env 의 INGEST_API_KEY 와 같은 값
        queue_dir     : 전송 실패 시 결과를 쌓아둘 폴더
        timeout       : 요청 1번 기다리는 최대 시간(초)
        model_version : 기본으로 붙일 AI 모델 버전 (전송할 때 따로 줄 수도 있음)
        """
        self.url = base_url.rstrip("/") + "/api/inspections"
        self.headers = {"X-API-Key": api_key}
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.model_version = model_version

    # ---------- 공정별 전송 ----------
    def send_dimension(self, serial_no: str, item: str, image_path: str | Path,
                       width: float, length: float, height: float,
                       status: str | None = None, inspected_at: datetime | None = None,
                       model_version: str | None = None) -> dict | None:
        """3D 치수검사 결과 전송. status("OK"/"NG")는 서버에 규격이 없을 때만 필요"""
        # numpy float 등도 받을 수 있게 float() 로 바꾸고 소수 3자리로 정리
        dim = {"width_mm": round(float(width), 3), "length_mm": round(float(length), 3),
               "height_mm": round(float(height), 3)}
        if status:
            dim["status"] = status
        return self._send(image_path, {
            "serial_no": serial_no, "item": item, "process": "DIM3D", "dimension": dim,
        }, inspected_at, model_version)

    def send_defects(self, serial_no: str, item: str, process: str, image_path: str | Path,
                     detections: list[dict], inspected_at: datetime | None = None,
                     model_version: str | None = None) -> dict | None:
        """detections: [{"type": "scratch", "confidence": 0.9, "box": [x1,y1,x2,y2]}, ...] 비어 있으면 양품"""
        if process not in ("PATCHCORE", "YOLO"):
            raise ValueError("process 는 PATCHCORE 또는 YOLO")
        # 결함 목록이 비어 있으면 "결함 없음" 1행을 보낸다
        defects = [{"defect_detected": True, **d} for d in detections] or [{"defect_detected": False}]
        return self._send(image_path, {
            "serial_no": serial_no, "item": item, "process": process, "defects": defects,
        }, inspected_at, model_version)

    # ---------- 내부 ----------
    def _send(self, image_path, payload, inspected_at, model_version):
        """공통 전송 처리: 검사 시각 기록 → 밀린 큐 먼저 → 이번 결과 전송 (실패 시 큐)"""
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        # 검사 시각을 '지금(시간대 포함)'으로 미리 박아둔다 → 나중에 재전송돼도 원래 시각 유지
        payload["inspected_at"] = (inspected_at or datetime.now().astimezone()).isoformat()
        if model_version or self.model_version:
            payload["model_version"] = model_version or self.model_version

        self.flush_queue()  # 밀린 것부터 보내서 순서 유지
        if self.pending():  # 아직 못 보낸 게 남아 있으면 새 결과도 뒤에 줄 세움 (순서 + 대기시간 절약)
            self._enqueue(image_path, payload)
            return None
        try:
            return self._post(image_path, payload)
        except (requests.ConnectionError, requests.Timeout, _ServerDown) as e:
            # 네트워크/서버 문제 → 나중에 다시 보낼 수 있으니 큐에 저장
            log.warning("MES 전송 실패 → 큐에 저장: %s", e)
            self._enqueue(image_path, payload)
            return None

    def _post(self, image_path: Path, payload: dict) -> dict:
        """실제 HTTP 전송 (multipart: image + payload)"""
        with open(image_path, "rb") as f:
            r = requests.post(self.url, headers=self.headers, timeout=self.timeout,
                              files={"image": (image_path.name, f)},
                              data={"payload": json.dumps(payload, ensure_ascii=False)})
        if r.status_code >= 500:   # 서버 내부 문제 → 재시도 대상
            raise _ServerDown(f"{r.status_code} {r.text[:200]}")
        if r.status_code >= 400:   # 데이터/키 문제 → 다시 보내도 같으니 바로 에러
            raise MESError(f"{r.status_code} {r.text[:500]}")
        res = r.json()
        log.info("MES 등록: %s %s", res.get("image_filename"), res.get("result"))
        return res

    def _enqueue(self, image_path: Path, payload: dict):
        """결과 1건을 큐 폴더에 저장 (이미지 복사본 + payload.json)"""
        job = self.queue_dir / f"{time.time_ns()}_{uuid.uuid4().hex[:6]}"  # 이름순 = 시간순
        job.mkdir()
        shutil.copy2(image_path, job / image_path.name)
        (job / "payload.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def pending(self) -> int:
        """아직 못 보낸 결과 개수"""
        return sum(1 for p in self.queue_dir.iterdir() if p.is_dir())

    def flush_queue(self) -> int:
        """큐에 쌓인 결과를 오래된 순서로 재전송. 보낸 개수 반환 (서버가 아직 안 되면 멈춤)"""
        sent = 0
        for job in sorted(p for p in self.queue_dir.iterdir() if p.is_dir()):
            payload_file = job / "payload.json"
            images = [p for p in job.iterdir() if p.name != "payload.json"]
            if not payload_file.exists() or not images:  # 저장 중 끊겨서 망가진 항목은 버림
                shutil.rmtree(job, ignore_errors=True)
                continue
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
            try:
                self._post(images[0], payload)
            except (requests.ConnectionError, requests.Timeout, _ServerDown):
                break  # 서버가 아직 안 됨 → 다음 기회에
            except MESError as e:
                # 서버가 거부한 건 다시 보내도 소용없으므로 따로 옮겨둠
                log.error("큐 항목을 서버가 거부 → failed 폴더로 이동: %s", e)
                failed = self.queue_dir.parent / (self.queue_dir.name + "_failed")
                failed.mkdir(exist_ok=True)
                shutil.move(str(job), failed / job.name)
                continue
            shutil.rmtree(job, ignore_errors=True)  # 성공한 항목 삭제
            sent += 1
        return sent


class _ServerDown(Exception):
    """5xx 응답 (내부용). 연결 실패와 똑같이 '나중에 재시도' 로 처리"""
    pass


# ---------- 모델 출력 → MES 형식 변환 ----------
def yolo_to_detections(result, conf_min: float = 0.0) -> list[dict]:
    """ultralytics YOLO 의 Results 1개 → detections 리스트"""
    out = []
    boxes = result.boxes
    if boxes is None:
        return out
    names = result.names  # {클래스번호: 이름}
    for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
        if conf < conf_min:  # 신뢰도가 기준보다 낮은 박스는 버림
            continue
        out.append({"type": str(names[int(cls)]), "confidence": round(float(conf), 4),
                    "box": [round(float(v), 1) for v in xyxy]})
    return out


def patchcore_to_detections(score: float, threshold: float, box: list[float] | None = None,
                            defect_type: str = "anomaly") -> list[dict]:
    """PatchCore 이상 점수 → detections. 임계값 넘으면 결함 1건.
    box 는 anomaly map 에서 뽑은 영역(없으면 None). confidence 에는 0~1로 자른 점수를 넣는다."""
    if score < threshold:
        return []
    return [{"type": defect_type, "confidence": round(min(max(float(score), 0.0), 1.0), 4), "box": box}]


def anomaly_map_to_box(anomaly_map, threshold: float) -> list[float] | None:
    """anomaly map(2D numpy 배열, 이미지 크기 기준)에서 임계값을 넘는 영역의 외곽 박스"""
    import numpy as np
    ys, xs = np.where(np.asarray(anomaly_map) >= threshold)  # 기준 넘는 픽셀 좌표들
    if len(xs) == 0:
        return None
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
