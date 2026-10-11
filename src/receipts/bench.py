"""A small, honest benchmark.

Each case is a directory:

    case.toml      description, expect = "<verdict>", meaningful = true|false
    base/          the default-branch tree
    head/          the pull-request tree (fix cases only)
    receipt.toml   optional; otherwise the receipt is discovered under head/.receipts/

The bench checks that the verifier behaves *as specified*. Cases with
meaningful = false are known limitations: the verdict is what the spec says,
but a human would not call the receipt meaningful. They are reported, not hidden.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .policy import Policy
from .report import paint
from .sandbox import LocalSandbox
from .verify import GOOD, run_verification


@dataclass
class CaseResult:
    name: str
    description: str
    expected: str
    got: str
    meaningful: bool
    seconds: float

    @property
    def ok(self) -> bool:
        return self.expected == self.got

    @property
    def accepted_but_meaningless(self) -> bool:
        return self.got in GOOD and not self.meaningful


def run_bench(cases_dir: Path) -> list[CaseResult]:
    policy = Policy(max_timeout=20)
    sandbox = LocalSandbox(policy)
    results: list[CaseResult] = []
    for case in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        meta = tomllib.loads((case / "case.toml").read_text(encoding="utf-8"))
        head = case / "head"
        receipt = case / "receipt.toml"
        verdict = run_verification(
            base_dir=case / "base",
            head_dir=head if head.is_dir() else None,
            receipt_path=receipt if receipt.is_file() else None,
            policy=policy, sandbox=sandbox)
        seconds = sum(r.duration_s for r in verdict.runs)
        results.append(CaseResult(case.name, meta.get("description", ""), meta["expect"],
                                  verdict.verdict, bool(meta.get("meaningful", True)), seconds))
    return results


def format_bench(results: list[CaseResult], *, color: bool = False) -> str:
    width = max((len(r.name) for r in results), default=10)
    lines = [f"{'case':<{width}}  {'expected':<15} {'got':<15} ", "-" * (width + 36)]
    for r in results:
        mark = paint("✓", "green", color) if r.ok else paint("✗ MISMATCH", "red", color)
        note = "  (known limitation)" if r.accepted_but_meaningless else ""
        lines.append(f"{r.name:<{width}}  {r.expected:<15} {r.got:<15} {mark}{note}")
    passed = sum(r.ok for r in results)
    limits = sum(r.accepted_but_meaningless for r in results)
    lines += ["", f"{passed}/{len(results)} cases behave as specified.",
              f"{limits} accepted receipt(s) are known limitations "
              "(they satisfy the spec but a human would call them meaningless)."]
    return "\n".join(lines)
