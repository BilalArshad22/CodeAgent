"""Turn the architecture inputs (Markdown + PlantUML) into structured JSON.

The agent works far better from a normalised spec than from raw Markdown:
sections become a tree, tables become lists of row dicts, PlantUML diagrams
become typed elements/relations, and cross-document inconsistencies are
surfaced up front as ``spec_issues`` so the model resolves them deliberately.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQ_ID = re.compile(r"\b(?:FR|NFR|ASR)-\d+\b")
FILENAME = re.compile(r"\b[\w./-]+\.(?:md|ya?ml|proto|sql|csv|json|txt|js|ts|py|toml|ini)\b")

# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
BULLET = re.compile(r"^\s*(?:[*\-+•]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _new_section(heading: str, level: int) -> dict[str, Any]:
    return {
        "heading": heading,
        "level": level,
        "paragraphs": [],
        "bullets": [],
        "tables": [],
        "code_blocks": [],
        "subsections": [],
    }


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _parse_table(lines: list[str]) -> dict[str, Any]:
    header = _split_row(lines[0])
    rows = []
    for line in lines[1:]:
        if TABLE_SEP.match(line):
            continue
        cells = _split_row(line)
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return {"columns": header, "rows": rows}


def parse_markdown(text: str) -> dict[str, Any]:
    """Parse Markdown into a nested section tree."""
    root = _new_section("(document)", 0)
    stack = [root]
    lines = text.splitlines()
    i = 0
    para: list[str] = []

    def flush_para() -> None:
        if para:
            stack[-1]["paragraphs"].append(" ".join(s.strip() for s in para))
            para.clear()

    while i < len(lines):
        line = lines[i]
        fence = FENCE.match(line)
        if fence:
            flush_para()
            lang = fence.group(1).lower()
            body = []
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            stack[-1]["code_blocks"].append({"language": lang, "content": "\n".join(body)})
            i += 1
            continue
        head = HEADING.match(line)
        if head:
            flush_para()
            level = len(head.group(1))
            section = _new_section(head.group(2).strip(), level)
            while stack[-1]["level"] >= level:
                stack.pop()
            stack[-1]["subsections"].append(section)
            stack.append(section)
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            flush_para()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            stack[-1]["tables"].append(_parse_table(block))
            continue
        bullet = BULLET.match(line)
        if bullet:
            flush_para()
            stack[-1]["bullets"].append(bullet.group(1).strip())
        elif not line.strip():
            flush_para()
        else:
            para.append(line)
        i += 1
    flush_para()
    return root


def iter_sections(section: dict[str, Any], path: tuple[str, ...] = ()):
    """Yield (path, section) for every section, depth first."""
    here = path + ((section["heading"],) if section["level"] else ())
    yield here, section
    for sub in section["subsections"]:
        yield from iter_sections(sub, here)


# --------------------------------------------------------------------------- #
# PlantUML
# --------------------------------------------------------------------------- #
_EP = r'\[\*\]|\([^)]*\)|"[^"]*"|[\w.]+'
RELATION = re.compile(
    rf"^(?P<src>{_EP})\s*(?P<arrow>[<*o]?[-.]+(?:>>|[>*o])?)\s*(?P<dst>{_EP})\s*(?::\s*(?P<label>.*))?$"
)
DECL = re.compile(
    r"^(?P<type>actor|participant|node|artifact|component|state|database|usecase|class|"
    r"interface|enum|object|package|rectangle|entity|boundary|control)\s+"
    r'(?:"(?P<qlabel>[^"]*)"\s+as\s+(?P<qalias>\S+)|(?P<name>[\w.]+)(?:\s+as\s+(?P<label>"[^"]*"|\S+))?|'
    r'(?P<lonely>"[^"]*"|\([^)]*\)))?\s*(?P<open>\{)?\s*$'
)
MEMBER = re.compile(r"^(?P<vis>[-+#~])?\s*(?P<body>.+)$")
NOTE = re.compile(r"^note\s+(?:left|right|top|bottom|over)(?:\s+of)?\s+(?P<target>[\w, ]+?)\s*:\s*(?P<text>.*)$")
VISIBILITY = {"-": "private", "+": "public", "#": "protected", "~": "package"}

DIAGRAM_KINDS = [
    "usecase", "class", "object", "state", "activity", "sequence",
    "collaboration", "package", "component", "deployment", "container",
]


def _strip(name: str | None) -> str:
    return (name or "").strip().strip('"').strip("()").strip()


def _arrow_kind(arrow: str) -> str:
    if "*" in arrow:
        return "composition"
    if arrow.endswith("o") or arrow.startswith("o"):
        return "aggregation"
    if arrow.endswith(">>"):
        return "message"
    if "." in arrow:
        return "dependency"
    if arrow.endswith(">") or arrow.startswith("<"):
        return "directed"
    return "association"


def _detect_kind(name: str, title: str, body: str) -> str:
    hay = f"{name} {title}".lower()
    for kind in DIAGRAM_KINDS:
        if kind in hay.replace(" ", ""):
            return kind
    if re.search(r"^\s*(start|stop)\s*$", body, re.M):
        return "activity"
    if "->>" in body:
        return "sequence"
    return "unknown"


def _parse_member(line: str) -> dict[str, Any]:
    m = MEMBER.match(line)
    vis = VISIBILITY.get(m.group("vis") or "", "default")
    body = m.group("body").strip()
    method = re.match(r"^(\w+)\s*\((.*?)\)\s*(?::\s*(.+))?$", body)
    if method:
        params = []
        for p in filter(None, (x.strip() for x in method.group(2).split(","))):
            pname, _, ptype = p.partition(":")
            params.append({"name": pname.strip(), "type": ptype.strip() or None})
        return {"kind": "method", "visibility": vis, "name": method.group(1),
                "params": params, "returns": (method.group(3) or "void").strip()}
    name, _, typ = body.partition(":")
    return {"kind": "attribute", "visibility": vis, "name": name.strip(), "type": typ.strip() or None}


def parse_plantuml(source: str, title: str = "", view: str = "") -> dict[str, Any]:
    lines = [ln.strip() for ln in source.splitlines()]
    name = ""
    for ln in lines:
        if ln.startswith("@startuml"):
            name = ln[len("@startuml"):].strip()
            break
    body = "\n".join(lines)
    diagram: dict[str, Any] = {
        "name": name or title or "diagram",
        "title": title,
        "view": view,
        "kind": _detect_kind(name, title, body),
        "elements": [],
        "relations": [],
        "notes": [],
        "steps": [],
        "source": source.strip(),
    }
    elements: dict[str, dict[str, Any]] = {}
    containers: list[str] = []   # stack of open package/rectangle names
    open_class: dict[str, Any] | None = None

    def element(name: str, etype: str, label: str | None = None, declared: bool = False) -> dict[str, Any]:
        plain = _strip(name)
        key = plain
        # e.g. `package Game { class Game }`: same name, different kinds of element
        if declared and key in elements and elements[key]["type"] != etype:
            key = f"{etype}:{plain}"
        if key not in elements:
            elements[key] = {"name": plain, "type": etype, "label": _strip(label) or plain,
                             "parent": containers[-1] if containers else None}
            diagram["elements"].append(elements[key])
        return elements[key]

    for ln in lines:
        if not ln or ln.startswith("'") or ln.startswith("@") or ln.startswith("left to right") \
                or ln.startswith("skinparam") or ln.startswith("title "):
            continue
        if open_class is not None:
            if ln == "}":
                open_class = None
            else:
                open_class.setdefault("members", []).append(_parse_member(ln))
            continue
        if ln == "}":
            if containers:
                containers.pop()
            continue

        # Activity diagram constructs
        if ln in ("start", "stop", "end", "endif", "fork", "end fork", "endwhile"):
            diagram["steps"].append({"type": ln.replace(" ", "_")})
            continue
        m = re.match(r"^:(.*);$", ln)
        if m:
            diagram["steps"].append({"type": "action", "text": m.group(1).strip()})
            continue
        m = re.match(r"^(else\s*)?if\s*\((.*?)\)\s*then\s*(?:\((.*?)\))?$", ln)
        if m:
            diagram["steps"].append({"type": "elseif" if m.group(1) else "if",
                                     "condition": m.group(2), "branch": m.group(3)})
            continue
        m = re.match(r"^else\s*(?:\((.*?)\))?$", ln)
        if m:
            diagram["steps"].append({"type": "else", "branch": m.group(1)})
            continue

        m = NOTE.match(ln)
        if m:
            diagram["notes"].append({"target": m.group("target").strip(), "text": m.group("text").strip()})
            continue

        m = DECL.match(ln)
        if m:
            etype = m.group("type")
            if m.group("qalias"):
                el = element(m.group("qalias"), etype, m.group("qlabel"), declared=True)
            elif m.group("name"):
                el = element(m.group("name"), etype, m.group("label"), declared=True)
            elif m.group("lonely"):
                el = element(m.group("lonely"), etype, declared=True)
            else:
                continue
            if m.group("open"):
                if etype in ("package", "rectangle", "node"):
                    containers.append(el["name"])
                else:
                    el.setdefault("members", [])
                    open_class = el
            continue

        m = RELATION.match(ln)
        if m:
            label = (m.group("label") or "").strip() or None
            src, dst = _strip(m.group("src")), _strip(m.group("dst"))
            rel: dict[str, Any] = {"source": src, "target": dst, "arrow": m.group("arrow"),
                                   "kind": _arrow_kind(m.group("arrow")), "label": label}
            if diagram["kind"] in ("sequence", "collaboration") and label:
                rel["kind"] = "return" if label.lower().startswith("return") else "message"
            if diagram["kind"] == "state":
                rel["kind"] = "transition"
                if src == "*":
                    rel["source"] = "[*]"
                if dst == "*":
                    rel["target"] = "[*]"
            diagram["relations"].append(rel)
            for end in (rel["source"], rel["target"]):
                if end not in ("[*]",) and end not in elements:
                    implied = "usecase" if f"({end})" in ln else "participant"
                    element(end, implied)
            continue

    if diagram["kind"] in ("sequence", "collaboration"):
        for idx, rel in enumerate(r for r in diagram["relations"]):
            rel["order"] = idx + 1
    return diagram


def extract_diagrams(md_text: str) -> list[dict[str, Any]]:
    """Find every ```plantuml block, keeping the nearest '## View' and numbered title."""
    diagrams = []
    view, title = "", ""
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        h = HEADING.match(line)
        if h:
            view = h.group(2).strip()
        elif re.match(r"^\s*\d+\.\s+\S", line) and not FENCE.match(line):
            title = re.sub(r"^\s*\d+\.\s+", "", line).strip()
        fence = FENCE.match(line)
        if fence:
            lang = fence.group(1).lower()
            body = []
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            src = "\n".join(body)
            if lang in ("plantuml", "puml", "uml") or "@startuml" in src:
                diagrams.append(parse_plantuml(src, title=title, view=view))
        i += 1
    return diagrams


# --------------------------------------------------------------------------- #
# Spec building
# --------------------------------------------------------------------------- #
def _domain_summary(diagrams: list[dict[str, Any]]) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {}
    use_cases, actors, states, transitions = [], [], [], []
    scenarios, components, nodes, packages = [], set(), set(), {}
    relations = []
    for d in diagrams:
        for el in d["elements"]:
            if el["type"] == "class":
                cls = classes.setdefault(el["name"], {"name": el["name"], "attributes": [], "methods": [],
                                                       "package": None})
                for mem in el.get("members", []):
                    bucket = cls["attributes" if mem["kind"] == "attribute" else "methods"]
                    if all(x["name"] != mem["name"] for x in bucket):
                        bucket.append({k: v for k, v in mem.items() if k != "kind"})
                if d["kind"] == "package" and el["parent"]:
                    cls["package"] = el["parent"]
                    packages.setdefault(el["parent"], []).append(el["name"])
            elif el["type"] == "usecase":
                use_cases.append({"id": el["name"], "label": el["label"]})
            elif el["type"] == "actor":
                actors.append({"id": el["name"], "label": el["label"]})
            elif el["type"] == "state":
                states.append(el["name"])
            elif el["type"] in ("artifact", "component") and d["kind"] == "component":
                components.add(el["name"])
            elif el["type"] == "node":
                nodes.add(el["name"])
        if d["kind"] == "class":
            relations += [{k: r[k] for k in ("source", "target", "kind")} for r in d["relations"]]
        if d["kind"] == "state":
            transitions += [{"from": r["source"], "to": r["target"], "trigger": r["label"]}
                            for r in d["relations"]]
        if d["kind"] == "sequence":
            scenarios.append({"diagram": d["name"],
                              "messages": [f'{r["source"]} -> {r["target"]}: {r["label"]}' for r in d["relations"]]})
    usecase_links = []
    for d in diagrams:
        if d["kind"] == "usecase":
            usecase_links += [{"actor": r["source"], "use_case": r["target"]} for r in d["relations"]]
    return {
        "actors": actors,
        "use_cases": use_cases,
        "actor_use_cases": usecase_links,
        "classes": list(classes.values()),
        "class_relations": relations,
        "states": states,
        "state_transitions": transitions,
        "scenarios": scenarios,
        "packages": packages,
        "components": sorted(components),
        "deployment_nodes": sorted(nodes),
    }


def _doc_facts(doc: dict[str, Any], raw: str) -> dict[str, Any]:
    requirements, components, stack, deliverables = [], [], [], []
    empty_tables = []
    for path, sec in iter_sections(doc):
        heading = " / ".join(path)
        for table in sec["tables"]:
            cols = [c.lower() for c in table["columns"]]
            if any("requirement id" in c for c in cols):
                requirements += table["rows"]
            filled = sum(1 for row in table["rows"] for k, v in row.items() if v and k != table["columns"][0])
            if table["rows"] and filled == 0:
                empty_tables.append(heading)
        for b in sec["bullets"]:
            m = re.match(r"^(\w*Component)\s*:\s*(.+)$", b)
            if m:
                key = "metrics" if "metric" in heading.lower() else "responsibility"
                entry = next((c for c in components if c["name"] == m.group(1)), None)
                if entry is None:
                    entry = {"name": m.group(1)}
                    components.append(entry)
                entry.setdefault(key, m.group(2))
        if "recommended default stack" in sec["heading"].lower():
            stack += sec["bullets"]
        if "deliverable" in sec["heading"].lower():
            for cb in sec["code_blocks"]:
                if cb["language"] in ("markdown", "md", "text", ""):
                    deliverables += [ln.strip() for ln in cb["content"].splitlines() if ln.strip()]
    mentioned_ids = sorted(set(REQ_ID.findall(raw)))
    return {
        "requirements": requirements,
        "requirement_ids_mentioned": mentioned_ids,
        "components": components,
        "recommended_stack": stack,
        "deliverables": deliverables,
        "empty_tables": empty_tables,
    }


def _spec_issues(facts: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    in_matrix = {r.get("Requirement ID", "") for r in facts["requirements"]}
    for rid in facts["requirement_ids_mentioned"]:
        if rid not in in_matrix:
            issues.append(f"{rid} is referenced in the documentation but missing from the traceability matrix.")
    listed = set(facts["deliverables"])
    for row in facts["requirements"]:
        for fname in FILENAME.findall(row.get("Artifact filename(s)", "")):
            if listed and fname not in listed and not any(d.endswith(fname) for d in listed):
                issues.append(
                    f"Traceability row {row.get('Requirement ID')} references '{fname}', "
                    f"which is not in the deliverables list {sorted(listed)}."
                )
    for heading in facts["empty_tables"]:
        issues.append(f"Table under '{heading}' has no content; fill it in sensibly.")
    doc_components = {c["name"] for c in facts["components"]}
    for comp in summary["components"]:
        if doc_components and comp not in doc_components:
            issues.append(f"{comp} appears in the component diagram but has no description in the documentation.")
    if summary["classes"]:
        names = {c["name"] for c in summary["classes"]}
        for rel in summary["class_relations"]:
            for end in (rel["source"], rel["target"]):
                if end not in names:
                    issues.append(f"Class relation references undefined class '{end}'.")
    return issues


def build_spec(paths: list[str | Path]) -> dict[str, Any]:
    """Preprocess every input file into a single spec dict."""
    documents, diagrams, other = [], [], []
    combined_facts: dict[str, Any] = {"requirements": [], "requirement_ids_mentioned": [], "components": [],
                                      "recommended_stack": [], "deliverables": [], "empty_tables": []}
    for p in map(Path, paths):
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        suffix = p.suffix.lower()
        if suffix in (".md", ".markdown", ".puml", ".plantuml", ".txt"):
            found = extract_diagrams(text) if suffix in (".md", ".markdown", ".txt") else \
                [parse_plantuml(text, title=p.stem)]
            for d in found:
                d["source_file"] = p.name
            diagrams += found
            if suffix in (".md", ".markdown", ".txt") and not found:
                tree = parse_markdown(text)
                facts = _doc_facts(tree, text)
                for k, v in facts.items():
                    for item in v:
                        if item not in combined_facts[k]:
                            combined_facts[k].append(item)
                documents.append({"file": p.name, "structure": tree, "facts": facts})
            elif suffix in (".md", ".markdown", ".txt"):
                documents.append({"file": p.name, "role": "architecture_views",
                                  "diagram_names": [d["name"] for d in found]})
        elif suffix == ".json":
            try:
                other.append({"file": p.name, "json": json.loads(text)})
            except ValueError:
                other.append({"file": p.name, "text": text})
        else:
            other.append({"file": p.name, "text": text})

    summary = _domain_summary(diagrams)
    summary["documented_components"] = combined_facts["components"]
    summary["requirements"] = combined_facts["requirements"]
    summary["recommended_stack"] = combined_facts["recommended_stack"]
    summary["deliverables"] = combined_facts["deliverables"]
    return {
        "meta": {
            "generator": "codeagent.preprocess",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inputs": [Path(p).name for p in paths],
            "diagram_count": len(diagrams),
        },
        "summary": summary,
        "spec_issues": _spec_issues(combined_facts, summary),
        "documents": documents,
        "diagrams": diagrams,
        "other_inputs": other,
    }


def compact_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Spec without raw PlantUML sources (they are re-derivable and noisy)."""
    out = json.loads(json.dumps(spec))
    for d in out.get("diagrams", []):
        d.pop("source", None)
    return out
