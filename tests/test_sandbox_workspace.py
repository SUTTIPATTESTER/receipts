import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from receipts import workspace as ws
from receipts.policy import Policy
from receipts.sandbox import DockerSandbox, LocalSandbox


class DockerArgv(unittest.TestCase):
    def setUp(self):
        self.sandbox = DockerSandbox(Policy())
        self.argv = self.sandbox.argv(Path("/tmp/w"), "python -c 'print(1)'; echo $HOME", name="n", network=False)

    def pair(self, flag):
        index = self.argv.index(flag)
        return self.argv[index + 1]

    def test_isolation_flags(self):
        self.assertEqual(self.pair("--network"), "none")
        self.assertEqual(self.pair("--cap-drop"), "ALL")
        self.assertEqual(self.pair("--security-opt"), "no-new-privileges")
        self.assertIn("--read-only", self.argv)
        self.assertNotIn("--privileged", self.argv)
        self.assertEqual(self.pair("--memory"), self.pair("--memory-swap"))

    def test_command_is_a_single_argument(self):
        self.assertEqual(self.argv[-3:-1], ["sh", "-c"])
        self.assertEqual(self.argv[-1], "python -c 'print(1)'; echo $HOME")

    def test_only_fixed_environment_is_passed(self):
        names = {self.argv[i + 1].split("=")[0] for i, a in enumerate(self.argv) if a == "-e"}
        self.assertEqual(names, {"HOME", "CI", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED"})

    def test_network_only_for_setup(self):
        online = self.sandbox.argv(Path("/tmp/w"), "pip install -r r.txt", name="n", network=True)
        self.assertEqual(online[online.index("--network") + 1], "bridge")


class LocalSandboxBehaviour(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="receipts-test-"))
        self.addCleanup(ws.rmtree_force, self.dir)
        self.sandbox = LocalSandbox(Policy(max_output_bytes=2048))

    def test_secrets_in_the_host_environment_do_not_leak(self):
        os.environ["RECEIPTS_TEST_SECRET"] = "s3cret-value"
        self.addCleanup(os.environ.pop, "RECEIPTS_TEST_SECRET", None)
        res = self.sandbox.run(
            self.dir, 'python -c "import os; print(os.environ.get(\'RECEIPTS_TEST_SECRET\', \'absent\'))"', timeout=30)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("absent", res.output)
        self.assertNotIn("s3cret-value", res.output)

    def test_timeout_kills_the_command(self):
        res = self.sandbox.run(self.dir, 'python -c "import time; time.sleep(60)"', timeout=1)
        self.assertTrue(res.timed_out)
        self.assertLess(res.duration_s, 20)

    def test_output_is_capped_to_the_tail(self):
        res = self.sandbox.run(self.dir, 'python -c "print(\'x\' * 100000); print(\'THE-END\')"', timeout=30)
        self.assertLess(len(res.output), 3000)
        self.assertIn("THE-END", res.output)
        self.assertIn("truncated", res.output)


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="receipts-test-"))
        self.addCleanup(ws.rmtree_force, self.tmp)

    def make(self, name, files):
        root = self.tmp / name
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return root

    def test_changed_files(self):
        a = self.make("a", {"x.py": "1", "y.py": "same", "gone.py": "g"})
        b = self.make("b", {"x.py": "2", "y.py": "same", "new.py": "n"})
        self.assertEqual(ws.changed_files(a, b), ["gone.py", "new.py", "x.py"])

    def test_same_size_different_content_is_detected(self):
        a = self.make("a", {"x.py": "aaaa"})
        b = self.make("b", {"x.py": "bbbb"})
        self.assertEqual(ws.changed_files(a, b), ["x.py"])

    def test_copy_skips_git_dir_and_symlinks(self):
        src = self.make("src", {"keep.txt": "k", ".git/config": "secret", "sub/ok.txt": "o"})
        outside = self.make("outside", {"host-secret.txt": "top secret"})
        try:
            os.symlink(outside / "host-secret.txt", src / "link.txt")
            os.symlink(outside, src / "linkdir", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        dst = self.tmp / "dst"
        skipped = ws.copy_tree(src, dst)
        self.assertTrue((dst / "keep.txt").exists() and (dst / "sub" / "ok.txt").exists())
        self.assertFalse((dst / ".git").exists())
        self.assertFalse((dst / "link.txt").exists())
        self.assertFalse((dst / "linkdir").exists())
        self.assertEqual(sorted(skipped), ["link.txt", "linkdir"])

    def test_archive_traversal_is_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo("../escape.txt")
            data = b"nope"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        with tarfile.open(fileobj=buf) as tar:
            with self.assertRaises(ws.WorkspaceError):
                ws.safe_extract(tar, self.tmp / "out")
        self.assertFalse((self.tmp / "escape.txt").exists())

    def test_archive_symlinks_are_dropped(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            link = tarfile.TarInfo("evil")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
            ok = tarfile.TarInfo("ok.txt")
            ok.size = 2
            tar.addfile(ok, io.BytesIO(b"hi"))
        buf.seek(0)
        with tarfile.open(fileobj=buf) as tar:
            skipped = ws.safe_extract(tar, self.tmp / "out")
        self.assertEqual(skipped, ["evil"])
        self.assertTrue((self.tmp / "out" / "ok.txt").exists())
        self.assertFalse((self.tmp / "out" / "evil").exists())

    def test_git_export_has_no_dot_git(self):
        repo = self.make("repo", {"a.txt": "one"})
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        out = self.tmp / "export"
        ws.export_ref(repo, "HEAD", out)
        self.assertEqual((out / "a.txt").read_text(), "one")
        self.assertFalse((out / ".git").exists())

    def test_suspicious_refs_are_refused(self):
        for ref in ("--output=/tmp/x", "-h", "a b", "a;b", ""):
            with self.subTest(ref=ref):
                with self.assertRaises(ws.WorkspaceError):
                    ws.export_ref(self.tmp, ref, self.tmp / "o")


if __name__ == "__main__":
    unittest.main()
