# AGENTS.md: project memory for AI coding agents

Read this before changing anything. For UI work, also read [`UI_REDESIGN.md`](UI_REDESIGN.md).

## What this project is

This is an assignment deliverable: a **simplified Claude Code-style coding agent** packaged as a **Windows desktop app**. The deliverable is a double-clickable `CodeAgent.exe` that needs no Python on the target machine.

The user does three things in the app:
1. Configures an API key.
2. Picks input files: `Architecture_Documentation.md` and `Architecture_View.md`, which contains PlantUML.
3. Picks an output directory and clicks Generate.

The agent then writes a complete project into that directory: source code, a manifest, a Dockerfile, a README and tests. For the sample input, that project is "Space Fractions", a fractions quiz game.

### Non-negotiable requirements from the assignment
- **The final model must be DeepSeek V4 Pro (`deepseek-v4-pro`) via the official API** (`https://api.deepseek.com`). No local model weights.
- **Gemini exists only as a testing provider** to save credits during development. The demo video and final runs use DeepSeek. Never make Gemini the default.
- The deliverable is a Windows `.exe`: an Electron shell (`electron-builder` portable target) that bundles the Python backend (PyInstaller `--onefile --console`, run hidden). A browser-based fallback would lose marks, so don't go there.
- Required outputs from the generated project: directory layout and source code, dependency manifest, README, test cases, and a Dockerfile (optional).

## Architecture

```
desktop/
  main.js        Electron main process. Spawns codeagent-backend.
  preload.js     Context bridge (IPC).
  src/           React frontend UI (Vite + React).
src/codeagent/
  bridge.py      JSON-lines IPC bridge connecting Electron to the Python backend.
  runner.py      run_pipeline(settings, on_event, cancel_event, llm=None)
  agent.py       Agent loop (model -> tool calls -> results -> ...). Emits Event(kind, message, data).
  tools.py       Sandboxed tools + check_project static validator.
  coverage.py    Spec coverage gate: spec classes/methods, state transitions, use cases, sequence steps and test count must be implemented and tested before `finish` is accepted.
  prompts.py     System prompt and initial task message.
  preprocess.py  Markdown -> section tree; PlantUML -> typed elements.
  llm.py         DeepSeekClient. provider="deepseek" | "gemini".
  config.py      Settings dataclass.
  cli.py         `codeagent [gui|bridge]`, `codeagent run ...`, `codeagent preprocess ...`
  samples/       Bundled sample inputs.
launcher.py      PyInstaller entry point.
```

### Event contract (agent → UI)
`Event(kind: str, message: str, data: dict)` is emitted from the agent's worker thread. `bridge.py` writes each one to stdout as a JSON line `{"event", "message", "data"}`; Electron forwards it to the renderer, which gets it through `window.api.onEvent`.

**Bridge protocol (JSON lines over stdin/stdout):**
- Requests are `{"id", "method", "params"}`. `main.js` assigns integer ids.
- Responses are `{"id", "result"}` or `{"id", "error"}`. They resolve the renderer's `window.api.invoke(method, params)` promise and are not forwarded as events.
- Methods: `get_settings`, `save_settings`, `list_samples`, `test_connection`, `check_output_dir`, `start_run`, `stop_run`.
- Only protocol JSON may ever be written to stdout; logging goes to stderr.
- The bridge exits when stdin closes.

| kind | message | data |
| --- | --- | --- |
| `status` | e.g. "Turn 3/120: waiting for model...", "Preprocessing…", "Context compacted…" | `turn` on turn events |
| `assistant` | the model's visible text | |
| `thinking` | `reasoning_content` (can be long) | |
| `tool_call` | short description, e.g. "write_file src/app.js" | `name`, `args` (long strings shortened to `<N chars>`) |
| `tool_result` | result text (≤600 chars) | `name`, `ok: bool` |
| `todos` | | `todos: [{id, content, status: pending/in_progress/completed}]` |
| `usage` | | cumulative `requests`, `prompt_tokens`, `completion_tokens`, `cache_hit_tokens` |
| `warning` / `error` | text | |
| `done` | final summary | the `AgentResult` fields: `success`, `summary`, `turns`, `stop_reason` (finished/cancelled/max_turns/model_stopped), `usage`, `files`, `elapsed_s` |

`CodeAgent.run()` emits exactly one `done` event; the bridge must not add another.

## Hard constraints
- **No third-party *Python* runtime dependencies.** `requirements.txt` is intentionally empty (urllib only), which keeps the backend about 10 MB and avoids PyInstaller trouble. Frontend packages live in `desktop/package.json`. If you add one, update `requirements.txt`, `build_exe.bat`, `build_mac.sh` and `.github/workflows/build-windows.yml`, and verify the frozen app launches.
- **Packaged backend:** Electron must start it with the `bridge` argument. With no arguments the CLI opens the legacy tkinter GUI.
- **Provider switch:** must also switch `model` and `base_url`, so one provider's key is never sent to the other's endpoint.
- **Legacy UI:** the tkinter UI (`gui.py`) remains available for development as `codeagent gui`, but it is not shipped.
- **DeepSeek thinking mode:** every assistant message's `reasoning_content` must be sent back verbatim on later requests, or the API returns 400. Context compaction must never strip it. Provider-specific `extra_content` on tool calls (Gemini thought signatures) must also round-trip.
- **Tool sandbox:** all paths resolve inside the output directory, and `.codeagent/` there is reserved for the agent's own metadata (`spec.json`, `transcript.jsonl`, `run_result.json`). There is no shell tool, on purpose.
- **Every assistant `tool_call` must get a matching `role: tool` message** before the next request.
- **Keep bundled resources working when frozen:** `Path(__file__).parent / "samples"` works under PyInstaller because of `--add-data`. Use the same approach for any new assets.

## Commands
```bash
python -m pytest -q
cd desktop && npm run app
cd desktop && npm run demo
./build_mac.sh
open desktop/release/mac-arm64/CodeAgent.app
```

| Command | What it does |
| --- | --- |
| `python -m pytest -q` | Python tests, including the bridge; no network (scripted FakeLLM in `tests/conftest.py`) |
| `cd desktop && npm run app` | run the Electron app from source (spawns `python3 -m codeagent bridge`; set `CODEAGENT_PYTHON` to use another interpreter) |
| `cd desktop && npm run demo` | same, but Generate replays a canned run with no API key |
| `./build_mac.sh` | macOS preview build: tests, onefile backend, then `desktop/release/mac*/CodeAgent.app` |
| `open desktop/release/mac-arm64/CodeAgent.app` | launch the macOS preview build |
| `video/make_video.sh` | record a real run (via the DevTools screencast) and build a narrated demo video: `video/out/CodeAgent-demo.mp4`, plus `.srt` subtitles and a `.txt` script. It uses the provider saved in the app and restores your settings afterwards. Override the narration with `VOICE` and `RATE`. |

On Windows, run `build_exe.bat`: tests, then the backend, then `desktop\release\CodeAgent.exe`, a portable single file. CI builds and smoke-tests the Windows exe on every push (`.github/workflows/build-windows.yml`) and uploads the `CodeAgent-windows` artifact.

## Conventions
- Python 3.10+, type hints, `from __future__ import annotations`, small focused functions. Comments explain *why*, not what.
- Tests live in `tests/`. GUI tests create a withdrawn `tk.Tk()` and skip when there is no display.
- Don't commit `dist/`, `build/`, `.venv-build/`, `desktop/node_modules/`, `desktop/dist/` or `desktop/release/`.

## Current status (2026-10-02)
- **Done and tested** (63 Python tests):
  - the agent loop, tools and preprocessing;
  - the DeepSeek and Gemini (testing) providers;
  - the Python bridge;
  - the spec-coverage finish gate. `tests/conftest.py::SPACE_FRACTIONS_PROJECT` is a reference implementation that passes it, and its own 9 node tests pass.
- **Electron UI:** done. The packaged macOS app was verified end to end through DevTools: UI ↔ backend requests, provider switching, and a clean backend shutdown on quit.
- **Not yet verified:**
  - a live run against the real DeepSeek or Gemini API;
  - an actual Windows exe build. Build on Windows or through CI.
- **Demo video:** recorded with Provider = DeepSeek and model `deepseek-v4-pro`.
