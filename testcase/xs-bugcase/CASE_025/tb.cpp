#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

static vluint64_t main_time = 0;

struct Stimulus {
    bool rst_n = true;
    bool req_read = false;
    bool req_write = false;
    std::uint8_t req_addr = 0;
    std::uint16_t req_wdata = 0;
};

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    grhsim.clk = clk;
    ref.rst_n = s.rst_n;
    grhsim.rst_n = s.rst_n;
    ref.req_read = s.req_read;
    grhsim.req_read = s.req_read;
    ref.req_write = s.req_write;
    grhsim.req_write = s.req_write;
    ref.req_addr = s.req_addr;
    grhsim.req_addr = s.req_addr;
    ref.req_wdata = s.req_wdata;
    grhsim.req_wdata = s.req_wdata;
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
    for (const bool clk : {false, true}) {
        drive(ref, grhsim, clk, s);
        ref.eval();
        grhsim.eval();
        if (ref.resp_data != grhsim.resp_data) {
            std::fprintf(stderr,
                         "[MISMATCH] cycle=%d phase=%s resp_data ref=0x%04x grhsim=0x%04x\n",
                         cycle,
                         clk ? "high" : "low",
                         static_cast<unsigned>(ref.resp_data),
                         static_cast<unsigned>(grhsim.resp_data));
            return false;
        }
        ++main_time;
    }
    return true;
}

} // namespace

double sc_time_stamp() { return static_cast<double>(main_time); }

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

    int cycle = 0;
    const auto run = [&](const Stimulus& s) { return step(ref, grhsim, s, cycle++); };

    // Reset idle cycles (DUT macro registers have no reset, keep bus quiet).
    for (int i = 0; i < 3; ++i)
        if (!run(Stimulus{.rst_n = false})) return 1;

    // Write 0xABCD -> mem[0x42], then 0x1234 -> mem[0x77].
    if (!run(Stimulus{.req_write = true, .req_addr = 0x42, .req_wdata = 0xABCD})) return 1;
    if (!run(Stimulus{})) return 1;
    if (!run(Stimulus{.req_write = true, .req_addr = 0x77, .req_wdata = 0x1234})) return 1;
    if (!run(Stimulus{})) return 1;

    // Read both back: the resp must show up the cycle after each read request.
    if (!run(Stimulus{.req_read = true, .req_addr = 0x42})) return 1;
    if (!run(Stimulus{})) return 1;
    if (!run(Stimulus{.req_read = true, .req_addr = 0x77})) return 1;
    if (!run(Stimulus{})) return 1;

    // Interleaved read/write traffic.
    for (int i = 0; i < 16; ++i) {
        Stimulus s;
        s.req_write = (i & 1) != 0;
        s.req_read = (i & 1) == 0;
        s.req_addr = static_cast<std::uint8_t>(0x40 + (i & 7));
        s.req_wdata = static_cast<std::uint16_t>(0x2000 + i * 0x111);
        if (!run(s)) return 1;
        if (!run(Stimulus{})) return 1;
    }

    std::printf("[PASS] CASE_025 GatedSram clock-gate latch ref == grhsim\n");
    return 0;
}
