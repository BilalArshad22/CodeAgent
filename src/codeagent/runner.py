"""End-to-end pipeline shared by GUI and CLI: preprocess -> agent -> report."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

import os
import re
import shutil
import subprocess
import sys

from .agent import AgentResult, ChatModel, CodeAgent, Event, ensure_dir
from .config import Settings
from .llm import DeepSeekClient
from .preprocess import build_spec, compact_spec
from .tools import META_DIR, Workspace


def find_electron_dist() -> Path | None:
    """Locate Electron runtime directory containing electron.exe/CodeAgent.exe and assets."""
    candidates = [
        Path(sys.executable).resolve().parent.parent,
        Path(sys.executable).resolve().parent,
        Path(__file__).resolve().parents[2] / "desktop" / "node_modules" / "electron" / "dist",
        Path(__file__).resolve().parents[2] / "desktop" / "release" / "win-unpacked",
        Path.cwd() / "desktop" / "node_modules" / "electron" / "dist",
        Path.cwd() / "desktop" / "release" / "win-unpacked",
    ]
    for c in candidates:
        if (c / "electron.exe").is_file() or (c / "CodeAgent.exe").is_file():
            return c

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        cache_dir = Path(local_appdata) / "electron" / "Cache"
        if cache_dir.is_dir():
            for zip_file in cache_dir.rglob("electron-*.zip"):
                if zip_file.is_file():
                    target_dir = cache_dir / "dist_extracted"
                    if not (target_dir / "electron.exe").is_file():
                        try:
                            shutil.unpack_archive(str(zip_file), str(target_dir))
                        except Exception:
                            pass
                    if (target_dir / "electron.exe").is_file():
                        return target_dir
    return None


def build_output_exe(output_dir: Path, emit: Callable[[Event], None]) -> Path | None:
    """Ensure a working standalone Windows executable (.exe) exists in output_dir."""
    app_name = "SpaceFractions"
    target_exe = output_dir / f"{app_name}.exe"

    # 1. If SpaceFractions.exe already exists and has substance, return it
    if target_exe.is_file() and target_exe.stat().st_size > 10000:
        return target_exe

    # 2. If build_exe.bat exists, run it first
    bat = output_dir / "build_exe.bat"
    if bat.is_file():
        emit(Event("status", "Running build_exe.bat to generate standalone Windows executable..."))
        try:
            subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(output_dir), input=b"\r\n", check=False, timeout=120)
            if target_exe.is_file() and target_exe.stat().st_size > 10000:
                return target_exe
            for search_dir in (output_dir, output_dir / "dist", output_dir / "release", output_dir / "win-unpacked"):
                if search_dir.is_dir():
                    for f in search_dir.glob("*.exe"):
                        if not f.name.startswith(".") and f.name.lower() != "elevate.exe":
                            if f != target_exe:
                                shutil.copy2(str(f), str(target_exe))
                            return target_exe
        except Exception as exc:
            emit(Event("warning", f"build_exe.bat execution error: {exc}"))

    # 3. Electron desktop application packaging
    is_electron = (output_dir / "main.js").is_file() or (output_dir / "package.json").is_file()
    if is_electron:
        emit(Event("status", f"Packaging {app_name}.exe with bundled Electron runtime for native desktop window..."))
        dist_src = find_electron_dist()
        if dist_src:
            try:
                # Copy Electron runtime files (DLLs, resources, locales, pak files) into output_dir
                for item in dist_src.iterdir():
                    dest = output_dir / item.name
                    if item.is_dir():
                        if item.name == "resources":
                            dest.mkdir(exist_ok=True)
                            for res_child in item.iterdir():
                                if res_child.name != "app" and res_child.name != "app.asar":
                                    res_dest = dest / res_child.name
                                    if not res_dest.exists():
                                        if res_child.is_dir():
                                            shutil.copytree(str(res_child), str(res_dest), dirs_exist_ok=True)
                                        else:
                                            shutil.copy2(str(res_child), str(res_dest))
                        else:
                            if not dest.exists():
                                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                    elif item.is_file():
                        if item.suffix.lower() == ".exe":
                            if not target_exe.exists() or target_exe.stat().st_size < 10000:
                                shutil.copy2(str(item), str(target_exe))
                        else:
                            if not dest.exists():
                                shutil.copy2(str(item), str(dest))

                # Bundle application files into resources/app so Electron executes them natively
                app_dest = output_dir / "resources" / "app"
                app_dest.mkdir(parents=True, exist_ok=True)

                # Remove any inherited app.asar from template dist so Electron uses resources/app
                asar_path = output_dir / "resources" / "app.asar"
                if asar_path.is_file():
                    try:
                        asar_path.unlink()
                    except OSError:
                        pass

                # Copy source files to resources/app
                for f in output_dir.iterdir():
                    if f.name in ("resources", "locales", ".codeagent", "dist", "release", "win-unpacked", "node_modules"):
                        continue
                    if f.name.endswith(".exe"):
                        continue
                    target_item = app_dest / f.name
                    if f.is_dir():
                        shutil.copytree(str(f), str(target_item), dirs_exist_ok=True)
                    elif f.is_file():
                        shutil.copy2(str(f), str(target_item))

                if target_exe.is_file() and target_exe.stat().st_size > 10000:
                    emit(Event("status", f"Standalone executable created: {target_exe.name} (native window)"))
                    return target_exe
            except Exception as exc:
                emit(Event("warning", f"Electron runtime bundling error: {exc}"))

    # 4. Python desktop application packaging (main.py / app.py)
    for py_entry in ("main.py", "app.py", "run.py", "src/main.py", "src/app.py"):
        if (output_dir / py_entry).is_file():
            emit(Event("status", "Packaging Python project into .exe via PyInstaller..."))
            try:
                subprocess.run(
                    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                     "--name", app_name, str(output_dir / py_entry)],
                    cwd=str(output_dir), check=False, timeout=120, capture_output=True
                )
                dist_dir = output_dir / "dist"
                if dist_dir.is_dir():
                    for f in dist_dir.glob("*.exe"):
                        shutil.copy2(str(f), str(target_exe))
                        return target_exe
            except Exception as exc:
                emit(Event("warning", f"PyInstaller packaging error: {exc}"))

    for f in output_dir.glob("*.exe"):
        if not f.name.startswith("."):
            return f
    return None


def run_pipeline(
    settings: Settings,
    on_event: Callable[[Event], None] | None = None,
    cancel_event: threading.Event | None = None,
    llm: ChatModel | None = None,
) -> AgentResult:
    emit = on_event or (lambda e: None)
    cancel_event = cancel_event or threading.Event()

    inputs = [Path(p) for p in settings.input_files]
    if not inputs:
        raise ValueError("Select at least one input file.")
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        raise FileNotFoundError("Input file(s) not found: " + ", ".join(missing))
    if not settings.output_dir:
        raise ValueError("Select an output directory.")

    out = ensure_dir(settings.output_dir)
    emit(Event("status", f"Preprocessing {len(inputs)} input file(s)..."))
    spec = build_spec(inputs)
    meta = out / META_DIR
    meta.mkdir(exist_ok=True)
    (meta / "spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    emit(Event("status", f"Spec: {spec['meta']['diagram_count']} diagrams, "
                         f"{len(spec['summary']['classes'])} classes, {len(spec['spec_issues'])} spec issue(s) "
                         f"-> {meta / 'spec.json'}"))

    if llm is None:
        llm = DeepSeekClient(
            api_key=settings.effective_api_key(),
            model=settings.model,
            base_url=settings.base_url,
            thinking=settings.thinking,
            max_tokens=settings.max_tokens,
            cancel_event=cancel_event,
            provider=settings.provider,
            on_retry=lambda msg: emit(Event("warning", msg)),
        )
    ws = Workspace(out, spec=compact_spec(spec))
    agent = CodeAgent(llm, ws, max_turns=settings.max_turns, on_event=emit, cancel_event=cancel_event)
    result = agent.run()

    # Post-processing: ALWAYS build and verify the standalone executable
    emit(Event("status", "Post-processing: Ensuring standalone Windows executable (.exe)..."))
    exe = build_output_exe(out, emit)
    if exe:
        emit(Event("status", f"Standalone executable verified in output: {exe.name} (ready to launch in native window)"))
        if exe.name not in result.files:
            result.files.append(exe.name)
    return result
