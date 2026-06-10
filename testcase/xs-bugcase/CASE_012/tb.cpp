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
    bool onehot1_comb = false;
    bool sampled_fail = false;
    bool different_ok = false;
    bool ok = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.load = cycle >= 2;
    if ((cycle & 1) == 0) {
        s.next_row0 = 1;
        s.next_row1 = 2;
    }
    else {
        s.next_row0 = 2;
        s.next_row1 = 1;
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
        ref.onehot1_comb != 0,
        ref.sampled_fail != 0,
        ref.different_ok != 0,
        ref.ok != 0,
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint8_t>(grhsim.priority_flat),
        static_cast<std::uint8_t>(grhsim.row0),
        static_cast<std::uint8_t>(grhsim.row1),
        grhsim.onehot1_comb != 0,
        grhsim.sampled_fail != 0,
        grhsim.different_ok != 0,
        grhsim.ok != 0,
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.flat == grhsim.flat && ref.row0 == grhsim.row0 && ref.row1 == grhsim.row1 &&
        ref.onehot1_comb == grhsim.onehot1_comb &&
        ref.sampled_fail == grhsim.sampled_fail &&
        ref.different_ok == grhsim.different_ok &&
        ref.ok == grhsim.ok) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s flat ref=0x%x grhsim=0x%x "
                 "row0 ref=0x%x grhsim=0x%x row1 ref=0x%x grhsim=0x%x "
                 "onehot1 ref=%u grhsim=%u sampled_fail ref=%u grhsim=%u "
                 "different_ok ref=%u grhsim=%u ok ref=%u grhsim=%u\n",
                 cycle,
                 phase,
                 static_cast<unsigned>(ref.flat),
                 static_cast<unsigned>(grhsim.flat),
                 static_cast<unsigned>(ref.row0),
                 static_cast<unsigned>(grhsim.row0),
                 static_cast<unsigned>(ref.row1),
                 static_cast<unsigned>(grhsim.row1),
                 ref.onehot1_comb ? 1u : 0u,
                 grhsim.onehot1_comb ? 1u : 0u,
                 ref.sampled_fail ? 1u : 0u,
                 grhsim.sampled_fail ? 1u : 0u,
                 ref.different_ok ? 1u : 0u,
                 grhsim.different_ok ? 1u : 0u,
                 ref.ok ? 1u : 0u,
                 grhsim.ok ? 1u : 0u);
    return false;
}

bool check_runtime(const GrhSIM_xs_bugcase_tb& grhsim, int cycle, const char* phase)
{
    if (!grhsim.fatal_requested() && !grhsim.finish_requested() && !grhsim.stop_requested()) {
        return true;
    }
    std::fprintf(stderr,
                 "[RUNTIME] cycle=%d phase=%s fatal=%u finish=%u stop=%u\n",
                 cycle,
                 phase,
                 grhsim.fatal_requested() ? 1u : 0u,
                 grhsim.finish_requested() ? 1u : 0u,
                 grhsim.stop_requested() ? 1u : 0u);
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
    if (!check_runtime(grhsim, cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_both(ref, grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "high")) {
        return false;
    }
    if (!check_runtime(grhsim, cycle, "high")) {
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
    std::printf("[PASS] CASE_012 ref == grhsim\n");
    return 0;
}
