"""Agent tools, all sandboxed to a single workspace directory.

Mirrors the core Claude Code tool set (TodoWrite, Read, Write, Edit, Glob/Grep)
minus shell execution: the target machine has no guaranteed runtime, and
letting a model run arbitrary commands from a double-click app is unsafe.
``check_project`` stands in for "run the build" with static validation.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .coverage import check_coverage

META_DIR = ".codeagent"
MAX_READ_LINES = 400
MAX_LIST_ENTRIES = 400
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", META_DIR}
TEST_PATTERNS = ("test_*.py", "*_test.py", "*.test.js", "*.spec.js", "*.test.ts", "*.spec.ts", "*Test.java")
MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "pom.xml", "go.mod", "Cargo.toml")


class ToolError(Exception):
    """An error reported back to the model as a tool result (not fatal)."""


@dataclass
class Todo:
    id: str
    content: str
    status: str = "pending"


@dataclass
class Workspace:
    root: Path
    spec: dict[str, Any] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    files_written: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------- path safety
    def resolve(self, rel: str, for_write: bool = False) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise ToolError("path must be a non-empty string relative to the project root")
        rel = rel.strip().replace("\\", "/")
        if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
            raise ToolError(f"absolute paths are not allowed: {rel!r}; use a path relative to the project root")
        target = (self.root / rel).resolve()
        try:
            rel_parts = target.relative_to(self.root).parts
        except ValueError:
            raise ToolError(f"path escapes the project root: {rel!r}") from None
        if for_write and rel_parts and rel_parts[0] == META_DIR:
            raise ToolError(f"{META_DIR}/ is reserved for the agent's own metadata")
        return target

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def iter_files(self, base: Path | None = None):
        base = base or self.root
        for p in sorted(base.rglob("*")):
            if any(part in IGNORED_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                yield p


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
def todo_write(ws: Workspace, todos: list[dict]) -> str:
    if not isinstance(todos, list) or not todos:
        raise ToolError("todos must be a non-empty list")
    parsed = []
    for i, t in enumerate(todos):
        status = t.get("status", "pending")
        if status not in ("pending", "in_progress", "completed"):
            raise ToolError(f"invalid status {status!r} (use pending, in_progress or completed)")
        if not t.get("content"):
            raise ToolError(f"todo #{i + 1} has no content")
        parsed.append(Todo(id=str(t.get("id") or i + 1), content=str(t["content"]), status=status))
    if sum(t.status == "in_progress" for t in parsed) > 1:
        raise ToolError("only one todo may be in_progress at a time")
    ws.todos = parsed
    return "Todo list updated:\n" + render_todos(ws.todos)


def render_todos(todos: list[Todo]) -> str:
    mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    return "\n".join(f"{mark[t.status]} {t.id}. {t.content}" for t in todos)


def list_files(ws: Workspace, path: str = ".") -> str:
    base = ws.resolve(path)
    if not base.exists():
        return f"{path} does not exist (the project may still be empty)."
    if base.is_file():
        return f"{ws.rel(base)} ({base.stat().st_size} bytes)"
    entries = [f"{ws.rel(p)} ({p.stat().st_size} bytes)" for p in ws.iter_files(base)]
    if not entries:
        return "(no files yet)"
    more = len(entries) - MAX_LIST_ENTRIES
    return "\n".join(entries[:MAX_LIST_ENTRIES]) + (f"\n... {more} more" if more > 0 else "")


def read_file(ws: Workspace, path: str, offset: int = 1, limit: int = MAX_READ_LINES) -> str:
    target = ws.resolve(path)
    if not target.is_file():
        raise ToolError(f"file not found: {path}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    offset = max(1, int(offset or 1))
    limit = max(1, min(int(limit or MAX_READ_LINES), 2000))
    chunk = lines[offset - 1: offset - 1 + limit]
    body = "\n".join(f"{n:>5}\t{line}" for n, line in enumerate(chunk, start=offset))
    tail = ""
    if offset - 1 + limit < len(lines):
        tail = f"\n... ({len(lines) - (offset - 1 + limit)} more lines; call again with offset={offset + limit})"
    return (body or "(empty file)") + tail


def write_file(ws: Workspace, path: str, content: str) -> str:
    if not isinstance(content, str):
        raise ToolError("content must be a string")
    target = ws.resolve(path, for_write=True)
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    rel = ws.rel(target)
    ws.files_written[rel] = len(content)
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"{'Overwrote' if existed else 'Created'} {rel} ({lines} lines, {len(content.encode('utf-8'))} bytes)"


def edit_file(ws: Workspace, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    target = ws.resolve(path, for_write=True)
    if not target.is_file():
        raise ToolError(f"file not found: {path}")
    if old_string == new_string:
        raise ToolError("old_string and new_string are identical")
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string) if old_string else 0
    if count == 0:
        raise ToolError("old_string not found; read_file first and copy the text exactly (without line numbers)")
    if count > 1 and not replace_all:
        raise ToolError(f"old_string occurs {count} times; add surrounding context or set replace_all=true")
    text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    ws.files_written[ws.rel(target)] = len(text)
    return f"Edited {ws.rel(target)} ({count if replace_all else 1} replacement(s))"


def search_files(ws: Workspace, pattern: str, glob: str | None = None) -> str:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"invalid regex: {exc}") from None
    hits = []
    for p in ws.iter_files():
        rel = ws.rel(p)
        if glob and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(p.name, glob):
            continue
        try:
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n... (truncated at 200 matches)"
        except (UnicodeDecodeError, OSError):
            continue
    return "\n".join(hits) or "no matches"


def read_spec(ws: Workspace, section: str = "summary") -> str:
    spec = ws.spec
    section = (section or "summary").strip()
    if section in ("summary", "spec_issues", "meta", "other_inputs"):
        data = spec.get(section)
    elif section == "diagrams":
        data = [{k: d[k] for k in ("name", "kind", "view", "title")} for d in spec.get("diagrams", [])]
    elif section.startswith("diagram:"):
        name = section.split(":", 1)[1]
        data = next((d for d in spec.get("diagrams", []) if d["name"] == name), None)
    elif section.startswith("document:"):
        name = section.split(":", 1)[1]
        data = next((d for d in spec.get("documents", []) if d["file"] == name), None)
    elif section == "documents":
        data = [d["file"] for d in spec.get("documents", [])]
    else:
        data = None
    if data is None:
        raise ToolError("unknown section. Use: summary, spec_issues, meta, diagrams, diagram:<name>, "
                        "documents, document:<file>, other_inputs")
    return json.dumps(data, indent=1, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Static project validation (stand-in for "run the build")
# --------------------------------------------------------------------------- #
def _check_js(path: Path) -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        res = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return (res.stderr or res.stdout).strip().splitlines()[-1][:300] if (res.stderr or res.stdout) else "syntax error"
    return None


def _check_braces(text: str) -> str | None:
    """Very rough balance check for languages we cannot parse (JS without node, etc.)."""
    stripped = re.sub(r"//.*?$|/\*.*?\*/|`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"",
                      "", text, flags=re.S | re.M)
    for o, c in ("{}", "()", "[]"):
        if stripped.count(o) != stripped.count(c):
            return f"unbalanced '{o}{c}' ({stripped.count(o)} vs {stripped.count(c)})"
    return None


def collect_project_issues(ws: Workspace) -> tuple[list[str], list[str], dict[str, int]]:
    """Return (blocking_issues, warnings, stats)."""
    blocking: list[str] = []
    warnings: list[str] = []
    files = list(ws.iter_files())
    rels = [ws.rel(p) for p in files]
    stats = {"files": len(files), "source_files": 0, "test_files": 0}

    placeholder = re.compile(r"\b(TODO|FIXME)\b|implement (this|me)|\.\.\. ?rest of", re.I)
    for p, rel in zip(files, rels):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        suffix = p.suffix.lower()
        if suffix in (".py", ".js", ".ts", ".mjs", ".cjs", ".java", ".go", ".rs", ".cs"):
            stats["source_files"] += 1
        if any(fnmatch.fnmatch(p.name, pat) for pat in TEST_PATTERNS) or \
                any(part in ("test", "tests", "__tests__", "spec") for part in Path(rel).parts[:-1]):
            stats["test_files"] += 1
        if not text.strip():
            blocking.append(f"{rel}: file is empty")
            continue
        if suffix == ".py":
            try:
                ast.parse(text, filename=rel)
            except SyntaxError as exc:
                blocking.append(f"{rel}:{exc.lineno}: Python syntax error: {exc.msg}")
        elif suffix == ".json":
            try:
                json.loads(text)
            except ValueError as exc:
                blocking.append(f"{rel}: invalid JSON: {exc}")
        elif suffix in (".js", ".mjs", ".cjs"):
            err = _check_js(p)
            if err is None and not shutil.which("node"):
                err = _check_braces(text)
            if err:
                blocking.append(f"{rel}: JavaScript check failed: {err}")
        elif suffix in (".yaml", ".yml"):
            if "\t" in text:
                blocking.append(f"{rel}: YAML must not contain tab characters")
        if suffix not in (".md",) and placeholder.search(text):
            line_no = text[: placeholder.search(text).start()].count("\n") + 1
            warnings.append(f"{rel}:{line_no}: contains a TODO/placeholder - make sure the code is complete")

    lower = {r.lower() for r in rels}
    if "readme.md" not in lower:
        blocking.append("missing README.md at the project root")
    manifests = [r for r in rels if Path(r).name in MANIFESTS]
    if not manifests:
        blocking.append("missing dependency manifest (package.json or requirements.txt)")
    if stats["test_files"] == 0:
        blocking.append("no test files found (e.g. tests/*.test.js or tests/test_*.py)")
    if stats["source_files"] == 0:
        blocking.append("no source code files found")
    for m in manifests:
        if Path(m).name == "package.json":
            try:
                pkg = json.loads((ws.root / m).read_text(encoding="utf-8"))
                if not pkg.get("scripts", {}).get("test"):
                    warnings.append(f"{m}: no \"test\" script defined")
                main = pkg.get("main")
                if main and not (ws.root / Path(m).parent / main).exists():
                    blocking.append(f"{m}: \"main\" points to missing file {main}")
            except (ValueError, OSError):
                pass

    # Local relative imports must resolve (common LLM failure mode)
    req = re.compile(r"""(?:require\(\s*|from\s+|import\s+)['"](\.{1,2}/[^'"]+)['"]""")
    for p, rel in zip(files, rels):
        if p.suffix.lower() not in (".js", ".ts", ".mjs", ".cjs"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for spec in req.findall(text):
            base = (p.parent / spec).resolve()
            candidates = [base, *(base.with_name(base.name + ext) for ext in (".js", ".ts", ".json", ".mjs", ".cjs")),
                          base / "index.js", base / "index.ts"]
            if not any(c.exists() for c in candidates):
                blocking.append(f"{rel}: import '{spec}' does not resolve to a file")

    for d in ws.spec.get("summary", {}).get("deliverables", []):
        if d.lower() not in lower and not any(r.lower().endswith("/" + d.lower()) for r in rels):
            warnings.append(f"spec deliverable '{d}' not found in the project")
    if not any(Path(r).name.lower() == "dockerfile" for r in rels):
        warnings.append("no Dockerfile (optional but recommended)")

    cov = check_coverage(ws.root, files, ws.spec)
    blocking += cov.blocking
    warnings += cov.warnings
    stats["coverage"] = cov.summary
    return blocking, warnings, stats


def check_project(ws: Workspace) -> str:
    blocking, warnings, stats = collect_project_issues(ws)
    out = [f"Files: {stats['files']}  source: {stats['source_files']}  tests: {stats['test_files']}"]
    if stats.get("coverage"):
        out.append("SPEC COVERAGE: " + "; ".join(stats["coverage"]))
    out.append("BLOCKING ISSUES:\n" + ("\n".join(f"- {b}" for b in blocking) if blocking else "- none"))
    out.append("WARNINGS:\n" + ("\n".join(f"- {w}" for w in warnings) if warnings else "- none"))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Registry / JSON schemas sent to the model
# --------------------------------------------------------------------------- #
def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOL_SCHEMAS: list[dict] = [
    _fn("todo_write",
        "Create or replace the task plan. Call first with the full plan, then again whenever a task changes "
        "status. Exactly one task should be in_progress while you work.",
        {"todos": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "content": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
            "required": ["content", "status"]}}},
        ["todos"]),
    _fn("read_spec",
        "Read part of the preprocessed architecture spec (JSON). Sections: summary, spec_issues, meta, diagrams, "
        "diagram:<name>, documents, document:<file>, other_inputs.",
        {"section": {"type": "string"}}, ["section"]),
    _fn("list_files", "List files in the project (recursively) with sizes.",
        {"path": {"type": "string", "description": "Directory relative to project root, default '.'"}}, []),
    _fn("read_file", "Read a project file with line numbers.",
        {"path": {"type": "string"}, "offset": {"type": "integer", "description": "1-based start line"},
         "limit": {"type": "integer", "description": "max lines (default 400)"}}, ["path"]),
    _fn("write_file",
        "Create or overwrite a file with COMPLETE content. Parent directories are created automatically. "
        "Write one file per call; never use placeholders.",
        {"path": {"type": "string", "description": "Path relative to the project root, forward slashes"},
         "content": {"type": "string"}}, ["path", "content"]),
    _fn("edit_file",
        "Replace an exact string in an existing file. old_string must match exactly once unless replace_all.",
        {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}}, ["path", "old_string", "new_string"]),
    _fn("search_files", "Regex search across project files. Returns path:line: text.",
        {"pattern": {"type": "string"}, "glob": {"type": "string", "description": "optional filename glob"}},
        ["pattern"]),
    _fn("check_project",
        "Statically validate the project: syntax of .py/.js/.json/.yaml, unresolved relative imports, "
        "required deliverables (README, manifest, tests, source), and SPEC COVERAGE (every spec class and "
        "method, state transition, use case and sequence-diagram step implemented and tested, plus a minimum "
        "number of tests). Run before finish and fix every blocking issue.",
        {}, []),
    _fn("finish",
        "Call once the project is complete and check_project reports no blocking issues. "
        "Provide a concise summary of what was built and any decisions about spec inconsistencies.",
        {"summary": {"type": "string"}}, ["summary"]),
]

TOOL_FUNCS: dict[str, Callable[..., str]] = {
    "todo_write": todo_write,
    "read_spec": read_spec,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "search_files": search_files,
    "check_project": check_project,
}


def run_tool(ws: Workspace, name: str, args: dict[str, Any]) -> str:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        raise ToolError(f"unknown tool {name!r}")
    try:
        return fn(ws, **args)
    except TypeError as exc:
        raise ToolError(f"bad arguments for {name}: {exc}") from None
