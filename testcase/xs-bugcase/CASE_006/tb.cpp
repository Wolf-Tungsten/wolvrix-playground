#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "svdpi.h"
#include "verilated.h"
#if defined(TRACE)
#include "verilated_fst_c.h"
#endif

namespace {

struct Outputs {
    std::uint64_t r_0_data = 0;
    bool r_0_async = false;
};

struct Stimulus {
    bool rst_n = true;
    bool r_en = false;
    std::uint64_t r_idx = 0;
    bool w_en = false;
    std::uint64_t w_idx = 0;
    std::uint64_t w_data = 0;
    std::uint64_t w_mask = 0;
};

static std::unordered_map<std::uint64_t, std::uint64_t> g_mem[2];
static int g_model_index = 0;
static vluint64_t main_time = 0;

#if defined(TRACE)
static VerilatedFstC *trace_ref = nullptr;
#endif

std::uint64_t init_value(std::uint64_t idx)
{
    std::uint64_t x = idx ^ 0x9e3779b97f4a7c15ULL;
    x ^= x >> 30U;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27U;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31U;
    return x;
}

const char *phase_name(int phase)
{
    switch (phase) {
    case 0:
        return "pre-posedge";
    case 1:
        return "posedge";
    case 2:
        return "post-posedge";
    default:
        return "unknown";
    }
}

std::uint64_t choose_distinct_widx(std::uint64_t r_idx, std::uint64_t candidate)
{
    if (candidate != r_idx) {
        return candidate;
    }
    return (candidate + 1ULL) & 0x3fULL;
}

std::uint64_t read_mem_value(const std::unordered_map<std::uint64_t, std::uint64_t> &mem, std::uint64_t idx)
{
    auto it = mem.find(idx);
    return (it != mem.end()) ? it->second : init_value(idx);
}

void apply_masked_write(std::unordered_map<std::uint64_t, std::uint64_t> &mem,
                        std::uint64_t idx, std::uint64_t data, std::uint64_t mask)
{
    const std::uint64_t cur = read_mem_value(mem, idx);
    mem[idx] = (cur & ~mask) | (data & mask);
}

std::uint64_t data_pattern(int cycle, std::uint64_t addr)
{
    const std::uint64_t seed = (static_cast<std::uint64_t>(cycle) << 32U) ^ (addr * 0x0101010101010101ULL);
    return 0x900df00d00000000ULL ^ seed ^ (seed << 7U) ^ (seed >> 3U);
}

Stimulus build_stimulus(int cycle)
{
    static constexpr std::uint64_t kHotAddrs[] = {0x03, 0x07, 0x0b, 0x11, 0x16, 0x1d, 0x24, 0x2b};
    static constexpr std::uint64_t kMasks[] = {
        0xffffffffffffffffULL,
        0x00ff00ff00ff00ffULL,
        0xff00ff00ff00ff00ULL,
        0x0000ffff0000ffffULL,
        0xffff0000ffff0000ULL,
    };

    Stimulus s;
    const int group = cycle / 6;
    const int lane = cycle % 6;
    const std::uint64_t base = kHotAddrs[group % 8];
    const std::uint64_t peer = kHotAddrs[(group + 3) % 8];
    const std::uint64_t far = kHotAddrs[(group + 5) % 8];
    const std::uint64_t alt = kHotAddrs[(group + 6) % 8];

    switch (lane) {
    case 0:
        s.r_en = true;
        s.r_idx = peer;
        s.w_en = true;
        s.w_idx = base;
        s.w_data = data_pattern(cycle, base);
        s.w_mask = 0xffffffffffffffffULL;
        break;
    case 1:
        s.r_en = true;
        s.r_idx = base;
        break;
    case 2:
        s.r_en = true;
        s.r_idx = far;
        s.w_en = true;
        s.w_idx = base;
        s.w_data = data_pattern(cycle, base) ^ 0x00ff00ff0000ffffULL;
        s.w_mask = kMasks[1 + (group % 4)];
        break;
    case 3:
        s.r_en = true;
        s.r_idx = base;
        break;
    case 4:
        s.r_en = (group & 1) == 0;
        s.r_idx = alt;
        s.w_en = true;
        s.w_idx = peer;
        s.w_data = data_pattern(cycle, peer) ^ 0x55005500aa00aa00ULL;
        s.w_mask = ((group & 1) == 0) ? 0xffffffffffffffffULL : 0x0000ffff0000ffffULL;
        break;
    case 5:
        s.r_en = true;
        s.r_idx = peer;
        break;
    default:
        break;
    }

    if (s.r_en && s.w_en) {
        s.w_idx = choose_distinct_widx(s.r_idx, s.w_idx);
    }
    return s;
}

void drive_inputs(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim,
                  bool rst_n, bool r_en, std::uint64_t r_idx,
                  bool w_en, std::uint64_t w_idx,
                  std::uint64_t w_data, std::uint64_t w_mask)
{
    ref.rst_n = rst_n;
    ref.r_0_enable = r_en;
    ref.r_0_index = r_idx;
    ref.w_0_enable = w_en;
    ref.w_0_index = w_idx;
    ref.w_0_data = w_data;
    ref.w_0_mask = w_mask;

    grhsim.rst_n = rst_n;
    grhsim.r_0_enable = r_en;
    grhsim.r_0_index = r_idx;
    grhsim.w_0_enable = w_en;
    grhsim.w_0_index = w_idx;
    grhsim.w_0_data = w_data;
    grhsim.w_0_mask = w_mask;
}

Outputs sample_ref(const VRef &ref)
{
    return Outputs{
        ref.r_0_data,
        static_cast<bool>(ref.r_0_async),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb &grhsim)
{
    return Outputs{
        grhsim.r_0_data,
        grhsim.r_0_async,
    };
}

bool compare_outputs(const Outputs &ref, const Outputs &grhsim, int cycle, int phase)
{
    bool ok = true;
    if (ref.r_0_data != grhsim.r_0_data) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d phase=%s r_0_data ref=0x%016llx grhsim=0x%016llx\n",
                     cycle,
                     phase_name(phase),
                     static_cast<unsigned long long>(ref.r_0_data),
                     static_cast<unsigned long long>(grhsim.r_0_data));
        ok = false;
    }
    if (ref.r_0_async != grhsim.r_0_async) {
        std::fprintf(stderr,
                     "[MISMATCH] cycle=%d phase=%s r_0_async ref=%u grhsim=%u\n",
                     cycle,
                     phase_name(phase),
                     static_cast<unsigned>(ref.r_0_async),
                     static_cast<unsigned>(grhsim.r_0_async));
        ok = false;
    }
    return ok;
}

bool compare_expected(const char *model_name, const Outputs &actual, const Outputs &expected, int cycle, int phase)
{
    bool ok = true;
    if (actual.r_0_data != expected.r_0_data) {
        std::fprintf(stderr,
                     "[EXPECTED-MISMATCH] model=%s cycle=%d phase=%s r_0_data actual=0x%016llx expected=0x%016llx\n",
                     model_name,
                     cycle,
                     phase_name(phase),
                     static_cast<unsigned long long>(actual.r_0_data),
                     static_cast<unsigned long long>(expected.r_0_data));
        ok = false;
    }
    if (actual.r_0_async != expected.r_0_async) {
        std::fprintf(stderr,
                     "[EXPECTED-MISMATCH] model=%s cycle=%d phase=%s r_0_async actual=%u expected=%u\n",
                     model_name,
                     cycle,
                     phase_name(phase),
                     static_cast<unsigned>(actual.r_0_async),
                     static_cast<unsigned>(expected.r_0_async));
        ok = false;
    }
    return ok;
}

void print_trace(int cycle, int phase, bool r_en, std::uint64_t r_idx,
                 bool w_en, std::uint64_t w_idx, std::uint64_t w_data,
                 std::uint64_t w_mask, const Outputs &ref, const Outputs &grhsim)
{
    std::fprintf(stdout,
                 "[TRACE] cycle=%d phase=%s r_en=%u r_idx=0x%016llx w_en=%u w_idx=0x%016llx "
                 "w_data=0x%016llx w_mask=0x%016llx ref_data=0x%016llx ref_async=%u "
                 "grhsim_data=0x%016llx grhsim_async=%u\n",
                 cycle,
                 phase_name(phase),
                 static_cast<unsigned>(r_en),
                 static_cast<unsigned long long>(r_idx),
                 static_cast<unsigned>(w_en),
                 static_cast<unsigned long long>(w_idx),
                 static_cast<unsigned long long>(w_data),
                 static_cast<unsigned long long>(w_mask),
                 static_cast<unsigned long long>(ref.r_0_data),
                 static_cast<unsigned>(ref.r_0_async),
                 static_cast<unsigned long long>(grhsim.r_0_data),
                 static_cast<unsigned>(grhsim.r_0_async));
}

void eval_both(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim)
{
    g_model_index = 0;
    ref.eval();
    g_model_index = 1;
    grhsim.eval();

#if defined(TRACE)
    if (trace_ref) {
        trace_ref->dump(main_time);
    }
#endif
    ++main_time;
}

void phase_eval(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim, bool clk)
{
    ref.clk = clk;
    grhsim.clk = clk;
    eval_both(ref, grhsim);
}

} // namespace

extern "C" long long difftest_ram_read(long long rIdx)
{
    const std::uint64_t idx = static_cast<std::uint64_t>(rIdx);
    auto &mem = g_mem[g_model_index];
    auto it = mem.find(idx);
    std::uint64_t data = (it != mem.end()) ? it->second : init_value(idx);
    std::fprintf(stdout,
                 "[DPIC] model=%d read idx=0x%016llx data=0x%016llx\n",
                 g_model_index,
                 static_cast<unsigned long long>(idx),
                 static_cast<unsigned long long>(data));
    return static_cast<long long>(data);
}

extern "C" void difftest_ram_write(long long index, long long data, long long mask)
{
    const std::uint64_t idx = static_cast<std::uint64_t>(index);
    auto &mem = g_mem[g_model_index];
    std::uint64_t cur = init_value(idx);
    auto it = mem.find(idx);
    if (it != mem.end()) {
        cur = it->second;
    }
    const std::uint64_t d = static_cast<std::uint64_t>(data);
    const std::uint64_t m = static_cast<std::uint64_t>(mask);
    mem[idx] = (cur & ~m) | (d & m);
}

double sc_time_stamp()
{
    return static_cast<double>(main_time);
}

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);

    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

#if defined(TRACE)
    Verilated::traceEverOn(true);
    trace_ref = new VerilatedFstC;
    ref.trace(trace_ref, 99);
    trace_ref->open("case006_ref.fst");
#endif

    drive_inputs(ref, grhsim, false, false, 0, false, 0, 0, 0);

    for (int i = 0; i < 2; ++i) {
        phase_eval(ref, grhsim, false);
        phase_eval(ref, grhsim, true);
        phase_eval(ref, grhsim, false);
    }

    int mismatches = 0;
    auto check_phase = [&](int cycle, int phase, bool r_en, std::uint64_t r_idx,
                           bool w_en, std::uint64_t w_idx, std::uint64_t w_data,
                           std::uint64_t w_mask, const Outputs &expected) {
        const Outputs ref_out = sample_ref(ref);
        const Outputs grhsim_out = sample_grhsim(grhsim);
        print_trace(cycle, phase, r_en, r_idx, w_en, w_idx, w_data, w_mask, ref_out, grhsim_out);
        if (!compare_outputs(ref_out, grhsim_out, cycle, phase)) {
            ++mismatches;
        }
        if (!compare_expected("ref", ref_out, expected, cycle, phase)) {
            ++mismatches;
        }
        if (!compare_expected("grhsim", grhsim_out, expected, cycle, phase)) {
            ++mismatches;
        }
    };

    Outputs expected_out{};
    std::unordered_map<std::uint64_t, std::uint64_t> expected_mem;

    const int cycles = 72;
    for (int cycle = 0; cycle < cycles; ++cycle) {
        const Stimulus stim = build_stimulus(cycle);

        drive_inputs(ref, grhsim, stim.rst_n, stim.r_en, stim.r_idx,
                     stim.w_en, stim.w_idx, stim.w_data, stim.w_mask);

        phase_eval(ref, grhsim, false);
        check_phase(cycle, 0, stim.r_en, stim.r_idx, stim.w_en, stim.w_idx, stim.w_data, stim.w_mask, expected_out);

        if (stim.r_en) {
            expected_out.r_0_data = read_mem_value(expected_mem, stim.r_idx);
        }
        expected_out.r_0_async = false;
        if (stim.w_en) {
            apply_masked_write(expected_mem, stim.w_idx, stim.w_data, stim.w_mask);
        }

        phase_eval(ref, grhsim, true);
        check_phase(cycle, 1, stim.r_en, stim.r_idx, stim.w_en, stim.w_idx, stim.w_data, stim.w_mask, expected_out);

        phase_eval(ref, grhsim, false);
        check_phase(cycle, 2, stim.r_en, stim.r_idx, stim.w_en, stim.w_idx, stim.w_data, stim.w_mask, expected_out);

        if (mismatches >= 16) {
            std::fprintf(stderr, "[FAIL] stopping after %d mismatches\n", mismatches);
            break;
        }
    }

#if defined(TRACE)
    if (trace_ref) {
        trace_ref->close();
        delete trace_ref;
        trace_ref = nullptr;
    }
#endif

    if (mismatches != 0) {
        std::fprintf(stderr, "[FAIL] mismatches=%d\n", mismatches);
        return 1;
    }

    std::printf("[PASS] CASE_006 ref == grhsim\n");
    return 0;
}
