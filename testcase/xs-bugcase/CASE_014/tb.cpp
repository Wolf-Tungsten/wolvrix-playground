#include <array>
#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

enum class EvalModel {
    Ref,
    GrhSIM,
};

struct Stimulus {
    bool rst_n = false;
    std::uint8_t hartId = 0x5a;
    bool redirect = false;
    bool rab_commit = false;
    bool rab_walk = false;
    std::uint8_t rab_valid = 0;
    std::uint8_t rab_walk_valid = 0;
    bool rab0_fpWen = false;
    std::uint8_t rab0_ldest = 0;
    std::uint8_t rab0_pdest = 0;
    bool rab1_fpWen = false;
    std::uint8_t rab1_ldest = 0;
    std::uint8_t rab1_pdest = 0;
    bool diff0_valid = false;
    bool diff0_fpWen = false;
    std::uint8_t diff0_ldest = 0;
    std::uint8_t diff0_pdest = 0;
    bool diff1_valid = false;
    bool diff1_fpWen = false;
    std::uint8_t diff1_ldest = 0;
    std::uint8_t diff1_pdest = 0;
    bool fp_rename0_wen = false;
    std::uint8_t fp_rename0_addr = 0;
    std::uint8_t fp_rename0_data = 0;
    bool fp_rename1_wen = false;
    std::uint8_t fp_rename1_addr = 0;
    std::uint8_t fp_rename1_data = 0;
    bool fp_read_hold = false;
    std::uint8_t fp_read_addr = 0;
};

struct Outputs {
    std::uint8_t fp_read_data = 0;
    std::uint8_t diff_rat0 = 0;
    std::uint8_t diff_rat1 = 0;
    std::uint8_t diff_rat2 = 0;
    std::uint8_t diff_rat3 = 0;
    std::uint8_t diff_coreid = 0;
};

struct ExpectedDiffRat {
    std::array<bool, 4> known{{false, false, false, false}};
    std::array<std::uint8_t, 4> value{{0, 0, 0, 0}};
};

static vluint64_t main_time = 0;
static EvalModel active_model = EvalModel::Ref;
static int ref_assert_count = 0;
static int grhsim_assert_count = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 2;
    s.fp_read_addr = static_cast<std::uint8_t>((cycle + 1) & 0x3f);

    switch (cycle) {
    case 3:
        s.diff0_valid = true;
        s.diff0_fpWen = true;
        s.diff0_ldest = 1;
        s.diff0_pdest = 29;
        s.rab_commit = true;
        s.rab_valid = 0x1;
        s.rab0_fpWen = true;
        s.rab0_ldest = 1;
        s.rab0_pdest = 29;
        s.fp_read_addr = 1;
        break;
    case 4:
        s.fp_read_addr = 1;
        break;
    case 5:
        s.diff0_valid = true;
        s.diff0_fpWen = true;
        s.diff0_ldest = 2;
        s.diff0_pdest = 30;
        s.diff1_valid = true;
        s.diff1_fpWen = true;
        s.diff1_ldest = 3;
        s.diff1_pdest = 31;
        s.fp_rename0_wen = true;
        s.fp_rename0_addr = 3;
        s.fp_rename0_data = 40;
        s.fp_rename1_wen = true;
        s.fp_rename1_addr = 4;
        s.fp_rename1_data = 41;
        s.fp_read_addr = 3;
        break;
    case 6:
        s.rab_commit = true;
        s.rab_valid = 0x3;
        s.rab0_fpWen = true;
        s.rab0_ldest = 2;
        s.rab0_pdest = 30;
        s.rab1_fpWen = true;
        s.rab1_ldest = 3;
        s.rab1_pdest = 31;
        s.fp_read_addr = 3;
        break;
    case 7:
        s.diff0_valid = true;
        s.diff0_fpWen = true;
        s.diff0_ldest = 1;
        s.diff0_pdest = 45;
        s.fp_read_addr = 1;
        break;
    case 8:
        s.fp_read_hold = true;
        s.fp_read_addr = 2;
        break;
    case 9:
        s.redirect = true;
        s.fp_read_addr = 1;
        break;
    default:
        break;
    }

    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.hartId = s.hartId;
    ref.redirect = s.redirect;
    ref.rab_commit = s.rab_commit;
    ref.rab_walk = s.rab_walk;
    ref.rab_valid = s.rab_valid;
    ref.rab_walk_valid = s.rab_walk_valid;
    ref.rab0_fpWen = s.rab0_fpWen;
    ref.rab0_ldest = s.rab0_ldest;
    ref.rab0_pdest = s.rab0_pdest;
    ref.rab1_fpWen = s.rab1_fpWen;
    ref.rab1_ldest = s.rab1_ldest;
    ref.rab1_pdest = s.rab1_pdest;
    ref.diff0_valid = s.diff0_valid;
    ref.diff0_fpWen = s.diff0_fpWen;
    ref.diff0_ldest = s.diff0_ldest;
    ref.diff0_pdest = s.diff0_pdest;
    ref.diff1_valid = s.diff1_valid;
    ref.diff1_fpWen = s.diff1_fpWen;
    ref.diff1_ldest = s.diff1_ldest;
    ref.diff1_pdest = s.diff1_pdest;
    ref.fp_rename0_wen = s.fp_rename0_wen;
    ref.fp_rename0_addr = s.fp_rename0_addr;
    ref.fp_rename0_data = s.fp_rename0_data;
    ref.fp_rename1_wen = s.fp_rename1_wen;
    ref.fp_rename1_addr = s.fp_rename1_addr;
    ref.fp_rename1_data = s.fp_rename1_data;
    ref.fp_read_hold = s.fp_read_hold;
    ref.fp_read_addr = s.fp_read_addr;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.hartId = s.hartId;
    grhsim.redirect = s.redirect;
    grhsim.rab_commit = s.rab_commit;
    grhsim.rab_walk = s.rab_walk;
    grhsim.rab_valid = s.rab_valid;
    grhsim.rab_walk_valid = s.rab_walk_valid;
    grhsim.rab0_fpWen = s.rab0_fpWen;
    grhsim.rab0_ldest = s.rab0_ldest;
    grhsim.rab0_pdest = s.rab0_pdest;
    grhsim.rab1_fpWen = s.rab1_fpWen;
    grhsim.rab1_ldest = s.rab1_ldest;
    grhsim.rab1_pdest = s.rab1_pdest;
    grhsim.diff0_valid = s.diff0_valid;
    grhsim.diff0_fpWen = s.diff0_fpWen;
    grhsim.diff0_ldest = s.diff0_ldest;
    grhsim.diff0_pdest = s.diff0_pdest;
    grhsim.diff1_valid = s.diff1_valid;
    grhsim.diff1_fpWen = s.diff1_fpWen;
    grhsim.diff1_ldest = s.diff1_ldest;
    grhsim.diff1_pdest = s.diff1_pdest;
    grhsim.fp_rename0_wen = s.fp_rename0_wen;
    grhsim.fp_rename0_addr = s.fp_rename0_addr;
    grhsim.fp_rename0_data = s.fp_rename0_data;
    grhsim.fp_rename1_wen = s.fp_rename1_wen;
    grhsim.fp_rename1_addr = s.fp_rename1_addr;
    grhsim.fp_rename1_data = s.fp_rename1_data;
    grhsim.fp_read_hold = s.fp_read_hold;
    grhsim.fp_read_addr = s.fp_read_addr;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<std::uint8_t>(ref.fp_read_data),
        static_cast<std::uint8_t>(ref.diff_rat0),
        static_cast<std::uint8_t>(ref.diff_rat1),
        static_cast<std::uint8_t>(ref.diff_rat2),
        static_cast<std::uint8_t>(ref.diff_rat3),
        static_cast<std::uint8_t>(ref.diff_coreid),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<std::uint8_t>(grhsim.fp_read_data),
        static_cast<std::uint8_t>(grhsim.diff_rat0),
        static_cast<std::uint8_t>(grhsim.diff_rat1),
        static_cast<std::uint8_t>(grhsim.diff_rat2),
        static_cast<std::uint8_t>(grhsim.diff_rat3),
        static_cast<std::uint8_t>(grhsim.diff_coreid),
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.fp_read_data == grhsim.fp_read_data &&
        ref.diff_rat0 == grhsim.diff_rat0 &&
        ref.diff_rat1 == grhsim.diff_rat1 &&
        ref.diff_rat2 == grhsim.diff_rat2 &&
        ref.diff_rat3 == grhsim.diff_rat3 &&
        ref.diff_coreid == grhsim.diff_coreid) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s "
                 "fp_read ref=0x%02x grhsim=0x%02x rat0 ref=0x%02x grhsim=0x%02x "
                 "rat1 ref=0x%02x grhsim=0x%02x rat2 ref=0x%02x grhsim=0x%02x "
                 "rat3 ref=0x%02x grhsim=0x%02x core ref=0x%02x grhsim=0x%02x\n",
                 cycle,
                 phase,
                 ref.fp_read_data,
                 grhsim.fp_read_data,
                 ref.diff_rat0,
                 grhsim.diff_rat0,
                 ref.diff_rat1,
                 grhsim.diff_rat1,
                 ref.diff_rat2,
                 grhsim.diff_rat2,
                 ref.diff_rat3,
                 grhsim.diff_rat3,
                 ref.diff_coreid,
                 grhsim.diff_coreid);
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

bool check_asserts(int cycle, const char* phase)
{
    if (ref_assert_count == grhsim_assert_count) {
        return true;
    }
    std::fprintf(stderr,
                 "[ASSERT-MISMATCH] cycle=%d phase=%s ref_asserts=%d grhsim_asserts=%d\n",
                 cycle,
                 phase,
                 ref_assert_count,
                 grhsim_assert_count);
    return false;
}

void update_expected(ExpectedDiffRat& expected, const Stimulus& s)
{
    if (!s.rst_n) {
        expected.known = {false, false, false, false};
        expected.value = {0, 0, 0, 0};
        return;
    }
    if (s.diff0_valid && s.diff0_fpWen && s.diff0_ldest < expected.known.size()) {
        expected.known[s.diff0_ldest] = true;
        expected.value[s.diff0_ldest] = s.diff0_pdest;
    }
    if (s.diff1_valid && s.diff1_fpWen && s.diff1_ldest < expected.known.size()) {
        expected.known[s.diff1_ldest] = true;
        expected.value[s.diff1_ldest] = s.diff1_pdest;
    }
}

bool check_expected(const Outputs& ref, const ExpectedDiffRat& expected, int cycle)
{
    const std::array<std::uint8_t, 4> actual{{ref.diff_rat0, ref.diff_rat1, ref.diff_rat2, ref.diff_rat3}};
    for (std::size_t i = 0; i < actual.size(); ++i) {
        if (!expected.known[i]) {
            continue;
        }
        if (actual[i] != expected.value[i]) {
            std::fprintf(stderr,
                         "[REF-SEMANTIC] cycle=%d diff_rat%zu expected=0x%02x ref=0x%02x\n",
                         cycle,
                         i,
                         expected.value[i],
                         actual[i]);
            return false;
        }
    }
    return true;
}

void eval_ref(VRef& ref)
{
    active_model = EvalModel::Ref;
    ref.eval();
}

void eval_grhsim(GrhSIM_xs_bugcase_tb& grhsim)
{
    active_model = EvalModel::GrhSIM;
    grhsim.eval();
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, ExpectedDiffRat& expected, int cycle)
{
    const Stimulus s = build_stimulus(cycle);
    drive(ref, grhsim, false, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (s.rst_n && !compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "low")) {
        return false;
    }
    if (!check_asserts(cycle, "low") || !check_runtime(grhsim, cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    update_expected(expected, s);
    const Outputs ref_out = sample_ref(ref);
    if (!compare(ref_out, sample_grhsim(grhsim), cycle, "high")) {
        return false;
    }
    if (!check_expected(ref_out, expected, cycle)) {
        return false;
    }
    if (!check_asserts(cycle, "high") || !check_runtime(grhsim, cycle, "high")) {
        return false;
    }
    ++main_time;
    return true;
}

} // namespace

extern "C" void xs_assert_v2(const char* filename, long long line)
{
    if (active_model == EvalModel::Ref) {
        ++ref_assert_count;
        std::printf("[REF-ASSERT] %s:%lld\n", filename, line);
    }
    else {
        ++grhsim_assert_count;
        std::printf("[GRHSIM-ASSERT] %s:%lld\n", filename, line);
    }
}

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    ExpectedDiffRat expected;
    grhsim.init();
    for (int cycle = 0; cycle < 16; ++cycle) {
        if (!step(ref, grhsim, expected, cycle)) {
            return 1;
        }
    }
    if (ref_assert_count != 0 || grhsim_assert_count != 0) {
        std::fprintf(stderr,
                     "[ASSERT-UNEXPECTED] ref_asserts=%d grhsim_asserts=%d\n",
                     ref_assert_count,
                     grhsim_assert_count);
        return 1;
    }
    if (!expected.known[1] || expected.value[1] != 45 || !expected.known[2] ||
        expected.value[2] != 30 || !expected.known[3] || expected.value[3] != 31) {
        std::fprintf(stderr, "[TESTBUG] expected FP difftest RAT updates were not exercised\n");
        return 1;
    }
    std::printf("[PASS] CASE_014 ref == grhsim\n");
    return 0;
}
