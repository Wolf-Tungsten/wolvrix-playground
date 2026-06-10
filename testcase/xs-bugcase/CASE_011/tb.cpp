#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool load = false;
    std::uint8_t next_row0 = 1;
    std::uint8_t next_row1 = 2;
};

struct Outputs {
    std::uint8_t flat = 0;
    std::uint8_t row0 = 0;
    std::uint8_t row1 = 0;
    bool bit00 = false;
    bool bit01 = false;
    bool bit10 = false;
    bool bit11 = false;
    bool onehot0 = false;
    bool onehot1 = false;
    bool ok = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.load = cycle >= 2;
    switch (cycle & 3) {
    case 0:
        s.next_row0 = 1;
        s.next_row1 = 2;
        break;
    case 1:
        s.next_row0 = 2;
        s.next_row1 = 1;
        break;
    case 2:
        s.next_row0 = 1;
        s.next_row1 = 1;
        break;
    default:
        s.next_row0 = 2;
        s.next_row1 = 2;
        break;
    }
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.load = s.load;
    ref.next_row0 = s.next_row0;
    ref.next_row1 = s.next_row1;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.load = s.load;
    grhsim.next_row0 = s.next_row0;
    grhsim.next_row1 = s.next_row1;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<std::uint8_t>(ref.priority_flat),
        static_cast<std::uint8_t>(ref.row0),
        static_cast<std::uint8_t>(ref.row1),
        ref.bit00 != 0,
        ref.bit01 != 0,
        ref.bit10 != 0,
        ref.bit11 != 0,
        ref.onehot0 != 0,
        ref.onehot1 != 0,
        ref.ok != 0,
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint8_t>(grhsim.priority_flat),
        static_cast<std::uint8_t>(grhsim.row0),
        static_cast<std::uint8_t>(grhsim.row1),
        grhsim.bit00 != 0,
        grhsim.bit01 != 0,
        grhsim.bit10 != 0,
        grhsim.bit11 != 0,
        grhsim.onehot0 != 0,
        grhsim.onehot1 != 0,
        grhsim.ok != 0,
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.flat == grhsim.flat && ref.row0 == grhsim.row0 && ref.row1 == grhsim.row1 &&
        ref.bit00 == grhsim.bit00 && ref.bit01 == grhsim.bit01 &&
        ref.bit10 == grhsim.bit10 && ref.bit11 == grhsim.bit11 &&
        ref.onehot0 == grhsim.onehot0 && ref.onehot1 == grhsim.onehot1 &&
        ref.ok == grhsim.ok) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s flat ref=0x%x grhsim=0x%x "
                 "row0 ref=0x%x grhsim=0x%x row1 ref=0x%x grhsim=0x%x "
                 "bits ref=%u%u%u%u grhsim=%u%u%u%u onehot ref=%u/%u grhsim=%u/%u ok ref=%u grhsim=%u\n",
                 cycle, phase,
                 static_cast<unsigned>(ref.flat),
                 static_cast<unsigned>(grhsim.flat),
                 static_cast<unsigned>(ref.row0),
                 static_cast<unsigned>(grhsim.row0),
                 static_cast<unsigned>(ref.row1),
                 static_cast<unsigned>(grhsim.row1),
                 ref.bit11 ? 1u : 0u,
                 ref.bit10 ? 1u : 0u,
                 ref.bit01 ? 1u : 0u,
                 ref.bit00 ? 1u : 0u,
                 grhsim.bit11 ? 1u : 0u,
                 grhsim.bit10 ? 1u : 0u,
                 grhsim.bit01 ? 1u : 0u,
                 grhsim.bit00 ? 1u : 0u,
                 ref.onehot0 ? 1u : 0u,
                 ref.onehot1 ? 1u : 0u,
                 grhsim.onehot0 ? 1u : 0u,
                 grhsim.onehot1 ? 1u : 0u,
                 ref.ok ? 1u : 0u,
                 grhsim.ok ? 1u : 0u);
    return false;
}

void eval_both(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    ref.eval();
    grhsim.eval();
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, int cycle)
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

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();
    for (int cycle = 0; cycle < 16; ++cycle) {
        if (!step(ref, grhsim, cycle)) {
            return 1;
        }
    }
    std::printf("[PASS] CASE_011 ref == grhsim\n");
    return 0;
}
