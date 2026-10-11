"""Maintainer policy (.receipts/policy.toml).

Policy is the *trusted* half of the system. It is always read from the base
branch, never from a pull request, so a contributor cannot loosen the limits
that apply to their own submission. Claims come from the PR; policy does not.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,200}$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[kmg]$")
_CPUS_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_URL_RE = re.compile(r"^https://[^\s<>()\"'`]{1,200}$")

_KEYS = {"image", "setup", "setup_timeout", "max_timeout", "memory", "cpus",
         "pids", "max_output_bytes", "docs_url"}


class PolicyError(ValueError):
    """policy.toml is malformed."""


@dataclass(frozen=True)
class Policy:
    image: str = "python:3.12-slim"
    setup: str | None = None
    setup_timeout: int = 600
    max_timeout: int = 120
    memory: str = "512m"
    cpus: str = "1"
    pids: int = 256
    max_output_bytes: int = 16384
    docs_url: str | None = None


def parse_policy(text: str) -> Policy:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"policy is not valid TOML: {exc}") from None
    extra = sorted(set(data) - _KEYS)
    if extra:
        raise PolicyError(f"unknown policy key(s): {', '.join(map(repr, extra))}")

    def integer(key: str, low: int, high: int, default: int) -> int:
        value = data.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise PolicyError(f"{key} must be an integer from {low} to {high}")
        return value

    def pattern(key: str, regex: re.Pattern[str], default: str) -> str:
        value = data.get(key, default)
        if not isinstance(value, str) or not regex.fullmatch(value):
            raise PolicyError(f"{key} has an invalid value")
        return value

    setup = data.get("setup")
    if setup is not None and (not isinstance(setup, str) or not setup.strip() or len(setup) > 2000):
        raise PolicyError("setup must be a non-empty string of at most 2000 characters")
    docs_url = data.get("docs_url")
    if docs_url is not None and (not isinstance(docs_url, str) or not _URL_RE.fullmatch(docs_url)):
        raise PolicyError("docs_url must be an https:// URL")

    return Policy(
        image=pattern("image", _IMAGE_RE, Policy.image),
        setup=setup,
        setup_timeout=integer("setup_timeout", 1, 3600, Policy.setup_timeout),
        max_timeout=integer("max_timeout", 1, 3600, Policy.max_timeout),
        memory=pattern("memory", _MEMORY_RE, Policy.memory),
        cpus=pattern("cpus", _CPUS_RE, Policy.cpus),
        pids=integer("pids", 16, 4096, Policy.pids),
        max_output_bytes=integer("max_output_bytes", 1024, 262144, Policy.max_output_bytes),
        docs_url=docs_url,
    )


def load_policy(path: Path | None) -> Policy:
    if path is None or not path.is_file():
        return Policy()
    if path.stat().st_size > 64 * 1024:
        raise PolicyError("policy file is larger than 64 KiB")
    return parse_policy(path.read_text(encoding="utf-8"))
