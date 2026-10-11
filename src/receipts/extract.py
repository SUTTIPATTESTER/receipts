"""Pull a receipt out of an issue or PR description (a fenced code block)."""

from __future__ import annotations

import re

MAX_BODY_BYTES = 256 * 1024

# ```receipt  or  ```toml receipt  (also with ~~~ fences)
_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[ \t]*(?:toml[ \t]+)?receipt[ \t]*\n"
    r"(?P<body>.*?)\n"
    r"(?P=fence)[`~]*[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def extract_receipt(markdown: str) -> str | None:
    """Return the body of the first ```receipt block, or None."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if len(text.encode("utf-8", "replace")) > MAX_BODY_BYTES:
        return None
    match = _FENCE_RE.search(text)
    return match.group("body") + "\n" if match else None
