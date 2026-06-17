#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool flush = false;
    bool bpu_valid = false;
    bool bpu_flag = false;
    std::uint8_t bpu_value = 0;
    bool read_ready = false;
    bool write_valid = false;
    std::uint16_t write_vset = 0;
    std::uint8_t write_waymask = 0;
    std::uint64_t write_maybe_rvc = 0;
    std::uint8_t write_meta_codes = 0;
    std::uint64_t write_ptag = 0;
    std::uint8_t write_itlb_pbmt = 0;
    std::uint8_t write_excp_value = 0;
    std::uint64_t write_gpaddr = 0;
    bool write_is_vs_nonleaf = false;
    bool write_ftq_flag = false;
    std::uint8_t write_ftq_value = 0;
    bool update_valid = false;
    std::uint64_t update_blk_paddr = 0;
    std::uint8_t update_vset = 0;
    std::uint8_t update_waymask = 0;
    std::uint32_t update_maybe_rvc = 0;
    bool update_corrupt = false;
};

struct Outputs {
    bool read_valid = false;
    std::uint16_t read_vset = 0;
    std::uint8_t read_waymask = 0;
    std::uint64_t read_maybe_rvc = 0;
    std::uint8_t read_meta_codes = 0;
    std::uint64_t read_ptag = 0;
    std::uint8_t read_itlb_pbmt = 0;
    std::uint8_t read_excp_value = 0;
    std::uint64_t read_gpaddr = 0;
    bool read_is_vs_nonleaf = false;
    bool write_ready = false;
    bool perf_empty = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint32_t xorshift32(std::uint32_t& state)
{
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

std::uint8_t nonzero_waymask(std::uint32_t x)
{
    std::uint8_t v = static_cast<std::uint8_t>(x & 0xFu);
    return v == 0 ? 1 : v;
}

std::uint64_t ptag_from_blk(std::uint64_t blk)
{
    return (blk >> 6) & 0xFFFFFFFFFULL;
}

void fill_write(Stimulus& s, int seq)
{
    const std::uint8_t v0 = static_cast<std::uint8_t>((seq * 7 + 3) & 0xFF);
    const std::uint8_t v1 = static_cast<std::uint8_t>((seq * 11 + 5) & 0xFF);
    const std::uint8_t w0 = static_cast<std::uint8_t>(1u << (seq & 3));
    const std::uint8_t w1 = static_cast<std::uint8_t>(1u << ((seq + 1) & 3));
    const std::uint64_t ptag = (0x123450ULL + static_cast<std::uint64_t>(seq) * 0x1111ULL) & 0xFFFFFFFFFULL;
    s.write_valid = true;
    s.write_vset = static_cast<std::uint16_t>((static_cast<std::uint16_t>(v1) << 8) | v0);
    s.write_waymask = static_cast<std::uint8_t>((w1 << 4) | w0);
    s.write_maybe_rvc =
        (static_cast<std::uint64_t>(0xCAFE0000u ^ (seq * 0x10203u)) << 32)
        | static_cast<std::uint64_t>(0x13570000u ^ (seq * 0x31415u));
    s.write_meta_codes = static_cast<std::uint8_t>(seq & 3);
    s.write_ptag = ptag;
    s.write_itlb_pbmt = static_cast<std::uint8_t>((seq >> 1) & 3);
    s.write_excp_value = 0;
    s.write_gpaddr = (0x100000ULL + static_cast<std::uint64_t>(seq) * 0x101ULL) & 0x7FFFFFFFFFFFFFULL;
    s.write_is_vs_nonleaf = (seq & 4) != 0;
    s.write_ftq_flag = (seq & 0x20) != 0;
    s.write_ftq_value = static_cast<std::uint8_t>(seq & 0x3F);
}

Stimulus build_directed(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 3;
    s.read_ready = true;
    if (!s.rst_n) {
        return s;
    }

    switch (cycle) {
    case 3:
        fill_write(s, 0);
        s.read_ready = false;
        break;
    case 4:
        s.read_ready = true;
        break;
    case 5:
        fill_write(s, 1);
        s.read_ready = false;
        break;
    case 6:
        fill_write(s, 2);
        s.read_ready = true;
        break;
    case 7:
        s.update_valid = true;
        s.update_blk_paddr = (0x123450ULL << 6);
        s.update_vset = 3;
        s.update_waymask = 0x8;
        s.update_maybe_rvc = 0x55AA00F0u;
        break;
    case 8:
        s.read_ready = true;
        break;
    case 9:
        fill_write(s, 3);
        s.write_excp_value = 5;
        s.write_gpaddr = 0x123456789ABULL;
        s.write_is_vs_nonleaf = true;
        s.read_ready = false;
        break;
    case 10:
        s.read_ready = true;
        break;
    case 11:
        fill_write(s, 4);
        s.read_ready = false;
        break;
    case 12:
        s.read_ready = true;
        break;
    case 13:
        s.flush = true;
        break;
    case 14:
        fill_write(s, 5);
        s.read_ready = true;
        break;
    case 15:
        fill_write(s, 6);
        s.read_ready = false;
        break;
    case 16:
        fill_write(s, 7);
        s.bpu_valid = true;
        s.bpu_flag = false;
        s.bpu_value = 5;
        s.read_ready = false;
        break;
    case 17:
        s.read_ready = true;
        break;
    default:
        if (cycle < 80) {
            fill_write(s, cycle - 10);
            s.read_ready = (cycle % 3) != 0;
            if (cycle == 44) {
                s.bpu_valid = true;
                s.bpu_flag = false;
                s.bpu_value = static_cast<std::uint8_t>((cycle - 12) & 0x3F);
            }
            if (cycle == 63) {
                s.update_valid = true;
                s.update_blk_paddr = (0x123450ULL << 6);
                s.update_vset = 3;
                s.update_waymask = 0x2;
                s.update_maybe_rvc = 0xABCDEu;
            }
        }
        break;
    }
    return s;
}

Stimulus build_random(int cycle, std::uint32_t& rng)
{
    Stimulus s;
    s.rst_n = true;
    const std::uint32_t a = xorshift32(rng);
    const std::uint32_t b = xorshift32(rng);
    const std::uint32_t c = xorshift32(rng);
    s.read_ready = (a & 1u) != 0u;
    if ((a & 0x1Fu) != 0x1Fu) {
        fill_write(s, cycle + static_cast<int>(a & 0x7Fu));
        s.write_valid = (a & 2u) != 0u;
        s.write_vset ^= static_cast<std::uint16_t>((b & 0xFF00u) | ((b >> 16) & 0xFFu));
        s.write_waymask = static_cast<std::uint8_t>((nonzero_waymask(b) << 4) | nonzero_waymask(b >> 8));
        s.write_maybe_rvc ^= (static_cast<std::uint64_t>(a) << 32) | c;
        s.write_meta_codes ^= static_cast<std::uint8_t>((b >> 20) & 3u);
        s.write_ptag ^= static_cast<std::uint64_t>(c & 0xFFFFu);
        s.write_itlb_pbmt = static_cast<std::uint8_t>((c >> 3) & 3u);
        s.write_excp_value = ((a & 0x40u) != 0u) ? static_cast<std::uint8_t>((b >> 5) & 7u) : 0;
        s.write_gpaddr = ((static_cast<std::uint64_t>(b) << 23) ^ c) & 0x7FFFFFFFFFFFFFULL;
        s.write_is_vs_nonleaf = (c & 0x80u) != 0u;
        s.write_ftq_flag = (a & 0x100u) != 0u;
        s.write_ftq_value = static_cast<std::uint8_t>((a >> 9) & 0x3Fu);
    }
    s.update_valid = (b & 0x8u) != 0u;
    s.update_blk_paddr = ((static_cast<std::uint64_t>(s.write_ptag) ^ (b & 0xFFFFu)) << 6) & 0x3FFFFFFFFFFULL;
    if ((cycle & 7) == 0) {
        s.update_blk_paddr = ptag_from_blk(s.update_blk_paddr) << 6;
    }
    s.update_vset = static_cast<std::uint8_t>(a >> 16);
    s.update_waymask = nonzero_waymask(c >> 8);
    s.update_maybe_rvc = b ^ (c << 1);
    s.update_corrupt = (c & 0x400u) != 0u;
    s.bpu_valid = (a & 0x4000u) != 0u;
    s.bpu_flag = (b & 0x8000u) != 0u;
    s.bpu_value = static_cast<std::uint8_t>((b >> 16) & 0x3Fu);
    s.flush = (a & 0x10000u) != 0u;
    return s;
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
#define SET_FIELD(name, value) \
    do {                       \
        ref.name = value;      \
        grhsim.name = value;   \
    } while (false)
    SET_FIELD(clk, clk);
    SET_FIELD(rst_n, s.rst_n);
    SET_FIELD(flush, s.flush);
    SET_FIELD(bpu_valid, s.bpu_valid);
    SET_FIELD(bpu_flag, s.bpu_flag);
    SET_FIELD(bpu_value, s.bpu_value);
    SET_FIELD(read_ready, s.read_ready);
    SET_FIELD(write_valid, s.write_valid);
    SET_FIELD(write_vset, s.write_vset);
    SET_FIELD(write_waymask, s.write_waymask);
    SET_FIELD(write_maybe_rvc, s.write_maybe_rvc);
    SET_FIELD(write_meta_codes, s.write_meta_codes);
    SET_FIELD(write_ptag, s.write_ptag);
    SET_FIELD(write_itlb_pbmt, s.write_itlb_pbmt);
    SET_FIELD(write_excp_value, s.write_excp_value);
    SET_FIELD(write_gpaddr, s.write_gpaddr);
    SET_FIELD(write_is_vs_nonleaf, s.write_is_vs_nonleaf);
    SET_FIELD(write_ftq_flag, s.write_ftq_flag);
    SET_FIELD(write_ftq_value, s.write_ftq_value);
    SET_FIELD(update_valid, s.update_valid);
    SET_FIELD(update_blk_paddr, s.update_blk_paddr);
    SET_FIELD(update_vset, s.update_vset);
    SET_FIELD(update_waymask, s.update_waymask);
    SET_FIELD(update_maybe_rvc, s.update_maybe_rvc);
    SET_FIELD(update_corrupt, s.update_corrupt);
#undef SET_FIELD
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<bool>(ref.read_valid),
        static_cast<std::uint16_t>(ref.read_vset),
        static_cast<std::uint8_t>(ref.read_waymask),
        static_cast<std::uint64_t>(ref.read_maybe_rvc),
        static_cast<std::uint8_t>(ref.read_meta_codes),
        static_cast<std::uint64_t>(ref.read_ptag),
        static_cast<std::uint8_t>(ref.read_itlb_pbmt),
        static_cast<std::uint8_t>(ref.read_excp_value),
        static_cast<std::uint64_t>(ref.read_gpaddr),
        static_cast<bool>(ref.read_is_vs_nonleaf),
        static_cast<bool>(ref.write_ready),
        static_cast<bool>(ref.perf_empty),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<bool>(grhsim.read_valid),
        static_cast<std::uint16_t>(grhsim.read_vset),
        static_cast<std::uint8_t>(grhsim.read_waymask),
        static_cast<std::uint64_t>(grhsim.read_maybe_rvc),
        static_cast<std::uint8_t>(grhsim.read_meta_codes),
        static_cast<std::uint64_t>(grhsim.read_ptag),
        static_cast<std::uint8_t>(grhsim.read_itlb_pbmt),
        static_cast<std::uint8_t>(grhsim.read_excp_value),
        static_cast<std::uint64_t>(grhsim.read_gpaddr),
        static_cast<bool>(grhsim.read_is_vs_nonleaf),
        static_cast<bool>(grhsim.write_ready),
        static_cast<bool>(grhsim.perf_empty),
    };
}

bool compare_u64(const char* name, std::uint64_t ref, std::uint64_t grhsim, int cycle, const char* phase)
{
    if (ref == grhsim) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s %s ref=0x%llx grhsim=0x%llx\n",
                 cycle,
                 phase,
                 name,
                 static_cast<unsigned long long>(ref),
                 static_cast<unsigned long long>(grhsim));
    return false;
}

bool compare(const Outputs& ref, const Outputs& grhsim, int cycle, const char* phase)
{
    bool ok = true;
    ok &= compare_u64("read_valid", ref.read_valid, grhsim.read_valid, cycle, phase);
    ok &= compare_u64("write_ready", ref.write_ready, grhsim.write_ready, cycle, phase);
    ok &= compare_u64("perf_empty", ref.perf_empty, grhsim.perf_empty, cycle, phase);
    if (ref.read_valid || grhsim.read_valid) {
        ok &= compare_u64("read_vset", ref.read_vset, grhsim.read_vset, cycle, phase);
        ok &= compare_u64("read_waymask", ref.read_waymask, grhsim.read_waymask, cycle, phase);
        ok &= compare_u64("read_maybe_rvc", ref.read_maybe_rvc, grhsim.read_maybe_rvc, cycle, phase);
        ok &= compare_u64("read_meta_codes", ref.read_meta_codes, grhsim.read_meta_codes, cycle, phase);
        ok &= compare_u64("read_ptag", ref.read_ptag, grhsim.read_ptag, cycle, phase);
        ok &= compare_u64("read_itlb_pbmt", ref.read_itlb_pbmt, grhsim.read_itlb_pbmt, cycle, phase);
        ok &= compare_u64("read_excp_value", ref.read_excp_value, grhsim.read_excp_value, cycle, phase);
        ok &= compare_u64("read_gpaddr", ref.read_gpaddr, grhsim.read_gpaddr, cycle, phase);
        ok &= compare_u64("read_is_vs_nonleaf", ref.read_is_vs_nonleaf, grhsim.read_is_vs_nonleaf, cycle, phase);
    }
    return ok;
}

void eval_both(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    ref.eval();
    grhsim.eval();
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
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

bool run_directed(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    for (int cycle = 0; cycle < 160; ++cycle) {
        if (!step(ref, grhsim, build_directed(cycle), cycle)) {
            return false;
        }
    }
    return true;
}

bool run_random(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    std::uint32_t rng = 0x2468ACE1u;
    for (int cycle = 160; cycle < 4096; ++cycle) {
        if (!step(ref, grhsim, build_random(cycle, rng), cycle)) {
            return false;
        }
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

    if (!run_directed(ref, grhsim) || !run_random(ref, grhsim)) {
        return 1;
    }

    std::printf("[PASS] CASE_024 ICacheWayLookup ref == grhsim\n");
    return 0;
}
