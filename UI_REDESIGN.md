# CodeAgent UI redesign brief

**Audience:** the AI agent (Antigravity) or developer who will redesign the desktop UI.
**Scope:** `src/codeagent/gui.py` only, plus `tests/test_gui.py` where widget names change. Do **not** change agent, tool, LLM or preprocessing behaviour.
**Read first:** [`AGENTS.md`](AGENTS.md), for the project context and hard constraints.

---

## 1. Problem

The current UI is a stock Tk "clam" form: grey boxes, default fonts, a plain log and a table for the plan. It works, but it looks dated. It also doesn't communicate what the agent is doing, which matters because the app will be **shown in a demo video**.

## 2. Goal and direction

The app should feel like **Claude Code in a desktop window**: a calm dark canvas, a terminal-style transcript of what the agent is doing, a live todo list, and a status line with a spinner, elapsed time and token usage. Setup controls stay out of the way.

Design principles:
1. **The transcript is the hero.** Most of the window shows the agent working, rendered like Claude Code's terminal output.
2. **Setup is quiet.** Provider, key, inputs and output live in a slim left sidebar. They lock (disable) while a run is in progress.
3. **Always show progress.** A spinner, elapsed time, the current step, tokens and estimated cost are visible at all times during a run.
4. **One accent colour.** Claude orange is used only for the primary action, the spinner and active state.
5. **Calm, legible, dense.** Use monospace for the transcript and a system sans-serif for the UI chrome. No gradients and no shadows beyond a hairline border.

## 3. Hard constraints (do not break these)

- **Electron & React:** The UI is an Electron shell wrapping a Python backend, interacting via JSON-lines on stdin/stdout. The visual style follows dark glassmorphic panels and glowing orange accents from the reference images.
- **Packaging stays the same:** the app must still freeze to a single Windows `CodeAgent.exe` with PyInstaller (`--onefile --windowed`) and run on a machine with no Python installed.
- **No GUI work off the main thread.** The agent runs in a worker thread and pushes `("event", Event)` tuples into `self.events`. The UI drains that queue in `_poll()` every 100 ms. Keep that pattern.
- **Keep every feature and setting** (section 7).
- **Tests stay green:** `python -m pytest -q` must pass. You may update `tests/test_gui.py` for renamed widgets, but keep the behaviours it checks:
  - samples load;
  - todos render and drive progress;
  - usage is displayed;
  - tool calls appear in the transcript;
  - switching provider keeps each key separate and shows or hides the warning.
- **Cross-platform:** it must look right on Windows 10/11 (primary target) and macOS (used for previews), with per-OS font fallbacks. Windows DPI awareness is already enabled in `launch()`; keep it.

## 4. Layout

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ✻ CodeAgent                     [● DeepSeek · deepseek-v4-pro]                ⚙   │  header (40px)
├──────────────────────┬─────────────────────────────────────────────────────────────┤
│ PROVIDER             │ ╭────────────────────────────────────────────────────────╮  │
│ [DeepSeek (official)▾]│ │ ✻ Welcome to CodeAgent                                 │  │  welcome card
│ API KEY              │ │   Turns an architecture spec into a full project.      │  │  (empty state only)
│ [••••••••••••] 👁 Test │ │   1. Add your API key  2. Add inputs  3. Generate      │  │
│ MODEL                │ ╰────────────────────────────────────────────────────────╯  │
│ [deepseek-v4-pro   ▾] │                                                             │
│ ☑ Thinking  Turns 120│ ⏺ I'll start by planning the project structure.            │  transcript
│                      │                                                             │
│ INPUTS          + Add│ ⏺ Update Todos                                             │
│ ┌──────────────────┐ │   ⎿ ☒ Parse spec and resolve issues                        │
│ │ 📄 Architecture_…│×│ │     ☐ Domain model (Game, Question, User, Admin)          │
│ │ 📄 Architecture_…│×│ │     ☐ REST API + OpenAPI                                   │
│ └──────────────────┘ │                                                             │
│ Use samples          │ ⏺ Write(src/domain/game.js)                                │
│                      │   ⎿ Created src/domain/game.js (84 lines)                  │
│ OUTPUT               │                                                             │
│ [~/CodeAgent-output…]📁│ ⏺ Check project                                           │
│                      │   ⎿ 0 blocking · 2 warnings                                │
│ ┌──────────────────┐ │                                                             │
│ │ ▶ Generate  ⌘↵   │ │ ✻ Composing… (2m 14s · ↑ 48.2k ↓ 6.1k · $0.21 · esc to stop)│  live status line
│ └──────────────────┘ │                                                             │
├──────────────────────┴─────────────────────────────────────────────────────────────┤
│ ~/CodeAgent-output/space-fractions · Turn 23/120 · Plan 4/12 ▰▰▰▱▱▱▱▱ · cache 71%  │  footer (28px)
└────────────────────────────────────────────────────────────────────────────────────┘
```

- **Window:** default 1180×780, minimum 900×600.
- **Sidebar:** fixed at about 300px and scrollable if the window is short.
- **Transcript:** fills the remaining space.
- **Plan placement:**
  - Render the plan *inline in the transcript* the way Claude Code does, each time `todo_write` fires.
  - Also show the **current** plan in a collapsible "Plan" panel pinned to the top of the transcript area, or as a narrow right column when the window is ≥ 1400px wide. The user should be able to see overall progress without scrolling.
- **Settings (⚙):** base URL, max tokens, "Show model reasoning" and "Remember key" move into a small settings popover or dialog to declutter the sidebar.

## 5. Visual language

### Palette: dark is the default (it suits the video)
| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#1A1915` | window background |
| `surface` | `#262522` | sidebar, cards, inputs |
| `surface-2` | `#30302C` | hover, selected rows |
| `border` | `#3D3C37` | 1px hairlines, input borders |
| `text` | `#ECEAE4` | primary text |
| `text-dim` | `#9B9890` | secondary text, tool results, labels |
| `accent` | `#D97757` | Claude orange: primary button, spinner, focus ring, active todo |
| `accent-hover` | `#E08A6D` | |
| `success` | `#7FB685` | ✓, check passed, completed todos |
| `warning` | `#E5B567` | warnings, "testing only" provider badge |
| `error` | `#E5726A` | errors, failed tool results |
| `info` | `#8AB4F8` | links and file paths in the transcript (optional) |

An optional light theme (`bg #FAF9F5`, `surface #FFFFFF`, `border #E5E3DB`, `text #1F1E1B`, same accent) would be nice to have. Toggle it from the settings dialog.

### Typography
| Role | Windows | macOS | Size |
| --- | --- | --- | --- |
| UI chrome | Segoe UI | SF Pro / `.AppleSystemUIFont`, fall back to Helvetica Neue | 10 pt (13 px) |
| Section labels | same, **bold, ALL CAPS, letter-spaced, `text-dim`** | | 8.5 pt |
| Transcript | Cascadia Mono, falling back to Consolas | SF Mono, falling back to Menlo | 10.5 pt |
| Header title | same as chrome, semibold | | 12 pt |

### Shape and spacing
- 8px spacing grid, 12–16px panel padding, 6px corner radius on inputs and buttons. In plain Tk, imitate rounding with flat widgets and 1px borders; a `Canvas` is fine for the primary button.
- Inputs are flat `surface` with a 1px `border`, and an `accent` border on focus.
- The primary button is filled `accent` with dark text and a 36px height. Secondary buttons are ghost style (text plus a border on hover).

## 6. Transcript rendering: map agent events to Claude Code style

Events arrive in `_handle_event(e: Event)`. `e.kind`, `e.message` and `e.data` are documented in `AGENTS.md`. Tool calls and their results always arrive **in order** (a call, then its result), so pair each result with the most recent call.

| Event | Render as | Colour |
| --- | --- | --- |
| `assistant` | `⏺ <text>`, with wrapped lines indented 2 spaces | `text` |
| `thinking` | Hidden by default. When "Show model reasoning" is on: a collapsed `✻ Thought for Ns` line that expands on click to show the reasoning, italic. | `text-dim` |
| `tool_call` | `⏺ <Verb>(<target>)` with the verb in bold. Verbs: `write_file`→**Write**, `edit_file`→**Update**, `read_file`→**Read**, `list_files`→**List**, `search_files`→**Search**, `read_spec`→**Read spec**, `check_project`→**Check project**, `todo_write`→**Update Todos**, `finish`→**Finish**. The target is `data.args.path`, `pattern` or `section`. | `text`, verb bold, bullet `accent` |
| `tool_result` with `ok=True` | `  ⎿  <first line of result>`, e.g. "Created src/app.js (84 lines)". For `check_project`, a one-line summary ("0 blocking · 2 warnings") that expands on click to the full report. | `text-dim`; green ✓ for a clean check |
| `tool_result` with `ok=False` | `  ⎿  <error>` | `error` |
| `todos` | Under the matching "Update Todos" call: `  ⎿ ☒ done` (dim, strikethrough), `☐ in progress` (bold, `accent`), `☐ pending` (`text`). Also refresh the pinned Plan panel. | see left |
| `status` with "Turn …" | Not printed. Drives the live status line (verb, turn number). | |
| other `status` | `· <text>` | `text-dim` |
| `warning` | `⚠ <text>` | `warning` |
| `error` / crash | `✗ <text>`, plus a non-blocking banner at the top of the transcript | `error` |
| `usage` | Not printed. Updates the status and footer tokens, and the cost. | |
| `done` | A summary card: "✓ Project generated" or "■ Stopped (reason)", turns, time, file count, tokens, cost, and the model's summary. Buttons: **Open folder**, **Open README**, **View spec.json** (in `.codeagent/`). | `success` / `warning` border |

**Live status line** (the last line of the transcript area, shown only while running):
- The spinner glyph cycles through `· ✢ ✳ ✶ ✻ ✽ ✻ ✶ ✳ ✢` about every 120 ms, in `accent`.
- Then a playful gerund that rotates every few seconds ("Planning…", "Composing…", "Scaffolding…", "Wiring…", "Checking…"; pick by the last tool, e.g. after a Write → "Composing…").
- Then dim text: `(elapsed · ↑ in-tokens ↓ out-tokens · $cost · esc to stop)`.

**Cost estimate** comes from cumulative `usage` and is labelled "est.". Prices are USD per 1M tokens at DeepSeek peak rates:

| Model | Input, cache hit | Input, cache miss | Output |
| --- | --- | --- | --- |
| `deepseek-v4-pro` | 0.044 | 1.32 | 3.96 |
| `deepseek-flash` | 0.006 | 0.30 | 1.20 |

Use `cache_hit_tokens` for the hit portion and treat the rest of `prompt_tokens` as misses. For Gemini or an unknown model, show tokens only, with no cost.

The transcript must auto-scroll while the user is at the bottom, and stop auto-scrolling once they scroll up. Add a small "↓ Jump to latest" pill that appears in that case.

## 7. Behaviour to preserve (feature checklist)

- [ ] **Provider dropdown:** "DeepSeek (official)" or "Gemini (testing only)".
  - Switching swaps the API key field (each provider keeps its own key), the model list and the base URL.
  - With Gemini selected, show a **warning badge**: "Testing only — use DeepSeek for the final run". Also put a provider chip in the header, coloured `warning` for Gemini.
- [ ] **API key:** masked entry, show/hide toggle, **Test connection** (async; show the result inline under the field as ✓ or ✗ text, not only in a messagebox), and a Remember option.
- [ ] **Model:** combobox, editable. Plus the **Thinking mode** toggle and **Max turns** spinner.
- [ ] **Inputs:** list with Add (multi-select dialog), remove per item, and **Use samples**. Bonus: drag-and-drop files onto the list if achievable without extra dependencies (on Windows, `tkinterdnd2` is *not* allowed unless bundled correctly; skip if unsure).
- [ ] **Output:** path entry, Browse, Open.
- [ ] **Generate:**
  - Validates the key, inputs and output. Show the problems inline in the sidebar, highlighting the offending fields in `error`.
  - Confirms before using a non-empty folder.
  - Locks the sidebar while running.
- [ ] **Stop:** sets `cancel_event`. The button becomes "Stopping…" until the worker ends. **Esc** also stops.
- [ ] **Keyboard:** Ctrl+Enter (⌘↵ on macOS) to Generate, Esc to Stop, Ctrl+L to clear the transcript (only when idle).
- [ ] Settings persist through `_collect_settings()` and `_save()` (`config.Settings`) when a run starts and when the app closes.
- [ ] Closing during a run asks for confirmation.
- [ ] When a run finishes successfully, offer to open the output folder. Prefer the summary card's buttons to a messagebox.
- [ ] Window title shows elapsed time while running.

## 8. Empty, loading and error states

- **First launch (no key, no inputs):** the welcome card in the transcript area has 3 numbered steps, each showing a check when done. Include a "Try the sample spec" link that calls `use_samples()`.
- **Waiting for the model:** the status line spinner. Never leave the UI looking frozen. Model calls can take 30–120 s with thinking on, so elapsed time must keep ticking.
- **API or network error:** an error line in the transcript, a banner with the message, and the sidebar unlocked again.
- **Cancelled:** the summary card with the "Stopped" state.

## 9. Acceptance criteria

1. `python -m pytest -q` passes.
2. `./build_mac.sh` produces `desktop/release/mac*/CodeAgent.app`, which launches and shows the new UI. On Windows, `build_exe.bat` produces `desktop\release\CodeAgent.exe`.
3. A full mocked run renders as in section 6. Simulate one with the fake LLM in `tests/conftest.py`, or by pushing synthetic `Event`s into `app.events`; consider adding a hidden `--demo` flag that replays a canned event stream for screenshots.
4. No text is clipped at 100%, 125% and 150% Windows scaling, nor at the minimum window size.
5. Contrast: body text is at least 4.5:1 on its background; dim text is at least 3:1.
6. The UI stays responsive (no blocking calls on the Tk thread) throughout a run.

## 10. Out of scope

- Changing the agent loop, tools, prompts, preprocessing or LLM client.
- A chat input box. This is a one-shot generator, not a conversation; the "prompt box" look applies to the Generate area only.
- Web or HTML frontends.

## 11. Known UI issues (found in the first real Gemini run, 2026-10-02)

1. **Plan panel overlaps the transcript.** The "Live Process" todo grid (`maxHeight: 35%`) clips its cards, and transcript lines (e.g. "Finish") slide underneath it. Make the plan panel and the transcript siblings in a flex column, where only the transcript scrolls; or collapse the plan to one summary row with an expand toggle.
2. **Header status is stale after the run.** "Turn N/120: waiting for model…" and its spinner stay visible after `done`. On `done`, set the status to "Completed", "Stopped" or "Failed" and stop the spinner.
3. **"Update Todos → Todo list updated:" is empty.** It only shows the first line of the result. Render the todo diff (☒ / ☐) inline, or hide `todo_write` results because the plan panel already shows them.
4. **Cost badge uses DeepSeek prices for every model.** Show the cost only for `deepseek-*` models; show tokens only for Gemini.
5. **Output path is truncated from the right.** `/Users/mc/Downloads/Task1/output` displays as `…/Task1/out`. Truncate from the left (`direction: rtl` with ellipsis, or a middle ellipsis) and show the full path in a tooltip.
6. **No `--demo` indicator.** A demo replay looks identical to a real run. Show a "DEMO" badge whenever `isDemo()` is true.
