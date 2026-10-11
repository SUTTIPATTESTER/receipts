import unittest

from receipts.policy import PolicyError, parse_policy
from receipts.spec import ReceiptError, parse_receipt

BUG = '''
version = 1
kind = "bug"
title = "boom"

[run]
command = "python repro.py"

[expect]
fail_output_contains = "ZeroDivisionError"

[[file]]
path = "repro.py"
content = "print(1/0)"
'''


def bug(**swaps):
    text = BUG
    for old, new in swaps.items():
        text = text.replace(old.replace("__", " "), new)
    return text


class ParseReceipt(unittest.TestCase):
    def test_valid_bug(self):
        r = parse_receipt(BUG)
        self.assertEqual((r.kind, r.command, r.timeout), ("bug", "python repro.py", 60))
        self.assertEqual(r.files[0].path, "repro.py")

    def test_valid_fix_with_overlay(self):
        r = parse_receipt('version = 1\nkind = "fix"\ntitle = "t"\n[run]\ncommand = "pytest"\n'
                          'overlay = ["tests/test_x.py"]\n')
        self.assertEqual(r.overlay, ("tests/test_x.py",))
        self.assertIsNone(r.signature)

    def test_unknown_keys_are_rejected(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG + "\nsneaky = 1\n")
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace("[expect]", "[expect]\nextra = 1"))

    def test_bad_paths_are_rejected(self):
        for bad in ["../x", "/etc/passwd", "C:/x", "a\\\\b", ".github/workflows/x.yml", ".git/config",
                    ".receipts/policy.toml", "a/../../b", ""]:
            with self.subTest(path=bad):
                with self.assertRaises(ReceiptError):
                    parse_receipt(BUG.replace('path = "repro.py"', f'path = "{bad}"'))

    def test_bug_requires_a_failure_signature(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('[expect]\nfail_output_contains = "ZeroDivisionError"\n', ""))

    def test_signature_must_not_be_echoed_by_the_command(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('python repro.py', 'echo ZeroDivisionError'))

    def test_signature_has_a_minimum_length(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace("ZeroDivisionError", "E"))

    def test_timeout_must_be_a_real_integer(self):
        for bad in ("true", "0", "99999", '"60"', "1.5"):
            with self.subTest(timeout=bad):
                with self.assertRaises(ReceiptError):
                    parse_receipt(BUG.replace('command = "python repro.py"', f'command = "python repro.py"\ntimeout = {bad}'))

    def test_overlay_is_for_fix_receipts_only(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('command = "python repro.py"', 'command = "python repro.py"\noverlay = ["a.py"]'))

    def test_duplicate_and_oversized_files(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG + '\n[[file]]\npath = "repro.py"\ncontent = "x"\n')
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('content = "print(1/0)"', 'content = "' + "x" * 70000 + '"'))

    def test_wrong_version_and_kind(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace("version = 1", "version = 2"))
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('kind = "bug"', 'kind = "feature"'))

    def test_newlines_in_single_line_fields(self):
        with self.assertRaises(ReceiptError):
            parse_receipt(BUG.replace('title = "boom"', 'title = "a\\nb"'))

    def test_not_toml(self):
        with self.assertRaises(ReceiptError):
            parse_receipt("this is not toml = = =")


class ParsePolicy(unittest.TestCase):
    def test_defaults_and_overrides(self):
        p = parse_policy('image = "python:3.12-slim"\nmax_timeout = 30\ndocs_url = "https://example.org/x"\n')
        self.assertEqual((p.image, p.max_timeout, p.docs_url), ("python:3.12-slim", 30, "https://example.org/x"))

    def test_rejects_flag_injection_and_junk(self):
        for text in ['image = "--privileged"', 'image = "a b"', 'memory = "lots"', 'cpus = "-1"',
                     'docs_url = "javascript:alert(1)"', 'mystery = 1', 'max_timeout = true']:
            with self.subTest(policy=text):
                with self.assertRaises(PolicyError):
                    parse_policy(text)


if __name__ == "__main__":
    unittest.main()
