import tempfile
import unittest
from pathlib import Path

from repcut_grhsim_backend_shape import (
    _plan_source_shape_envelope,
    _project_source_shape,
    _read_plan_shape,
    inspect_package,
)


def _write_package(root: Path) -> None:
    sources = [
        "grhsim_Gpart_3_model_eval.cpp",
        "grhsim_Gpart_3_model_sched_0.cpp",
        "grhsim_Gpart_3_model_state_init_0.cpp",
        "Gpart_3.cpp",
        "wolvi_repcut_grhsim_sim_common.cpp",
    ]
    (root / "Makefile").write_text("SRCS := " + " ".join(sources) + "\nOBJS := $(SRCS:.cpp=.o)\n")
    for index, source in enumerate(sources, 1):
        (root / source).write_bytes(b"x" * index)


def _write_plan(root: Path, *, lines: int, state: int, inputs: int) -> None:
    root.mkdir()
    (root / "summary.csv").write_text(
        "part,precision,feature,value\n"
        f"inst_part_3,whole,state_logic_bytes,{state}\n"
        f"inst_part_3,whole,input_targets,{inputs}\n"
        "inst_part_3,whole,boundary_targets,10\n"
        "inst_part_3,whole,event_edge_bytes,2\n"
        "inst_part_3,whole,producer_dirty_target_words,3\n"
    )
    (root / "groups.csv").write_text(
        "part,group,active_id,phase,operations,estimated_lines,work,group_mask,value_rise_work,value_fall_work\n"
        f"inst_part_3,0,0,compute,10,{lines},0,0,0,0\n"
        "inst_part_3,1,1,commit,2,20,0,0,0,0\n"
    )
    (root / "batch_groups.csv").write_text(
        "part,batch,phase,word,group,active_id,helper_chunks\n"
        "inst_part_3,0,compute,0,0,0,0\n"
        "inst_part_3,1,commit,0,1,1,0\n"
    )


class BackendShapeTest(unittest.TestCase):
    def test_generated_sources_are_grouped_by_category_and_part(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)
            _write_package(package)
            report = inspect_package("test", package)
            self.assertEqual(report["source_count"], 5)
            part = report["parts"]["3"]["source"]
            self.assertEqual(part["eval_files"], 1)
            self.assertEqual(part["sched_files"], 1)
            self.assertEqual(part["state_init_files"], 1)
            self.assertEqual(report["common_source"]["files"], 1)
            self.assertEqual(report["missing_source_files"], 0)

    def test_object_root_falls_back_to_harness_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "package"
            package.mkdir()
            _write_package(package)
            objects = package.parent / "objects"
            objects.mkdir()
            for source in package.glob("*.cpp"):
                (objects / (source.stem + ".o")).write_bytes(b"o")
            report = inspect_package("test", package)
            self.assertEqual(report["objects_root"], str(objects.resolve()))
            self.assertEqual(report["missing_object_files"], 0)
            self.assertEqual(report["parts"]["3"]["objects"]["files"], 4)

    def test_plan_projection_uses_generic_operation_ratio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package"
            package.mkdir()
            _write_package(package)
            baseline = root / "baseline.parts.csv"
            candidate = root / "candidate.parts.csv"
            header = (
                "part,grhsim_v1_closure_work,grhsim_v1_recurring_work,"
                "raw_operation_count,state_write_count,piece_copies,send_calls,"
                "send_bytes,receive_calls,receive_bytes\n"
            )
            row = "3,10,10,{ops},1,1,1,1,1,1\n"
            baseline.write_text(header + row.format(ops=10))
            candidate.write_text(header + row.format(ops=20))
            report = inspect_package("test", package)
            projection = _project_source_shape(report, baseline, candidate)
            self.assertEqual(projection["parts"]["3"]["raw_operation_count"]["delta"], 10)
            self.assertAlmostEqual(projection["predicted_source_delta_percent"], 100.0 / 3.0)

    def test_plan_shape_exposes_commit_bucket_risk_before_emission(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder)
            (plan / "summary.csv").write_text(
                "part,precision,feature,value\ninst_part_3,whole,graph_ops,9000\n"
            )
            (plan / "groups.csv").write_text(
                "part,group,active_id,phase,operations,estimated_lines,work,group_mask,value_rise_work,value_fall_work\n"
                "inst_part_3,0,0,commit,5000,90000,0,0,0,0\n"
                "inst_part_3,1,1,compute,20,100,0,0,0,0\n"
            )
            (plan / "batch_groups.csv").write_text(
                "part,batch,phase,word,group,active_id,helper_chunks\n"
                "inst_part_3,0,commit,0,0,0,0\n"
                "inst_part_3,1,compute,0,1,1,0\n"
            )
            report = _read_plan_shape(plan)
            part = report["parts"]["3"]
            self.assertEqual(part["commit_groups_over_4096_ops"], 1)
            self.assertEqual(part["commit_groups_over_8192_ops"], 0)
            self.assertEqual(part["scheduler_estimated_lines"], 90100)
            self.assertEqual(part["commit_batch_count"], 1)

    def test_plan_shape_projects_categories_without_timing_coefficients(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package"
            package.mkdir()
            _write_package(package)
            baseline_plan = root / "baseline-plan"
            candidate_plan = root / "candidate-plan"
            _write_plan(baseline_plan, lines=100, state=10, inputs=10)
            _write_plan(candidate_plan, lines=150, state=20, inputs=5)
            report = inspect_package("test", package)
            envelope = _plan_source_shape_envelope(report, baseline_plan, candidate_plan)
            part = envelope["parts"]["3"]
            self.assertAlmostEqual(part["ratios"]["sched_bytes"], 170 / 120)
            self.assertAlmostEqual(part["ratios"]["eval_bytes"], 150 / 100)
            self.assertAlmostEqual(part["ratios"]["state_bytes"], 2.0)
            self.assertAlmostEqual(part["ratios"]["part_bytes"], 20 / 25)
            self.assertEqual(envelope["unknown_dimensions"], [])


if __name__ == "__main__":
    unittest.main()
