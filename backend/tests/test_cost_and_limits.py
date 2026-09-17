"""Cost limit, prompt-cache reuse, and grounding rejection at pipeline level."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.llm.cache import cache_key
from app.llm.errors import CostLimitError
from app.llm.mock import MockClaudeClient
from app.llm.prompts import PROMPT_VERSION, global_block, project_block, render_user_text
from app.llm.schemas import FLOW_SCHEMA
from app.models.orm import LlmCache, UsageEvent
from tests.helpers import make_zip

PROJECT = {
    "app/main.py": (
        "from app.svc import work\n\n"
        "def handle(request):\n"
        "    data = request.get('body')\n"
        "    if not data:\n"
        "        return None\n"
        "    return work(data)\n"
    ),
    "app/svc.py": (
        "from app.store import save\n\n"
        "def work(data):\n"
        "    cleaned = data.strip()\n"
        "    if not cleaned:\n"
        "        raise ValueError('empty')\n"
        "    return save(cleaned)\n"
    ),
    "app/store.py": "ROWS = []\n\n\ndef save(row):\n    ROWS.append(row)\n    return row\n",
}
OPTIONS = {"model_id": "mock-capable", "smart_mix": True}


async def _analyse(client: AsyncClient, *, limit: float | None = None) -> str:
    upload = await client.post(
        "/api/projects", files={"file": ("p.zip", make_zip(PROJECT, root="p"), "application/zip")}
    )
    project_id = upload.json()["id"]
    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-x-0123456789"})
    headers = {"X-Session-Token": key.json()["session_token"]}
    body = dict(OPTIONS)
    if limit is not None:
        body["cost_limit_usd"] = limit
    await client.post(f"/api/projects/{project_id}/analysis/start", json=body, headers=headers)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 60
    while loop.time() < deadline:
        status = (await client.get(f"/api/projects/{project_id}")).json()["status"]
        if status in ("ready", "paused", "error", "cancelled"):
            return project_id
        await asyncio.sleep(0.05)
    raise AssertionError("analysis did not settle")


async def test_cost_limit_pauses_the_run(client: AsyncClient) -> None:
    project_id = await _analyse(client, limit=0.000001)
    project = (await client.get(f"/api/projects/{project_id}")).json()
    assert project["status"] == "paused"
    assert "cost limit" in (project["error"] or "").lower()
    usage = (await client.get(f"/api/projects/{project_id}/analysis/usage")).json()
    assert usage["cost_usd"] > 0


async def test_estimate_flags_being_over_the_limit(client: AsyncClient, settings: Settings) -> None:
    settings.max_cost_per_project_usd = 0.0000001
    upload = await client.post(
        "/api/projects", files={"file": ("p.zip", make_zip(PROJECT, root="p"), "application/zip")}
    )
    project_id = upload.json()["id"]
    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-x-0123456789"})
    headers = {"X-Session-Token": key.json()["session_token"]}
    result = await client.post(
        f"/api/projects/{project_id}/analysis/estimate", json=OPTIONS, headers=headers
    )
    assert result.status_code == 200
    assert result.json()["estimate"]["over_limit"] is True


async def test_second_run_of_the_same_code_is_served_from_cache(client: AsyncClient) -> None:
    """Re-uploading identical code must not cost anything extra."""
    first = await _analyse(client)
    first_usage = (await client.get(f"/api/projects/{first}/analysis/usage")).json()
    assert first_usage["calls"] > 0

    second = await _analyse(client)
    second_usage = (await client.get(f"/api/projects/{second}/analysis/usage")).json()
    assert second_usage["calls"] > 0
    # Every call on the second run is a cache hit, so it costs nothing.
    assert second_usage["cost_usd"] == 0.0
    assert first_usage["cost_usd"] > 0


async def test_prompt_caching_produces_cache_reads(client: AsyncClient) -> None:
    project_id = await _analyse(client)
    usage = (await client.get(f"/api/projects/{project_id}/analysis/usage")).json()
    assert usage["cache_read_tokens"] > 0
    assert usage["cache_write_tokens"] > 0


async def test_cache_rows_are_keyed_by_model_and_prompt_version(client: AsyncClient) -> None:
    await _analyse(client)
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.db.session_factory() as session:
        rows = list((await session.execute(select(LlmCache))).scalars())
        usage_rows = list((await session.execute(select(UsageEvent))).scalars())
    assert rows, "responses must be cached"
    assert {row.model_id for row in rows} <= {"mock-capable", "mock-cheap"}
    assert {row.task for row in rows} & {"function_summary", "system_flow", "expand"}
    assert all(len(row.key) == 64 for row in rows)
    assert {u.task for u in usage_rows}


def test_cache_key_changes_with_model_and_prompt_version() -> None:
    payload = {"units": [{"id": "a"}]}
    base = cache_key(task="expand", model="m1", prompt_version=PROMPT_VERSION, payload=payload)
    assert base != cache_key(
        task="expand", model="m2", prompt_version=PROMPT_VERSION, payload=payload
    )
    assert base != cache_key(task="expand", model="m1", prompt_version="99", payload=payload)
    assert base != cache_key(
        task="steps", model="m1", prompt_version=PROMPT_VERSION, payload=payload
    )
    assert base == cache_key(
        task="expand", model="m1", prompt_version=PROMPT_VERSION, payload=dict(payload)
    )


async def test_cached_prefix_is_byte_identical_between_calls() -> None:
    """The two cached system blocks must not change between calls, or caching silently stops."""
    mock = MockClaudeClient()
    block = project_block(
        name="p",
        languages={"python": 3},
        frameworks=["Flask"],
        readme="hi",
        tree="a/b.py",
        entry_points=["main_guard: a/b.py:1"],
    )
    system = [global_block(), block]
    prefixes = []
    for question in ("one", "two", "three"):
        await mock.generate_json(
            task="expand",
            system=system,
            user_text=render_user_text("expand", question, {"units": [{"id": question}]}),
            schema=FLOW_SCHEMA,
            model="mock-capable",
            max_tokens=100,
        )
        prefixes.append("".join(b.text for b in system if b.cache))
    assert len(set(prefixes)) == 1, "the cached prefix changed between calls"


@pytest.mark.parametrize("bad_limit", [0.0])
async def test_zero_limit_means_no_limit(client: AsyncClient, bad_limit: float) -> None:
    project_id = await _analyse(client, limit=bad_limit)
    assert (await client.get(f"/api/projects/{project_id}")).json()["status"] == "ready"


def test_cost_limit_error_is_user_readable() -> None:
    error = CostLimitError("The cost limit of $5.00 was reached. Raise the limit to carry on.")
    assert "$5.00" in error.message and error.code == "cost_limit"
