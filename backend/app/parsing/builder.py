"""Build the :class:`CodeMap` for a scanned project (parallel parse, resolve, entry points)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.logging_setup import get_logger
from app.parsing.codemap import CodeMap, FileMap
from app.parsing.entrypoints import detect_entry_points
from app.parsing.extractor import Extraction, extract_file
from app.parsing.languages import grammar_key, is_parseable
from app.parsing.resolve import Resolver
from app.pipeline.scan import Language as LanguageName
from app.pipeline.scan import ScanResult

log = get_logger(__name__)
CODEMAP_FILE = "codemap.json"


def _parse_one(root: Path, path: str, language: LanguageName) -> Extraction:
    source = (root / path).read_bytes()
    return extract_file(path, grammar_key(language, path), source, language)


def build_codemap(root: Path, scan: ScanResult, *, workers: int = 4) -> CodeMap:
    code_files = [f for f in scan.files if f.language != "text"]
    parseable = [f for f in code_files if is_parseable(f.language)]
    unparsed = [f.path for f in code_files if not is_parseable(f.language)]
    files: dict[str, FileMap] = {}
    symbols = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_parse_one, root, f.path, f.language) for f in parseable]
        for fut in futures:
            try:
                ex = fut.result()
            except Exception as exc:  # unreadable file etc. — never fatal
                log.warning("parse_failed", error=str(exc))
                continue
            files[ex.file.path] = ex.file
            for sym in ex.symbols:
                symbols[sym.id] = sym
    for f in unparsed:
        files[f] = FileMap(path=f, language="text", lines=0, parse_error="no grammar")
    resolver = Resolver(files, symbols)
    resolver.resolve_all_imports()
    resolver.resolve_all_calls()
    cm = CodeMap(files=files, symbols=symbols, unparsed_files=unparsed)
    cm.entry_points = detect_entry_points(cm, scan.entry_hints)
    log.info("codemap_built", **cm.stats())
    return cm


def save_codemap(cm: CodeMap, project_dir: Path) -> Path:
    target = project_dir / CODEMAP_FILE
    target.write_text(cm.model_dump_json(exclude_none=True), encoding="utf-8")
    return target


def load_codemap(project_dir: Path) -> CodeMap | None:
    target = project_dir / CODEMAP_FILE
    if not target.exists():
        return None
    return CodeMap.model_validate(json.loads(target.read_text(encoding="utf-8")))
