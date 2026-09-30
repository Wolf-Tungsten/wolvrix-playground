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

static int compare_step(const VRef *ref, const GrhSIM_xs_bugcase_tb *grhsim, int cycle, uint16_t expected_sum) {
    if (ref->sum != expected_sum || ref->bad != 0) {
        std::fprintf(stderr,
                     "[REF-UNEXPECTED] cycle=%d sum=%u bad=%u expected_sum=%u expected_bad=0\n",
                     cycle, static_cast<unsigned>(ref->sum),
                     static_cast<unsigned>(ref->bad), expected_sum);
        return 1;
    }
    if (ref->sum != grhsim->sum || ref->bad != grhsim->bad) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d sum ref=%u grhsim=%u bad ref=%u grhsim=%u\n",
                     cycle,
                     static_cast<unsigned>(ref->sum), static_cast<unsigned>(grhsim->sum),
                     static_cast<unsigned>(ref->bad), static_cast<unsigned>(grhsim->bad));
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
    ref->flag_a = 0;
    grhsim->flag_a = 0;
    ref->flag_b = 0;
    grhsim->flag_b = 0;
    ref->val_a = 0;
    grhsim->val_a = 0;
    ref->val_b = 0;
    grhsim->val_b = 0;
    ref->b0 = 0;
    grhsim->b0 = 0;
    ref->b1 = 0;
    grhsim->b1 = 0;
    ref->b2 = 0;
    grhsim->b2 = 0;

    for (int i = 0; i < 2; ++i) {
        tick(ref, grhsim, 0);
        tick(ref, grhsim, 1);
    }

    ref->rst_n = 1;
    grhsim->rst_n = 1;
    ref->flag_a = 0;
    grhsim->flag_a = 0;
    ref->flag_b = 0;
    grhsim->flag_b = 0;
    ref->val_a = 0xDF;
    grhsim->val_a = 0xDF;
    ref->val_b = 0x00;
    grhsim->val_b = 0x00;
    ref->b0 = 0x01;
    grhsim->b0 = 0x01;
    ref->b1 = 0x00;
    grhsim->b1 = 0x00;
    ref->b2 = 0x00;
    grhsim->b2 = 0x00;

    const uint16_t expected_sum = 0xDF + 0x01;
    int cycle = 0;
    for (int i = 0; i < 4; ++i) {
        tick(ref, grhsim, 0);
        tick(ref, grhsim, 1);
        if (compare_step(ref, grhsim, cycle++, expected_sum) != 0) {
            delete ref;
            delete grhsim;
            return 1;
        }
    }

    delete ref;
    delete grhsim;
    std::printf("[PASS] CASE_004 ref == grhsim\n");
    return 0;
}
