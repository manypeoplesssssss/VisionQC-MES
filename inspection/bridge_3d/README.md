# bridge_3d — 3D 검사 결과를 MES·비전 검사로 넘기는 연결 프로그램

`station_3d`(3D 스캔 코드)는 **건드리지 않습니다.** 이 폴더의 스크립트는 3D 코드가 만든
`station_3d/scans/<세션>/measurement.json` 과 `station_3d/config.py` 의 기준값을 **읽기만** 합니다.

## 순서 (3D 환경 가상환경에서)
```powershell
cd inspection\station_3d
.venv\Scripts\python.exe turntable_scan.py            # 스캔 → scans/<날짜_시각>/
.venv\Scripts\python.exe merge_turntable_scans.py     # 병합 → merged_model.ply
.venv\Scripts\python.exe measure_object.py            # 측정 → measurement.json
.venv\Scripts\python.exe ..\bridge_3d\send_3d_to_mes.py --serial RC-0001   # MES 전송 + ../handoff/latest.json 기록
```
그다음 환경을 바꿔 `station_vision` 의 `inspection_app.py` 에서 [검사 시작]을 누르면
handoff 의 검사번호를 이어받아 같은 MES 검사에 PatchCore·YOLO 결과가 붙습니다.
치수 불합격이면 비전 검사 프로그램이 검사를 시작하지 않습니다.

## MES 로 보내는 것
- 검사번호: 측정 시각 기준 `YYYYMMDD_inspection_HHMMSS_3d`
- 치수: 가로 / 길이(= 3D 코드의 depth, 전폭) / 높이 실측 + 3D `config.py` 의 `NOMINAL_MM` (검사 당시 기준으로 MES 에 저장)
- 판정: MES 가 축별 한계로 다시 계산 — 3D `config.py` 의 `RECHECK_MM`(정상 한계) / `TOLERANCE_MM`(불량 한계)와 같은 값
  - 3D 쪽 한계를 바꾸면 MES 쪽(`backend/app/models.py`, `backend/sql/schema.sql`)도 같이 바꿔야 합니다
- MES 서버 주소·API 키·제품 모델명: `--url --key --product` 또는 환경변수 `MES_URL`, `MES_API_KEY`, `MES_PRODUCT`
- 서버가 꺼져 있으면 `bridge_3d/mes_queue/` 에 쌓였다가 다음 전송 때 다시 보냅니다

## 3D 환경 패키지
3D 코드가 쓰는 패키지 목록은 `requirements-3d.txt` (3D 가상환경에 설치). MES 전송에는 `requests` 가 필요합니다.
