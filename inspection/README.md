# 검사 PC 프로그램 (inspection/)

검사 결과는 **DB(MySQL)에 직접 저장**하고 MES 서버·화면은 DB 에서 읽습니다 (검사 PC → DB → MES). DB 주소·사진 폴더 설정은 [docs/SETUP.md 7-3](../docs/SETUP.md#7-3-db-주소와-사진-폴더).

검사 라인 PC 에서 돌리는 프로그램 모음입니다. MES 서버(`backend/`)와 화면(`frontend/`)은 이 폴더 없이도 돌아가고,
검사 PC 에는 이 폴더만 있으면 됩니다.

```
inspection/
├─ common/           공용 모듈. db_client.py (DB 직접 저장·재저장 큐), mes_client.py (예전 MES API 방식), 테스트
├─ station_3d/       3D 스캔 치수 검사 코드 (3D 환경 가상환경) — 3D 담당 코드, 다른 작업에서 수정하지 않음
├─ bridge_3d/        3D 측정 결과(measurement.json)를 읽어 DB 저장 + handoff 기록 (save_3d_to_db.py)
├─ station_vision/   PatchCore → YOLO 검사 프로그램 (비전 환경 가상환경)
│  ├─ inspection_app.py     버튼 화면 (턴테이블 + PatchCore → YOLO, DB 저장)
│  ├─ patchcore_infer.py    PatchCore 모델(v3)로 사진 1장 이상 점수·히트맵
│  ├─ yolo_live.py          키보드로 조작하는 원래 검사 프로그램
│  ├─ turntable.py · turntable/turntable.ino   아두이노 턴테이블
│  ├─ config.py · inspection_roi.json · best.pt
│  └─ captures/             촬영 사진 (Git 에 올리지 않음)
├─ handoff/          3D → 비전으로 검사번호를 넘기는 폴더 (Git 에 올리지 않음)
└─ visionPatchCore/   PatchCore 학습 코드와 모델 (models/ 는 Git 에 올리지 않음)
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

**장비 안전:** 검사 허용은 **센터링 OFF(정위치) AND 인터락 0(정상)** 일 때만. ON / 1 / UNKNOWN(미확인·센서 응답 끊김)이면 검사 프로그램이 시작하지 않거나 장비를 멈추고 검사를 보류하며, MES 에 알람을 남김. 알람 해제만으로 자동 재시작하지 않음. 센서 연결 전이라 버튼 화면의 [장비 안전 상태]에서 작업자가 고릅니다 (기본 미확인 → 시작 불가). 센서를 붙이면 `inspection_app.py` 의 `App.safety_state()` 만 센서 값을 읽게 바꾸면 됩니다.
3D 쪽 실행 순서와 연결 방법은 [bridge_3d/README.md](bridge_3d/README.md) (station_3d 코드는 그대로 두고 bridge_3d 가 결과만 읽음). PatchCore 는 `station_vision/patchcore_infer.py` 가 `visionPatchCore/patchcore_export/models/v3/model.ckpt` 를 읽어서 판정합니다 (학습 코드 폴더는 건드리지 않음).

## 가상환경 만들기 (폴더마다 따로)
```powershell
cd inspection\station_vision
python -m venv .venv
.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
torch 는 CPU 용을 먼저 깝니다 (NVIDIA 그래픽이 없으면 CUDA 판은 쓸모없고 큼).
PatchCore 모델 `visionPatchCore/patchcore_export/models/v3/model.ckpt` 는 100MB 가 넘어 git 에 없으니 따로 복사해 둡니다.
`station_3d` 도 같은 방법으로 가상환경을 만들고, 패키지는 `bridge_3d/requirements-3d.txt` 로 설치합니다.

## 실행
```powershell
cd inspection\station_vision
.venv\Scripts\python.exe inspection_app.py          # 실제 카메라 + 턴테이블
.venv\Scripts\python.exe inspection_app.py --sim    # 장비 없이 captures 사진으로 시험
```
[▶ 검사 시작] 한 번에 **PatchCore** (45도씩 8장, 가장 높은 이상 점수로 판정) → 불합격이면 **YOLO** 한 바퀴.
PatchCore 합격이면 YOLO 없이 끝납니다 (최종 정상). `PatchCore 먼저` 체크를 끄면 YOLO 만 합니다.
PatchCore 사진은 검사 폴더의 `patchcore/` 에 `_pcNN.jpg`(원본), `_pcNN_heatmap.jpg`, `_pcNN.json`(각도·점수·기준) 으로 남습니다.
장수·자르는 범위·모델 파일은 `station_vision/config.py` 의 `PATCHCORE_VIEWS`, `PATCHCORE_CROP`, `PATCHCORE_MODEL`.

DB 주소·사진 폴더·제품 모델명은 화면 오른쪽에서 바꾸거나 `station_vision/config.py` 에
`DB_URL`, `STORAGE_DIR`, `PRODUCT` 를 적습니다.

## 테스트
```powershell
cd inspection\common
..\..\backend\.venv\Scripts\python.exe -m pytest -q     # db_client (임시 DB → MES API 로 확인), mes_client
```
