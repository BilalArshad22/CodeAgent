"""System prompt and initial task message."""

from __future__ import annotations

import json
from typing import Any

from .coverage import coverage_checklist

SYSTEM_PROMPT = """\
You are CodeAgent, an autonomous senior software engineer. You turn an architecture \
specification into a complete, runnable software project, writing every file yourself \
through the provided tools. There is no human in the loop until you call `finish`.

# Environment
- All file paths are relative to the project root (the output directory). Use forward slashes.
- You cannot execute commands. Use `check_project` for static validation instead, and \
write code carefully enough that it runs first time.
- The `.codeagent/` folder belongs to the agent itself; never write there.

# Workflow
1. Understand: study the spec in the first message (call `read_spec` for detail you need later). \
Decide how to resolve every item in `spec_issues`, and record those decisions in the README.
2. Plan: call `todo_write` with a concise, ordered plan of 5-8 milestones (e.g. Domain & State Machine, \
Storage & Services, API & Routes, UI & Frontend, Tests & Packaging). Avoid overly granular plans that inflate turn count.
3. Build: for each milestone mark it `in_progress`, write the files, then mark it `completed`. \
Batch related file writes within the same turn to save tokens and minimize round trips.
4. Verify: call `check_project`, fix every BLOCKING issue (and placeholders), then re-check.
5. Call `finish` with a short summary.

# Engineering rules
- Follow the spec's recommended stack and architecture (components, APIs, data schema, \
state machine, scenarios). Map each class, use case, state transition and sequence \
scenario to concrete code.
- The project must run locally with minimal setup. Put heavy infrastructure the spec \
demands (databases, caches, brokers, search) behind small interfaces that default to an \
in-memory implementation, with the real adapter selected by environment variables. Provide \
docker-compose for the full stack.
- Write complete, production-quality code. Never write placeholders such as "TODO", \
"implement later" or "... rest of code".
- Keep files focused and under about 300 lines; split modules rather than writing giant files.
- Every relative import must point to a file you actually create.
- Implement real behaviour, not stubs: domain classes hold the logic (scoring, answer checking, \
state transitions that reject invalid moves); routes and handlers stay thin and call into them.
- Target platform & user interface: Use Electron.js to launch the game inside a native desktop window:
  * Double-clicking `SpaceFractions.exe` opens the game directly in its own native desktop window.
  * No separate browser is needed. Do NOT build an Express HTTP web server or public/ browser UI.
  * The application and its required runtime are packaged together so a standalone Windows executable (.exe) is produced in the output directory.
- Runnable entry point: Ensure the project has `main.js` (for Electron) that creates a native BrowserWindow, initializes all components, and loads the game window (`index.html`). Provide `preload.js` as context bridge.
- Real behaviour: Domain classes (Game, Question, User, Admin) hold the genuine logic (scoring, answer checking, question updates); state machine transitions: Playing -> Paused (via pause()), Paused -> Playing (via resume()), Playing -> GameOver (via gameOver()), and explicit rejection of invalid moves.
- Tests: Must be runnable with `npm test` (using `node --test`). Cover the domain logic, all use cases ('Play Game', 'View Score', 'Update Questions', 'View Help'), and state machine transitions.
- Deliverables: Keep the project focused, complete, and token-efficient (aim for 6-8 files total):
  1. main.js (Electron main process creating BrowserWindow)
  2. preload.js (Context bridge)
  3. index.html / renderer.js / style.css (Desktop window UI with Play Game, questions, answers, score, pause/resume, help, update questions)
  4. src/domain/ (Game, Question, User, Admin domain classes)
  5. tests/game.test.js (Automated test cases)
  6. package.json (Manifest with `"main": "main.js"`, `"scripts": {"start": "electron .", "test": "node --test"}`)
  7. build_exe.bat (Packaging script to bundle app and runtime into SpaceFractions.exe)
  8. README.md (Instructions on double-clicking SpaceFractions.exe and running tests)
- Token efficiency & cost control: Be strictly economical with tokens to avoid wastage. Plan 4-5 milestones in `todo_write`. Batch related file writes within single turns to minimize round trips. Finish the entire project in 6-10 turns. Never write binary bytes via `write_file`. Do not create unnecessary artifacts (no Kubernetes, Dockerfile, docker-compose, OpenAPI, proto, or SQL DDL).
"""


def _extract_spec_text(spec: dict[str, Any]) -> str:
    """Collect lowercase text fragments from spec summary, documents, and inputs."""
    parts: list[str] = []

    summary = spec.get("summary") or {}
    for key in ("recommended_stack", "deployment_nodes", "deliverables"):
        for item in summary.get(key) or []:
            if isinstance(item, str):
                parts.append(item)
    for comp in summary.get("documented_components") or []:
        if isinstance(comp, dict):
            parts.extend(str(v) for v in comp.values() if v)
    for req in summary.get("requirements") or []:
        if isinstance(req, dict):
            parts.extend(str(v) for v in req.values() if v)

    def _collect_sections(sec: dict[str, Any]) -> None:
        if sec.get("heading"):
            parts.append(sec["heading"])
        parts.extend(sec.get("paragraphs") or [])
        parts.extend(sec.get("bullets") or [])
        for table in sec.get("tables") or []:
            for row in table.get("rows") or []:
                if isinstance(row, dict):
                    parts.extend(str(v) for v in row.values() if v)
        for sub in sec.get("subsections") or []:
            _collect_sections(sub)

    for doc in spec.get("documents") or []:
        if isinstance(doc, dict):
            if "structure" in doc and isinstance(doc["structure"], dict):
                _collect_sections(doc["structure"])
            if "text" in doc and isinstance(doc["text"], str):
                parts.append(doc["text"])

    for other in spec.get("other_inputs") or []:
        if isinstance(other, dict) and "text" in other and isinstance(other["text"], str):
            parts.append(other["text"])

    meta = spec.get("meta") or {}
    for inp in meta.get("inputs") or []:
        if isinstance(inp, str):
            parts.append(inp)

    return " ".join(parts).lower()


def detect_app_type(spec: dict[str, Any] | None) -> str:
    """Detect application platform type. Desktop Electron application is default."""
    if not spec:
        return "desktop"
    text = _extract_spec_text(spec)
    if not text:
        return "desktop"
    if any(k in text for k in ("desktop", "electron", ".exe", "windows client", "gui", "standalone")):
        return "desktop"
    return "desktop"


def get_required_deliverables(spec: dict[str, Any] | None = None) -> list[str]:
    """Return required deliverables for the standalone Electron.js desktop application."""
    return [
        "Project directory layout and full source code",
        "Standalone Windows executable packaging (SpaceFractions.exe with bundled Electron runtime launched in native window, main.js, preload.js, and build_exe.bat)",
        "Dependency manifest (package.json)",
        "README.md (including instructions on double-clicking SpaceFractions.exe and running tests)",
        "Automated test cases (covering all use cases and state transitions)",
    ]


REQUIRED_DELIVERABLES = get_required_deliverables(None)


def initial_task(spec: dict[str, Any]) -> str:
    deliverables = "\n".join(f"- {d}" for d in get_required_deliverables(spec))
    spec_deliverables = spec.get("summary", {}).get("deliverables") or []
    extra = ("\n\nThe architecture documentation also lists these artifacts, which you must produce:\n"
             + "\n".join(f"- {d}" for d in spec_deliverables)) if spec_deliverables else ""
    issues = spec.get("spec_issues") or []
    issue_text = "\n".join(f"- {i}" for i in issues) if issues else "- none detected"
    checklist = coverage_checklist(spec)
    coverage = ("\n## Spec coverage checklist (enforced: `finish` is rejected until every item is implemented "
                "and tested; stubs do not count)\n" + checklist + "\n") if checklist else ""

    platform_guidance = (
        "\n## Target platform: Standalone Desktop Application with Electron.js (.exe)\n"
        "Use Electron.js to launch the game inside a native desktop window:\n"
        "- Double-click `SpaceFractions.exe`: the game opens directly in its own native desktop window.\n"
        "- No separate browser is needed (do NOT create an Express server or public/ browser UI).\n"
        "- You can package the app and its required runtime together into `SpaceFractions.exe` via `build_exe.bat`.\n"
        "- Implement domain classes (Game, Question, User, Admin) with real behaviour matching the specification.\n"
        "- Implement state machine: Playing -> Paused (via pause()), Paused -> Playing (via resume()), "
        "Playing -> GameOver (via gameOver()), and explicit rejection of invalid state transitions.\n"
        "- Implement automated tests covering all use cases: 'Play Game', 'View Score', 'Update Questions', 'View Help'.\n"
        "- Keep the project modular, token-efficient, and concise (aim for 6-8 files total). Batch file writes and complete in under 10 turns.\n"
    )

    return f"""\
Build the complete software project described by the architecture specification below.

## Required deliverables
{deliverables}{extra}
{platform_guidance}
## Detected spec issues (resolve each one deliberately and document the decision)
{issue_text}
{coverage}
## Preprocessed specification (JSON)
```json
{json.dumps(spec, ensure_ascii=False, separators=(",", ":"))}
```

Start by calling `todo_write` with your plan."""


CONTINUE_NUDGE = (
    "You have not called `finish`. Continue working with the tools: carry on with the next "
    "pending todo, or run `check_project` and call `finish` if everything is done."
)



def finish_rejected(report: str) -> str:
    return ("`finish` rejected: the project still has blocking issues. Fix them, run "
            "`check_project` again, and then call `finish`.\n\n" + report)
