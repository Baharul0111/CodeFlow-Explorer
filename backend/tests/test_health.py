from __future__ import annotations

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "mock"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


async def test_unknown_route_has_error_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/nope")
    assert resp.status_code == 404
    assert set(resp.json()["error"]) == {"code", "message"}
