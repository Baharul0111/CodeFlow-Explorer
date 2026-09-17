from __future__ import annotations

from pathlib import Path

from app.api.schemas import CodeRef
from app.llm.schemas import FlowResponse
from app.parsing.builder import build_codemap
from app.parsing.codemap import CodeMap
from app.pipeline.grounding import (
    refs_exist,
    repair_payload,
    validate_step_flow,
    validate_structural_flow,
)
from app.pipeline.scan import scan_project
from app.pipeline.units import Unit, file_unit_id

PROJECT = {
    "app/main.py": "def handle(req):\n    data = parse(req)\n    if not data:\n        return None\n    saved = store(data)\n    return saved\n\ndef parse(r):\n    return r\n\ndef store(d):\n    return d\n",
    "app/db.py": "def save(x):\n    return x\n",
}


def _codemap(tmp_path: Path) -> CodeMap:
    for rel, content in PROJECT.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return build_codemap(tmp_path, scan_project(tmp_path))


def _menu() -> list[Unit]:
    return [
        Unit(id=file_unit_id("app/main.py"), kind="file", name="app/main.py"),
        Unit(id=file_unit_id("app/db.py"), kind="file", name="app/db.py"),
    ]


def _node(key: str, covers: list[str], **kw: object) -> dict[str, object]:
    return {
        "key": key,
        "kind": kw.get("kind", "process"),
        "title": kw.get("title", "Do the thing"),
        "explanation": kw.get("explanation", "It does the thing."),
        "inputs": [],
        "outputs": [],
        "covers": covers,
        "start_line": kw.get("start_line", 0),
        "end_line": kw.get("end_line", 0),
    }


def test_valid_flow_passes_and_gets_real_code_refs(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {
            "nodes": [
                _node("a", [file_unit_id("app/main.py")], kind="start"),
                _node("b", [file_unit_id("app/db.py")], kind="output"),
            ],
            "edges": [
                {
                    "source": "a",
                    "target": "b",
                    "label": "user request",
                    "data_shape": "",
                    "kind": "data",
                }
            ],
        }
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm, require_start_and_output=True)
    assert flow.ok and not flow.problems
    assert [n.kind for n in flow.nodes] == ["start", "output"]
    assert flow.nodes[0].code_refs[0].file == "app/main.py"
    assert refs_exist(flow.nodes[0].code_refs, cm)


def test_invented_id_is_rejected(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {"nodes": [_node("a", ["file:app/does_not_exist.py"])], "edges": []}
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm)
    assert not flow.ok
    assert any("was not in the list" in p for p in flow.problems)


def test_missing_coverage_is_reported_for_repair(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {"nodes": [_node("a", [file_unit_id("app/main.py")])], "edges": []}
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm)
    assert not flow.ok
    assert any("left out" in p and "app/db.py" in p for p in flow.problems)
    payload = repair_payload(flow, _menu())
    assert payload["ids"] == [u.id for u in _menu()]
    assert len(payload["problems"]) == len(flow.problems)  # only problems go back, not the context


def test_duplicate_coverage_is_reported(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {
            "nodes": [
                _node("a", [file_unit_id("app/main.py")]),
                _node("b", [file_unit_id("app/main.py"), file_unit_id("app/db.py")]),
            ],
            "edges": [],
        }
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm)
    assert any("is used by both" in p for p in flow.problems)


def test_long_text_is_trimmed_not_rejected(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {
            "nodes": [
                _node(
                    "a",
                    [file_unit_id("app/main.py")],
                    title="One two three four five six seven",
                    explanation=" ".join(["word"] * 40),
                ),
                _node("b", [file_unit_id("app/db.py")]),
            ],
            "edges": [
                {
                    "source": "a",
                    "target": "b",
                    "label": "a b c d e f g h",
                    "data_shape": "x" * 200,
                    "kind": "data",
                }
            ],
        }
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm)
    assert flow.ok
    assert len(flow.nodes[0].title.split()) == 5
    assert len(flow.nodes[0].explanation.split()) == 25
    assert len(flow.edges[0].label.split()) == 6
    assert len(flow.edges[0].data_shape) <= 60


def test_missing_edges_are_repaired_into_a_chain(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {
            "nodes": [
                _node("a", [file_unit_id("app/main.py")]),
                _node("b", [file_unit_id("app/db.py")]),
            ],
            "edges": [
                {"source": "a", "target": "ghost", "label": "x", "data_shape": "", "kind": "data"}
            ],
        }
    )
    flow = validate_structural_flow(response, menu=_menu(), cm=cm)
    assert flow.ok
    assert [(e.source, e.target) for e in flow.edges] == [("a", "b")]
    assert any("dropped edge" in f for f in flow.fixes)


def test_steps_must_stay_within_the_function(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    good = FlowResponse.model_validate(
        {
            "nodes": [
                _node("s1", [], start_line=1, end_line=3),
                _node("s2", [], start_line=4, end_line=6),
            ],
            "edges": [],
        }
    )
    flow = validate_step_flow(
        good, file="app/main.py", start_line=1, end_line=6, symbol="handle", cm=cm
    )
    assert flow.ok
    assert flow.nodes[0].code_refs[0].start_line == 1
    assert refs_exist(flow.nodes[1].code_refs, cm)

    bad = FlowResponse.model_validate(
        {"nodes": [_node("s1", [], start_line=90, end_line=99)], "edges": []}
    )
    flow = validate_step_flow(
        bad, file="app/main.py", start_line=1, end_line=6, symbol="handle", cm=cm
    )
    assert not flow.ok
    assert any("outside this function" in p for p in flow.problems)


def test_steps_in_an_unknown_file_are_rejected(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    response = FlowResponse.model_validate(
        {"nodes": [_node("s1", [], start_line=1, end_line=2)], "edges": []}
    )
    flow = validate_step_flow(response, file="nope.py", start_line=1, end_line=2, symbol="x", cm=cm)
    assert not flow.ok and "not part of this project" in flow.problems[0]


def test_refs_exist_rejects_out_of_range_lines(tmp_path: Path) -> None:
    cm = _codemap(tmp_path)
    assert refs_exist([CodeRef(file="app/db.py", start_line=1, end_line=2, symbol="save")], cm)
    assert not refs_exist(
        [CodeRef(file="app/db.py", start_line=9999, end_line=10000, symbol="")], cm
    )
    assert not refs_exist([CodeRef(file="ghost.py", start_line=1, end_line=2, symbol="")], cm)
