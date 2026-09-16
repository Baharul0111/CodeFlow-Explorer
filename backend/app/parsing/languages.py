"""Grammar registry: maps our language names to loaded tree-sitter ``Language`` objects."""

from __future__ import annotations

import importlib
from functools import cache
from pathlib import Path

from tree_sitter import Language, Parser

from app.pipeline.scan import Language as LanguageName
from app.pipeline.scan import detect_language

PARSEABLE: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "c",
        "cpp",
        "csharp",
        "ruby",
        "php",
        "rust",
    }
)

# Grammar key -> loader. Grammar keys differ from language names where one language has
# several grammars (typescript vs tsx) or a grammar module exposes several entry points (php).
_LOADERS = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "java": ("tree_sitter_java", "language"),
    "go": ("tree_sitter_go", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "csharp": ("tree_sitter_c_sharp", "language"),
    "ruby": ("tree_sitter_ruby", "language"),
    "php": ("tree_sitter_php", "language_php"),
    "rust": ("tree_sitter_rust", "language"),
}


def grammar_key(language: LanguageName, path: str) -> str:
    """Pick the grammar for a file (TS files with JSX need the tsx grammar)."""
    if language == "typescript":
        return "tsx" if path.lower().endswith(".tsx") else "typescript"
    if language == "javascript":
        return "javascript"
    return language


@cache
def load_language(key: str) -> Language:
    module_name, attr = _LOADERS[key]
    module = importlib.import_module(module_name)
    return Language(getattr(module, attr)())


def make_parser(key: str) -> Parser:
    return Parser(load_language(key))


def is_parseable(language: str) -> bool:
    return language in PARSEABLE


def guess_language_for_path(path: Path) -> LanguageName | None:
    lang = detect_language(path)
    return lang if lang is not None and lang != "text" else None
