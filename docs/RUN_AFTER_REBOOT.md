# PC 를 다시 켠 뒤 실행 순서 (터미널)

MES 서버 PC 를 껐다 켠 뒤, PowerShell 로 전체를 다시 띄우는 순서입니다.
처음 설치는 [SETUP.md](SETUP.md), 다른 PC 접속은 [DB_REMOTE_ACCESS.md](DB_REMOTE_ACCESS.md).

| 순서 | 무엇 | 창 |
|---|---|---|
| 0 | MySQL | 자동 (Windows 서비스 `MySQL84`) |
| 1 | MES 서버 (백엔드, 8000) | PowerShell 창 1 |
| 2 | MES 화면 (프론트엔드, 5173) | PowerShell 창 2 |
| 3 | 3D 검사 + YOLO 검사 (한 화면) | PowerShell 창 3 |

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

## 3. 3D 검사 + YOLO 검사 (창 3, 한 화면)

3D 와 YOLO 는 같은 가상환경(`inspection\station_vision\.venv`)에서 한 화면으로 돌립니다.
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe inspection_app.py
```
창이 뜨면:
1. 오른쪽 **[DB 저장]** 칸의 DB 주소가 `mysql+pymysql://mes_user:...@localhost:3306/visionqc...` 인지 확인, 제품 번호가 있으면 입력
2. **[장비 안전 상태]** 를 센터링 `OFF 정위치`, 인터락 `0 정상` 으로 (기본 "미확인" 이면 시작 안 됨)
3. **[① 3D 검사]** 를 누른다 → 스캔 → 병합 → 측정 → DB 저장이 차례로 돌고 기록란에 3D 출력이 나온다.
   스캔 때 열리는 3D 창의 안내(배경 촬영, 물체 올리기 등 Space 키)를 따른다. 3D 가 카메라·턴테이블을 쓰는 동안 이 화면은 연결을 놓아 준다
4. 치수가 **합격** 이면 **[② YOLO 검사 시작]** 이 켜진다. 불합격·재검이면 켜지지 않는다 (재검은 다시 ① 부터)
5. 검사 영역이 맞는지 확인 (카메라가 움직였으면 [검사 영역 설정]) 후 **[② YOLO 검사 시작]**

장비 없이 시험: `inspection_app.py --sim` (3D 는 가짜 측정값, 결과는 `--sim-3d fail` / `recheck` 로 바꿈).
3D 없이 YOLO 만 시험: `inspection_app.py --no-gate` (② 잠금 해제).
실행 전 확인: 아두이노 IDE 의 시리얼 모니터는 닫기, 카메라 앱 켜기. 3D 스크립트의 포트는 `station_3d\config.py` 의 `SERIAL_PORT`, YOLO 는 `station_vision\config.py` 의 `SERIAL_PORT`.

**처음 한 번 (이 PC 는 이미 해 둠)** — 3D 패키지를 같은 환경에 설치:
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
`open3d` 가 `애플리케이션 제어 정책에서 이 파일을 차단했습니다` 로 안 열리면 Windows **스마트 앱 컨트롤**이 막는 것입니다 (설정 → Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 설정). 3D 팀이 쓰는 환경이 따로 있으면 `station_vision\config.py` 에 `PYTHON_3D = r"그 환경\Scripts\python.exe"` 를 적어 3D 스크립트만 그 파이썬으로 돌릴 수 있습니다.

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
