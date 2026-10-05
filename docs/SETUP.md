# 설치 · 구동 가이드

Windows 10/11 기준으로 처음부터 끝까지 따라 하면 실행되도록 적었습니다.
명령은 **명령 프롬프트(cmd)** 기준이고, PowerShell 에서 다른 부분은 따로 표시했습니다.

- [1. 준비물 설치](#1-준비물-설치)
- [2. 코드 받기](#2-코드-받기)
- [2-1. 스크립트로 한 번에 설치 (권장)](#2-1-스크립트로-한-번에-설치-권장)
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
| 3 | `vision_client\requirements.txt` 설치 (같은 가상환경, 검사PC 클라이언트 테스트용) | 7-2 |
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
| `python seed.py` | 계정 2개(`admin`/`admin1234` 관리자, `operator`/`oper1234` 작업자) + 품목 규격 3개(Redcar, Bluecar, Greencar) |
| `python seed.py --demo` | 위 + 최근 7일 더미 검사 데이터와 이미지 (화면 확인용) |
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

검사 PC 클라이언트(`vision_client`) 테스트는 MES 서버 없이 가짜 서버로 돕니다.
```bat
cd vision_client
pip install requests pytest numpy
pytest -v
```

---

## 7. 검사 PC 연동

검사 프로그램(3D 치수 / PatchCore / YOLO)이 결과를 MES 로 보내는 방법입니다.

### 7-1. 검사 PC 에 파일 복사
`vision_client\mes_client.py` 를 검사 프로그램 폴더로 복사합니다.

### 7-2. 패키지 설치 (검사 PC 의 파이썬 환경에서)
`vision_client\requirements.txt` 도 같이 복사해서
```bat
pip install -r requirements.txt
```
필수는 `requests` 하나이고, `numpy` 는 `anomaly_map_to_box()` 를 쓸 때만, `pytest` 는 테스트할 때만 필요합니다.

### 7-3. 코드에 붙이기
```python
from mes_client import MESClient, yolo_to_detections, patchcore_to_detections, anomaly_map_to_box

mes = MESClient("http://<MES서버IP>:8000", api_key="<.env 의 INGEST_API_KEY>", model_version="v1.0")

# 3D 치수
mes.send_dimension("SN0001", "Redcar", "scan.png", width=40.1, length=90.0, height=30.0)

# PatchCore
mes.send_defects("SN0001", "Redcar", "PATCHCORE", "pc.png",
                 patchcore_to_detections(score, threshold=0.5, box=anomaly_map_to_box(amap, 0.5)))

# YOLO (ultralytics)
result = model("img.png")[0]
mes.send_defects("SN0001", "Redcar", "YOLO", "img.png", yolo_to_detections(result, conf_min=0.5))
```
전체 흐름 예시는 `vision_client\example_pipeline.py`.

### 7-4. 지켜야 할 값 규칙
| 값 | 규칙 | 예 |
|---|---|---|
| 시리얼 `serial_no` | 영문/숫자/`_`/`-`, 50자 이하. **같은 제품은 3공정 모두 같은 시리얼** | `SN2610050001` |
| 품목 `item` | 영문/숫자/`_` 만 (파일명에 들어감) | `Redcar` |
| 이미지 | `.jpg` `.jpeg` `.png` `.bmp`, 20MB 이하 | |
| 결함 박스 `box` | `[x1, y1, x2, y2]`, **원본 이미지 픽셀 기준** | `[120, 80, 180, 130]` |
| 신뢰도 `confidence` | 0 ~ 1 | `0.91` |

### 7-5. 서버가 꺼져 있을 때
`mes_queue\` 폴더에 결과가 쌓이고, 다음 전송 때 오래된 것부터 자동으로 다시 보냅니다. 검사 시각은 처음 검사한 시각 그대로 들어갑니다. 서버가 형식 오류로 거부한 건은 `mes_queue_failed\` 로 옮겨지니 가끔 확인하세요.

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
| `Unknown column 'users.role'` 등 컬럼 없음 | 예전(뼈대) 버전으로 만든 테이블 | `python seed.py --reset --demo` (데이터 삭제됨) |
| `[Errno 10048] ... only one usage of each socket address` | 8000 포트 사용 중 | `netstat -ano \| findstr :8000` 로 PID 확인 후 종료, 또는 `--port 8001` (이 경우 `vite.config.js` proxy 도 8001 로) |
| 화면에서 `요청 실패 (500)`, Vite 창에 `http proxy error ... ECONNREFUSED` | 백엔드가 안 켜져 있음 | 4-6 실행 |
| 로그인하자마자 다시 로그인 화면 | 토큰 만료 / `JWT_SECRET` 변경 | 다시 로그인 |
| 이미지가 회색 "불러올 수 없습니다" | 파일이 없음 / `STORAGE_DIR` 경로 변경 / 오래 띄워둔 화면 | `STORAGE_DIR` 확인, 새로고침 |
| 검사 PC 전송이 `401` | API Key 불일치 | 서버 `.env` 의 `INGEST_API_KEY` 와 `MESClient(api_key=...)` 맞추기 |
| 검사 PC 전송이 `422` | payload 형식 오류 (품목명에 `-`, 공정과 데이터 불일치 등) | 응답 메시지 확인, 7-4 규칙 확인 |
| 검사 PC 전송이 `MESError 422 ... dimension.status` | 서버에 그 품목 규격이 없음 | 화면 [치수 규격]에서 규격 등록, 또는 `status` 를 같이 보내기 |
| 다른 PC 에서 접속 안 됨 | `--host` 옵션 없음 / 방화벽 | 8장 |
| 검사 시각이 9시간 어긋남 | 서버 PC 시간대 설정 | Windows 시간대를 서울로, 검사 PC 는 `MESClient` 가 시간대 포함해서 보냄 |
| `npm install` 이 매우 느리거나 실패 | 네트워크 / 캐시 | `npm cache clean --force` 후 재시도 |
