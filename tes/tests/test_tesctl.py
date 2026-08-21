#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
TESCTL = REPO / "tes" / "tools" / "tesctl.py"
SPEC = importlib.util.spec_from_file_location("tesctl", TESCTL)
assert SPEC is not None and SPEC.loader is not None
tesctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tesctl)


class EvalSequenceTest(unittest.TestCase):
    def test_sequence_is_task_wide(self) -> None:
        entries = [
            {"run": "r001", "eval_id": "e00050"},
            {"run": "r002", "eval_id": "e00034"},
            {"kind": "commit-marker", "eval_id": "e00007"},
        ]

        self.assertEqual(tesctl.next_task_eval_number(entries), 51)

    def test_configured_r003_solution_is_r002_e00007(self) -> None:
        tesctl.TASK_DIR = REPO / "tes" / "grhsim-am-coremark"

        solution = tesctl.resolve_base_eval("r002/e00007")

        self.assertEqual(
            solution["commit"],
            "ecb4c3f3c6b26cd0aed3491a1a9444959a4a73fb",
        )
        self.assertEqual(len(solution["emit_args"]), 10)
        self.assertIn("--wide-detect-fast-path", solution["emit_args"])
        self.assertNotIn("--scan-branch-hints", solution["emit_args"])

    def test_run_qualifier_disambiguates_reused_eval_ids(self) -> None:
        tesctl.TASK_DIR = REPO / "tes" / "grhsim-am-coremark"

        solution = tesctl.resolve_base_eval("r002/e00007")

        self.assertEqual(solution["run"], "r002")
        self.assertEqual(solution["eval_id"], "e00007")

    def test_base_eval_requires_ledger_commit(self) -> None:
        entry = {
            "run": "r002",
            "eval_id": "e00007",
            "status": "ok",
            "committed": True,
            "emit_args": ["--wide-detect-fast-path"],
        }
        with (
            mock.patch.object(tesctl, "iter_ledger", return_value=iter([entry])),
            mock.patch.object(tesctl, "load_config", return_value={}),
        ):
            with self.assertRaisesRegex(ValueError, "缺少可复现的 commit"):
                tesctl.resolve_base_eval("r002/e00007")

    def test_prepared_solution_must_match_ledger_and_result(self) -> None:
        commit = "a" * 40
        entry = {
            "run": "r002",
            "eval_id": "e00007",
            "status": "ok",
            "committed": True,
            "commit": commit,
            "result_json": "result.json",
        }
        prepared = {
            "source_run": "r002",
            "source_eval": "e00007",
            "commit": commit,
            "emit_args": ["--prepared"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "result.json").write_text(
                '{"emit_args": ["--recorded"]}\n', encoding="utf-8"
            )
            with (
                mock.patch.object(tesctl, "REPO", Path(tmp)),
                mock.patch.object(tesctl, "iter_ledger", return_value=iter([entry])),
                mock.patch.object(
                    tesctl,
                    "load_config",
                    return_value={"restart": {"prepared_solution": prepared}},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "emit_args 不一致"):
                    tesctl.resolve_base_eval("r002/e00007")

        prepared["emit_args"] = ["--recorded"]
        prepared["commit"] = "b" * 40
        with (
            mock.patch.object(tesctl, "iter_ledger", return_value=iter([entry])),
            mock.patch.object(
                tesctl,
                "load_config",
                return_value={"restart": {"prepared_solution": prepared}},
            ),
        ):
            with self.assertRaisesRegex(ValueError, "commit 不一致"):
                tesctl.resolve_base_eval("r002/e00007")

    def test_base_commit_is_only_a_matching_assertion(self) -> None:
        tesctl.TASK_DIR = REPO / "tes" / "grhsim-am-coremark"
        args = SimpleNamespace(
            run_id="r003",
            base_commit="b" * 40,
            base_eval="r002/e00007",
            base_emit_args=None,
            C=None,
            L=None,
            K=None,
            force=False,
        )
        config = {
            "search": {"C": 2, "L": 8, "K": 2},
            "phi": {},
            "eval": {"emit_args": []},
            "restart": {},
        }
        source = {
            "run": "r002",
            "eval_id": "e00007",
            "commit": "a" * 40,
            "emit_args": ["--wide-detect-fast-path"],
        }
        fake_run_path = mock.Mock()
        fake_run_path.exists.return_value = True
        with (
            mock.patch.object(tesctl, "run_json_path", return_value=fake_run_path),
            mock.patch.object(
                tesctl, "load_run", return_value={"status": "completed", "run_id": "r002"}
            ),
            mock.patch.object(tesctl, "load_config", return_value=config),
            mock.patch.object(tesctl, "resolve_base_eval", return_value=source),
            mock.patch.object(tesctl, "git_target", side_effect=["b" * 40, "a" * 40]),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(tesctl.cmd_init_run(args), 1)
        self.assertIn("与 --base-eval r002/e00007 的 commit", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
