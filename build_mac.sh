#!/usr/bin/env bash
# macOS preview build: Python backend (PyInstaller onefile) + Electron shell -> desktop/release/mac*/CodeAgent.app
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv-build ] || python3 -m venv .venv-build
.venv-build/bin/python -m pip install -q -r requirements-dev.txt
.venv-build/bin/python -m pytest -q

echo "Building Python backend..."
.venv-build/bin/pyinstaller --noconfirm --clean --onefile --console \
    --name codeagent-backend \
    --paths src \
    --add-data "src/codeagent/samples:codeagent/samples" \
    launcher.py

echo "Building Electron app..."
cd desktop
npm ci
npm run dist:mac
echo "Done: $(ls -d release/mac*/CodeAgent.app)"
