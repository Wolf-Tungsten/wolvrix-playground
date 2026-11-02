"""Check the independent PLRU oracle and first-divergence reporting."""

import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest

from xs_firrtl_replacer import (INPUT_WIDTHS, ROOT, VARIANTS, compare, minimal,
                                touch, update, victim, word_layout)


class ReplacerOracleTests(unittest.TestCase):
    def test_tree_paths(self):
        # Known paths in the postorder tree; each access marks its siblings old.
        self.assertEqual([touch(0, way) for way in range(8)], [69, 68, 66, 64, 40, 32, 16, 0])
        paths = [0b1000101, 0b1000101, 0b1000110, 0b1000110,
                 0b1101000, 0b1101000, 0b1110000, 0b1110000]
        for state in range(128):
            self.assertIn(victim(state), range(8))
            for way in range(8):
                after = touch(state, way)
                self.assertNotEqual(victim(after), way)
                self.assertEqual((after ^ state) & ~paths[way], 0)
        self.assertEqual([victim(1 << bit) for bit in range(7)], [1, 0, 2, 0, 0, 0, 4])

    def test_write_priority_and_independent_sets(self):
        values = {"reset": 0, "io_readSetIdx": 2, "io_writeSetIdx": 2,
                  "io_readValid": 1, "io_writeValid": 1, "io_writeWayIdx": 0,
                  **{f"io_readWayMask_{way}": 1 for way in range(8)}}
        states = [0] * 32
        update(states, values)
        self.assertEqual(states[2], touch(0, 0))
        values["io_writeSetIdx"] = 3
        update(states, values)
        self.assertEqual(states[2], 0)
        self.assertEqual(states[3], touch(0, 0))
        values.update(reset=1)
        update(states, values)
        self.assertEqual(states, [0] * 32)

    def test_comparator_detects_corruption(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="firrtl-replacer-test-", dir=ROOT / "ptmp") as temp:
            work = Path(temp)
            args = SimpleNamespace(output=work)
            expected = struct.pack("<4Q", 0, 4, 6, 7)
            (work / "expected.bin").write_bytes(expected)
            for variant in VARIANTS:
                (work / variant).mkdir()
                (work / variant / "outputs.bin").write_bytes(expected)
            compare(args)
            (work / "verilator/outputs.bin").write_bytes(struct.pack("<4Q", 0, 4, 7, 7))
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                compare(args)
            report = json.loads((work / "comparison.json").read_text())
            self.assertEqual(report["first"], {"variant": "verilator", "step": 2,
                "cycle": 1, "clock": 0, "expected": 6, "actual": 7})
            (work / "verilator/outputs.bin").write_bytes(expected[:-8])
            with self.assertRaisesRegex(ValueError, "output size"):
                compare(args)

    def test_minimal_fixture(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="firrtl-replacer-minimal-test-", dir=ROOT / "ptmp") as temp:
            work = Path(temp)
            layout = {"inputs": word_layout(INPUT_WIDTHS),
                      "outputs": word_layout([("io_victimWayIdx", 3)])}
            (work / "layout.json").write_text(json.dumps(layout))
            minimal(SimpleNamespace(output=work))
            expected = (work / "minimal/expected.bin").read_bytes()
            self.assertEqual(struct.unpack("<12Q", expected), (*([0] * 9), 7, 7, 7))
            operations = json.loads((work / "minimal/operations.json").read_text())
            self.assertEqual([op["io_writeWayIdx"] for op in operations[2:4]], [6, 4])


if __name__ == "__main__":
    unittest.main()
