"""Bottom-up summaries: functions, then files, then folders.

Everything above function level reads summaries, never raw code. Trivial functions
(getters/setters/one-liners) never reach Claude at all — their text is generated from the static
code map. Batching keeps the number of calls low; the response cache makes repeats free.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.llm.cache import ResponseCache, cache_key
from app.llm.client import ClaudeClient, llm_errors
from app.llm.prompts import (
    FILE_SUMMARY_INSTRUCTION,
    MODULE_SUMMARY_INSTRUCTION,
    PROMPT_VERSION,
    SUMMARY_INSTRUCTION,
    global_block,
    render_user_text,
)
from app.llm.schemas import SUMMARY_SCHEMA, SummaryResponse
from app.llm.types import LlmResult, SystemBlock, Task
from app.logging_setup import get_logger
from app.parsing.codemap import CodeMap, Symbol
from app.pipeline.units import file_unit_id, module_unit_id

log = get_logger(__name__)

SUMMARIES_FILE = "summaries.json"
MAX_BATCH_CHARS = 24_000
MAX_BATCH_ITEMS = 12
MAX_CODE_CHARS_PER_SYMBOL = 4_000
SUMMARY_MAX_TOKENS = 2_000

ProgressFn = Callable[[str, float], Awaitable[None]]


@dataclass(slots=True)
class SummaryOutcome:
    summaries: dict[str, str]
    llm_calls: int = 0
    skipped_trivial: int = 0


def trivial_summary(sym: Symbol) -> str:
    """Summary text for a trivial symbol, written from static facts only."""
    name = sym.name.replace("_", " ").strip()
    lowered = name.lower()
    if lowered.startswith("get "):
        return f"Gives back the {lowered[4:] or 'value'}."
    if lowered.startswith("set "):
        return f"Stores a new {lowered[4:] or 'value'}."
    if lowered.startswith(("is ", "has ")):
        return f"Answers yes or no: {lowered}."
    if sym.docstring:
        return " ".join(sym.docstring.split()[:20])
    return f"Small helper called {name}."


def read_symbol_code(root: Path, sym: Symbol) -> str:
    """The symbol's own lines, numbered, capped so one huge function cannot blow the budget."""
    try:
        lines = (root / sym.file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    chunk = lines[sym.start_line - 1 : sym.end_line]
    numbered = "\n".join(f"{sym.start_line + i}: {line}" for i, line in enumerate(chunk))
    return numbered[:MAX_CODE_CHARS_PER_SYMBOL]


def _batches(items: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    out: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    size = 0
    for item in items:
        item_size = len(json.dumps(item, ensure_ascii=False))
        if current and (size + item_size > MAX_BATCH_CHARS or len(current) >= MAX_BATCH_ITEMS):
            out.append(current)
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        out.append(current)
    return out


class SummaryGenerator:
    def __init__(
        self,
        *,
        client: ClaudeClient,
        cache: ResponseCache | None,
        model: str,
        project_block: SystemBlock,
        on_usage: Callable[[Task, LlmResult, bool], Awaitable[None]] | None = None,
        effort: str | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._model = model
        self._system = [global_block(summaries=True), project_block]
        self._on_usage = on_usage
        self._effort = effort

    async def _run_batch(
        self, task: Task, instruction: str, items: list[dict[str, str]]
    ) -> dict[str, str]:
        payload = {"items": items}
        key = cache_key(
            task=task, model=self._model, prompt_version=PROMPT_VERSION, payload=payload
        )
        if self._cache is not None:
            hit = await self._cache.get(key)
            if hit is not None:
                parsed = SummaryResponse.model_validate(hit)
                if self._on_usage:
                    await self._on_usage(
                        task, LlmResult(data=hit, model=self._model, cached=True), True
                    )
                return {s.id: s.summary for s in parsed.summaries}
        with llm_errors():
            result = await self._client.generate_json(
                task=task,
                system=self._system,
                user_text=render_user_text(task, instruction, payload),
                schema=SUMMARY_SCHEMA,
                model=self._model,
                max_tokens=SUMMARY_MAX_TOKENS,
                effort=self._effort,
            )
        parsed = SummaryResponse.model_validate(result.data)
        wanted = {item["id"] for item in items}
        summaries = {
            s.id: " ".join(s.summary.split()[:20]) for s in parsed.summaries if s.id in wanted
        }
        if self._cache is not None:
            await self._cache.put(key, task=task, model=self._model, response=result.data)
        if self._on_usage:
            await self._on_usage(task, result, False)
        return summaries

    async def summarise_functions(
        self, cm: CodeMap, root: Path, *, progress: ProgressFn | None = None
    ) -> SummaryOutcome:
        outcome = SummaryOutcome(summaries={})
        pending: list[dict[str, str]] = []
        for sym in cm.functions():
            if sym.is_trivial:
                outcome.summaries[sym.id] = trivial_summary(sym)
                outcome.skipped_trivial += 1
                continue
            code = read_symbol_code(root, sym)
            if not code:
                outcome.summaries[sym.id] = trivial_summary(sym)
                continue
            pending.append({"id": sym.id, "name": sym.qualname, "code": code})
        batches = _batches(pending)
        for index, batch in enumerate(batches):
            summaries = await self._run_batch("function_summary", SUMMARY_INSTRUCTION, batch)
            outcome.summaries.update(summaries)
            outcome.llm_calls += 1
            if progress:
                await progress(
                    f"Reading functions ({index + 1}/{len(batches)})",
                    (index + 1) / max(1, len(batches)),
                )
        for sym in cm.functions():
            outcome.summaries.setdefault(sym.id, trivial_summary(sym))
        for cls in (s for s in cm.symbols.values() if s.kind == "class"):
            methods = [
                outcome.summaries.get(s.id, "") for s in cm.symbols.values() if s.parent == cls.id
            ]
            joined = " ".join(m for m in methods[:3] if m)
            outcome.summaries.setdefault(
                cls.id, joined or f"A group of related actions called {cls.name}."
            )
        return outcome

    async def summarise_files(
        self, cm: CodeMap, summaries: dict[str, str], *, progress: ProgressFn | None = None
    ) -> SummaryOutcome:
        outcome = SummaryOutcome(summaries={})
        pending: list[dict[str, str]] = []
        for path in sorted(cm.files):
            symbols = cm.file_symbols(path)
            parts = [f"{s.qualname}: {summaries.get(s.id, '')}".strip(": ") for s in symbols[:20]]
            body = "; ".join(p for p in parts if p)
            if not body:
                outcome.summaries[file_unit_id(path)] = f"Support file {path.rsplit('/', 1)[-1]}."
                continue
            pending.append({"id": file_unit_id(path), "name": path, "parts": body[:2000]})
        for index, batch in enumerate(_batches(pending)):
            outcome.summaries.update(
                await self._run_batch("file_summary", FILE_SUMMARY_INSTRUCTION, batch)
            )
            outcome.llm_calls += 1
            if progress:
                await progress(f"Reading files ({index + 1})", 1.0)
        for path in cm.files:
            outcome.summaries.setdefault(file_unit_id(path), f"Part of the project: {path}.")
        return outcome

    async def summarise_modules(
        self, cm: CodeMap, summaries: dict[str, str], *, progress: ProgressFn | None = None
    ) -> SummaryOutcome:
        outcome = SummaryOutcome(summaries={})
        pending: list[dict[str, str]] = []
        for directory, files in sorted(cm.modules().items()):
            parts = [
                f"{p.rsplit('/', 1)[-1]}: {summaries.get(file_unit_id(p), '')}" for p in files[:20]
            ]
            body = "; ".join(parts)
            pending.append(
                {"id": module_unit_id(directory), "name": directory or ".", "parts": body[:2500]}
            )
        for index, batch in enumerate(_batches(pending)):
            outcome.summaries.update(
                await self._run_batch("module_summary", MODULE_SUMMARY_INSTRUCTION, batch)
            )
            outcome.llm_calls += 1
            if progress:
                await progress(f"Reading folders ({index + 1})", 1.0)
        for directory in cm.modules():
            outcome.summaries.setdefault(
                module_unit_id(directory), f"The {directory or 'root'} folder."
            )
        return outcome


def save_summaries(summaries: dict[str, str], project_dir: Path) -> None:
    (project_dir / SUMMARIES_FILE).write_text(
        json.dumps(summaries, ensure_ascii=False), encoding="utf-8"
    )


def load_summaries(project_dir: Path) -> dict[str, str]:
    path = project_dir / SUMMARIES_FILE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
