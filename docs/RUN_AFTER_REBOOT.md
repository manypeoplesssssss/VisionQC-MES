# PC 를 다시 켠 뒤 실행 순서 (터미널)

MES 서버 PC 를 껐다 켠 뒤, PowerShell 로 전체를 다시 띄우는 순서입니다.
처음 설치는 [SETUP.md](SETUP.md), 다른 PC 접속은 [DB_REMOTE_ACCESS.md](DB_REMOTE_ACCESS.md).

| 순서 | 무엇 | 창 |
|---|---|---|
| 0 | MySQL | 자동 (Windows 서비스 `MySQL84`) |
| 1 | MES 서버 (백엔드, 8000) | PowerShell 창 1 |
| 2 | MES 화면 (프론트엔드, 5173) | PowerShell 창 2 |
| 3 | 3D 검사 + PatchCore + YOLO 검사 (한 화면) | PowerShell 창 3 |

창마다 켜 둔 채로 두고, 끌 때는 그 창에서 `Ctrl + C` (검사 프로그램은 창을 닫으면 됨).

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

## 3. 3D 검사 + PatchCore + YOLO 검사 (창 3, 한 화면)

3D·PatchCore·YOLO 는 같은 가상환경(`inspection\station_vision\.venv`)에서 한 화면으로 돌립니다.
PatchCore 모델은 `inspection\visionPatchCore\patchcore_export\models\v3\model.ckpt` 를 읽습니다 (100MB 가 넘어 git 에는 없음, 따로 복사). 처음 켤 때 모델을 불러오느라 30초쯤 걸립니다.
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe inspection_app.py
```
창이 뜨면:
1. 오른쪽 **[DB 저장]** 칸의 DB 주소가 `mysql+pymysql://mes_user:...@localhost:3306/visionqc...` 인지 확인, 제품 번호가 있으면 입력
2. **[장비 안전 상태]** 를 센터링 `OFF 정위치`, 인터락 `0 정상` 으로 (기본 "미확인" 이면 시작 안 됨)
   (처음 화면에는 **3D 카메라 2대(인텔)** 영상이 나란히 나온다. 치수가 합격하면 YOLO 카메라 영상으로 바뀐다)
3. **[① 3D 검사]** 를 누른다 → 스캔 → 병합 → 측정 → DB 저장이 차례로 돌고 기록란에 3D 출력이 나온다.
   스캔이 시작되면 3D 카메라 창이 열리고, 진행은 **이 프로그램의 버튼**으로 한다 (카메라 창에서 Space 를 눌러도 같음):
   - 턴테이블을 비운 상태에서 **[① 배경 촬영]** → 배경을 찍는다
   - 물체를 올리고 준비되면 **[② 스캔 시작]** → 그때부터 턴테이블이 돌며 스캔한다 (누르기 전에는 돌지 않는다) 3D 가 카메라·턴테이블을 쓰는 동안 이 화면은 연결을 놓아 준다
   YOLO 카메라(아이폰 카메라 등)는 3D 검사 때 꺼 두어도 됩니다. 3D 가 끝난 뒤 카메라를 켜고 [YOLO 카메라 연결]이나 ② 를 누르면 그때 연결합니다 (프로그램을 껐다 켤 필요 없음)
4. 치수가 **합격** 이면 **[② 검사 시작 (PatchCore → YOLO)]** 이 켜진다. 불합격·재검이면 켜지지 않는다 (재검은 다시 ① 부터)
5. **[② 검사 시작]** 을 누르면 PatchCore 가 `config.py` 의 `PATCHCORE_VIEWS` 장(기본 12장 = 30도씩)을 멈춰 가며 찍고, 가장 높은 이상 점수로 판정한다.
   합격이면 여기서 끝(최종 정상), 불합격이면 이어서 YOLO 한 바퀴로 결함 종류·위치를 찍는다. **[PatchCore 먼저]** 체크를 끄면 YOLO 만 한다.
   검사 영역은 학습 때 쓴 **고정 ROI** (`ROI_X`, `ROI_Y`, 600×320 픽셀) 라서 화면에서 바꾸지 않는다. 카메라는 1920×1080 이어야 하고, 카메라를 옮겼으면 학습 때 위치로 다시 맞춘다 (입력 조건: `station_vision\PREPROCESSING.md`)

장비 없이 시험: `inspection_app.py --sim` (3D 는 가짜 측정값, 결과는 `--sim-3d fail` / `recheck` 로 바꿈).
3D 없이 YOLO 만 시험: `inspection_app.py --no-gate` (② 잠금 해제).
**아두이노 펌웨어:** 보드 하나로 3D 와 비전을 같이 쓰므로 **3D 펌웨어(`station_3d\scanner_v2_6	urntable	urntable.ino`)** 를 올려 두면 된다. 이 펌웨어에는 연속 회전(S/X)이 없어서, 검사 프로그램이 YOLO 를 5도씩 멈춰 가며 검사한다 (PatchCore 는 원래 그렇게 동작). 비전 전용 펌웨어(`station_vision	urntable	urntable.ino`)를 올리면 YOLO 가 연속 회전하지만 3D 스캔은 못 한다.
실행 전 확인: 아두이노 IDE 의 시리얼 모니터는 닫기, 카메라 앱 켜기. 턴테이블 포트는 `station_vision\config.py` 의 `SERIAL_PORT` 하나로 정합니다 (3D 스크립트에도 이 값을 넘겨 주므로 `station_3d` 의 `COM6` 설정은 바뀌지 않고 무시됨).

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
| ② YOLO 버튼이 안 켜짐 | ① 3D 검사를 하고 치수가 합격이어야 함 (기록란의 `3D 결과:` 줄 확인) |
| 3D 단계에서 `open3d` 오류 | 위 3장의 스마트 앱 컨트롤 안내 |
| 검사 창이 `카메라 연결 실패` | 카메라 앱(OBS/DroidCam) 켜기 |
| 다른 PC 에서 화면이 안 열림 | 창 2 를 `--host` 로 켰는지, 방화벽 5173 규칙, Wi-Fi 개인 네트워크 |
