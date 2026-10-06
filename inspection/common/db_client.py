"""
검사 PC → DB 직접 저장 모듈 (db_client.py)

검사 프로그램은 결과를 DB(MySQL)에 바로 저장하고, MES 서버와 화면은 DB 에서 읽기만 한다.
    검사 PC ──(이 모듈)──▶ MySQL ◀──(읽기)── MES 서버 ◀── 화면

    from db_client import DBClient, safety_ok

    db = DBClient("mysql+pymysql://mes_user:mes_pass@<DB서버IP>:3306/visionqc_mes?charset=utf8mb4",
                  storage_dir=r"\\\\MES서버\\images")      # MES 가 사진을 읽는 폴더 (같은 PC 면 기본값)
    iid = "20261006_inspection_143000_001"                    # 검사 고유번호 (날짜 포함)
    db.start(iid, "redcar", product_serial="RC-0001")         # 0) 검사 시작
    db.send_dimension(iid, 194.8, 85.0, 58.7, standards=(194.5, 84.96, 58.68), centering="OFF", interlock="0")
    db.send_patchcore(iid, score=0.82, threshold=0.6)         # 2) PatchCore (점수 >= 기준 → 불합격)
    db.send_yolo_capture(iid, 1, "c001.jpg", "c001_annotated.jpg", defects=[...], angle_deg=95.0)
    db.complete_yolo(iid)                                     # 4) YOLO 분류 완료
    db.check_safety("YOLO", "OFF", "1", inspection_id=iid)    # 장비 안전 상태 기록 (이상이면 알람 행 추가)

메서드 이름과 인자는 예전 mes_client.MESClient 와 같다 (검사 프로그램은 클래스만 바꿔 끼우면 됨).

규칙 (MES 와 같아야 하는 것)
  - 테이블은 MES 서버(backend)가 처음 뜰 때 만든다. 이 모듈은 있는 테이블을 읽어서(reflect) 쓴다
  - 치수 축별·종합 판정과 final_result 는 DB 생성 컬럼이 자동 계산 → 여기서 계산하지 않는다
  - PatchCore: 점수 >= 기준이면 FAIL
  - 장비 안전: 센터링 OFF + 인터락 0 만 허용. 이상이면 조건마다 알람 1행
    (같은 검사·단계·상태의 발생 중 알람이 있으면 중복 안 만듦) — backend/app/services/safety.py 와 같은 규칙
  - 사진은 storage_dir/<일자>/<일자>-<제품>-<시각>-YOLO-<검사번호>_c<번호>[_annotated].<확장자> 로 복사하고
    DB 에는 storage_dir 기준 상대경로를 기록 — backend/app/storage.py 와 같은 규칙

DB 에 연결이 안 되면 요청을 queue 폴더(db_queue/)에 쌓아두고, 다음 저장 때 순서대로 다시 저장한다.
반환값: dict (저장 후 검사 상태 요약) / None (연결 안 돼서 큐에 쌓음) / 예외 DBError (데이터 문제)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.exc import DBAPIError, OperationalError

log = logging.getLogger("db_client")

REPO = Path(__file__).resolve().parents[2]
# 같은 PC 에서 MES 를 돌릴 때 MES 가 사진을 읽는 폴더 (backend/.env 의 STORAGE_DIR 기본값과 같은 곳)
DEFAULT_STORAGE_DIR = REPO / "backend" / "storage" / "images"
DEFAULT_DB_URL = "mysql+pymysql://mes_user:mes_pass@localhost:3306/visionqc_mes?charset=utf8mb4"

# 치수 판정 한계 (기록용). 실제 판정은 DB 생성 컬럼 — backend/app/models.py 의 값과 같게 유지
DIM_TOLERANCE_MM = {"width": 2.5, "length": 3.5, "height": 2.0}
DIM_RECHECK_MM = {"width": 1.5, "length": 2.0, "height": 1.5}
AXES = ("width", "length", "height")
_SAFE = re.compile(r"[^A-Za-z0-9_]")
_KO_CENTERING = {"OFF": "정위치", "ON": "위치 이상", "UNKNOWN": "미확인"}
_KO_INTERLOCK = {"0": "정상", "1": "비정상", "UNKNOWN": "미확인"}
_KO_STAGE = {"PRECHECK": "사전 확인", "DIMENSION": "3D 치수", "PATCHCORE": "PatchCore", "YOLO": "YOLO"}


class DBError(Exception):
    """DB 가 데이터를 거부함 (검사번호 없음, 사진 번호 중복 등). 큐에 쌓지 않고 바로 알려준다"""


def default_db_url() -> str:
    """환경변수 VISIONQC_DB_URL > backend/.env 의 DATABASE_URL > MySQL 기본값"""
    if os.environ.get("VISIONQC_DB_URL"):
        return os.environ["VISIONQC_DB_URL"]
    env = REPO / "backend" / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return DEFAULT_DB_URL


def safety_ok(centering: str | None, interlock: str | None) -> bool:
    """검사 허용: 센터링 OFF(정위치) 그리고 인터락 0(정상) 일 때만. 미확인(UNKNOWN)·센서 응답 끊김은 금지"""
    return centering == "OFF" and str(interlock) == "0"


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _local(dt: datetime | None) -> datetime:
    """시간대가 붙은 시각은 이 PC 로컬 시각으로 (DB 는 로컬 시각 기준)"""
    if dt is None:
        return _now()
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _num(v):
    """DB 숫자 → float (MySQL DOUBLE 은 Decimal 로 읽힐 수 있어 JSON 에 못 넣음)"""
    return None if v is None else float(v)


def _json(v, default):
    """JSON 컬럼 값 → 파이썬 (DB 종류에 따라 문자열로 올 수도 있음)"""
    if v is None:
        return default
    return json.loads(v) if isinstance(v, (str, bytes)) else v


class DBClient:
    def __init__(self, db_url: str | None = None, storage_dir: str | Path | None = None,
                 queue_dir: str | Path = "./db_queue", model_version: str | None = None):
        """
        db_url       : SQLAlchemy 주소 (MES 서버와 같은 DB). 없으면 default_db_url()
        storage_dir  : MES 가 사진을 읽는 폴더 (MES 의 STORAGE_DIR 과 같은 곳). 다른 PC 면 공유 폴더
        queue_dir    : DB 연결이 안 될 때 요청을 쌓아둘 폴더
        """
        self.db_url = db_url or default_db_url()
        self.storage_dir = Path(storage_dir or DEFAULT_STORAGE_DIR)
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.model_version = model_version
        self.product_name: dict[str, str] = {}  # inspection_id → 제품 모델명 (검사 행이 없을 때 만들기용)
        connect_args = {"check_same_thread": False} if self.db_url.startswith("sqlite") else {}
        self.engine = create_engine(self.db_url, pool_pre_ping=True, connect_args=connect_args)
        self._tables = None

    # ------------------------------------------------------------------ 테이블
    def _t(self):
        """MES 가 만든 테이블을 한 번 읽어 둔다 (생성 컬럼까지 그대로 쓰기 위해)"""
        if self._tables is None:
            meta = MetaData()
            names = ("product_inspection", "product_dimension_inspection", "equipment_safety_alarm")
            self._tables = {n: Table(n, meta, autoload_with=self.engine) for n in names}
        return self._tables

    def _row(self, conn, iid: str):
        pi = self._t()["product_inspection"]
        return conn.execute(select(pi).where(pi.c.inspection_id == iid)).mappings().first()

    def _ensure(self, conn, iid: str, product_name: str | None):
        """검사 행을 찾고, 없으면 product_name 으로 새로 만든다 (NOT NULL 컬럼은 모두 채움)"""
        row = self._row(conn, iid)
        if row is not None:
            return row
        product_name = product_name or self.product_name.get(iid)
        if not product_name:
            raise DBError(f"검사 {iid} 가 없습니다. 먼저 start() 로 검사를 시작하세요")
        now = _now()
        conn.execute(self._t()["product_inspection"].insert().values(
            inspection_id=iid, product_name=product_name, centering_state="UNKNOWN", interlock_state="UNKNOWN",
            dimension_result="PENDING", patchcore_result="PENDING", yolo_status="NOT_STARTED",
            yolo_defect_data=[], image_files=[], created_at=now, updated_at=now))
        return self._row(conn, iid)

    def _update(self, conn, iid: str, **values):
        pi = self._t()["product_inspection"]
        conn.execute(pi.update().where(pi.c.inspection_id == iid).values(updated_at=_now(), **values))

    def _summary(self, conn, iid: str) -> dict:
        r = self._row(conn, iid)
        alarms = self._t()["equipment_safety_alarm"]
        active = conn.execute(select(alarms.c.id).where(alarms.c.inspection_id == iid,
                                                        alarms.c.alarm_status == "ACTIVE")).all()
        return {"inspection_id": iid, "product_name": r["product_name"], "product_serial": r["product_serial"],
                "dimension_result": r["dimension_result"], "patchcore_result": r["patchcore_result"],
                "yolo_status": r["yolo_status"], "final_result": r["final_result"],
                "centering_state": r["centering_state"], "interlock_state": r["interlock_state"],
                "capture_count": len(_json(r["image_files"], [])),
                "defect_count": len(_json(r["yolo_defect_data"], [])), "active_alarms": len(active)}

    # ------------------------------------------------------------------ 단계별 저장
    def start(self, inspection_id: str, product_name: str, product_serial: str | None = None,
              capture_folder: str | None = None, started_at: datetime | None = None) -> dict | None:
        """검사 1회 시작 (또는 기본 정보 수정)"""
        self.product_name[inspection_id] = product_name
        return self._do("start", inspection_id=inspection_id, product_name=product_name,
                        product_serial=product_serial, capture_folder=capture_folder,
                        started_at=(started_at or datetime.now().astimezone()).isoformat())

    def send_dimension(self, inspection_id: str, width: float | None, length: float | None,
                       height: float | None, standards: tuple[float, float, float] | None = None,
                       scan_file_path: str | None = None, centering: str | None = None,
                       interlock: str | None = None) -> dict | None:
        """3D 치수 (mm). standards=(가로, 길이, 높이) 기준값을 같이 준다 (검사 당시 기준으로 보관).
        centering / interlock 은 측정 시점 장비 상태 (안 주면 미확인으로 기록 → 알람)"""
        return self._do("dimension", inspection_id=inspection_id, width=width, length=length, height=height,
                        standards=list(standards) if standards else None, scan_file_path=scan_file_path,
                        centering=centering or "UNKNOWN", interlock=str(interlock) if interlock is not None else "UNKNOWN")

    def send_patchcore(self, inspection_id: str, score: float, threshold: float,
                       model_version: str | None = None) -> dict | None:
        """PatchCore 이상 점수와 그때의 판정 기준"""
        return self._do("patchcore", inspection_id=inspection_id, score=float(score), threshold=float(threshold),
                        model_version=model_version or self.model_version)

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
        return self._do("capture", files=files, inspection_id=inspection_id, capture_number=int(capture_number),
                        defects=list(defects), angle_deg=angle_deg,
                        captured_at=(captured_at or datetime.now().astimezone()).isoformat(),
                        model_version=model_version or self.model_version)

    def complete_yolo(self, inspection_id: str, model_version: str | None = None) -> dict | None:
        """YOLO 분류 완료 (한 바퀴 검사가 끝났을 때)"""
        return self._do("complete", inspection_id=inspection_id, model_version=model_version or self.model_version)

    def check_safety(self, stage: str, centering: str, interlock: str, inspection_id: str | None = None,
                     message: str | None = None) -> dict | None:
        """장비 안전 상태 기록. 이상이면 알람 행 추가. 반환 {"allowed": bool, "alarms": [새 알람...]}
        ※ 장비를 멈출지는 safety_ok() 로 이 PC 에서 바로 판단할 것 (저장을 기다리지 않음)"""
        return self._do("safety", stage=stage, centering=centering, interlock=str(interlock),
                        inspection_id=inspection_id, message=message)

    # ------------------------------------------------------------------ 실제 저장 (op 별)
    def _apply(self, op: str, a: dict, files: dict[str, Path]) -> dict:
        with self.engine.begin() as conn:  # 한 요청 = 한 트랜잭션 (실패하면 전부 취소)
            return getattr(self, f"_op_{op}")(conn, a, files)

    def _op_start(self, conn, a, files):
        iid = a["inspection_id"]
        self._ensure(conn, iid, a["product_name"])
        values = {"product_name": a["product_name"], "created_at": _local(datetime.fromisoformat(a["started_at"]))}
        if a.get("product_serial") is not None:
            values["product_serial"] = a["product_serial"]
        if a.get("capture_folder") is not None:
            values["capture_folder"] = a["capture_folder"]
        self._update(conn, iid, **values)
        return self._summary(conn, iid)

    def _op_dimension(self, conn, a, files):
        iid = a["inspection_id"]
        self._ensure(conn, iid, a.get("product_name"))
        dim = self._t()["product_dimension_inspection"]
        std = a.get("standards") or [None, None, None]
        values = {"width_mm": a["width"], "length_mm": a["length"], "height_mm": a["height"],
                  "standard_width_mm": std[0], "standard_length_mm": std[1], "standard_height_mm": std[2],
                  "scan_file_path": a.get("scan_file_path"), "centering_state": a["centering"],
                  "interlock_state": a["interlock"], "updated_at": _now()}
        if conn.execute(select(dim.c.id).where(dim.c.inspection_id == iid)).first():
            conn.execute(dim.update().where(dim.c.inspection_id == iid).values(**values))
        else:
            conn.execute(dim.insert().values(inspection_id=iid, created_at=_now(), **values))
        d = conn.execute(select(dim).where(dim.c.inspection_id == iid)).mappings().first()  # DB 가 계산한 판정
        self._update(conn, iid, dimension_result=d["dimension_result"], scan_file_path=a.get("scan_file_path"),
                     dimension_data={"tolerance_mm": DIM_TOLERANCE_MM, "recheck_mm": DIM_RECHECK_MM,
                                     **{f"{x}_mm": _num(d[f"{x}_mm"]) for x in AXES},
                                     **{f"standard_{x}_mm": _num(d[f"standard_{x}_mm"]) for x in AXES},
                                     **{f"{x}_result": d[f"{x}_result"] for x in AXES}})
        self._record_safety(conn, iid, "DIMENSION", a["centering"], a["interlock"], "치수 측정 시점 상태")
        return self._summary(conn, iid)

    def _op_patchcore(self, conn, a, files):
        iid = a["inspection_id"]
        self._ensure(conn, iid, a.get("product_name"))
        self._update(conn, iid, patchcore_score=a["score"], patchcore_threshold=a["threshold"],
                     patchcore_model_version=a.get("model_version"),
                     patchcore_result="FAIL" if a["score"] >= a["threshold"] else "PASS")
        return self._summary(conn, iid)

    def _op_capture(self, conn, a, files):
        iid = a["inspection_id"]
        row = self._ensure(conn, iid, a.get("product_name"))
        images = _json(row["image_files"], [])
        if any(f.get("capture_number") == a["capture_number"] for f in images):
            raise DBError(f"사진 번호 {a['capture_number']} 는 이미 저장되어 있습니다")
        at = _local(datetime.fromisoformat(a["captured_at"]))
        ident = f"{iid}_c{a['capture_number']:03d}"
        saved = []
        try:
            orig = self._store(files["original"].read_bytes(), files["original"].suffix.lower() or ".jpg",
                               at, row["product_name"], ident)
            saved.append(orig)
            ann = None
            if "annotated" in files:
                ann = self._store(files["annotated"].read_bytes(), files["annotated"].suffix.lower() or ".jpg",
                                  at, row["product_name"], ident + "_annotated")
                saved.append(ann)
            meta = self._store(json.dumps({"inspection_id": iid, **{k: a[k] for k in ("capture_number", "angle_deg",
                               "captured_at", "model_version", "defects")}}, ensure_ascii=False, indent=2).encode("utf-8"),
                               ".json", at, row["product_name"], ident)
            saved.append(meta)
            images = images + [{"capture_number": a["capture_number"], "original_path": orig,
                                "annotated_path": ann, "metadata_path": meta}]
            defects = _json(row["yolo_defect_data"], []) + [
                {"capture_number": a["capture_number"], "defect_class": d.get("defect_class"),
                 "confidence": round(float(d.get("confidence", 0)), 4), "box": d.get("box"),
                 "angle_deg": a.get("angle_deg"), "defect_code": None} for d in a.get("defects", [])]
            values = {"image_files": images, "yolo_defect_data": defects}
            if a.get("model_version"):
                values["yolo_model_version"] = a["model_version"]
            if row["yolo_status"] == "NOT_STARTED":
                values["yolo_status"] = "IN_PROGRESS"
            self._update(conn, iid, **values)
            return self._summary(conn, iid)
        except Exception:
            for rel in saved:  # DB 저장이 실패하면 방금 복사한 사진도 지운다 (고아 파일 방지)
                (self.storage_dir / rel).unlink(missing_ok=True)
            raise

    def _op_complete(self, conn, a, files):
        iid = a["inspection_id"]
        self._ensure(conn, iid, a.get("product_name"))
        values = {"yolo_status": "COMPLETED"}
        if a.get("model_version"):
            values["yolo_model_version"] = a["model_version"]
        self._update(conn, iid, **values)
        return self._summary(conn, iid)

    def _op_safety(self, conn, a, files):
        iid = a.get("inspection_id")
        if iid:
            self._ensure(conn, iid, a.get("product_name"))
        allowed, alarms = self._record_safety(conn, iid, a["stage"], a["centering"], a["interlock"], a.get("message"))
        return {"allowed": allowed, "alarms": alarms}

    def _record_safety(self, conn, iid, stage, centering, interlock, message=None):
        """상태를 검사 행에 기록하고, 이상이면 조건마다 알람 1행 (backend/app/services/safety.py 와 같은 규칙)"""
        if iid:
            self._update(conn, iid, centering_state=centering, interlock_state=interlock)
        if safety_ok(centering, interlock):
            return True, []
        problems = []
        if centering != "OFF":
            problems.append(("CENTERING", f"센터링 {_KO_CENTERING.get(centering, centering)}"))
        if interlock != "0":
            problems.append(("INTERLOCK", f"인터락 {_KO_INTERLOCK.get(interlock, interlock)}"))
        al = self._t()["equipment_safety_alarm"]
        active = set()
        if iid:
            active = {tuple(r) for r in conn.execute(select(
                al.c.alarm_type, al.c.inspection_stage, al.c.centering_state, al.c.interlock_state).where(
                al.c.inspection_id == iid, al.c.alarm_status == "ACTIVE")).all()}
        created = []
        for kind, what in problems:
            if (kind, stage, centering, interlock) in active:
                continue
            text = f"[{_KO_STAGE.get(stage, stage)}] {what} → 검사 중단·보류" + (f" ({message})" if message else "")
            values = {"inspection_id": iid, "alarm_type": kind, "alarm_status": "ACTIVE",
                      "centering_state": centering, "interlock_state": interlock, "inspection_stage": stage,
                      "alarm_message": text, "occurred_at": _now()}
            conn.execute(al.insert().values(**values))
            created.append({**values, "occurred_at": values["occurred_at"].isoformat()})
        return False, created

    def _store(self, data: bytes, ext: str, at: datetime, product: str, ident: str) -> str:
        """사진·정보 파일을 MES 저장 폴더에 규칙대로 저장하고 상대경로를 돌려준다 (같은 이름이면 _r2, _r3 ...)"""
        day = f"{at:%Y-%m-%d}"
        folder = self.storage_dir / day
        folder.mkdir(parents=True, exist_ok=True)
        retry = 1
        while True:
            suffix = "" if retry == 1 else f"_r{retry}"
            name = f"{day}-{product}-{at:%H%M%S}-YOLO-{_SAFE.sub('_', ident)}{suffix}{ext}"
            try:
                with open(folder / name, "xb") as f:  # 'x': 이미 있으면 덮어쓰지 않고 실패
                    f.write(data)
                return f"{day}/{name}"
            except FileExistsError:
                retry += 1

    # ------------------------------------------------------------------ 큐 (DB 연결 실패 대비)
    def _do(self, op: str, files: dict[str, Path] | None = None, **args) -> dict | None:
        """밀린 큐 먼저 → 이번 요청 저장 (연결 실패 시 큐)"""
        iid = args.get("inspection_id")
        if iid and "product_name" not in args:
            args["product_name"] = self.product_name.get(iid)
        self.flush_queue()
        if self.pending():  # 못 저장한 게 남아 있으면 순서를 지키려고 새 요청도 뒤에 줄 세움
            self._enqueue(op, args, files or {})
            return None
        try:
            return self._apply(op, args, files or {})
        except (OperationalError, DBAPIError) as e:
            if isinstance(e, DBAPIError) and not e.connection_invalidated and not isinstance(e, OperationalError):
                raise DBError(str(e.orig)) from e  # 데이터 문제 (제약 위반 등) → 다시 해도 같음
            log.warning("DB 저장 실패 → 큐에 저장: %s", e)
            self._enqueue(op, args, files or {})
            return None

    def _enqueue(self, op: str, args: dict, files: dict[str, Path]):
        job = self.queue_dir / f"{time.time_ns()}_{uuid.uuid4().hex[:6]}"  # 이름순 = 시간순
        job.mkdir()
        names = {}
        for field, p in files.items():
            names[field] = f"{field}{p.suffix}"
            shutil.copy2(p, job / names[field])
        (job / "request.json").write_text(json.dumps({"op": op, "args": args, "files": names},
                                                     ensure_ascii=False), encoding="utf-8")

    def pending(self) -> int:
        """아직 저장 못 한 요청 개수"""
        return sum(1 for p in self.queue_dir.iterdir() if p.is_dir())

    def flush_queue(self) -> int:
        """큐에 쌓인 요청을 오래된 순서로 다시 저장. 저장한 개수 반환 (DB 가 아직 안 되면 멈춤)"""
        sent = 0
        for job in sorted(p for p in self.queue_dir.iterdir() if p.is_dir()):
            req_file = job / "request.json"
            if not req_file.exists():
                shutil.rmtree(job, ignore_errors=True)
                continue
            req = json.loads(req_file.read_text(encoding="utf-8"))
            files = {k: job / v for k, v in req.get("files", {}).items()}
            try:
                self._apply(req["op"], req["args"], files)
            except OperationalError:
                break  # DB 가 아직 안 됨 → 다음 기회에
            except (DBError, DBAPIError) as e:
                log.error("큐 항목 저장 거부 → failed 폴더로 이동: %s", e)
                failed = self.queue_dir.parent / (self.queue_dir.name + "_failed")
                failed.mkdir(exist_ok=True)
                shutil.move(str(job), failed / job.name)
                continue
            shutil.rmtree(job, ignore_errors=True)
            sent += 1
        return sent
