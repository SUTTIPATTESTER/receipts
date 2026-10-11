"""Turning verdicts into words: PR comments, terminal output, JSON re-validation.

Everything that came from the sandbox (command output, titles, error text) is
untrusted. It is only ever shown inside code spans/blocks, with @mentions
defused, so a malicious receipt cannot ping people or break out of formatting.
"""

from __future__ import annotations

import re

from .verify import ALL_LABELS, OUTCOMES, VERDICTS, RunInfo, Verdict

MARKER = "<!-- receipts:v1 -->"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MENTION_RE = re.compile(r"@(?=[A-Za-z0-9_-])")
_URL_RE = re.compile(r"^https://[^\s<>()\"'`]{1,200}$")

_HEADLINES = {
    "verified": ("✅", "Receipt verified"),
    "reproduced": ("✅", "Bug reproduced"),
    "vacuous": ("⚠️", "The receipt passes without the change"),
    "wrong-failure": ("⚠️", "It fails, but not the way the receipt describes"),
    "not-fixed": ("⚠️", "Still failing with the change applied"),
    "unreproducible": ("⚠️", "Could not reproduce the bug"),
    "no-change": ("⚠️", "Only the receipt changed"),
    "timeout": ("⏱️", "The receipt timed out"),
    "missing": ("📝", "No receipt found"),
    "invalid": ("❌", "The receipt is not valid"),
    "error": ("🛠️", "Verification could not run"),
}

_ADVICE = {
    "verified": "The claim holds when run: the receipt fails on the base tree and passes with this change. "
                "A maintainer still reviews the change itself, but the claim no longer needs to be taken on trust.",
    "reproduced": "The report is runnable and fails on the default branch exactly as described. "
                  "It is now in the verified queue.",
    "vacuous": "A receipt has to **fail before** the change and **pass after** it. This one already passes on the "
               "base tree, so it does not show that the change does anything. Make the test fail on the old code.",
    "wrong-failure": "The command fails, but the output does not contain the failure signature the receipt promises "
                     "(`expect.fail_output_contains`). Check the last lines below: the test may be failing for an "
                     "unrelated reason, such as a typo or a missing import.",
    "not-fixed": "The receipt fails on the base tree as expected, but it still fails once the change is applied.",
    "unreproducible": "The command exited successfully on the default branch, so the bug did not show up. "
                      "Check the version, the inputs and the exact command.",
    "no-change": "Besides the receipt (and the test files it points at) nothing in the tree changed, "
                 "so there is nothing for the receipt to verify.",
    "timeout": "The command did not finish in time. Keep receipts small and deterministic.",
    "missing": "Add a *receipt*: a tiny runnable proof that the problem exists (bug report) or is fixed "
               "(pull request). Run `receipts init` for a template, or paste a fenced ```` ```toml receipt ```` block "
               "into the issue.",
    "invalid": "Fix the problem named below and push again. `receipts lint` checks a receipt locally.",
    "error": "This is an infrastructure problem on the maintainers' side, not a problem with your submission.",
}


def strip_ansi(text: str) -> str:
    return _CTRL_RE.sub("", _ANSI_RE.sub("", text))


def defuse(text: str) -> str:
    """Stop @mentions from notifying anyone."""
    return _MENTION_RE.sub("@​", text)


def safe_inline(text: object, limit: int = 160) -> str:
    cleaned = " ".join(strip_ansi(str(text)).split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return "`" + defuse(cleaned.replace("`", "'")) + "`"


def safe_block(text: str, *, max_lines: int = 40, max_chars: int = 6000) -> str:
    cleaned = defuse(strip_ansi(text)).strip("\n")
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        cut = len(lines) - max_lines
        lines = [f"[... {cut} earlier lines hidden ...]"] + lines[-max_lines:]
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = "[... earlier output hidden ...]\n" + body[-max_chars:]
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{body}\n{fence}"


def md_escape(text: object, limit: int = 400) -> str:
    cleaned = " ".join(strip_ansi(str(text)).split())[:limit]
    return defuse(re.sub(r"([\\`*_{}\[\]<>()#+!|~])", r"\\\1", cleaned))


def _outcome_phrase(run: RunInfo) -> str:
    if run.outcome == "not-run":
        return "skipped"
    if run.outcome == "timeout":
        return "timed out"
    if run.outcome == "error":
        return "sandbox error"
    if run.outcome == "unrunnable":
        return f"could not start (exit {run.exit_code})"
    return f"{run.outcome.upper()} (exit {run.exit_code})"


def render_markdown(verdict: Verdict) -> str:
    emoji, headline = _HEADLINES[verdict.verdict]
    out = [MARKER, f"<!-- receipts:verdict:{verdict.verdict} -->", f"### {emoji} {headline}", ""]
    if verdict.title:
        out.append(f"**Claim:** {safe_inline(verdict.title, 200)}")
    if verdict.command:
        out.append(f"**Command:** {safe_inline(verdict.command, 300)}")
    if verdict.title or verdict.command:
        out.append("")
    if verdict.verdict == "invalid" and verdict.summary:
        out += [f"> {md_escape(verdict.summary)}", ""]
    out += [_ADVICE[verdict.verdict], ""]
    if verdict.runs:
        out += ["| Tree | Expected | Result | Time |", "|---|---|---|---|"]
        for run in verdict.runs:
            ok = "" if run.outcome == "not-run" else (
                " ✅" if run.outcome == run.expected else " ⚠️")
            out.append(f"| {run.name} | {run.expected.upper()} | {_outcome_phrase(run)}{ok} | {run.duration_s:.2f}s |")
        out.append("")
        shown = next((r for r in reversed(verdict.runs) if r.output.strip()), None)
        if shown and verdict.verdict not in ("verified", "reproduced"):
            out += [f"<details open><summary>Last output ({shown.name} tree)</summary>", "",
                    safe_block(shown.output), "", "</details>", ""]
        elif shown:
            out += [f"<details><summary>Output ({shown.name} tree)</summary>", "",
                    safe_block(shown.output), "", "</details>", ""]
    for note in verdict.notes[:10]:
        out.append(f"- ℹ️ {md_escape(note)}")
    if verdict.notes:
        out.append("")
    footer = f"<sub>receipts v{verdict.receipts_version} · verified by running it, not by guessing"
    if verdict.docs_url and _URL_RE.fullmatch(verdict.docs_url):
        footer += f" · [how receipts work]({verdict.docs_url})"
    out.append(footer + "</sub>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- terminal

_COLORS = {"green": "32", "yellow": "33", "red": "31", "cyan": "36", "dim": "2", "bold": "1", "grey": "90"}


def paint(text: str, color: str, enabled: bool) -> str:
    return f"\x1b[{_COLORS[color]}m{text}\x1b[0m" if enabled else text


def format_terminal(verdict: Verdict, *, color: bool = False) -> str:
    emoji = {"verified": "✔", "reproduced": "✔"}.get(verdict.verdict, "✘" if verdict.verdict in ("invalid", "error") else "!")
    tone = "green" if verdict.good else ("red" if verdict.verdict in ("invalid", "error") else "yellow")
    lines = ["", f"  {paint(emoji + ' ' + verdict.verdict.upper(), tone, color)}  {verdict.summary}"]
    if verdict.kind:
        lines.append(f"    {paint('kind', 'grey', color)}      {verdict.kind}")
    if verdict.title:
        lines.append(f"    {paint('claim', 'grey', color)}     {verdict.title}")
    if verdict.command:
        lines.append(f"    {paint('command', 'grey', color)}   {verdict.command}")
    if verdict.signature:
        lines.append(f"    {paint('fails as', 'grey', color)}  output contains \"{verdict.signature}\"")
    for index, run in enumerate(verdict.runs):
        branch = "└─" if index == len(verdict.runs) - 1 else "├─"
        matched = run.outcome == run.expected
        mark = paint("✓", "green", color) if matched else (
            paint("·", "grey", color) if run.outcome == "not-run" else paint("✗", "yellow", color))
        detail = _outcome_phrase(run)
        extra = f"  {run.duration_s:.2f}s" if run.outcome != "not-run" else ""
        lines.append(f"    {branch} {run.name:<5} expected {run.expected.upper():<4} → {detail}{extra} {mark}")
    for note in verdict.notes:
        lines.append(f"    {paint('note', 'grey', color)}      {note}")
    if verdict.label:
        lines.append(f"    {paint('label', 'grey', color)}     {paint(verdict.label, tone, color)}")
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------- untrusted JSON -> Verdict

def _need(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


def _opt_str(value, name: str, limit: int):
    if value is None:
        return None
    _need(isinstance(value, str) and len(value) <= limit, f"{name} must be a string of at most {limit} characters")
    return value


def verdict_from_untrusted(obj: object) -> Verdict:
    """Strictly rebuild a Verdict from JSON produced somewhere less trusted."""
    _need(isinstance(obj, dict), "verdict must be a JSON object")
    _need(obj.get("schema") == 1, "unsupported schema version")
    verdict = obj.get("verdict")
    _need(verdict in VERDICTS, "unknown verdict")
    kind = obj.get("kind")
    _need(kind in (None, "bug", "fix"), "bad kind")

    runs: list[RunInfo] = []
    raw_runs = obj.get("runs", [])
    _need(isinstance(raw_runs, list) and len(raw_runs) <= 3, "runs must be a short list")
    for raw in raw_runs:
        _need(isinstance(raw, dict), "run must be an object")
        _need(raw.get("name") in ("base", "head"), "bad run name")
        _need(raw.get("expected") in ("fail", "pass"), "bad run expectation")
        _need(raw.get("outcome") in OUTCOMES, "bad run outcome")
        code = raw.get("exit_code")
        _need(code is None or (type(code) is int and -(2**31) <= code < 2**31), "bad exit code")
        duration = raw.get("duration_s", 0)
        _need(type(duration) in (int, float) and 0 <= duration < 1e7, "bad duration")
        output = raw.get("output", "")
        _need(isinstance(output, str) and len(output) <= 300_000, "run output too large")
        runs.append(RunInfo(raw["name"], raw["expected"], raw["outcome"], code, float(duration), output))

    notes = obj.get("notes", [])
    _need(isinstance(notes, list) and len(notes) <= 20 and all(isinstance(n, str) and len(n) <= 1000 for n in notes),
          "bad notes")

    subject = obj.get("subject")
    if subject is not None:
        _need(isinstance(subject, dict) and subject.get("type") in ("issue", "pull_request"), "bad subject type")
        number = subject.get("number")
        _need(type(number) is int and 1 <= number <= 10**9, "bad subject number")
        subject = {"type": subject["type"], "number": number}

    docs_url = _opt_str(obj.get("docs_url"), "docs_url", 200)
    _need(docs_url is None or bool(_URL_RE.fullmatch(docs_url)), "docs_url must be an https URL")
    version = _opt_str(obj.get("receipts_version"), "receipts_version", 32) or "unknown"
    _need(bool(re.fullmatch(r"[0-9A-Za-z.+-]*", version)), "bad version string")

    return Verdict(
        verdict=verdict,
        summary=_opt_str(obj.get("summary"), "summary", 1000) or "",
        kind=kind,
        title=_opt_str(obj.get("title"), "title", 400),
        command=_opt_str(obj.get("command"), "command", 4000),
        signature=_opt_str(obj.get("signature"), "signature", 400),
        runs=runs, notes=notes, subject=subject, docs_url=docs_url, receipts_version=version,
    )


__all__ = ["ALL_LABELS", "MARKER", "defuse", "format_terminal", "md_escape", "paint", "render_markdown",
           "safe_block", "safe_inline", "strip_ansi", "verdict_from_untrusted"]
