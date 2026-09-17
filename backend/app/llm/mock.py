"""Deterministic mock Claude client.

It reads the same JSON payload the real prompt carries and builds a *grounded* answer from it, so
tests and the ``LLM_MODE=mock`` demo exercise the real pipeline (coverage checks, grounding,
persistence, SSE) on any project without an API key and without spending anything.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.llm.errors import BadOutputError
from app.llm.prompts import parse_payload
from app.llm.types import LlmResult, ModelSpec, SystemBlock, Task, TokenUsage

MOCK_MODELS = [
    ModelSpec(
        id="mock-capable",
        display_name="Mock Capable",
        tier="capable",
        hint="Most capable",
        supports_effort=True,
        input_price=5.0,
        output_price=25.0,
        cache_read_price=0.5,
        cache_write_price=6.25,
        max_input_tokens=1_000_000,
        max_output_tokens=64_000,
        source="fallback",
    ),
    ModelSpec(
        id="mock-cheap",
        display_name="Mock Cheap",
        tier="cheap",
        hint="Fastest and cheapest",
        supports_effort=False,
        input_price=1.0,
        output_price=5.0,
        cache_read_price=0.1,
        cache_write_price=1.25,
        max_input_tokens=200_000,
        max_output_tokens=32_000,
        source="fallback",
    ),
]

VERBS = ["Check", "Read", "Handle", "Save", "Build", "Send", "Turn", "Sort"]


def _words(text: str, limit: int) -> str:
    return " ".join(text.replace("_", " ").replace("-", " ").split()[:limit])


def _label_for(unit: dict[str, Any]) -> str:
    name = str(unit.get("name") or unit.get("id", "part")).split("::")[-1]
    return _words(name.replace(".", " "), 3) or "part"


def _pick_verb(seed: str) -> str:
    digest = hashlib.sha256(seed.encode()).digest()
    return VERBS[digest[0] % len(VERBS)]


def _kind_for(unit: dict[str, Any], index: int, total: int) -> str:
    hint = " ".join(str(unit.get(k, "")) for k in ("id", "name", "summary", "kind")).lower()
    if any(w in hint for w in ("db", "database", "store", "repo", "model", "sql", "cache")):
        return "datastore"
    if any(w in hint for w in ("http", "client", "api", "fetch", "request", "external")):
        return "external"
    if any(w in hint for w in ("valid", "check", "auth", "guard", "permission")):
        return "decision"
    if index == 0:
        return "start"
    if index == total - 1:
        return "output"
    return "process"


class MockClaudeClient:
    """Implements :class:`app.llm.client.ClaudeClient` with no network access."""

    def __init__(self, *, fail_task: Task | None = None) -> None:
        self.calls: list[tuple[Task, str]] = []
        self._seen: set[str] = set()
        self._fail_task = fail_task

    async def aclose(self) -> None:
        return None

    async def list_models(self) -> list[ModelSpec]:
        return list(MOCK_MODELS)

    async def verify_credentials(self, *, model: str | None = None) -> None:
        return None

    async def count_tokens(self, *, system: list[SystemBlock], user_text: str, model: str) -> int:
        chars = sum(len(b.text) for b in system) + len(user_text)
        return max(1, chars // 4)

    async def generate_json(
        self,
        *,
        task: Task,
        system: list[SystemBlock],
        user_text: str,
        schema: dict[str, Any],
        model: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> LlmResult:
        self.calls.append((task, model))
        if self._fail_task == task:
            raise BadOutputError()
        payload = parse_payload(user_text)
        if task in ("function_summary", "file_summary", "module_summary"):
            data = self._summaries(payload)
        elif task == "steps":
            data = self._steps(payload)
        else:
            data = self._flow(payload, task)
        prompt_chars = sum(len(b.text) for b in system) + len(user_text)
        cached_prefix = "".join(b.text for b in system if b.cache)
        key = hashlib.sha256(cached_prefix.encode()).hexdigest()
        cache_hit = key in self._seen
        self._seen.add(key)
        cache_tokens = len(cached_prefix) // 4
        return LlmResult(
            data=data,
            model=model,
            usage=TokenUsage(
                input_tokens=max(1, (prompt_chars - len(cached_prefix)) // 4),
                output_tokens=max(1, len(str(data)) // 4),
                cache_write_tokens=0 if cache_hit else cache_tokens,
                cache_read_tokens=cache_tokens if cache_hit else 0,
            ),
        )

    # ---------------------------------------------------------------- builders
    def _summaries(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = payload.get("items", [])
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id", ""))
            label = _label_for(item)
            verb = _pick_verb(ident)
            out.append({"id": ident, "summary": f"{verb}s the {label.lower()} for the program."})
        return {"summaries": out}

    def _flow(self, payload: dict[str, Any], task: Task) -> dict[str, Any]:
        units = [u for u in payload.get("units", []) if isinstance(u, dict)]
        if not units:
            return {
                "nodes": [
                    {
                        "key": "n1",
                        "kind": "process",
                        "title": "Run the program",
                        "explanation": "This part of the program does its work.",
                        "inputs": ["input"],
                        "outputs": ["result"],
                        "covers": [],
                        "start_line": 0,
                        "end_line": 0,
                    }
                ],
                "edges": [],
            }
        groups = _group(units, target=min(6, max(3, len(units))))
        nodes: list[dict[str, Any]] = []
        for i, group in enumerate(groups):
            head = group[0]
            kind = _kind_for(head, i, len(groups))
            label = _label_for(head)
            verb = _pick_verb(str(head.get("id", i)))
            title = _words(f"{verb} {label}", 5)
            nodes.append(
                {
                    "key": f"n{i + 1}",
                    "kind": kind,
                    "title": title,
                    "explanation": f"{verb}s the {label.lower()} so the next step can use it.",
                    "inputs": ["incoming details"] if i else ["request from the user"],
                    "outputs": ["the finished answer"]
                    if i == len(groups) - 1
                    else ["prepared details"],
                    "covers": [str(u.get("id")) for u in group if u.get("id")],
                    "start_line": 0,
                    "end_line": 0,
                }
            )
        edges = [
            {
                "source": nodes[i]["key"],
                "target": nodes[i + 1]["key"],
                "label": f"{_label_for(groups[i][0]).lower()} details",
                "data_shape": "a small set of values",
                "kind": "data",
            }
            for i in range(len(nodes) - 1)
        ]
        if task == "system_flow" and nodes:
            nodes[0]["kind"] = "start"
            nodes[-1]["kind"] = "output"
        return {"nodes": nodes, "edges": edges}

    def _steps(self, payload: dict[str, Any]) -> dict[str, Any]:
        fn = payload.get("function", {})
        lines = fn.get("lines", [])
        numbers = [int(entry[0]) for entry in lines if isinstance(entry, list) and entry]
        if not numbers:
            start = int(fn.get("start_line", 1) or 1)
            end = int(fn.get("end_line", start) or start)
            numbers = list(range(start, end + 1))
        chunks = _chunks(numbers, target=min(4, max(2, len(numbers) // 3 or 2)))
        nodes = []
        for i, chunk in enumerate(chunks):
            verb = _pick_verb(f"{fn.get('id', '')}{i}")
            nodes.append(
                {
                    "key": f"s{i + 1}",
                    "kind": "start"
                    if i == 0
                    else ("output" if i == len(chunks) - 1 else "process"),
                    "title": _words(f"{verb} the values", 5),
                    "explanation": "This part of the function does one small job.",
                    "inputs": ["values from the step before"],
                    "outputs": ["values for the next step"],
                    "covers": [],
                    "start_line": chunk[0],
                    "end_line": chunk[-1],
                }
            )
        edges = [
            {
                "source": nodes[i]["key"],
                "target": nodes[i + 1]["key"],
                "label": "values so far",
                "data_shape": "a few values",
                "kind": "control",
            }
            for i in range(len(nodes) - 1)
        ]
        return {"nodes": nodes, "edges": edges}


def _step_kind(index: int, total: int) -> str:
    if index == 0:
        return "start"
    return "output" if index == total - 1 else "process"


def _group(units: list[dict[str, Any]], *, target: int) -> list[list[dict[str, Any]]]:
    target = max(1, min(target, len(units)))
    size, extra = divmod(len(units), target)
    out: list[list[dict[str, Any]]] = []
    idx = 0
    for i in range(target):
        take = size + (1 if i < extra else 0)
        out.append(units[idx : idx + take])
        idx += take
    return [g for g in out if g]


def _chunks(numbers: list[int], *, target: int) -> list[list[int]]:
    return [
        [numbers[i] for i in range(start, stop)] for start, stop in _spans(len(numbers), target)
    ]


def _spans(total: int, target: int) -> list[tuple[int, int]]:
    target = max(1, min(target, total))
    size, extra = divmod(total, target)
    spans: list[tuple[int, int]] = []
    idx = 0
    for i in range(target):
        take = size + (1 if i < extra else 0)
        spans.append((idx, idx + take))
        idx += take
    return [s for s in spans if s[1] > s[0]]
