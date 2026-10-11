---
name: Bug report
about: Report a bug with a receipt, a tiny runnable proof, and it jumps the queue
title: ""
labels: bug
assignees: ""
---

**What is wrong?** One or two sentences.

**Receipt** (run `receipts init --kind bug` for a template; edit the block and keep the `receipt` tag):

```toml receipt
version = 1
kind = "bug"
title = "what breaks, in one line"

[run]
command = "python repro.py"      # must exit non-zero while the bug exists

[expect]
fail_output_contains = "the exception name or assertion text the code under test prints"

[[file]]
path = "repro.py"
content = """
# the smallest script that triggers the bug
"""
```

Bug reports without a receipt are still welcome; they just cannot be verified automatically.
