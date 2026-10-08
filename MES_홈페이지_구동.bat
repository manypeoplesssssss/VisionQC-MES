@echo off
chcp 65001 >nul

echo 🔄 기존에 켜져 있던 프로세스 안전하게 종료 중...
taskkill /f /im node.exe 2>nul
taskkill /f /im python.exe 2>nul

cls
echo ===================================================
echo 💻 5조 풀스택 MES 관제 시스템 통합 기동 (가상환경 우회 완벽 연동 버전)
echo ===================================================

echo 🚀 1. 백엔드(FastAPI Uvicorn) 서버 안전 기동 중...
start /min cmd /c "cd /d D:\VisionQC-MES\backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo 🚀 2. 정식 React 웹 상황실 기동 중...
start /min cmd /c "cd /d D:\VisionQC-MES\frontend && npm run dev"

echo 🚀 3. 바탕화면 스트림릿 보조 상황판 기동 중...
start /min cmd /c "cd /d C:\Users\user\Desktop && streamlit run mes_web.py"

echo ===================================================
echo 🎉 모든 시스템(React + Streamlit + FastAPI + MySQL) 연동 완료!
echo ===================================================
echo 🔗 정식 React 웹 상황실         : http://localhost:5173
echo 🔗 바탕화면 스트림릿 보조 상황판 : http://localhost:8501
echo ===================================================
echo ※ 본 창을 닫으려면 아무 키나 누르세요...
pause >nul
