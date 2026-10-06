# 사용 패키지 · 기술 정리

이 프로젝트가 쓰는 언어, 프레임워크, 라이브러리를 **무엇에 쓰는지 / 어느 파일에서 쓰는지** 기준으로 정리했습니다.
버전은 "이 이상이면 동작" 하는 최소 기준입니다 (`requirements.txt`, `package.json` 에 적힌 값).

- [설치 파일 한눈에 보기](#설치-파일-한눈에-보기)
- [전체 한눈에 보기](#전체-한눈에-보기)
- [백엔드 (Python)](#백엔드-python)
- [프론트엔드 (JavaScript)](#프론트엔드-javascript)
- [검사 PC 클라이언트](#검사-pc-클라이언트)
- [인프라 · 도구](#인프라--도구)
- [일부러 쓰지 않은 것](#일부러-쓰지-않은-것)
- [패키지 추가하는 방법](#패키지-추가하는-방법)

---

## 설치 파일 한눈에 보기

| 파일 | 대상 | 설치 명령 (보통은 `install.bat` 이 대신 실행) |
|---|---|---|
| `backend/requirements.txt` | 백엔드 실행 | `pip install -r requirements.txt` |
| `backend/requirements-dev.txt` | 백엔드 실행 + 테스트 | `pip install -r requirements-dev.txt` |
| `frontend/package.json` | 프론트엔드 | `npm install` (처음 실행하면 `package-lock.json` 이 생김 → **커밋해서 팀 전체 버전 통일**) |
| `inspection/common/requirements.txt` | 검사 PC 클라이언트 | `pip install -r requirements.txt` |
| `install.bat` / `install.sh` | 위 전부 + `.env` + (선택) DB | 더블클릭 / `bash install.sh` |

## 전체 한눈에 보기

```
[브라우저]  React 18 + react-router 6     ← Vite 5 로 개발/빌드
     │ fetch (/api/..., JSON, Bearer 토큰)
[API 서버]  FastAPI + Uvicorn (Python 3.11+)
     │ SQLAlchemy 2.0 + PyMySQL
[DB]        MySQL 8
[파일]      로컬 폴더 storage/images/yyyy-mm-dd/
     ▲ requests (multipart, X-API-Key)
[검사 PC]   mes_client.py  ← 팀의 3D 치수 / PatchCore / YOLO 코드
```

| 구분 | 언어 | 핵심 기술 | 설치 파일 |
|---|---|---|---|
| 백엔드 | Python 3.11+ | FastAPI, SQLAlchemy, Pydantic | `backend/requirements.txt` |
| 백엔드 테스트 | Python | pytest, httpx | `backend/requirements-dev.txt` |
| 프론트엔드 | JavaScript (JSX) | React, react-router, Vite | `frontend/package.json` |
| 검사 PC | Python | requests | `inspection/common/requirements.txt` |
| DB | SQL | MySQL 8 | `backend/sql/schema.sql` |
| 배포(선택) | - | Docker, nginx | `docker-compose.yml`, `*/Dockerfile` |

---

## 백엔드 (Python)

설치: `cd backend` → `pip install -r requirements.txt` (테스트까지: `requirements-dev.txt`)

### 실행용 (`requirements.txt`)

| 패키지 | 최소 버전 | 무엇인가 | 이 프로젝트에서 하는 일 | 쓰는 파일 |
|---|---|---|---|---|
| **fastapi** | 0.115 | 파이썬 웹 API 프레임워크 | 모든 REST API, 요청값 검증, `/docs` 자동 문서, 의존성 주입(`Depends`)으로 로그인·권한 체크 | `app/main.py`, `app/routers/*.py`, `app/security.py` |
| **uvicorn[standard]** | 0.30 | ASGI 웹 서버 | FastAPI 앱을 실제로 띄움 (`uvicorn app.main:app`). `[standard]` 는 빠른 이벤트루프·자동 재시작(--reload) 기능 포함 | 실행 명령, `Dockerfile` |
| **sqlalchemy** | 2.0 | ORM (파이썬 클래스 ↔ DB 테이블) | 테이블 정의, 쿼리 작성, 트랜잭션. SQL 문자열을 직접 쓰지 않아 MySQL/SQLite 둘 다 같은 코드로 동작 | `app/models.py`, `app/database.py`, `app/services/*.py`, `app/routers/*.py` |
| **pymysql** | 1.1 | 순수 파이썬 MySQL 드라이버 | SQLAlchemy 가 MySQL 에 실제로 접속할 때 사용 (`mysql+pymysql://...`). C 컴파일이 필요 없어 Windows 설치가 쉬움 | `.env` 의 `DATABASE_URL` |
| **cryptography** | 42 | 암호화 라이브러리 | MySQL 8 기본 인증 방식(`caching_sha2_password`)으로 접속할 때 PyMySQL 이 필요로 함. 코드에서 직접 import 하지는 않음 | (PyMySQL 내부) |
| **pydantic** | 2.7 | 데이터 검증 라이브러리 | API 요청/응답 형식 정의와 검증 (틀린 값이면 자동 422). FastAPI 가 내부적으로 사용 | `app/schemas.py` |
| **pydantic-settings** | 2.3 | 설정 관리 | `.env` 파일과 환경변수를 읽어 `settings` 객체로 만듦 | `app/config.py` |
| **pyjwt** | 2.8 | JWT 토큰 생성·검증 | 로그인 토큰 발급, 요청마다 서명·만료 검사 | `app/security.py` |
| **bcrypt** | 4.1 | 비밀번호 해시 | 비밀번호를 복원 불가능한 해시로 저장하고 로그인 시 비교 | `app/security.py` |
| **python-multipart** | 0.0.9 | multipart/form-data 파서 | 이미지 파일 + JSON 을 한 번에 받는 업로드 API 에 필요 (FastAPI 의 `File`, `Form`) | `app/routers/ingest.py` |
| **pillow** | 10.0 | 이미지 처리 | `seed.py` 에서 더미 검사 이미지 생성 (서버 실행 자체에는 안 씀) | `seed.py` |

### 테스트용 (`requirements-dev.txt`)

| 패키지 | 최소 버전 | 하는 일 | 쓰는 파일 |
|---|---|---|---|
| **pytest** | 8.0 | 테스트 실행기. `test_` 로 시작하는 함수를 찾아 실행, fixture 로 준비 작업 공유 | `tests/*.py` |
| **httpx** | 0.27 | HTTP 클라이언트. FastAPI `TestClient` 가 내부적으로 사용 (서버를 띄우지 않고 API 호출) | `tests/conftest.py` |

### 표준 라이브러리 (설치 불필요)

| 모듈 | 하는 일 |
|---|---|
| `hmac`, `hashlib` | 이미지 주소 서명 (`storage.py`) |
| `secrets` | API Key 를 타이밍 공격에 안전하게 비교 (`security.py`) |
| `csv`, `io` | CSV 내보내기 (`routers/inspections.py`) |
| `logging` | 서버 로그 |
| `pathlib` | 파일 경로 처리, 경로 조작(`../`) 차단 |
| `dataclasses` | 제품 집계용 임시 구조체 (`services/products.py`) |

---

## 프론트엔드 (JavaScript)

설치: `cd frontend` → `npm install`

### 실행용 (`dependencies`)

| 패키지 | 버전 | 무엇인가 | 이 프로젝트에서 하는 일 | 쓰는 파일 |
|---|---|---|---|---|
| **react** | ^18.3 | UI 라이브러리 | 모든 화면을 컴포넌트로 구성, `useState`/`useEffect` 로 상태와 API 호출 관리 | `src/**/*.jsx` |
| **react-dom** | ^18.3 | React 를 브라우저 DOM 에 그리는 부분 | `createRoot` 로 앱 시작 | `src/main.jsx` |
| **react-router-dom** | ^6.26 | 주소(URL) 기반 화면 전환 | `/`, `/inspections`, `/products/:serial` 등 라우팅, 메뉴 활성 표시(`NavLink`), 필터를 주소창에 저장(`useSearchParams`) | `src/App.jsx`, `src/components/Layout.jsx`, `src/pages/*.jsx` |

### 개발용 (`devDependencies`)

| 패키지 | 버전 | 하는 일 |
|---|---|---|
| **vite** | ^5.4 | 개발 서버(`npm run dev`, 저장 즉시 화면 반영)와 배포 빌드(`npm run build`). `/api` 요청을 백엔드로 넘기는 프록시 |
| **@vitejs/plugin-react** | ^4.3 | Vite 에서 JSX 문법 변환, React 빠른 새로고침 |

`^18.3.1` 의 `^` 는 "18.x 중 최신(19 미만)" 이라는 뜻입니다. 팀원끼리 정확히 같은 버전을 쓰려면 `npm install` 때 생기는 `package-lock.json` 을 Git 에 같이 올리세요.

### 브라우저 기본 기능 (설치 불필요)

| 기능 | 하는 일 |
|---|---|
| `fetch` | API 호출 (`src/api/client.js`) |
| `localStorage` | 로그인 토큰 저장 → 새로고침해도 로그인 유지 |
| SVG | 차트(`Charts.jsx`)와 결함 박스(`ImageViewer.jsx`) 직접 그리기 |
| CSS 변수 | 색상 한 곳에서 관리 (`styles.css` 의 `:root`) |

---

## 검사 PC 클라이언트

`inspection/common/mes_client.py` 를 검사 프로그램이 돌아가는 파이썬 환경에서 import 합니다.

| 패키지 | 필수 | 하는 일 |
|---|---|---|
| **requests** | 필수 | MES 서버로 이미지 + 결과 전송 (`pip install requests`) |
| **numpy** | `anomaly_map_to_box()` 쓸 때만 | PatchCore anomaly map 에서 결함 영역 박스 계산 (보통 PatchCore 환경에 이미 있음) |
| ultralytics | 팀 코드 쪽 | `yolo_to_detections()` 가 ultralytics YOLO 결과(`Results`) 형식을 받음. mes_client 자체는 ultralytics 를 import 하지 않음 |

설치: 검사 PC 에서 `pip install -r inspection/common/requirements.txt` (개발 PC 는 `install.bat` 이 같이 설치)

---

## 인프라 · 도구

| 이름 | 버전 | 하는 일 | 파일 |
|---|---|---|---|
| **MySQL** | 8.0 / 8.4 | 검사 결과·사용자·규격 저장. `utf8mb4` 로 한글 이름 저장 가능 | `backend/sql/schema.sql` |
| **Docker / Docker Compose** | 최신 | MySQL·백엔드·프론트를 컨테이너 3개로 한 번에 실행 (선택) | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` |
| **nginx** | 1.27 (Docker 이미지) | Docker 실행 시 React 빌드 결과 제공 + `/api` 를 백엔드로 전달 | `frontend/nginx.conf` |
| **python:3.12-slim** | Docker 이미지 | 백엔드 컨테이너 기반 | `backend/Dockerfile` |
| **node:20-alpine** | Docker 이미지 | 프론트 빌드용 (최종 이미지에는 안 들어감) | `frontend/Dockerfile` |
| Git / GitHub | - | 버전 관리, 팀 협업 (`docs/TEAM.md` 규칙) | `.gitignore` |

---

## 일부러 쓰지 않은 것

팀원이 "왜 이건 없지?" 할 만한 것들과 이유입니다. 필요해지면 추가해도 됩니다.

| 안 쓴 것 | 대신 | 이유 |
|---|---|---|
| 차트 라이브러리 (Recharts, Chart.js) | SVG 직접 (`Charts.jsx`) | 차트 2종류뿐이라 의존성 없이 가볍게. 차트가 많아지면 Recharts 추천 |
| CSS 프레임워크 (Tailwind, MUI) | `styles.css` 한 파일 | 설정 없이 바로 읽히는 코드. 화면이 늘면 도입 검토 |
| 상태관리 (Redux, Zustand) | React Context + URL 쿼리스트링 | 전역 상태가 로그인 정보뿐이라 충분 |
| axios | `fetch` (`api/client.js`) | 브라우저 기본 기능으로 충분 |
| Alembic (DB 마이그레이션) | `create_all` + `seed.py --reset` | 개발 단계라 단순하게. 실제 데이터가 쌓이면 도입 권장 |
| 클라우드 파일 저장소 (S3 등) | 로컬 폴더 | 요구사항이 "로컬 저장 + DB 에 파일명 기록" |

---

## 패키지 추가하는 방법

> 아래처럼 목록 파일(`requirements*.txt`, `package.json`)에 추가해 두면, 팀원은 `git pull` 후 **`install.bat` 만 다시 실행**하면 됩니다.

### 백엔드
```bat
cd backend
.venv\Scripts\activate
pip install 패키지이름
```
그리고 `requirements.txt` 에 `패키지이름>=버전` 한 줄 추가 (테스트 전용이면 `requirements-dev.txt`). 설치된 버전은 `pip show 패키지이름` 으로 확인.

### 프론트엔드
```bat
cd frontend
npm install 패키지이름          :: 실행용
npm install -D 패키지이름       :: 개발 도구
```
`package.json` 과 `package-lock.json` 이 자동으로 바뀌니 둘 다 커밋.

추가했으면 이 문서 표에도 한 줄 적어 주세요.
