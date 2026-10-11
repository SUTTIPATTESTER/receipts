"""Command line interface: `receipts verify | extract | init | lint | render | bench`."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import __version__
from . import workspace as ws
from .bench import format_bench, run_bench
from .extract import extract_receipt
from .policy import PolicyError, load_policy
from .report import format_terminal, render_markdown, verdict_from_untrusted
from .sandbox import SandboxError, make_sandbox
from .spec import ReceiptError, parse_receipt
from .verify import ALL_LABELS, Verdict, run_verification

TEMPLATES = {
    "bug": '''\
version = 1
kind = "bug"
title = "average([]) raises ZeroDivisionError"   # one line: what is wrong?

[run]
command = "python repro.py"   # exits non-zero while the bug exists
timeout = 60

[expect]
# How must it fail? Name the exception / assertion text the *code under test* prints.
fail_output_contains = "ZeroDivisionError"

# Self-contained repro: this file is written into the repository before the command runs.
[[file]]
path = "repro.py"
content = """
import sys
sys.path.insert(0, "src")
from mathx import average
print(average([]))
"""
''',
    "fix": '''\
version = 1
kind = "fix"
title = "average([]) returns 0.0 instead of crashing"
closes = "#123"

[run]
command = "python tests/test_average_empty.py"   # fails before your change, passes after
overlay = ["tests/test_average_empty.py"]         # your test is copied onto the base tree for the "before" run
timeout = 60

[expect]
fail_output_contains = "ZeroDivisionError"        # optional for fixes, but it keeps the failure honest
''',
}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _color_enabled(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _parse_subject(value: str | None) -> dict | None:
    if not value:
        return None
    match = re.fullmatch(r"(issue|pull_request):([1-9][0-9]{0,9})", value)
    if not match:
        raise SystemExit("error: --subject must look like pull_request:12 or issue:7")
    return {"type": match.group(1), "number": int(match.group(2))}


def _append(env_name: str, text: str) -> None:
    target = os.environ.get(env_name)
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)


def _emit(verdict: Verdict, args: argparse.Namespace) -> None:
    print(format_terminal(verdict, color=_color_enabled(args.color)))
    if args.json_out:
        _write_text(Path(args.json_out), json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False) + "\n")
    markdown = render_markdown(verdict)
    if args.markdown_out:
        _write_text(Path(args.markdown_out), markdown)
    if args.github_summary:
        _append("GITHUB_STEP_SUMMARY", markdown + "\n")
    if args.github_output:
        _append("GITHUB_OUTPUT",
                f"verdict={verdict.verdict}\ngood={'true' if verdict.good else 'false'}\n"
                f"label={verdict.label or ''}\n")


def cmd_verify(args: argparse.Namespace) -> int:
    subject = _parse_subject(args.subject)
    if args.sandbox == "local" and not args.unsafe_local:
        print("error: the local sandbox is not a security boundary. Pass --unsafe-local to use it "
              "on trusted input, or use --sandbox docker.", file=sys.stderr)
        return 2
    if bool(args.repo) == bool(args.base_dir):
        print("error: give either --repo with --base-ref, or --base-dir", file=sys.stderr)
        return 2

    with contextlib.ExitStack() as stack:
        try:
            if args.repo:
                if not args.base_ref:
                    print("error: --repo needs --base-ref", file=sys.stderr)
                    return 2
                scratch = Path(tempfile.mkdtemp(prefix="receipts-export-"))
                stack.callback(ws.rmtree_force, scratch)
                base_dir = scratch / "base"
                ws.export_ref(Path(args.repo), args.base_ref, base_dir)
                head_dir = None
                if args.head_ref:
                    head_dir = scratch / "head"
                    ws.export_ref(Path(args.repo), args.head_ref, head_dir)
            else:
                base_dir = Path(args.base_dir)
                head_dir = Path(args.head_dir) if args.head_dir else None
                for folder in (base_dir, head_dir):
                    if folder is not None and not folder.is_dir():
                        print(f"error: {folder} is not a directory", file=sys.stderr)
                        return 2
        except ws.WorkspaceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        # Policy is trusted configuration: it only ever comes from the base tree (or --policy).
        policy_path = Path(args.policy) if args.policy else base_dir / ".receipts" / "policy.toml"
        try:
            policy = load_policy(policy_path)
        except (PolicyError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            sandbox = make_sandbox(args.sandbox, policy)
        except SandboxError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        verdict = run_verification(
            base_dir=base_dir, head_dir=head_dir,
            receipt_path=Path(args.receipt) if args.receipt else None,
            policy=policy, sandbox=sandbox, kind=args.kind)
        verdict.subject = subject
        _emit(verdict, args)

    if args.strict:
        return 0 if verdict.good else (2 if verdict.verdict == "error" else 1)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    body = Path(args.body_file)
    if not body.is_file():
        print(f"error: {body} not found", file=sys.stderr)
        return 2
    receipt = extract_receipt(body.read_text(encoding="utf-8", errors="replace"))
    if receipt is None:
        print("no ```receipt block found", file=sys.stderr)
        return 3
    _write_text(Path(args.out), receipt)
    print(f"wrote {args.out}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.exists() and not args.force:
        print(f"error: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    _write_text(target, TEMPLATES[args.kind])
    print(f"wrote {target}: edit it, then run `receipts lint {target}`")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    try:
        receipt = parse_receipt(Path(args.receipt).read_text(encoding="utf-8"))
    except (ReceiptError, OSError, UnicodeDecodeError) as exc:
        print(f"invalid: {exc}")
        return 1
    print(f"ok: {receipt.kind} receipt, {len(receipt.files)} embedded file(s), "
          f"{len(receipt.overlay)} overlay path(s), timeout {receipt.timeout}s")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    path = Path(args.verdict)
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("verdict file is larger than 2 MiB")
        verdict = verdict_from_untrusted(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        print(f"error: rejected verdict file: {exc}", file=sys.stderr)
        return 2
    _write_text(Path(args.markdown_out), render_markdown(verdict))
    subject = verdict.subject or {}
    # Every value below is an enum or an integer that was validated above: safe for GITHUB_OUTPUT.
    _append("GITHUB_OUTPUT",
            f"verdict={verdict.verdict}\nlabel={verdict.label or ''}\n"
            f"subject_type={subject.get('type', '')}\nsubject_number={subject.get('number', '')}\n"
            f"all_labels={','.join(ALL_LABELS)}\n")
    print(f"rendered {verdict.verdict} for {subject.get('type', '?')} #{subject.get('number', '?')}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    results = run_bench(Path(args.cases))
    print(format_bench(results, color=_color_enabled(args.color)))
    return 0 if all(r.ok for r in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="receipts", description="Verify bug reports and pull requests by running them.")
    parser.add_argument("--version", action="version", version=f"receipts {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="run a receipt and print a verdict")
    verify.add_argument("--base-dir", help="directory with the base tree (default branch)")
    verify.add_argument("--head-dir", help="directory with the head tree (the pull request)")
    verify.add_argument("--repo", help="git repository to export trees from")
    verify.add_argument("--base-ref", help="git ref of the base tree (with --repo)")
    verify.add_argument("--head-ref", help="git ref of the head tree (with --repo)")
    verify.add_argument("--receipt", help="receipt file (default: discovered under .receipts/ in the head tree)")
    verify.add_argument("--kind", choices=["bug", "fix"], help="require this kind of receipt")
    verify.add_argument("--policy", help="policy file (default: .receipts/policy.toml in the BASE tree)")
    verify.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    verify.add_argument("--unsafe-local", action="store_true",
                        help="allow the local sandbox, which is not a security boundary")
    verify.add_argument("--subject", help="pull_request:12 or issue:7 (recorded in the verdict)")
    verify.add_argument("--json-out", help="write verdict.json here")
    verify.add_argument("--markdown-out", help="write the PR comment here")
    verify.add_argument("--github-summary", action="store_true", help="append to $GITHUB_STEP_SUMMARY")
    verify.add_argument("--github-output", action="store_true", help="write outputs to $GITHUB_OUTPUT")
    verify.add_argument("--strict", action="store_true", help="exit 1 unless verified/reproduced (2 on error)")
    verify.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    verify.set_defaults(func=cmd_verify)

    extract = sub.add_parser("extract", help="extract a ```receipt block from an issue/PR body")
    extract.add_argument("--body-file", required=True)
    extract.add_argument("--out", required=True)
    extract.set_defaults(func=cmd_extract)

    init = sub.add_parser("init", help="write a receipt template")
    init.add_argument("--kind", choices=["bug", "fix"], default="bug")
    init.add_argument("--force", action="store_true")
    init.add_argument("path", nargs="?", default=".receipts/my-receipt.toml")
    init.set_defaults(func=cmd_init)

    lint = sub.add_parser("lint", help="check a receipt file for mistakes")
    lint.add_argument("receipt")
    lint.set_defaults(func=cmd_lint)

    render = sub.add_parser("render", help="validate an untrusted verdict.json and render the PR comment")
    render.add_argument("--verdict", required=True)
    render.add_argument("--markdown-out", required=True)
    render.set_defaults(func=cmd_render)

    bench = sub.add_parser("bench", help="run the benchmark corpus")
    bench.add_argument("--cases", default="bench/cases")
    bench.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    bench.set_defaults(func=cmd_bench)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
