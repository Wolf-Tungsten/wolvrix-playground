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
    bool in0_valid = false;
    std::uint8_t in0_addr = 0;
    bool in0_flag = false;
    std::uint16_t in0_value = 0;
    bool in0_issue = false;
    bool in1_valid = false;
    std::uint8_t in1_addr = 0;
    bool in1_flag = false;
    std::uint16_t in1_value = 0;
    bool in1_issue = false;
};

struct Outputs {
    bool in0_ready = false;
    bool in1_ready = false;
    bool out_valid = false;
    std::uint8_t out_addr = 0;
    bool out_flag = false;
    std::uint16_t out_value = 0;
    bool out_issue = false;
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
    s.in0_valid = ((cycle * 7 + 1) & 3) != 0;
    s.in1_valid = ((cycle * 5 + 2) & 3) != 0;
    s.in0_addr = static_cast<std::uint8_t>((cycle * 3 + 1) & 0x3f);
    s.in1_addr = static_cast<std::uint8_t>((cycle * 5 + 9) & 0x3f);
    s.in0_flag = ((cycle >> 1) & 1) != 0;
    s.in1_flag = ((cycle >> 2) & 1) != 0;
    s.in0_value = static_cast<std::uint16_t>((cycle * 17 + 4) & 0x1ff);
    s.in1_value = static_cast<std::uint16_t>((cycle * 11 + 19) & 0x1ff);
    s.in0_issue = ((cycle + 1) & 1) != 0;
    s.in1_issue = ((cycle + 2) & 1) != 0;
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.in0_valid = s.in0_valid;
    ref.in0_addr = s.in0_addr;
    ref.in0_flag = s.in0_flag;
    ref.in0_value = s.in0_value;
    ref.in0_issue = s.in0_issue;
    ref.in1_valid = s.in1_valid;
    ref.in1_addr = s.in1_addr;
    ref.in1_flag = s.in1_flag;
    ref.in1_value = s.in1_value;
    ref.in1_issue = s.in1_issue;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.in0_valid = s.in0_valid;
    grhsim.in0_addr = s.in0_addr;
    grhsim.in0_flag = s.in0_flag;
    grhsim.in0_value = s.in0_value;
    grhsim.in0_issue = s.in0_issue;
    grhsim.in1_valid = s.in1_valid;
    grhsim.in1_addr = s.in1_addr;
    grhsim.in1_flag = s.in1_flag;
    grhsim.in1_value = s.in1_value;
    grhsim.in1_issue = s.in1_issue;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        ref.in0_ready != 0,
        ref.in1_ready != 0,
        ref.out_valid != 0,
        static_cast<std::uint8_t>(ref.out_addr),
        ref.out_flag != 0,
        static_cast<std::uint16_t>(ref.out_value),
        ref.out_issue != 0,
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        grhsim.in0_ready != 0,
        grhsim.in1_ready != 0,
        grhsim.out_valid != 0,
        static_cast<std::uint8_t>(grhsim.out_addr),
        grhsim.out_flag != 0,
        static_cast<std::uint16_t>(grhsim.out_value),
        grhsim.out_issue != 0,
    };
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    if (ref.in0_ready == grhsim.in0_ready &&
        ref.in1_ready == grhsim.in1_ready &&
        ref.out_valid == grhsim.out_valid &&
        ref.out_addr == grhsim.out_addr &&
        ref.out_flag == grhsim.out_flag &&
        ref.out_value == grhsim.out_value &&
        ref.out_issue == grhsim.out_issue) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s "
                 "in0_ready ref=%u grhsim=%u in1_ready ref=%u grhsim=%u "
                 "out_valid ref=%u grhsim=%u out_addr ref=0x%x grhsim=0x%x "
                 "out_flag ref=%u grhsim=%u out_value ref=0x%x grhsim=0x%x "
                 "out_issue ref=%u grhsim=%u\n",
                 cycle,
                 phase,
                 ref.in0_ready ? 1u : 0u,
                 grhsim.in0_ready ? 1u : 0u,
                 ref.in1_ready ? 1u : 0u,
                 grhsim.in1_ready ? 1u : 0u,
                 ref.out_valid ? 1u : 0u,
                 grhsim.out_valid ? 1u : 0u,
                 static_cast<unsigned>(ref.out_addr),
                 static_cast<unsigned>(grhsim.out_addr),
                 ref.out_flag ? 1u : 0u,
                 grhsim.out_flag ? 1u : 0u,
                 static_cast<unsigned>(ref.out_value),
                 static_cast<unsigned>(grhsim.out_value),
                 ref.out_issue ? 1u : 0u,
                 grhsim.out_issue ? 1u : 0u);
    return false;
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

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, int cycle)
{
    const Stimulus s = build_stimulus(cycle);
    drive(ref, grhsim, false, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "low")) {
        return false;
    }
    if (!check_asserts(cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "high")) {
        return false;
    }
    if (!check_asserts(cycle, "high")) {
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
    grhsim.init();
    for (int cycle = 0; cycle < 32; ++cycle) {
        if (!step(ref, grhsim, cycle)) {
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
    std::printf("[PASS] CASE_013 ref == grhsim\n");
    return 0;
}
