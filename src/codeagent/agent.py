"""The agent loop: model -> tool calls -> tool results -> model ... -> finish.

Mechanisms borrowed from Claude Code's design:
- a single tool-use loop, where the model decides what to do next;
- TodoWrite-style planning, so progress is visible and the model stays on track;
- a "stop hook": `finish` is rejected while static checks still find blocking issues;
- micro-compaction: old, bulky tool payloads are elided once the context grows;
- graceful handling of malformed or truncated tool calls (the error goes back to the model).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import prompts
from .llm import Cancelled, LLMResponse
from .tools import META_DIR, TOOL_SCHEMAS, ToolError, Workspace, check_project, collect_project_issues, run_tool


class ChatModel(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse: ...


@dataclass
class Event:
    kind: str          # status|assistant|thinking|tool_call|tool_result|todos|usage|warning|error|done
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    success: bool
    summary: str
    turns: int
    stop_reason: str
    usage: dict[str, int]
    files: list[str]
    elapsed_s: float


ELIDED = "[elided by context compaction - use read_file / read_spec to inspect again]"


class CodeAgent:
    def __init__(
        self,
        llm: ChatModel,
        workspace: Workspace,
        max_turns: int = 120,
        on_event: Callable[[Event], None] | None = None,
        cancel_event: threading.Event | None = None,
        compact_threshold_chars: int = 80_000,
        keep_recent_messages: int = 8,
        max_finish_rejections: int = 1,
        max_idle_nudges: int = 3,
    ):
        self.llm = llm
        self.ws = workspace
        self.max_turns = max_turns
        self.on_event = on_event or (lambda e: None)
        self.cancel_event = cancel_event or threading.Event()
        self.compact_threshold_chars = compact_threshold_chars
        self.keep_recent_messages = keep_recent_messages
        self.max_finish_rejections = max_finish_rejections
        self.max_idle_nudges = max_idle_nudges
        self.messages: list[dict[str, Any]] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "requests": 0}
        self._meta = self.ws.root / META_DIR
        self._meta.mkdir(exist_ok=True)
        self._transcript = self._meta / "transcript.jsonl"

    # ------------------------------------------------------------------ utils
    def _emit(self, kind: str, message: str = "", **data: Any) -> None:
        try:
            self.on_event(Event(kind, message, data))
        except Exception:  # a UI bug must never kill the agent
            pass

    def _append(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)
        with open(self._transcript, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def _track_usage(self, usage: dict[str, Any]) -> None:
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.usage["cache_hit_tokens"] += int(usage.get("prompt_cache_hit_tokens") or 0)
        self._emit("usage", "", **self.usage)

    # ------------------------------------------------------------- compaction
    def context_chars(self) -> int:
        return sum(len(json.dumps(m, ensure_ascii=False)) for m in self.messages)

    def compact(self) -> int:
        """Elide bulky payloads in older messages. Returns the number of characters saved.

        The system prompt, the task message and ``reasoning_content`` are left
        untouched (DeepSeek requires reasoning to be passed back verbatim).
        """
        before = self.context_chars()
        cutoff = len(self.messages) - self.keep_recent_messages
        for msg in self.messages[2:max(2, cutoff)]:
            if msg["role"] == "tool" and len(msg.get("content", "")) > 400 and ELIDED not in msg["content"]:
                msg["content"] = msg["content"][:200] + "\n" + ELIDED
            elif msg["role"] == "assistant":
                for tc in msg.get("tool_calls") or []:
                    fn = tc["function"]
                    if fn["name"] not in ("write_file", "edit_file") or len(fn["arguments"]) < 400:
                        continue
                    try:
                        args = json.loads(fn["arguments"])
                    except ValueError:
                        fn["arguments"] = json.dumps({"note": ELIDED})
                        continue
                    for key in ("content", "old_string", "new_string"):
                        if isinstance(args.get(key), str) and len(args[key]) > 200:
                            args[key] = f"<{len(args[key])} chars, already applied on disk> {ELIDED}"
                    fn["arguments"] = json.dumps(args, ensure_ascii=False)
        return before - self.context_chars()

    # ------------------------------------------------------------------- tools
    def _handle_call(self, call: dict[str, Any], finish_rejections: int) -> tuple[str, bool, str | None]:
        """Execute one tool call. Returns (result_text, finished, summary)."""
        name = call["function"]["name"]
        raw_args = call["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            self._emit("warning", f"{name}: invalid arguments ({exc})")
            return (f"Error: arguments were not valid JSON ({exc}). If you were writing a large file the output "
                    "was probably truncated - split it into smaller files and try again."), False, None

        self._emit("tool_call", _describe_call(name, args), name=name, args=_short_args(args))

        if name == "finish":
            blocking, warnings, _ = collect_project_issues(self.ws)
            if blocking and finish_rejections < self.max_finish_rejections:
                report = check_project(self.ws)
                self._emit("warning", f"finish rejected: {len(blocking)} blocking issue(s)")
                return prompts.finish_rejected(report), False, None
            summary = str(args.get("summary", "")).strip()
            if blocking:
                summary += "\n\nUnresolved issues:\n" + "\n".join(f"- {b}" for b in blocking)
            return "Finished.", True, summary

        try:
            result = run_tool(self.ws, name, args)
            ok = True
        except ToolError as exc:
            result, ok = f"Error: {exc}", False
        except Exception as exc:  # unexpected tool crash: report, keep going
            result, ok = f"Error: {type(exc).__name__}: {exc}", False

        if name == "todo_write" and ok:
            self._emit("todos", "", todos=[t.__dict__ for t in self.ws.todos])
        self._emit("tool_result", result if len(result) < 600 else result[:600] + " ...", name=name, ok=ok)
        return result, False, None

    # -------------------------------------------------------------------- run
    def run(self) -> AgentResult:
        start = time.monotonic()
        self.messages = []
        self._transcript.write_text("", encoding="utf-8")
        self._append({"role": "system", "content": prompts.SYSTEM_PROMPT})
        self._append({"role": "user", "content": prompts.initial_task(self.ws.spec)})

        finished, summary, stop_reason = False, "", "max_turns"
        finish_rejections, idle_nudges = 0, 0
        turn = 0
        try:
            for turn in range(1, self.max_turns + 1):
                if self.cancel_event.is_set():
                    raise Cancelled("Cancelled by user.")
                if self.context_chars() > self.compact_threshold_chars:
                    saved = self.compact()
                    self._emit("status", f"Context compacted (saved {saved:,} chars)")

                self._emit("status", f"Turn {turn}/{self.max_turns}: waiting for model...", turn=turn)
                resp = self.llm.chat(self.messages, tools=TOOL_SCHEMAS)
                self._track_usage(resp.usage)
                msg = resp.message
                self._append(msg)
                if msg.get("reasoning_content"):
                    self._emit("thinking", msg["reasoning_content"])
                if msg.get("content"):
                    self._emit("assistant", msg["content"])

                calls = msg.get("tool_calls") or []
                if not calls:
                    if resp.finish_reason == "length":
                        self._append({"role": "user", "content": "Your output was cut off by the length limit. "
                                      "Continue using tools, writing smaller files."})
                        continue
                    idle_nudges += 1
                    if idle_nudges > self.max_idle_nudges:
                        stop_reason = "model_stopped"
                        break
                    self._append({"role": "user", "content": prompts.CONTINUE_NUDGE})
                    continue
                idle_nudges = 0

                for call in calls:
                    if finished:
                        result = "Skipped: finish was already called."
                    else:
                        result, finished, maybe_summary = self._handle_call(call, finish_rejections)
                        if call["function"]["name"] == "finish" and not finished:
                            finish_rejections += 1
                        if finished:
                            summary = maybe_summary or ""
                    self._append({"role": "tool", "tool_call_id": call["id"], "content": result})
                if finished:
                    stop_reason = "finished"
                    break
                if getattr(self.llm, "provider", "") == "gemini":
                    self.cancel_event.wait(2.0)
        except Cancelled:
            stop_reason = "cancelled"
            self._emit("warning", "Run cancelled by user.")

        files = sorted(self.ws.files_written)
        blocking, _, _ = collect_project_issues(self.ws)
        result = AgentResult(
            success=finished and not blocking,
            summary=summary or f"Stopped ({stop_reason}) after {turn} turns.",
            turns=turn,
            stop_reason=stop_reason,
            usage=dict(self.usage),
            files=files,
            elapsed_s=round(time.monotonic() - start, 1),
        )
        (self._meta / "run_result.json").write_text(json.dumps(result.__dict__, indent=2), encoding="utf-8")
        self._emit("done", result.summary, **result.__dict__)
        return result


def _short_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if not isinstance(v, str) or len(v) <= 120 else f"<{len(v)} chars>") for k, v in args.items()
            if k != "todos"}


def _describe_call(name: str, args: dict[str, Any]) -> str:
    if name in ("write_file", "edit_file", "read_file"):
        return f"{name} {args.get('path', '?')}"
    if name == "todo_write":
        todos = args.get("todos") or []
        done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return f"todo_write ({done}/{len(todos)} done)"
    if name == "read_spec":
        return f"read_spec {args.get('section', '')}"
    if name == "search_files":
        return f"search_files /{args.get('pattern', '')}/"
    return name


def ensure_dir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p
