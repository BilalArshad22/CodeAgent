# 🤖 CodeAgent

<div align="center">

[![DeepSeek V4 Pro](https://img.shields.io/badge/Model-DeepSeek%20V4%20Pro-4A90E2?style=for-the-badge&logo=deepseek&logoColor=white)](https://api.deepseek.com)
[![Electron](https://img.shields.io/badge/Desktop-Electron%20%2B%20React-47848F?style=for-the-badge&logo=electron&logoColor=white)](https://electronjs.org)
[![Python](https://img.shields.io/badge/Backend-Python%203.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-0078D6?style=for-the-badge&logo=windows&logoColor=white)](#building-the-application)
[![Build Status](https://img.shields.io/badge/Build-Passing-2ea44f?style=for-the-badge&logo=githubactions&logoColor=white)](#github-actions-cicd)
[![License](https://img.shields.io/badge/License-MIT-orange?style=for-the-badge)](#license)

**An autonomous, Claude Code-inspired coding agent packaged as a single standalone desktop executable.**  
*Reads software architecture documents & PlantUML diagrams and synthesizes complete, tested, containerized software projects.*

[Key Features](#-key-features) •
[Architecture](#-architecture) •
[Quick Start](#-quick-start) •
[Claude Code Alignment](#-claude-code-alignment) •
[Building from Source](#-building--packaging) •
[CLI & Headless](#-cli--headless-usage)

<br/>

[![Download Latest CodeAgent.exe](https://img.shields.io/badge/⬇%20Download-Latest%20CodeAgent.exe%20(Windows)-2ea44f?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/BilalArshad22/CodeAgent/releases/latest/download/CodeAgent.exe)

*(Double-click to run — No installation or Python required)*

</div>

---

> [!TIP]
> **To run the application immediately:** Click the green **[Download Latest CodeAgent.exe](https://github.com/BilalArshad22/CodeAgent/releases/latest/download/CodeAgent.exe)** button above or grab it from the [Latest Release](https://github.com/BilalArshad22/CodeAgent/releases/latest) page. If you downloaded the repository as a ZIP using GitHub's green `<> Code` button, please note that GitHub excludes Git LFS binaries (>100 MB) from archive downloads; use the direct release download link instead.

---

## 🌟 Overview

**CodeAgent** is an autonomous AI software engineer packaged as a portable Windows desktop application (`CodeAgent.exe`, requiring zero Python installation on the target machine). Inspired by the architecture and ergonomics of **Claude Code**, CodeAgent consumes formal software architecture specifications and drives **DeepSeek V4 Pro** (`deepseek-v4-pro`) through a multi-turn, tool-assisted agent loop to synthesize a complete, production-ready codebase.

Given:
1. **`Architecture_Documentation.md`**: Textual requirements, functional/non-functional specifications, technology choices, and component responsibilities.
2. **`Architecture_View.md`**: Multi-view PlantUML diagrams (Class, State Machine, Sequence, Use Case, Activity, Component, and Deployment).

CodeAgent automatically plans, writes, verifies, and packages:
- 📁 **Clean Source Code & Architecture**: Complete, idiomatic implementation conforming to the specified design patterns.
- 📦 **Dependency Manifests**: Valid `package.json`, `requirements.txt`, or relevant package managers.
- 🐳 **Containerization**: Optimized `Dockerfile` ready for deployment.
- 🧪 **Automated Test Suite**: Unit, integration, and scenario tests validating functional requirements.
- 📑 **Artifacts & Documentation**: Project `README.md`, OpenAPI REST specifications, database DDL schemas (`.sql`), and traceability records.

---

## 🚀 Key Features

- **🧠 DeepSeek V4 Pro Engine with Native Thinking Mode**  
  Uses DeepSeek's official reasoning API (`deepseek-v4-pro`). Full `reasoning_content` is captured, streamed live in the UI as collapsible thought blocks, and round-tripped verbatim across turns to maintain reasoning chain integrity.
- **🎨 Claude Code-Style Desktop UI**  
  Built with Electron and React. Features a dark terminal canvas, real-time tool execution logs, live interactive todo/plan cards, token telemetry, and live cost calculation.
- **📐 Intelligent Preprocessing & Inconsistency Detector**  
  Transforms unstructured Markdown into hierarchical section trees and parses PlantUML diagrams into typed AST entities. Automatically detects and alerts on cross-document inconsistencies (`spec_issues`) before code generation begins.
- **🛡️ Hardened Sandbox File Operations**  
  All filesystem interactions (`read_file`, `write_file`, `edit_file`, `list_files`, `search_files`) are strictly sandboxed inside the user-selected output directory. Path traversals, absolute escapes, and `.codeagent` metadata access are blocked. No arbitrary shell execution is permitted.
- **🚦 Strict Spec-Coverage Gate (`coverage.py`)**  
  The agent cannot simply call `finish` to exit. The built-in coverage gate verifies that all specification classes, methods, state machine transitions, use cases, sequence steps, and test suites are fully implemented.
- **🔍 Deep Static Code Analysis (`check_project`)**  
  Built-in validators check AST syntax (Python), JSON validity, `node --check` syntax, brace balancing, relative import resolution, package.json integrity, and scans for leftover TODOs/stubs before allowing completion.
- **⚡ Micro-Compaction of Context**  
  When conversation history approaches token thresholds (~600k characters), CodeAgent intelligently elides obsolete tool outputs and redundant file writes while preserving reasoning chains and disk contents.
- **📦 Zero-Dependency Windows Binary**  
  PyInstaller bundles the Python backend into a single hidden executable, packaged inside an Electron portable shell. Double-click and run immediately.

---

## 🏛️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Desktop Shell (Electron)                         │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        React Frontend (Vite)                        │   │
│   │  • Config Sidebar (API Keys, Inputs, Output, Model Settings)        │   │
│   │  • Live Agentic Transcript (Assistant text, Tool calls, Thinking)   │   │
│   │  • Interactive Plan Panel (Todos, Progress bar, Status indicators)  │   │
│   │  • Live Telemetry (Turn counter, Token usage, Real-time cost USD)   │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │ stdin / stdout (JSON-Lines RPC)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    Python Core Backend (codeagent-backend)                   │
│                                                                             │
│   ┌───────────────────────────┐         ┌───────────────────────────────┐   │
│   │    IPC Bridge             │         │   Input Preprocessor          │   │
│   │    bridge.py              │         │   preprocess.py               │   │
│   │    • JSON-RPC Protocol    │         │   • Markdown -> Section Tree  │   │
│   │    • Event Dispatcher     │         │   • PlantUML -> Typed AST     │   │
│   │    • Thread Management    │         │   • Spec Inconsistency Check  │   │
│   └─────────────┬─────────────┘         └──────────────┬────────────────┘   │
│                 │                                      │                    │
│                 ▼                                      ▼                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                   Autonomous Agent Loop (agent.py)                  │   │
│   │  • Context Assembly & Micro-Compaction                              │   │
│   │  • Verbatim Thinking Maintenance (reasoning_content preservation)   │   │
│   │  • Multi-Turn Error Recovery & Self-Healing                         │   │
│   └───────────────────┬───────────────────────────────▲─────────────────┘   │
│                       │                               │                     │
│                       ▼                               │                     │
│   ┌────────────────────────────────────────┐  ┌───────┴─────────────────┐   │
│   │         Sandboxed Tool Suite           │  │   Quality & Finish Gate │   │
│   │  • todo_write (dynamic planning)       │  │   coverage.py & tools.py│   │
│   │  • read_file / write_file / edit_file  │  │   • Spec Coverage Check │   │
│   │  • list_files / search_files           │  │   • Static AST & Node   │   │
│   │  • read_spec (structured queries)      │  │   • Import Resolution   │   │
│   └───────────────────┬────────────────────┘  └─────────────────────────┘   │
└───────────────────────┼─────────────────────────────────────────────────────┘
                        │ HTTPS (Official API)
┌───────────────────────▼─────────────────────────────────────────────────────┐
│                 DeepSeek V4 Pro Engine (api.deepseek.com)                   │
│               deepseek-v4-pro (Thinking Mode & Tool Calling)                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Claude Code Alignment

CodeAgent directly implements the core architectural patterns pioneered by **Claude Code**:

| Claude Code Mechanism | CodeAgent Implementation | Technical Details |
| :--- | :--- | :--- |
| **Autonomous Tool Loop** | `agent.py` (`CodeAgent.run()`) | Dispatches tool calls, captures results, updates conversation context, and loops until requirements are met. |
| **Visible Todo Planning** | `todo_write` tool | Maintains dynamic tasks (`pending`, `in_progress`, `completed`). Rendered both inline and in the sticky Plan panel. |
| **Safe File Operations** | `tools.py` | Line-numbered paged reading (`read_file`), atomic writes (`write_file`), and deterministic unique block edits (`edit_file`). |
| **Strict Permission Sandbox** | Sandboxed Execution | Paths are strictly canonicalized within the target output directory. Absolute paths, `..` escapes, and `.codeagent` writes are rejected. No shell execution. |
| **Verification Stop Hooks** | `coverage.py` & `check_project` | Model `finish` calls are **rejected** if classes, methods, state transitions, or tests fail the coverage rubric. |
| **Static Build Checks** | `check_project` tool | Verifies syntax, JSON structures, `node --check` parsing, unresolved relative imports, and presence of mandatory deliverables. |
| **Context Micro-Compaction** | `agent.py` (`_compact()`) | Compresses stale tool outputs and bulky file payloads when context exceeds ~600k chars while keeping thoughts and files intact. |
| **Self-Healing Error Recovery** | Exception-to-Tool Feedback | Truncated inputs, schema mismatches, and validation errors are converted into tool error messages for self-correction. |
| **Deep Reasoning Models** | DeepSeek V4 Pro Thinking | Captures `reasoning_content` and passes it back on subsequent turns to comply with DeepSeek API requirements. |
| **Resilient API Client** | `llm.py` (`DeepSeekClient`) | Handles exponential backoff retries on rate limits (429), server errors (5xx), and network interruptions. |

---

## ⚡ Quick Start

### 1. Download & Launch Standalone App
1. Download the latest `CodeAgent.exe` from **[GitHub Latest Release](https://github.com/BilalArshad22/CodeAgent/releases/latest/download/CodeAgent.exe)** (or view all versions under [Releases](https://github.com/BilalArshad22/CodeAgent/releases)).
2. Double-click **`CodeAgent.exe`** on any 64-bit Windows machine. No Python or Node.js installation is required.

### 2. Configure & Run
1. **API Key**: Enter your DeepSeek API key. Click **Test connection** to verify connectivity with `api.deepseek.com`.
2. **Architecture Inputs**:
   - Click **Add files...** to select your `Architecture_Documentation.md` and `Architecture_View.md`.
   - Alternatively, click **Use samples** to instantly load the bundled "Space Fractions" math quiz game specification.
3. **Output Directory**: Choose an empty folder where your generated software project will be created.
4. **Generate**: Click **Generate project** (or press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>).
5. Watch CodeAgent autonomously plan, implement, verify, and package the complete codebase!

---

## 📦 Generated Deliverables

When the agent finishes, your selected output directory contains the generated project along with an internal `.codeagent/` audit directory:

```
output-directory/
├── src/                         # Complete application source code
│   ├── domain/                  # Core domain models, state machines & logic
│   ├── api/                     # REST API handlers, routing, controllers
│   └── ...                      # Services, middleware, utilities
├── tests/                       # Complete automated test suite
├── sql/                         # Database DDL schemas
├── openapi.yaml                 # REST API specification
├── package.json                 # Project dependencies and test scripts
├── Dockerfile                   # Production container definition
├── README.md                    # Generated project documentation
└── .codeagent/                  # Audit & execution records
    ├── spec.json                # Preprocessed AST & extracted requirements
    ├── transcript.jsonl         # Full multi-turn conversation & thoughts
    └── run_result.json          # Execution metrics, turns, token telemetry
```

---

## 💻 Desktop Interface Tour

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ✻ CodeAgent                     [● DeepSeek · deepseek-v4-pro]                ⚙   │
├──────────────────────┬─────────────────────────────────────────────────────────────┤
│ PROVIDER             │ ╭────────────────────────────────────────────────────────╮  │
│ [DeepSeek (official)▾]│ │ ✻ Welcome to CodeAgent                                 │  │
│                      │ │   Turns an architecture spec into a full project.      │  │
│ API KEY              │ ╰────────────────────────────────────────────────────────╯  │
│ [••••••••••••] 👁 Test│                                                             │
│                      │ ⏺ Thinking... (Click to expand 48s reasoning chain)         │
│ MODEL                │                                                             │
│ [deepseek-v4-pro   ▾]│ ⏺ Update Todos                                             │
│ ☑ Thinking  Turns 120│   ⎿ ☒ Parse architecture spec and resolve inconsistencies  │
│                      │     ☒ Implement core Domain models (Game, Question, User)   │
│ INPUTS          + Add│     ☐ Scaffold Express REST API & OpenAPI schema            │
│ ┌──────────────────┐ │     ☐ Implement State Machine transitions                   │
│ │ 📄 Architecture_…│ │     ☐ Write comprehensive test suites                       │
│ │ 📄 Architecture_…│ │                                                             │
│ └──────────────────┘ │ ⏺ Write(src/domain/game.js)                                │
│ Use samples          │   ⎿ Created src/domain/game.js (124 lines)                 │
│                      │                                                             │
│ OUTPUT               │ ⏺ Check project                                           │
│ [C:/Projects/game 📁]│   ⎿ 0 blocking issues · 2 warnings                         │
│                      │                                                             │
│ ┌──────────────────┐ │ ✻ Composing… (3m 12s · ↑ 52.4k ↓ 7.8k · $0.23 · esc to stop)│
│ │ ▶ Generate  Ctrl↵│ │                                                             │
│ └──────────────────┘ │                                                             │
├──────────────────────┴─────────────────────────────────────────────────────────────┤
│ C:/Projects/game · Turn 28/120 · Plan 6/12 ▰▰▰▰▰▰▱▱▱▱▱▱ · Cache Hit: 78.4%        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

- **Interactive Transcript**: Color-coded execution stream showing agent thoughts, tool execution, and code outputs.
- **Dynamic Plan Widget**: High-level visual checklist updated live as tasks transition from pending to completed.
- **Real-Time Telemetry**: Real-time tracking of turns, elapsed time, input/output tokens, cache hit rates, and estimated API expenditure.
- **Keyboard Shortcuts**:
  - <kbd>Ctrl</kbd> + <kbd>Enter</kbd> (<kbd>Cmd</kbd> + <kbd>Enter</kbd> on macOS): Start generation.
  - <kbd>Esc</kbd>: Gracefully stop generation after current turn.
  - <kbd>Ctrl</kbd> + <kbd>L</kbd>: Clear transcript when idle.

---

## 🧩 PlantUML & Spec Preprocessor

CodeAgent's preprocessor (`preprocess.py`) parses diagrams and architecture text into structured data:

| PlantUML Diagram | Extracted Structured Information |
| :--- | :--- |
| **Class Diagram** | Classes, interfaces, typed fields, methods, return types, access modifiers (`+`, `-`, `#`), and relationships (inheritance, composition, aggregation). |
| **State Machine** | States, initial/final states, transitions, events, guards, and transition actions. |
| **Sequence Diagram** | Participants, message orders, synchronous/asynchronous calls, return messages, activation bars. |
| **Use Case Diagram** | Actors, use case titles, associations, `<<include>>`, and `<<extend>>` linkages. |
| **Activity Diagram** | Execution flows, conditions (`if`/`else`), fork/join parallel branches, and action nodes. |
| **Component Diagram** | Component boundaries, exposed interfaces, consumed dependencies, and port mappings. |
| **Deployment Diagram** | Execution environments, hardware nodes, software artifacts, and network protocols. |

### Inconsistency Detection (`spec_issues`)
Before code generation begins, cross-document inconsistencies between the Markdown text and diagrams are identified. For example:
- Mention of requirements in text missing from the traceability matrix.
- Naming discrepancies in SQL DDL file deliverables.
- Components depicted in diagrams but absent from documentation.

The agent is explicitly instructed to reconcile each detected issue and record the architectural decision.

---

## 💻 CLI & Headless Usage

CodeAgent can be operated directly from the terminal or incorporated into CI/CD pipelines:

### Headless Project Generation
```bash
python -m codeagent run \
  --input docs/Architecture_Documentation.md docs/Architecture_View.md \
  --out ./output/space-fractions \
  --model deepseek-v4-pro \
  --thinking
```

### Standalone Preprocessor
Inspect the structured JSON AST generated from your architecture specification:
```bash
python -m codeagent preprocess \
  --input docs/Architecture_Documentation.md docs/Architecture_View.md \
  --out spec.json
```

### Legacy Tkinter GUI
For testing in minimal environments without Node.js/Electron:
```bash
python -m codeagent gui
```

---

## 🗂️ Project Structure

```
CodeAgent/
├── .github/
│   └── workflows/
│       └── build-windows.yml       # Automated CI: unit tests, PyInstaller, Electron build
├── desktop/                        # Modern Electron desktop application
│   ├── src/                        # React UI (Vite, Tailwind-inspired glassmorphism)
│   │   ├── App.jsx                 # Main layout, transcript, sidebar, telemetry
│   │   ├── main.jsx                # React root mount
│   │   └── index.css               # Styling and animations
│   ├── main.js                     # Electron main process & backend process spawner
│   ├── preload.js                  # Secure IPC context bridge
│   ├── package.json                # Frontend dependencies
│   └── vite.config.js              # Vite bundler configuration
├── src/codeagent/                  # Python agent core (Zero runtime dependencies)
│   ├── agent.py                    # Claude Code-style agentic execution loop
│   ├── bridge.py                   # JSON-lines IPC protocol bridge for Electron
│   ├── cli.py / __main__.py        # Command-line interface entry points
│   ├── config.py                   # Settings dataclass & persistence
│   ├── coverage.py                 # Spec coverage verification gate
│   ├── gui.py                      # Fallback Tkinter interface
│   ├── llm.py                      # Robust DeepSeek & Gemini client (urllib, backoff)
│   ├── preprocess.py               # Markdown section tree & PlantUML AST parser
│   ├── prompts.py                  # System prompts & task directives
│   ├── runner.py                   # End-to-end pipeline coordinator
│   ├── tools.py                    # Sandboxed file tools & check_project static validator
│   └── samples/                    # Bundled sample inputs ("Space Fractions")
│       ├── Architecture_Documentation.md
│       └── Architecture_View.md
├── tests/                          # Comprehensive pytest test suite (Mocked FakeLLM)
│   ├── conftest.py                 # Test fixtures & reference Space Fractions mock
│   ├── test_agent.py               # Agent loop, compaction, and stop hooks
│   ├── test_bridge.py              # IPC bridge protocol validation
│   ├── test_coverage.py            # Spec coverage gate verification
│   ├── test_preprocess.py          # PlantUML & Markdown parser tests
│   └── test_tools.py               # Sandbox safety & static analysis tests
├── build_exe.bat                   # One-shot Windows build script
├── build_mac.sh                    # One-shot macOS build script
├── launcher.py                     # PyInstaller entry point
├── pyproject.toml                  # Python package configuration
├── requirements.txt                # Zero runtime dependencies (Standard Library only)
└── requirements-dev.txt            # Dev dependencies: pytest, pyinstaller
```

---

## 🔨 Building & Packaging

### Windows Portable Executable (`CodeAgent.exe`)

Prerequisites: Python 3.10+ and Node.js 20+ installed on the build machine.

```cmd
build_exe.bat
```

This automated script will:
1. Create a dedicated virtual environment (`.venv-build`).
2. Install testing and build dependencies (`requirements-dev.txt`).
3. Run the full Python test suite (`pytest`).
4. Package the Python backend with PyInstaller (`dist/codeagent-backend.exe`).
5. Compile the React frontend and package the portable Electron executable into:
   ```
   desktop\release\CodeAgent.exe
   ```

### macOS Application Bundle (`CodeAgent.app`)

```bash
chmod +x build_mac.sh
./build_mac.sh
```
Outputs the application bundle to `desktop/release/mac-arm64/CodeAgent.app`.

### GitHub Actions CI/CD

Every commit pushed to GitHub automatically triggers `.github/workflows/build-windows.yml`:
- Sets up Python and Node.js.
- Executes the test suite.
- Builds the PyInstaller backend and runs automated smoke tests.
- Packages the Electron portable executable.
- Uploads `CodeAgent.exe` as a downloadable artifact.

---

## 🧪 Testing

The codebase includes an extensive automated test suite that runs without network access by using a deterministic `FakeLLM`:

```bash
python -m pytest -q
```

Coverage areas include:
- **Preprocessor AST**: Verifies parsing of every PlantUML diagram variant and Markdown section hierarchies.
- **Sandbox Security**: Validates path containment, traversal attempts (`../`), and forbidden directory protection.
- **Agent Loop Mechanics**: Tests tool call sequencing, verbatim reasoning preservation, finish gating, and context micro-compaction.
- **Spec Coverage Gate**: Validates that incomplete implementations are rejected with actionable feedback.
- **Static Analyzer**: Ensures `check_project` detects syntax faults, missing scripts, and unhandled imports.

---

## ⚙️ Configuration & Models

| Setting | Default | Description |
| :--- | :--- | :--- |
| **Provider** | `DeepSeek (official)` | Primary AI provider. Uses `https://api.deepseek.com`. |
| **Model** | `deepseek-v4-pro` | Default frontier reasoning model. (`deepseek-flash` also supported). |
| **Thinking Mode** | `Enabled` | Enables reasoning chain generation. |
| **Max Turns** | `120` | Maximum model interaction turns allowed per generation. |
| **Max Output Tokens** | `32000` | Token limit per individual completion request. |
| **Gemini (Testing)** | `Optional` | Testing provider using Google OpenAI-compatible endpoint to save credits during local development. |

### Token Economics & Cache Hits (DeepSeek Peak Rates)
| Model | Input (Cache Hit) | Input (Cache Miss) | Output |
| :--- | :--- | :--- | :--- |
| `deepseek-v4-pro` | \$0.044 / 1M tokens | \$1.32 / 1M tokens | \$3.96 / 1M tokens |
| `deepseek-flash` | \$0.006 / 1M tokens | \$0.30 / 1M tokens | \$1.20 / 1M tokens |

*CodeAgent tracks cumulative token counts and live cache hits to calculate accurate estimated project generation costs in real time.*

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).