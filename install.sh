#!/usr/bin/env bash
# ============================================================
#  VisionQC AI MES - 의존성 한 번에 설치 (Mac / Linux)
#  실행: bash install.sh     (다시 실행해도 빠진 것만 설치)
#  Windows 는 install.bat
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

echo "[1/5] Python / Node.js 확인"
command -v "$PY" >/dev/null || { echo "[오류] python3 가 없습니다 (3.11 이상 설치)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "[오류] Python 3.11 이상이 필요합니다: $("$PY" --version)"; exit 1; }
command -v npm >/dev/null || { echo "[오류] npm 이 없습니다 (Node.js 20 LTS 설치)"; exit 1; }
"$PY" --version; echo "Node.js $(node --version)"

echo "[2/5] 백엔드: backend/.venv 가상환경 + 패키지"
[ -x backend/.venv/bin/python ] || "$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt

echo "[3/5] 검사 PC 클라이언트 패키지 (같은 가상환경)"
backend/.venv/bin/python -m pip install -r vision_client/requirements.txt

echo "[4/5] 프론트엔드: npm install"
(cd frontend && npm install)

echo "[5/5] 설정 파일 backend/.env"
if [ -f backend/.env ]; then echo "backend/.env 이미 있음 - 그대로 둠"
else cp backend/.env.example backend/.env && echo "backend/.env 생성 (비밀번호/키 필요하면 수정)"; fi

if command -v mysql >/dev/null; then
  read -r -p "MySQL DB/계정을 만들고 더미 데이터를 넣을까요? (y/n) " ans
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    echo "MySQL root 비밀번호를 입력하세요"
    if mysql -u root -p < backend/sql/schema.sql; then
      (cd backend && .venv/bin/python seed.py --demo)
    else
      echo "[경고] DB 생성 실패 - MySQL 실행 여부와 root 비밀번호 확인"
    fi
  fi
else
  echo "[안내] mysql 명령이 없어 DB 설정은 건너뜀. backend/sql/schema.sql 실행 후 (cd backend && .venv/bin/python seed.py --demo)"
fi

echo
echo "설치 완료.  실행: bash start.sh   테스트: bash test.sh   로그인: admin / admin1234"
