# PC 를 다시 켠 뒤 실행 순서 (터미널)

MES 서버 PC 를 껐다 켠 뒤, PowerShell 로 전체를 다시 띄우는 순서입니다.
처음 설치는 [SETUP.md](SETUP.md), 다른 PC 접속은 [DB_REMOTE_ACCESS.md](DB_REMOTE_ACCESS.md).

| 순서 | 무엇 | 창 |
|---|---|---|
| 0 | MySQL | 자동 (Windows 서비스 `MySQL84`) |
| 1 | MES 서버 (백엔드, 8000) | PowerShell 창 1 |
| 2 | MES 화면 (프론트엔드, 5173) | PowerShell 창 2 |
| 3 | 3D 검사 → DB 저장 (필요할 때) | PowerShell 창 3 |
| 4 | 비전 검사 버튼 프로그램 | PowerShell 창 4 |

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

## 3. 3D 검사 → DB 저장 (창 3, 3D 환경)

3D 가상환경이 있는 경우(`inspection\station_3d\.venv`):
```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_3d
.venv\Scripts\python.exe turntable_scan.py
.venv\Scripts\python.exe merge_turntable_scans.py
.venv\Scripts\python.exe measure_object.py
.venv\Scripts\python.exe ..\bridge_3d\save_3d_to_db.py --serial RC-0001 --centering OFF --interlock 0
```
마지막 줄이 DB 에 저장하고 검사번호를 `inspection\handoff\latest.json` 에 남깁니다 (비전 검사가 이어받음).
3D 를 안 하고 YOLO 만 시험할 때는 건너뜁니다.

## 4. 비전 검사 버튼 프로그램 (창 4, 비전 환경)

```powershell
cd C:\Users\짱가\Desktop\VisionQC_AI_MES\VisionQC-MES\inspection\station_vision
.venv\Scripts\python.exe inspection_app.py
```
가상환경 `inspection\station_vision\.venv` 에 PatchCore(anomalib, CPU용 torch)와 YOLO 가 같이 들어 있습니다.
PatchCore 모델은 `inspection\visionPatchCore\patchcore_export\models\v3\model.ckpt` 를 읽습니다 (100MB 가 넘어 git 에는 없음, 따로 복사).

[▶ 검사 시작] 한 번에:
1. **PatchCore**: 턴테이블이 45도씩 8번 멈추며 찍고, 가장 높은 이상 점수로 판정 (오른쪽 `PC 점수` = 최고 점수 / 기준)
2. 합격이면 여기서 끝 (최종 정상). 불합격이면 이어서 **YOLO** 한 바퀴로 결함 종류·위치를 찍음

`PatchCore 먼저` 체크를 끄면 예전처럼 YOLO 만 합니다. PatchCore 사진(원본·히트맵·점수)은 검사 폴더 안 `patchcore` 폴더에 남습니다.

창이 뜨면:
1. 오른쪽 **[DB 저장]** 칸의 DB 주소가 `mysql+pymysql://mes_user:...@localhost:3306/visionqc...` 인지 확인
2. **[장비 안전 상태]** 를 센터링 `OFF 정위치`, 인터락 `0 정상` 으로 (기본 "미확인" 이면 시작 안 됨)
3. 검사 영역이 맞는지 확인 (카메라가 움직였으면 [검사 영역 설정])
4. **[▶ 검사 시작]**

장비 없이 시험: 끝에 `--sim` 을 붙입니다.
실행 전 확인: 아두이노 IDE 의 시리얼 모니터는 닫기 (포트 `COM3`, `config.py` 의 `SERIAL_PORT`), 카메라 앱 켜기.

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
| 검사 창이 `카메라 연결 실패` | 카메라 앱(OBS/DroidCam) 켜기 |
| 다른 PC 에서 화면이 안 열림 | 창 2 를 `--host` 로 켰는지, 방화벽 5173 규칙, Wi-Fi 개인 네트워크 |
