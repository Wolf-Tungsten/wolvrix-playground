#!/usr/bin/env python3

import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from wolvrix import _compile_emit_grhsim_cpp_kwargs, _compile_run_pass


SCRIPT = Path(__file__).with_name("wolvrix_xs_grhsim.py")
MODULE = runpy.run_path(str(SCRIPT), run_name="wolvrix_xs_grhsim_option_test")
ENV_OPTIONAL_FLAG = MODULE["env_optional_flag"]
FORMAT_OPTIONAL_FLAG = MODULE["format_optional_flag"]
READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS = MODULE["read_activity_schedule_sparse_options"]
ACTIVITY_SCHEDULE_SPARSE_BOOL_OPTIONS = MODULE["ACTIVITY_SCHEDULE_SPARSE_BOOL_OPTIONS"]
ACTIVITY_SCHEDULE_SPARSE_INTEGER_OPTIONS = MODULE["ACTIVITY_SCHEDULE_SPARSE_INTEGER_OPTIONS"]
ACTIVITY_SCHEDULE_SPARSE_STRING_OPTIONS = MODULE["ACTIVITY_SCHEDULE_SPARSE_STRING_OPTIONS"]
READ_FINAL_SIBLING_FUSION_OPTIONS = MODULE["read_final_sibling_fusion_options"]
READ_ACTIVE_MASK_GAP_PACK_OPTIONS = MODULE["read_active_mask_gap_pack_options"]
DESCRIBE_ACTIVE_MASK_GAP_PACK_POLICY = MODULE["describe_active_mask_gap_pack_policy"]
FORMAT_NATIVE_DEFAULT_OPTION = MODULE["format_native_default_option"]

ACTIVITY_SCHEDULE_SPARSE_ENV_NAMES = {
    env_name
    for env_name, _ in (
        *ACTIVITY_SCHEDULE_SPARSE_BOOL_OPTIONS,
        *ACTIVITY_SCHEDULE_SPARSE_INTEGER_OPTIONS,
        *ACTIVITY_SCHEDULE_SPARSE_STRING_OPTIONS,
    )
}

ACTIVITY_SCHEDULE_EXPLICIT_ENV = {
    "WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE": "8192",
    "WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS": "0",
    "WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY": "1",
    "WOLVRIX_XS_GRHSIM_ENABLE_LOCAL_SHARED_COMPUTE": "false",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_FANOUT": "3",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_WIDTH": "65",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_CLONES": "4097",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_CLONED_OP_PPM": "5001",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_COMMON_OWNER_POLICY": "probe",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_COMMON_OWNER_MAX_CLONES": "4098",
    "WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_COMMON_OWNER_MAX_CLONED_OP_PPM": "5002",
    "WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM": "999999",
    "WOLVRIX_XS_GRHSIM_POST_DP_REFINE_POLICY": "balanced",
    "WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_ROUNDS": "2",
    "WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_MOVES": "4099",
    "WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_MOVED_OP_PPM": "10001",
    "WOLVRIX_XS_GRHSIM_POST_DP_REFINE_MAX_REGRESSION_PPM": "10002",
    "WOLVRIX_XS_GRHSIM_KAHN_LEVEL_PACK_POLICY": "bae-budget",
    "WOLVRIX_XS_GRHSIM_KAHN_LEVEL_PACK_MAX_MOVES": "4100",
    "WOLVRIX_XS_GRHSIM_KAHN_LEVEL_PACK_MAX_MOVED_OP_PPM": "10003",
    "WOLVRIX_XS_GRHSIM_KAHN_LEVEL_PACK_MAX_REGRESSION_PPM": "10004",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_POLICY": "probe",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_MAX_NODE_OPS": "9",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_MAX_VALUE_WIDTH": "65",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_MIN_GAIN": "4",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_MAX_MOVES": "4101",
    "WOLVRIX_XS_GRHSIM_FINAL_FANIN_PULLBACK_MAX_MOVED_OP_PPM": "5003",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_POLICY": "probe",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_PROFILE_PATH": "/tmp/fire.tsv",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_NODE_OPS": "9",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_INPUTS": "17",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_OUTPUTS": "18",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_VALUE_WIDTH": "65",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MIN_BAE_GAIN": "2",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MIN_BOUNDARY_VALUE_GAIN": "3",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_MOVES": "129",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_MAX_MOVED_OP_PPM": "201",
    "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_PROFILE_MIN_SOURCE_FIRE": "1234",
    "WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY": "level-op",
}

ACTIVITY_SCHEDULE_EXPLICIT_OPTIONS = {
    "max_op_in_commit_supernode": 8192,
    "commit_guard_event_buckets": False,
    "declared_value_compute_node_boundary": True,
    "enable_local_shared_compute": False,
    "local_shared_compute_max_fanout": 3,
    "local_shared_compute_max_width": 65,
    "local_shared_compute_max_clones": 4097,
    "local_shared_compute_max_cloned_op_ppm": 5001,
    "local_shared_compute_common_owner_policy": "probe",
    "local_shared_compute_common_owner_max_clones": 4098,
    "local_shared_compute_common_owner_max_cloned_op_ppm": 5002,
    "dp_segment_penalty_ppm": 999999,
    "post_dp_refine_policy": "balanced",
    "post_dp_refine_max_rounds": 2,
    "post_dp_refine_max_moves": 4099,
    "post_dp_refine_max_moved_op_ppm": 10001,
    "post_dp_refine_max_regression_ppm": 10002,
    "kahn_level_pack_policy": "bae-budget",
    "kahn_level_pack_max_moves": 4100,
    "kahn_level_pack_max_moved_op_ppm": 10003,
    "kahn_level_pack_max_regression_ppm": 10004,
    "final_fanin_pullback_policy": "probe",
    "final_fanin_pullback_max_node_ops": 9,
    "final_fanin_pullback_max_value_width": 65,
    "final_fanin_pullback_min_gain": 4,
    "final_fanin_pullback_max_moves": 4101,
    "final_fanin_pullback_max_moved_op_ppm": 5003,
    "final_terminal_pushforward_policy": "probe",
    "final_terminal_pushforward_profile_path": "/tmp/fire.tsv",
    "final_terminal_pushforward_max_node_ops": 9,
    "final_terminal_pushforward_max_inputs": 17,
    "final_terminal_pushforward_max_outputs": 18,
    "final_terminal_pushforward_max_value_width": 65,
    "final_terminal_pushforward_min_bae_gain": 2,
    "final_terminal_pushforward_min_boundary_value_gain": 3,
    "final_terminal_pushforward_max_moves": 129,
    "final_terminal_pushforward_max_moved_op_ppm": 201,
    "final_terminal_pushforward_profile_min_source_fire": 1234,
    "final_topo_policy": "level-op",
}


class XsGrhsimOptionTest(unittest.TestCase):
    def check_option(self, stem: str) -> None:
        high = f"WOLVRIX_XS_GRHSIM_{stem}"
        low = f"WOLVRIX_GRHSIM_{stem}"
        base = {key: value for key, value in os.environ.items() if key not in {high, low}}

        with patch.dict(os.environ, base, clear=True):
            before = dict(os.environ)
            self.assertIsNone(ENV_OPTIONAL_FLAG(high, low))
            self.assertEqual(os.environ, before)

        with patch.dict(os.environ, {**base, low: "0"}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), False)

        with patch.dict(os.environ, {**base, low: ""}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "0", high: "1"}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "0", high: ""}, clear=True):
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), True)

        with patch.dict(os.environ, {**base, low: "1", high: "0"}, clear=True):
            before = dict(os.environ)
            self.assertIs(ENV_OPTIONAL_FLAG(high, low), False)
            self.assertEqual(os.environ, before)

    def test_direct_override_precedence(self) -> None:
        self.check_option("DIRECT_SINGLE_WRITER_STATE_READS")

    def test_pure_event_override_precedence(self) -> None:
        self.check_option("PURE_EVENT_COMPUTE_WORD_BYPASS")

    def test_log_value_distinguishes_cpp_default(self) -> None:
        self.assertEqual(FORMAT_OPTIONAL_FLAG(None), "cpp-default")
        self.assertEqual(FORMAT_OPTIONAL_FLAG(False), "False")
        self.assertEqual(FORMAT_OPTIONAL_FLAG(True), "True")

    def test_activity_schedule_sparse_clean_environment_is_empty(self) -> None:
        base = {
            key: value
            for key, value in os.environ.items()
            if key not in ACTIVITY_SCHEDULE_SPARSE_ENV_NAMES
        }
        with patch.dict(os.environ, base, clear=True):
            self.assertEqual(READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS(), {})

    def test_activity_schedule_sparse_explicit_values(self) -> None:
        with patch.dict(os.environ, ACTIVITY_SCHEDULE_EXPLICIT_ENV, clear=True):
            self.assertEqual(
                READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS(),
                ACTIVITY_SCHEDULE_EXPLICIT_OPTIONS,
            )
        self.assertEqual(len(ACTIVITY_SCHEDULE_SPARSE_ENV_NAMES), 39)

    def test_activity_schedule_sparse_bool_false_is_forwarded(self) -> None:
        for env_name, option_name in ACTIVITY_SCHEDULE_SPARSE_BOOL_OPTIONS:
            with self.subTest(option_name=option_name):
                with patch.dict(os.environ, {env_name: "0"}, clear=True):
                    self.assertEqual(
                        READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS(),
                        {option_name: False},
                    )

    def test_activity_schedule_sparse_compiler_accepts_explicit_values(self) -> None:
        with patch.dict(os.environ, ACTIVITY_SCHEDULE_EXPLICIT_ENV, clear=True):
            options = READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS()
        canonical, args = _compile_run_pass(
            "activity-schedule",
            [],
            {"path": "SimTop", **options},
        )
        self.assertEqual(canonical, "activity-schedule")
        self.assertIn("-path", args)
        self.assertIn("-max-op-in-commit-supernode", args)
        self.assertEqual(len(args), 2 * 39 + 2)

    def test_final_terminal_pushforward_policy_is_sparse(self) -> None:
        env_name = "WOLVRIX_XS_GRHSIM_FINAL_TERMINAL_PUSHFORWARD_POLICY"
        for value in ("off", "probe", "strict"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {env_name: value}, clear=True):
                    options = READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS()
                self.assertEqual(options, {"final_terminal_pushforward_policy": value})
                canonical, args = _compile_run_pass(
                    "activity-schedule",
                    [],
                    {"path": "SimTop", **options},
                )
                self.assertEqual(canonical, "activity-schedule")
                self.assertEqual(
                    args,
                    ["-path", "SimTop", "-final-terminal-pushforward-policy", value],
                )

    def test_activity_schedule_sparse_invalid_integer_is_rejected(self) -> None:
        for env_name, option_name in ACTIVITY_SCHEDULE_SPARSE_INTEGER_OPTIONS:
            with self.subTest(option_name=option_name, value="bad"):
                with patch.dict(os.environ, {env_name: "bad"}, clear=True):
                    with self.assertRaises(ValueError):
                        READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS()
            with self.subTest(option_name=option_name, value="negative"):
                with patch.dict(os.environ, {env_name: "-1"}, clear=True):
                    options = READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS()
                    with self.assertRaises(ValueError):
                        _compile_run_pass(
                            "activity-schedule",
                            [],
                            {"path": "SimTop", **options},
                        )

    def test_activity_schedule_sparse_log_uses_cpp_defaults(self) -> None:
        base = {
            key: value
            for key, value in os.environ.items()
            if key not in ACTIVITY_SCHEDULE_SPARSE_ENV_NAMES
        }
        with patch.dict(os.environ, base, clear=True):
            options = READ_ACTIVITY_SCHEDULE_SPARSE_OPTIONS()
        for _, option_name in (
            *ACTIVITY_SCHEDULE_SPARSE_BOOL_OPTIONS,
            *ACTIVITY_SCHEDULE_SPARSE_INTEGER_OPTIONS,
            *ACTIVITY_SCHEDULE_SPARSE_STRING_OPTIONS,
        ):
            with self.subTest(option_name=option_name):
                self.assertEqual(FORMAT_NATIVE_DEFAULT_OPTION(options, option_name), "cpp-default")
        self.assertEqual(
            FORMAT_NATIVE_DEFAULT_OPTION({"commit_guard_event_buckets": False}, "commit_guard_event_buckets"),
            "False",
        )

    def test_final_sibling_fusion_defaults(self) -> None:
        names = {
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM",
        }
        base = {key: value for key, value in os.environ.items() if key not in names}
        with patch.dict(os.environ, base, clear=True):
            options = READ_FINAL_SIBLING_FUSION_OPTIONS()
            self.assertEqual(options, {})
            for name in (
                "final_sibling_fusion_policy",
                "final_sibling_fusion_min_gain",
                "final_sibling_fusion_max_pairs",
                "final_sibling_fusion_max_fused_op_ppm",
            ):
                with self.subTest(name=name):
                    self.assertEqual(FORMAT_NATIVE_DEFAULT_OPTION(options, name), "cpp-default")

    def test_final_sibling_fusion_explicit_values(self) -> None:
        values = {
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY": "probe",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN": "7",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS": "19",
            "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM": "2300",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(
                READ_FINAL_SIBLING_FUSION_OPTIONS(),
                {
                    "final_sibling_fusion_policy": "probe",
                    "final_sibling_fusion_min_gain": 7,
                    "final_sibling_fusion_max_pairs": 19,
                    "final_sibling_fusion_max_fused_op_ppm": 2300,
                },
            )

    def test_final_sibling_fusion_values_are_independent(self) -> None:
        cases = (
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_POLICY",
                "probe",
                "final_sibling_fusion_policy",
                "probe",
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MIN_GAIN",
                "7",
                "final_sibling_fusion_min_gain",
                7,
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_PAIRS",
                "19",
                "final_sibling_fusion_max_pairs",
                19,
            ),
            (
                "WOLVRIX_XS_GRHSIM_FINAL_SIBLING_FUSION_MAX_FUSED_OP_PPM",
                "2300",
                "final_sibling_fusion_max_fused_op_ppm",
                2300,
            ),
        )
        for env_name, env_value, option_name, option_value in cases:
            with self.subTest(env_name=env_name):
                with patch.dict(os.environ, {env_name: env_value}, clear=True):
                    options = READ_FINAL_SIBLING_FUSION_OPTIONS()
                    self.assertEqual(options, {option_name: option_value})
                    self.assertEqual(
                        FORMAT_NATIVE_DEFAULT_OPTION(options, option_name),
                        str(option_value),
                    )

    def test_active_mask_gap_pack_default_is_sparse(self) -> None:
        high = "WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        low = "WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        base = {key: value for key, value in os.environ.items() if key not in {high, low}}

        with patch.dict(os.environ, base, clear=True):
            options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
            self.assertEqual(options, {})
            self.assertEqual(DESCRIBE_ACTIVE_MASK_GAP_PACK_POLICY(options), ("cpp-default", "cpp-default"))

        with patch.dict(os.environ, {**base, low: "targeted-direct"}, clear=True):
            before = dict(os.environ)
            options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
            self.assertEqual(options, {})
            self.assertEqual(
                DESCRIBE_ACTIVE_MASK_GAP_PACK_POLICY(options),
                ("targeted-direct", "cpp-low-env"),
            )
            self.assertEqual(os.environ, before)

        with patch.dict(os.environ, {**base, high: "off", low: "targeted-direct"}, clear=True):
            before = dict(os.environ)
            options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
            self.assertEqual(options, {"active_mask_gap_pack_policy": "off"})
            self.assertEqual(DESCRIBE_ACTIVE_MASK_GAP_PACK_POLICY(options), ("off", "xs-override"))
            self.assertEqual(os.environ, before)

    def test_active_mask_gap_pack_explicit_value_is_forwarded_verbatim(self) -> None:
        env_name = "WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        for value in (
            "off",
            "probe",
            "targeted-direct",
            "targeted-table-contiguous",
            "targeted-table-gap",
        ):
            with self.subTest(value=value):
                with patch.dict(os.environ, {env_name: value}, clear=True):
                    options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
                    self.assertEqual(options, {"active_mask_gap_pack_policy": value})
                    _compile_emit_grhsim_cpp_kwargs(options)

    def test_active_mask_gap_pack_invalid_value_is_not_normalized(self) -> None:
        env_name = "WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        for value in ("targeted", "table", "targeted-table", " probe "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {env_name: value}, clear=True):
                    options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
                    self.assertEqual(options, {"active_mask_gap_pack_policy": value})
                    with self.assertRaisesRegex(ValueError, "active_mask_gap_pack_policy"):
                        _compile_emit_grhsim_cpp_kwargs(options)

    def test_active_mask_gap_pack_low_env_is_observed_without_xs_validation(self) -> None:
        high = "WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        low = "WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY"
        base = {key: value for key, value in os.environ.items() if key not in {high, low}}
        with patch.dict(os.environ, {**base, low: "table"}, clear=True):
            options = READ_ACTIVE_MASK_GAP_PACK_OPTIONS()
            self.assertEqual(options, {})
            self.assertEqual(DESCRIBE_ACTIVE_MASK_GAP_PACK_POLICY(options), ("table", "cpp-low-env"))


if __name__ == "__main__":
    unittest.main()
