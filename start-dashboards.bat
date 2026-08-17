@echo off
setlocal

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo Starting backend (FastAPI)...
start "Dashboards Backend" cmd /k "cd /d "%PROJECT_DIR%" && call .venv\Scripts\activate.bat && uvicorn main:app --reload --port 4100"

echo Starting frontend (Vite)...
start "Dashboards Frontend" cmd /k "cd /d "%PROJECT_DIR%dashboards-frontend" && npm run dev"

echo Waiting for servers to start...
timeout /t 6 /nobreak >nul

echo Opening browser...
start http://localhost:4099/analytics

endlocal
