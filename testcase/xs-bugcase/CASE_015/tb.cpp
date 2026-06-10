#include <array>
#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool touch0_valid = false;
    std::uint8_t touch0_vset = 0;
    std::uint8_t touch0_way = 0;
    bool touch1_valid = false;
    std::uint8_t touch1_vset = 0;
    std::uint8_t touch1_way = 0;
    bool victim_valid = false;
    std::uint8_t victim_vset = 0;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint32_t xorshift32(std::uint32_t& state)
{
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 3;
    if (!s.rst_n) {
        return s;
    }

    const std::uint8_t bank0_set = static_cast<std::uint8_t>(((cycle * 5) + 3) & 0x7F);
    const std::uint8_t bank1_set = static_cast<std::uint8_t>(((cycle * 7) + 11) & 0x7F);
    s.touch0_valid = (cycle % 5) != 1;
    s.touch0_vset = static_cast<std::uint8_t>((bank0_set << 1) | (cycle & 1));
    s.touch0_way = static_cast<std::uint8_t>((cycle + (cycle >> 2)) & 3);

    s.touch1_valid = (cycle % 7) != 2;
    s.touch1_vset = static_cast<std::uint8_t>((bank1_set << 1) | ((cycle + 1) & 1));
    s.touch1_way = static_cast<std::uint8_t>(((cycle * 3) + 1) & 3);

    s.victim_valid = (cycle % 4) != 0;
    s.victim_vset = static_cast<std::uint8_t>(((cycle * 13) + (cycle >> 1)) & 0xFF);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.touch0_valid = s.touch0_valid;
    ref.touch0_vset = s.touch0_vset;
    ref.touch0_way = s.touch0_way;
    ref.touch1_valid = s.touch1_valid;
    ref.touch1_vset = s.touch1_vset;
    ref.touch1_way = s.touch1_way;
    ref.victim_valid = s.victim_valid;
    ref.victim_vset = s.victim_vset;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.touch0_valid = s.touch0_valid;
    grhsim.touch0_vset = s.touch0_vset;
    grhsim.touch0_way = s.touch0_way;
    grhsim.touch1_valid = s.touch1_valid;
    grhsim.touch1_vset = s.touch1_vset;
    grhsim.touch1_way = s.touch1_way;
    grhsim.victim_valid = s.victim_valid;
    grhsim.victim_vset = s.victim_vset;
}

bool compare(const VRef& ref, const GrhSIM_xs_bugcase_tb& grhsim, int cycle, const char* phase)
{
    const std::uint8_t ref_way = static_cast<std::uint8_t>(ref.victim_way);
    const std::uint8_t grhsim_way = static_cast<std::uint8_t>(grhsim.victim_way);
    if (ref_way == grhsim_way) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s victim_way ref=%u grhsim=%u\n",
                 cycle,
                 phase,
                 static_cast<unsigned>(ref_way),
                 static_cast<unsigned>(grhsim_way));
    return false;
}

void eval_both(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    ref.eval();
    grhsim.eval();
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
    drive(ref, grhsim, false, s);
    eval_both(ref, grhsim);
    if (!compare(ref, grhsim, cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_both(ref, grhsim);
    if (!compare(ref, grhsim, cycle, "high")) {
        return false;
    }
    ++main_time;
    return true;
}

bool run_directed(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    for (int cycle = 0; cycle < 640; ++cycle) {
        if (!step(ref, grhsim, build_stimulus(cycle), cycle)) {
            return false;
        }
    }
    return true;
}

bool run_random(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    std::uint32_t rng = 0x13579BDFu;
    for (int cycle = 640; cycle < 4096; ++cycle) {
        Stimulus s;
        s.rst_n = true;
        const std::uint32_t a = xorshift32(rng);
        const std::uint32_t b = xorshift32(rng);
        s.touch0_valid = (a & 1u) != 0u;
        s.touch0_vset = static_cast<std::uint8_t>(a >> 8);
        s.touch0_way = static_cast<std::uint8_t>((a >> 4) & 3u);
        s.touch1_valid = (a & 2u) != 0u;
        s.touch1_vset = static_cast<std::uint8_t>(b);
        s.touch1_way = static_cast<std::uint8_t>((b >> 12) & 3u);
        s.victim_valid = (b & 4u) != 0u;
        s.victim_vset = static_cast<std::uint8_t>(b >> 16);
        if (!step(ref, grhsim, s, cycle)) {
            return false;
        }
    }
    return true;
}

} // namespace

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

    if (!run_directed(ref, grhsim) || !run_random(ref, grhsim)) {
        return 1;
    }

    std::printf("[PASS] CASE_015 ICacheReplacer ref == grhsim\n");
    return 0;
}
