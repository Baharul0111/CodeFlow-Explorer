"""Build a single HTML file that shows a finished graph, offline and interactive.

The page carries the whole graph plus the code snippets it needs, and a small viewer written in
plain JavaScript — no network, no build step, no dependencies. Open it by double-clicking, or send
it to someone who has never heard of this app.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MAX_SNIPPET_LINES = 60
MAX_SNIPPET_BYTES = 1_500_000  # keep the shared file comfortably under a few MB


@dataclass(slots=True)
class ExportPayload:
    project: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    snippets: dict[str, dict[str, Any]]


def snippet_key(file: str, start: int, end: int) -> str:
    return f"{file}:{start}:{end}"


def collect_snippets(root: Path, nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Read the lines each node points at, so the exported page can show real code offline."""
    snippets: dict[str, dict[str, Any]] = {}
    budget = MAX_SNIPPET_BYTES
    cache: dict[str, list[str]] = {}
    for node in nodes:
        for ref in node.get("code_refs", []):
            file = str(ref.get("file", ""))
            start = int(ref.get("start_line", 0) or 0)
            end = int(ref.get("end_line", 0) or 0)
            key = snippet_key(file, start, end)
            if key in snippets or budget <= 0 or start < 1:
                continue
            if file not in cache:
                path = (root / file).resolve()
                if root.resolve() not in path.parents or not path.is_file():
                    continue
                try:
                    cache[file] = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
            lines = cache[file]
            first = max(1, start)
            last = min(len(lines), max(first, min(end, first + MAX_SNIPPET_LINES - 1)))
            text = "\n".join(lines[first - 1 : last])
            budget -= len(text)
            snippets[key] = {"start": first, "code": text}
    return snippets


def _embed(data: Any) -> str:
    """JSON safe to place inside a <script> block."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


@lru_cache(maxsize=1)
def _template() -> str:
    return (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")


def render(payload: ExportPayload) -> str:
    """Return one HTML document containing the graph, its snippets and the viewer."""
    name = payload.project.get("name", "project")
    return (
        _template()
        .replace("__TITLE__", _escape(str(name)))
        .replace(
            "__DATA__",
            _embed(
                {
                    "project": payload.project,
                    "nodes": payload.nodes,
                    "edges": payload.edges,
                    "snippets": payload.snippets,
                }
            ),
        )
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
