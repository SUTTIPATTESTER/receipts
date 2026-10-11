"""Receipt files (spec v1): parsing and strict validation.

A receipt is a small TOML document that turns a claim into something a machine
can run. Everything in it is untrusted input, so parsing is strict and fails
closed: unknown keys, odd paths and oversized values are all rejected.
See spec/RECEIPT.md for the human-readable specification.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath

SPEC_VERSION = 1
KINDS = ("bug", "fix")

MAX_RECEIPT_BYTES = 256 * 1024
MAX_TITLE = 200
MAX_COMMAND = 2000
MAX_SIGNATURE = 300
MIN_SIGNATURE = 4
MAX_FILES = 20
MAX_FILE_BYTES = 64 * 1024
MAX_OVERLAY = 50
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 3600

_TOP_KEYS = {"version", "kind", "title", "closes", "run", "expect", "file"}
_RUN_KEYS = {"command", "timeout", "overlay"}
_EXPECT_KEYS = {"fail_output_contains"}
_FILE_KEYS = {"path", "content"}

_FORBIDDEN_TOP = {".git", ".github"}
_FORBIDDEN_EXACT = {".receipts/policy.toml"}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class ReceiptError(ValueError):
    """The receipt is malformed or breaks a rule of the spec."""


@dataclass(frozen=True)
class EmbeddedFile:
    path: str
    content: str


@dataclass(frozen=True)
class Receipt:
    kind: str
    title: str
    command: str
    timeout: int = DEFAULT_TIMEOUT
    signature: str | None = None
    overlay: tuple[str, ...] = ()
    files: tuple[EmbeddedFile, ...] = ()
    closes: str | None = None

    @property
    def receipt_paths(self) -> frozenset[str]:
        """Paths that belong to the receipt itself (tests, repro scripts)."""
        return frozenset(self.overlay) | {f.path for f in self.files}


def clean_rel_path(raw: object, *, what: str = "path") -> str:
    """Normalise a repo-relative POSIX path, or raise ReceiptError."""
    if not isinstance(raw, str) or not raw.strip():
        raise ReceiptError(f"{what} must be a non-empty string")
    if len(raw) > 200 or "\\" in raw or any(ord(c) < 32 for c in raw):
        raise ReceiptError(f"{what} {raw[:60]!r} contains forbidden characters")
    path = PurePosixPath(raw)
    if path.is_absolute() or _DRIVE_RE.match(raw):
        raise ReceiptError(f"{what} {raw!r} must be relative to the repository root")
    parts = path.parts
    if not parts or ".." in parts:
        raise ReceiptError(f"{what} {raw!r} must stay inside the repository")
    normal = "/".join(parts)
    if parts[0] in _FORBIDDEN_TOP or normal in _FORBIDDEN_EXACT:
        raise ReceiptError(f"{what} {raw!r} points at a protected location")
    return normal


def _table(data: dict, key: str, *, required: bool = False) -> dict:
    value = data.get(key)
    if value is None:
        if required:
            raise ReceiptError(f"missing required table [{key}]")
        return {}
    if not isinstance(value, dict):
        raise ReceiptError(f"[{key}] must be a table")
    return value


def _reject_unknown(table: dict, allowed: set[str], where: str) -> None:
    extra = sorted(set(table) - allowed)
    if extra:
        names = ", ".join(repr(k) for k in extra)
        raise ReceiptError(f"unknown key(s) in {where}: {names}")


def _line(value: object, name: str, *, max_len: int, min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise ReceiptError(f"{name} must be a string")
    if any(ord(c) < 32 and c != "\t" for c in value):
        raise ReceiptError(f"{name} must be a single line without control characters")
    text = value.strip()
    if len(text) < min_len:
        raise ReceiptError(f"{name} is too short (minimum {min_len} characters)")
    if len(text) > max_len:
        raise ReceiptError(f"{name} is too long (maximum {max_len} characters)")
    return text


def parse_receipt(text: str) -> Receipt:
    if len(text.encode("utf-8", "replace")) > MAX_RECEIPT_BYTES:
        raise ReceiptError("receipt is larger than 256 KiB")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReceiptError(f"not valid TOML: {exc}") from None

    _reject_unknown(data, _TOP_KEYS, "the top level")
    if type(data.get("version")) is not int or data["version"] != SPEC_VERSION:
        raise ReceiptError(f"version must be {SPEC_VERSION}")
    kind = data.get("kind")
    if kind not in KINDS:
        raise ReceiptError(f"kind must be one of: {', '.join(KINDS)}")
    title = _line(data.get("title"), "title", max_len=MAX_TITLE)
    closes = data.get("closes")
    if closes is not None:
        closes = _line(closes, "closes", max_len=40)

    run = _table(data, "run", required=True)
    _reject_unknown(run, _RUN_KEYS, "[run]")
    command = _line(run.get("command"), "run.command", max_len=MAX_COMMAND)
    timeout = run.get("timeout", DEFAULT_TIMEOUT)
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        raise ReceiptError(f"run.timeout must be an integer from 1 to {MAX_TIMEOUT} seconds")
    overlay_raw = run.get("overlay", [])
    if not isinstance(overlay_raw, list) or len(overlay_raw) > MAX_OVERLAY:
        raise ReceiptError(f"run.overlay must be a list of at most {MAX_OVERLAY} paths")
    overlay = tuple(clean_rel_path(p, what="run.overlay entry") for p in overlay_raw)
    if overlay and kind == "bug":
        raise ReceiptError("run.overlay only makes sense for kind = \"fix\" (a bug has no head tree)")

    expect = _table(data, "expect")
    _reject_unknown(expect, _EXPECT_KEYS, "[expect]")
    signature = expect.get("fail_output_contains")
    if signature is not None:
        signature = _line(signature, "expect.fail_output_contains",
                          max_len=MAX_SIGNATURE, min_len=MIN_SIGNATURE)
        if signature in command:
            raise ReceiptError(
                "expect.fail_output_contains appears in run.command: the failure must be "
                "produced by the code under test, not echoed by the receipt")
    if kind == "bug" and signature is None:
        raise ReceiptError(
            "a bug receipt must say how it fails: set expect.fail_output_contains "
            "(for example the exception name or assertion message)")

    files_raw = data.get("file", [])
    if not isinstance(files_raw, list) or len(files_raw) > MAX_FILES:
        raise ReceiptError(f"at most {MAX_FILES} [[file]] entries are allowed")
    files: list[EmbeddedFile] = []
    seen: set[str] = set()
    for entry in files_raw:
        if not isinstance(entry, dict):
            raise ReceiptError("each [[file]] entry must be a table")
        _reject_unknown(entry, _FILE_KEYS, "[[file]]")
        path = clean_rel_path(entry.get("path"), what="file.path")
        content = entry.get("content")
        if not isinstance(content, str):
            raise ReceiptError(f"file {path!r}: content must be a string")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ReceiptError(f"file {path!r} is larger than {MAX_FILE_BYTES // 1024} KiB")
        if path in seen or path in overlay:
            raise ReceiptError(f"file {path!r} is listed twice")
        seen.add(path)
        files.append(EmbeddedFile(path, content))

    return Receipt(kind=kind, title=title, command=command, timeout=timeout,
                   signature=signature, overlay=overlay, files=tuple(files), closes=closes)
