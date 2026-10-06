"""
검사 PC(3D 치수 / PatchCore / YOLO 프로그램) → MES 결과 전송 클라이언트 (mes_client.py)

이미 만들어 둔 AI 코드에서 이 파일 하나만 import 해서 쓰면 된다.
  pip install requests

MES 는 "검사 1회 = product_inspection 1행" 이다. 같은 inspection_id 로 단계별 결과를 채워 넣는다.

    from mes_client import MESClient, safety_ok, yolo_to_defects

    mes = MESClient("http://MES서버IP:8000", api_key="change-this-ingest-key")
    iid = "20261006_inspection_143000_001"          # 검사 고유번호 (날짜 포함 권장)

    mes.start(iid, "redcar", product_serial="RC-0001")      # 0) 검사 시작
    mes.send_dimension(iid, 40.1, 90.0, 30.2)                # 1) 3D 치수 (합불은 DB 가 자동 계산)
    mes.send_patchcore(iid, score=0.82, threshold=0.6)       # 2) PatchCore (점수 >= 기준 → 불합격)
    mes.send_yolo_capture(iid, 1, "c001.jpg", "c001_annotated.jpg",   # 3) YOLO 결함 사진 1장씩
                          defects=yolo_to_defects(result, conf_min=0.8), angle_deg=95.0)
    mes.complete_yolo(iid)                                   # 4) YOLO 분류 완료

    # 장비 안전 (센터링 · 인터락): 시작 전과 각 단계 중에 확인. 허용 판단은 safety_ok() 로 이 PC 에서 바로
    if not safety_ok(centering, interlock):                  # 센터링 OFF + 인터락 0 이 아니면
        stop_equipment()                                     #   장비 정지 → 검사 보류 (검사 프로그램이 직접)
    mes.check_safety("YOLO", centering, interlock, inspection_id=iid)   # 상태 기록 (이상이면 MES 가 알람 저장)

최종 결과(final_result)는 서버 DB 가 단계별 결과에서 자동으로 계산한다.

서버가 꺼져 있거나 네트워크가 끊기면 요청을 queue 폴더에 쌓아두고,
다음 전송 때(또는 flush_queue() 호출 시) 보낸 순서 그대로 다시 보낸다. 시각 값은 처음 그대로 유지된다.

반환값
  dict  : 서버가 저장한 검사 상세 (final_result 등으로 확인 가능)
  None  : 서버에 못 보내서 큐에 쌓아둠
  예외  : MESError (서버가 형식 오류로 거부), FileNotFoundError (사진 경로 틀림)

큐 폴더 구조
  mes_queue/<시각ns>_<랜덤>/request.json + 사진 파일들   ← 폴더 이름순 = 보낼 순서
  mes_queue_failed/...                                    ← 서버가 거부한 건 (사람이 확인 필요)
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


class MESError(Exception):
    """서버가 데이터를 거부함 (형식 오류 등). 큐에 쌓지 않고 바로 알려준다"""


class MESClient:
    def __init__(self, base_url: str, api_key: str, queue_dir: str | Path = "./mes_queue",
                 timeout: float = 10.0, model_version: str | None = None):
        """
        base_url      : MES 서버 주소 (예: http://192.168.0.10:8000)
        api_key       : 서버 .env 의 INGEST_API_KEY 와 같은 값
        queue_dir     : 전송 실패 시 요청을 쌓아둘 폴더
        timeout       : 요청 1번 기다리는 최대 시간(초)
        model_version : 기본으로 붙일 AI 모델 버전 (PatchCore/YOLO 전송 때 따로 줄 수도 있음)
        """
        self.root = base_url.rstrip("/")
        self.base = self.root + "/api/inspections"
        self.headers = {"X-API-Key": api_key}
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.model_version = model_version
        self.product_name: dict[str, str] = {}  # inspection_id → 제품 모델명 (단계 API 가 검사 행을 만들 때 사용)

    # ------------------------------------------------------------------ 단계별 전송
    def start(self, inspection_id: str, product_name: str, product_serial: str | None = None,
              capture_folder: str | None = None, started_at: datetime | None = None) -> dict | None:
        """검사 1회 시작 (또는 기본 정보 수정)"""
        self.product_name[inspection_id] = product_name
        return self._send("PUT", inspection_id, "", json_body={
            "product_name": product_name, "product_serial": product_serial,
            "capture_folder": capture_folder,
            "started_at": (started_at or datetime.now().astimezone()).isoformat()})

    def send_dimension(self, inspection_id: str, width: float | None, length: float | None,
                       height: float | None, standards: tuple[float, float, float] | None = None,
                       scan_file_path: str | None = None, centering: str | None = None,
                       interlock: str | None = None) -> dict | None:
        """3D 치수 측정값 (mm). standards=(가로, 길이, 높이) 를 안 주면 서버 설정의 기준을 쓴다.
        centering("OFF"/"ON"/"UNKNOWN"), interlock("0"/"1"/"UNKNOWN") 은 측정 시점 장비 상태 (안 주면 서버가 미확인으로 기록)"""
        body = {"width_mm": _r(width), "length_mm": _r(length), "height_mm": _r(height),
                "scan_file_path": scan_file_path}
        if centering is not None:
            body["centering_state"] = centering
        if interlock is not None:
            body["interlock_state"] = interlock
        if standards:
            body.update(standard_width_mm=standards[0], standard_length_mm=standards[1],
                        standard_height_mm=standards[2])
        return self._send("PUT", inspection_id, "/dimension", json_body=body)

    def send_patchcore(self, inspection_id: str, score: float, threshold: float,
                       model_version: str | None = None) -> dict | None:
        """PatchCore 이상 점수와 그때의 판정 기준"""
        return self._send("PUT", inspection_id, "/patchcore", json_body={
            "score": float(score), "threshold": float(threshold),
            "model_version": model_version or self.model_version})

    def send_yolo_capture(self, inspection_id: str, capture_number: int, original: str | Path,
                          annotated: str | Path | None = None, defects: list[dict] = (),
                          angle_deg: float | None = None, captured_at: datetime | None = None,
                          model_version: str | None = None) -> dict | None:
        """YOLO 결함 사진 1장. defects: [{"defect_class": "scratch", "confidence": 0.9, "box": [x1,y1,x2,y2]}]"""
        files = {"original": Path(original)}
        if annotated:
            files["annotated"] = Path(annotated)
        for p in files.values():
            if not p.is_file():
                raise FileNotFoundError(p)
        payload = {"capture_number": int(capture_number), "angle_deg": angle_deg,
                   "captured_at": (captured_at or datetime.now().astimezone()).isoformat(),
                   "model_version": model_version or self.model_version, "defects": list(defects)}
        return self._send("POST", inspection_id, "/yolo/captures", form={"payload": payload}, files=files)

    def complete_yolo(self, inspection_id: str, model_version: str | None = None) -> dict | None:
        """YOLO 분류 완료 (한 바퀴 검사가 끝났을 때)"""
        return self._send("PUT", inspection_id, "/yolo/complete",
                          json_body={"model_version": model_version or self.model_version})

    def check_safety(self, stage: str, centering: str, interlock: str, inspection_id: str | None = None,
                     message: str | None = None) -> dict | None:
        """장비 안전 상태(센터링·인터락)를 MES 에 기록. 이상이면 MES 가 알람을 남긴다.
        stage: PRECHECK / DIMENSION / PATCHCORE / YOLO. 반환: {"allowed": bool, "alarms": [...]} 또는 None(큐)
        ※ 검사를 멈출지는 서버 응답을 기다리지 말고 safety_ok() 로 이 PC 에서 바로 판단할 것"""
        body = {"stage": stage, "centering_state": centering, "interlock_state": interlock, "message": message}
        if inspection_id:
            body.update(inspection_id=inspection_id, product_name=self.product_name.get(inspection_id))
        return self._send("POST", None, "", json_body=body, path="/api/safety/check")

    # ------------------------------------------------------------------ 공통 전송 · 큐
    def _send(self, method: str, inspection_id: str | None, suffix: str, json_body: dict | None = None,
              form: dict | None = None, files: dict[str, Path] | None = None,
              path: str | None = None) -> dict | None:
        """밀린 큐 먼저 → 이번 요청 전송 (실패 시 큐). path 를 주면 검사 주소 대신 그 주소로 보낸다"""
        req = {"method": method, "inspection_id": inspection_id, "suffix": suffix, "path": path,
               "product_name": self.product_name.get(inspection_id) if inspection_id else None,
               "json": json_body, "form": form}
        self.flush_queue()  # 밀린 것부터 보내서 순서 유지
        if self.pending():  # 아직 못 보낸 게 남아 있으면 새 요청도 뒤에 줄 세움 (순서 + 대기시간 절약)
            self._enqueue(req, files or {})
            return None
        try:
            return self._request(req, files or {})
        except (requests.ConnectionError, requests.Timeout, _ServerDown) as e:
            log.warning("MES 전송 실패 → 큐에 저장: %s", e)
            self._enqueue(req, files or {})
            return None

    def _request(self, req: dict, files: dict[str, Path]) -> dict:
        """실제 HTTP 전송"""
        if req.get("path"):
            url = self.root + req["path"]
        else:
            url = f"{self.base}/{req['inspection_id']}{req['suffix']}"
        params = {"product_name": req["product_name"]} if req.get("product_name") else None
        opened = {k: open(p, "rb") for k, p in files.items()}
        try:
            if opened:  # multipart: 사진 + payload(JSON 문자열)
                data = {k: json.dumps(v, ensure_ascii=False) for k, v in (req.get("form") or {}).items()}
                r = requests.request(req["method"], url, headers=self.headers, params=params,
                                     timeout=self.timeout, data=data,
                                     files={k: (Path(f.name).name, f) for k, f in opened.items()})
            else:
                r = requests.request(req["method"], url, headers=self.headers, params=params,
                                     timeout=self.timeout, json=req.get("json"))
        finally:
            for f in opened.values():
                f.close()
        if r.status_code >= 500:   # 서버 내부 문제 → 재시도 대상
            raise _ServerDown(f"{r.status_code} {r.text[:200]}")
        if r.status_code >= 400:   # 데이터/키 문제 → 다시 보내도 같으니 바로 에러
            raise MESError(f"{r.status_code} {r.text[:500]}")
        res = r.json()
        log.info("MES 등록: %s → %s", req.get("path") or f"{req['inspection_id']}{req['suffix']}",
                 res.get("final_result", res.get("allowed")))
        return res

    def _enqueue(self, req: dict, files: dict[str, Path]):
        """요청 1건을 큐 폴더에 저장 (사진 복사본 + request.json)"""
        job = self.queue_dir / f"{time.time_ns()}_{uuid.uuid4().hex[:6]}"  # 이름순 = 시간순
        job.mkdir()
        req = {**req, "files": {}}
        for field, p in files.items():
            name = f"{field}{p.suffix}"
            shutil.copy2(p, job / name)
            req["files"][field] = name
        (job / "request.json").write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")

    def pending(self) -> int:
        """아직 못 보낸 요청 개수"""
        return sum(1 for p in self.queue_dir.iterdir() if p.is_dir())

    def flush_queue(self) -> int:
        """큐에 쌓인 요청을 오래된 순서로 재전송. 보낸 개수 반환 (서버가 아직 안 되면 멈춤)"""
        sent = 0
        for job in sorted(p for p in self.queue_dir.iterdir() if p.is_dir()):
            req_file = job / "request.json"
            if not req_file.exists():  # 저장 중 끊겨서 망가진 항목은 버림
                shutil.rmtree(job, ignore_errors=True)
                continue
            req = json.loads(req_file.read_text(encoding="utf-8"))
            files = {k: job / v for k, v in req.pop("files", {}).items()}
            try:
                self._request(req, files)
            except (requests.ConnectionError, requests.Timeout, _ServerDown):
                break  # 서버가 아직 안 됨 → 다음 기회에
            except MESError as e:
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


def safety_ok(centering: str | None, interlock: str | None) -> bool:
    """검사 허용: 센터링 OFF(정위치) 그리고 인터락 0(정상) 일 때만. 미확인(UNKNOWN)·센서 응답 끊김은 금지"""
    return centering == "OFF" and str(interlock) == "0"


def _r(v: float | None) -> float | None:
    """치수는 소수 3자리까지"""
    return None if v is None else round(float(v), 3)


def yolo_to_defects(result, conf_min: float = 0.0) -> list[dict]:
    """ultralytics YOLO 의 Results 1개 → send_yolo_capture 의 defects 리스트"""
    out = []
    boxes = result.boxes
    if boxes is None:
        return out
    names = result.names  # {클래스번호: 이름}
    for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
        if conf < conf_min:  # 신뢰도가 기준보다 낮은 박스는 버림
            continue
        out.append({"defect_class": str(names[int(cls)]), "confidence": round(float(conf), 4),
                    "box": [round(float(v), 1) for v in xyxy]})
    return out
