from __future__ import annotations

from app.llm.mock import MockClaudeClient
from app.llm.prompts import global_block, render_user_text
from app.llm.schemas import FLOW_SCHEMA, SUMMARY_SCHEMA, FlowResponse, SummaryResponse
from app.llm.types import SystemBlock

SYSTEM = [global_block(), SystemBlock("project context", cache=True)]


async def test_summaries_cover_every_id() -> None:
    client = MockClaudeClient()
    payload = {"items": [{"id": "a.py::f", "name": "f"}, {"id": "a.py::g", "name": "g"}]}
    result = await client.generate_json(
        task="function_summary",
        system=SYSTEM,
        user_text=render_user_text("function_summary", "do it", payload),
        schema=SUMMARY_SCHEMA,
        model="mock-cheap",
        max_tokens=1000,
    )
    parsed = SummaryResponse.model_validate(result.data)
    assert [s.id for s in parsed.summaries] == ["a.py::f", "a.py::g"]
    assert all(len(s.summary.split()) <= 20 for s in parsed.summaries)


async def test_flow_covers_every_unit_and_is_connected() -> None:
    client = MockClaudeClient()
    units = [{"id": f"f{i}.py", "name": f"file {i}", "summary": "does a thing"} for i in range(7)]
    result = await client.generate_json(
        task="system_flow",
        system=SYSTEM,
        user_text=render_user_text("system_flow", "draw it", {"units": units}),
        schema=FLOW_SCHEMA,
        model="mock-capable",
        max_tokens=2000,
    )
    flow = FlowResponse.model_validate(result.data)
    covered = [c for n in flow.nodes for c in n.covers]
    assert sorted(covered) == sorted(u["id"] for u in units)
    assert len(covered) == len(set(covered))  # each unit exactly once
    assert flow.nodes[0].kind == "start" and flow.nodes[-1].kind == "output"
    keys = {n.key for n in flow.nodes}
    assert all(e.source in keys and e.target in keys for e in flow.edges)
    assert all(e.label and e.label != "data" for e in flow.edges)


async def test_steps_stay_inside_the_function_lines() -> None:
    client = MockClaudeClient()
    fn = {
        "id": "a.py::f",
        "start_line": 10,
        "end_line": 16,
        "lines": [[n, "code"] for n in range(10, 17)],
    }
    result = await client.generate_json(
        task="steps",
        system=SYSTEM,
        user_text=render_user_text("steps", "steps please", {"function": fn}),
        schema=FLOW_SCHEMA,
        model="mock-cheap",
        max_tokens=2000,
    )
    flow = FlowResponse.model_validate(result.data)
    assert flow.nodes
    for node in flow.nodes:
        assert 10 <= node.start_line <= node.end_line <= 16
        assert node.covers == []


async def test_mock_is_deterministic_and_reports_cache_reads() -> None:
    payload = {"units": [{"id": "x.py", "name": "x"}]}
    text = render_user_text("expand", "expand", payload)
    client = MockClaudeClient()
    first = await client.generate_json(
        task="expand", system=SYSTEM, user_text=text, schema=FLOW_SCHEMA, model="m", max_tokens=100
    )
    second = await client.generate_json(
        task="expand", system=SYSTEM, user_text=text, schema=FLOW_SCHEMA, model="m", max_tokens=100
    )
    assert first.data == second.data
    assert first.usage.cache_write_tokens > 0 and first.usage.cache_read_tokens == 0
    assert second.usage.cache_read_tokens > 0  # second call reads the cached prefix
