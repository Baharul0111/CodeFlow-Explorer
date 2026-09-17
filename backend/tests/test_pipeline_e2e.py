"""End-to-end pipeline test with the mock client: upload → analyse → graph → drill down."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from tests.helpers import make_zip

FLASK_APP = {
    "README.md": "# Todo app\n\nA small Flask todo app with login.\n",
    "requirements.txt": "flask\n",
    "app/__init__.py": "",
    "app/main.py": '''from flask import Flask, request, jsonify
from app.auth import check_login
from app.todos import add_todo, list_todos
from app import db

app = Flask(__name__)


@app.route("/login", methods=["POST"])
def login():
    """Log a person in."""
    payload = request.json
    if not check_login(payload["email"], payload["password"]):
        return jsonify({"error": "bad login"}), 401
    return jsonify({"ok": True})


@app.route("/todos", methods=["GET"])
def todos():
    items = list_todos(request.args.get("user"))
    return jsonify(items)


@app.route("/todos", methods=["POST"])
def create():
    body = request.json
    item = add_todo(body["user"], body["text"])
    return jsonify(item), 201


def main():
    db.init()
    app.run(port=5000)


if __name__ == "__main__":
    main()
''',
    "app/auth.py": '''import hashlib
from app.db import find_user


def hash_password(password):
    """Scramble a password so it is not stored as plain text."""
    return hashlib.sha256(password.encode()).hexdigest()


def check_login(email, password):
    """Check an email and password against the saved users."""
    user = find_user(email)
    if user is None:
        return False
    if user["password"] != hash_password(password):
        return False
    return True
''',
    "app/todos.py": '''from app.db import insert, select_all


def add_todo(user, text):
    """Save one new todo for a person."""
    if not text:
        raise ValueError("text required")
    record = {"user": user, "text": text, "done": False}
    insert("todos", record)
    return record


def list_todos(user):
    """Get every todo belonging to a person."""
    rows = select_all("todos")
    return [r for r in rows if r["user"] == user]
''',
    "app/db.py": """STORE = {}


def init():
    STORE.clear()


def insert(table, record):
    STORE.setdefault(table, []).append(record)
    return record


def select_all(table):
    return STORE.get(table, [])


def find_user(email):
    for row in STORE.get("users", []):
        if row["email"] == email:
            return row
    return None
""",
}


async def _wait_for(check, limit: float = 20.0):  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + limit
    while asyncio.get_running_loop().time() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the pipeline")


async def _upload_and_analyse(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/projects",
        files={"file": ("todo.zip", make_zip(FLASK_APP, root="todo"), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-test-0123456789"})
    token = key.json()["session_token"]
    headers = {"X-Session-Token": token}

    est = await client.post(
        f"/api/projects/{project_id}/analysis/estimate",
        json={"model_id": "mock-capable", "smart_mix": True},
        headers=headers,
    )
    assert est.status_code == 200, est.text
    estimate = est.json()["estimate"]
    assert estimate["calls"] > 0 and estimate["high_usd"] >= estimate["low_usd"]

    started = await client.post(
        f"/api/projects/{project_id}/analysis/start",
        json={"model_id": "mock-capable", "smart_mix": True},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["deep_model_id"] == "mock-cheap"  # smart mix picked the cheap model

    async def ready() -> Any:
        got = await client.get(f"/api/projects/{project_id}")
        return got.json()["status"] == "ready"

    await _wait_for(ready)
    return project_id


async def test_full_pipeline_builds_a_grounded_graph(
    client: AsyncClient, settings: Settings
) -> None:
    project_id = await _upload_and_analyse(client)
    graph = (await client.get(f"/api/projects/{project_id}/graph")).json()
    nodes = graph["nodes"]
    edges = graph["edges"]

    top = [n for n in nodes if n["parent_id"] is None]
    assert len(top) >= 3
    assert any(n["kind"] == "start" for n in top), "a start node is required"
    assert any(n["kind"] == "output" for n in top), "an output node is required"

    top_edges = [e for e in edges if e["parent_id"] is None]
    assert top_edges, "top level must have edges"
    assert all(e["label"] for e in top_edges), "every edge must be labelled"

    # Grounding: every code reference points at a real file and real lines in the upload.
    root = Path(settings.workspace_dir) / project_id / "src" / "todo"
    for node in nodes:
        for ref in node["code_refs"]:
            path = root / ref["file"]
            assert path.is_file(), f"{ref['file']} is not in the upload"
            total = len(path.read_text().splitlines())
            assert 1 <= ref["start_line"] <= ref["end_line"] <= max(total, 1)

    # Titles and explanations follow the writing rules.
    for node in nodes:
        assert len(node["title"].split()) <= 5
        assert len(node["explanation"].split()) <= 25


async def test_drill_down_reaches_function_steps(client: AsyncClient) -> None:
    project_id = await _upload_and_analyse(client)
    graph = (await client.get(f"/api/projects/{project_id}/graph")).json()
    nodes = {n["id"]: n for n in graph["nodes"]}

    # Walk down from the top until a step node (one with line-level refs and no children).
    frontier = [n for n in graph["nodes"] if n["parent_id"] is None]
    depth = 0
    reached_step = False
    while frontier and depth < 8:
        depth += 1
        next_frontier = []
        for node in frontier:
            if node["scope"] == "step":
                reached_step = True
                assert node["has_children"] is False, "step nodes are leaves"
                ref = node["code_refs"][0]
                assert ref["start_line"] >= 1 and ref["symbol"]
                continue
            if not node["has_children"]:
                continue
            resp = await client.post(f"/api/projects/{project_id}/graph/nodes/{node['id']}/expand")
            assert resp.status_code == 200, resp.text
            children = resp.json()["nodes"]
            for child in children:
                nodes[child["id"]] = child
            next_frontier.extend(children)
        frontier = next_frontier
        if reached_step:
            break
    assert reached_step, "drilling down must reach steps inside a function"


async def test_reopening_costs_no_new_tokens(client: AsyncClient) -> None:
    project_id = await _upload_and_analyse(client)
    before = (await client.get(f"/api/projects/{project_id}/analysis/usage")).json()
    assert before["calls"] > 0

    graph_one = (await client.get(f"/api/projects/{project_id}/graph")).json()
    graph_two = (await client.get(f"/api/projects/{project_id}/graph")).json()
    after = (await client.get(f"/api/projects/{project_id}/analysis/usage")).json()
    assert graph_one == graph_two
    assert after["calls"] == before["calls"], "reopening must not call Claude again"
    assert after["cost_usd"] == before["cost_usd"]


async def test_cache_reads_happen_on_repeated_calls(client: AsyncClient) -> None:
    project_id = await _upload_and_analyse(client)
    usage = (await client.get(f"/api/projects/{project_id}/analysis/usage")).json()
    assert usage["cache_read_tokens"] > 0, "prompt caching must produce cache reads"
    assert usage["cost_usd"] > 0


async def test_search_and_snippet_and_export(client: AsyncClient) -> None:
    project_id = await _upload_and_analyse(client)
    hits = (
        await client.get(f"/api/projects/{project_id}/graph/search", params={"q": "app"})
    ).json()
    assert hits and hits[0]["path"][0]
    nodes = (await client.get(f"/api/projects/{project_id}/graph")).json()["nodes"]
    ref = next(r for n in nodes for r in n["code_refs"] if r["end_line"] > 1)
    snippet = await client.get(
        f"/api/projects/{project_id}/graph/snippet",
        params={"file": ref["file"], "start_line": ref["start_line"], "end_line": ref["end_line"]},
    )
    assert snippet.status_code == 200
    assert snippet.json()["code"]

    export = await client.get(f"/api/projects/{project_id}/graph/export")
    assert export.status_code == 200
    payload = json.loads(export.text)
    assert payload["nodes"] and payload["edges"]
    assert "attachment" in export.headers["content-disposition"]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "app/../../secret.py"])
async def test_snippet_path_traversal_is_blocked(client: AsyncClient, bad: str) -> None:
    project_id = await _upload_and_analyse(client)
    resp = await client.get(
        f"/api/projects/{project_id}/graph/snippet",
        params={"file": bad, "start_line": 1, "end_line": 2},
    )
    assert resp.status_code in (400, 404)


async def test_sse_stream_reports_progress(live_server: str) -> None:
    """Progress must stream live over SSE (checked against a real server socket)."""
    async with AsyncClient(base_url=live_server, timeout=60.0) as http:
        resp = await http.post(
            "/api/projects",
            files={"file": ("todo.zip", make_zip(FLASK_APP, root="todo"), "application/zip")},
        )
        project_id = resp.json()["id"]
        key = await http.post("/api/keys/test", json={"api_key": "sk-ant-test-0123456789"})
        headers = {"X-Session-Token": key.json()["session_token"]}

        seen: list[str] = []
        payloads: list[str] = []

        async def read_stream() -> None:
            async with http.stream("GET", f"/api/projects/{project_id}/analysis/events") as stream:
                assert stream.status_code == 200
                assert "text/event-stream" in stream.headers["content-type"]
                async for line in stream.aiter_lines():
                    if line.startswith("event:"):
                        seen.append(line.split(":", 1)[1].strip())
                    elif line.startswith("data:"):
                        payloads.append(line.split(":", 1)[1].strip())
                    if seen and seen[-1] in ("done", "error"):
                        break

        reader = asyncio.create_task(read_stream())
        await asyncio.sleep(0.2)
        await http.post(
            f"/api/projects/{project_id}/analysis/start",
            json={"model_id": "mock-capable", "smart_mix": True},
            headers=headers,
        )
        try:
            await asyncio.wait_for(reader, timeout=60)
        except TimeoutError:  # pragma: no cover - diagnostic path
            reader.cancel()
            raise AssertionError(f"stream did not finish; saw {seen}") from None

    assert seen[0] == "stage"
    assert "graph_ready" in seen, "the graph must be announced before deeper levels finish"
    assert "usage" in seen, "running token and cost totals must be streamed"
    assert "nodes" in seen
    assert seen[-1] == "done"
    assert any("percent" in p for p in payloads)
