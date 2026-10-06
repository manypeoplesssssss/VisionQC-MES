"""
send_3d_to_mes.py — 3D 측정 결과(measurement.json)를 MES 로 보내고, 비전 검사로 검사번호를 넘긴다

station_3d 의 코드·파일은 건드리지 않는다. 그쪽 결과물(scans/<세션>/measurement.json)과
config.py 의 기준값(NOMINAL_MM, SCAN_ROOT)을 읽기만 한다.

순서 (3D 환경에서, station_3d 폴더의 원래 순서대로 측정까지 한 뒤):
    python measure_object.py                                   # (station_3d) → <세션>/measurement.json
    python ..\\bridge_3d\\send_3d_to_mes.py --serial RC-0001    # ← 이 파일: MES 전송 + ../handoff/latest.json 기록
그다음 환경을 바꿔 station_vision/inspection_app.py 를 켜면 handoff 의 검사번호를 이어받아
같은 검사에 PatchCore·YOLO 결과를 붙인다.

실행 (어느 폴더에서 실행해도 된다):
    python send_3d_to_mes.py                               # station_3d 의 최근 세션
    python send_3d_to_mes.py <세션 폴더> --serial RC-0001
    python send_3d_to_mes.py --url http://192.168.0.10:8000 --key <INGEST_API_KEY>

MES 에 보내는 것
    - 검사 시작: 검사번호 = 측정시각 기준 "YYYYMMDD_inspection_HHMMSS_3d", 제품 모델명, 제품번호, 세션 폴더
    - 치수: 가로 / 길이(= 3D 코드의 depth, 전폭) / 높이 실측값 + station_3d/config.py 의 기준값(NOMINAL_MM)
      합격·재검·불합격 판정은 MES 가 축별 한계로 다시 계산한다 (3D config 의 TOLERANCE_MM / RECHECK_MM 와 같은 값)
MES 설정은 명령줄(--url --key --product) 또는 환경변수 MES_URL, MES_API_KEY, MES_PRODUCT 로 준다.
장비 안전 상태(측정 시점 센터링·인터락)는 --centering OFF --interlock 0 처럼 준다. 안 주면 미확인(UNKNOWN)으로
기록되어 MES 에 알람이 남고, 비전 검사가 이 검사번호를 이어받지 않는다 (검사 허용: 센터링 OFF + 인터락 0).
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATION_3D = ROOT.parent / "station_3d"
sys.path.insert(0, str(ROOT.parent / "common"))  # 공용 mes_client.py
sys.path.insert(1, str(STATION_3D))              # 3D 설정(config.py)을 읽기만 함
sys.dont_write_bytecode = True                   # station_3d 폴더에 __pycache__ 를 만들지 않게
import config  # noqa: E402  (station_3d/config.py)
from mes_client import MESClient, safety_ok  # noqa: E402

HANDOFF = ROOT.parent / "handoff" / "latest.json"
SCAN_ROOT = STATION_3D / config.SCAN_ROOT       # 3D 프로그램은 station_3d 폴더 기준으로 scans/ 를 만든다
# 3D 코드 축 이름 → MES 축 이름
AXIS_MAP = {"width": "width", "depth": "length", "height": "height"}


def latest_session():
    """measurement.json 이 있는 가장 최근 세션 (세션 이름이 날짜_시각이라 이름순 = 시간순)"""
    sessions = sorted(d for d in glob.glob(os.path.join(SCAN_ROOT, "*"))
                      if os.path.isfile(os.path.join(d, "measurement.json")))
    if not sessions:
        raise RuntimeError(f"'{SCAN_ROOT}' 에 measurement.json 이 있는 세션이 없습니다. "
                           "measure_object.py 를 먼저 실행하세요.")
    return sessions[-1]


def write_handoff(info: dict):
    """비전 검사 프로그램이 이어받을 검사번호를 기록 (임시 파일에 쓴 뒤 교체 → 반쯤 쓴 파일을 읽지 않게)"""
    HANDOFF.parent.mkdir(parents=True, exist_ok=True)
    tmp = HANDOFF.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HANDOFF)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", default=None, help="세션 폴더 (없으면 최근 세션)")
    ap.add_argument("--serial", default=None, help="제품번호 (라벨 등, 선택)")
    ap.add_argument("--product", default=os.environ.get("MES_PRODUCT", "redcar"), help="제품 모델명")
    ap.add_argument("--url", default=os.environ.get("MES_URL", "http://127.0.0.1:8000"), help="MES 서버 주소")
    ap.add_argument("--centering", default="UNKNOWN", choices=["OFF", "ON", "UNKNOWN"],
                    help="측정 시점 센터링 상태 (OFF 정위치 / ON 위치 이상 / UNKNOWN 미확인)")
    ap.add_argument("--interlock", default="UNKNOWN", choices=["0", "1", "UNKNOWN"],
                    help="측정 시점 인터락 상태 (0 정상 / 1 비정상 / UNKNOWN 미확인)")
    ap.add_argument("--key", default=os.environ.get("MES_API_KEY", "change-this-ingest-key"), help="MES API 키")
    args = ap.parse_args()

    session = args.session or latest_session()
    m = json.loads(Path(session, "measurement.json").read_text(encoding="utf-8"))
    ts = dt.datetime.fromisoformat(m["timestamp"]).astimezone()
    iid = f"{ts:%Y%m%d}_inspection_{ts:%H%M%S}_3d"
    dims = {AXIS_MAP[k]: v for k, v in m["dimensions"].items() if k in AXIS_MAP}
    nominal = getattr(config, "NOMINAL_MM", None)
    standards = tuple(nominal[k] for k in ("width", "depth", "height")) if nominal else None

    mes = MESClient(args.url, args.key, queue_dir=ROOT / "mes_queue")
    mes.start(iid, args.product, product_serial=args.serial,
              capture_folder=os.path.abspath(session), started_at=ts)
    res = mes.send_dimension(iid, dims.get("width"), dims.get("length"), dims.get("height"),
                             standards=standards,
                             scan_file_path=os.path.abspath(os.path.join(session, "merged_model.ply")),
                             centering=args.centering, interlock=args.interlock)
    safe = safety_ok(args.centering, args.interlock)  # 센터링 OFF + 인터락 0 이 아니면 MES 가 알람을 남김

    # MES 응답이 있으면 MES 판정, 서버가 꺼져 대기열에 쌓였으면 3D 코드 자체 판정을 같이 남긴다
    local = (m.get("judgement") or {}).get("result")  # OK / RECHECK / NG
    dimension_result = res["dimension_result"] if res else {"OK": "PASS", "NG": "FAIL"}.get(local, local)
    write_handoff({"inspection_id": iid, "product_name": args.product, "product_serial": args.serial,
                   "dimension_result": dimension_result, "safety_ok": safe,
                   "centering_state": args.centering, "interlock_state": args.interlock,
                   "session": os.path.abspath(session),
                   "measured_at": ts.isoformat(), "consumed": False})

    ko = {"PASS": "합격", "RECHECK": "재검 (다시 스캔)", "FAIL": "불합격", "PENDING": "대기"}
    print(f"검사번호 {iid}")
    print(f"  치수: 가로 {dims.get('width')} / 길이 {dims.get('length')} / 높이 {dims.get('height')} mm")
    print(f"  판정: {ko.get(dimension_result, dimension_result)}"
          + ("" if res else f"  (MES 연결 안 됨 → 대기열 {mes.pending()}건, 3D 자체 판정 표시)"))
    print(f"  비전 검사가 이어받을 검사번호를 {HANDOFF} 에 기록했습니다.")
    if not safe:
        print(f"  장비 안전 이상(센터링 {args.centering} / 인터락 {args.interlock}): MES 에 알람을 남겼고, "
              "비전 검사로 이어받지 않습니다. 상태를 확인하고 다시 스캔하세요.")
    elif dimension_result == "FAIL":
        print("  치수 불합격 제품입니다. 비전 검사(PatchCore·YOLO)로 넘기지 않아도 됩니다.")
    elif dimension_result == "RECHECK":
        print("  재검입니다. 다시 스캔해서 측정하세요 (새 검사번호로 다시 보내면 됩니다).")


if __name__ == "__main__":
    main()
