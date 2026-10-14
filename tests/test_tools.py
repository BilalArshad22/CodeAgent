import json

import pytest

from codeagent.tools import (
    TOOL_SCHEMAS, ToolError, Workspace, check_project, collect_project_issues, edit_file, list_files, read_file,
    read_spec, run_tool, search_files, todo_write, write_file,
)

from conftest import MINIMAL_PROJECT


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "proj", spec={"summary": {"deliverables": ["openapi.yaml"]},
                                              "diagrams": [{"name": "D1", "kind": "class", "view": "", "title": ""}]})


@pytest.mark.parametrize("bad", ["../escape.txt", "/etc/passwd", "C:/Windows/x", "a/../../x", ""])
def test_sandbox_rejects_escapes(ws, bad):
    with pytest.raises(ToolError):
        write_file(ws, bad, "x")


def test_meta_dir_is_read_only(ws):
    with pytest.raises(ToolError):
        write_file(ws, ".codeagent/spec.json", "{}")


def test_write_read_edit_roundtrip(ws):
    assert "Created src/a.js" in write_file(ws, "src/a.js", "line1\nline2\nline2\n")
    assert "Overwrote" in write_file(ws, "src/a.js", "line1\nline2\nline2\n")
    assert "    2\tline2" in read_file(ws, "src/a.js")
    with pytest.raises(ToolError, match="occurs 2 times"):
        edit_file(ws, "src/a.js", "line2", "X")
    edit_file(ws, "src/a.js", "line2", "X", replace_all=True)
    assert (ws.root / "src/a.js").read_text() == "line1\nX\nX\n"
    with pytest.raises(ToolError, match="not found"):
        edit_file(ws, "src/a.js", "nope", "X")


def test_write_preserves_newlines(ws):
    write_file(ws, "f.txt", "a\nb\n")
    assert (ws.root / "f.txt").read_bytes() == b"a\nb\n"


def test_read_file_paging(ws):
    write_file(ws, "big.txt", "\n".join(str(i) for i in range(1, 11)))
    out = read_file(ws, "big.txt", offset=3, limit=2)
    assert "    3\t3" in out and "    4\t4" in out and "offset=5" in out


def test_list_and_search(ws):
    write_file(ws, "a/b.py", "def hello():\n    return 1\n")
    assert "a/b.py" in list_files(ws)
    assert search_files(ws, r"def \w+") == "a/b.py:1: def hello():"
    assert search_files(ws, "zzz") == "no matches"
    with pytest.raises(ToolError):
        search_files(ws, "(")


def test_todo_write_validation(ws):
    out = todo_write(ws, [{"content": "plan", "status": "completed"}, {"content": "build", "status": "in_progress"}])
    assert "[x] 1. plan" in out and "[~] 2. build" in out
    with pytest.raises(ToolError):
        todo_write(ws, [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}])
    with pytest.raises(ToolError):
        todo_write(ws, [{"content": "a", "status": "done"}])


def test_read_spec_sections(ws):
    assert json.loads(read_spec(ws, "diagrams"))[0]["name"] == "D1"
    assert json.loads(read_spec(ws, "diagram:D1"))["kind"] == "class"
    with pytest.raises(ToolError):
        read_spec(ws, "nope")


def test_check_project_flags_missing_deliverables(ws):
    blocking, _, _ = collect_project_issues(ws)
    joined = " ".join(blocking)
    assert "README.md" in joined and "manifest" in joined and "test" in joined


def test_check_project_detects_errors(ws):
    for path, content in MINIMAL_PROJECT.items():
        write_file(ws, path, content)
    blocking, warnings, stats = collect_project_issues(ws)
    assert blocking == []
    assert stats["test_files"] == 1
    assert any("openapi.yaml" in w for w in warnings)

    write_file(ws, "bad.json", "{nope")
    write_file(ws, "bad.py", "def f(:\n")
    write_file(ws, "src/uses.js", "const x = require('./missing');\n")
    write_file(ws, "k8s.yaml", "a:\n\tb: 1\n")
    report = check_project(ws)
    assert "bad.json: invalid JSON" in report
    assert "bad.py:1: Python syntax error" in report
    assert "'./missing' does not resolve" in report
    assert "k8s.yaml: YAML must not contain tab" in report


def test_run_tool_errors(ws):
    with pytest.raises(ToolError, match="unknown tool"):
        run_tool(ws, "rm_rf", {})
    with pytest.raises(ToolError, match="bad arguments"):
        run_tool(ws, "write_file", {"path": "x"})


def test_schemas_cover_all_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"todo_write", "read_spec", "list_files", "read_file", "write_file", "edit_file",
                     "search_files", "check_project", "finish"}
