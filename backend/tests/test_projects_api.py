from __future__ import annotations

import os

from httpx import AsyncClient

from tests.helpers import make_zip

SAMPLE = {
    "README.md": "# Tiny\n",
    "app/main.py": "def main():\n    print('hi')\n\nif __name__ == '__main__':\n    main()\n",
    "app/util.py": "def add(a, b):\n    return a + b\n",
}


async def _upload(client: AsyncClient, data: bytes, name: str = "tiny.zip") -> object:
    return await client.post("/api/projects", files={"file": (name, data, "application/zip")})


async def test_upload_and_get(client: AsyncClient) -> None:
    resp = await _upload(client, make_zip(SAMPLE, root="tiny"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "tiny"
    assert body["status"] == "scanned"
    assert body["scan"]["languages"]["python"]["files"] == 2
    assert body["scan"]["code_file_count"] == 2

    got = await client.get(f"/api/projects/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]

    listing = await client.get("/api/projects")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == body["id"]
    assert listing.json()[0]["file_count"] == 3

    deleted = await client.delete(f"/api/projects/{body['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/projects/{body['id']}")).status_code == 404


async def test_zip_slip_rejected_with_clear_message(client: AsyncClient) -> None:
    resp = await _upload(client, make_zip({"../../evil.py": "x", "ok.py": "y"}))
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "unsafe_zip"
    assert "unsafe path" in err["message"]


async def test_zip_bomb_rejected(client: AsyncClient) -> None:
    resp = await _upload(client, make_zip({"bomb.txt": b"0" * (3 * 1024 * 1024)}))
    assert resp.status_code == 400
    assert "zip bomb" in resp.json()["error"]["message"]


async def test_not_a_zip_rejected(client: AsyncClient) -> None:
    resp = await _upload(client, b"hello", name="x.zip")
    assert resp.status_code == 400
    assert "not a valid zip" in resp.json()["error"]["message"]


async def test_oversized_upload_rejected(client: AsyncClient, settings) -> None:  # type: ignore[no-untyped-def]
    settings.max_upload_mb = 1
    resp = await _upload(client, os.urandom(2 * 1024 * 1024))
    assert resp.status_code == 413
    assert "larger than 1 MB" in resp.json()["error"]["message"]


async def test_upload_rate_limited(client: AsyncClient, settings) -> None:  # type: ignore[no-untyped-def]
    settings.rate_limit_uploads_per_minute = 2
    data = make_zip(SAMPLE)
    assert (await _upload(client, data)).status_code == 201
    assert (await _upload(client, data)).status_code == 201
    third = await _upload(client, data)
    assert third.status_code == 429
    assert "too often" in third.json()["error"]["message"]
