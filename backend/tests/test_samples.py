"""Every sample project must produce a usable, grounded graph (mock client, no key needed)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import Settings

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples" / "dist"
SAMPLES = ["flask-todo", "node-orders-api", "react-dashboard", "python-csv-report"]


def _zip_bytes(name: str) -> bytes:
    path = SAMPLES_DIR / f"{name}.zip"
    if not path.exists():
        pytest.skip(f"{path} is missing — run `make samples` first")
    return path.read_bytes()


async def _wait_ready(client: AsyncClient, project_id: str, limit: float = 90.0) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    while loop.time() < deadline:
        status = (await client.get(f"/api/projects/{project_id}")).json()["status"]
        if status in ("ready", "error", "cancelled", "paused"):
            return str(status)
        await asyncio.sleep(0.05)
    raise AssertionError("analysis did not finish in time")


@pytest.mark.parametrize("sample", SAMPLES)
async def test_sample_produces_a_grounded_graph(
    client: AsyncClient, settings: Settings, sample: str
) -> None:
    upload = await client.post(
        "/api/projects",
        files={"file": (f"{sample}.zip", _zip_bytes(sample), "application/zip")},
    )
    assert upload.status_code == 201, upload.text
    project = upload.json()
    project_id = project["id"]
    assert project["scan"]["code_file_count"] > 0

    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-sample-0123456789"})
    headers = {"X-Session-Token": key.json()["session_token"]}
    options = {"model_id": "mock-capable", "smart_mix": True}

    estimate = await client.post(
        f"/api/projects/{project_id}/analysis/estimate", json=options, headers=headers
    )
    assert estimate.status_code == 200, estimate.text

    start = await client.post(
        f"/api/projects/{project_id}/analysis/start", json=options, headers=headers
    )
    assert start.status_code == 200, start.text
    assert await _wait_ready(client, project_id) == "ready"

    graph = (await client.get(f"/api/projects/{project_id}/graph")).json()
    nodes = graph["nodes"]
    edges = graph["edges"]
    top = [n for n in nodes if n["parent_id"] is None]

    assert len(top) >= 3, f"{sample}: expected several top-level stages"
    assert any(n["kind"] == "start" for n in top), f"{sample}: no start node"
    assert any(n["kind"] == "output" for n in top), f"{sample}: no output node"
    top_edges = [e for e in edges if e["parent_id"] is None]
    assert top_edges and all(e["label"].strip() for e in top_edges), f"{sample}: unlabelled edges"

    # Grounding: every reference must exist in the upload with real line numbers.
    root = Path(settings.workspace_dir) / project_id / "src" / sample
    assert root.is_dir()
    checked = 0
    for node in nodes:
        for ref in node["code_refs"]:
            file_path = root / ref["file"]
            assert file_path.is_file(), f"{sample}: {ref['file']} is not in the upload"
            total = len(file_path.read_text(encoding="utf-8", errors="replace").splitlines())
            assert 1 <= ref["start_line"] <= ref["end_line"] <= max(total, 1), (
                f"{sample}: {ref['file']}:{ref['start_line']}-{ref['end_line']} is out of range"
            )
            checked += 1
    assert checked > 0, f"{sample}: no code references at all"

    # The writing rules hold everywhere.
    for node in nodes:
        assert len(node["title"].split()) <= 5
        assert len(node["explanation"].split()) <= 25
    for edge in edges:
        assert len(edge["label"].split()) <= 6

    # Depth: the graph is more than one flat level.
    assert max(n["level"] for n in nodes) >= 1, f"{sample}: the graph never went deeper"
