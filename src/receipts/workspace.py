"""Throwaway working trees.

Verification never runs inside the caller's checkout. Each tree is exported or
copied into a temp directory first, symlinks are dropped, and the directory is
deleted afterwards.
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SKIP_DIRS = frozenset({".git", "__pycache__"})
MAX_EXPORT_BYTES = 1024 * 1024 * 1024
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~+-]{0,199}$")


class WorkspaceError(RuntimeError):
    pass


def rmtree_force(path: Path) -> None:
    """Delete a tree, including read-only files (common on Windows)."""

    def fix(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def copy_tree(src: Path, dst: Path) -> list[str]:
    """Copy regular files only. Returns the paths that were skipped (symlinks etc.)."""
    skipped: list[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src, followlinks=False):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        kept = []
        for name in dirs:
            if name in SKIP_DIRS:
                continue
            if (root_path / name).is_symlink():
                skipped.append((rel / name).as_posix())
                continue
            kept.append(name)
        dirs[:] = kept
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            source = root_path / name
            if source.is_symlink() or not source.is_file():
                skipped.append((rel / name).as_posix())
                continue
            shutil.copy2(source, dst / rel / name)
    return skipped


def _index(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            full = Path(current) / name
            if full.is_symlink():
                continue
            out[full.relative_to(root).as_posix()] = full.stat().st_size
    return out


def changed_files(base: Path, head: Path) -> list[str]:
    """Files added, removed or modified between two trees (POSIX relative paths)."""
    a, b = _index(base), _index(head)
    changed = []
    for path in sorted(set(a) | set(b)):
        if path not in a or path not in b or a[path] != b[path]:
            changed.append(path)
        elif not filecmp.cmp(base / path, head / path, shallow=False):
            changed.append(path)
    return changed


def _inside(root: Path, target: Path) -> bool:
    return target.resolve().is_relative_to(root.resolve())


def write_embedded(root: Path, files) -> None:
    for item in files:
        target = root / item.path
        if not _inside(root, target):
            raise WorkspaceError(f"refusing to write outside the tree: {item.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content.encode("utf-8"))


def apply_overlay(head: Path, base: Path, overlay) -> list[str]:
    """Copy the receipt's own files (tests, repro scripts) from head onto base.

    Returns the overlay entries that do not exist in the head tree.
    """
    missing: list[str] = []
    for rel in overlay:
        source, target = head / rel, base / rel
        if not (_inside(head, source) and _inside(base, target)):
            raise WorkspaceError(f"refusing to copy outside the tree: {rel}")
        if source.is_symlink() or not source.exists():
            missing.append(rel)
            continue
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            copy_tree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return missing


def safe_extract(tar: tarfile.TarFile, dest: Path) -> list[str]:
    """Extract regular files and directories only; refuse path traversal."""
    skipped: list[str] = []
    root = dest.resolve()
    total = 0
    for member in tar:
        name = member.name
        pure = PurePosixPath(name)
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            skipped.append(name)
            continue
        if pure.is_absolute() or ".." in pure.parts:
            raise WorkspaceError(f"unsafe path in archive: {name!r}")
        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise WorkspaceError(f"unsafe path in archive: {name!r}")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            skipped.append(name)
            continue
        total += member.size
        if total > MAX_EXPORT_BYTES:
            raise WorkspaceError("repository export is larger than 1 GiB")
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = tar.extractfile(member)
        if extracted is None:
            continue
        with extracted, open(target, "wb") as out:
            shutil.copyfileobj(extracted, out)
        if os.name != "nt" and member.mode & 0o111:
            os.chmod(target, 0o755)
    return skipped


def export_ref(repo: Path, ref: str, dest: Path) -> list[str]:
    """Export a git ref into dest without a .git directory (no hooks, no config)."""
    if not _REF_RE.fullmatch(ref):
        raise WorkspaceError(f"refusing suspicious git ref {ref!r}")
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as archive:
        proc = subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", ref],
            stdout=archive, stderr=subprocess.PIPE, timeout=600, check=False)
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
            raise WorkspaceError(f"git archive {ref} failed: {detail}")
        archive.seek(0)
        with tarfile.open(fileobj=archive, mode="r:") as tar:
            return safe_extract(tar, dest)
