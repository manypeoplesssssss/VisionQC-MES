# 검사 시작 전 준비와 실행 순서 (터미널)

PC 를 켠 뒤 PowerShell 로 전체를 띄우는 순서입니다.
처음 설치는 [SETUP.md](SETUP.md), 다른 PC 접속은 [DB_REMOTE_ACCESS.md](DB_REMOTE_ACCESS.md).

## 한눈에 보기

| 순서 | 무엇 | 어디서 | 꼭 필요? |
|---|---|---|---|
| 0 | MySQL | 자동 (Windows 서비스 `MySQL84`) | 필요 (결과 저장) |
| 1 | MES 서버 (백엔드, 8000) | PowerShell 창 1 | 결과를 MES 화면으로 볼 때 |
| 2 | MES 화면 (프론트엔드, 5173) | PowerShell 창 2 | 결과를 MES 화면으로 볼 때 |
| 3 | **검사 프로그램** (3D + PatchCore + YOLO 한 화면) | PowerShell 창 3 | 필요 |

검사만 하고 결과는 나중에 보려면 **0번(MySQL)과 3번(검사 프로그램)만** 있으면 됩니다. 1, 2번 없이도 결과는 DB 에 저장되고, MES 화면은 1, 2번을 켠 뒤에 보면 됩니다.
창마다 켜 둔 채로 두고, 끌 때는 그 창에서 `Ctrl + C` (검사 프로그램은 창을 닫으면 됨).

## 시작 전 체크리스트 (검사 프로그램을 켜기 전에)

- [ ] **Arduino IDE 의 시리얼 모니터를 닫기** (또는 IDE 종료). 열려 있으면 `could not open port 'COM3'` 오류가 납니다
- [ ] 아두이노(턴테이블)와 **인텔 카메라 2대 USB 연결**. 카메라는 허브 말고 PC 본체 USB 3 포트에 직접
- [ ] 보드에 올라간 펌웨어 확인: 지금은 **비전용 펌웨어**(`station_vision\turntable\turntable.ino`)가 올라가 있음 (아래 "아두이노 펌웨어" 참고)
- [ ] PatchCore 모델 파일 `inspection\visionPatchCore\patchcore_export\models\v3\model.ckpt` 가 있는지 (git 에 없으니 PC 마다 따로 복사)
- [ ] **아이폰(YOLO) 카메라**: 3D 검사가 끝난 뒤에 켜도 됩니다 (DroidCam 등). 카메라 번호는 `config.py` 의 `CAMERA_INDEX`
- [ ] 턴테이블 위 **받침과 조명**이 학습 때와 같은지 (PatchCore 점수에 영향)
- [ ] 물체를 올리기 전에 **턴테이블을 비워 두기** (3D 배경 촬영용)

## 0. MySQL 확인

PC 가 켜지면 자동으로 실행됩니다. 확인만:
```powershell
Get-Service MySQL84
```
`Running` 이면 OK. `Stopped` 면 **관리자 권한** PowerShell 에서 `Start-Service MySQL84`.

## 1. MES 서버 (창 1)

```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
`Uvicorn running on http://127.0.0.1:8000` 이 나오면 성공.
DB 주소는 `backend\.env` 의 `DATABASE_URL` (MySQL `visionqc`) 을 자동으로 씁니다.
확인: 브라우저에서 http://localhost:8000/api/health → `{"status":"ok","db":"ok"}`

## 2. MES 화면 (창 2)

```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\frontend
npm run dev -- --host
```
- 이 PC: http://localhost:5173
- 같은 Wi-Fi 의 다른 PC: `Network:` 줄에 나온 주소 (예: `http://<이 PC IP>:5173`)
- 로그인: `admin` / `admin1234`

`--host` 를 빼면 이 PC 에서만 열립니다.

## 3. 검사 프로그램 (창 3)

3D·PatchCore·YOLO 는 같은 가상환경(`inspection\station_vision\.venv`)에서 한 화면으로 돌립니다.
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe inspection_app.py
```
처음 켤 때 YOLO 와 PatchCore 모델을 불러오느라 **30초~1분** 걸립니다 (기록란에 "준비 완료"가 뜰 때까지 기다림).

### 검사 순서

1. 오른쪽 **[DB 저장]** 칸의 DB 주소가 `mysql+pymysql://mes_user:...@localhost:3306/visionqc...` 인지 확인하고, 제품 번호가 있으면 입력
2. **[장비 안전 상태]** 를 센터링 `OFF 정위치`, 인터락 `0 정상` 으로 (기본 "미확인" 이면 시작 안 됨)
3. 처음 화면에는 **3D 카메라 2대(인텔) 영상**이 나란히 나옵니다
4. **[① 3D 검사]** 를 누른다 → 3D 카메라 창이 열리고, 진행은 **오른쪽 "3D 진행" 칸의 버튼**으로 (카메라 창에서 Space 를 눌러도 같음)
   - 턴테이블을 **비운 상태**에서 **[3D: 배경 촬영]** → 배경을 찍는다
   - 물체를 올리고 준비되면 **[3D: 스캔 시작]** → 그때부터 턴테이블이 돌며 스캔한다 (누르기 전에는 돌지 않는다)
   - 스캔 → 병합 → 측정 → DB 저장이 차례로 돌고, 기록란에 3D 출력이 나온다 (전체 출력은 `captures\3d_logs` 에도 저장)
5. 치수가 **합격** 이면 **[② 검사 시작 (PatchCore → YOLO)]** 이 켜진다. 불합격이면 켜지지 않는다 (다시 ① 부터)
6. **아이폰(YOLO) 카메라를 켜고** **[YOLO 카메라 연결]** (또는 ② 를 누르면 그때 연결). 3D 가 끝나기 전에 켜 둘 필요는 없다
7. **[② 검사 시작]** → PatchCore 가 `PATCHCORE_VIEWS` 장(기본 12장 = 30도씩)을 멈춰 가며 찍고, 가장 높은 이상 점수로 판정한다
   - 판정 기준은 `config.py` 의 `PATCHCORE_THRESHOLD` (지금 0.75, 점수가 기준 이상이면 불합격. 지우면 모델 기본값 0.5)
   - 합격이면 여기서 끝 (최종 정상)
   - 불합격이면 이어서 YOLO 가 한 바퀴 돌며 결함 종류·위치를 찍는다
   - **[PatchCore 먼저]** 체크를 끄면 YOLO 만 한다
8. 결과는 화면 오른쪽 "상태" 칸에 나오고, 같은 내용이 DB 에 저장된다 (MES 화면 [검사 조회])

검사 영역은 학습 때 쓴 **고정 ROI** (`ROI_X`, `ROI_Y`, 600×320 픽셀) 라서 화면에서 바꾸지 않는다. 카메라는 1920×1080 이어야 하고, 카메라를 옮겼으면 학습 때 위치로 다시 맞춘다 (입력 조건: `station_vision\PREPROCESSING.md`).

### 시험용 실행 옵션

| 명령 (끝에 붙임) | 용도 |
|---|---|
| `--sim` | 장비 없이 시험 (3D 는 가짜 측정값, 결과는 `--sim-3d fail` / `recheck` 로 바꿈) |
| `--no-gate` | 3D 검사 없이 ② 를 바로 누를 수 있게 (3D 합격 잠금 해제) |
| `--patchcore-only` | PatchCore 만 (3D·YOLO 없이 판정까지) |

### 아두이노 펌웨어

보드에는 펌웨어를 **하나만** 올릴 수 있습니다.
- **비전용** (`station_vision\turntable\turntable.ino`) — **지금 올라가 있음.** YOLO 가 연속 회전으로 돈다. 인터락(초음파)·놓임 검사 기능은 없다
- **3D용** (`station_3d\scanner_v2_6\turntable\turntable.ino`) — 인터락·놓임 검사 포함. 연속 회전(S/X)이 없어서 검사 프로그램이 YOLO 를 `YOLO_STEP_DEG`(기본 5도)씩 멈춰 가며 검사한다. 오류 없이 동작하도록 해 둠

어느 쪽이 올라가 있어도 검사 프로그램이 알아서 맞춰 동작합니다 (3D 쪽이면 기록란에 "3D 펌웨어" 안내가 뜸). 펌웨어를 바꿔 올릴 때는 시리얼 모니터와 검사 프로그램을 먼저 닫아야 합니다.

턴테이블 포트는 `station_vision\config.py` 의 `SERIAL_PORT` (지금 `COM3`) 하나로 정합니다. 3D 스크립트에도 이 값을 넘겨 주므로 `station_3d` 의 `COM6` 설정은 바뀌지 않고 무시됩니다.

**처음 한 번 (이 PC 는 이미 해 둠)** — 3D 패키지를 같은 환경에 설치:
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
`open3d` 가 `애플리케이션 제어 정책에서 이 파일을 차단했습니다` 로 안 열리면 Windows **스마트 앱 컨트롤**이 막는 것입니다. 이 PC 에서는 `open3d 0.20.0` 이 막혀서 **0.19.0 으로 고정**해 해결했습니다 (`pip install open3d==0.19.0`, requirements.txt 에 반영). 그래도 막히면 스마트 앱 컨트롤을 끄거나, 3D 가 되는 환경의 파이썬을 `station_vision\config.py` 의 `PYTHON_3D` 에 적어 3D 스크립트만 그 파이썬으로 돌릴 수 있습니다.

## 결과 보기

http://localhost:5173 → [검사 조회] → 줄을 누르면 사진·결함·치수, [안전 알람] 에서 알람 이력.

## 자주 나는 문제

| 증상 | 해결 |
|---|---|
| 창 1 에 `Can't connect to MySQL server` | 0번: MySQL84 서비스 시작 |
| 창 1 에 `only one usage of each socket address` | 서버가 이미 켜져 있음 → 기존 창 사용, 또는 그 창 닫고 다시 |
| 화면에 `요청 실패 (500)` / 로그인 안 됨 | 창 1 (MES 서버) 가 켜져 있는지 확인 |
| 검사 창 "기록"에 `DB 연결 실패 → 대기열에 저장` | MySQL 확인. 연결되면 쌓인 것이 자동으로 다시 저장됨 |
| 검사 창이 `턴테이블 응답이 없습니다` | 아두이노 연결·포트(COM3)·시리얼 모니터 닫기 |
| ② 검사 시작 버튼이 안 켜짐 | ① 3D 검사를 하고 치수가 합격이어야 함 (기록란의 `3D 결과:` 줄 확인) |
| 3D 단계에서 `open3d` 오류 | 위 3장의 스마트 앱 컨트롤 안내 |
| 검사 창이 `카메라 연결 실패` / `YOLO 카메라를 열지 못했습니다` | 카메라 앱(DroidCam 등) 켜고 [YOLO 카메라 연결]. 번호는 `camera_check.py` 로 확인 |
| `could not open port 'COM3'` (액세스 거부) | Arduino IDE 시리얼 모니터 닫기, 검사 프로그램이 두 개 떠 있지 않은지 확인 |
| PatchCore 점수가 전부 높게(불합격) 나옴 | 받침·조명·카메라 위치가 학습 때와 같은지. 히트맵(`captures\...\patchcore`)에서 빨간 곳 확인 |
| 3D 스캔 중 `Frame didn't arrive` | 인텔 카메라를 허브가 아닌 본체 USB 3 포트에 직접 꽂기 |
| 다른 PC 에서 화면이 안 열림 | 창 2 를 `--host` 로 켰는지, 방화벽 5173 규칙, Wi-Fi 개인 네트워크 |
