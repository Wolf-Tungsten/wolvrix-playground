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
    std::uint8_t write_usefulCtr = 0;
    bool write_useProvider = false;
    std::uint8_t write_providerTableIdx = 0;
    std::uint8_t read_idx = 0;
};

static vluint64_t main_time = 0;
double sc_time_stamp() { return static_cast<double>(main_time); }
std::uint32_t lcg(std::uint32_t x) { return x * 1664525u + 1013904223u; }

Stimulus build_stimulus(int cycle)
{
    std::uint32_t r = lcg(0xBADC0DEu + cycle * 2654435761u);
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.write_valid = s.rst_n && ((r >> 2) & 1);
    s.write_idx = static_cast<std::uint8_t>((r >> 3) & 0x3f);
    s.write_usefulCtr = static_cast<std::uint8_t>((r >> 9) & 0x3);
    s.write_useProvider = (r >> 11) & 1;
    s.write_providerTableIdx = static_cast<std::uint8_t>((r >> 12) & 0x7);
    s.read_idx = static_cast<std::uint8_t>((r >> 15) & 0x3f);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& g, bool clk, const Stimulus& s)
{
    ref.clk = clk; ref.rst_n = s.rst_n;
    ref.write_valid = s.write_valid; ref.write_idx = s.write_idx;
    ref.write_usefulCtr = s.write_usefulCtr; ref.write_useProvider = s.write_useProvider;
    ref.write_providerTableIdx = s.write_providerTableIdx; ref.read_idx = s.read_idx;
    g.clk = clk; g.rst_n = s.rst_n;
    g.write_valid = s.write_valid; g.write_idx = s.write_idx;
    g.write_usefulCtr = s.write_usefulCtr; g.write_useProvider = s.write_useProvider;
    g.write_providerTableIdx = s.write_providerTableIdx; g.read_idx = s.read_idx;
}

bool cmp(const VRef& ref, const GrhSIM_xs_bugcase_tb& g, int cycle, const char* ph)
{
    if (ref.read_usefulCtr == g.read_usefulCtr &&
        ref.read_useProvider == g.read_useProvider &&
        ref.read_providerTableIdx == g.read_providerTableIdx) return true;
    std::fprintf(stderr, "[MISMATCH] cycle=%d phase=%s ctr ref=%x grh=%x useP ref=%x grh=%x tableIdx ref=%x grh=%x\n",
                 cycle, ph, ref.read_usefulCtr, g.read_usefulCtr, ref.read_useProvider, g.read_useProvider,
                 ref.read_providerTableIdx, g.read_providerTableIdx);
    return false;
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& g, int cycle)
{
    const Stimulus s = build_stimulus(cycle);
    drive(ref, g, false, s); ref.eval(); g.eval();
    if (!cmp(ref, g, cycle, "low")) return false;
    ++main_time;
    drive(ref, g, true, s); ref.eval(); g.eval();
    if (!cmp(ref, g, cycle, "high")) return false;
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
    for (int cycle = 0; cycle < 64; ++cycle)
        if (!step(ref, g, cycle)) return 1;
    std::printf("[PASS] CASE_023 ref == grhsim\n");
    return 0;
}
