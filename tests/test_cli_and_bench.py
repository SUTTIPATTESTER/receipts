import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from receipts import workspace as ws
from receipts.bench import run_bench
from receipts.cli import main
from receipts.extract import extract_receipt

from . import ROOT

EX = ROOT / "examples" / "average"
LOCAL = ["--sandbox", "local", "--unsafe-local", "--color", "never"]


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class Bench(unittest.TestCase):
    def test_every_case_behaves_as_specified(self):
        results = run_bench(ROOT / "bench" / "cases")
        self.assertGreaterEqual(len(results), 19)
        wrong = [(r.name, r.expected, r.got) for r in results if not r.ok]
        self.assertEqual(wrong, [])


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="receipts-test-"))
        self.addCleanup(ws.rmtree_force, self.tmp)

    def test_verified_fix_writes_json_and_markdown(self):
        j, m = self.tmp / "v.json", self.tmp / "c.md"
        code, out, _ = run("verify", "--base-dir", str(EX / "base"), "--head-dir", str(EX / "fix"), *LOCAL,
                           "--strict", "--subject", "pull_request:7", "--json-out", str(j), "--markdown-out", str(m))
        self.assertEqual(code, 0, out)
        data = json.loads(j.read_text(encoding="utf-8"))
        self.assertEqual((data["verdict"], data["good"], data["label"]), ("verified", True, "receipt:verified"))
        self.assertEqual(data["subject"], {"type": "pull_request", "number": 7})
        self.assertIn("Receipt verified", m.read_text(encoding="utf-8"))

    def test_vacuous_fix_fails_strict(self):
        code, out, _ = run("verify", "--base-dir", str(EX / "base"), "--head-dir", str(EX / "vacuous"), *LOCAL, "--strict")
        self.assertEqual(code, 1)
        self.assertIn("VACUOUS", out)

    def test_bug_receipt_reproduces(self):
        code, out, _ = run("verify", "--base-dir", str(EX / "base"), "--receipt", str(EX / "bug.toml"), *LOCAL, "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("REPRODUCED", out)

    def test_local_sandbox_needs_explicit_opt_in(self):
        code, _, err = run("verify", "--base-dir", str(EX / "base"), "--receipt", str(EX / "bug.toml"), "--sandbox", "local")
        self.assertEqual(code, 2)
        self.assertIn("--unsafe-local", err)

    def test_missing_docker_is_an_error_verdict_not_a_crash(self):
        if shutil.which("docker"):
            self.skipTest("docker is installed here")
        code, out, _ = run("verify", "--base-dir", str(EX / "base"), "--receipt", str(EX / "bug.toml"), "--strict",
                           "--color", "never")
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)

    def test_policy_in_the_pull_request_is_ignored(self):
        evil = self.tmp / "evil"
        shutil.copytree(EX / "fix", evil)
        (evil / ".receipts" / "policy.toml").write_text('max_timeout = 3600\nsetup = "echo pwned"\n', encoding="utf-8")
        code, out, _ = run("verify", "--base-dir", str(EX / "base"), "--head-dir", str(evil), *LOCAL, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("pwned", out)

    def test_git_mode_end_to_end(self):
        repo = self.tmp / "repo"
        shutil.copytree(EX / "base", repo)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
        shutil.copytree(EX / "fix", repo, dirs_exist_ok=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "fix"], check=True)
        code, out, _ = run("verify", "--repo", str(repo), "--base-ref", "HEAD~1", "--head-ref", "HEAD", *LOCAL, "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("VERIFIED", out)


class ExtractLintRender(unittest.TestCase):
    BODY = "Steps\r\n\r\n```toml receipt\r\nversion = 1\r\nkind = \"bug\"\r\ntitle = \"t\"\r\n\r\n" \
           "[run]\r\ncommand = \"python repro.py\"\r\n\r\n[expect]\r\nfail_output_contains = \"Boom\"\r\n```\r\n\r\nthanks"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="receipts-test-"))
        self.addCleanup(ws.rmtree_force, self.tmp)

    def test_extract_handles_crlf_and_both_fence_styles(self):
        self.assertIn('kind = "bug"', extract_receipt(self.BODY))
        self.assertIn("version = 1", extract_receipt("~~~receipt\nversion = 1\n~~~"))
        self.assertIsNone(extract_receipt("```python\nprint(1)\n```"))
        self.assertIsNone(extract_receipt("no code here"))

    def test_extract_then_lint(self):
        body, out = self.tmp / "body.md", self.tmp / "r.toml"
        body.write_text(self.BODY, encoding="utf-8", newline="")
        self.assertEqual(run("extract", "--body-file", str(body), "--out", str(out))[0], 0)
        code, text, _ = run("lint", str(out))
        self.assertEqual(code, 0, text)
        self.assertEqual(run("extract", "--body-file", str(body.with_name("nope.md")), "--out", str(out))[0], 2)

    def test_init_templates_are_valid(self):
        for kind in ("bug", "fix"):
            path = self.tmp / f"{kind}.toml"
            self.assertEqual(run("init", "--kind", kind, str(path))[0], 0)
            code, text, _ = run("lint", str(path))
            self.assertEqual(code, 0, text)
            self.assertEqual(run("init", "--kind", kind, str(path))[0], 2)  # refuses to overwrite

    def test_render_rejects_forged_verdicts(self):
        forged = self.tmp / "forged.json"
        forged.write_text(json.dumps({"schema": 1, "verdict": "verified", "subject": {"type": "issue", "number": "7; x"}}))
        code, _, err = run("render", "--verdict", str(forged), "--markdown-out", str(self.tmp / "o.md"))
        self.assertEqual(code, 2)
        self.assertIn("rejected", err)
        self.assertFalse((self.tmp / "o.md").exists())


if __name__ == "__main__":
    unittest.main()
