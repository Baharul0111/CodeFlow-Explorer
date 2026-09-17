#!/usr/bin/env python3
"""Zip every sample project into samples/dist/ so they can be uploaded as-is."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

SAMPLES = ["flask-todo", "node-orders-api", "react-dashboard", "python-csv-report"]
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", ".venv"}


def build(root: Path, name: str, out_dir: Path) -> Path:
    source = root / name
    if not source.is_dir():
        raise SystemExit(f"Sample {name} is missing from {root}")
    target = out_dir / f"{name}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                archive.write(path, f"{name}/{path.relative_to(source).as_posix()}")
    return target


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "dist"
    out_dir.mkdir(exist_ok=True)
    for name in SAMPLES:
        target = build(root, name, out_dir)
        print(f"{target.relative_to(root.parent)}  ({target.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
