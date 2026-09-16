from __future__ import annotations

from pathlib import Path

from app.pipeline.scan import ScanLimits, build_tree, detect_language, scan_project


def _mk(root: Path, files: dict[str, bytes | str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            p.write_text(content)
        else:
            p.write_bytes(content)


def test_scan_filters_and_detects(tmp_path: Path) -> None:
    _mk(
        tmp_path,
        {
            "README.md": "# Demo app\n\nDoes things.\n",
            "package.json": '{"main": "src/index.js", "scripts": {"start": "node src/index.js"}, "dependencies": {"express": "^4"}}',
            "src/index.js": "const express = require('express');\n",
            "src/util.ts": "export const x = 1;\n",
            "src/types.d.ts": "export type X = 1;\n",
            "node_modules/express/index.js": "module.exports = {}\n",
            "dist/bundle.min.js": "x" * 3000,
            "package-lock.json": "{}",
            "logo.png": b"\x89PNG\x00\x00",
            "data.bin": b"\x00\x01\x02",
            "big.py": "x = 1\n" * 300_000,
            ".gitignore": "secrets/\n*.log\n",
            "secrets/key.py": "KEY=1",
            "app.log": "log",
            "Dockerfile": 'FROM node\nCMD ["node", "src/index.js"]\n',
            "gen/model_pb2.py": "# generated\n",
            "tool/main.py": "def main():\n    pass\n",
        },
    )
    res = scan_project(tmp_path, ScanLimits(max_file_bytes=1_000_000))
    paths = {f.path for f in res.files}
    assert {
        "src/index.js",
        "src/util.ts",
        "tool/main.py",
        "README.md",
        "package.json",
        "Dockerfile",
    } <= paths
    assert "node_modules/express/index.js" not in paths
    assert "secrets/key.py" not in paths
    assert "app.log" not in paths
    reasons = {s.path: s.reason for s in res.skipped}
    assert reasons["node_modules/"] == "ignored_dir"
    assert reasons["secrets/"] == "gitignore"
    assert reasons["package-lock.json"] == "lock_file"
    assert reasons["logo.png"] == "media"
    assert reasons["data.bin"] == "binary"
    assert reasons["big.py"] == "too_large"
    assert reasons["gen/model_pb2.py"] == "generated"
    assert reasons["src/types.d.ts"] == "generated"
    assert res.languages["javascript"].files == 1
    assert res.languages["typescript"].files == 1
    assert res.languages["python"].files == 1
    assert "Express" in res.frameworks
    kinds = {(h.kind, h.detail) for h in res.entry_hints}
    assert ("package_main", "src/index.js") in kinds
    assert ("npm_script", "start: node src/index.js") in kinds
    assert any(k == "dockerfile_cmd" for k, _ in kinds)
    assert res.readme_excerpt.startswith("# Demo app")
    assert "src/" in res.tree and "index.js" in res.tree


def test_pyproject_scripts_and_frameworks(tmp_path: Path) -> None:
    _mk(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname="x"\ndependencies=["fastapi>=0.1", "sqlalchemy"]\n[project.scripts]\nmycli = "pkg.cli:main"\n',
            "pkg/cli.py": "def main():\n    pass\n",
        },
    )
    res = scan_project(tmp_path)
    assert {"FastAPI", "SQLAlchemy"} <= set(res.frameworks)
    assert any(h.kind == "pyproject_script" and "mycli" in h.detail for h in res.entry_hints)


def test_detect_language() -> None:
    assert detect_language(Path("a.tsx")) == "typescript"
    assert detect_language(Path("Dockerfile")) == "text"
    assert detect_language(Path("x.unknownext")) is None


def test_build_tree_elides_large_dirs() -> None:
    paths = [f"src/f{i}.py" for i in range(30)] + ["README.md"]
    tree = build_tree(paths, max_lines=100)
    assert "… 20 more files" in tree
    assert tree.splitlines()[0] == "src/"
