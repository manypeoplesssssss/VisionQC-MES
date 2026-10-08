# 검사 PC 프로그램 (inspection/)

검사 결과는 **DB(MySQL)에 직접 저장**하고 MES 서버·화면은 DB 에서 읽습니다 (검사 PC → DB → MES). DB 주소·사진 폴더 설정은 [docs/SETUP.md 7-3](../docs/SETUP.md#7-3-db-주소와-사진-폴더).

검사 라인 PC 에서 돌리는 프로그램 모음입니다. MES 서버(`backend/`)와 화면(`frontend/`)은 이 폴더 없이도 돌아가고,
검사 PC 에는 이 폴더만 있으면 됩니다.

```
inspection/
├─ common/           공용 모듈. db_client.py (DB 직접 저장·재저장 큐), mes_client.py (예전 MES API 방식), 테스트
├─ station_3d/       3D 스캔 치수 검사 코드 (3D 환경 가상환경) — 3D 담당 코드, 다른 작업에서 수정하지 않음
├─ bridge_3d/        3D 측정 결과(measurement.json)를 읽어 DB 저장 + handoff 기록 (save_3d_to_db.py)
├─ station_vision/   3D 검사 + YOLO 검사를 한 화면에서 (한 가상환경)
│  ├─ inspection_app.py     버튼 화면 ([3D 검사] → 치수 합격이면 [YOLO 검사], DB 저장)
│  ├─ yolo_live.py          키보드로 조작하는 원래 검사 프로그램
│  ├─ turntable.py · turntable/turntable.ino   아두이노 턴테이블
│  ├─ config.py · inspection_roi.json · best.pt
│  └─ captures/             촬영 사진 (Git 에 올리지 않음)
└─ handoff/          3D → 비전으로 검사번호를 넘기는 폴더 (Git 에 올리지 않음)
```

## 검사 흐름
3D 와 YOLO 는 한 가상환경(`station_vision\.venv`)에서 한 화면으로 돌립니다. PatchCore 도 같은 화면에서 돌립니다 (3D → PatchCore → YOLO).
[3D 검사] 버튼이 `station_3d` 스크립트를 그대로 실행하고(코드는 수정하지 않음), MES 에서는 같은 검사번호(`inspection_id`) 한 줄로 이어 붙입니다.

```
station_3d     스캔 → 병합 → 측정 (measurement.json)
bridge_3d      검사 시작(start) + 치수(send_dimension) → handoff/ 에 검사번호 기록
   (환경 변경)
station_vision handoff/ 의 검사번호를 읽어 → 치수 합격이면 PatchCore(send_patchcore) → 불합격이면 YOLO 사진 → 완료
```
최종 결과(정상/치수 불합격/공정 불량 …)는 MES 서버가 자동으로 계산합니다.

**장비 안전:** 검사 허용은 **센터링 OFF(정위치) AND 인터락 0(정상)** 일 때만. ON / 1 / UNKNOWN(미확인·센서 응답 끊김)이면 검사 프로그램이 시작하지 않거나 장비를 멈추고 검사를 보류하며, MES 에 알람을 남김. 알람 해제만으로 자동 재시작하지 않음. 센서가 없는 펌웨어(비전용)면 버튼 화면의 [장비 안전 상태]에서 작업자가 고릅니다 (기본 미확인 → 시작 불가). 센서용 펌웨어(`station_vision/turntable/turntable_safety`)를 올리면 센터링(레이저 놓임 검사)·인터락(초음파)이 실제 센서 값으로 들어오고, 인터락이 걸리면 즉시 멈췄다가 [인터락 리셋] → [이어서 진행]으로 멈춘 자리부터 이어갑니다 (`Engine._safety_now`, `_hold_interlock`. 사용법은 `docs/RUN_AFTER_REBOOT.md` 의 "센서 인터락").
3D 쪽 실행 순서와 연결 방법은 [bridge_3d/README.md](bridge_3d/README.md) (station_3d 코드는 그대로 두고 bridge_3d 가 결과만 읽음). PatchCore 는 `station_vision/patchcore_infer.py` 가 `visionPatchCore/patchcore_export/models/v3/model.ckpt` 를 읽어서 판정합니다 (학습 코드 폴더는 건드리지 않음, 모델 파일은 git 에 없음).

## 가상환경 만들기 (폴더마다 따로)
```powershell
cd inspection\station_vision
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
이 가상환경 하나에 YOLO 와 3D(`pyrealsense2`, `open3d`) 패키지가 모두 들어 있습니다. Windows **스마트 앱 컨트롤**이 켜져 있으면 `open3d 0.20.0` 이 "애플리케이션 제어 정책" 오류로 막혀서 `0.19.0` 으로 고정했습니다 (해결은 [RUN_AFTER_REBOOT.md](../docs/RUN_AFTER_REBOOT.md) 3장). 3D 환경을 따로 두려면 `station_vision/config.py` 의 `PYTHON_3D` 에 그 파이썬을 적습니다.

## 실행
```powershell
cd inspection\station_vision
.venv\Scripts\python.exe inspection_app.py          # 실제 카메라 + 턴테이블
.venv\Scripts\python.exe inspection_app.py --sim    # 장비 없이 시험 (captures 사진, 3D 는 가짜 측정값)
.venv\Scripts\python.exe inspection_app.py --no-gate  # 3D 없이 YOLO 만 시험
```
화면 순서: **[① 3D 검사]** → 치수 합격이면 **[② 검사 시작]** 이 켜집니다 (불합격·재검이면 켜지지 않음).
[②] 는 **PatchCore** (기본 30도씩 12장, 가장 높은 이상 점수로 판정) 를 먼저 하고, 합격이면 거기서 끝(정상), 불합격이면 이어서 **YOLO** 한 바퀴를 합니다. `PatchCore 먼저` 체크를 끄면 YOLO 만 합니다.
PatchCore 사진은 검사 폴더의 `patchcore/` 에 `_pcNN.jpg`(원본), `_pcNN_roi.png`(모델 입력), `_pcNN_heatmap.jpg`(위쪽에 점수·기준·합불 표시), `_pcNN.json`(각도·점수·기준·shape) 으로 남습니다.
검사 영역은 학습 때 쓴 **고정 ROI**(`config.py` 의 `ROI_X`·`ROI_Y`, 600×320 픽셀)이고 카메라는 1920×1080 이어야 합니다 (`station_vision/PREPROCESSING.md`).
`--sim` 은 1920×1080 원본 사진이 `captures/` 안에 있어야 합니다 (작은 사진을 확대하지 않음).
DB 주소·사진 폴더·제품 모델명은 화면 오른쪽에서 바꾸거나 `station_vision/config.py` 에 `DB_URL`, `STORAGE_DIR`, `PRODUCT` 를 적습니다.

## 테스트
```powershell
cd inspection\common
..\..\backend\.venv\Scripts\python.exe -m pytest -q     # db_client (임시 DB → MES API 로 확인), mes_client
```
