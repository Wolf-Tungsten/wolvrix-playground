#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    std::uint8_t in_valid = 0;
    std::uint8_t older0 = 0;
    std::uint8_t older1 = 0;
    std::uint8_t older2 = 0;
};

struct Outputs {
    std::uint8_t valid2 = 0;
    std::uint8_t priority2 = 0;
    bool ok2 = false;
    std::uint8_t valid3 = 0;
    std::uint16_t priority3 = 0;
    bool ok3 = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.in_valid = static_cast<std::uint8_t>((cycle * 5 + 3) & 7);
    s.older0 = static_cast<std::uint8_t>(cycle & 3);
    s.older1 = static_cast<std::uint8_t>((cycle + 1) & 3);
    s.older2 = static_cast<std::uint8_t>((cycle + 2) & 3);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.in_valid = s.in_valid;
    ref.older0 = s.older0;
    ref.older1 = s.older1;
    ref.older2 = s.older2;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.in_valid = s.in_valid;
    grhsim.older0 = s.older0;
    grhsim.older1 = s.older1;
    grhsim.older2 = s.older2;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<std::uint8_t>(ref.valid2),
        static_cast<std::uint8_t>(ref.priority2),
        ref.ok2 != 0,
        static_cast<std::uint8_t>(ref.valid3),
        static_cast<std::uint16_t>(ref.priority3),
        ref.ok3 != 0,
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint8_t>(grhsim.valid2),
        static_cast<std::uint8_t>(grhsim.priority2),
        grhsim.ok2 != 0,
        static_cast<std::uint8_t>(grhsim.valid3),
        static_cast<std::uint16_t>(grhsim.priority3),
        grhsim.ok3 != 0,
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    bool ok = true;
    if (ref.valid2 != grhsim.valid2 || ref.priority2 != grhsim.priority2 || ref.ok2 != grhsim.ok2) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d phase=%s dut2 valid ref=0x%x grhsim=0x%x "
                     "priority ref=0x%x grhsim=0x%x ok ref=%u grhsim=%u\n",
                     cycle, phase,
                     static_cast<unsigned>(ref.valid2),
                     static_cast<unsigned>(grhsim.valid2),
                     static_cast<unsigned>(ref.priority2),
                     static_cast<unsigned>(grhsim.priority2),
                     ref.ok2 ? 1u : 0u,
                     grhsim.ok2 ? 1u : 0u);
        ok = false;
    }
    if (ref.valid3 != grhsim.valid3 || ref.priority3 != grhsim.priority3 || ref.ok3 != grhsim.ok3) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d phase=%s dut3 valid ref=0x%x grhsim=0x%x "
                     "priority ref=0x%x grhsim=0x%x ok ref=%u grhsim=%u\n",
                     cycle, phase,
                     static_cast<unsigned>(ref.valid3),
                     static_cast<unsigned>(grhsim.valid3),
                     static_cast<unsigned>(ref.priority3),
                     static_cast<unsigned>(grhsim.priority3),
                     ref.ok3 ? 1u : 0u,
                     grhsim.ok3 ? 1u : 0u);
        ok = false;
    }
    return ok;
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

    if (s.rst_n) {
        return true;
    }
    const Outputs refOut = sample_ref(ref);
    if (refOut.valid2 != 0 || refOut.priority2 != 0x9 || !refOut.ok2 ||
        refOut.valid3 != 0 || refOut.priority3 != 0x111 || !refOut.ok3) {
        std::fprintf(stderr,
                     "[REF-UNEXPECTED] cycle=%d reset state valid2=0x%x priority2=0x%x ok2=%u "
                     "valid3=0x%x priority3=0x%x ok3=%u\n",
                     cycle,
                     static_cast<unsigned>(refOut.valid2),
                     static_cast<unsigned>(refOut.priority2),
                     refOut.ok2 ? 1u : 0u,
                     static_cast<unsigned>(refOut.valid3),
                     static_cast<unsigned>(refOut.priority3),
                     refOut.ok3 ? 1u : 0u);
        return false;
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
    for (int cycle = 0; cycle < 32; ++cycle) {
        if (!step(ref, grhsim, cycle)) {
            return 1;
        }
    }
    std::printf("[PASS] CASE_009 ref == grhsim\n");
    return 0;
}
