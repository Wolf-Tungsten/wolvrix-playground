"""Exercise the actual emulator reset sequence against an edge-sensitive model."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GrhSimResetTests(unittest.TestCase):
    def test_reset_settles_before_clock_without_changing_pulse_count(self):
        source = (ROOT / "testcase/xiangshan/difftest/src/test/csrc/emu/emu.cpp").read_text()
        start = source.index("inline void Emulator::reset_ncycles(size_t cycles)")
        end = source.index("inline void Emulator::single_cycle()", start)
        (ROOT / "ptmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="grhsim-reset-", dir=ROOT / "ptmp") as directory:
            work = Path(directory)
            (work / "driver.cpp").write_text(r'''
#include <cassert>
#include <cstddef>
#include <stdexcept>
struct Model {
    bool clock = false, reset = false, previous = false, settled = false;
    unsigned evaluations = 0, edges = 0;
    void set_reset(unsigned value) { reset = value; }
    void set_clock(unsigned value) { clock = value; }
    void waveform_tick() {}
    void step() {
        if (clock && !previous) {
            if (!settled) throw std::runtime_error("edge preceded asynchronous reset settling");
            ++edges;
        }
        if (reset) settled = true;
        previous = clock;
        ++evaluations;
    }
};
struct Emulator {
    struct Args {
        const char* trace_name = nullptr;
        bool trace_is_read = false, enable_waveform = false, enable_waveform_full = false;
        unsigned log_begin = 0;
    } args;
    Model model;
    Model* dut_ptr = &model;
    void reset_ncycles(std::size_t);
};
''' + source[start:end] + r'''
int main() {
    Model unprepared;
    unprepared.set_reset(1);
    unprepared.set_clock(1);
    bool rejected = false;
    try { unprepared.step(); } catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
    for (const unsigned cycles : {1, 50}) {
        Emulator emulator;
        emulator.reset_ncycles(cycles);
        assert(emulator.model.evaluations == 2 * cycles + 1);
        assert(emulator.model.edges == cycles);
        assert(!emulator.model.reset && !emulator.model.clock);
    }
    Emulator zero;
    zero.reset_ncycles(0);
    assert(zero.model.evaluations == 0);
    Emulator replay;
    replay.args.trace_name = "saved";
    replay.args.trace_is_read = true;
    replay.reset_ncycles(50);
    assert(replay.model.evaluations == 0);
}
''')
            (work / "Makefile").write_text(
                "CXX ?= c++\n.PHONY: check\ncheck: driver\n\t./driver\n"
                "driver: driver.cpp\n\t$(CXX) -std=c++17 -DGRHSIM $< -o $@\n")
            environment = {**os.environ, "TMPDIR": str(work)}
            result = subprocess.run(["make", "--no-print-directory", "-C", str(work), "check"],
                cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
