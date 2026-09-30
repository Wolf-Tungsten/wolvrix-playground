#include <cstdint>
#include <cstdio>

#include "svdpi.h"
#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"
#include "verilated_cov.h"

static int g_model_index = 0;
static int g_jtag_calls[2] = {0, 0};
static int g_ram_reads[2] = {0, 0};
static int g_ram_writes[2] = {0, 0};
static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

extern "C" long long difftest_ram_read(long long rIdx) {
    ++g_ram_reads[g_model_index];
    return rIdx ^ 0x5a5a5a5a5a5a5a5aLL;
}

extern "C" void difftest_ram_write(long long index, long long data, long long mask) {
    (void)index;
    (void)data;
    (void)mask;
    ++g_ram_writes[g_model_index];
}

extern "C" int jtag_tick(svBit *jtag_TCK,
                          svBit *jtag_TMS,
                          svBit *jtag_TDI,
                          svBit *jtag_TRSTn,
                          svBit jtag_TDO) {
    const int tick_count = g_jtag_calls[g_model_index]++;
    const int value = tick_count ^ (jtag_TDO ? 1 : 0);
    *jtag_TCK = (tick_count >> 0) & 1;
    *jtag_TMS = (tick_count >> 1) & 1;
    *jtag_TDI = (tick_count >> 2) & 1;
    *jtag_TRSTn = (tick_count >> 3) & 1;
    return value;
}

static void tick(VRef *ref, GrhSIM_xs_bugcase_tb *grhsim, bool clk) {
    ref->clk = clk;
    grhsim->clk = clk;
    g_model_index = 0;
    ref->eval();
    g_model_index = 1;
    grhsim->eval();
    ++main_time;
}

static int compare_step(const VRef *ref, const GrhSIM_xs_bugcase_tb *grhsim, int cycle) {
    if (ref->r_0_data != grhsim->r_0_data || ref->r_0_async != grhsim->r_0_async ||
        ref->jtag_TCK != grhsim->jtag_TCK || ref->jtag_TMS != grhsim->jtag_TMS ||
        ref->jtag_TDI != grhsim->jtag_TDI || ref->jtag_TRSTn != grhsim->jtag_TRSTn ||
        ref->exit != grhsim->exit) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d ram ref=%016llx/%u grhsim=%016llx/%u "
                     "jtag ref=%u%u%u%u grhsim=%u%u%u%u exit ref=%u grhsim=%u\n",
                     cycle,
                     static_cast<unsigned long long>(ref->r_0_data),
                     static_cast<unsigned>(ref->r_0_async),
                     static_cast<unsigned long long>(grhsim->r_0_data),
                     static_cast<unsigned>(grhsim->r_0_async),
                     static_cast<unsigned>(ref->jtag_TCK),
                     static_cast<unsigned>(ref->jtag_TMS),
                     static_cast<unsigned>(ref->jtag_TDI),
                     static_cast<unsigned>(ref->jtag_TRSTn),
                     static_cast<unsigned>(grhsim->jtag_TCK),
                     static_cast<unsigned>(grhsim->jtag_TMS),
                     static_cast<unsigned>(grhsim->jtag_TDI),
                     static_cast<unsigned>(grhsim->jtag_TRSTn),
                     static_cast<unsigned>(ref->exit),
                     static_cast<unsigned>(grhsim->exit));
        return 1;
    }
    return 0;
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
    ref.enable = 0;
    grhsim.enable = 0;
    ref.init_done = 0;
    grhsim.init_done = 0;
    ref.r_0_enable = 0;
    grhsim.r_0_enable = 0;
    ref.r_0_index = 0;
    grhsim.r_0_index = 0;
    ref.w_0_enable = 0;
    grhsim.w_0_enable = 0;
    ref.w_0_index = 0;
    grhsim.w_0_index = 0;
    ref.w_0_data = 0;
    grhsim.w_0_data = 0;
    ref.w_0_mask = 0;
    grhsim.w_0_mask = 0;
    ref.jtag_TDO_data = 0;
    grhsim.jtag_TDO_data = 0;
    ref.jtag_TDO_driven = 0;
    grhsim.jtag_TDO_driven = 0;

    for (int i = 0; i < 3; ++i) {
        tick(&ref, &grhsim, 0);
        tick(&ref, &grhsim, 1);
    }

    ref.rst_n = 1;
    grhsim.rst_n = 1;
    ref.enable = 1;
    grhsim.enable = 1;

    // XsDpiTop overrides SimJTAG's tick delay to one cycle; repeated calls
    // exercise every JTAG output bit and successive exit values.
    constexpr int max_cycles = 120;
    for (int cycle = 0; cycle < max_cycles; ++cycle) {
        ref.init_done = (cycle >= 1) ? 1 : 0;
        grhsim.init_done = ref.init_done;
        ref.r_0_enable = (cycle & 1) ? 1 : 0;
        grhsim.r_0_enable = ref.r_0_enable;
        ref.r_0_index = static_cast<vluint64_t>(cycle & 0x7);
        grhsim.r_0_index = ref.r_0_index;
        ref.w_0_enable = (cycle % 3 == 0) ? 1 : 0;
        grhsim.w_0_enable = ref.w_0_enable;
        ref.w_0_index = static_cast<vluint64_t>((cycle + 1) & 0x7);
        grhsim.w_0_index = ref.w_0_index;
        ref.w_0_data = 0x100u + static_cast<vluint64_t>(cycle);
        grhsim.w_0_data = ref.w_0_data;
        ref.w_0_mask = 0xffffffffffffffffULL;
        grhsim.w_0_mask = ref.w_0_mask;
        ref.jtag_TDO_driven = 1;
        grhsim.jtag_TDO_driven = 1;
        ref.jtag_TDO_data = (cycle & 1) ? 1 : 0;
        grhsim.jtag_TDO_data = ref.jtag_TDO_data;

        tick(&ref, &grhsim, 0);
        tick(&ref, &grhsim, 1);
        if (compare_step(&ref, &grhsim, cycle) != 0) return 1;
    }

    if (g_jtag_calls[0] < 2 || g_jtag_calls[0] != g_jtag_calls[1] ||
        g_ram_reads[0] == 0 || g_ram_reads[0] != g_ram_reads[1] ||
        g_ram_writes[0] == 0 || g_ram_writes[0] != g_ram_writes[1]) {
        std::fprintf(stderr,
                     "[DPI-COVERAGE] jtag=%d/%d ram_read=%d/%d ram_write=%d/%d\n",
                     g_jtag_calls[0], g_jtag_calls[1], g_ram_reads[0], g_ram_reads[1],
                     g_ram_writes[0], g_ram_writes[1]);
        return 1;
    }

    VerilatedCov::write();
    std::printf("[PASS] CASE_002 ref == grhsim, jtag=%d ram_read=%d ram_write=%d\n",
                g_jtag_calls[0], g_ram_reads[0], g_ram_writes[0]);
    return 0;
}
