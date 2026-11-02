import copy
from pathlib import Path
import struct
import tempfile
import unittest

from xs_firrtl_rob_oob_audit import INFO_FIELDS, check_defined_records


ROOT = Path(__file__).resolve().parents[1]


class RobDefinednessTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="firrtl-defined-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.layout = {"inputs": [{"name": "clock", "width": 1, "words": 1, "offset": 0},
                                  {"name": "reset", "width": 1, "words": 1, "offset": 1}], "outputs": []}
        def output(name, width, **extra):
            self.layout["outputs"].append({"name": name, "width": width, "words": 1,
                                           "offset": len(self.layout["outputs"]), **extra})
        for lane in range(520):
            output(f"io_diffCommits_commitValid_{lane}", 1)
            for field, width in INFO_FIELDS.items():
                output(f"io_diffCommits_info_{lane}_{field}", width)
        output("io_commits_commitValid_0", 1)
        output("ordinary", 1)
        output("probe", 1, native_probe=True)
        output("recovered", 1, sv_internal=True)
        self.offsets = {leaf["name"]: leaf["offset"] for leaf in self.layout["outputs"]}
        self.words = len(self.offsets)
        record = struct.Struct(f"<{self.words}Q")
        self.rows = {name: [] for name in ("sv-off", "firrtl-off", "firrtl-prefer")}
        stimulus = bytearray(struct.pack("<8sQII", b"FirXio01", 20, 2, self.words))
        masks = bytearray()
        for step in range(20):
            cycle, high = divmod(step, 2)
            stimulus.extend(struct.pack("<2Q", high, int(cycle < 8)))
            masks.extend(record.pack(*(0 if cycle < 8 else (1 << leaf["width"]) - 1
                                       for leaf in self.layout["outputs"])))
            pointer = 185 if step >= 17 else 0
            for variant in self.rows:
                row = [0] * self.words
                if cycle == 8:
                    for lane in range(185):
                        row[self.offsets[f"io_diffCommits_commitValid_{lane}"]] = 1
                if step >= 16:
                    row[self.offsets["io_commits_commitValid_0"]] = 1
                    row[self.offsets["ordinary"]] = 1
                    row[self.offsets["recovered"]] = 1
                    if variant != "sv-off":
                        row[self.offsets["probe"]] = 1
                if pointer:
                    row[self.offsets["io_diffCommits_info_167_ldest"]] = 5
                    if variant == "sv-off":
                        row[self.offsets["io_diffCommits_info_519_ldest"]] = 5
                self.rows[variant].append(row)
        (self.work / "inputs.bin").write_bytes(stimulus)
        (self.work / "compare-mask.bin").write_bytes(masks)
        self.paths = {variant: self.work / f"{variant}.bin" for variant in self.rows}
        self.write_rows()

    def write_rows(self):
        record = struct.Struct(f"<{self.words}Q")
        for variant, rows in self.rows.items():
            self.paths[variant].write_bytes(b"".join(record.pack(*row) for row in rows))

    def compare(self):
        return check_defined_records(self.layout, self.work / "inputs.bin", self.work / "compare-mask.bin",
                                     self.paths, 10)

    def test_defined_outputs_and_both_policies(self):
        result = self.compare()
        self.assertTrue(result["passed"])
        self.assertFalse(result["bitwise_all_output_equality"])
        self.assertEqual(result["indeterminate_info_bits"], 60)
        self.assertEqual(result["indeterminate_lane_records"], 3)
        self.assertEqual(result["first_indeterminate_read"]["index"], 352)
        self.assertEqual(result["activity"], {variant: 2 for variant in self.rows})
        self.assertEqual(result["native_probe_bits"], 4)
        self.assertEqual(result["sv_internal_source_defined_bits"], 4)

    def test_corrupted_native_oob_rejected_in_each_route(self):
        original = copy.deepcopy(self.rows)
        for variant in ("firrtl-off", "firrtl-prefer"):
            with self.subTest(variant=variant):
                self.rows = copy.deepcopy(original)
                self.rows[variant][17][self.offsets["io_diffCommits_info_519_ldest"]] = 1
                self.write_rows()
                with self.assertRaisesRegex(ValueError, "native OOB policy"):
                    self.compare()

    def test_corrupted_sv_oob_padding_rejected(self):
        self.rows["sv-off"][17][self.offsets["io_diffCommits_info_519_ldest"]] = 6
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "SV OOB padding policy"):
            self.compare()

    def test_valid_oob_lane_rejected_in_each_route(self):
        original = copy.deepcopy(self.rows)
        for variant in self.rows:
            with self.subTest(variant=variant):
                self.rows = copy.deepcopy(original)
                self.rows[variant][17][self.offsets["io_diffCommits_commitValid_519"]] = 1
                self.write_rows()
                with self.assertRaisesRegex(ValueError, "OOB lane valid"):
                    self.compare()

    def test_in_range_difference_rejected(self):
        self.rows["sv-off"][17][self.offsets["io_diffCommits_info_0_ldest"]] = 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "in-range SV/native mismatch"):
            self.compare()

    def test_probe_difference_rejected(self):
        self.rows["firrtl-prefer"][17][self.offsets["probe"]] = 0
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "native full-observation mismatch"):
            self.compare()
