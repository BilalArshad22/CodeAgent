"""Command-line entry points.

    CodeAgent.exe                     -> GUI (default)
    python -m codeagent gui
    python -m codeagent run --input a.md b.md --out ./generated [--model ...]
    python -m codeagent preprocess --input a.md b.md [--out spec.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import Event
from .config import PROVIDERS, load_settings
from .preprocess import build_spec


def _print_event(e: Event) -> None:
    if e.kind == "thinking":
        return
    prefix = {"tool_call": ">>", "tool_result": "  ", "warning": "!!", "error": "!!", "done": "=="}.get(e.kind, "--")
    text = e.message if e.kind != "assistant" else e.message.strip()
    if e.kind == "usage":
        return
    if text:
        print(f"{prefix} {text}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codeagent", description="DeepSeek-powered code generation agent")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="launch the desktop GUI (default)")
    sub.add_parser("bridge", help="run the backend bridge for Electron")

    run = sub.add_parser("run", help="run the agent headless")
    run.add_argument("--input", nargs="+", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--provider", choices=sorted(PROVIDERS), help="deepseek (default) or gemini (testing only)")
    run.add_argument("--model")
    run.add_argument("--base-url")
    run.add_argument("--max-turns", type=int)
    run.add_argument("--no-thinking", action="store_true")

    pre = sub.add_parser("preprocess", help="convert inputs to structured JSON")
    pre.add_argument("--input", nargs="+", required=True)
    pre.add_argument("--out")

    args = parser.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui import launch
        launch()
        return 0

    if args.cmd == "bridge":
        from .bridge import main as bridge_main
        bridge_main()
        return 0

    if args.cmd == "preprocess":
        text = json.dumps(build_spec(args.input), indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(text)
        return 0

    from .runner import run_pipeline
    settings = load_settings()
    settings.input_files = args.input
    settings.output_dir = args.out
    if args.provider and args.provider != settings.provider:
        settings.provider = args.provider
        settings.model = PROVIDERS[args.provider]["models"][0]
        settings.base_url = PROVIDERS[args.provider]["base_url"]
    settings.model = args.model or settings.model
    settings.base_url = args.base_url or settings.base_url or PROVIDERS[settings.provider]["base_url"]
    settings.max_turns = args.max_turns or settings.max_turns
    if args.no_thinking:
        settings.thinking = False
    if not settings.effective_api_key():
        env = PROVIDERS[settings.provider]["env"]
        print(f"No API key: set {env} or save one in the GUI.", file=sys.stderr)
        return 2
    try:
        result = run_pipeline(settings, on_event=_print_event)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.usage))
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
