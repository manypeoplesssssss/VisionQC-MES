# bridge_3d — 3D 검사 결과를 DB 에 저장하고 비전 검사로 넘기는 연결 프로그램

`station_3d`(3D 스캔 코드)는 **건드리지 않습니다.** 이 폴더의 스크립트는 3D 코드가 만든
`station_3d/scans/<세션>/measurement.json` 과 `station_3d/config.py` 의 기준값을 **읽기만** 합니다.

## 순서 (3D 환경 가상환경에서)
```powershell
cd inspection\station_3d
.venv\Scripts\python.exe turntable_scan.py            # 스캔 → scans/<날짜_시각>/
.venv\Scripts\python.exe merge_turntable_scans.py     # 병합 → merged_model.ply
.venv\Scripts\python.exe measure_object.py            # 측정 → measurement.json
.venv\Scripts\python.exe ..\bridge_3d\save_3d_to_db.py --serial RC-0001 --centering OFF --interlock 0
#                                                         ↑ DB 저장 + ../handoff/latest.json 기록
```
`--centering` / `--interlock` 은 측정할 때의 장비 안전 상태입니다 (센서가 아직 없어서 작업자가 확인한 값).
안 주면 미확인(UNKNOWN)으로 기록되어 DB 에 알람이 남고, 비전 검사가 이어받지 않습니다.
검사 허용: **센터링 OFF(정위치) + 인터락 0(정상)**.
`station_vision/inspection_app.py` 의 **[① 3D 검사]** 버튼이 위 순서를 대신 실행하고, 치수가 합격이면 [② YOLO 검사]가 켜져
handoff 의 검사번호를 이어받아 같은 DB 검사 행에 YOLO 결과가 붙습니다. 치수 불합격·재검이면 YOLO 검사를 시작하지 않습니다.
(이 순서를 손으로 직접 실행해도 됩니다.)

## DB 에 저장하는 것
- 검사번호: 측정 시각 기준 `YYYYMMDD_inspection_HHMMSS_3d`
- 치수: 가로 / 길이(= 3D 코드의 depth, 전폭) / 높이 실측 + 3D `config.py` 의 `NOMINAL_MM` (검사 당시 기준으로 MES 에 저장)
- 판정: DB 생성 컬럼이 축별 한계로 자동 계산 — 3D `config.py` 의 `RECHECK_MM`(정상 한계) / `TOLERANCE_MM`(불량 한계)와 같은 값
  - 3D 쪽 한계를 바꾸면 MES 쪽(`backend/app/models.py`, `backend/sql/schema.sql`)도 같이 바꿔야 합니다
  - 길이(3D 코드의 depth)는 2026-10-07 에 정상 ±3.5 / 불량 ±5.5 로 바꿨습니다. 3D 코드 `config.py` 는 그대로 두고, 검사 프로그램이 `station_vision/config.py` 의 `DIM_LIMITS_3D` 로 실행할 때만 덮어씁니다
- DB 주소·제품 모델명: `--db --product`, 또는 환경변수 `VISIONQC_DB_URL`, 없으면 `backend/.env` 의 `DATABASE_URL` (같은 PC)
- DB 에 연결이 안 되면 `bridge_3d/db_queue/` 에 쌓였다가 다음 저장 때 다시 저장합니다

## 3D 환경 패키지
3D 코드가 쓰는 패키지 목록은 `requirements-3d.txt` (3D 가상환경에 설치). DB 저장에는 `sqlalchemy`, `pymysql` 이 필요합니다.
