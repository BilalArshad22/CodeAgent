@echo off
setlocal
cd /d "%~dp0"

if not exist .venv-build (
    python -m venv .venv-build || goto :error
)
call .venv-build\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :error

echo Running tests...
python -m pytest -q || goto :error

echo Building backend...
pyinstaller --noconfirm --clean --onefile --console ^
    --name codeagent-backend ^
    --paths src ^
    --add-data "src\codeagent\samples;codeagent\samples" ^
    launcher.py || goto :error

echo Building Electron app...
cd desktop
call npm ci || goto :error
call npm run dist:win || goto :error

echo.
echo Done: desktop\release\CodeAgent.exe
exit /b 0

:error
echo Build failed.
exit /b 1
