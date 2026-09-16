from __future__ import annotations

import io
import zipfile
from pathlib import Path


def make_zip(files: dict[str, bytes | str], *, root: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            arc = f"{root}/{name}" if root else name
            zf.writestr(arc, data)
    return buf.getvalue()


def zip_dir(directory: Path, *, root: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                rel = path.relative_to(directory).as_posix()
                zf.write(path, f"{root}/{rel}" if root else rel)
    return buf.getvalue()
