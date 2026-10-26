"""Native counter graph/source binding, closure and generated-program checks."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from grhsim_execution_counts import MAX_COUNT, NativeExecutionCounts, SCHEMA, binding, read_counts
from grhsim_grh_reader import GraphReader
from grhsim_declared_pack_census import native_family_report
from grhsim_paired_cone_diff import native_paired_report
import test_grhsim_grh_reader as reader_fixtures
from test_grhsim_grh_reader import Fixture, gsim_fixture


ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get("WOLVRIX_TEST_BUILD_DIR", ROOT / "wolvrix/build"))


class ExecutionCountsTests(unittest.TestCase):
    def setup_files(self, fixture=None):
        base = ROOT / "ptmp/remove-grhsim-ir"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="counter-test-", dir=base)
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        fixture = fixture or Fixture()
        for op in fixture.graph["ops"]:
            if op["kind"] != "kRegister":
                op["attrs"]["grhsim.partition"] = {"vs": ["general", "nonsink", "0", "0"]}
        sites = [{"operation": op["sym"], "category": "writer-sample" if op["kind"].startswith("grhsim.write") else "operation",
                  "function": "sn_0"} for op in fixture.graph["ops"] if op["kind"] != "kRegister"]
        snapshot = json.dumps(fixture.model).encode()
        program = {"model.hpp": b"// native test header\n", "tu.cpp": (
            "\n".join(f"++opExecCounts_[{i}];" for i in range(len(sites))) +
            f'\nstd::fputs("{SCHEMA}\\t__GRHSIM_EXECUTION_BINDING__\\n", stream);\n').encode()}
        tag = binding(snapshot, sites, program)
        metadata = {"schema": SCHEMA, "graph_file": "execution-counter-graph.json",
                    "binding_fnv1a64": tag, "binding_files": sorted(program), "sites": sites, "elided_operations": []}
        (directory / "execution-counter-graph.json").write_bytes(snapshot)
        (directory / "manifest.json").write_text(json.dumps({"execution_counters": metadata, "sources": ["tu.cpp"]}))
        for name, raw in program.items():
            (directory / name).write_bytes(raw.replace(b"__GRHSIM_EXECUTION_BINDING__", tag.encode()))
        for name in ("first.tsv", "second.tsv"):
            counts = [4 if site["category"] == "writer-sample" else 8 for site in sites]
            rows = "".join(f"{index}\t{count}\n" for index, count in enumerate(counts))
            (directory / name).write_text(f"{SCHEMA}\t{tag}\nevals\t3\n{rows}total\t{sum(counts)}\nend\t{len(sites)}\n")
        return fixture.model, directory

    @staticmethod
    def load(model, directory):
        return NativeExecutionCounts(model, directory, directory / "first.tsv", directory / "second.tsv")

    def test_valid_counts_and_compute_caliber(self):
        model, directory = self.setup_files()
        counts = self.load(model, directory)
        summary = counts.summary()
        self.assertTrue(summary["executable_coverage"])
        self.assertEqual(summary["category_visits"]["operation"], 24)
        self.assertEqual(summary["category_visits"]["writer-sample"], 4)
        self.assertEqual(summary["compute_operation_visits"], 8)
        self.assertEqual(counts.price({"one", "read", "xor"}), 8)
        with self.assertRaisesRegex(ValueError, "foreign"):
            counts.price({"foreign"})

    def test_full_graph_binding_rejects_changed_shapes_and_operands(self):
        original, directory = self.setup_files()
        for change in (lambda g: g["ops"][-1]["in"].reverse(),
                       lambda g: g["vals"][-1].update(shape=[8]),
                       lambda g: g["ops"][-1]["attrs"].update(priority={"v": 3})):
            model = copy.deepcopy(original)
            change(model["graphs"][0])
            with self.assertRaisesRegex(ValueError, "snapshot differs"):
                self.load(model, directory)

    def test_missing_and_duplicate_source_sites_fail(self):
        model, directory = self.setup_files()
        source = (directory / "tu.cpp").read_text()
        for text in (source.replace("++opExecCounts_[0];", ""), source + "\n++opExecCounts_[0];"):
            (directory / "tu.cpp").write_text(text)
            with self.assertRaisesRegex(ValueError, "site closure"):
                self.load(model, directory)

    def test_same_graph_with_changed_guard_or_header_is_rejected(self):
        model, directory = self.setup_files()
        for name in ("tu.cpp", "model.hpp"):
            path = directory / name
            original = path.read_bytes()
            path.write_bytes(original + b"// changed generated program\n")
            with self.assertRaisesRegex(ValueError, "source binding"):
                self.load(model, directory)
            path.write_bytes(original)

    def test_coverage_and_metadata_binding_fail_closed(self):
        model, directory = self.setup_files()
        manifest = json.loads((directory / "manifest.json").read_text())
        for change, message in ((lambda m: m["sites"].pop(), "coverage"),
                                (lambda m: m["sites"][0].update(function="pOutput"), "binding"),
                                (lambda m: m["sites"][0].update(category="writer-commit"), "category"),
                                (lambda m: m.update(elided_operations=["xor"]), "elisions")):
            altered = copy.deepcopy(manifest)
            change(altered["execution_counters"])
            (directory / "manifest.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, message):
                self.load(model, directory)

    def test_independent_run_difference_and_same_path_are_rejected(self):
        model, directory = self.setup_files()
        second = directory / "second.tsv"
        second.write_text(second.read_text().replace("2\t8", "2\t9").replace("total\t28", "total\t29"))
        with self.assertRaisesRegex(ValueError, "independent native"):
            self.load(model, directory)
        first = directory / "first.tsv"
        with self.assertRaisesRegex(ValueError, "independent execution"):
            NativeExecutionCounts(model, directory, first, first)

    def test_log_truncation_duplicates_overflow_and_zero_eval_rejected(self):
        _model, directory = self.setup_files()
        path = directory / "first.tsv"
        original = path.read_text()
        tag = original.splitlines()[0].split("\t")[1]
        for text in (original.replace("end\t4\n", ""), original.replace("evals\t3", "evals\t0"),
                     original.replace("1\t8", "0\t8"), original.replace("0\t8", "0\t-1"),
                     original.replace("0\t8", f"0\t{MAX_COUNT + 1}"),
                     original.replace("total\t28", "total\t27"),
                     original.replace(tag, "0")):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_counts(path, tag, 4)

    def test_utf8_binding_lengths_are_bytes(self):
        sites = [{"operation": "寄存器", "category": "operation", "function": "sn_0"}]
        self.assertNotEqual(binding(b"{}", sites), binding(b"{} ", sites))
        raw = b"{}9:" + "寄存器".encode("utf-8") + b"9:operation4:sn_0"
        self.assertEqual(binding(b"{}", sites), binding(raw, []))

    def test_family_and_paired_pricing_use_bound_native_counts(self):
        model, directory = self.setup_files(reader_fixtures.ReaderTests().family_fixture())
        counts = self.load(model, directory)
        family = native_family_report(model, final_model=model, execution=counts)["dynamic"]
        self.assertTrue(family["available"])
        self.assertEqual(family["union_compute_visits"], 16)
        self.assertEqual(family["sum_family_compute_visits"], 16)
        self.assertEqual(family["compute_operation_visits"], 24)
        paired = native_paired_report(GraphReader(model), gsim_fixture(), execution=counts)
        self.assertEqual(paired["dynamic"]["union_compute_visits"], 8)
        self.assertEqual(paired["linked_pairs"][0]["grh_compute_visits"], 8)
        with self.assertRaisesRegex(ValueError, "exact counter graph"):
            native_paired_report(GraphReader(Fixture().model), gsim_fixture(), execution=counts)

    def test_removed_family_members_are_unpriced_not_zero(self):
        before = reader_fixtures.ReaderTests().family_fixture().model
        model, directory = self.setup_files()
        counts = self.load(model, directory)
        dynamic = native_family_report(before, final_model=model, execution=counts)["dynamic"]
        row = dynamic["families"][0]
        self.assertFalse(row["available"])
        self.assertNotIn("compute_visits", row)
        self.assertEqual(row["unpriced_reasons"], {"missing_final_state_or_unique_writer": 2})

    def test_generated_tiny_and_large_budget_counts(self):
        reports = []
        for budget in (16, 1024):
            directory = BUILD / f"artifacts/grhsim-cpu-st-cpp/execution-counts-b{budget}"
            self.assertTrue((directory / "execution1.tsv").is_file(), "run make test_grhsim_cpu_st_cpp first")
            model = json.loads((directory / "model/execution-counter-graph.json").read_bytes())
            counts = NativeExecutionCounts(model, directory / "model", directory / "execution1.tsv", directory / "execution2.tsv")
            report = counts.summary()
            self.assertEqual(report["evals"], 12)
            self.assertTrue(all(report["category_visits"][category] > 0 for category in
                                ("operation", "effect", "writer-sample", "writer-commit", "history-write")))
            owners = report["operation_visits_by_owner"]
            self.assertTrue(all(any(key.startswith(prefix) for key in owners) for prefix in
                                ("event", "output", "general/nonsink")))
            effects = counts.visits["effect"]
            dpi = [name for name, op in counts.reader.ops.items() if op["kind"] == "grhsim.dpi-call"]
            random = [name for name, op in counts.reader.ops.items() if op["kind"] == "grhsim.system-function"]
            self.assertEqual([effects[name] for name in dpi], [4])
            self.assertEqual([effects[name] for name in random], [12])
            # Function placement can change with the emission budget. Each
            # model's source binding is checked above; compare the graph and
            # every operation/category count across the two layouts.
            reports.append((counts.reader.graph, counts.evals, counts.visits, counts.elided))
        self.assertEqual(*reports)


if __name__ == "__main__":
    unittest.main()
