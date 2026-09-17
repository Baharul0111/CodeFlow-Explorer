"""The shareable HTML export must be self-contained, grounded and actually interactive."""

from __future__ import annotations

import asyncio
import json
import re

from httpx import AsyncClient

from tests.helpers import make_zip

PROJECT = {
    "app/main.py": (
        "from app.svc import work\n\n"
        "def handle(request):\n"
        "    body = request.get('body')\n"
        "    if not body:\n"
        "        return None\n"
        "    return work(body)\n"
    ),
    "app/svc.py": "def work(data):\n    return data.strip().upper()\n",
}


async def _ready_project(client: AsyncClient) -> str:
    upload = await client.post(
        "/api/projects", files={"file": ("p.zip", make_zip(PROJECT, root="p"), "application/zip")}
    )
    project_id = upload.json()["id"]
    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-x-0123456789"})
    headers = {"X-Session-Token": key.json()["session_token"]}
    await client.post(
        f"/api/projects/{project_id}/analysis/start",
        json={"model_id": "mock-capable", "smart_mix": True},
        headers=headers,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 60
    while loop.time() < deadline:
        if (await client.get(f"/api/projects/{project_id}")).json()["status"] == "ready":
            return project_id
        await asyncio.sleep(0.05)
    raise AssertionError("analysis did not finish")


async def test_export_page_is_self_contained_and_complete(client: AsyncClient) -> None:
    project_id = await _ready_project(client)
    response = await client.get(f"/api/projects/{project_id}/graph/export.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('flow.html"')
    html = response.text

    # Self-contained: no network needed to view it.
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    for pattern in ("http://", "https://"):
        for hit in re.findall(rf'(?:src|href)="{pattern}[^"]*"', html):
            raise AssertionError(f"export is not self-contained: {hit}")

    # Carries the whole graph.
    payload = json.loads(re.search(r'type="application/json">(.*?)</script>', html, re.S).group(1))
    graph = (await client.get(f"/api/projects/{project_id}/graph")).json()
    assert len(payload["nodes"]) == len(graph["nodes"])
    assert len(payload["edges"]) == len(graph["edges"])
    assert payload["project"]["name"] == "p"

    # Every node keeps what the viewer needs, including its real code references.
    for node in payload["nodes"]:
        assert node["title"] and node["kind"] in (
            "start",
            "process",
            "decision",
            "datastore",
            "external",
            "output",
        )
        assert "has_children" in node and "code_refs" in node

    # Snippets are embedded so the side panel shows real code offline.
    assert payload["snippets"], "no code snippets were embedded"
    for key, snippet in payload["snippets"].items():
        file = key.rsplit(":", 2)[0]
        assert file.endswith((".py", ".md", ".txt"))
        assert snippet["start"] >= 1
    joined = " ".join(s["code"] for s in payload["snippets"].values())
    assert "def handle" in joined or "def work" in joined

    # The viewer is present and interactive.
    for needle in (
        "function layout",
        "data-toggle",
        "Open all",
        'addEventListener("wheel"',
        "prefers-color-scheme",
    ):
        assert needle in html, f"missing viewer feature: {needle}"


async def test_export_page_escapes_script_breakouts(client: AsyncClient) -> None:
    """Code containing </script> must not be able to break out of the embedded JSON."""
    evil = {
        "app/x.py": "HTML = '</script><script>alert(1)</script>'\n\n\ndef render():\n    return HTML\n"
    }
    upload = await client.post(
        "/api/projects", files={"file": ("e.zip", make_zip(evil, root="e"), "application/zip")}
    )
    project_id = upload.json()["id"]
    key = await client.post("/api/keys/test", json={"api_key": "sk-ant-x-0123456789"})
    headers = {"X-Session-Token": key.json()["session_token"]}
    await client.post(
        f"/api/projects/{project_id}/analysis/start",
        json={"model_id": "mock-capable", "smart_mix": True},
        headers=headers,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 60
    while loop.time() < deadline:
        if (await client.get(f"/api/projects/{project_id}")).json()["status"] == "ready":
            break
        await asyncio.sleep(0.05)
    html = (await client.get(f"/api/projects/{project_id}/graph/export.html")).text
    data_block = re.search(r'type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script>" not in data_block
    assert "<\\/script>" in data_block or "alert(1)" not in data_block
    json.loads(data_block)  # still valid JSON


async def test_export_page_refused_before_a_flow_exists(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/projects", files={"file": ("p.zip", make_zip(PROJECT, root="p"), "application/zip")}
    )
    response = await client.get(f"/api/projects/{upload.json()['id']}/graph/export.html")
    assert response.status_code == 404
    assert "no flow to share" in response.json()["error"]["message"]
