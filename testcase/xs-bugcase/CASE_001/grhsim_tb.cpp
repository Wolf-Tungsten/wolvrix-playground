#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"
#include "verilated_cov.h"

static vluint64_t main_time = 0;
double sc_time_stamp() { return static_cast<double>(main_time); }

static void tick(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim, bool clk) {
    ref.clk = clk;
    grhsim.clk = clk;
    ref.eval();
    grhsim.eval();
    ++main_time;
}

static void set_w76(VlWide<3> &dst, std::uint64_t lo, std::uint32_t hi) {
    dst[0] = static_cast<vluint32_t>(lo);
    dst[1] = static_cast<vluint32_t>(lo >> 32);
    dst[2] = hi & 0x0fffU;
}

static void set_w76(unsigned _BitInt(128) &dst, std::uint64_t lo, std::uint32_t hi) {
    dst = static_cast<unsigned _BitInt(128)>(lo) |
          (static_cast<unsigned _BitInt(128)>(hi & 0x0fffU) << 64);
}

static int compare_step(const VRef &ref, const GrhSIM_xs_bugcase_tb &grhsim, int cycle) {
    const std::uint64_t ref_lo = static_cast<std::uint64_t>(ref.RW0_rdata[0]) |
                                 (static_cast<std::uint64_t>(ref.RW0_rdata[1]) << 32);
    const std::uint32_t ref_hi = ref.RW0_rdata[2] & 0x0fffU;
    const std::uint64_t grhsim_lo = static_cast<std::uint64_t>(grhsim.RW0_rdata);
    const std::uint64_t grhsim_hi = static_cast<std::uint64_t>(grhsim.RW0_rdata >> 64) & 0x0fffU;
    if (ref_lo == grhsim_lo && ref_hi == grhsim_hi) {
        return 0;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d rdata ref=%03x_%016llx grhsim=%03llx_%016llx\n",
                 cycle, ref_hi, static_cast<unsigned long long>(ref_lo),
                 static_cast<unsigned long long>(grhsim_hi),
                 static_cast<unsigned long long>(grhsim_lo));
    return 1;
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);

    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

    ref.clk = 0;
    grhsim.clk = 0;
    ref.rst_n = 0;
    grhsim.rst_n = 0;
    ref.RW0_en = 0;
    grhsim.RW0_en = 0;
    ref.RW0_wmode = 0;
    grhsim.RW0_wmode = 0;
    ref.RW0_addr = 0;
    grhsim.RW0_addr = 0;
    set_w76(ref.RW0_wmask, 0, 0);
    set_w76(grhsim.RW0_wmask, 0, 0);
    set_w76(ref.RW0_wdata, 0, 0);
    set_w76(grhsim.RW0_wdata, 0, 0);

    for (int i = 0; i < 2; ++i) {
        tick(ref, grhsim, false);
        tick(ref, grhsim, true);
    }

    ref.rst_n = 1;
    grhsim.rst_n = 1;

    int cycle = 0;
    for (int addr = 0; addr < 4; ++addr) {
        const std::uint64_t wdata_lo = 0x0123456789abcdefULL ^ static_cast<std::uint64_t>(addr);
        const std::uint32_t wdata_hi = static_cast<std::uint32_t>((0xabcU ^ addr) & 0x0fffU);

        ref.RW0_addr = addr;
        grhsim.RW0_addr = addr;
        ref.RW0_en = 1;
        grhsim.RW0_en = 1;
        ref.RW0_wmode = 1;
        grhsim.RW0_wmode = 1;
        set_w76(ref.RW0_wmask, UINT64_MAX, 0x0fffU);
        set_w76(grhsim.RW0_wmask, UINT64_MAX, 0x0fffU);
        set_w76(ref.RW0_wdata, wdata_lo, wdata_hi);
        set_w76(grhsim.RW0_wdata, wdata_lo, wdata_hi);
        tick(ref, grhsim, false);
        tick(ref, grhsim, true);
        if (compare_step(ref, grhsim, cycle++) != 0) {
            return 1;
        }

        ref.RW0_wmode = 0;
        grhsim.RW0_wmode = 0;
        set_w76(ref.RW0_wmask, 0, 0);
        set_w76(grhsim.RW0_wmask, 0, 0);
        set_w76(ref.RW0_wdata, 0, 0);
        set_w76(grhsim.RW0_wdata, 0, 0);
        tick(ref, grhsim, false);
        tick(ref, grhsim, true);
        if (compare_step(ref, grhsim, cycle++) != 0) {
            return 1;
        }

        ref.RW0_en = 0;
        grhsim.RW0_en = 0;
        tick(ref, grhsim, false);
        tick(ref, grhsim, true);
        if (compare_step(ref, grhsim, cycle++) != 0) {
            return 1;
        }
    }

    VerilatedCov::write();
    std::printf("[PASS] CASE_001 ref == grhsim\n");
    return 0;
}
