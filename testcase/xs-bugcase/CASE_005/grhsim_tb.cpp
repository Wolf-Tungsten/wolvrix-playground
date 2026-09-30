#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"
#include "verilated_cov.h"

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

static void tick(VRef *ref, GrhSIM_xs_bugcase_tb *grhsim, bool clk) {
    ref->clk = clk;
    grhsim->clk = clk;
    ref->eval();
    grhsim->eval();
    ++main_time;
}

static int compare_step(const VRef *ref, const GrhSIM_xs_bugcase_tb *grhsim, int cycle) {
    const uint8_t expected_id = 1; // idx=1 should map to 1
    const uint32_t expected_sel = 1u << expected_id;

    if (ref->id_shift != expected_id || ref->id_port != expected_id || ref->bad != 0 || ref->sel != expected_sel) {
        std::fprintf(stderr,
                     "[REF-UNEXPECTED] cycle=%d id_shift=%u id_port=%u sel=0x%08x bad=%u\n",
                     cycle,
                     static_cast<unsigned>(ref->id_shift),
                     static_cast<unsigned>(ref->id_port),
                     static_cast<unsigned>(ref->sel),
                     static_cast<unsigned>(ref->bad));
        return 1;
    }
    if (ref->id_shift != grhsim->id_shift || ref->id_port != grhsim->id_port ||
        ref->sel != grhsim->sel || ref->bad != grhsim->bad) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d id_shift ref=%u grhsim=%u id_port ref=%u grhsim=%u sel ref=0x%08x grhsim=0x%08x bad ref=%u grhsim=%u\n",
                     cycle,
                     static_cast<unsigned>(ref->id_shift),
                     static_cast<unsigned>(grhsim->id_shift),
                     static_cast<unsigned>(ref->id_port),
                     static_cast<unsigned>(grhsim->id_port),
                     static_cast<unsigned>(ref->sel),
                     static_cast<unsigned>(grhsim->sel),
                     static_cast<unsigned>(ref->bad),
                     static_cast<unsigned>(grhsim->bad));
        return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);

    VRef *ref = new VRef;
    GrhSIM_xs_bugcase_tb *grhsim = new GrhSIM_xs_bugcase_tb;
    grhsim->init();

    ref->clk = 0;
    grhsim->clk = 0;
    ref->rst_n = 0;
    grhsim->rst_n = 0;
    ref->idx = 0;
    grhsim->idx = 0;

    for (int i = 0; i < 2; ++i) {
        tick(ref, grhsim, 0);
        tick(ref, grhsim, 1);
    }

    ref->rst_n = 1;
    grhsim->rst_n = 1;
    ref->idx = 1;
    grhsim->idx = 1;

    int cycle = 0;
    for (int i = 0; i < 4; ++i) {
        tick(ref, grhsim, 0);
        tick(ref, grhsim, 1);
        if (compare_step(ref, grhsim, cycle++) != 0) {
            delete ref;
            delete grhsim;
            return 1;
        }
    }

    delete ref;
    delete grhsim;
    std::printf("[PASS] CASE_005 ref == grhsim\n");
    return 0;
}
