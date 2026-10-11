import json
import unittest

from receipts.report import (defuse, md_escape, render_markdown, safe_block, safe_inline, strip_ansi,
                             verdict_from_untrusted)
from receipts.verify import RunInfo, Verdict

ZWSP = "​"


def sample(**kw):
    runs = [RunInfo("base", "fail", "fail", 1, 0.12, "Traceback...\nZeroDivisionError: division by zero"),
            RunInfo("head", "pass", "pass", 0, 0.10, "OK")]
    base = dict(verdict="verified", kind="fix", title="average([]) is fixed",
                command="python tests/t.py", runs=runs, subject={"type": "pull_request", "number": 12})
    base.update(kw)
    return Verdict(**base)


class Sanitising(unittest.TestCase):
    def test_mentions_are_defused(self):
        self.assertNotIn("@everyone", defuse("hi @everyone and @octocat"))
        self.assertIn("@" + ZWSP + "everyone", defuse("@everyone"))
        self.assertEqual(defuse("a@ b"), "a@ b")

    def test_ansi_and_control_characters_are_stripped(self):
        self.assertEqual(strip_ansi("\x1b[31mred\x1b[0m\x07\x00ok"), "redok")

    def test_block_cannot_be_closed_by_the_output(self):
        block = safe_block("before\n```\n# I escaped the block\n@maintainers\n````\nafter")
        fence = block.splitlines()[0].replace("text", "")
        self.assertGreaterEqual(len(fence), 5)  # longer than the longest run (4) inside the output
        self.assertEqual(block.splitlines()[-1], fence)
        self.assertNotIn("@maintainers", block)

    def test_block_keeps_only_the_tail(self):
        body = "\n".join(f"line {i}" for i in range(500))
        block = safe_block(body, max_lines=10)
        self.assertIn("line 499", block)
        self.assertNotIn("line 100\n", block)
        self.assertIn("earlier lines hidden", block)

    def test_inline_has_no_backticks_or_newlines(self):
        text = safe_inline("a`b\nc @someone")
        self.assertEqual(text.count("`"), 2)
        self.assertNotIn("\n", text)
        self.assertNotIn("@someone", text)

    def test_markdown_escape(self):
        self.assertNotIn("<script>", md_escape("<script>alert(1)</script> [x](http://evil)"))


class Rendering(unittest.TestCase):
    def test_comment_has_marker_and_verdict(self):
        md = render_markdown(sample())
        self.assertIn("<!-- receipts:v1 -->", md)
        self.assertIn("Receipt verified", md)
        self.assertIn("| base | FAIL |", md)

    def test_hostile_receipt_content_cannot_ping_or_break_out(self):
        evil = sample(verdict="wrong-failure", title="@everyone `click`", command="echo @maintainers",
                      runs=[RunInfo("base", "fail", "fail", 1, 0.1, "```\n@octocat\n```\n<img src=x onerror=1>")])
        md = render_markdown(evil)
        for raw in ("@everyone", "@maintainers", "@octocat"):
            self.assertNotIn(raw, md)

    def test_docs_url_only_if_https(self):
        self.assertIn("https://example.org/docs", render_markdown(sample(docs_url="https://example.org/docs")))
        self.assertNotIn("javascript:", render_markdown(sample(docs_url="javascript:alert(1)")))


class UntrustedJson(unittest.TestCase):
    def test_round_trip(self):
        original = sample()
        loaded = verdict_from_untrusted(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(loaded.verdict, "verified")
        self.assertEqual(loaded.subject, {"type": "pull_request", "number": 12})
        self.assertEqual(len(loaded.runs), 2)

    def test_rejections(self):
        good = sample().to_dict()
        cases = {
            "not an object": [],
            "bad schema": {**good, "schema": 2},
            "unknown verdict": {**good, "verdict": "approved-by-god"},
            "bad subject type": {**good, "subject": {"type": "repo", "number": 1}},
            "negative number": {**good, "subject": {"type": "issue", "number": -5}},
            "string number": {**good, "subject": {"type": "issue", "number": "1; rm -rf"}},
            "huge output": {**good, "runs": [{**good["runs"][0], "output": "x" * 400_000}]},
            "too many runs": {**good, "runs": good["runs"] * 3},
            "bad outcome": {**good, "runs": [{**good["runs"][0], "outcome": "owned"}]},
            "http docs url": {**good, "docs_url": "http://example.org"},
            "bad version": {**good, "receipts_version": "1.0\nFOO=bar"},
        }
        for name, payload in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    verdict_from_untrusted(payload)


if __name__ == "__main__":
    unittest.main()
