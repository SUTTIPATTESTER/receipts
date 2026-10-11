"""The verifier: turn a receipt into a verdict by running it.

The verdict comes from exit codes and output, never from a model's opinion.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import workspace as ws
from .policy import Policy
from .sandbox import RunResult, Sandbox, SandboxError
from .spec import MAX_RECEIPT_BYTES, Receipt, ReceiptError, parse_receipt

GOOD = frozenset({"verified", "reproduced"})

VERDICTS = (
    "verified", "reproduced", "vacuous", "wrong-failure", "not-fixed",
    "unreproducible", "no-change", "timeout", "missing", "invalid", "error",
)

LABELS = {
    "verified": "receipt:verified",
    "reproduced": "receipt:verified",
    "vacuous": "receipt:needs-work",
    "wrong-failure": "receipt:needs-work",
    "not-fixed": "receipt:needs-work",
    "unreproducible": "receipt:needs-work",
    "no-change": "receipt:needs-work",
    "timeout": "receipt:needs-work",
    "missing": "receipt:missing",
    "invalid": "receipt:invalid",
    "error": None,  # infrastructure trouble: never blame the contributor
}
ALL_LABELS = ("receipt:verified", "receipt:needs-work", "receipt:missing", "receipt:invalid")

SUMMARIES = {
    "verified": "Fails on the base tree, passes with the change.",
    "reproduced": "The bug reproduces on the base tree.",
    "vacuous": "The receipt already passes without the change, so it proves nothing yet.",
    "wrong-failure": "It fails, but not in the way the receipt describes.",
    "not-fixed": "Still failing with the change applied.",
    "unreproducible": "The command succeeded, so the bug did not reproduce.",
    "no-change": "Nothing besides the receipt itself was changed.",
    "timeout": "The command ran out of time.",
    "missing": "No receipt was found.",
    "invalid": "The receipt is not valid.",
    "error": "Verification could not run.",
}

OUTCOMES = ("fail", "pass", "timeout", "error", "unrunnable", "not-run")


@dataclass
class RunInfo:
    name: str  # "base" | "head"
    expected: str  # "fail" | "pass"
    outcome: str
    exit_code: int | None
    duration_s: float
    output: str


@dataclass
class Verdict:
    verdict: str
    summary: str = ""
    kind: str | None = None
    title: str | None = None
    command: str | None = None
    signature: str | None = None
    runs: list[RunInfo] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    subject: dict | None = None
    docs_url: str | None = None
    receipts_version: str = __version__
    schema: int = 1

    def __post_init__(self):
        if not self.summary:
            self.summary = SUMMARIES.get(self.verdict, "")

    @property
    def good(self) -> bool:
        return self.verdict in GOOD

    @property
    def label(self) -> str | None:
        return LABELS.get(self.verdict)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "receipts_version": self.receipts_version,
            "verdict": self.verdict,
            "good": self.good,
            "label": self.label,
            "summary": self.summary,
            "kind": self.kind,
            "title": self.title,
            "command": self.command,
            "signature": self.signature,
            "runs": [r.__dict__.copy() for r in self.runs],
            "notes": list(self.notes),
            "subject": self.subject,
            "docs_url": self.docs_url,
        }


def discover_receipt(base: Path, head: Path) -> tuple[Path | None, list[Path]]:
    """Find receipts a PR added or changed under .receipts/ (policy.toml excluded)."""
    folder = head / ".receipts"
    if not folder.is_dir():
        return None, []
    found: list[Path] = []
    for path in sorted(folder.glob("*.toml")):
        if path.name == "policy.toml" or path.is_symlink() or not path.is_file():
            continue
        twin = base / ".receipts" / path.name
        if not twin.is_file() or twin.read_bytes() != path.read_bytes():
            found.append(path)
    return (found[0] if found else None), found


def _outcome(result: RunResult) -> str:
    if result.error:
        return "error"
    if result.timed_out:
        return "timeout"
    if result.exit_code in (126, 127):
        return "unrunnable"
    return "pass" if result.exit_code == 0 else "fail"


def _info(name: str, expected: str, result: RunResult | None) -> RunInfo:
    if result is None:
        return RunInfo(name, expected, "not-run", None, 0.0, "")
    return RunInfo(name, expected, _outcome(result), result.exit_code,
                   round(result.duration_s, 3), result.output)


def _is_receipt_file(path: str, receipt: Receipt) -> bool:
    if path.startswith(".receipts/"):
        return True
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in receipt.receipt_paths)


def run_verification(*, base_dir: Path, head_dir: Path | None, receipt_path: Path | None,
                     policy: Policy, sandbox: Sandbox, kind: str | None = None) -> Verdict:
    notes: list[str] = []
    docs_url = policy.docs_url

    def done(verdict: str, summary: str = "", **extra) -> Verdict:
        extra.setdefault("kind", kind)
        extra.setdefault("notes", notes)
        return Verdict(verdict, summary, docs_url=docs_url, **extra)

    if receipt_path is None and head_dir is not None:
        receipt_path, found = discover_receipt(base_dir, head_dir)
        if len(found) > 1:
            notes.append(f"{len(found)} receipts were added; only {found[0].name} was checked.")
    if receipt_path is None:
        return done("missing")

    try:
        if receipt_path.stat().st_size > MAX_RECEIPT_BYTES:
            raise ReceiptError("receipt is larger than 256 KiB")
        receipt = parse_receipt(receipt_path.read_text(encoding="utf-8"))
    except (ReceiptError, OSError, UnicodeDecodeError) as exc:
        return done("invalid", f"The receipt is not valid: {exc}")

    common = dict(kind=receipt.kind, title=receipt.title,
                  command=receipt.command, signature=receipt.signature)
    if kind and kind != receipt.kind:
        return done("invalid", f"Expected a {kind!r} receipt but this one is {receipt.kind!r}.", **common)
    if receipt.kind == "fix" and head_dir is None:
        return done("invalid", "A fix receipt needs a head tree to compare against.", **common)
    if receipt.kind == "bug" and head_dir is not None:
        notes.append("This is a bug receipt, so the head tree was ignored.")
        head_dir = None

    timeout = min(receipt.timeout, policy.max_timeout)
    if timeout < receipt.timeout:
        notes.append(f"Timeout reduced from {receipt.timeout}s to the policy maximum of {timeout}s.")

    work = Path(tempfile.mkdtemp(prefix="receipts-"))
    try:
        base = work / "base"
        skipped = ws.copy_tree(base_dir, base)
        head = None
        if receipt.kind == "fix":
            head = work / "head"
            skipped += ws.copy_tree(head_dir, head)
            real_changes = [p for p in ws.changed_files(base, head) if not _is_receipt_file(p, receipt)]
            if not real_changes:
                return done("no-change", **common)
            missing = ws.apply_overlay(head, base, receipt.overlay)
            if missing:
                return done("invalid", "run.overlay lists files that are not in the pull request: "
                            + ", ".join(missing), **common)
        if skipped:
            notes.append(f"{len(skipped)} symlink(s)/special file(s) were not copied into the sandbox.")

        trees = [base] + ([head] if head else [])
        for tree in trees:
            ws.write_embedded(tree, receipt.files)

        sandbox.prepare()
        if policy.setup:
            for tree in trees:
                res = sandbox.run(tree, policy.setup, timeout=policy.setup_timeout, network=True)
                if res.error or res.timed_out or res.exit_code != 0:
                    notes.append("The maintainers' setup command failed; this is not a problem with the receipt.")
                    return done("error", "Setup failed before the receipt could run.", **common)

        runs: list[RunInfo] = []

        def finish(verdict: str, summary: str = "") -> Verdict:
            return done(verdict, summary, runs=runs, **common)

        base_res = sandbox.run(base, receipt.command, timeout=timeout)
        base_info = _info("base", "fail", base_res)
        runs.append(base_info)
        if base_info.outcome == "error":
            notes.append(base_res.error or "sandbox error")
            return finish("error", "The sandbox could not run the command.")
        if base_info.outcome == "timeout":
            return finish("timeout", f"The command did not finish within {timeout}s on the base tree.")
        if base_info.outcome == "unrunnable":
            return finish("invalid", "The command could not be started (exit code "
                          f"{base_info.exit_code}). Check run.command.")
        if base_info.outcome == "pass":
            if receipt.kind == "bug":
                return finish("unreproducible")
            runs.append(_info("head", "pass", None))
            return finish("vacuous")
        if receipt.signature and receipt.signature not in base_res.output:
            if receipt.kind == "fix":
                runs.append(_info("head", "pass", None))
            return finish("wrong-failure")
        if receipt.kind == "bug":
            return finish("reproduced")

        head_res = sandbox.run(head, receipt.command, timeout=timeout)
        head_info = _info("head", "pass", head_res)
        runs.append(head_info)
        if head_info.outcome == "error":
            notes.append(head_res.error or "sandbox error")
            return finish("error", "The sandbox could not run the command.")
        if head_info.outcome == "timeout":
            return finish("timeout", f"The command did not finish within {timeout}s with the change applied.")
        if head_info.outcome == "pass":
            return finish("verified")
        return finish("not-fixed")
    except (SandboxError, ws.WorkspaceError) as exc:
        notes.append(str(exc))
        return done("error", "Verification could not run.", **common)
    finally:
        ws.rmtree_force(work)
