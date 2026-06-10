#include <cstdint>
#include <cstdio>
#include <deque>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

enum class EvalModel {
    Ref,
    GrhSIM,
};

struct Entry {
    std::uint16_t vset = 0;
    std::uint8_t waymask = 0x11;
    std::uint64_t maybe_rvc = 0;
    std::uint8_t meta_codes = 0;
    std::uint64_t ptag = 0;
    std::uint8_t itlb_pbmt = 0;
    std::uint8_t excp_value = 0;
    std::uint64_t gpaddr = 0;
    bool is_vs_nonleaf = false;
    bool ftq_flag = false;
    std::uint8_t ftq_value = 0;
};

struct Stimulus {
    bool rst_n = false;
    std::uint8_t hartId = 0x2a;
    bool data_ready = true;
    bool miss_ready = true;
    bool miss_resp_valid = false;
    std::uint64_t miss_resp_blk_paddr = 0;
    std::uint64_t miss_resp_data[8]{};
    std::uint32_t miss_resp_maybe_rvc = 0;
    bool miss_resp_corrupt = false;
    bool miss_resp_denied = false;
    bool ecc_enable = false;
    bool req_valid = false;
    std::uint64_t req_start_vaddr = 0;
    std::uint64_t req_next_vaddr = 0;
    bool req_ftq_flag = false;
    std::uint8_t req_ftq_value = 0;
    std::uint8_t req_taken_cfi_offset = 0;
    bool req_backend_exception = false;
    bool flush = false;
    bool bpu_valid = false;
    bool bpu_flag = false;
    std::uint8_t bpu_value = 0;
    bool pmp_instr = true;
    bool pmp_mmio = false;
    bool resp_stall = false;
    bool write_valid = false;
    Entry write_entry;
    bool update_valid = false;
    std::uint64_t update_blk_paddr = 0;
    std::uint8_t update_vset = 0;
    std::uint8_t update_waymask = 0;
    std::uint32_t update_maybe_rvc = 0;
    bool update_corrupt = false;
};

struct Outputs {
    bool data_req_valid = false;
    std::uint16_t data_req_vset = 0;
    bool data_req_doubleline = false;
    std::uint8_t data_req_waymask = 0;
    std::uint8_t data_req_blk_offset = 0;
    std::uint8_t data_req_blk_end_offset = 0;
    bool touch0_valid = false;
    std::uint8_t touch0_vset = 0;
    std::uint8_t touch0_way = 0;
    bool touch1_valid = false;
    std::uint8_t touch1_vset = 0;
    std::uint8_t touch1_way = 0;
    bool way_read_ready = false;
    bool way_read_valid = false;
    bool way_write_ready = false;
    bool way_perf_empty = false;
    bool miss_req_valid = false;
    std::uint64_t miss_req_blk_paddr = 0;
    std::uint8_t miss_req_vset = 0;
    bool req_ready = false;
    std::uint64_t pmp_req_addr = 0;
    bool resp_valid = false;
    bool resp_doubleline = false;
    std::uint64_t resp_vaddr = 0;
    std::uint64_t resp_data[8]{};
    std::uint32_t resp_maybe_rvc = 0;
    std::uint64_t resp_paddr = 0;
    std::uint8_t resp_exception = 0;
    bool resp_pmp_mmio = false;
    std::uint8_t resp_itlb_pbmt = 0;
    bool resp_backend_exception = false;
    std::uint64_t resp_gpaddr = 0;
    bool resp_is_vs_nonleaf = false;
    bool error0_valid = false;
    std::uint64_t error0_paddr = 0;
    bool error0_report = false;
    bool error1_valid = false;
    std::uint64_t error1_paddr = 0;
    bool error1_report = false;
    std::uint8_t perf_raw_hits = 0;
    bool perf_pending_miss = false;
};

struct StepResult {
    bool ok = false;
    Outputs low_ref;
};

static vluint64_t main_time = 0;
static EvalModel active_model = EvalModel::Ref;
static int ref_assert_count = 0;
static int grhsim_assert_count = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint32_t xorshift32(std::uint32_t& state)
{
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

std::uint8_t parity64(std::uint64_t value)
{
    value ^= value >> 32;
    value ^= value >> 16;
    value ^= value >> 8;
    value ^= value >> 4;
    value &= 0xFu;
    return static_cast<std::uint8_t>((0x6996u >> value) & 1u);
}

std::uint64_t mask_bits(std::uint64_t value, unsigned width)
{
    return width >= 64 ? value : (value & ((1ULL << width) - 1ULL));
}

Entry make_entry(int seq)
{
    Entry e;
    const std::uint8_t v0 = static_cast<std::uint8_t>((seq * 17 + 0x35) & 0xFF);
    const std::uint8_t v1 = static_cast<std::uint8_t>((v0 + ((seq & 3) == 0 ? 1 : 0)) & 0xFF);
    e.vset = static_cast<std::uint16_t>((static_cast<std::uint16_t>(v1) << 8) | v0);
    e.waymask = static_cast<std::uint8_t>((1u << ((seq + 1) & 3)) << 4 | (1u << (seq & 3)));
    e.maybe_rvc =
        (static_cast<std::uint64_t>(0x31410000u ^ (seq * 0x13579u)) << 32)
        | static_cast<std::uint64_t>(0x27180000u ^ (seq * 0x2468Bu));
    e.ptag = static_cast<std::uint64_t>(0x10000u + ((seq * 19 + 0x1234) & 0xFFFFu)) & 0xFFFFFFFFFULL;
    e.meta_codes = static_cast<std::uint8_t>(
        (parity64((e.ptag << 32) ^ (e.maybe_rvc & 0xFFFFFFFFULL)) |
         (parity64((e.ptag << 32) ^ (e.maybe_rvc >> 32)) << 1)) &
        3u);
    e.itlb_pbmt = static_cast<std::uint8_t>((seq >> 2) & 3);
    e.excp_value = 0;
    e.gpaddr = mask_bits(0x1234000000ULL + static_cast<std::uint64_t>(seq) * 0x41ULL, 55);
    e.is_vs_nonleaf = (seq & 0x20) != 0;
    e.ftq_flag = (seq & 0x40) != 0;
    e.ftq_value = static_cast<std::uint8_t>(seq & 0x3F);
    return e;
}

void set_req_from_entry(Stimulus& s, const Entry& e, int seq)
{
    const std::uint8_t v0 = static_cast<std::uint8_t>(e.vset & 0xFFu);
    const std::uint8_t v1 = static_cast<std::uint8_t>((e.vset >> 8) & 0xFFu);
    const std::uint8_t offset = static_cast<std::uint8_t>((seq * 5 + 3) & 0x1Fu);
    s.req_start_vaddr = mask_bits(0x80000000ULL | (static_cast<std::uint64_t>(v0) << 5) | offset, 49);
    s.req_next_vaddr = mask_bits(0x80010000ULL | (static_cast<std::uint64_t>(v1) << 5), 49);
    s.req_taken_cfi_offset = static_cast<std::uint8_t>((seq * 3 + 7) & 0x1F);
    s.req_ftq_flag = e.ftq_flag;
    s.req_ftq_value = e.ftq_value;
}

void fill_common(Stimulus& s, int cycle, const Entry& req_entry)
{
    s.rst_n = cycle >= 3;
    s.hartId = static_cast<std::uint8_t>((0x15u + cycle) & 0x3Fu);
    s.data_ready = true;
    s.miss_ready = true;
    s.ecc_enable = false;
    s.req_valid = s.rst_n;
    s.req_backend_exception = false;
    s.flush = false;
    s.bpu_valid = false;
    s.pmp_instr = true;
    s.pmp_mmio = false;
    s.resp_stall = false;
    set_req_from_entry(s, req_entry, cycle);
    s.miss_resp_blk_paddr = (req_entry.ptag << 6) | ((s.req_start_vaddr >> 5) & 0x3FULL);
    s.miss_resp_maybe_rvc = static_cast<std::uint32_t>(req_entry.maybe_rvc);
    for (int i = 0; i < 8; ++i) {
        s.miss_resp_data[i] =
            (0xC0FFEE0000000000ULL ^ (static_cast<std::uint64_t>(cycle) << 24))
            + static_cast<std::uint64_t>(i) * 0x0101010101010101ULL;
    }
}

Stimulus build_stimulus(int cycle, const std::deque<Entry>& pending)
{
    const bool drain = !pending.empty();
    const Entry req_entry = drain ? pending.front() : make_entry(cycle);
    Stimulus s;
    fill_common(s, cycle, req_entry);
    if (!s.rst_n) {
        s.req_valid = false;
        s.write_valid = false;
        return s;
    }

    if (drain) {
        s.write_valid = false;
        s.data_ready = true;
        s.resp_stall = false;
    }
    else {
        s.write_valid = true;
        s.write_entry = req_entry;
        if ((cycle % 17) == 5) {
            s.data_ready = false;
        }
        if ((cycle % 19) == 9) {
            s.resp_stall = true;
        }
        if ((cycle % 29) == 11) {
            s.req_valid = false;
        }
    }

    if ((cycle % 31) == 13) {
        s.update_valid = true;
        s.update_blk_paddr = (req_entry.ptag << 6) | ((s.req_start_vaddr >> 5) & 0x3FULL);
        s.update_vset = static_cast<std::uint8_t>(req_entry.vset & 0xFFu);
        s.update_waymask = static_cast<std::uint8_t>((req_entry.waymask ^ 0x5u) & 0xFu);
        if (s.update_waymask == 0) {
            s.update_waymask = 1;
        }
        s.update_maybe_rvc = static_cast<std::uint32_t>(req_entry.maybe_rvc ^ 0x00FF00FFu);
    }
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
    SET_FIELD(hartId, s.hartId);
    SET_FIELD(data_ready, s.data_ready);
    SET_FIELD(miss_ready, s.miss_ready);
    SET_FIELD(miss_resp_valid, s.miss_resp_valid);
    SET_FIELD(miss_resp_blk_paddr, s.miss_resp_blk_paddr);
    SET_FIELD(miss_resp_data0, s.miss_resp_data[0]);
    SET_FIELD(miss_resp_data1, s.miss_resp_data[1]);
    SET_FIELD(miss_resp_data2, s.miss_resp_data[2]);
    SET_FIELD(miss_resp_data3, s.miss_resp_data[3]);
    SET_FIELD(miss_resp_data4, s.miss_resp_data[4]);
    SET_FIELD(miss_resp_data5, s.miss_resp_data[5]);
    SET_FIELD(miss_resp_data6, s.miss_resp_data[6]);
    SET_FIELD(miss_resp_data7, s.miss_resp_data[7]);
    SET_FIELD(miss_resp_maybe_rvc, s.miss_resp_maybe_rvc);
    SET_FIELD(miss_resp_corrupt, s.miss_resp_corrupt);
    SET_FIELD(miss_resp_denied, s.miss_resp_denied);
    SET_FIELD(ecc_enable, s.ecc_enable);
    SET_FIELD(req_valid, s.req_valid);
    SET_FIELD(req_start_vaddr, s.req_start_vaddr);
    SET_FIELD(req_next_vaddr, s.req_next_vaddr);
    SET_FIELD(req_ftq_flag, s.req_ftq_flag);
    SET_FIELD(req_ftq_value, s.req_ftq_value);
    SET_FIELD(req_taken_cfi_offset, s.req_taken_cfi_offset);
    SET_FIELD(req_backend_exception, s.req_backend_exception);
    SET_FIELD(flush, s.flush);
    SET_FIELD(bpu_valid, s.bpu_valid);
    SET_FIELD(bpu_flag, s.bpu_flag);
    SET_FIELD(bpu_value, s.bpu_value);
    SET_FIELD(pmp_instr, s.pmp_instr);
    SET_FIELD(pmp_mmio, s.pmp_mmio);
    SET_FIELD(resp_stall, s.resp_stall);
    SET_FIELD(write_valid, s.write_valid);
    SET_FIELD(write_vset, s.write_entry.vset);
    SET_FIELD(write_waymask, s.write_entry.waymask);
    SET_FIELD(write_maybe_rvc, s.write_entry.maybe_rvc);
    SET_FIELD(write_meta_codes, s.write_entry.meta_codes);
    SET_FIELD(write_ptag, s.write_entry.ptag);
    SET_FIELD(write_itlb_pbmt, s.write_entry.itlb_pbmt);
    SET_FIELD(write_excp_value, s.write_entry.excp_value);
    SET_FIELD(write_gpaddr, s.write_entry.gpaddr);
    SET_FIELD(write_is_vs_nonleaf, s.write_entry.is_vs_nonleaf);
    SET_FIELD(write_ftq_flag, s.write_entry.ftq_flag);
    SET_FIELD(write_ftq_value, s.write_entry.ftq_value);
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
    Outputs o;
    o.data_req_valid = static_cast<bool>(ref.data_req_valid);
    o.data_req_vset = static_cast<std::uint16_t>(ref.data_req_vset);
    o.data_req_doubleline = static_cast<bool>(ref.data_req_doubleline);
    o.data_req_waymask = static_cast<std::uint8_t>(ref.data_req_waymask);
    o.data_req_blk_offset = static_cast<std::uint8_t>(ref.data_req_blk_offset);
    o.data_req_blk_end_offset = static_cast<std::uint8_t>(ref.data_req_blk_end_offset);
    o.touch0_valid = static_cast<bool>(ref.touch0_valid);
    o.touch0_vset = static_cast<std::uint8_t>(ref.touch0_vset);
    o.touch0_way = static_cast<std::uint8_t>(ref.touch0_way);
    o.touch1_valid = static_cast<bool>(ref.touch1_valid);
    o.touch1_vset = static_cast<std::uint8_t>(ref.touch1_vset);
    o.touch1_way = static_cast<std::uint8_t>(ref.touch1_way);
    o.way_read_ready = static_cast<bool>(ref.way_read_ready);
    o.way_read_valid = static_cast<bool>(ref.way_read_valid);
    o.way_write_ready = static_cast<bool>(ref.way_write_ready);
    o.way_perf_empty = static_cast<bool>(ref.way_perf_empty);
    o.miss_req_valid = static_cast<bool>(ref.miss_req_valid);
    o.miss_req_blk_paddr = static_cast<std::uint64_t>(ref.miss_req_blk_paddr);
    o.miss_req_vset = static_cast<std::uint8_t>(ref.miss_req_vset);
    o.req_ready = static_cast<bool>(ref.req_ready);
    o.pmp_req_addr = static_cast<std::uint64_t>(ref.pmp_req_addr);
    o.resp_valid = static_cast<bool>(ref.resp_valid);
    o.resp_doubleline = static_cast<bool>(ref.resp_doubleline);
    o.resp_vaddr = static_cast<std::uint64_t>(ref.resp_vaddr);
    o.resp_data[0] = static_cast<std::uint64_t>(ref.resp_data0);
    o.resp_data[1] = static_cast<std::uint64_t>(ref.resp_data1);
    o.resp_data[2] = static_cast<std::uint64_t>(ref.resp_data2);
    o.resp_data[3] = static_cast<std::uint64_t>(ref.resp_data3);
    o.resp_data[4] = static_cast<std::uint64_t>(ref.resp_data4);
    o.resp_data[5] = static_cast<std::uint64_t>(ref.resp_data5);
    o.resp_data[6] = static_cast<std::uint64_t>(ref.resp_data6);
    o.resp_data[7] = static_cast<std::uint64_t>(ref.resp_data7);
    o.resp_maybe_rvc = static_cast<std::uint32_t>(ref.resp_maybe_rvc);
    o.resp_paddr = static_cast<std::uint64_t>(ref.resp_paddr);
    o.resp_exception = static_cast<std::uint8_t>(ref.resp_exception);
    o.resp_pmp_mmio = static_cast<bool>(ref.resp_pmp_mmio);
    o.resp_itlb_pbmt = static_cast<std::uint8_t>(ref.resp_itlb_pbmt);
    o.resp_backend_exception = static_cast<bool>(ref.resp_backend_exception);
    o.resp_gpaddr = static_cast<std::uint64_t>(ref.resp_gpaddr);
    o.resp_is_vs_nonleaf = static_cast<bool>(ref.resp_is_vs_nonleaf);
    o.error0_valid = static_cast<bool>(ref.error0_valid);
    o.error0_paddr = static_cast<std::uint64_t>(ref.error0_paddr);
    o.error0_report = static_cast<bool>(ref.error0_report);
    o.error1_valid = static_cast<bool>(ref.error1_valid);
    o.error1_paddr = static_cast<std::uint64_t>(ref.error1_paddr);
    o.error1_report = static_cast<bool>(ref.error1_report);
    o.perf_raw_hits = static_cast<std::uint8_t>(ref.perf_raw_hits);
    o.perf_pending_miss = static_cast<bool>(ref.perf_pending_miss);
    return o;
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    Outputs o;
    o.data_req_valid = static_cast<bool>(grhsim.data_req_valid);
    o.data_req_vset = static_cast<std::uint16_t>(grhsim.data_req_vset);
    o.data_req_doubleline = static_cast<bool>(grhsim.data_req_doubleline);
    o.data_req_waymask = static_cast<std::uint8_t>(grhsim.data_req_waymask);
    o.data_req_blk_offset = static_cast<std::uint8_t>(grhsim.data_req_blk_offset);
    o.data_req_blk_end_offset = static_cast<std::uint8_t>(grhsim.data_req_blk_end_offset);
    o.touch0_valid = static_cast<bool>(grhsim.touch0_valid);
    o.touch0_vset = static_cast<std::uint8_t>(grhsim.touch0_vset);
    o.touch0_way = static_cast<std::uint8_t>(grhsim.touch0_way);
    o.touch1_valid = static_cast<bool>(grhsim.touch1_valid);
    o.touch1_vset = static_cast<std::uint8_t>(grhsim.touch1_vset);
    o.touch1_way = static_cast<std::uint8_t>(grhsim.touch1_way);
    o.way_read_ready = static_cast<bool>(grhsim.way_read_ready);
    o.way_read_valid = static_cast<bool>(grhsim.way_read_valid);
    o.way_write_ready = static_cast<bool>(grhsim.way_write_ready);
    o.way_perf_empty = static_cast<bool>(grhsim.way_perf_empty);
    o.miss_req_valid = static_cast<bool>(grhsim.miss_req_valid);
    o.miss_req_blk_paddr = static_cast<std::uint64_t>(grhsim.miss_req_blk_paddr);
    o.miss_req_vset = static_cast<std::uint8_t>(grhsim.miss_req_vset);
    o.req_ready = static_cast<bool>(grhsim.req_ready);
    o.pmp_req_addr = static_cast<std::uint64_t>(grhsim.pmp_req_addr);
    o.resp_valid = static_cast<bool>(grhsim.resp_valid);
    o.resp_doubleline = static_cast<bool>(grhsim.resp_doubleline);
    o.resp_vaddr = static_cast<std::uint64_t>(grhsim.resp_vaddr);
    o.resp_data[0] = static_cast<std::uint64_t>(grhsim.resp_data0);
    o.resp_data[1] = static_cast<std::uint64_t>(grhsim.resp_data1);
    o.resp_data[2] = static_cast<std::uint64_t>(grhsim.resp_data2);
    o.resp_data[3] = static_cast<std::uint64_t>(grhsim.resp_data3);
    o.resp_data[4] = static_cast<std::uint64_t>(grhsim.resp_data4);
    o.resp_data[5] = static_cast<std::uint64_t>(grhsim.resp_data5);
    o.resp_data[6] = static_cast<std::uint64_t>(grhsim.resp_data6);
    o.resp_data[7] = static_cast<std::uint64_t>(grhsim.resp_data7);
    o.resp_maybe_rvc = static_cast<std::uint32_t>(grhsim.resp_maybe_rvc);
    o.resp_paddr = static_cast<std::uint64_t>(grhsim.resp_paddr);
    o.resp_exception = static_cast<std::uint8_t>(grhsim.resp_exception);
    o.resp_pmp_mmio = static_cast<bool>(grhsim.resp_pmp_mmio);
    o.resp_itlb_pbmt = static_cast<std::uint8_t>(grhsim.resp_itlb_pbmt);
    o.resp_backend_exception = static_cast<bool>(grhsim.resp_backend_exception);
    o.resp_gpaddr = static_cast<std::uint64_t>(grhsim.resp_gpaddr);
    o.resp_is_vs_nonleaf = static_cast<bool>(grhsim.resp_is_vs_nonleaf);
    o.error0_valid = static_cast<bool>(grhsim.error0_valid);
    o.error0_paddr = static_cast<std::uint64_t>(grhsim.error0_paddr);
    o.error0_report = static_cast<bool>(grhsim.error0_report);
    o.error1_valid = static_cast<bool>(grhsim.error1_valid);
    o.error1_paddr = static_cast<std::uint64_t>(grhsim.error1_paddr);
    o.error1_report = static_cast<bool>(grhsim.error1_report);
    o.perf_raw_hits = static_cast<std::uint8_t>(grhsim.perf_raw_hits);
    o.perf_pending_miss = static_cast<bool>(grhsim.perf_pending_miss);
    return o;
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
    ok &= compare_u64("way_read_ready", ref.way_read_ready, grhsim.way_read_ready, cycle, phase);
    ok &= compare_u64("way_read_valid", ref.way_read_valid, grhsim.way_read_valid, cycle, phase);
    ok &= compare_u64("way_write_ready", ref.way_write_ready, grhsim.way_write_ready, cycle, phase);
    ok &= compare_u64("way_perf_empty", ref.way_perf_empty, grhsim.way_perf_empty, cycle, phase);
    ok &= compare_u64("req_ready", ref.req_ready, grhsim.req_ready, cycle, phase);
    ok &= compare_u64("data_req_valid", ref.data_req_valid, grhsim.data_req_valid, cycle, phase);
    ok &= compare_u64("data_req_vset", ref.data_req_vset, grhsim.data_req_vset, cycle, phase);
    ok &= compare_u64("data_req_doubleline", ref.data_req_doubleline, grhsim.data_req_doubleline, cycle, phase);
    ok &= compare_u64("data_req_waymask", ref.data_req_waymask, grhsim.data_req_waymask, cycle, phase);
    ok &= compare_u64("data_req_blk_offset", ref.data_req_blk_offset, grhsim.data_req_blk_offset, cycle, phase);
    ok &= compare_u64("data_req_blk_end_offset", ref.data_req_blk_end_offset, grhsim.data_req_blk_end_offset, cycle, phase);
    ok &= compare_u64("touch0_valid", ref.touch0_valid, grhsim.touch0_valid, cycle, phase);
    if (ref.touch0_valid || grhsim.touch0_valid) {
        ok &= compare_u64("touch0_vset", ref.touch0_vset, grhsim.touch0_vset, cycle, phase);
        ok &= compare_u64("touch0_way", ref.touch0_way, grhsim.touch0_way, cycle, phase);
    }
    ok &= compare_u64("touch1_valid", ref.touch1_valid, grhsim.touch1_valid, cycle, phase);
    if (ref.touch1_valid || grhsim.touch1_valid) {
        ok &= compare_u64("touch1_vset", ref.touch1_vset, grhsim.touch1_vset, cycle, phase);
        ok &= compare_u64("touch1_way", ref.touch1_way, grhsim.touch1_way, cycle, phase);
    }
    ok &= compare_u64("miss_req_valid", ref.miss_req_valid, grhsim.miss_req_valid, cycle, phase);
    if (ref.miss_req_valid || grhsim.miss_req_valid) {
        ok &= compare_u64("miss_req_blk_paddr", ref.miss_req_blk_paddr, grhsim.miss_req_blk_paddr, cycle, phase);
        ok &= compare_u64("miss_req_vset", ref.miss_req_vset, grhsim.miss_req_vset, cycle, phase);
    }
    ok &= compare_u64("pmp_req_addr", ref.pmp_req_addr, grhsim.pmp_req_addr, cycle, phase);
    ok &= compare_u64("resp_valid", ref.resp_valid, grhsim.resp_valid, cycle, phase);
    if (ref.resp_valid || grhsim.resp_valid) {
        ok &= compare_u64("resp_doubleline", ref.resp_doubleline, grhsim.resp_doubleline, cycle, phase);
        ok &= compare_u64("resp_vaddr", ref.resp_vaddr, grhsim.resp_vaddr, cycle, phase);
        ok &= compare_u64("resp_maybe_rvc", ref.resp_maybe_rvc, grhsim.resp_maybe_rvc, cycle, phase);
        ok &= compare_u64("resp_paddr", ref.resp_paddr, grhsim.resp_paddr, cycle, phase);
        ok &= compare_u64("resp_exception", ref.resp_exception, grhsim.resp_exception, cycle, phase);
        ok &= compare_u64("resp_pmp_mmio", ref.resp_pmp_mmio, grhsim.resp_pmp_mmio, cycle, phase);
        ok &= compare_u64("resp_itlb_pbmt", ref.resp_itlb_pbmt, grhsim.resp_itlb_pbmt, cycle, phase);
        ok &= compare_u64("resp_backend_exception", ref.resp_backend_exception, grhsim.resp_backend_exception, cycle, phase);
        ok &= compare_u64("resp_gpaddr", ref.resp_gpaddr, grhsim.resp_gpaddr, cycle, phase);
        ok &= compare_u64("resp_is_vs_nonleaf", ref.resp_is_vs_nonleaf, grhsim.resp_is_vs_nonleaf, cycle, phase);
        for (int i = 0; i < 8; ++i) {
            char name[32];
            std::snprintf(name, sizeof(name), "resp_data%d", i);
            ok &= compare_u64(name, ref.resp_data[i], grhsim.resp_data[i], cycle, phase);
        }
    }
    ok &= compare_u64("error0_valid", ref.error0_valid, grhsim.error0_valid, cycle, phase);
    ok &= compare_u64("error1_valid", ref.error1_valid, grhsim.error1_valid, cycle, phase);
    ok &= compare_u64("perf_raw_hits", ref.perf_raw_hits, grhsim.perf_raw_hits, cycle, phase);
    ok &= compare_u64("perf_pending_miss", ref.perf_pending_miss, grhsim.perf_pending_miss, cycle, phase);
    return ok;
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

StepResult step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
    StepResult result;
    drive(ref, grhsim, false, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    result.low_ref = sample_ref(ref);
    if (!compare(result.low_ref, sample_grhsim(grhsim), cycle, "low") ||
        !check_asserts(cycle, "low")) {
        return result;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "high") ||
        !check_asserts(cycle, "high")) {
        return result;
    }
    ++main_time;
    result.ok = true;
    return result;
}

void update_pending(std::deque<Entry>& pending, const Stimulus& s, const Outputs& low)
{
    if (!s.rst_n || s.flush) {
        pending.clear();
        return;
    }
    const bool was_empty = pending.empty();
    const bool read_fire = low.way_read_ready && low.way_read_valid;
    const bool write_fire = s.write_valid && low.way_write_ready;
    if (read_fire && !was_empty) {
        pending.pop_front();
    }
    if (write_fire && !(read_fire && was_empty)) {
        pending.push_back(s.write_entry);
    }
}

bool run_cycles(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, int begin, int end)
{
    std::deque<Entry> pending;
    for (int cycle = begin; cycle < end; ++cycle) {
        Stimulus s = build_stimulus(cycle, pending);
        StepResult r = step(ref, grhsim, s, cycle);
        if (!r.ok) {
            return false;
        }
        update_pending(pending, s, r.low_ref);
    }
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

    if (!run_cycles(ref, grhsim, 0, 4096)) {
        return 1;
    }
    if (ref_assert_count != 0 || grhsim_assert_count != 0) {
        std::fprintf(stderr,
                     "[ASSERT-UNEXPECTED] ref_asserts=%d grhsim_asserts=%d\n",
                     ref_assert_count,
                     grhsim_assert_count);
        return 1;
    }

    std::printf("[PASS] CASE_018 ICacheMainPipe+ICacheWayLookup ref == grhsim\n");
    return 0;
}
