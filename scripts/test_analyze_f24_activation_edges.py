"""Checks for the emitted-code census used by the F24 quality gate."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze_f24_activation_edges import census, compare_native, main


class ActivationCensusTests(unittest.TestCase):
    def test_scalar_bound_excludes_self_unconditional_and_unguarded(self):
        # The guards and activation comments mirror cppEmitter.cpp. The same
        # source appears twice to ensure emission count never inflates edges.
        code = """void SSimTop::subStep0() {
  if(unlikely(oldFlag & 0x1)) { // id=7
    bool cond_x = x ^ x$old$10;
    oldFlag |= -(uint8_t)cond_x & 0x81; // 7 8
    activeFlags[2] |= cond_x; // 16
    bool cond_x = x ^ x$old$10;
    activeFlags[2] |= cond_x; // 16
    if (y != y$old$11) {
      activeFlags[3] |= 0x03; // 24 25
    }
    activeFlags[4] |= 0x01; // 32
    if (reset$old$12 || (reset != reset$old$12)) {
      activateAll();
    }
  }
  bool cond_z = z != z$old$20;
  activeFlags[4] |= cond_z; // 33
}
"""
        root = Path("ptmp/firrtl-ingest/F24/activation-audit/test-artifacts")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            model = Path(directory)
            (model / "SimTop0.cpp").write_text(code)
            result = census(model, "SimTop")
        self.assertEqual(result["confirmed_scalar_compare_edges"], 5)
        self.assertEqual(result["confirmed_scalar_compare_boundary_edges"], 4)
        self.assertEqual(result["confirmed_scalar_compare_boundary_edges_by_emission"],
                         {"compare_block": 2, "cond_variable": 2})
        self.assertEqual(result["diagnostics"]["duplicate_node_target_emission"], 1)
        self.assertEqual(result["diagnostics"]["cond_definitions_without_super_guard"], 1)


class NativeComparisonTests(unittest.TestCase):
    def stats(self, values=70, state_change=5, state_write=10, pulses=6):
        return {
            "schema": "grhsim-activation-stats.v1",
            "graph": "SimTop",
            "value_change_activation_edges": values,
            "state_change_activation_edges": state_change,
            "state_write_activation_edges": state_write,
            "event_pulse_activation_edges": pulses,
            "total_activation_edges": values + state_change + state_write + pulses,
        }

    def test_broad_state_bound_and_stricter_pulse_bound_are_separate(self):
        result = compare_native(self.stats(), confirmed=60, compute_lower_bound=40)
        self.assertFalse(result["compute_subset"]["sufficient_count_inequality_holds"])
        self.assertFalse(result["sufficient_count_inequality_holds"])
        broad = result["broad_conditional"]
        self.assertEqual(broad["native_edges_upper_bound"], 85)
        self.assertEqual(broad["native_edges_sufficient_limit"], 90)
        self.assertTrue(broad["sufficient_count_inequality_holds"])
        stricter = result["publications_including_event_pulses"]
        self.assertEqual(stricter["native_edges_upper_bound"], 91)
        self.assertFalse(stricter["sufficient_count_inequality_holds"])

    def test_state_write_label_cannot_hide_conditional_small_state_edges(self):
        result = compare_native(self.stats(values=80, state_change=0, state_write=11, pulses=0),
                                confirmed=60, compute_lower_bound=60)
        self.assertTrue(result["compute_subset"]["sufficient_count_inequality_holds"])
        self.assertEqual(result["broad_conditional"]["native_edges_upper_bound"], 91)
        self.assertFalse(result["broad_conditional"]["sufficient_count_inequality_holds"])

    def test_integer_limit_does_not_round_up(self):
        for values, expected in ((4, True), (5, False)):
            with self.subTest(values=values):
                result = compare_native(self.stats(values=values, state_change=0, state_write=0, pulses=0),
                                        confirmed=3, compute_lower_bound=3)
                self.assertEqual(result["broad_conditional"]["native_edges_sufficient_limit"], 4)
                self.assertEqual(result["broad_conditional"]["sufficient_count_inequality_holds"], expected)

    def test_rejects_incomplete_or_inconsistent_native_components(self):
        for field, value in (("state_write_activation_edges", None),
                             ("event_pulse_activation_edges", -1),
                             ("value_change_activation_edges", True),
                             ("total_activation_edges", 1)):
            with self.subTest(field=field, value=value):
                stats = self.stats()
                if value is None:
                    del stats[field]
                else:
                    stats[field] = value
                with self.assertRaises(ValueError):
                    compare_native(stats, confirmed=60, compute_lower_bound=40)

    def test_evidence_path_does_not_certify_input_or_scope(self):
        root = Path("ptmp/firrtl-ingest/F24/activation-audit/test-artifacts")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            model = Path(directory)
            (model / "SimTop0.cpp").write_text("""void SSimTop::subStep0() {
  if(unlikely(oldFlag & 0x1)) { // id=7
    bool cond_x = x ^ x$old$10;
    activeFlags[1] |= cond_x; // 8
  }
}
""")
            (model / "SimTop_supernode_stats.json").write_text(json.dumps({
                "boundary_activation_edges": 1,
                "boundary_activation_edges_by_node_type": {"NODE_OTHERS": 1},
            }))
            native = model / "native.json"
            native.write_text(json.dumps(self.stats(values=1, state_change=0, state_write=0, pulses=0)))
            evidence = model / "evidence.json"
            evidence.write_text(json.dumps({"same_input": True}))
            output = model / "report.json"
            args = ["analyze_f24_activation_edges.py", "--gsim-model", str(model),
                    "--native-activation-stats", str(native), "--same-input-evidence", str(evidence),
                    "--output", str(output)]
            with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                main()
            report = json.loads(output.read_text())
        self.assertEqual(report["native_broad_conditional_edges_sufficient_limit"], 1)
        self.assertTrue(report["native"]["broad_conditional"]["sufficient_count_inequality_holds"])
        self.assertTrue(report["native"]["external_identity_evidence_supplied"])
        self.assertFalse(report["native"]["input_identity_verified_by_this_script"])
        self.assertFalse(report["native"]["quality_gate_certified_by_this_script"])
        self.assertTrue(report["runtime_scope_assumptions"])


if __name__ == "__main__":
    unittest.main()
