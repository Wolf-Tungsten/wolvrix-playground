"""Check the component oracle and the minimum useful activity gates."""

import json
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import unittest

from xs_firrtl_compare import (MEMORY, ROOT, audit_retained_inputs, bindings, compare, observe_register_data_checkpoint,
                               observation_source_evidence, port_values, rob_trace_activity,
                               stimulus, word_layout, words_in)


class ComponentCompareTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="firrtl-compare-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.args = SimpleNamespace(output=Path(self.temp.name), cycles=512)

    def test_memory_oracle_and_corruption(self):
        work = self.args.output / MEMORY
        work.mkdir()
        layout = {"inputs": word_layout([
            ("RW0_addr", 7), ("RW0_clk", 1), ("RW0_en", 1),
            ("RW0_wmode", 1), ("RW0_wmask", 2), ("RW0_wdata", 138)]),
            "outputs": word_layout([("RW0_rdata", 138)])}
        (work / "layout.json").write_text(json.dumps(layout))
        stimulus(self.args, MEMORY, layout)
        identity = json.loads((work / "stimulus-identity.json").read_text())
        self.assertEqual(identity["coverage"]["reset_cycles"], 0)
        for field in ("read_cycles", "disabled_cycles", "write_mask_0", "write_mask_1",
                      "write_mask_2", "write_mask_3"):
            self.assertGreater(identity["coverage"][field], 0, field)
        for variant in ("sv-off", "firrtl-off", "firrtl-prefer"):
            (work / variant).mkdir()
            shutil.copyfile(work / "expected.bin", work / variant / "outputs.bin")
        compare(self.args, MEMORY)
        mask = (work / "compare-mask.bin").read_bytes()
        index = next(i for i, byte in enumerate(mask) if byte)
        output = work / "firrtl-off/outputs.bin"
        data = bytearray(output.read_bytes())
        data[index] ^= 1 << ((mask[index] & -mask[index]).bit_length() - 1)
        output.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            compare(self.args, MEMORY)

    def test_rob_rejects_inactive_trace(self):
        work = self.args.output / "Rob"
        work.mkdir()
        self.args.cycles = 8
        layout = {"inputs": word_layout([("clock", 1), ("reset", 1),
            ("io_enq_req_0_valid", 1), ("io_writeback_0_valid", 1)]),
            "outputs": word_layout([("io_commits_commitValid_0", 1)])}
        trace_layout = {"in_words": 2, "out_words": 1,
            "inputs": word_layout([("io_enq_req_0_valid", 1), ("io_writeback_0_valid", 1)])}
        self.args.rob_trace = work / "trace.bin"
        self.args.rob_layout = work / "trace-layout.json"
        self.args.rob_layout.write_text(json.dumps(trace_layout))
        self.args.rob_trace.write_bytes(struct.pack("<8sQII", b"RobTrc01", 8, 2, 1) + bytes(8 * 4 * 8))
        with self.assertRaisesRegex(ValueError, "enqueue and writeback"):
            stimulus(self.args, "Rob", layout)

    def test_rob_rejects_no_commit(self):
        work = self.args.output / "Rob"
        work.mkdir()
        layout = {"inputs": [], "outputs": word_layout([("io_commits_commitValid_0", 1)])}
        (work / "layout.json").write_text(json.dumps(layout))
        (work / "stimulus-identity.json").write_text(json.dumps({"cycles": 1}))
        (work / "compare-mask.bin").write_bytes(struct.pack("<2Q", 1, 1))
        for variant in ("sv-off", "firrtl-off", "firrtl-prefer"):
            (work / variant).mkdir()
            (work / variant / "outputs.bin").write_bytes(bytes(2 * words_in(layout["outputs"]) * 8))
        with self.assertRaisesRegex(RuntimeError, "commit outputs"):
            compare(self.args, "Rob")

    def test_rob_trace_declared_static_zero(self):
        self.args.cycles = 16
        work = self.args.output / "Rob"
        work.mkdir()
        inputs = word_layout([("clock", 1), ("reset", 1), ("io_enq_req_0_valid", 1),
                              ("io_writeback_0_valid", 1), ("configuration", 6)])
        layout = {"inputs": inputs, "outputs": word_layout([("out", 1)])}
        trace_inputs = word_layout([("io_enq_req_0_valid", 1), ("io_writeback_0_valid", 1)])
        trace_inputs.append({"name": "configuration", "width": 6, "words": 1,
                             "offset": None, "kind": "static"})
        self.args.rob_trace = work / "trace.bin"
        self.args.rob_layout = work / "trace-layout.json"
        self.args.rob_layout.write_text(json.dumps({"in_words": 2, "out_words": 1, "inputs": trace_inputs}))
        self.args.rob_trace.write_bytes(struct.pack("<8sQII", b"RobTrc01", 16, 2, 1) +
            struct.pack("<4Q", 1, 1, 1, 0) * 16)
        self.args.rob_capture_mapping = work / "capture-mapping.json"
        self.args.rob_capture_summary = work / "capture-summary.json"
        witness = {"name": "configuration", "signal": "configuration", "handle": 7,
                   "bit": 0, "source_width": 6}
        self.args.rob_capture_mapping.write_text(json.dumps({"mapped": [witness]}))
        self.args.rob_capture_summary.write_text(json.dumps({"cycles": 16, "in_words": 2,
            "out_words": 1, "first_reset": True, "bytes": self.args.rob_trace.stat().st_size}))
        stimulus(self.args, "Rob", layout)
        identity = json.loads((work / "stimulus-identity.json").read_text())
        self.assertEqual(identity["trace_static_inputs"], [{"name": "configuration", "width": 6,
                                                           "value": 0, "capture": witness}])
        record = struct.Struct(f"<{words_in(inputs)}Q")
        data = (work / "inputs.bin").read_bytes()[24:]
        for offset in range(0, len(data), record.size):
            self.assertEqual(record.unpack_from(data, offset)[-1], 0)

    def test_trace_activity(self):
        self.args.cycles = 3
        self.args.rob_trace = self.args.output / "trace.bin"
        self.args.rob_layout = self.args.output / "trace-layout.json"
        self.args.rob_layout.write_text(json.dumps({"in_words": 2, "out_words": 1,
            "inputs": word_layout([("io_enq_req_0_valid", 1), ("io_writeback_0_valid", 1)]),
            "outputs": word_layout([("io_commits_commitValid_0", 1)])}))
        self.args.rob_trace.write_bytes(struct.pack("<8sQII", b"RobTrc01", 3, 2, 1) +
            struct.pack("<12Q", 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1))
        self.assertEqual(rob_trace_activity(self.args), {"cycles": 3,
            "valid_lanes": {"enqueue": 2, "writeback": 1, "commit": 1},
            "first_cycle": {"enqueue": 0, "writeback": 1, "commit": 2}})

    def checkpoint(self, duplicate_write=False):
        value = {"sym": "next", "w": 1, "in": False, "out": False, "inout": False}
        output = {"sym": "shared", "w": 2, "in": False, "out": True, "inout": False}
        write = {"sym": "write", "kind": "kRegisterWritePort", "in": ["enable", "next", "clock"],
                 "out": [], "attrs": {"regSymbol": {"t": "string", "v": "r"},
                                       "eventEdge": {"t": "string[]", "vs": ["posedge"]}}}
        path = self.args.output / "checkpoint.json"
        path.write_text('{"graphs": [{\n      "values": [\n' +
            '        ' + json.dumps(value) + ',\n        ' + json.dumps(output) + '\n      ],\n' +
            '      "ports": {\n        "in": [],\n        "out": [\n' +
            '          {"name": "first", "val": "shared"},\n' +
            '          {"name": "second", "val": "shared"}\n        ]\n      },\n' +
            '      "ops": [\n        ' + json.dumps(write) +
            (',\n        ' + json.dumps({**write, "sym": "write2"}) if duplicate_write else '') +
            '\n      ]\n    }]}\n')
        return path

    def test_port_geometry_keeps_output_aliases(self):
        values = port_values(self.checkpoint())
        self.assertEqual(set(values), {"first", "second"})
        self.assertEqual(values["first"]["value_symbol"], "shared")
        self.assertEqual(values["second"]["w"], 2)

    def test_port_geometry_uses_each_port_direction(self):
        path = self.checkpoint()
        path.write_text(path.read_text().replace('"in": [],\n        "out": [',
            '"in": [\n          {"name": "input_alias", "val": "shared"}\n        ],\n        "out": ['))
        values = port_values(path)
        self.assertTrue(values["input_alias"]["in"])
        self.assertFalse(values["input_alias"]["out"])
        self.assertFalse(values["first"]["in"])
        self.assertTrue(values["first"]["out"])

    def test_observation_preserves_state_and_operations(self):
        source = self.checkpoint()
        original = source.read_bytes()
        destination = self.args.output / "observed.json"
        report = observe_register_data_checkpoint(source, destination,
            [{"reg_symbol": "r", "sv_port": "observed", "firrtl_port": "io__DOT__observed", "width": 1}])
        before, after = json.loads(original)["graphs"][0], json.loads(destination.read_text())["graphs"][0]
        self.assertEqual(before["ops"], after["ops"])
        self.assertEqual(after["ports"]["out"][1:], before["ports"]["out"])
        self.assertEqual(after["ports"]["out"][0], {"name": "observed", "val": "next"})
        self.assertEqual(after["values"], [{**before["values"][0], "out": True}, before["values"][1]])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(report["observations"][0]["operand_index"], 1)
        self.assertFalse(report["observations"][0]["source_geometry"]["out"])

    def test_observation_rejects_ambiguous_register_writes(self):
        with self.assertRaisesRegex(ValueError, "requires one register write"):
            observe_register_data_checkpoint(self.checkpoint(duplicate_write=True),
                self.args.output / "observed.json", [{"reg_symbol": "r", "sv_port": "observed", "width": 1}])

    def test_observation_source_expression_must_match(self):
        firrtl, sv = self.args.output / "T.fir", self.args.output / "T.sv"
        firrtl.write_text("circuit T :\n  module T :\n    connect io.foo, foo\n")
        sv.write_text("always @(posedge clock) begin\n  r <=\n    a & b;\nend\n")
        specs = [{"reg_symbol": "r", "firrtl_statements": ["connect io.foo, foo"],
                  "sv_statement": "r <= a & b;"}]
        result = observation_source_evidence(firrtl, sv, "T", specs)
        self.assertEqual(result["sv"]["r"][0]["line"], 2)
        sv.write_text("r <= a | b;\n")
        with self.assertRaisesRegex(ValueError, "expression changed"):
            observation_source_evidence(firrtl, sv, "T", specs)

    def test_attribute_rename_binds_real_native_output(self):
        member = "io__DOT__out__DOT__attribute__DOT__rasAction"
        header = self.args.output / "model.hpp"
        header.write_text(f"class GrhSIM_T {{\npublic:\n  std::uint8_t {member}{{}};\nprivate:\n}};")
        result, extra = bindings({member: {"w": 2, "in": False}}, header, "T",
            {"io_out_attribute_0_rasAction": ("output", SimpleNamespace(width=2))}, "firrtl")
        self.assertEqual(result["io_out_attribute_0_rasAction"], (member, 0, 2, "output"))
        self.assertEqual(extra, [])

    def test_internal_observation_is_compared_in_all_routes(self):
        work = self.args.output / "Observed"
        work.mkdir()
        layout = {"inputs": [], "outputs": [{**word_layout([("internal", 1)])[0], "sv_internal": True}]}
        (work / "layout.json").write_text(json.dumps(layout))
        (work / "stimulus-identity.json").write_text(json.dumps({"cycles": 1}))
        (work / "compare-mask.bin").write_bytes(struct.pack("<2Q", 1, 1))
        for variant in ("sv-off", "firrtl-off", "firrtl-prefer"):
            (work / variant).mkdir()
            (work / variant / "outputs.bin").write_bytes(struct.pack("<2Q", 1, 0))
        compare(self.args, "Observed")
        report = json.loads((work / "comparison.json").read_text())
        self.assertEqual(report["sv_internal_bits"], 2)
        self.assertEqual(report["sv_firrtl_bits"], 0)
        compare(self.args, "Observed", prefix_cycles=1)
        prefix = json.loads((work / "comparison-prefix.json").read_text())
        self.assertFalse(prefix["complete"])
        self.assertFalse(prefix["passed"])
        self.assertEqual(prefix["compared_records"], 2)
        self.assertEqual(prefix["available_full_records"]["sv-off"], 2)
        with self.assertRaisesRegex(ValueError, "not reached"):
            compare(self.args, "Observed", prefix_cycles=2)
        (work / "sv-off/outputs.bin").write_bytes(struct.pack("<2Q", 0, 0))
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            compare(self.args, "Observed")

    def test_final_comparison_rejects_consistent_truncation(self):
        work = self.args.output / "Truncated"
        work.mkdir()
        (work / "layout.json").write_text(json.dumps({"inputs": [], "outputs": word_layout([("out", 1)])}))
        (work / "stimulus-identity.json").write_text(json.dumps({"cycles": 2}))
        (work / "compare-mask.bin").write_bytes(struct.pack("<2Q", 1, 1))
        for variant in ("sv-off", "firrtl-off", "firrtl-prefer"):
            (work / variant).mkdir()
            (work / variant / "outputs.bin").write_bytes(struct.pack("<2Q", 0, 0))
        with self.assertRaisesRegex(ValueError, "every complete"):
            compare(self.args, "Truncated")

    def test_comparison_rejects_missing_stimulus_identity(self):
        work = self.args.output / "MissingIdentity"
        work.mkdir()
        (work / "layout.json").write_text(json.dumps({"inputs": [], "outputs": word_layout([("out", 1)])}))
        (work / "compare-mask.bin").write_bytes(struct.pack("<2Q", 1, 1))
        for variant in ("sv-off", "firrtl-off", "firrtl-prefer"):
            (work / variant).mkdir()
            (work / variant / "outputs.bin").write_bytes(struct.pack("<2Q", 0, 0))
        for prefix in (None, 1):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "requires stimulus identity"):
                compare(self.args, "MissingIdentity", prefix_cycles=prefix)
        self.assertFalse((work / "comparison.json").exists())

    def test_live_extra_input_requires_context_evidence(self):
        name = "io__DOT__unaccounted"
        with self.assertRaisesRegex(ValueError, "requires source context proof"):
            audit_retained_inputs(self.args, "Rob", {name: {"users": [{"op": "consumer", "idx": 0}]}},
                [{"name": name, "width": 1, "shape": [], "matched": 0, "direction": "input"}])


if __name__ == "__main__":
    unittest.main()
