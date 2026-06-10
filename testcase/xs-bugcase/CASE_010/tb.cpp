#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool load = false;
    std::uint32_t packed_in0 = 0;
    std::uint32_t packed_in1 = 0;
    std::uint32_t packed_in2 = 0;
    std::uint32_t packed_in3 = 0;
};

struct Outputs {
    std::uint32_t row0 = 0;
    std::uint32_t row1 = 0;
    std::uint32_t row2 = 0;
    std::uint32_t row3 = 0;
    std::uint32_t checksum = 0;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.load = s.rst_n && ((cycle % 3) != 0);
    s.packed_in0 = 0x20000000u + static_cast<std::uint32_t>(cycle * 3);
    s.packed_in1 = 0x10000000u + static_cast<std::uint32_t>(cycle);
    s.packed_in2 = 0x40000000u + static_cast<std::uint32_t>(cycle * 7);
    s.packed_in3 = 0x30000000u + static_cast<std::uint32_t>(cycle * 5);
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.load = s.load;
    ref.packed_in0 = s.packed_in0;
    ref.packed_in1 = s.packed_in1;
    ref.packed_in2 = s.packed_in2;
    ref.packed_in3 = s.packed_in3;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.load = s.load;
    grhsim.packed_in0 = s.packed_in0;
    grhsim.packed_in1 = s.packed_in1;
    grhsim.packed_in2 = s.packed_in2;
    grhsim.packed_in3 = s.packed_in3;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<std::uint32_t>(ref.row0),
        static_cast<std::uint32_t>(ref.row1),
        static_cast<std::uint32_t>(ref.row2),
        static_cast<std::uint32_t>(ref.row3),
        static_cast<std::uint32_t>(ref.checksum),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint32_t>(grhsim.row0),
        static_cast<std::uint32_t>(grhsim.row1),
        static_cast<std::uint32_t>(grhsim.row2),
        static_cast<std::uint32_t>(grhsim.row3),
        static_cast<std::uint32_t>(grhsim.checksum),
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.row0 == grhsim.row0 && ref.row1 == grhsim.row1 &&
        ref.row2 == grhsim.row2 && ref.row3 == grhsim.row3 &&
        ref.checksum == grhsim.checksum) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s "
                 "row0 ref=0x%08x grhsim=0x%08x row1 ref=0x%08x grhsim=0x%08x "
                 "row2 ref=0x%08x grhsim=0x%08x row3 ref=0x%08x grhsim=0x%08x "
                 "checksum ref=0x%08x grhsim=0x%08x\n",
                 cycle,
                 phase,
                 ref.row0,
                 grhsim.row0,
                 ref.row1,
                 grhsim.row1,
                 ref.row2,
                 grhsim.row2,
                 ref.row3,
                 grhsim.row3,
                 ref.checksum,
                 grhsim.checksum);
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
    for (int cycle = 0; cycle < 20; ++cycle) {
        if (!step(ref, grhsim, cycle)) {
            return 1;
        }
    }
    std::printf("[PASS] CASE_010 ref == grhsim\n");
    return 0;
}
