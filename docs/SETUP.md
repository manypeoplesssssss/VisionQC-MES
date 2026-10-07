# 설치 · 구동 가이드

Windows 10/11 기준으로 처음부터 끝까지 따라 하면 실행되도록 적었습니다.
명령은 **명령 프롬프트(cmd)** 기준이고, PowerShell 에서 다른 부분은 따로 표시했습니다.

- [1. 준비물 설치](#1-준비물-설치)
- [2. 코드 받기](#2-코드-받기)
- [2-1. 스크립트로 한 번에 설치 (권장)](#2-1-스크립트로-한-번에-설치-권장)
- [2-2. 스크립트 없이 터미널로 설치 · 실행 (PowerShell)](#2-2-스크립트-없이-터미널로-설치--실행-powershell)
- [3. MySQL 준비](#3-mysql-준비)
- [4. 백엔드 실행](#4-백엔드-실행)
- [5. 프론트엔드 실행](#5-프론트엔드-실행)
- [6. 테스트 실행](#6-테스트-실행)
- [7. 검사 PC 연동](#7-검사-pc-연동)
- [8. 다른 PC 에서 접속하기](#8-다른-pc-에서-접속하기)
- [9. Docker 로 한 번에 실행](#9-docker-로-한-번에-실행)
- [10. 매일 실행 순서 요약](#10-매일-실행-순서-요약)
- [11. 문제 해결](#11-문제-해결)

---

## 1. 준비물 설치

| 프로그램 | 버전 | 용도 | 받는 곳 |
|---|---|---|---|
| Python | 3.11 또는 3.12 권장 (3.13 도 동작) | 백엔드 | https://www.python.org/downloads/ |
| Node.js | 20 LTS 이상 | 프론트엔드 | https://nodejs.org/ |
| MySQL Server | 8.0 또는 8.4 | DB | https://dev.mysql.com/downloads/installer/ |
| MySQL Workbench | 8.x (선택) | DB 를 화면으로 보기 | MySQL Installer 에 포함 |
| Git | 최신 | 팀 협업 | https://git-scm.com/ |
| Docker Desktop | 최신 (선택) | 9장 방법으로 실행할 때만 | https://www.docker.com/products/docker-desktop/ |

설치할 때 주의할 점
- **Python**: 설치 첫 화면에서 **"Add python.exe to PATH" 체크**. 안 하면 `python` 명령이 안 먹습니다.
- **MySQL**: 설치 중 root 비밀번호를 정하라고 나옵니다. 잊지 않게 적어 두세요. "Configure MySQL Server as a Windows Service" 는 켜 둔 채로 두면 PC 가 켜질 때 자동으로 실행됩니다.
- 설치가 끝나면 **열려 있던 cmd 창을 닫고 새로 여세요** (PATH 반영).

설치 확인
```bat
python --version
node --version
npm --version
mysql --version
```
`mysql` 명령이 없다고 나오면 Workbench 를 쓰면 되니 넘어가도 됩니다.

터미널에서 바로 설치하려면 winget 을 써도 됩니다 (Windows 11 기본 포함).
```bat
winget install -e --id Python.Python.3.12
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Oracle.MySQL
```
MySQL 없이 화면만 먼저 보고 싶다면 MySQL 은 건너뛰고 [3장 방법 C (SQLite)](#방법-c-mysql-없이-sqlite-로-빠르게-보기) 를 쓰면 됩니다.

---

## 2. 코드 받기

GitHub 저장소가 있다면
```bat
cd C:\work
git clone https://github.com/manypeoplesssssss/VisionQC-MES.git
cd VisionQC-MES
```
zip 으로 받았다면 원하는 곳에 압축을 풀고 그 폴더로 이동합니다.

> 폴더 경로에 **한글이나 공백이 없는 곳**(예: `C:\work\VisionQC-MES`)을 권장합니다. 일부 도구가 한글 경로에서 오류를 냅니다.

---

## 2-1. 스크립트로 한 번에 설치 (권장)

프로젝트 폴더의 **`install.bat` 을 더블클릭**(또는 cmd 에서 `install.bat`)하면 3~5장의 설치 작업을 한 번에 합니다. 스크립트 사용법 요약은 [README.md 의 설치 · 실행](../README.md#설치--실행).
아래 3~5장은 스크립트가 하는 일을 손으로 하는 방법이니, 스크립트가 성공했다면 **4-6(서버 실행)으로 건너뛰어도 됩니다.**

| 단계 | install.bat 이 하는 일 | 손으로 하면 |
|---|---|---|
| 1 | Python 3.11+ / Node.js 설치 확인 | 1장 |
| 2 | `backend\.venv` 가상환경 만들고 `backend\requirements-dev.txt` 설치 | 4-1, 4-3 |
| 3 | `inspection\common\requirements.txt` 설치 (같은 가상환경, 검사PC 클라이언트 테스트용) | 7-2 |
| 4 | `frontend` 에서 `npm install` | 5-1 |
| 5 | `backend\.env` 가 없으면 `.env.example` 복사 (있으면 그대로) | 4-4 |
| 선택 | `mysql` 명령이 있으면 물어보고 → `schema.sql` 실행 + `seed.py --demo` | 3장, 4-5 |

- 여러 번 실행해도 안전합니다. 이미 설치된 건 건너뛰고 바뀐 것만 설치합니다. **팀원 코드를 `git pull` 한 뒤 패키지가 바뀌었으면 다시 실행**하세요.
- 실패하면 창에 `[ERROR]` 와 이유가 나오고 멈춥니다 (11장 문제 해결 참고).
- 창의 안내 문구는 cmd 에서 한글이 깨지지 않도록 영어로 되어 있습니다.

같이 있는 파일
| 파일 | 하는 일 |
|---|---|
| `start.bat` | 백엔드(8000)·프론트(5173) 창 2개를 띄우고 브라우저를 엶. 끌 때는 각 창을 닫거나 `Ctrl+C` |
| `test.bat` | 백엔드 + 검사PC 클라이언트 테스트 전체. `test.bat tests\test_ingest.py -v` 처럼 인자를 주면 백엔드 테스트 일부만 |
| `install.sh` `start.sh` `test.sh` | Mac/Linux 팀원용 (`bash install.sh`) |

> MySQL 서버 자체는 스크립트가 설치하지 않습니다. 1장에서 설치해 두세요.

---

## 2-2. 스크립트 없이 터미널로 설치 · 실행 (PowerShell)

bat 파일을 쓰지 않고 PowerShell 에 직접 입력하는 방법입니다. 3~6장 내용을 복사해서 바로 쓸 수 있게 모은 것이고, 각 줄의 설명은 해당 장을 보세요.
가상환경을 켜지 않고 `.venv\Scripts\python.exe` 를 직접 부르기 때문에 PowerShell 실행 정책 오류(4-2)가 나지 않습니다.
`C:\work\VisionQC-MES` 는 코드를 받은 폴더로 바꿔서 입력하세요.

**처음 한 번**
```powershell
# 백엔드 패키지 (4-1, 4-3, 7-2)
cd C:\work\VisionQC-MES\backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r ..\inspection\common\requirements.txt

# 설정 파일 (4-4)
Copy-Item .env.example .env

# DB + 초기 데이터 (3장, 4-5) - MySQL 을 쓸 때
Get-Content sql\schema.sql | mysql -u root -p
.venv\Scripts\python.exe seed.py --demo
#   MySQL 없이 SQLite 로 할 때는 위 두 줄 대신 3장 방법 C

# 프론트엔드 패키지 (5-1)
cd ..\frontend
npm install
```

**실행할 때마다** (PowerShell 창 2개)
```powershell
# 창 1 - 백엔드 :8000
cd C:\work\VisionQC-MES\backend
# SQLite 로 할 때만: $env:DATABASE_URL = "sqlite:///./storage/dev.db"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# 창 2 - 프론트엔드 :5173
cd C:\work\VisionQC-MES\frontend
npm run dev
```
http://localhost:5173 에서 `admin` / `admin1234` 로 로그인합니다. 끌 때는 각 창에서 `Ctrl + C`.

**테스트** (6장, MySQL 필요 없음)
```powershell
cd C:\work\VisionQC-MES\backend
.venv\Scripts\python.exe -m pytest -q
cd ..\inspection\common
..\..\backend\.venv\Scripts\python.exe -m pytest -q
```

---

## 3. MySQL 준비

DB(`visionqc_mes`)와 접속 계정(`mes_user` / `mes_pass`)을 만듭니다. **테이블은 백엔드가 처음 뜰 때 자동으로 만들어지므로** 여기서는 DB 와 계정만 있으면 됩니다.

### 방법 A. MySQL Workbench
1. Workbench 실행 → `Local instance MySQL80` 클릭 → root 비밀번호 입력
2. `File > Open SQL Script...` → `backend\sql\schema.sql` 열기
3. 번개 아이콘(Execute) 클릭

### 방법 B. 명령줄
```bat
mysql -u root -p < backend\sql\schema.sql
```

### 확인
```bat
mysql -u mes_user -pmes_pass -e "SHOW DATABASES;"
```
목록에 `visionqc_mes` 가 보이면 성공입니다.

### 방법 C. MySQL 없이 SQLite 로 빠르게 보기
MySQL 을 설치하지 않고 파일 하나짜리 DB 로 화면을 확인하는 방법입니다 (개발·시연용). 코드나 `.env` 는 고치지 않고 **그 터미널에서만** 환경변수 `DATABASE_URL` 을 바꿉니다. 환경변수가 `.env` 보다 우선합니다.
```powershell
cd backend
New-Item -ItemType Directory -Force storage | Out-Null
$env:DATABASE_URL = "sqlite:///./storage/dev.db"
.venv\Scripts\python.exe seed.py --demo
```
cmd 라면 `mkdir storage` 와 `set DATABASE_URL=sqlite:///./storage/dev.db`.

- DB 파일은 `backend\storage\dev.db` 에 생기고 Git 에 올라가지 않습니다 (`storage/` 는 `.gitignore` 에 있음).
- **백엔드를 띄우는 창에서도 같은 `DATABASE_URL` 줄을 먼저 입력**해야 합니다. 창을 새로 열면 사라집니다.
- 계속 SQLite 로 쓸 거라면 `.env` 의 `DATABASE_URL` 을 위 값으로 바꿔도 됩니다.

> 계정 이름이나 비밀번호를 바꾸고 싶으면 `schema.sql` 위쪽의 `mes_user` / `mes_pass` 를 바꾸고, 4장의 `.env` 에도 똑같이 적어야 합니다.

---

## 4. 백엔드 실행

### 4-1. 가상환경 만들기 (처음 한 번)
프로젝트마다 패키지를 따로 설치하기 위한 독립 공간입니다.
```bat
cd backend
python -m venv .venv
```

### 4-2. 가상환경 켜기 (터미널을 새로 열 때마다)
```bat
.venv\Scripts\activate
```
PowerShell 이라면
```powershell
.venv\Scripts\Activate.ps1
```
줄 앞에 `(.venv)` 가 붙으면 켜진 것입니다.

> PowerShell 에서 "이 시스템에서 스크립트를 실행할 수 없으므로…" 오류가 나면 한 번만 실행:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4-3. 패키지 설치 (처음 한 번, requirements 가 바뀌었을 때)
```bat
pip install -r requirements-dev.txt
```
실행에 필요한 패키지 + 테스트 도구가 같이 설치됩니다. 각 패키지가 무엇인지는 [PACKAGES.md](PACKAGES.md) 참고.

### 4-4. 설정 파일 만들기 (처음 한 번)
```bat
copy .env.example .env
```
PowerShell 이라면 `Copy-Item .env.example .env`

`.env` 를 메모장이나 VS Code 로 열어서 필요한 값을 고칩니다.

| 항목 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://mes_user:mes_pass@localhost:3306/visionqc_mes?charset=utf8mb4` | DB 접속 정보. 형식은 `mysql+pymysql://아이디:비밀번호@호스트:포트/DB이름?charset=utf8mb4` |
| `STORAGE_DIR` | `./storage/images` | 검사 이미지를 저장할 폴더. 절대경로도 가능 (예: `D:/mes_images`) |
| `MAX_IMAGE_MB` | `20` | 업로드 이미지 1장 최대 크기(MB) |
| `JWT_SECRET` | `change-this-secret` | 로그인 토큰·이미지 주소 서명 키. **아무 긴 문자열로 꼭 바꾸기**. 바꾸면 기존 로그인은 모두 풀림 |
| `JWT_EXPIRE_MINUTES` | `480` | 로그인 유지 시간(분) |
| `IMAGE_URL_TTL_SECONDS` | `3600` | 이미지 주소 유효 시간(초) |
| `INGEST_API_KEY` | `change-this-ingest-key` | 검사 PC 가 결과를 올릴 때 쓰는 키. 검사 PC 쪽 `MESClient(api_key=...)` 와 같아야 함 |
| `CORS_ORIGINS` | `http://localhost:5173` | 다른 주소에서 띄운 프론트가 API 를 부를 때 허용 목록 (쉼표 구분) |

> `.env` 는 비밀번호가 들어 있어서 **Git 에 올리지 않습니다** (`.gitignore` 에 들어 있음). 팀원은 각자 `.env.example` 을 복사해서 씁니다.

### 4-5. 초기 데이터 넣기
```bat
python seed.py --demo
```
| 명령 | 하는 일 |
|---|---|
| `python seed.py` | 계정 3개(`admin`/`admin1234` 최고관리자, `manager`/`manager1234` 관리자, `viewer`/`viewer1234` 조회 전용) + 불량 종류 D01~D05 |
| `python seed.py --demo` | 위 + 최근 7일 더미 검사 데이터와 사진 (3D 치수 → PatchCore → YOLO 흐름, 화면 확인용) |
| `python seed.py --reset --demo` | **모든 테이블과 이미지를 지우고** 다시 생성. 되돌릴 수 없음 |

여러 번 실행해도 이미 있는 데이터는 다시 만들지 않습니다. 실제 라인 데이터만 쌓고 싶으면 `--demo` 없이 실행하세요.

### 4-6. 서버 실행
```bat
uvicorn app.main:app --reload --port 8000
```
- `app.main:app` : `app` 폴더의 `main.py` 안에 있는 `app` 객체를 실행
- `--reload` : 코드를 저장하면 서버가 자동으로 다시 뜸 (개발용)
- `--port 8000` : 포트 번호

아래처럼 나오면 성공입니다.
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 4-7. 확인
- http://localhost:8000/api/health → `{"status":"ok","db":"ok"}`
- http://localhost:8000/docs → API 문서 화면. 오른쪽 위 **Authorize** 를 누르고, `/api/auth/login` 으로 받은 토큰을 넣으면 모든 API 를 직접 눌러볼 수 있습니다.

서버를 끌 때는 그 창에서 `Ctrl + C`.

---

## 5. 프론트엔드 실행

**백엔드를 켜 둔 상태에서** 새 cmd 창을 엽니다.

### 5-1. 패키지 설치 (처음 한 번, package.json 이 바뀌었을 때)
```bat
cd frontend
npm install
```
`node_modules` 폴더가 생깁니다 (Git 에는 올리지 않음).

### 5-2. 개발 서버 실행
```bat
npm run dev
```
```
  VITE v5.x  ready in 300 ms
  ➜  Local:   http://localhost:5173/
```
브라우저에서 http://localhost:5173 → `admin` / `admin1234` 로 로그인.

개발 서버는 `/api` 로 시작하는 요청을 자동으로 백엔드(8000)로 넘겨줍니다 (`vite.config.js` 의 `proxy`). 그래서 프론트 코드에는 서버 주소를 적지 않습니다.

### 5-3. 배포용 빌드 (필요할 때)
```bat
npm run build
```
`frontend\dist` 폴더에 HTML/JS/CSS 가 만들어집니다. 9장의 Docker 방식에서는 이 과정을 자동으로 합니다.

---

## 6. 테스트 실행

MySQL 없이 임시 SQLite DB 로 API 전체를 검사합니다. 코드를 고친 뒤 PR 올리기 전에 꼭 돌려 주세요.

가장 쉬운 방법은 **`test.bat`** (백엔드 + 검사PC 클라이언트 전체). 손으로 하려면
```bat
cd backend
.venv\Scripts\activate
pytest -q
```
```
..................                                   [100%]
16 passed in 4.21s
```
어떤 테스트가 있는지 보려면 `pytest -v`. 테스트는 기능별 파일로 나뉘어 있어서 자기 기능만 돌릴 수 있습니다.
```bat
pytest tests/test_ingest.py -v                            :: 파일 하나 (F05·F06)
pytest tests/test_ingest.py::test_retest_gets_suffix -v   :: 테스트 하나
```
어떤 파일이 어떤 기능인지는 [FEATURES.md 8장](FEATURES.md#8-테스트-파일--기능-대응표).

검사 PC 클라이언트(`inspection/common`) 테스트는 MES 서버 없이 가짜 서버로 돕니다.
```bat
cd inspection\common
pip install requests pytest numpy
pytest -v
```

---

## 7. 검사 PC 연동

검사 프로그램(3D 치수 / PatchCore / YOLO)은 결과를 **DB(MySQL)에 직접 저장**하고, MES 서버와 화면은 **DB 에서 읽어서** 보여 줍니다.
```
검사 PC (inspection/) ──저장──▶ MySQL ◀──읽기── MES 서버 (backend/) ◀── 화면 (frontend/)
          └─ 사진은 MES 사진 폴더(STORAGE_DIR)로 복사, DB 에는 경로만
```

### 7-1. 검사 PC 에 폴더 복사
저장소의 `inspection\` 폴더를 검사 PC 로 복사합니다 (MES 서버·화면 폴더는 필요 없음). 구성은 [inspection/README.md](../inspection/README.md).
- `common\` : DB 저장 모듈 `db_client.py` (두 검사 프로그램이 같이 씀). `mes_client.py` 는 MES API 로 보내는 예전 방식(선택)
- `station_3d\` : 3D 치수 검사 (3D 환경, 3D 담당 코드)
- `bridge_3d\` : 3D 측정 결과를 DB 에 저장하고 비전 검사로 검사번호를 넘기는 연결 프로그램 (`save_3d_to_db.py`)
- `station_vision\` : 3D 검사 + PatchCore → YOLO 검사, 턴테이블 버튼 화면 (한 가상환경)

### 7-2. 패키지 설치 (검사 프로그램 폴더마다 가상환경 따로)
3D·PatchCore·YOLO 는 한 가상환경(`station_vision\.venv`)에 같이 설치해 한 화면에서 돌립니다 (3D 환경을 따로 두려면 `config.py` 의 `PYTHON_3D`).
```bat
cd inspection\station_vision
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
DB 저장에 필요한 것은 `sqlalchemy`, `pymysql`, `cryptography` 이고, 각 프로그램의 `requirements.txt` 에 들어 있습니다.

### 7-3. DB 주소와 사진 폴더
| 설정 | 정하는 곳 (위가 우선) | 같은 PC 기본값 |
|---|---|---|
| DB 주소 | 버튼 화면 [DB 저장] 칸 / `station_vision/config.py` 의 `DB_URL` / 환경변수 `VISIONQC_DB_URL` / `backend/.env` 의 `DATABASE_URL` | `backend/.env` 와 같은 DB |
| 사진 폴더 | 버튼 화면 / `config.py` 의 `STORAGE_DIR` | `backend/storage/images` (MES 의 `STORAGE_DIR`) |

검사 PC 와 MES 서버가 **다른 PC** 면 DB 주소에 MES 서버 IP 를 넣고 (`mysql+pymysql://mes_user:mes_pass@192.168.0.10:3306/visionqc_mes?charset=utf8mb4`),
사진 폴더는 MES 서버의 `STORAGE_DIR` 을 공유 폴더로 열어서 그 경로(`\\MES서버\images`)를 넣습니다. MySQL 은 다른 PC 접속을 허용해야 합니다 (`schema.sql` 의 `'mes_user'@'%'`).

### 7-4. 코드에 붙이기
DB 는 **검사 1회 = `product_inspection` 한 행**입니다. 같은 검사번호(`inspection_id`)로 단계별 결과를 채워 넣으면, 합격·재검·불합격과 최종 결과는 DB 가 자동으로 계산합니다.
테이블은 MES 서버가 처음 뜰 때 만들므로, 검사 프로그램보다 MES 서버를 한 번 먼저 실행하세요.
```python
from db_client import DBClient, safety_ok

db = DBClient()                                         # DB 주소·사진 폴더는 7-3 기본값 (직접 줘도 됨)
iid = "20261006_inspection_143000_001"                  # 검사번호 (날짜 포함)

db.start(iid, "redcar", product_serial="RC-0001")       # 0) 검사 시작
db.send_dimension(iid, 194.8, 85.0, 58.7, standards=(194.5, 84.96, 58.68),
                  centering="OFF", interlock="0")        # 1) 3D 치수 + 측정 시점 장비 상태
db.send_patchcore(iid, score=0.82, threshold=0.6)       # 2) PatchCore (점수 >= 기준 → 불합격)
db.send_yolo_capture(iid, 1, "c001.jpg", "c001_annotated.jpg",   # 3) YOLO 결함 사진 1장마다
                     defects=[{"defect_class": "scratch", "confidence": 0.91, "box": [120, 80, 180, 130]}],
                     angle_deg=95.0)
db.complete_yolo(iid)                                   # 4) 한 바퀴 끝 → YOLO 분류 완료
```
3D 쪽은 `bridge_3d/save_3d_to_db.py`, 턴테이블 버튼 검사 프로그램(`inspection_app.py`)은 YOLO 단계를 이 방식으로 저장합니다.

장비 안전 (센터링 · 인터락): 검사 허용은 **센터링 OFF(정위치) AND 인터락 0(정상)** 일 때만. ON / 1 / UNKNOWN(미확인·센서 응답 끊김)이면 검사 프로그램이 시작하지 않거나 장비를 멈추고 검사를 보류하며, DB 에 알람을 남김. 알람 해제만으로 자동 재시작하지 않음.
```python
if not safety_ok(centering, interlock):           # 이 PC 에서 바로 판단 (저장을 기다리지 않음)
    stop_equipment()                              # 장비 정지 → 검사 보류
db.check_safety("YOLO", centering, interlock, inspection_id=iid)   # 상태 기록, 이상이면 알람 행 추가
```
센서가 아직 없어서 `inspection_app.py` 는 화면의 [장비 안전 상태]에서 작업자가 고른 값을 쓰고(기본 미확인 → 시작 불가),
3D 쪽은 `bridge_3d/save_3d_to_db.py --centering OFF --interlock 0` 으로 넘깁니다.

| 최종 결과 (자동) | 뜻 |
|---|---|
| `DIMENSION_PENDING` | 치수 대기·재검 (치수가 아직 안 들어옴, 하나라도 누락, 또는 재검이라 다시 스캔 필요) |
| `DIMENSION_DEFECT` | 치수 불합격 (축별 불량 한계 초과) |
| `PATCHCORE_PENDING` | 치수 합격, PatchCore 대기 |
| `NORMAL` | 치수와 PatchCore 모두 합격 |
| `YOLO_PENDING` | PatchCore 불합격, YOLO 분류 대기 (사진이 들어오는 중이어도 완료 전이면 여기) |
| `PROCESS_DEFECT` | PatchCore 불합격, YOLO 분류 완료 |

### 7-5. 지켜야 할 값 규칙
| 값 | 규칙 | 예 |
|---|---|---|
| 검사번호 `inspection_id` | 영문/숫자/`_`/`-`, 64자 이하. **날짜를 넣어** 다른 날 검사와 겹치지 않게 | `20261006_inspection_143000_001` |
| 제품 모델명 `product_name` | 영문/숫자/`_` 만 (파일명에 들어감) | `redcar` |
| 제품번호 `product_serial` | 영문/숫자/`_`/`-` (선택) | `RC-0001` |
| 사진 | `.jpg` `.jpeg` `.png` `.bmp`, 20MB 이하 | |
| 결함 박스 `box` | `[x1, y1, x2, y2]`, **원본 사진 픽셀 기준** | `[120, 80, 180, 130]` |
| 신뢰도 `confidence` | 0 ~ 1 | `0.91` |
| 기준 치수 | `bridge_3d` 가 3D `station_3d/config.py` 의 `NOMINAL_MM` 을 같이 저장 | `[194.50, 84.96, 58.68]` |
| 판정 한계 | 가로 ±1.5 / ±2.5, 길이(전폭) ±3.5 / ±5.5, 높이 ±1.5 / ±2.0mm (정상 한계 / 불량 한계). 3D 코드 `TOLERANCE_MM` / `RECHECK_MM` 과 같은 값 | |

### 7-6. DB 에 연결이 안 될 때
`db_queue\` 폴더에 요청(사진 복사본 포함)이 쌓이고, 다음 저장 때 순서 그대로 자동으로 다시 저장합니다. 버튼 화면에는 "DB 대기 N" 과 경고가 보입니다.
시각 값은 처음 그대로 들어갑니다. DB 가 거부한 건(사진 번호 중복 등)은 `db_queue_failed\` 로 옮겨지니 가끔 확인하세요.

---

## 8. 다른 PC 에서 접속하기

같은 공유기/사내망 안에서 팀원 PC 나 검사 PC 가 MES 에 접속하려면

### 8-1. 서버 PC 의 IP 확인
```bat
ipconfig
```
`IPv4 주소 . . . : 192.168.0.10` 같은 값을 확인합니다.

### 8-2. 외부 접속을 허용하며 실행
```bat
:: 백엔드 (0.0.0.0 = 모든 네트워크에서 접속 허용)
uvicorn app.main:app --host 0.0.0.0 --port 8000

:: 프론트엔드 (다른 cmd 창)
npm run dev -- --host
```

### 8-3. Windows 방화벽 열기 (관리자 권한 cmd 에서 한 번)
```bat
netsh advfirewall firewall add rule name="VisionQC MES API" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="VisionQC MES Web" dir=in action=allow protocol=TCP localport=5173
```

### 8-4. 접속
- 화면: `http://192.168.0.10:5173`
- 검사 PC 의 `MESClient("http://192.168.0.10:8000", ...)`

---

## 9. Docker 로 한 번에 실행

MySQL·백엔드·프론트를 직접 설치하지 않고 컨테이너로 띄우는 방법입니다. Docker Desktop 이 실행 중이어야 합니다.

```bat
cd VisionQC-MES
docker compose up -d --build
docker compose exec backend python seed.py --demo
```
- 화면: http://localhost (80 포트)
- API 문서: http://localhost:8000/docs

| 명령 | 하는 일 |
|---|---|
| `docker compose ps` | 컨테이너 상태 |
| `docker compose logs -f backend` | 백엔드 로그 보기 (`Ctrl+C` 로 빠져나옴) |
| `docker compose down` | 끄기 (데이터는 남음) |
| `docker compose down -v` | 끄고 **DB·이미지까지 삭제** |
| `docker compose up -d --build` | 코드 바꾼 뒤 다시 빌드해서 켜기 |

비밀번호/키는 `docker-compose.yml` 의 `environment` 에서 바꿉니다. 이미 로컬에 MySQL 이 3306 포트로 돌고 있으면 충돌하니, 로컬 MySQL 을 끄거나 `ports: ["3307:3306"]` 처럼 바꾸세요.

---

## 10. 매일 실행 순서 요약

**`start.bat` 더블클릭** 이면 끝입니다 (백엔드·프론트 창 2개 + 브라우저). MySQL 은 Windows 서비스로 자동 실행됩니다.

손으로 하려면
```bat
:: 창 1 - 백엔드
cd C:\work\VisionQC-MES\backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

:: 창 2 - 프론트엔드
cd C:\work\VisionQC-MES\frontend
npm run dev
```
PowerShell 이나 SQLite 로 할 때는 [2-2](#2-2-스크립트-없이-터미널로-설치--실행-powershell) 의 "실행할 때마다" 를 쓰세요.

팀원 코드를 받은 뒤에는
```bat
git pull
install.bat
```
(`requirements*.txt` / `package.json` 이 안 바뀌었으면 install.bat 은 건너뛰어도 됩니다)

---

## 11. 문제 해결

| 증상 / 메시지 | 원인 | 해결 |
|---|---|---|
| `'python'은(는) 내부 또는 외부 명령...` | PATH 미등록 | Python 재설치 시 "Add to PATH" 체크, 또는 `py` 명령 사용 |
| `Activate.ps1 ... 스크립트를 실행할 수 없으므로` | PowerShell 실행 정책 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 또는 cmd 사용 |
| `ModuleNotFoundError: No module named 'fastapi'` | 가상환경이 꺼져 있음 / 설치 안 함 | `.venv\Scripts\activate` 후 `pip install -r requirements-dev.txt` |
| `Can't connect to MySQL server on 'localhost'` (2003) | MySQL 이 꺼져 있음 | `Win+R` → `services.msc` → `MySQL80` 시작 |
| `Access denied for user 'mes_user'` (1045) | 계정/비밀번호 불일치 | `schema.sql` 다시 실행, `.env` 의 `DATABASE_URL` 확인 |
| `Unknown database 'visionqc_mes'` (1049) | DB 를 안 만듦 | 3장 다시 |
| `'cryptography' package is required for ... caching_sha2_password` | MySQL 8 인증 방식 | `pip install cryptography` (requirements 에 포함) |
| `Unknown column ...` / `no such table: product_inspection` | 예전 구조(테이블 4개로 바뀌기 전)로 만든 DB | `python seed.py --reset --demo` (데이터 삭제됨) |
| `[Errno 10048] ... only one usage of each socket address` | 8000 포트 사용 중 | `netstat -ano \| findstr :8000` 로 PID 확인 후 종료, 또는 `--port 8001` (이 경우 `vite.config.js` proxy 도 8001 로) |
| 화면에서 `요청 실패 (500)`, Vite 창에 `http proxy error ... ECONNREFUSED` | 백엔드가 안 켜져 있음 | 4-6 실행 |
| 로그인하자마자 다시 로그인 화면 | 토큰 만료 / `JWT_SECRET` 변경 | 다시 로그인 |
| 이미지가 회색 "불러올 수 없습니다" | 파일이 없음 / `STORAGE_DIR` 경로 변경 / 오래 띄워둔 화면 | `STORAGE_DIR` 확인, 새로고침 |
| 검사 PC 전송이 `401` | API Key 불일치 | 서버 `.env` 의 `INGEST_API_KEY` 와 `MESClient(api_key=...)` 맞추기 |
| 검사 PC 전송이 `422` | 형식 오류 (제품 모델명에 `-`, 검사번호에 `.` 등) | 응답 메시지 확인, 7-4 규칙 확인 |
| 3D 치수 결과가 계속 `대기` | 기준 치수가 없음 (`PRODUCT_STANDARDS` 에 그 제품이 없음) | `.env` 의 `PRODUCT_STANDARDS` 에 추가, 또는 `send_dimension(..., standards=(가로, 길이, 높이))` |
| 검사 PC 전송이 `404 검사가 없습니다` | `start()` 없이 단계 결과만 보냄 | 먼저 `mes.start(검사번호, 제품명)` 호출 |
| 다른 PC 에서 접속 안 됨 | `--host` 옵션 없음 / 방화벽 | 8장 |
| 검사 시각이 9시간 어긋남 | 서버 PC 시간대 설정 | Windows 시간대를 서울로, 검사 PC 는 `MESClient` 가 시간대 포함해서 보냄 |
| `npm install` 이 매우 느리거나 실패 | 네트워크 / 캐시 | `npm cache clean --force` 후 재시도 |
