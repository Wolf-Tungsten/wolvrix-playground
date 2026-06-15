#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool write_valid = false;
    std::uint8_t write_idx = 0;
    std::uint8_t write_ctr = 0;
    bool write2_valid = false;
    std::uint8_t write2_idx = 0;
    std::uint8_t write2_ctr = 0;
    std::uint8_t read_idx = 0;
};

static vluint64_t main_time = 0;
double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint32_t lcg(std::uint32_t x) { return x * 1664525u + 1013904223u; }

Stimulus build_stimulus(int cycle)
{
    std::uint32_t r = lcg(0xC0FFEEu + cycle * 2654435761u);
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.write_valid = s.rst_n && ((r >> 3) & 1);
    s.write_idx = static_cast<std::uint8_t>((r >> 4) & 0x3f);
    s.write_ctr = static_cast<std::uint8_t>((r >> 10) & 0x3);
    s.write2_valid = s.rst_n && ((r >> 12) & 1);
    s.write2_idx = static_cast<std::uint8_t>((r >> 13) & 0x3f);
    s.write2_ctr = static_cast<std::uint8_t>((r >> 19) & 0x3);
    s.read_idx = static_cast<std::uint8_t>((r >> 21) & 0x3f);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& g, bool clk, const Stimulus& s)
{
    ref.clk = clk; ref.rst_n = s.rst_n;
    ref.write_valid = s.write_valid; ref.write_idx = s.write_idx; ref.write_ctr = s.write_ctr;
    ref.write2_valid = s.write2_valid; ref.write2_idx = s.write2_idx; ref.write2_ctr = s.write2_ctr;
    ref.read_idx = s.read_idx;
    g.clk = clk; g.rst_n = s.rst_n;
    g.write_valid = s.write_valid; g.write_idx = s.write_idx; g.write_ctr = s.write_ctr;
    g.write2_valid = s.write2_valid; g.write2_idx = s.write2_idx; g.write2_ctr = s.write2_ctr;
    g.read_idx = s.read_idx;
}

bool compare(const VRef& ref, const GrhSIM_xs_bugcase_tb& g, int cycle, const char* phase)
{
    if (ref.read_ctr == g.read_ctr) return true;
    std::fprintf(stderr, "[MISMATCH] cycle=%d phase=%s read_ctr ref=0x%x grhsim=0x%x\n",
                 cycle, phase, ref.read_ctr, g.read_ctr);
    return false;
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& g, int cycle)
{
    const Stimulus s = build_stimulus(cycle);
    drive(ref, g, false, s); ref.eval(); g.eval();
    if (!compare(ref, g, cycle, "low")) return false;
    ++main_time;
    drive(ref, g, true, s); ref.eval(); g.eval();
    if (!compare(ref, g, cycle, "high")) return false;
    ++main_time;
    return true;
}

} // namespace

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb g;
    g.init();
    for (int cycle = 0; cycle < 64; ++cycle) {
        if (!step(ref, g, cycle)) return 1;
    }
    std::printf("[PASS] CASE_022 ref == grhsim\n");
    return 0;
}
