# The receipt format, version 1

> A **receipt** is a small TOML document that turns a claim ("this is broken", "this fixes it")
> into something a machine can run. Anyone can implement this spec; the `receipts` tool is the reference implementation.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Two kinds of receipt

| kind  | attached to  | claim                              | what the verifier does                                    |
|-------|--------------|------------------------------------|-----------------------------------------------------------|
| `bug` | an issue     | "this fails on the default branch" | runs the command on the **base** tree; it MUST fail as described |
| `fix` | a pull request | "this change makes it pass"      | runs the command on **base**, then on **head**: fail → pass |

A bug receipt is self-contained: any scripts it needs are embedded as `[[file]]` entries.
A fix receipt usually points at a test the pull request added (`run.overlay`).

## 2. File layout

```toml
version = 1                      # MUST be 1
kind    = "fix"                  # "bug" | "fix"
title   = "average([]) returns 0.0 instead of crashing"   # one line, ≤ 200 chars
closes  = "#123"                 # optional, free text, ≤ 40 chars

[run]
command = "python tests/test_average_empty.py"   # MUST exit non-zero when the claim is false
timeout = 60                                      # seconds, 1..3600, default 60 (policy may lower it)
overlay = ["tests/test_average_empty.py"]         # fix only: files copied from head onto base for the "before" run

[expect]
fail_output_contains = "ZeroDivisionError"        # REQUIRED for bug, optional for fix; ≥ 4 chars

[[file]]                         # optional, repeatable, ≤ 20 entries, ≤ 64 KiB each
path    = "repro.py"
content = """
print("written into the tree before the command runs")
"""
```

Rules (a conforming parser MUST reject a receipt that breaks any of them):

1. Unknown keys are errors. Typos must not silently weaken a receipt.
2. Every path (`run.overlay`, `file.path`) is relative, uses `/`, contains no `..`, and does not point into
   `.git/`, `.github/` or at `.receipts/policy.toml`.
3. `expect.fail_output_contains` MUST NOT appear in `run.command`: the failure has to be produced by the
   code under test, not echoed by the receipt.
4. A `bug` receipt MUST set `expect.fail_output_contains`, and MUST NOT use `run.overlay`.
5. The command is one line. Longer logic belongs in an embedded `[[file]]`.
6. A receipt is at most 256 KiB.

### Where receipts live

* **Issues:** a fenced block whose info string is `receipt` or `toml receipt`.
* **Pull requests:** a file `.receipts/<name>.toml` that the PR adds or changes.

## 3. Verification semantics

Let *base* be the default-branch tree and *head* the tree with the pull request applied.
"Fails" means the command exits non-zero; "passes" means it exits 0. Exit codes 126 and 127
(cannot start / not found) are never "fails": they make the receipt `invalid`.

**Bug receipts**

1. Write `[[file]]` entries into *base*; run the command.
2. Exit 0 → `unreproducible`. Fails without the signature → `wrong-failure`. Fails with it → `reproduced`.

**Fix receipts**

1. If nothing changed between *base* and *head* other than the receipt, its overlay files and `.receipts/` → `no-change`.
2. Copy `run.overlay` from *head* onto *base*; write `[[file]]` entries into both trees.
3. Run on *base*. Exit 0 → `vacuous` (head is not run). Fails without the signature (when set) → `wrong-failure`.
4. Run on *head*. Passes → `verified`. Fails → `not-fixed`.

A timeout on either run gives `timeout`. A sandbox or setup problem gives `error`, which is never the contributor's fault.

### Verdicts

| verdict          | good? | meaning                                                              | suggested label        |
|------------------|:----:|----------------------------------------------------------------------|------------------------|
| `verified`       | ✅   | fails on base, passes on head                                        | `receipt:verified`     |
| `reproduced`     | ✅   | bug fails on base with the promised signature                        | `receipt:verified`     |
| `vacuous`        |      | already passes on base: proves nothing                               | `receipt:needs-work`   |
| `wrong-failure`  |      | fails, but not with the promised signature                           | `receipt:needs-work`   |
| `not-fixed`      |      | fails on base and still fails on head                                | `receipt:needs-work`   |
| `unreproducible` |      | bug command exits 0 on base                                          | `receipt:needs-work`   |
| `no-change`      |      | the pull request contains nothing but its receipt                    | `receipt:needs-work`   |
| `timeout`        |      | a run exceeded its time limit                                        | `receipt:needs-work`   |
| `missing`        |      | no receipt found                                                     | `receipt:missing`      |
| `invalid`        |      | malformed, forbidden path, or the command cannot start               | `receipt:invalid`      |
| `error`          |      | infrastructure failure (sandbox down, maintainers' setup failed)     | *(none)*               |

## 4. Execution environment

Policy comes from the **base** branch (`.receipts/policy.toml`), never from the pull request:

```toml
image            = "python:3.12-slim"   # image the commands run in
setup            = "pip install -r requirements.txt"   # optional; runs WITH network, before the receipt, per tree
setup_timeout    = 600
max_timeout      = 120                  # upper bound for run.timeout
memory           = "512m"
cpus             = "1"
pids             = 256
max_output_bytes = 16384                # only the tail is kept
docs_url         = "https://example.org/contributing"   # shown in comments, https only
```

A conforming sandbox MUST run the receipt command with no network, no secrets, no extra capabilities, a read-only root
filesystem apart from the working tree and a scratch `/tmp`, and enforce the time, memory and process limits.
Each tree is a throwaway export without a `.git` directory; symlinks are not copied.

## 5. Verdict JSON

`receipts verify --json-out` writes this document. Consumers that receive it from a less trusted place MUST validate it
strictly (the reference implementation does so in `receipts render`).

```json
{
  "schema": 1,
  "receipts_version": "0.1.0",
  "verdict": "verified",
  "good": true,
  "label": "receipt:verified",
  "summary": "Fails on the base tree, passes with the change.",
  "kind": "fix",
  "title": "average([]) returns 0.0 instead of crashing",
  "command": "python tests/test_average_empty.py",
  "signature": "ZeroDivisionError",
  "runs": [
    {"name": "base", "expected": "fail", "outcome": "fail", "exit_code": 1, "duration_s": 0.17, "output": "..."},
    {"name": "head", "expected": "pass", "outcome": "pass", "exit_code": 0, "duration_s": 0.16, "output": "..."}
  ],
  "notes": [],
  "subject": {"type": "pull_request", "number": 12},
  "docs_url": null
}
```

## 6. What a verdict does and does not prove

`verified` means: *this exact command flipped from failing to passing when this change was applied, and the change
touched more than the receipt.* It does **not** prove that the command measures what the title says.
A human still decides whether the receipt is meaningful and the change is right.
The goal is that maintainers spend that attention only on claims that already survived contact with a computer.
See the [threat model](../docs/threat-model.md#what-receipts-does-not-do) for the known gaps.
