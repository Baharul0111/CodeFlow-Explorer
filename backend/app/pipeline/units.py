"""Units: the atoms a graph node can cover, and the menu shown to Claude when expanding.

A unit id is one of

* ``mod:<directory>``  — every file under one directory
* ``file:<path>``      — one file
* ``<path>::<qualname>`` — one function, method or class (a code-map symbol id)

Node coverage is always a list of unit ids, and Claude may only ever use ids from the menu it was
handed. That is what makes the graph grounded: the ids come from tree-sitter, not from the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.parsing.codemap import CodeMap, Symbol

Scope = Literal["system", "stage", "group", "file", "function", "step"]

MODULE_PREFIX = "mod:"
FILE_PREFIX = "file:"
MAX_FILES_BEFORE_GROUPING = 12
MAX_MENU_ITEMS = 40


@dataclass(slots=True)
class Unit:
    id: str
    kind: Literal["module", "file", "symbol"]
    name: str
    summary: str = ""
    files: list[str] = field(default_factory=list)
    symbol_id: str | None = None
    file: str | None = None
    start_line: int = 0
    end_line: int = 0
    detail: str = ""

    def as_payload(self) -> dict[str, str]:
        """Compact form sent to Claude (short keys, no empty fields)."""
        out = {"id": self.id, "name": self.name}
        if self.summary:
            out["s"] = self.summary
        if self.detail:
            out["d"] = self.detail
        return out


def module_unit_id(directory: str) -> str:
    return f"{MODULE_PREFIX}{directory}"


def file_unit_id(path: str) -> str:
    return f"{FILE_PREFIX}{path}"


def is_module(unit_id: str) -> bool:
    return unit_id.startswith(MODULE_PREFIX)


def is_file(unit_id: str) -> bool:
    return unit_id.startswith(FILE_PREFIX)


def is_symbol(unit_id: str) -> bool:
    return "::" in unit_id


def files_of(unit_id: str, cm: CodeMap) -> list[str]:
    if is_module(unit_id):
        directory = unit_id[len(MODULE_PREFIX) :]
        return sorted(p for p in cm.files if cm.module_of(p) == directory)
    if is_file(unit_id):
        path = unit_id[len(FILE_PREFIX) :]
        return [path] if path in cm.files else []
    if is_symbol(unit_id):
        sym = cm.symbols.get(unit_id)
        return [sym.file] if sym else []
    return []


def covered_files(coverage: list[str], cm: CodeMap) -> list[str]:
    seen: list[str] = []
    for unit_id in coverage:
        for path in files_of(unit_id, cm):
            if path not in seen:
                seen.append(path)
    return seen


def covered_symbols(coverage: list[str], cm: CodeMap) -> list[Symbol]:
    out: list[Symbol] = []
    for unit_id in coverage:
        if is_symbol(unit_id):
            sym = cm.symbols.get(unit_id)
            if sym:
                out.append(sym)
        else:
            for path in files_of(unit_id, cm):
                out.extend(cm.file_symbols(path))
    return out


def _module_unit(directory: str, cm: CodeMap, summaries: dict[str, str]) -> Unit:
    files = sorted(p for p in cm.files if cm.module_of(p) == directory)
    unit_id = module_unit_id(directory)
    return Unit(
        id=unit_id,
        kind="module",
        name=directory if directory != "." else "project root",
        summary=summaries.get(unit_id, ""),
        files=files,
        detail=f"{len(files)} files",
    )


def _file_unit(path: str, cm: CodeMap, summaries: dict[str, str]) -> Unit:
    unit_id = file_unit_id(path)
    symbols = cm.file_symbols(path)
    return Unit(
        id=unit_id,
        kind="file",
        name=path,
        summary=summaries.get(unit_id, ""),
        files=[path],
        file=path,
        detail=f"{len(symbols)} functions" if symbols else "",
    )


def _symbol_unit(sym: Symbol, summaries: dict[str, str]) -> Unit:
    signature = f"{sym.name}{sym.params}" + (f" -> {sym.returns}" if sym.returns else "")
    return Unit(
        id=sym.id,
        kind="symbol",
        name=sym.qualname,
        summary=summaries.get(sym.id, sym.docstring or ""),
        files=[sym.file],
        symbol_id=sym.id,
        file=sym.file,
        start_line=sym.start_line,
        end_line=sym.end_line,
        detail=signature[:120],
    )


def top_level_units(cm: CodeMap, summaries: dict[str, str]) -> tuple[list[Unit], Scope]:
    """Menu for level 0: modules when the project is big, files when it is small."""
    modules = cm.modules()
    if len(cm.files) <= MAX_FILES_BEFORE_GROUPING or len(modules) <= 1:
        units = [_file_unit(p, cm, summaries) for p in sorted(cm.files)]
        return units[:MAX_MENU_ITEMS], "file"
    units = [_module_unit(d, cm, summaries) for d in sorted(modules)]
    if len(units) > MAX_MENU_ITEMS:
        units = _roll_up(units, summaries)
    return units, "stage"


def _roll_up(units: list[Unit], summaries: dict[str, str]) -> list[Unit]:
    """Too many directories: group them by their first path segment."""
    buckets: dict[str, list[Unit]] = {}
    for unit in units:
        directory = unit.id[len(MODULE_PREFIX) :]
        top = directory.split("/", 1)[0] if directory != "." else "."
        buckets.setdefault(top, []).append(unit)
    rolled: list[Unit] = []
    for top, group in sorted(buckets.items()):
        if len(group) == 1:
            rolled.append(group[0])
            continue
        files = [f for unit in group for f in unit.files]
        rolled.append(
            Unit(
                id=module_unit_id(top),
                kind="module",
                name=top if top != "." else "project root",
                summary=summaries.get(module_unit_id(top), ""),
                files=files,
                detail=f"{len(files)} files in {len(group)} folders",
            )
        )
    return rolled[:MAX_MENU_ITEMS]


def _symbol_child_menu(
    symbol_id: str, cm: CodeMap, summaries: dict[str, str]
) -> tuple[list[Unit], Scope]:
    """A class expands into its methods; a function expands into steps, not units."""
    sym = cm.symbols.get(symbol_id)
    if sym is None or sym.kind != "class":
        return [], "step"
    methods = [s for s in cm.symbols.values() if s.parent == sym.id]
    return ([_symbol_unit(m, summaries) for m in methods], "function") if methods else ([], "step")


def child_menu(
    coverage: list[str], cm: CodeMap, summaries: dict[str, str]
) -> tuple[list[Unit], Scope]:
    """What the children of a node covering ``coverage`` may be built from."""
    if len(coverage) == 1 and is_symbol(coverage[0]):
        return _symbol_child_menu(coverage[0], cm, summaries)

    files = covered_files(coverage, cm)
    if len(files) == 1:
        symbols = [s for s in cm.file_symbols(files[0]) if s.parent is None]
        if symbols:
            return [_symbol_unit(s, summaries) for s in symbols][:MAX_MENU_ITEMS], "function"
        return [], "step"

    directories = sorted({cm.module_of(p) for p in files})
    if len(files) > MAX_FILES_BEFORE_GROUPING and len(directories) > 1:
        units = [_module_unit(d, cm, summaries) for d in directories]
        units = [u for u in units if u.files]
        if len(units) > MAX_MENU_ITEMS:
            units = _roll_up(units, summaries)
        return units, "group"
    return [_file_unit(p, cm, summaries) for p in files][:MAX_MENU_ITEMS], "file"


def expandable(coverage: list[str], cm: CodeMap, scope: Scope) -> bool:
    """Can this node be drilled into? Step nodes and leaf functions cannot."""
    if scope == "step":
        return False
    if len(coverage) == 1 and is_symbol(coverage[0]):
        sym = cm.symbols.get(coverage[0])
        if sym is None:
            return False
        if sym.kind == "class":
            return any(s.parent == sym.id for s in cm.symbols.values())
        return True  # a function always expands once into its internal steps
    menu, _scope = child_menu(coverage, cm, {})
    return bool(menu)
