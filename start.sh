#!/usr/bin/env bash
# ============================================================
#  VisionQC AI MES - 백엔드 + 프론트엔드 실행 (Mac / Linux)
#  실행: bash start.sh      종료: Ctrl+C (둘 다 같이 꺼짐)
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"
[ -x backend/.venv/bin/python ] && [ -d frontend/node_modules ] || { echo "[오류] 먼저 bash install.sh"; exit 1; }

(cd backend && exec .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
BACK=$!
(cd frontend && exec npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM

echo "화면: http://localhost:5173 (admin / admin1234)   API 문서: http://localhost:8000/docs"
wait
