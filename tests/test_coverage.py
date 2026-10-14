import json
from pathlib import Path

import pytest

from codeagent.coverage import check_coverage, coverage_checklist, scenario_steps
from codeagent.preprocess import build_spec, compact_spec

from conftest import SPACE_FRACTIONS_PROJECT


@pytest.fixture(scope="module")
def spec(request):
    root = Path(__file__).resolve().parents[1] / "src" / "codeagent" / "samples"
    return compact_spec(build_spec([root / "Architecture_Documentation.md", root / "Architecture_View.md"]))


def write(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return [p for p in tmp_path.rglob("*") if p.is_file()]


def test_full_implementation_passes(tmp_path, spec):
    cov = check_coverage(tmp_path, write(tmp_path, SPACE_FRACTIONS_PROJECT), spec)
    assert cov.blocking == [], cov.blocking
    assert any("classes 4/4, methods 7/7" in s for s in cov.summary)
    assert any("tested 3/3" in s for s in cov.summary)


def test_stub_project_is_blocked_with_specific_reasons(tmp_path, spec):
    # Shape of the real gemini-3.1-flash-lite output: state endpoints only, no domain classes.
    stub = {
        "src/gameComponent.js": "const app = require('express')();\nlet s = 'Playing';\n"
                                "app.get('/play', () => {});\napp.post('/pause', () => { s = 'Paused'; });\n"
                                "app.post('/resume', () => {});\napp.post('/gameOver', () => { s = 'GameOver'; });\n",
        "tests/game.test.js": "test('should start game', () => {});\ntest('should pause game', () => {});\n",
    }
    cov = check_coverage(tmp_path, write(tmp_path, stub), spec)
    text = "\n".join(cov.blocking)
    assert "spec class 'Game' is not defined" in text
    assert "class 'Question' is missing spec method(s): getPrompt, getOptions" in text
    assert "use case 'View Help' has no entry point" in text
    assert "not implemented: play, getPrompt, submitAnswer, checkAnswer, update" in text  # route strings do not count
    assert "only 2 test case(s); the spec needs at least 7" in text
    assert "Paused -> Playing on resume() has no test" in text


def test_names_in_comments_do_not_count(tmp_path, spec):
    files = dict(SPACE_FRACTIONS_PROJECT)
    files["src/domain/admin.js"] = "// class Admin { updateQuestions() }\n/* class Admin */\nmodule.exports = {};\n"
    cov = check_coverage(tmp_path, write(tmp_path, files), spec)
    assert "spec class 'Admin' is not defined in the source (expected e.g. `class Admin`)" in cov.blocking


def test_prefix_matching_rules(tmp_path, spec):
    # 'display' must not satisfy the 'play' step; 'updateQuestions' does satisfy 'update'
    files = {k: v.replace("play()", "display()").replace("play(", "display(") if k == "src/domain/game.js" else v
             for k, v in SPACE_FRACTIONS_PROJECT.items()}
    files["src/domain/user.js"] = files["src/domain/user.js"].replace("game.play()", "game.display()")
    cov = check_coverage(tmp_path, write(tmp_path, files), spec)
    assert "class 'Game' is missing spec method(s): play" in cov.blocking
    assert not any("update" in b for b in cov.blocking)


def test_checklist_and_steps(spec):
    assert scenario_steps(spec["summary"]) == ["play", "getPrompt", "submitAnswer", "checkAnswer", "update"]
    checklist = coverage_checklist(spec)
    assert "class `Question` with methods: getPrompt, getOptions" in checklist
    assert "Playing -> Paused via `pause()`" in checklist
    assert "at least 7 automated test cases" in checklist


def test_no_spec_means_no_coverage_checks(tmp_path):
    assert check_coverage(tmp_path, [], {}).blocking == []
