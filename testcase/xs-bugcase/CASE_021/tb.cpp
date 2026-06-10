#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool t0_fire = false;
    std::uint16_t start_idx = 0;
    std::uint8_t payload_in = 0;
};

struct Outputs {
    std::uint16_t child0_set_idx = 0;
    std::uint16_t child1_set_idx = 0;
    std::uint8_t child0_payload = 0;
    std::uint8_t child1_payload = 0;
    bool ok = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.t0_fire = s.rst_n;
    s.start_idx = static_cast<std::uint16_t>((0x0fcu + cycle * 0x13u) & 0x1ffu);
    s.payload_in = static_cast<std::uint8_t>((0x9u + cycle) & 0xfu);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.t0_fire = s.t0_fire;
    ref.start_idx = s.start_idx;
    ref.payload_in = s.payload_in;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.t0_fire = s.t0_fire;
    grhsim.start_idx = s.start_idx;
    grhsim.payload_in = s.payload_in;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<std::uint16_t>(ref.child0_set_idx),
        static_cast<std::uint16_t>(ref.child1_set_idx),
        static_cast<std::uint8_t>(ref.child0_payload),
        static_cast<std::uint8_t>(ref.child1_payload),
        ref.ok != 0,
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint16_t>(grhsim.child0_set_idx),
        static_cast<std::uint16_t>(grhsim.child1_set_idx),
        static_cast<std::uint8_t>(grhsim.child0_payload),
        static_cast<std::uint8_t>(grhsim.child1_payload),
        grhsim.ok != 0,
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.child0_set_idx == grhsim.child0_set_idx &&
        ref.child1_set_idx == grhsim.child1_set_idx &&
        ref.child0_payload == grhsim.child0_payload &&
        ref.child1_payload == grhsim.child1_payload &&
        ref.ok == grhsim.ok) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s "
                 "child0_set_idx ref=0x%03x grhsim=0x%03x "
                 "child1_set_idx ref=0x%03x grhsim=0x%03x "
                 "payload0 ref=0x%x grhsim=0x%x "
                 "payload1 ref=0x%x grhsim=0x%x "
                 "ok ref=%u grhsim=%u\n",
                 cycle,
                 phase,
                 ref.child0_set_idx,
                 grhsim.child0_set_idx,
                 ref.child1_set_idx,
                 grhsim.child1_set_idx,
                 ref.child0_payload,
                 grhsim.child0_payload,
                 ref.child1_payload,
                 grhsim.child1_payload,
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
    std::printf("[PASS] CASE_021 ref == grhsim\n");
    return 0;
}
