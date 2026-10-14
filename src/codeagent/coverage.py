"""Spec coverage: does the generated code actually implement and test the spec?

``check_project`` only proves files exist and parse; a model can satisfy that with
stubs. These heuristics compare the generated sources against the preprocessed
spec (classes + methods, state machine, use cases, sequence-diagram steps,
test count) so the finish gate can send the model back to fill real gaps.

The checks are deliberately language-agnostic text heuristics (comments are
stripped first so names in comments do not count).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CODE_SUFFIXES = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".java", ".go", ".cs", ".kt", ".rb", ".php"}
TEST_PATTERNS = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*", "*Test.java", "*_test.go")
TEST_DIRS = {"test", "tests", "__tests__", "spec"}
TEST_CASE = re.compile(r"\b(?:it|test)\s*\(\s*['\"`]|\bdef\s+test_\w+|@Test\b|\bfunc\s+Test\w+")
COMMENTS = re.compile(r"/\*.*?\*/|(?<![:'\"`])//[^\n]*|^\s*#[^\n]*", re.S | re.M)
MIN_TESTS_FLOOR = 6
# Sequence-diagram steps that are presentation or replies, not behaviour to implement.
SKIP_STEP_PREFIXES = ("display", "return", "show", "render")


@dataclass
class Coverage:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)   # "classes 4/4" style lines


def _words(name: str) -> list[str]:
    """'PlayGame' / 'play game' / 'view_score' -> ['play', 'game']"""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.strip("()"))
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def _camel(words: list[str]) -> str:
    return words[0] + "".join(w.title() for w in words[1:]) if words else ""


def _variants(name: str) -> set[str]:
    w = _words(name)
    if not w:
        return set()
    return {_camel(w), _camel(w)[0].upper() + _camel(w)[1:], "_".join(w), "-".join(w), "".join(w)}


def _is_test(rel: str) -> bool:
    p = Path(rel)
    return any(fnmatch.fnmatch(p.name, pat) for pat in TEST_PATTERNS) or \
        any(part in TEST_DIRS for part in p.parts[:-1])


def _identifier(code: str, name: str, prefix: bool = False, callable_: bool = False) -> bool:
    """Exact identifier, or (prefix=True) an identifier that starts with it in camel/snake case:
    'update' matches updateQuestions / update_questions but 'play' never matches 'display'.
    callable_=True only counts definitions/calls (`play(`, `play =`, `play:`), so a route
    string like '/play' does not pass for the method play()."""
    tail = r"(?:[A-Z_][A-Za-z0-9_]*)?" if prefix else ""
    after = r"\s*[(=:]" if callable_ else r"(?![A-Za-z0-9_])"
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}{tail}{after}", code) is not None


def _defines(code: str, name: str) -> bool:
    n = re.escape(name)
    return re.search(
        rf"\b(?:class|interface|struct|type|function|def|record|enum)\s+{n}\b"
        rf"|\b(?:const|let|var)\s+{n}\s*=|\b{n}\s*=\s*(?:class|function)\b",
        code) is not None


def _route_or_name(code: str, name: str) -> bool:
    """A use case counts as present if its name appears as an identifier or a route mentions one of its words."""
    if any(_identifier(code, v) for v in _variants(name) if re.fullmatch(r"\w+", v)):
        return True
    for word in _words(name):
        stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
        if re.search(rf"""['"`][^'"`\n]*/{re.escape(stem)}""", code, re.I):
            return True
    return False


def _load(root: Path, files: list[Path]) -> tuple[str, str, int, list[str]]:
    """(source code, test code, number of test cases, relative paths) with comments stripped."""
    src, tests, rels = [], [], []
    for p in files:
        rel = p.relative_to(root).as_posix()
        rels.append(rel)
        if p.suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            text = COMMENTS.sub("", p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
        (tests if _is_test(rel) else src).append(text)
    test_code = "\n".join(tests)
    return "\n".join(src), test_code, len(TEST_CASE.findall(test_code)), rels


def scenario_steps(summary: dict[str, Any]) -> list[str]:
    """Behavioural steps from sequence diagrams, as identifiers: 'submit answer' -> 'submitAnswer'."""
    steps: list[str] = []
    for sc in summary.get("scenarios", []):
        for msg in sc.get("messages", []):
            label = msg.split(":", 1)[-1].strip()
            if not label or label.lower().startswith(SKIP_STEP_PREFIXES):
                continue
            ident = _camel(_words(label))
            if ident and ident not in steps:
                steps.append(ident)
    return steps


def transitions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in summary.get("state_transitions", []) if t.get("from") != "[*]" and t.get("to") != "[*]"]


def min_tests(summary: dict[str, Any]) -> int:
    return max(MIN_TESTS_FLOOR, len(summary.get("use_cases", [])) + len(transitions(summary)))


def check_coverage(root: Path, files: list[Path], spec: dict[str, Any]) -> Coverage:
    cov = Coverage()
    summary = spec.get("summary") or {}
    if not any(summary.get(k) for k in ("classes", "states", "use_cases", "scenarios")):
        return cov  # the spec describes no behaviour to check against
    code, test_code, n_tests, rels = _load(root, files)

    # 1. Classes and their methods
    classes = summary.get("classes", [])
    if classes:
        defined = methods_ok = methods_total = 0
        for cls in classes:
            name = cls["name"]
            if _defines(code, name):
                defined += 1
            else:
                cov.blocking.append(f"spec class '{name}' is not defined in the source (expected e.g. `class {name}`)")
            missing = [m["name"] for m in cls.get("methods", []) if not _identifier(code, m["name"], callable_=True)]
            methods_total += len(cls.get("methods", []))
            methods_ok += len(cls.get("methods", [])) - len(missing)
            if missing:
                cov.blocking.append(f"class '{name}' is missing spec method(s): {', '.join(missing)}")
        cov.summary.append(f"classes {defined}/{len(classes)}, methods {methods_ok}/{methods_total}")

    # 2. State machine: states and triggers implemented, each transition tested
    trans = transitions(summary)
    states = summary.get("states", [])
    if states:
        missing_states = [s for s in states if not re.search(rf"\b{re.escape(s)}\b", code, re.I)]
        for s in missing_states:
            cov.blocking.append(f"state '{s}' from the state diagram does not appear in the source")
        impl = tested = 0
        for t in trans:
            trig = _camel(_words(t.get("trigger") or ""))
            label = f"{t['from']} -> {t['to']}" + (f" on {t['trigger']}" if t.get("trigger") else "")
            if trig and not _identifier(code, trig, prefix=True, callable_=True):
                cov.blocking.append(f"transition {label}: trigger '{trig}' is not implemented")
            else:
                impl += 1
            if (trig and _identifier(test_code, trig, prefix=True)) or re.search(rf"\b{re.escape(t['to'])}\b", test_code, re.I):
                tested += 1
            else:
                cov.blocking.append(f"transition {label} has no test (tests never mention '{trig or t['to']}')")
        cov.summary.append(f"states {len(states) - len(missing_states)}/{len(states)}, "
                           f"transitions implemented {impl}/{len(trans)}, tested {tested}/{len(trans)}")

    # 3. Use cases: an entry point (route/handler) and a test each
    use_cases = summary.get("use_cases", [])
    if use_cases:
        impl = tested = 0
        for uc in use_cases:
            label = uc.get("label") or uc["id"]
            if _route_or_name(code, uc["id"]):
                impl += 1
            else:
                cov.blocking.append(f"use case '{label}' has no entry point (route or handler named like "
                                    f"{_camel(_words(uc['id']))} or a '/{_words(uc['id'])[-1]}' route)")
            if _route_or_name(test_code, uc["id"]):
                tested += 1
            else:
                cov.blocking.append(f"use case '{label}' is not exercised by any test")
        cov.summary.append(f"use cases implemented {impl}/{len(use_cases)}, tested {tested}/{len(use_cases)}")

    # 4. Behaviour from sequence diagrams (e.g. submitAnswer, checkAnswer)
    steps = scenario_steps(summary)
    if steps:
        missing = [s for s in steps if not _identifier(code, s, prefix=True, callable_=True)]
        if missing:
            cov.blocking.append("sequence-diagram step(s) not implemented: " + ", ".join(missing))
        cov.summary.append(f"scenario steps {len(steps) - len(missing)}/{len(steps)}")

    # 5. Enough tests to cover the above
    need = min_tests(summary)
    if n_tests < need:
        cov.blocking.append(f"only {n_tests} test case(s); the spec needs at least {need} "
                            f"(one per use case and per state transition)")
    cov.summary.append(f"test cases {n_tests} (min {need})")

    # 6. Components from the component diagram (soft)
    paths_and_code = "\n".join(rels) + "\n" + code
    for comp in summary.get("components", []):
        base = re.sub(r"(Component|Service|Container)$", "", comp)
        if not any(re.search(re.escape(v), paths_and_code, re.I) for v in _variants(comp) | _variants(base)):
            cov.warnings.append(f"component '{comp}' has no matching module or identifier")
    return cov


def coverage_checklist(spec: dict[str, Any]) -> str:
    """Human-readable checklist for the task prompt (mirrors check_coverage)."""
    s = spec.get("summary") or {}
    lines = []
    for cls in s.get("classes", []):
        methods = ", ".join(m["name"] for m in cls.get("methods", [])) or "-"
        lines.append(f"- class `{cls['name']}` with methods: {methods}")
    if s.get("states"):
        lines.append(f"- state machine with states {', '.join(s['states'])}; enforce valid transitions "
                     "(reject invalid ones) and test each:")
        lines += [f"  - {t['from']} -> {t['to']}" + (f" via `{t['trigger']}`" if t.get("trigger") else "")
                  for t in transitions(s)]
    if s.get("use_cases"):
        lines.append("- one entry point (e.g. HTTP route) AND at least one test per use case: "
                     + ", ".join(u.get("label") or u["id"] for u in s["use_cases"]))
    steps = scenario_steps(s)
    if steps:
        lines.append("- behaviour from the sequence diagrams, as real logic: " + ", ".join(f"`{x}`" for x in steps))
    if lines:
        lines.append(f"- at least {min_tests(s)} automated test cases")
    return "\n".join(lines)
