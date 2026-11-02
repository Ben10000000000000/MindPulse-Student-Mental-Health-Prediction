@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" if not exist "venv\Scripts\python.exe" (
  echo Python environment not found. Run: python -m venv .venv
  echo Then run: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=venv\Scripts\python.exe)
%PY% -m uvicorn api.main:app --reload
endlocal
