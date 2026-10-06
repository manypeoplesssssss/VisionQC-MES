# 검사 PC 프로그램 (inspection/)

검사 라인 PC 에서 돌리는 프로그램 모음입니다. MES 서버(`backend/`)와 화면(`frontend/`)은 이 폴더 없이도 돌아가고,
검사 PC 에는 이 폴더만 있으면 됩니다.

```
inspection/
├─ common/           공용 모듈. mes_client.py (MES 전송·재전송 큐), 예시, 테스트
├─ station_3d/       3D 스캔 치수 검사 코드 (3D 환경 가상환경) — 3D 담당 코드, 다른 작업에서 수정하지 않음
├─ bridge_3d/        3D 측정 결과(measurement.json)를 읽어 MES 전송 + handoff 기록 (send_3d_to_mes.py)
├─ station_vision/   PatchCore → YOLO 검사 프로그램 (비전 환경 가상환경)
│  ├─ inspection_app.py     버튼 화면 (턴테이블 + YOLO, MES 자동 전송)
│  ├─ yolo_live.py          키보드로 조작하는 원래 검사 프로그램
│  ├─ turntable.py · turntable/turntable.ino   아두이노 턴테이블
│  ├─ config.py · inspection_roi.json · best.pt
│  └─ captures/             촬영 사진 (Git 에 올리지 않음)
└─ handoff/          3D → 비전으로 검사번호를 넘기는 폴더 (Git 에 올리지 않음)
```

## 왜 프로그램이 두 개인가
3D 모델링과 PatchCore·YOLO 는 같은 PC 에서 **환경을 바꿔 가며** 돌립니다 (한 가상환경에 같이 못 넣음).
그래서 프로그램과 가상환경을 둘로 나누고, MES 에서는 같은 검사번호(`inspection_id`) 한 줄로 이어 붙입니다.

```
station_3d     스캔 → 병합 → 측정 (measurement.json)
bridge_3d      검사 시작(start) + 치수(send_dimension) → handoff/ 에 검사번호 기록
   (환경 변경)
station_vision handoff/ 의 검사번호를 읽어 → PatchCore(send_patchcore) → 불합격이면 YOLO 사진 → 완료
```
최종 결과(정상/치수 불합격/공정 불량 …)는 MES 서버가 자동으로 계산합니다.
3D 쪽 실행 순서와 연결 방법은 [bridge_3d/README.md](bridge_3d/README.md) (station_3d 코드는 그대로 두고 bridge_3d 가 결과만 읽음). PatchCore 는 아직 연결 전이라 지금은 YOLO 결과만 붙습니다.

## 가상환경 만들기 (폴더마다 따로)
```powershell
cd inspection\station_vision
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
`station_3d` 도 같은 방법으로 가상환경을 만들고, 패키지는 `bridge_3d/requirements-3d.txt` 로 설치합니다.

## 실행
```powershell
cd inspection\station_vision
.venv\Scripts\python.exe inspection_app.py          # 실제 카메라 + 턴테이블
.venv\Scripts\python.exe inspection_app.py --sim    # 장비 없이 captures 사진으로 시험
```
MES 서버 주소·API 키·제품 모델명은 화면 오른쪽에서 바꾸거나 `station_vision/config.py` 에
`MES_URL`, `MES_API_KEY`, `MES_PRODUCT` 를 적습니다.

## 테스트
```powershell
cd inspection\common
..\..\backend\.venv\Scripts\python.exe -m pytest -q     # mes_client (가짜 서버, MES 불필요)
```
