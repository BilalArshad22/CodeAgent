# CodeAgent: a simplified Claude Code-style agent on DeepSeek V4 Pro

CodeAgent is a Windows desktop app (a single `CodeAgent.exe` you double-click; no Python needed). It reads an architecture specification:

- a Markdown architecture document, and
- a Markdown file of PlantUML views (use case, class, object, state, activity, sequence, collaboration, package, component, deployment and container).

It then drives **DeepSeek V4 Pro** (`deepseek-v4-pro`, official API) through an autonomous tool-use loop to write a complete project:

- source code
- a dependency manifest
- a Dockerfile
- a README
- tests
- the spec's own artifacts (OpenAPI, proto, SQL DDL, k8s, traceability CSV)

```
+------------------+     +-------------------+     +--------------------------------------+
|  GUI (tkinter)   |     |  Preprocessor     |     |  Agent loop                          |
|  API key, model  | --> |  Markdown -> tree | --> |  messages -> DeepSeek -> tool_calls  |
|  input files     |     |  PlantUML -> JSON |     |      ^                     |         |
|  output dir, Run |     |  spec_issues      |     |      +---- tool results <--+         |
+------------------+     +-------------------+     |  tools sandboxed to output dir       |
        ^  events (queue)                          |  todo / read / write / edit / search |
        +------------------------------------------|  check_project / finish (gated)      |
                                                   +--------------------------------------+
```

## Using it

1. Double-click **`CodeAgent.exe`**.
2. **DeepSeek API:** paste your API key. **Test connection** checks the key and confirms the model exists. The key is saved in `%APPDATA%\CodeAgent\settings.json` unless you untick *Remember*. `DEEPSEEK_API_KEY` is also honoured.
3. **Input files:** use **Add files…**, or **Use samples** to load the bundled `Architecture_Documentation.md` and `Architecture_View.md`.
4. **Output directory:** pick or type a folder (it is created if missing).
5. Click **Generate project**. While it runs:
   - the log shows every tool call;
   - the *Plan* panel shows the agent's todo list;
   - the progress bar tracks completed todos;
   - token usage (including cache hits) is shown live.

   **Stop** cancels after the current model request returns.

The output folder then holds the generated project, plus a `.codeagent/` folder containing:

| File | Contents |
| --- | --- |
| `spec.json` | the preprocessed structured JSON input |
| `transcript.jsonl` | full conversation with the model, for auditing |
| `run_result.json` | outcome, turns, token usage, files written |

## How it works (mapped to the Claude Code references)

| Claude Code mechanism | CodeAgent implementation |
| --- | --- |
| Single agentic loop: model ↔ tools until done | `agent.py` `CodeAgent.run()`: chat → execute every `tool_call` → append `tool` results → repeat |
| TodoWrite planning and visible progress | `todo_write` tool (one task `in_progress` at a time), rendered in the GUI plan panel |
| Read / Write / Edit / Glob / Grep tools | `read_file` (paged, line numbered), `write_file`, `edit_file` (exact unique match or `replace_all`), `list_files`, `search_files` |
| Permission system / sandbox | Every path resolves inside the output dir. Absolute paths, `..` escapes and `.codeagent/` writes are rejected. No shell tool. |
| Stop hooks (verify before ending) | `finish` is **rejected** while `check_project` reports blocking issues (up to 3 times), and the report goes back to the model |
| Running the build / tests | `check_project`: Python AST parse, JSON parse, `node --check` (falls back to a brace balance check), YAML tab check, unresolved relative imports, `package.json` main/test script, required deliverables, placeholder/TODO scan |
| Auto-compaction of context | Micro-compaction once the context passes about 600k chars: old tool outputs and old `write_file`/`edit_file` payloads are elided (the files stay on disk) |
| Errors fed back, never fatal | Bad or truncated JSON arguments, unknown tools and sandbox violations come back to the model as tool errors. After a `length` cut-off the model is told to write smaller files. |
| Reasoning models | DeepSeek thinking mode is on by default, and `reasoning_content` is kept and sent back verbatim on every request, as DeepSeek's API requires |
| Robust API client | Retries with exponential backoff on 408/409/429/5xx and network errors (honours `Retry-After`). Auth and 400 errors are not retried. The Stop button interrupts retry waits. |

### Input preprocessing (`preprocess.py`)

The task recommends converting the inputs to structured JSON first. CodeAgent does this before the agent starts:

- **Markdown:** becomes a nested section tree with paragraphs, bullets, tables (as row dicts) and fenced code blocks.
- **Facts extracted:**
  - requirements (FR/NFR/ASR) from the traceability matrix
  - component responsibilities and metrics
  - the recommended stack
  - the deliverables list
- **PlantUML:** each diagram is classified by kind and view and parsed into elements, relations and steps:
  - elements: actors, use cases, classes with typed attributes and methods, states, participants, nodes, artifacts, packages
  - relations: composition, association, directed, message/return (in sequence order), state transitions
  - activity steps, including if/else branches
- **Domain summary:** the diagrams are merged into one summary: classes, use cases, state machine, scenarios, packages, components and deployment nodes.
- **`spec_issues`:** cross-document inconsistencies are detected automatically, and the agent must resolve each one and document the decision. For the sample inputs these are:
  - `ASR-2` is referenced but missing from the traceability matrix.
  - The matrix names `sql/question_ddl.sql`, but the deliverables list has `sql/game_ddl.sql`.
  - The testing-strategy matrix is empty.
  - `AdminComponent` appears in the component diagram but is never described.

You can run the preprocessing step on its own:

```bash
python -m codeagent preprocess --input Architecture_Documentation.md Architecture_View.md --out spec.json
```

## Project layout

```
code-agent/
├── launcher.py                  # PyInstaller entry point
├── build_exe.bat                # one-shot Windows build: venv, tests, dist\CodeAgent.exe
├── .github/workflows/build-windows.yml   # CI: test, build exe, smoke-test, upload artifact
├── requirements.txt             # runtime deps: none (stdlib only)
├── requirements-dev.txt         # pytest, pyinstaller
├── pyproject.toml
├── src/codeagent/
│   ├── gui.py                   # tkinter desktop UI
│   ├── cli.py / __main__.py     # gui | run | preprocess subcommands
│   ├── runner.py                # preprocess → agent pipeline (shared by GUI/CLI)
│   ├── agent.py                 # agent loop, finish gate, compaction, events
│   ├── tools.py                 # sandboxed tools + JSON schemas + check_project
│   ├── prompts.py               # system prompt and task message
│   ├── preprocess.py            # Markdown/PlantUML → structured JSON
│   ├── llm.py                   # DeepSeek client (urllib, retries, thinking mode)
│   ├── config.py                # settings persistence
│   └── samples/                 # bundled example inputs
└── tests/                       # 46 pytest tests (scripted fake LLM; no network)
```

## Building the .exe

On any Windows machine with Python 3.10+ from python.org (Python is needed on the build machine only), run:

```bat
build_exe.bat
```

It creates a venv, installs `pytest` and `pyinstaller`, runs the tests, and produces **`dist\CodeAgent.exe`**: a single file with no console window, about 10 MB.

Without a Windows machine, push the repo to GitHub. The `build-windows-exe` workflow builds and smoke-tests the exe on `windows-latest` and uploads it as the `CodeAgent-windows` artifact.

## Running from source / headless

```bash
python -m pip install -e .
python -m codeagent
```

That opens the GUI. To run without it:

```bash
DEEPSEEK_API_KEY=sk-... python -m codeagent run --input Architecture_Documentation.md Architecture_View.md --out ./space-fractions
```

## Tests

```bash
python -m pytest -q
```

The suite covers:

- **Preprocessor:** Markdown structure, every PlantUML diagram kind, package/class name collisions, and the full sample spec including the detected issues.
- **Tools:** sandbox escapes, edit semantics, paging, todo validation and every `check_project` rule.
- **Agent loop:**
  - happy path, with `reasoning_content` passed back
  - every `tool_call` answered
  - finish gating
  - malformed arguments
  - idle nudging, max turns and cancel
  - compaction keeping reasoning and files intact
- **End-to-end pipeline:** run with a scripted fake model.
- **DeepSeek client:** request shape, retry and backoff, auth and 400 handling.
- **Settings and GUI:** settings persistence, plus a GUI smoke test that is skipped when there is no display.

## Settings

| Setting | Default | Notes |
| --- | --- | --- |
| Provider | DeepSeek (official) | *Gemini (testing only)* is for cheap development runs; see below |
| Model | `deepseek-v4-pro` | `deepseek-flash` is cheaper and faster |
| Thinking mode | on | sends `thinking: {type: enabled/disabled}` |
| Max turns | 120 | one turn = one model request |
| Base URL | `https://api.deepseek.com` | |
| Max output tokens / request | 32000 | in `settings.json` |

### Gemini for testing (not for submission)

To save DeepSeek credits while developing, choose **Provider → Gemini (testing only)**. CodeAgent then uses Google's OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai`) with its own saved key. `GEMINI_API_KEY` or `GOOGLE_API_KEY` also work, and on the command line you can pass `--provider gemini`.

- The GUI shows a warning whenever Gemini is selected.
- Provider-specific tool-call data, such as Gemini thought signatures in `extra_content`, is passed back unchanged.
- The assignment requires DeepSeek V4 Pro, so switch back to **DeepSeek / `deepseek-v4-pro`** for the final run and the demo.

## Design decisions and limitations

- **No shell tool.** The model never executes commands: the end user's machine has no guaranteed Node or Python, and command execution from a double-click app is a security risk. `check_project` provides static validation instead. Run `npm install && npm test` in the generated project yourself to verify it.
- **Standard library only.** tkinter and urllib keep the exe small and avoid native-dependency problems with PyInstaller. Windows' certificate store is used for TLS.
- **Overwrites.** The output directory is not cleaned. Files with the same names are overwritten, and the GUI asks before using a non-empty folder.
- **Cost and time.** A full run is typically 30–80 model turns, and thinking mode adds latency. Prompt caching (shown as "cache" in the GUI) cuts the cost of the repeated prefix.
