"""Check packed RTL bit ordering and the FIRRTL-array replay boundary."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from gen_rob_bench import (
    GsimPort, GrhsimMember, build_leaves, compute_record_layout, emit_cpp,
    parse_sv_ports, sv_port_leaves,
)
from pack_rob_trace import build_plan
from map_rob_fst import computational_input_uses, constant_zero_reason, validate_reference


class RobTraceTests(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[3] / "ptmp/rob-script-tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def rtl(self, text):
        path = self.work / "Rob.sv"
        path.write_text(text)
        return path

    def test_nested_packed_offsets(self):
        sv = self.rtl("""module Rob(input clock, input reset,
            input struct packed {
                logic [3:0] tag;
                logic [1:0][4:0] lanes;
            } [1:0] bus);
            endmodule
        """)
        self.assertEqual(parse_sv_ports(sv, "Rob")["bus"].width, 28)
        leaves = {leaf.logical_name: leaf for leaf in sv_port_leaves(sv, "Rob")["bus"]}
        expected = {"bus_0_tag": (4, 10), "bus_0_lanes_0": (5, 0),
                    "bus_0_lanes_1": (5, 5), "bus_1_tag": (4, 24),
                    "bus_1_lanes_0": (5, 14), "bus_1_lanes_1": (5, 19)}
        self.assertEqual({n: (l.width, l.offset) for n, l in leaves.items()}, expected)

    def test_bool_vector_pairs_live_bits(self):
        sv = self.rtl("module Rob(input clock, input reset, input [2:0] io_lsq_mmio); endmodule")
        gsim = GsimPort("io__DOT__lsq__DOT__mmio", "input", "uint8_t", 1,
                        (4,), True, True)
        leaves = build_leaves({gsim.name: gsim}, {},
                              {"io_lsq_mmio": GrhsimMember("io_lsq_mmio", "std::uint8_t", (), 8)},
                              parse_sv_ports(sv, "Rob"), sv_port_leaves(sv, "Rob"))
        live = [l for l in leaves if l.paired]
        self.assertEqual([(l.name, l.sv_offset, l.grhsim_bit_offset) for l in live],
                         [(f"io_lsq_mmio_{i}", i, i) for i in range(3)])
        self.assertEqual(compute_record_layout(leaves)["in_words"], 3)
        cpp = emit_cpp(leaves, "Rob")
        self.assertIn("tmp[3] = 0;", cpp)
        self.assertIn("(rec[2] & 1u) << 2u", cpp)

    def test_packer_extracts_wide_fields(self):
        manifest = {"inputs": [{"name": "bus", "width": 140}],
                    "outputs": [{"name": "result", "width": 8}]}
        layout = {"in_words": 3, "out_words": 1,
                  "inputs": [{"name": "wide", "sv_port": "bus", "sv_offset": 8,
                              "width": 128, "words": 2, "offset": 0},
                             {"name": "tag", "sv_port": "bus", "sv_offset": 136,
                              "width": 4, "words": 1, "offset": 2}],
                  "outputs": [{"name": "result", "width": 8, "words": 1, "offset": 0}]}
        value = (1 << 127) | 0x123456789abcdef
        (self.work / "manifest.json").write_text(json.dumps(manifest))
        (self.work / "layout.json").write_text(json.dumps(layout))
        (self.work / "trace.txt").write_text(f"I 0 1 {(0xa << 136) | (value << 8) | 0xff:x}\nO 0 5a\n")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("pack_rob_trace.py")),
                                 "--manifest", str(self.work / "manifest.json"),
                                 "--layout", str(self.work / "layout.json"),
                                 "--in", str(self.work / "trace.txt"),
                                 "--out", str(self.work / "trace.bin")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = (self.work / "trace.bin").read_bytes()
        self.assertEqual(struct.unpack_from("<8sQII", data), (b"RobTrc01", 1, 3, 1))
        self.assertEqual(struct.unpack_from("<5Q", data, 24),
                         (1, value & ((1 << 64) - 1), value >> 64, 0xa, 0x5a))

    def test_bool_vector_inside_struct_array(self):
        sv = self.rtl("""module Rob(input clock, input reset,
            input struct packed {logic [3:0] flags;} [2:0] io_enq);
            endmodule""")
        gsim = GsimPort("io__DOT__enq__DOT__flags", "input", "uint8_t", 1,
                        (4, 4), True, True)
        leaves = build_leaves({gsim.name: gsim}, {},
                              {"io_enq__DOT__flags": GrhsimMember("io_enq__DOT__flags", "std::uint8_t", (3,), 8)},
                              parse_sv_ports(sv, "Rob"), sv_port_leaves(sv, "Rob"))
        live = [l for l in leaves if l.paired]
        self.assertEqual(len(live), 12)
        for leaf in live:
            row, bit = leaf.gsim_index
            self.assertEqual(leaf.grhsim_row, (row,))
            self.assertEqual(leaf.grhsim_bit_offset, bit)
            self.assertEqual(leaf.sv_offset, 4 * row + bit)

    def test_capture_retains_bits_narrowed_by_gsim(self):
        sv = self.rtl("module Rob(input clock, input reset, input [127:0] io_data); endmodule")
        gsim = GsimPort("io__DOT__data", "input", "uint64_t", 64, (), True, False)
        leaves = build_leaves({gsim.name: gsim}, {},
                              {"io_data": GrhsimMember("io_data", "unsigned _BitInt(128)", (), 128)},
                              parse_sv_ports(sv, "Rob"), sv_port_leaves(sv, "Rob"))
        live = [l for l in leaves if l.paired]
        self.assertEqual(live[0].width, 128)
        self.assertEqual(compute_record_layout(leaves)["in_words"], 2)
        cpp = emit_cpp(leaves, "Rob")
        self.assertIn("dut.set_io__DOT__data(static_cast<uint64_t>(mask_word(rec[0], 64u)))", cpp)
        self.assertIn("dut.io_data = bitint_from_words<128>(rec + 0, 128u)", cpp)

    def test_packer_rejects_outside_port(self):
        with self.assertRaisesRegex(RuntimeError, "outside"):
            build_plan([{"name": "field", "sv_port": "bus", "offset": 0,
                         "sv_offset": 6, "width": 4, "words": 1}],
                       [{"name": "bus", "width": 8}], "input")

    def test_packer_rejects_missing_port(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            build_plan([{"name": "missing", "offset": 0}], [], "input")

    def test_dead_input_audit_ignores_accessors_and_logging(self):
        (self.work / "Rob0.cpp").write_text("""
void SRob::set_io__DOT__dead(int val) { io__DOT__dead = val; }
void SRob::subStep0() {
    result = io__DOT__live[2];
    result |= io__DOT__dynamic[index];
#ifdef ENABLE_LOG
    printf("%x", io__DOT__dead);
#endif
}
""")
        uses = computational_input_uses(self.work)
        self.assertNotIn("io__DOT__dead", uses)
        self.assertEqual(uses["io__DOT__live"], {(2,)})
        self.assertEqual(uses["io__DOT__dynamic"], {None})

    def test_unknown_live_input_is_not_assumed_constant(self):
        self.assertIsNone(constant_zero_reason("io_redirect_valid"))
        self.assertIsNone(constant_zero_reason("io_writeback_0_bits_exceptionVec_0"))
        self.assertIsNotNone(constant_zero_reason("io_enq_req_0_bits_replayInst"))

    def test_reference_requires_clean_cycle_limit(self):
        log = self.work / "ref.log"
        log.write_text("[0] commit cycle 99 pc 80000000\n[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n"
                       "EXCEEDING CYCLE/INSTR LIMIT\n")
        self.assertEqual(validate_reference(log, 100000)["commit_records"], 1)
        with self.assertRaisesRegex(RuntimeError, "complete"):
            validate_reference(log, 200000)
        log.write_text(log.read_text() + "Assertion failed\n")
        with self.assertRaisesRegex(RuntimeError, "failure"):
            validate_reference(log, 100000)

    def test_fst_samples_before_edge_and_slices_across_words(self):
        packer = os.environ["ROB_FST_PACKER"]
        fixture = os.environ["ROB_FST_FIXTURE"]
        wave = self.work / "wave.fst"
        subprocess.run([fixture, str(wave)], check=True)
        plan = self.work / "plan.tsv"
        plan.write_text("3 1\n1 0 1 -2 1 clock\n2 0 1 0 1 reset\n"
                        "3 4 128 1 2 payload\n3 132 4 3 1 tag\n4 0 8 4 1 out\n")
        output = self.work / "replay.bin"
        result = subprocess.run([packer, str(wave), str(plan), str(output),
                                 str(self.work / "summary.json"), "2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = output.read_bytes()
        self.assertEqual(struct.unpack_from("<8sQII", data), (b"RobTrc01", 2, 3, 1))
        for cycle, (reset, low, high, expected) in enumerate(
                ((1, 0x1234, 0x80000000, 0x11), (0, 0x9abc, 0x20000000, 0x33))):
            value = low | (0x12345678 << 32) | (0x90abcdef << 64) | (high << 96) | (0xa5b << 128)
            payload = (value >> 4) & ((1 << 128) - 1)
            self.assertEqual(struct.unpack_from("<5Q", data, 24 + cycle * 40),
                             (reset, payload & ((1 << 64) - 1), payload >> 64, 5, expected))
        rejected = self.work / "rejected.bin"
        result = subprocess.run([packer, str(wave), str(plan), str(rejected),
                                 str(self.work / "rejected.json"), "3"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()
