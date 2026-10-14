import json

from codeagent.preprocess import build_spec, compact_spec, parse_markdown, parse_plantuml


def test_parse_markdown_sections_tables_code():
    md = """Intro line.

# A. Title
Para one
continues.

| ID | Name |
| --- | --- |
| 1 | x |

* bullet one
- bullet two

## Sub
```sql
CREATE TABLE t (id INT);
```
"""
    root = parse_markdown(md)
    assert root["paragraphs"] == ["Intro line."]
    a = root["subsections"][0]
    assert a["heading"] == "A. Title"
    assert a["paragraphs"] == ["Para one continues."]
    assert a["tables"][0]["rows"] == [{"ID": "1", "Name": "x"}]
    assert a["bullets"] == ["bullet one", "bullet two"]
    sub = a["subsections"][0]
    assert sub["code_blocks"] == [{"language": "sql", "content": "CREATE TABLE t (id INT);"}]


def test_class_diagram_members_and_relations():
    d = parse_plantuml("""@startuml ClassDiagram
class Game {
  - id: string
  + play(): void
  + score(user: User, n: int): int
}
Game --* Question
@enduml""")
    assert d["kind"] == "class"
    game = next(e for e in d["elements"] if e["name"] == "Game")
    attrs = [m for m in game["members"] if m["kind"] == "attribute"]
    methods = [m for m in game["members"] if m["kind"] == "method"]
    assert attrs == [{"kind": "attribute", "visibility": "private", "name": "id", "type": "string"}]
    assert methods[1]["params"] == [{"name": "user", "type": "User"}, {"name": "n", "type": "int"}]
    assert d["relations"][0]["kind"] == "composition"


def test_sequence_state_and_activity():
    seq = parse_plantuml("@startuml SequenceDiagram1\nUser->>Game: play()\nGame->>User: return ok\n@enduml")
    assert [r["kind"] for r in seq["relations"]] == ["message", "return"]
    assert [r["order"] for r in seq["relations"]] == [1, 2]

    st = parse_plantuml("@startuml StateDiagram\nstate A\n[*] --> A\nA --> B : go()\n@enduml")
    assert st["relations"][0]["source"] == "[*]"
    assert st["relations"][1] == {"source": "A", "target": "B", "arrow": "-->", "kind": "transition",
                                  "label": "go()"}

    act = parse_plantuml("@startuml ActivityDiagram\nstart\n:a;\nif (x?) then (yes)\n:b;\nelse (no)\nendif\nstop\n@enduml")
    assert [s["type"] for s in act["steps"]] == ["start", "action", "if", "action", "else", "endif", "stop"]


def test_package_and_class_with_same_name_are_distinct():
    d = parse_plantuml("@startuml PackageDiagram\npackage Game {\n  class Game\n  class Question\n}\n@enduml")
    kinds = sorted((e["type"], e["name"], e["parent"]) for e in d["elements"])
    assert kinds == [("class", "Game", "Game"), ("class", "Question", "Game"), ("package", "Game", None)]


def test_build_spec_on_samples(sample_inputs):
    spec = build_spec(sample_inputs)
    assert spec["meta"]["diagram_count"] == 13
    kinds = {d["kind"] for d in spec["diagrams"]}
    assert kinds >= {"usecase", "class", "object", "state", "activity", "sequence", "collaboration",
                     "package", "component", "deployment", "container"}
    s = spec["summary"]
    assert {c["name"] for c in s["classes"]} == {"Game", "Question", "User", "Admin"}
    assert {u["id"] for u in s["use_cases"]} == {"PlayGame", "ViewScore", "UpdateQuestions", "ViewHelp"}
    assert {"from": "Playing", "to": "Paused", "trigger": "pause()"} in s["state_transitions"]
    assert [r["Requirement ID"] for r in s["requirements"]] == ["FR-1", "NFR-1", "ASR-1"]
    assert "Node.js 18" in s["recommended_stack"]
    assert "sql/game_ddl.sql" in s["deliverables"]
    game_comp = next(c for c in s["documented_components"] if c["name"] == "GameComponent")
    assert "metrics" in game_comp and "game logic" in game_comp["responsibility"]

    issues = " ".join(spec["spec_issues"])
    assert "ASR-2" in issues                      # referenced but missing from matrix
    assert "question_ddl.sql" in issues           # matrix vs deliverables mismatch
    assert "AdminComponent" in issues             # undocumented component
    assert "Testing Strategy" in issues           # empty test matrix

    json.dumps(spec)  # must be serialisable
    assert all("source" not in d for d in compact_spec(spec)["diagrams"])
    assert all("source" in d for d in spec["diagrams"])
