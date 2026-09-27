"""Exercise the goal loop with a local fake CLI; no model calls are made."""

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "pdocs" / "codex_goal_loop.py"


@unittest.skipUnless(os.name == "posix", "the loop uses POSIX process groups")
class CodexGoalLoopTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "ptmp" / "codex-goal-loop-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.log_dir = self.work / "logs"
        self.fake = self.work / "fake codex"
        self.fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
            import json
            import os
            from pathlib import Path
            import signal
            import subprocess
            import sys
            import time

            work = Path(os.environ["CODEX_LOOP_TEST_DIR"])
            mode = os.environ.get("CODEX_LOOP_TEST_MODE", "success")
            calls = work / "calls.jsonl"
            count = len(calls.read_text().splitlines()) if calls.exists() else 0
            record = {"argv": sys.argv[1:], "cwd": os.getcwd(),
                      "stdin": sys.stdin.read(), "pid": os.getpid()}
            with calls.open("a") as output:
                output.write(json.dumps(record) + "\\n")
            if mode in ("timeout", "interrupt", "orphan") and count == 0:
                code = ("import signal, time; "
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                        "print('grandchild ready', flush=True); time.sleep(30)")
                child = subprocess.Popen([sys.executable, "-c", code])
                (work / "grandchild.pid").write_text(str(child.pid))
                if mode != "orphan":
                    # No output from the leader, even while the pipe remains open.
                    time.sleep(30)
                sys.exit(0)
            os.write(1, "标准输出\\n".encode("utf-8"))
            os.write(2, b"stderr output\\n")
            os.write(1, b"invalid utf8: \\xff\\npartial tail")
            sys.exit(3 if mode == "fail-first" and count == 0 else 0)
            '''), encoding="utf-8")
        self.fake.chmod(0o755)
        self.driver = self.work / "driver.py"
        self.driver.write_text(textwrap.dedent(f'''\
            import importlib.util
            from pathlib import Path
            import sys

            spec = importlib.util.spec_from_file_location("codex_goal_loop", {str(SCRIPT)!r})
            loop = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loop)
            loop.LOG_DIR = Path({str(self.log_dir)!r})
            sys.exit(loop.main())
            '''), encoding="utf-8")
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        for call in self.calls():
            try:
                os.killpg(call["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass

    def start(self, *args, mode="success"):
        env = dict(os.environ, CODEX_LOOP_TEST_DIR=str(self.work),
                   CODEX_LOOP_TEST_MODE=mode, PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.Popen(
            [sys.executable, str(self.driver), "--codex", str(self.fake),
             "--no-tui", "--max-runs", "1", "--sleep", "0", "--timeout", "5", *args],
            cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def run_loop(self, *args, mode="success"):
        process = self.start(*args, mode=mode)
        stdout, stderr = process.communicate(input="must not become task context", timeout=15)
        return process.returncode, stdout, stderr

    def calls(self):
        path = self.work / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def records(self):
        return [json.loads(line) for line in (self.log_dir / "runs.jsonl").read_text().splitlines()]

    def assert_grandchild_stopped(self):
        pid = int((self.work / "grandchild.pid").read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
            except FileNotFoundError:
                return
            if stat.rsplit(") ", 1)[1].split()[0] == "Z":
                return
            time.sleep(0.02)
        self.fail(f"grandchild {pid} is still running")

    def test_dry_run_quotes_options_without_launching(self):
        code, stdout, stderr = self.run_loop(
            "--dry-run", "--model", "test-model", "--profile", "profile name")
        self.assertEqual(code, 0, stderr)
        tokens = shlex.split(stdout.strip())
        self.assertEqual(tokens[:4], ["cd", str(ROOT), "&&", str(self.fake)])
        self.assertIn("test-model", tokens)
        self.assertIn("profile name", tokens)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", tokens)
        self.assertNotIn("--sandbox", tokens)
        self.assertNotIn("--ask-for-approval", tokens)
        self.assertNotIn("--approve-for-me", tokens)
        self.assertFalse(self.calls())
        self.assertFalse(self.log_dir.exists())

    def test_never_approval_remains_explicitly_available(self):
        code, stdout, stderr = self.run_loop("--dry-run", "--approval", "never")
        self.assertEqual(code, 0, stderr)
        tokens = shlex.split(stdout.strip())
        self.assertIn('approval_policy="never"', tokens)
        self.assertFalse(any(token.startswith("approvals_reviewer=") for token in tokens))
        self.assertIn("workspace-write", tokens)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", tokens)
        self.assertFalse(self.calls())

    def test_auto_review_uses_exec_flag(self):
        code, stdout, stderr = self.run_loop("--dry-run", "--approval", "auto-review")
        self.assertEqual(code, 0, stderr)
        tokens = shlex.split(stdout.strip())
        self.assertIn("--approve-for-me", tokens)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", tokens)
        self.assertNotIn("--ask-for-approval", tokens)
        self.assertFalse(self.calls())

    def test_sandbox_override_requires_compatible_approval_mode(self):
        for args in (("--sandbox", "workspace-write"),
                     ("--approval", "bypass", "--sandbox", "read-only"),
                     ("--approval", "auto-review", "--sandbox", "danger-full-access")):
            with self.subTest(args=args):
                code, _, stderr = self.run_loop("--dry-run", *args)
                self.assertEqual(code, 2)
                self.assertIn("sandbox", stderr)
                self.assertFalse(self.calls())
        code, stdout, stderr = self.run_loop(
            "--dry-run", "--approval", "never", "--sandbox", "read-only")
        self.assertEqual(code, 0, stderr)
        tokens = shlex.split(stdout.strip())
        self.assertEqual(tokens[tokens.index("--sandbox") + 1], "read-only")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", tokens)

    def test_continues_after_failure_and_records_all_output(self):
        code, stdout, stderr = self.run_loop("--max-runs", "2", mode="fail-first")
        self.assertEqual(code, 0, stderr)
        records = self.records()
        self.assertEqual([row["label"] for row in records], ["exit-3", "success"])
        self.assertEqual([row["exit_code"] for row in records], [3, 0])
        self.assertEqual(len({row["run_id"] for row in records}), 2)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call, row in zip(calls, records):
            self.assertEqual(call["cwd"], str(ROOT))
            self.assertEqual(call["stdin"], "")
            self.assertEqual(call["argv"], row["command"][1:])
            self.assertEqual(call["argv"][:4],
                             ["exec", "--dangerously-bypass-approvals-and-sandbox",
                              "--color", "never"])
            self.assertTrue(call["argv"][-1].startswith("按照 pdocs/"))
            self.assertIn("先提交子模块，再提交根仓库", call["argv"][-1])
            self.assertIn("未完成节点不提前提交", call["argv"][-1])
            self.assertIn("已授权上述节点的正常暂存和最终提交", call["argv"][-1])
            output = Path(row["log"]).read_text()
            for text in ("标准输出", "stderr output", "invalid utf8: \ufffd", "partial tail"):
                self.assertIn(text, output)
                self.assertIn(text, stdout)

    def test_timeout_kills_descendants_and_advances(self):
        code, stdout, stderr = self.run_loop(
            "--max-runs", "2", "--timeout", "0.8", mode="timeout")
        self.assertEqual(code, 0, stderr)
        records = self.records()
        self.assertEqual([row["label"] for row in records], ["timeout", "success"])
        self.assertEqual(records[0]["exit_code"], -signal.SIGKILL)
        self.assertIn("killing process group", stdout)
        self.assert_grandchild_stopped()

    def test_exited_leader_does_not_leave_inherited_pipe_open(self):
        code, _, stderr = self.run_loop("--timeout", "0", mode="orphan")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.records()[0]["label"], "success")
        self.assert_grandchild_stopped()

    def test_interrupt_is_indexed_and_cleans_up(self):
        process = self.start(mode="interrupt")
        ready = self.work / "grandchild.pid"
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(ready.exists(), "fake CLI failed to start")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 130, stderr)
        self.assertIn("loop interrupted by user", stdout)
        self.assertEqual(self.records()[0]["label"], "interrupted")
        self.assertEqual(len(self.calls()), 1)
        self.assert_grandchild_stopped()

    def test_missing_executable_stops_instead_of_retrying(self):
        code, _, _ = self.run_loop("--codex", str(self.work / "absent"), "--max-runs", "2")
        self.assertEqual(code, 2)
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["label"], "codex-not-found")

    def test_rejects_invalid_limits_before_launch(self):
        for option, value in (("--max-runs", "-1"), ("--sleep", "-1"),
                              ("--timeout", "nan"), ("--timeout", "inf")):
            with self.subTest(option=option, value=value):
                code, _, stderr = self.run_loop(option, value)
                self.assertEqual(code, 2)
                self.assertIn("nonnegative", stderr)
                self.assertFalse(self.calls())


if __name__ == "__main__":
    unittest.main()
