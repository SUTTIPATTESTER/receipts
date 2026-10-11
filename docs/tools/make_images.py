#!/usr/bin/env python3
"""Generate the README illustrations. Standard library only.

    python docs/tools/make_images.py

Writes SVGs into docs/img/. The terminal image is captured from a REAL run of the
CLI against examples/average (local sandbox: those examples are trusted).
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', 'Noto Sans Thai', 'Leelawadee UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

THEMES = {
    "light": dict(bg="#ffffff", fg="#1f2328", muted="#59636e", border="#d1d9e0", card="#f6f8fa",
                  green="#1a7f37", green_bg="#dafbe1", amber="#9a6700", amber_bg="#fff8c5",
                  red="#cf222e", red_bg="#ffebe9", blue="#0969da", blue_bg="#ddf4ff",
                  purple="#8250df", purple_bg="#fbefff", shadow="#8c959f"),
    "dark": dict(bg="#0d1117", fg="#f0f6fc", muted="#9198a1", border="#3d444d", card="#151b23",
                 green="#3fb950", green_bg="#10241a", amber="#d29922", amber_bg="#2a2112",
                 red="#f85149", red_bg="#2b1618", blue="#58a6ff", blue_bg="#10243a",
                 purple="#bc8cff", purple_bg="#241a3b", shadow="#010409"),
}


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


class Svg:
    def __init__(self, w: int, h: int, c: dict | None, title: str, desc: str, radius: int = 16, frame: bool = True):
        self.w, self.h, self.c, self.title, self.desc = w, h, c, title, desc
        self.parts: list[str] = []
        self.defs: list[str] = []
        if c and frame:
            self.parts.append(f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="{radius}" '
                              f'fill="{c["bg"]}" stroke="{c["border"]}"/>')

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill="none", stroke=None, rx=8, sw=1, dash=None, extra=""):
        s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
        if stroke:
            s += f' stroke="{stroke}" stroke-width="{sw}"'
        if dash:
            s += f' stroke-dasharray="{dash}"'
        self.add(s + f" {extra}/>")

    def text(self, x, y, s, size=14, fill="#000", weight=400, anchor="start", mono=False, extra=""):
        family = MONO if mono else SANS
        self.add(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
                 f'fill="{fill}" text-anchor="{anchor}" xml:space="preserve" {extra}>{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, stroke, sw=2, dash=None, marker=False):
        s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round"'
        if dash:
            s += f' stroke-dasharray="{dash}"'
        if marker:
            s += ' marker-end="url(#arrow)"'
        self.add(s + "/>")

    def pill(self, x, y, w, h, label, fg, bg, size=13, mono=True, weight=600):
        self.rect(x, y, w, h, fill=bg, stroke=fg, rx=h / 2, sw=1)
        self.text(x + w / 2, y + h / 2 + size * 0.35, label, size=size, fill=fg, weight=weight, anchor="middle", mono=mono)

    def render(self) -> str:
        arrow = ""
        if self.c:
            arrow = (f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" '
                     f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{self.c["muted"]}"/></marker>')
        defs = "".join(self.defs)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" role="img" aria-labelledby="t d">\n<title id="t">{esc(self.title)}</title>\n'
                f'<desc id="d">{esc(self.desc)}</desc>\n<defs>{arrow}{defs}</defs>\n'
                + "\n".join(self.parts) + "\n</svg>\n")


# ---------------------------------------------------------------- icons

def icon_lock(s: Svg, x, y, color, size=18):
    k = size / 18
    s.add(f'<g transform="translate({x},{y}) scale({k})" fill="none" stroke="{color}" stroke-width="2" '
          f'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="12" height="9" rx="2" fill="{color}" '
          f'fill-opacity="0.15"/><path d="M6 8V5.5a3 3 0 0 1 6 0V8"/></g>')


def icon_doc(s: Svg, x, y, color, size=28):
    k = size / 28
    s.add(f'<g transform="translate({x},{y}) scale({k})" fill="none" stroke="{color}" stroke-width="2" '
          f'stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h11l6 6v18H6z" fill="{color}" fill-opacity="0.12"/>'
          f'<path d="M17 2v6h6M10 14h9M10 18h9M10 22h6"/></g>')


def icon_shield(s: Svg, x, y, color, size=36):
    k = size / 36
    s.add(f'<g transform="translate({x},{y}) scale({k})" fill="none" stroke="{color}" stroke-width="2.4" '
          f'stroke-linecap="round" stroke-linejoin="round"><path d="M18 3l12 4v9c0 8-5 14-12 17C11 30 6 24 6 16V7z" '
          f'fill="{color}" fill-opacity="0.15"/><path d="M12 17l4 4 8-9"/></g>')


def icon_check(s: Svg, cx, cy, r, fg, bg):
    s.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{bg}" stroke="{fg}" stroke-width="1.6"/>'
          f'<path d="M{cx - r * .42:.1f} {cy + r * .02:.1f} l{r * .32:.1f} {r * .34:.1f} l{r * .6:.1f} {-r * .66:.1f}" '
          f'fill="none" stroke="{fg}" stroke-width="{max(1.8, r / 5):.1f}" stroke-linecap="round" stroke-linejoin="round"/>')


def icon_warn(s: Svg, cx, cy, r, fg, bg):
    s.add(f'<path d="M{cx} {cy - r} L{cx + r * 1.05:.1f} {cy + r * .85:.1f} L{cx - r * 1.05:.1f} {cy + r * .85:.1f} Z" '
          f'fill="{bg}" stroke="{fg}" stroke-width="1.6" stroke-linejoin="round"/>'
          f'<path d="M{cx} {cy - r * .3:.1f} v{r * .55:.1f}" stroke="{fg}" stroke-width="2" stroke-linecap="round"/>'
          f'<circle cx="{cx}" cy="{cy + r * .52:.1f}" r="1.3" fill="{fg}"/>')


# ---------------------------------------------------------------- hero (dark, theme independent)

def hero() -> str:
    W, H = 1280, 440
    s = Svg(W, H, None, "receipts: every claim comes with a receipt",
            "Banner: the word receipts, the tagline 'Every claim comes with a receipt', and a paper receipt "
            "stamped VERIFIED.")
    s.defs.append(
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a1020"/>'
        '<stop offset="1" stop-color="#101d36"/></linearGradient>'
        '<linearGradient id="word" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffffff"/>'
        '<stop offset="1" stop-color="#7ee2a0"/></linearGradient>'
        '<radialGradient id="glow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#2ea043" stop-opacity="0.32"/>'
        '<stop offset="1" stop-color="#2ea043" stop-opacity="0"/></radialGradient>'
        '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" '
        'fill="#ffffff" fill-opacity="0.06"/></pattern>'
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="18" stdDeviation="16" '
        'flood-color="#000" flood-opacity="0.55"/></filter>')
    s.add(f'<rect width="{W}" height="{H}" rx="20" fill="url(#bg)"/>')
    s.add(f'<rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>')
    s.add('<ellipse cx="985" cy="230" rx="330" ry="260" fill="url(#glow)"/>')

    # left copy
    x = 72
    for i, label in enumerate(["GitHub Action", "Open spec", "Zero dependencies"]):
        w = [124, 100, 150][i]
        px = x + [0, 138, 252][i]
        s.add(f'<rect x="{px}" y="56" width="{w}" height="28" rx="14" fill="#ffffff" fill-opacity="0.07" '
              f'stroke="#ffffff" stroke-opacity="0.22"/>')
        s.text(px + w / 2, 75, label, size=13, fill="#c9d4e6", weight=600, anchor="middle")
    s.text(x - 4, 190, "receipts", size=118, fill="url(#word)", weight=800, extra='letter-spacing="-3"')
    s.text(x, 244, "Every claim comes with a receipt.", size=38, fill="#ffffff", weight=700)
    s.text(x, 292, "Verify bug reports and pull requests by running them.", size=22, fill="#a9b8d0")
    s.text(x, 322, "Unproven claims never reach a maintainer's attention.", size=22, fill="#a9b8d0")
    s.text(x, 376, "ทุกคำกล่าวอ้างต้องมีใบเสร็จ", size=22, fill="#7ee2a0", weight=600)

    # receipt paper
    pw, ph, n = 330, 372, 22
    top = " ".join(f"L{(i + .5) * pw / n:.1f},0 L{(i + 1) * pw / n:.1f},9" for i in range(n))
    bottom = " ".join(f"L{pw - (i + .5) * pw / n:.1f},{ph + 9} L{pw - (i + 1) * pw / n:.1f},{ph}" for i in range(n))
    s.add(f'<g transform="translate(838,30) rotate(3 165 200)" filter="url(#shadow)">'
          f'<path d="M0,9 {top} L{pw},{ph} {bottom} Z" fill="#fffdf6"/>')
    ink, soft, grn = "#22272e", "#6a737d", "#1a7f37"
    s.text(28, 58, "RECEIPT", size=22, fill=ink, weight=800, mono=True, extra='letter-spacing="3"')
    s.text(pw - 28, 58, "#142", size=18, fill=soft, mono=True, anchor="end")
    s.text(28, 86, "average([]) must not crash", size=14, fill=soft, mono=True)
    s.add(f'<line x1="28" y1="104" x2="{pw - 28}" y2="104" stroke="{soft}" stroke-dasharray="4 5"/>')
    rows = [("✓ fails on main", "exit 1"), ("✓ passes with PR", "exit 0"), ("✓ real code changed", "1 file")]
    for i, (a, b) in enumerate(rows):
        y = 140 + i * 32
        s.text(28, y, a, size=16, fill=ink, mono=True)
        s.text(pw - 28, y, b, size=16, fill=soft, mono=True, anchor="end")
    s.add(f'<line x1="28" y1="222" x2="{pw - 28}" y2="222" stroke="{soft}" stroke-dasharray="4 5"/>')
    s.text(28, 258, "VERDICT", size=16, fill=soft, mono=True, weight=700)
    bars, x0, seed = [], 28, 7
    while x0 < pw - 28:
        seed = (seed * 31 + 11) % 97
        w = 2 + seed % 4
        bars.append(f'<rect x="{x0}" y="312" width="{w}" height="38" fill="{ink}"/>')
        x0 += w + 2 + seed % 3
    s.add("".join(bars))
    s.add(f'<g transform="translate(218,262) rotate(-11)"><rect x="-84" y="-30" width="168" height="60" rx="10" '
          f'fill="none" stroke="{grn}" stroke-width="4" opacity="0.9"/><rect x="-77" y="-23" width="154" height="46" '
          f'rx="6" fill="none" stroke="{grn}" stroke-width="1.5" opacity="0.9"/>'
          f'<text x="0" y="10" font-family="{SANS}" font-size="30" font-weight="800" fill="{grn}" opacity="0.9" '
          f'text-anchor="middle" letter-spacing="2">VERIFIED</text></g>')
    s.add("</g>")
    return s.render()


# ---------------------------------------------------------------- flow

def flow(theme: str) -> str:
    c = THEMES[theme]
    s = Svg(1240, 440, c, "How receipts works",
            "A receipt goes into a sandbox where it runs on the base tree (must fail) and the head tree (must pass), "
            "under a policy taken from the base branch. A deterministic verdict becomes a comment and a label.")
    # 1 receipt
    s.rect(30, 130, 200, 176, fill=c["card"], stroke=c["border"], rx=14)
    icon_doc(s, 48, 146, c["blue"])
    s.text(88, 168, "The receipt", size=17, fill=c["fg"], weight=700)
    s.text(46, 206, "A tiny TOML file in", size=13, fill=c["muted"])
    s.text(46, 224, "the issue or the PR", size=13, fill=c["muted"])
    for i, line in enumerate(['kind    = "fix"', 'command = "pytest t.py"', 'expect  = "ZeroDivisionError"']):
        s.text(46, 254 + i * 18, line, size=11.5, fill=c["fg"], mono=True)
    s.line(232, 218, 282, 218, c["muted"], marker=True)

    # policy
    s.rect(346, 14, 410, 42, fill=c["purple_bg"], stroke=c["purple"], rx=21)
    icon_lock(s, 366, 26, c["purple"], 18)
    s.text(394, 40, "policy.toml · read from the BASE branch, never the PR", size=13.5, fill=c["purple"], weight=600)
    s.line(551, 57, 551, 86, c["purple"], marker=True)

    # sandbox
    s.rect(286, 86, 490, 290, fill="none", stroke=c["muted"], rx=18, sw=2, dash="7 6")
    icon_lock(s, 306, 100, c["fg"], 20)
    s.text(334, 116, "SANDBOX", size=13, fill=c["fg"], weight=800, extra='letter-spacing="2"')
    for x, name, expect, fg, bg in [(310, "base tree", "must FAIL", c["red"], c["red_bg"]),
                                    (546, "head tree", "must PASS", c["green"], c["green_bg"])]:
        s.rect(x, 138, 210, 108, fill=c["card"], stroke=c["border"], rx=12)
        s.text(x + 16, 168, name, size=16, fill=c["fg"], weight=700)
        s.text(x + 16, 190, "run the command", size=13, fill=c["muted"])
        s.pill(x + 16, 204, 98, 26, expect, fg, bg, size=12.5)
    s.line(522, 192, 544, 192, c["muted"], marker=True)
    x = 310
    for label, w in [("no network", 92), ("no secrets", 92), ("read-only root", 112), ("CPU/mem/time caps", 142)]:
        s.rect(x, 268, w, 28, fill="none", stroke=c["border"], rx=14)
        s.text(x + w / 2, 287, label, size=12, fill=c["muted"], anchor="middle", weight=600)
        x += w + 8
    s.text(310, 330, "throwaway export of each tree · no .git · symlinks dropped", size=12.5, fill=c["muted"])
    s.text(310, 350, "(the receipt's own files are copied onto base for the 'before' run)", size=12.5, fill=c["muted"])
    s.line(778, 232, 830, 232, c["muted"], marker=True)

    # verdict
    s.rect(832, 96, 172, 280, fill=c["card"], stroke=c["border"], rx=14)
    s.text(918, 124, "Verdict", size=17, fill=c["fg"], weight=700, anchor="middle")
    s.text(918, 142, "from exit codes only", size=12, fill=c["muted"], anchor="middle")
    items = [("verified", c["green"], c["green_bg"]), ("reproduced", c["green"], c["green_bg"]),
             ("vacuous", c["amber"], c["amber_bg"]), ("not-fixed", c["amber"], c["amber_bg"]),
             ("wrong-failure", c["amber"], c["amber_bg"]), ("invalid", c["red"], c["red_bg"]),
             ("missing", c["purple"], c["purple_bg"])]
    for i, (label, fg, bg) in enumerate(items):
        s.pill(852, 156 + i * 30, 132, 24, label, fg, bg, size=12)
    s.line(1006, 232, 1038, 232, c["muted"], marker=True)

    # output
    s.rect(1040, 130, 170, 176, fill=c["card"], stroke=c["border"], rx=14)
    s.text(1056, 158, "Comment + label", size=15.5, fill=c["fg"], weight=700)
    s.pill(1056, 174, 128, 24, "receipt:verified", c["green"], c["green_bg"], size=11.5)
    icon_check(s, 1070, 226, 9, c["green"], c["green_bg"])
    s.text(1086, 231, "Receipt verified", size=13, fill=c["fg"], weight=600)
    s.text(1056, 256, "base  FAIL  ✓", size=12, fill=c["muted"], mono=True)
    s.text(1056, 274, "head  PASS  ✓", size=12, fill=c["muted"], mono=True)

    for cx, label in [(130, "① attach"), (531, "② run twice"), (918, "③ decide"), (1125, "④ report")]:
        s.text(cx, 408, label, size=15, fill=c["muted"], anchor="middle", weight=600)
    return s.render()


# ---------------------------------------------------------------- verdict matrix

def verdicts(theme: str) -> str:
    c = THEMES[theme]
    s = Svg(1000, 484, c, "What the verifier concludes",
            "A table of outcomes. Fails on base and passes with the change: verified. Fails on base and still fails: "
            "not-fixed. Passes on base already: vacuous.")
    s.text(260, 56, "with the change applied …", size=14, fill=c["muted"], weight=600)
    s.text(425, 90, "still FAILS", size=16, fill=c["fg"], weight=700, anchor="middle")
    s.text(765, 90, "PASSES", size=16, fill=c["fg"], weight=700, anchor="middle")
    s.text(40, 168, "on the base tree …", size=14, fill=c["muted"], weight=600)
    s.text(40, 196, "FAILS", size=18, fill=c["red"], weight=800)
    s.text(40, 218, "(that is what a", size=13, fill=c["muted"])
    s.text(40, 236, "receipt promises)", size=13, fill=c["muted"])
    s.text(40, 334, "already PASSES", size=18, fill=c["amber"], weight=800)
    s.text(40, 356, "(nothing to prove)", size=13, fill=c["muted"])

    def cell(x, y, w, h, name, body, fg, bg, strong=False):
        s.rect(x, y, w, h, fill=bg, stroke=fg, rx=14, sw=2.5 if strong else 1.4)
        s.text(x + 24, y + 48, name, size=28, fill=fg, weight=800, mono=True)
        for i, line in enumerate(body):
            s.text(x + 24, y + 80 + i * 22, line, size=14.5, fill=c["fg"])

    cell(260, 106, 330, 150, "not-fixed", ["The change did not fix it.", "Back to the author."], c["amber"], c["amber_bg"])
    cell(600, 106, 330, 150, "verified", ["The claim holds when run.", "A human reviews the change itself."],
         c["green"], c["green_bg"], strong=True)
    cell(260, 272, 670, 120, "vacuous", ["The test passes without the change, so it proves nothing.",
                                         "The head tree is not even run."], c["amber"], c["amber_bg"])
    s.text(40, 428, "Also:", size=14, fill=c["muted"], weight=700)
    x = 96
    for label, fg, bg in [("wrong-failure", c["amber"], c["amber_bg"]), ("timeout", c["amber"], c["amber_bg"]),
                          ("no-change", c["amber"], c["amber_bg"]), ("invalid", c["red"], c["red_bg"]),
                          ("missing", c["purple"], c["purple_bg"]), ("error", c["muted"], c["card"])]:
        w = 24 + 8.6 * len(label)
        s.pill(x, 410, w, 26, label, fg, bg, size=12)
        x += w + 10
    s.text(40, 462, "Bug reports follow the same logic on the base tree alone: reproduced · unreproducible · wrong-failure.",
           size=13, fill=c["muted"])
    return s.render()


# ---------------------------------------------------------------- trust boundary

def trust(theme: str) -> str:
    c = THEMES[theme]
    s = Svg(1200, 470, c, "Trust boundary",
            "Two workflows. The unprivileged one runs pull-request code in a sandbox and uploads only data. The privileged "
            "one never runs pull-request code; it validates the data and posts a comment and label.")
    s.rect(24, 64, 520, 336, fill=c["red_bg"], stroke=c["red"], rx=18, sw=2, dash="8 6")
    s.text(48, 96, "UNTRUSTED · runs pull-request code", size=14, fill=c["red"], weight=800, extra='letter-spacing="1.2"')
    s.rect(48, 112, 472, 66, fill=c["bg"], stroke=c["border"], rx=12)
    s.text(64, 138, "receipts-verify", size=16, fill=c["fg"], weight=700, mono=True)
    s.text(64, 160, "on: pull_request · permissions: contents: read · no secrets", size=13, fill=c["muted"])
    s.rect(48, 194, 472, 128, fill=c["bg"], stroke=c["red"], rx=12, sw=1.6)
    icon_lock(s, 64, 208, c["red"], 20)
    s.text(92, 224, "sandbox container", size=16, fill=c["fg"], weight=700)
    for i, line in enumerate(["network: none · capabilities: none · root: read-only",
                              "the ONLY place a contributor's code ever executes",
                              "limits on time, memory, processes and output size"]):
        s.text(64, 252 + i * 22, line, size=13, fill=c["muted"])
    s.text(48, 354, "writes one file:", size=13, fill=c["muted"])
    s.text(150, 354, "verdict.json", size=13.5, fill=c["fg"], weight=700, mono=True)
    s.text(264, 354, "(data, not code)", size=13, fill=c["muted"])
    s.text(48, 380, "policy.toml comes from the BASE branch, so a PR can't loosen its own limits", size=12.5, fill=c["purple"])

    s.line(546, 236, 654, 236, c["muted"], sw=2.4, marker=True)
    s.text(600, 218, "artifact", size=12.5, fill=c["muted"], anchor="middle", weight=600)
    icon_shield(s, 582, 250, c["blue"], 36)
    s.text(600, 306, "strict", size=12.5, fill=c["blue"], anchor="middle", weight=700)
    s.text(600, 322, "schema", size=12.5, fill=c["blue"], anchor="middle", weight=700)

    s.rect(656, 64, 520, 336, fill=c["green_bg"], stroke=c["green"], rx=18, sw=2, dash="8 6")
    s.text(680, 96, "PRIVILEGED · never runs pull-request code", size=14, fill=c["green"], weight=800,
           extra='letter-spacing="1.2"')
    s.rect(680, 112, 472, 66, fill=c["bg"], stroke=c["border"], rx=12)
    s.text(696, 138, "receipts-report", size=16, fill=c["fg"], weight=700, mono=True)
    s.text(696, 160, "on: workflow_run · issues + pull-requests: write", size=13, fill=c["muted"])
    s.rect(680, 194, 472, 128, fill=c["bg"], stroke=c["green"], rx=12, sw=1.6)
    s.text(696, 222, "receipts render", size=16, fill=c["fg"], weight=700, mono=True)
    for i, line in enumerate(["enums, bounded sizes and integer ids only; anything else aborts",
                              "@mentions defused · code fences can't be closed · ANSI stripped",
                              "then: one comment (updated in place) + one receipt:* label"]):
        icon_check(s, 702, 248 + i * 22, 7, c["green"], c["green_bg"])
        s.text(718, 253 + i * 22, line, size=13, fill=c["muted"])
    s.text(680, 354, "The write token never shares a machine with the contributor's code.", size=13.5, fill=c["fg"],
           weight=600)
    s.text(680, 380, "No checkout of the PR · no shell interpolation of untrusted text", size=12.5, fill=c["muted"])
    s.text(600, 440, "Claims come from the pull request. Rules and credentials never do.", size=16, fill=c["fg"],
           weight=700, anchor="middle")
    return s.render()


# ---------------------------------------------------------------- bot comments (illustrative)

def comments(theme: str) -> str:
    c = THEMES[theme]
    s = Svg(1200, 400, c, "What contributors see",
            "Two illustrative bot comments. Left: the receipt passes without the change, with guidance. "
            "Right: receipt verified.")

    def card(x, kind):
        good = kind == "verified"
        fg, bg = (c["green"], c["green_bg"]) if good else (c["amber"], c["amber_bg"])
        s.rect(x, 24, 560, 352, fill=c["bg"], stroke=c["border"], rx=12)
        s.add(f'<path d="M{x},60 v-24 a12,12 0 0 1 12,-12 h536 a12,12 0 0 1 12,12 v24 z" fill="{c["card"]}" '
              f'stroke="{c["border"]}"/>')
        s.add(f'<circle cx="{x + 28}" cy="42" r="12" fill="{c["blue"]}"/>')
        s.text(x + 28, 47, "R", size=13, fill="#ffffff", weight=800, anchor="middle")
        s.text(x + 50, 47, "github-actions", size=13.5, fill=c["fg"], weight=700)
        s.pill(x + 160, 31, 34, 20, "bot", c["muted"], c["card"], size=11, mono=False)
        s.text(x + 204, 47, "commented just now", size=13, fill=c["muted"])
        (icon_check if good else icon_warn)(s, x + 36, 94, 11, fg, bg)
        s.text(x + 58, 100, "Receipt verified" if good else "The receipt passes without the change",
               size=19, fill=c["fg"], weight=700)
        s.text(x + 24, 134, "Claim:", size=13.5, fill=c["muted"], weight=600)
        s.rect(x + 74, 118, 380 if good else 392, 24, fill=c["card"], stroke=c["border"], rx=6)
        s.text(x + 84, 135, "average([]) returns 0.0 instead of crashing", size=12, fill=c["fg"], mono=True)
        lines = (["The claim holds when run: the receipt fails on the base tree",
                  "and passes with this change. A maintainer still reviews the",
                  "change itself, but the claim no longer needs to be taken on trust."] if good else
                 ["A receipt has to fail before the change and pass after it.",
                  "This one already passes on the base tree, so it does not show",
                  "that the change does anything. Make the test fail on the old code."])
        for i, ln in enumerate(lines):
            s.text(x + 24, 170 + i * 21, ln, size=13.5, fill=c["fg"])
        # table
        top = 246
        s.rect(x + 24, top, 512, 92, fill="none", stroke=c["border"], rx=8)
        s.add(f'<path d="M{x + 24},{top + 30} h512" stroke="{c["border"]}"/><path d="M{x + 24},{top + 61} h512" '
              f'stroke="{c["border"]}"/>')
        for tx, label in [(40, "Tree"), (150, "Expected"), (270, "Result"), (480, "Time")]:
            s.text(x + tx, top + 20, label, size=12.5, fill=c["muted"], weight=700)
        rows = ([("base", "FAIL", "FAIL (exit 1)", "0.17s", True), ("head", "PASS", "PASS (exit 0)", "0.16s", True)] if good
                else [("base", "FAIL", "PASS (exit 0)", "0.16s", False), ("head", "PASS", "skipped", "-", None)])
        for i, (a, b, r, t, ok) in enumerate(rows):
            y = top + 50 + i * 31
            s.text(x + 40, y, a, size=13, fill=c["fg"], mono=True)
            s.text(x + 150, y, b, size=13, fill=c["fg"], mono=True)
            s.text(x + 270, y, r, size=13, fill=c["fg"], mono=True)
            s.text(x + 480, y, t, size=13, fill=c["muted"], mono=True)
            if ok is True:
                icon_check(s, x + 232, y - 4, 7, c["green"], c["green_bg"])
            elif ok is False:
                icon_warn(s, x + 236, y - 4, 7, c["amber"], c["amber_bg"])
        s.text(x + 24, 362, "receipts v0.1.0 · verified by running it, not by guessing", size=11.5, fill=c["muted"])

    card(24, "vacuous")
    card(616, "verified")
    return s.render()


# ---------------------------------------------------------------- terminal (captured from a real run)

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
TERM = dict(fg="#e6edf3", bg="#0d1117", bar="#161b22", border="#30363d", green="#3fb950", yellow="#d29922",
            red="#f85149", cyan="#39c5cf", grey="#8b949e", dim="#8b949e")
ANSI_FG = {"32": "green", "33": "yellow", "31": "red", "36": "cyan", "90": "grey", "2": "dim"}


def parse_ansi(line: str):
    runs, color, bold, pos = [], "fg", False, 0
    for m in ANSI_RE.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], color, bold))
        for code in (m.group(1) or "0").split(";"):
            if code in ("0", ""):
                color, bold = "fg", False
            elif code == "1":
                bold = True
            elif code in ANSI_FG:
                color = ANSI_FG[code]
        pos = m.end()
    if pos < len(line):
        runs.append((line[pos:], color, bold))
    return runs


def capture(args: list[str]) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", NO_COLOR="")
    env.pop("NO_COLOR", None)
    proc = subprocess.run([sys.executable, "-m", "receipts", *args, "--color", "always"],
                          cwd=ROOT / "examples" / "average", env=env, capture_output=True, text=True,
                          encoding="utf-8", check=False)
    return proc.stdout


def terminal() -> str:
    cmds = [
        ["verify", "--base-dir", "base", "--receipt", "bug.toml", "--sandbox", "local", "--unsafe-local"],
        ["verify", "--base-dir", "base", "--head-dir", "vacuous", "--sandbox", "local", "--unsafe-local"],
        ["verify", "--base-dir", "base", "--head-dir", "fix", "--sandbox", "local", "--unsafe-local"],
    ]
    lines: list[list[tuple[str, str, bool]]] = []
    lines.append([("# trusted examples, so this demo uses the local sandbox (real CI uses --sandbox docker)", "grey", False)])
    for cmd in cmds:
        lines.append([("$ ", "green", True), ("receipts " + " ".join(cmd), "fg", False)])
        out = capture(cmd).strip("\n").splitlines()
        lines.extend(parse_ansi(line) for line in out)
        lines.append([])
    while lines and not lines[-1]:
        lines.pop()
    char_w, lh, pad = 8.45, 23, 26
    width = max(880, int(max((sum(len(t) for t, _, _ in ln) for ln in lines), default=0) * char_w + pad * 2))
    height = 56 + lh * len(lines) + pad
    s = Svg(width, height, None, "receipts in the terminal",
            "A terminal session: a bug report is reproduced, a vacuous receipt is flagged, and a fix is verified.")
    s.add(f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{TERM["bg"]}" '
          f'stroke="{TERM["border"]}"/>')
    s.add(f'<path d="M0.5,42 v-30 a12,12 0 0 1 12,-12 h{width - 25} a12,12 0 0 1 12,12 v30 z" fill="{TERM["bar"]}"/>')
    for i, col in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        s.add(f'<circle cx="{24 + i * 22}" cy="21" r="6.5" fill="{col}"/>')
    s.text(width / 2, 26, "receipts: examples/average", size=13, fill=TERM["grey"], anchor="middle")
    y = 74
    for ln in lines:
        if ln:
            weight = ' font-weight="700"'
            spans = "".join(
                f'<tspan fill="{TERM[col]}"{weight if bold else ""}>{esc(t)}</tspan>'
                for t, col, bold in ln)
            s.add(f'<text x="{pad}" y="{y}" font-family="{MONO}" font-size="14" xml:space="preserve">{spans}</text>')
        y += lh
    return s.render()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"hero.svg": hero(), "terminal.svg": terminal()}
    for theme in ("light", "dark"):
        files[f"flow-{theme}.svg"] = flow(theme)
        files[f"verdicts-{theme}.svg"] = verdicts(theme)
        files[f"trust-{theme}.svg"] = trust(theme)
        files[f"comments-{theme}.svg"] = comments(theme)
    for name, body in files.items():
        (OUT / name).write_text(body, encoding="utf-8", newline="\n")
        print(f"wrote docs/img/{name}  ({len(body) // 1024 or 1} KiB)")


if __name__ == "__main__":
    main()
