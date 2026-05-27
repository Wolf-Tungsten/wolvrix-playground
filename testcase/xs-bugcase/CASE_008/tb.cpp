#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = true;
    bool en = false;
    std::uint8_t req = 0;
    bool flag = false;
    std::uint32_t a = 0;
    std::uint32_t b = 0;
    std::uint32_t c = 0;
    std::uint32_t fallback = 0;
    std::uint8_t idx = 0;
    std::uint32_t dummy = 0;
};

struct Outputs {
    std::uint32_t q = 0;
    std::uint32_t early_use = 0;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint32_t mask27(std::uint32_t value)
{
    return value & 0x07ffffffU;
}

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.en = true;
    s.req = static_cast<std::uint8_t>((cycle * 3 + 1) & 3);
    s.flag = (cycle & 2) != 0;
    s.a = mask27(0x01234567U ^ static_cast<std::uint32_t>(cycle * 0x010101U));
    s.b = mask27(0x04561234U ^ static_cast<std::uint32_t>(cycle * 0x020203U));
    s.c = mask27(0x00654321U ^ static_cast<std::uint32_t>(cycle * 0x030307U));
    s.fallback = mask27(0x0013579bU ^ static_cast<std::uint32_t>(cycle * 0x040409U));
    s.idx = static_cast<std::uint8_t>(cycle & 1);
    s.dummy = mask27(0x00777777U ^ static_cast<std::uint32_t>(cycle * 0x05050bU));
    return s;
}

void drive(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim, bool clk, const Stimulus &s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.en = s.en;
    ref.req = s.req;
    ref.flag = s.flag;
    ref.a = s.a;
    ref.b = s.b;
    ref.c = s.c;
    ref.fallback = s.fallback;
    ref.idx = s.idx;
    ref.dummy = s.dummy;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.en = s.en;
    grhsim.req = s.req;
    grhsim.flag = s.flag;
    grhsim.a = s.a;
    grhsim.b = s.b;
    grhsim.c = s.c;
    grhsim.fallback = s.fallback;
    grhsim.idx = s.idx;
    grhsim.dummy = s.dummy;
}

Outputs sample_ref(const VRef &ref)
{
    return Outputs{static_cast<std::uint32_t>(ref.q), static_cast<std::uint32_t>(ref.early_use)};
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb &grhsim)
{
    return Outputs{static_cast<std::uint32_t>(grhsim.q), static_cast<std::uint32_t>(grhsim.early_use)};
}

bool compare(const Outputs &ref, const Outputs &grhsim, int cycle, const char *phase)
{
    bool ok = true;
    if (ref.q != grhsim.q) {
        std::fprintf(stderr, "[MISMATCH] cycle=%d phase=%s q ref=0x%08x grhsim=0x%08x\n",
                     cycle, phase, ref.q, grhsim.q);
        ok = false;
    }
    if (ref.early_use != grhsim.early_use) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d phase=%s early_use ref=0x%08x grhsim=0x%08x\n",
                     cycle, phase, ref.early_use, grhsim.early_use);
        ok = false;
    }
    return ok;
}

void eval_both(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim)
{
    ref.eval();
    grhsim.eval();
}

bool step(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim, int cycle)
{
    const Stimulus s = build_stimulus(cycle);
    drive(ref, grhsim, false, s);
    eval_both(ref, grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_both(ref, grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "high")) {
        return false;
    }
    ++main_time;
    return true;
}

} // namespace

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();
    for (int cycle = 0; cycle < 64; ++cycle) {
        if (!step(ref, grhsim, cycle)) {
            return 1;
        }
    }
    std::printf("[PASS] CASE_008 ref == grhsim\n");
    return 0;
}
