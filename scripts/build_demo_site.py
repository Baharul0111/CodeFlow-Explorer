#!/usr/bin/env python3
"""Build the static demo site published to GitHub Pages.

For every sample project it runs the real pipeline and writes the app's own self-contained export,
then writes a landing page linking to them. The result is pure static HTML: no server, no API key
needed to *view* it.

    uv run python ../scripts/build_demo_site.py --out ../site          # deterministic demo mode
    ANTHROPIC_API_KEY=sk-ant-... uv run python ../scripts/build_demo_site.py --out ../site --real

Run it from the backend/ directory (or anywhere, as long as the backend package is importable).
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

SAMPLES = [
    ("flask-todo", "Flask todo app", "Python · Flask · SQLite", "Sign up, log in, keep a list."),
    (
        "node-orders-api",
        "Express orders API",
        "JavaScript · Express · Postgres",
        "Place orders, update their status.",
    ),
    (
        "react-dashboard",
        "React dashboard",
        "TypeScript · React",
        "Fetch sales figures and chart them.",
    ),
    (
        "python-csv-report",
        "Python CSV tool",
        "Python · CLI",
        "Read CSVs, clean them, write a report.",
    ),
]
TIMEOUT_SECONDS = 600


@dataclass(slots=True)
class Demo:
    slug: str
    title: str
    stack: str
    blurb: str
    nodes: int
    file: str


async def build_one(
    client: AsyncClient, slug: str, payload: bytes, real_key: str | None
) -> tuple[str, int]:
    """Run the pipeline over one sample and return its exported page plus the node count."""
    upload = await client.post(
        "/api/projects",
        files={"file": (f"{slug}.zip", payload, "application/zip")},
    )
    upload.raise_for_status()
    project_id = upload.json()["id"]

    headers: dict[str, str] = {}
    model, deep = "mock-capable", "mock-cheap"
    if real_key:
        tested = await client.post("/api/keys/test", json={"api_key": real_key})
        tested.raise_for_status()
        body = tested.json()
        headers["X-Session-Token"] = body["session_token"]
        model = body["suggested_model"] or body["models"][0]["id"]
        deep = body["suggested_deep_model"] or model
    else:
        tested = await client.post("/api/keys/test", json={"api_key": "sk-ant-demo-0123456789"})
        headers["X-Session-Token"] = tested.json()["session_token"]

    options = {"model_id": model, "smart_mix": True, "deep_model_id": deep}
    started = await client.post(
        f"/api/projects/{project_id}/analysis/start", json=options, headers=headers
    )
    started.raise_for_status()

    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT_SECONDS
    status = "queued"
    while loop.time() < deadline:
        status = (await client.get(f"/api/projects/{project_id}")).json()["status"]
        if status in ("ready", "error", "paused", "cancelled"):
            break
        await asyncio.sleep(0.2)
    if status not in ("ready", "paused"):
        raise RuntimeError(f"{slug}: analysis ended as {status!r}")

    graph = (await client.get(f"/api/projects/{project_id}/graph")).json()
    page = await client.get(f"/api/projects/{project_id}/graph/export.html")
    page.raise_for_status()
    return page.text, len(graph["nodes"])


def build_sample_zips() -> None:
    subprocess.run(  # noqa: S603 - fixed, local command
        [sys.executable, str(REPO / "samples" / "scripts" / "make_sample_zips.py")], check=True
    )


async def build(out_dir: Path, real: bool) -> list[Demo]:
    real_key = os.environ.get("ANTHROPIC_API_KEY") if real else None
    if real and not real_key:
        raise SystemExit("--real needs ANTHROPIC_API_KEY in the environment")

    demos: list[Demo] = []
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        settings = Settings(
            app_env="test",
            llm_mode="anthropic" if real_key else "mock",
            database_url=f"sqlite+aiosqlite:///{workspace / 'demo.db'}",
            workspace_dir=workspace / "ws",
            key_encryption_secret="demo-site-build",  # noqa: S106 - throwaway, temp dir only
            max_cost_per_project_usd=2.0,
            background_max_nodes=120,
            _env_file=None,
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://demo", timeout=TIMEOUT_SECONDS
            ) as client:
                for slug, title, stack, blurb in SAMPLES:
                    payload = (REPO / "samples" / "dist" / f"{slug}.zip").read_bytes()
                    print(f"building {slug}…", flush=True)
                    page, nodes = await build_one(client, slug, payload, real_key)
                    target = out_dir / "demos" / f"{slug}.html"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(page, encoding="utf-8")
                    demos.append(Demo(slug, title, stack, blurb, nodes, f"demos/{slug}.html"))
                    print(f"  {nodes} nodes → {target.relative_to(out_dir)}", flush=True)
    return demos


def _landing_template() -> str:
    return (Path(__file__).parent / "landing_template.html").read_text(encoding="utf-8")


def landing_page(demos: list[Demo], *, real: bool) -> str:
    cards = "\n".join(
        f"""      <a class="card" href="{d.file}">
        <span class="stack">{html.escape(d.stack)}</span>
        <h3>{html.escape(d.title)}</h3>
        <p>{html.escape(d.blurb)}</p>
        <span class="count">{d.nodes} steps · open it up →</span>
      </a>"""
        for d in demos
    )
    note = (
        "These graphs were generated by Claude from the sample code."
        if real
        else (
            "These graphs were generated in <strong>demo mode</strong>, which uses a deterministic "
            "stand-in instead of Claude — structure, code references and line numbers are real, "
            "but the wording in the boxes is placeholder text. Run it with your own API key for "
            "explanations written properly."
        )
    )
    return _landing_template().replace("__CARDS__", cards).replace("__NOTE__", note)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO / "site"), help="Directory to write the site into"
    )
    parser.add_argument(
        "--real", action="store_true", help="Use the real Claude API (needs ANTHROPIC_API_KEY)"
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    build_sample_zips()
    demos = asyncio.run(build(out_dir, args.real))
    (out_dir / "index.html").write_text(landing_page(demos, real=args.real), encoding="utf-8")
    preview = REPO / "docs" / "images" / "graph.png"
    if preview.exists():
        shutil.copy(preview, out_dir / "preview.png")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    total = sum(d.nodes for d in demos)
    print(f"\nwrote {out_dir} — {len(demos)} demos, {total} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
