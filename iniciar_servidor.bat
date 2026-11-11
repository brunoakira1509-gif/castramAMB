@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual .venv nao encontrado.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import waitress" 2>nul || ".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" serve.py
pause
