#!/usr/bin/env bash
# ============================================================
#  VisionQC AI MES - 테스트 실행 (Mac / Linux)
#  bash test.sh                       : 백엔드 + 검사 PC 클라이언트 전체
#  bash test.sh tests/test_ingest.py  : 백엔드 테스트 파일 하나 (인자는 pytest 로 전달)
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"
[ -x backend/.venv/bin/python ] || { echo "[오류] 먼저 bash install.sh"; exit 1; }

if [ $# -gt 0 ]; then
  cd backend && exec .venv/bin/python -m pytest "$@"
fi

echo "===== 백엔드 ====="
(cd backend && .venv/bin/python -m pytest -q); rc1=$?
echo "===== 검사 PC 클라이언트 ====="
(cd inspection/common && ../../backend/.venv/bin/python -m pytest -q); rc2=$?
[ $rc1 -eq 0 ] && [ $rc2 -eq 0 ] && echo "전체 통과" || { echo "실패한 테스트가 있습니다"; exit 1; }
