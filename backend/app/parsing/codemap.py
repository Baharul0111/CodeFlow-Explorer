"""Code map data model (serialisable, compact) shared by parsing, pipeline and prompts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SymbolKind = Literal["function", "method", "class"]


class CallSite(BaseModel):
    name: str
    receiver: str | None = None
    line: int
    resolved: str | None = None  # symbol id when statically resolvable, else None (= unknown)
    arg_refs: list[str] = Field(default_factory=list)  # bare identifiers passed as arguments
    arg_resolved: list[str] = Field(default_factory=list)  # those that name project symbols


class Import(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    alias: str | None = None
    line: int
    resolved_file: str | None = None


class Symbol(BaseModel):
    id: str  # "path/to/file.py::Class.method"
    file: str
    name: str
    qualname: str
    kind: SymbolKind
    start_line: int
    end_line: int
    params: str = ""
    returns: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    parent: str | None = None  # enclosing class symbol id for methods
    calls: list[CallSite] = Field(default_factory=list)
    is_exported: bool = False

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def project_calls(self) -> list[CallSite]:
        return [c for c in self.calls if c.resolved]

    @property
    def is_leaf(self) -> bool:
        """Leaf rule: small (< 15 lines) or calls nothing else in the project."""
        return self.kind != "class" and (self.line_count < 15 or not self.project_calls)

    @property
    def is_trivial(self) -> bool:
        """Getters/setters/one-liners: summarised from static data without an LLM call."""
        if self.kind == "class":
            return False
        if self.line_count <= 3 and not self.calls:
            return True
        lowered = self.name.lower()
        accessor = lowered.startswith(("get_", "set_", "is_", "has_")) or lowered in {
            "__str__",
            "__repr__",
            "tostring",
            "getter",
            "setter",
        }
        return accessor and self.line_count <= 5 and not self.project_calls


class MainGuard(BaseModel):
    start_line: int
    end_line: int


class FileMap(BaseModel):
    path: str
    language: str
    lines: int
    symbols: list[str] = Field(default_factory=list)  # symbol ids, in source order
    imports: list[Import] = Field(default_factory=list)
    top_level_calls: list[CallSite] = Field(default_factory=list)
    main_guards: list[MainGuard] = Field(default_factory=list)
    parse_error: str | None = None


class EntryPoint(BaseModel):
    kind: str
    file: str
    line: int
    symbol_id: str | None = None
    detail: str = ""


class CodeMap(BaseModel):
    files: dict[str, FileMap]
    symbols: dict[str, Symbol]
    entry_points: list[EntryPoint] = Field(default_factory=list)
    unparsed_files: list[str] = Field(default_factory=list)  # code files without a grammar

    def file_symbols(self, path: str) -> list[Symbol]:
        fm = self.files.get(path)
        return [self.symbols[s] for s in fm.symbols if s in self.symbols] if fm else []

    def functions(self) -> list[Symbol]:
        return [s for s in self.symbols.values() if s.kind != "class"]

    def callers_of(self, symbol_id: str) -> list[Symbol]:
        return [s for s in self.symbols.values() if any(c.resolved == symbol_id for c in s.calls)]

    def module_of(self, path: str) -> str:
        return path.rsplit("/", 1)[0] if "/" in path else "."

    def modules(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for path in self.files:
            out.setdefault(self.module_of(path), []).append(path)
        return out

    def stats(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "functions": sum(1 for s in self.symbols.values() if s.kind != "class"),
            "classes": sum(1 for s in self.symbols.values() if s.kind == "class"),
            "resolved_calls": sum(len(s.project_calls) for s in self.symbols.values()),
            "unresolved_calls": sum(
                len(s.calls) - len(s.project_calls) for s in self.symbols.values()
            ),
            "entry_points": len(self.entry_points),
        }
