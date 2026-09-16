from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from app.pipeline.unzip import ExtractResult, UnsafeZipError, ZipLimits, safe_extract
from tests.helpers import make_zip

LIMITS = ZipLimits(max_unzipped_bytes=5 * 1024 * 1024, max_files=50, max_compression_ratio=100)


def _write(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "in.zip"
    p.write_bytes(data)
    return p


def _extract(tmp_path: Path, data: bytes, limits: ZipLimits = LIMITS) -> ExtractResult:
    return safe_extract(_write(tmp_path, data), tmp_path / "out", limits)


def test_extracts_and_detects_common_root(tmp_path: Path) -> None:
    res = _extract(tmp_path, make_zip({"a.py": "print(1)", "pkg/b.py": "x=1"}, root="proj"))
    assert res.root == tmp_path / "out" / "proj"
    assert (res.root / "pkg" / "b.py").read_text() == "x=1"
    assert res.file_count == 2


def test_no_common_root_when_loose_files(tmp_path: Path) -> None:
    res = _extract(tmp_path, make_zip({"a.py": "1", "pkg/b.py": "2"}))
    assert res.root == tmp_path / "out"


@pytest.mark.parametrize(
    "bad", ["../evil.py", "/etc/passwd", "a/../../evil", "C:\\win\\x", "..\\x"]
)
def test_zip_slip_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(UnsafeZipError, match="unsafe path"):
        _extract(tmp_path, make_zip({bad: "x", "ok.py": "y"}))
    assert not (tmp_path / "evil.py").exists()


def test_symlink_rejected(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "../../etc/passwd")
        zf.writestr("ok.py", "y")
    with pytest.raises(UnsafeZipError, match="symbolic link"):
        _extract(tmp_path, buf.getvalue())


def test_zip_bomb_ratio_rejected(tmp_path: Path) -> None:
    payload = b"0" * (3 * 1024 * 1024)  # compresses ~1000x
    with pytest.raises(UnsafeZipError, match="zip bomb"):
        _extract(tmp_path, make_zip({"bomb.txt": payload}))


def test_declared_size_over_limit_rejected(tmp_path: Path) -> None:
    payload = os.urandom(2 * 1024 * 1024)  # incompressible, so the ratio check stays quiet
    limits = ZipLimits(max_unzipped_bytes=1024 * 1024, max_files=50)
    with pytest.raises(UnsafeZipError, match="unpacks to more than"):
        _extract(tmp_path, make_zip({"big.bin": payload}), limits)


def test_too_many_files_rejected(tmp_path: Path) -> None:
    files = {f"f{i}.py": "x" for i in range(60)}
    with pytest.raises(UnsafeZipError, match="entries"):
        _extract(tmp_path, make_zip(files))


def test_encrypted_rejected(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("secret.py", "x")
        zf.filelist[0].flag_bits |= 0x1  # mark as encrypted in the central directory
    with pytest.raises(UnsafeZipError, match="password"):
        _extract(tmp_path, buf.getvalue())


def test_not_a_zip(tmp_path: Path) -> None:
    with pytest.raises(UnsafeZipError, match="not a valid zip"):
        _extract(tmp_path, b"definitely not a zip")


def test_empty_zip(tmp_path: Path) -> None:
    with pytest.raises(UnsafeZipError, match="no files"):
        _extract(tmp_path, make_zip({}))


def test_running_counter_catches_lying_headers(tmp_path: Path) -> None:
    """A header can under-report file_size; the streaming counter must still enforce the cap."""
    data = make_zip({"a.txt": b"x" * 4096})
    # Patch the central-directory size field of the only entry to claim 10 bytes.
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = zf.infolist()[0]
    assert info.file_size == 4096
    limits = ZipLimits(max_unzipped_bytes=1024, max_files=10)
    with pytest.raises(UnsafeZipError, match="unpacks to more than"):
        _extract(tmp_path, data, limits)
