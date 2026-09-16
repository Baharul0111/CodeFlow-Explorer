"""Safe zip extraction.

Defends against zip-slip (``../`` and absolute paths), symlinks and special files, zip bombs
(declared size, compression ratio and a running byte counter while streaming) and oversized
archives. Nothing is ever executed; entries are copied byte-for-byte to ``dest``.
"""

from __future__ import annotations

import posixpath
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.api.errors import AppError

CHUNK = 1024 * 1024
MIN_RATIO_CHECK_BYTES = 1024 * 1024  # ratio checks only matter once the payload is non-trivial


class UnsafeZipError(AppError):
    status_code = 400
    code = "unsafe_zip"


@dataclass(frozen=True)
class ZipLimits:
    max_unzipped_bytes: int
    max_files: int
    max_compression_ratio: float = 100.0


@dataclass
class ExtractResult:
    root: Path
    file_count: int
    total_bytes: int
    skipped: list[str] = field(default_factory=list)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _is_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)


def _safe_relative(name: str) -> str | None:
    """Return a normalised relative POSIX path, or ``None`` if the entry must be rejected."""
    if "\x00" in name:
        return None
    norm = name.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return None
    norm = posixpath.normpath(norm)
    if norm in (".", "") or norm.startswith("../") or norm == ".." or "/../" in f"/{norm}/":
        return None
    return norm


def _validate_entries(
    zf: zipfile.ZipFile, limits: ZipLimits
) -> tuple[list[tuple[zipfile.ZipInfo, str]], int]:
    infos = zf.infolist()
    if len(infos) > limits.max_files:
        raise UnsafeZipError(
            f"This zip has {len(infos):,} entries; the limit is {limits.max_files:,} files."
        )
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    declared = 0
    compressed = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise UnsafeZipError(
                "This zip is password protected. Please upload an unencrypted zip."
            )
        rel = _safe_relative(info.filename)
        if rel is None:
            raise UnsafeZipError(
                f"This zip contains an unsafe path ({info.filename!r}). Upload was rejected."
            )
        if _is_symlink(info):
            raise UnsafeZipError(
                f"This zip contains a symbolic link ({info.filename!r}). Links are not allowed."
            )
        if _is_special(info):
            raise UnsafeZipError(f"This zip contains a special file ({info.filename!r}).")
        if info.is_dir():
            continue
        declared += info.file_size
        compressed += info.compress_size
        if declared > limits.max_unzipped_bytes:
            raise UnsafeZipError(
                "This zip unpacks to more than "
                f"{limits.max_unzipped_bytes // (1024 * 1024):,} MB. Upload was rejected."
            )
        if info.file_size > MIN_RATIO_CHECK_BYTES and info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise UnsafeZipError(
                    "This zip looks like a zip bomb (a file expands "
                    f"{ratio:,.0f}x). Upload was rejected."
                )
        entries.append((info, rel))
    if declared > MIN_RATIO_CHECK_BYTES and compressed > 0:
        ratio = declared / compressed
        if ratio > limits.max_compression_ratio:
            raise UnsafeZipError(
                f"This zip looks like a zip bomb (it expands {ratio:,.0f}x). Upload was rejected."
            )
    return entries, declared


def _common_root(entries: list[tuple[zipfile.ZipInfo, str]]) -> str | None:
    tops = {rel.split("/", 1)[0] for _, rel in entries if "/" in rel}
    loose = [rel for _, rel in entries if "/" not in rel]
    if len(tops) == 1 and not loose:
        return next(iter(tops))
    return None


def safe_extract(zip_path: Path, dest: Path, limits: ZipLimits) -> ExtractResult:
    """Extract ``zip_path`` into ``dest`` (created if needed) and return the project root."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnsafeZipError("This file is not a valid zip archive.") from exc
    with zf:
        entries, _declared = _validate_entries(zf, limits)
        if not entries:
            raise UnsafeZipError("This zip contains no files.")
        dest.mkdir(parents=True, exist_ok=True)
        dest_resolved = dest.resolve()
        written = 0
        skipped: list[str] = []
        for info, rel in entries:
            target = (dest / rel).resolve()
            if dest_resolved not in target.parents:
                raise UnsafeZipError(
                    f"This zip contains an unsafe path ({info.filename!r}). Upload was rejected."
                )
            if target.exists() and target.is_dir():
                skipped.append(rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limits.max_unzipped_bytes:
                        raise UnsafeZipError(
                            "This zip unpacks to more than "
                            f"{limits.max_unzipped_bytes // (1024 * 1024):,} MB. "
                            "Upload was rejected."
                        )
                    out.write(chunk)
        root_name = _common_root(entries)
        root = dest / root_name if root_name else dest
        return ExtractResult(
            root=root, file_count=len(entries) - len(skipped), total_bytes=written, skipped=skipped
        )
