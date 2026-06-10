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
    std::uint8_t hartId = 0x2a;
    bool data_ready = true;
    bool way_valid = true;
    std::uint16_t way_vset = 0;
    std::uint8_t way_waymask = 0x11;
    std::uint64_t way_maybe_rvc = 0;
    std::uint8_t way_meta_codes = 0;
    std::uint64_t way_ptag = 0x12345;
    std::uint8_t way_itlb_pbmt = 0;
    std::uint8_t way_excp_value = 0;
    std::uint64_t way_gpaddr = 0;
    bool way_is_vs_nonleaf = false;
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
    bool way_ready = false;
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

std::uint8_t nonzero_waymask(std::uint32_t x)
{
    const std::uint8_t value = static_cast<std::uint8_t>(x & 0xFu);
    return value == 0 ? 1 : value;
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
    if (width >= 64) {
        return value;
    }
    return value & ((1ULL << width) - 1ULL);
}

std::uint64_t make_start_vaddr(int cycle, std::uint32_t salt)
{
    const std::uint64_t base = 0x80000000ULL + static_cast<std::uint64_t>((cycle * 64) & 0x1FFFF);
    const std::uint64_t set = static_cast<std::uint64_t>((cycle * 17 + salt) & 0xFFu) << 5;
    const std::uint64_t offset = static_cast<std::uint64_t>((salt >> 8) & 0x1Fu);
    return mask_bits((base & ~0x1FE0ULL) | set | offset, 49);
}

void fill_common(Stimulus& s, int cycle, std::uint32_t salt)
{
    s.rst_n = cycle >= 3;
    s.hartId = static_cast<std::uint8_t>((0x15u + cycle) & 0x3Fu);
    s.req_valid = s.rst_n;
    s.req_start_vaddr = make_start_vaddr(cycle, salt);
    const std::uint8_t taken = static_cast<std::uint8_t>((cycle * 3 + (salt & 7u)) & 0x1Fu);
    s.req_taken_cfi_offset = taken;
    const std::uint64_t end_addr = s.req_start_vaddr + (static_cast<std::uint64_t>(taken) << 1);
    s.req_next_vaddr = mask_bits((end_addr & ~0x3FULL) + 0x40ULL, 49);
    s.req_ftq_flag = ((cycle + static_cast<int>(salt)) & 0x40) != 0;
    s.req_ftq_value = static_cast<std::uint8_t>(cycle & 0x3F);
    s.req_backend_exception = ((salt >> 11) & 1u) != 0u;
    s.data_ready = true;
    s.way_valid = true;
    s.miss_ready = true;
    s.ecc_enable = false;
    s.pmp_instr = true;
    s.pmp_mmio = false;
    s.resp_stall = false;
    s.way_vset = static_cast<std::uint16_t>(((s.req_next_vaddr >> 5) & 0xFFu) << 8 |
                                            ((s.req_start_vaddr >> 5) & 0xFFu));
    s.way_waymask = static_cast<std::uint8_t>((1u << ((cycle + 1) & 3)) << 4 |
                                             (1u << (cycle & 3)));
    s.way_maybe_rvc =
        (static_cast<std::uint64_t>(0x11110000u ^ (cycle * 0x13579u)) << 32)
        | static_cast<std::uint64_t>(0x22220000u ^ (cycle * 0x2468Bu));
    s.way_ptag = static_cast<std::uint64_t>((0x10000u + ((cycle * 19 + salt) & 0xFFFFu))) & 0xFFFFFFFFFULL;
    s.way_meta_codes = static_cast<std::uint8_t>((parity64((s.way_ptag << 32) ^ (s.way_maybe_rvc & 0xFFFFFFFFULL)) |
                                                  (parity64((s.way_ptag << 32) ^ (s.way_maybe_rvc >> 32)) << 1)) &
                                                 3u);
    s.way_itlb_pbmt = static_cast<std::uint8_t>((cycle >> 2) & 3);
    s.way_excp_value = 0;
    s.way_gpaddr = mask_bits(0x1234000000ULL + static_cast<std::uint64_t>(cycle) * 0x41ULL, 55);
    s.way_is_vs_nonleaf = ((cycle + static_cast<int>(salt)) & 0x20) != 0;
    s.miss_resp_blk_paddr = (s.way_ptag << 6) | ((s.req_start_vaddr >> 5) & 0x3FULL);
    s.miss_resp_maybe_rvc = static_cast<std::uint32_t>(s.way_maybe_rvc);
    for (int i = 0; i < 8; ++i) {
        s.miss_resp_data[i] =
            (0xC0FFEE0000000000ULL ^ (static_cast<std::uint64_t>(cycle) << 24))
            + static_cast<std::uint64_t>(i) * 0x0101010101010101ULL
            + static_cast<std::uint64_t>(salt & 0xFFFFu);
    }
}

Stimulus build_directed(int cycle)
{
    Stimulus s;
    fill_common(s, cycle, 0x1234u);
    if (!s.rst_n) {
        s.req_valid = false;
        s.data_ready = true;
        s.way_valid = false;
        return s;
    }

    switch (cycle) {
    case 4:
    case 5:
    case 6:
        s.data_ready = true;
        s.way_valid = true;
        break;
    case 7:
        s.data_ready = false;
        break;
    case 8:
        s.way_valid = false;
        break;
    case 9:
        s.resp_stall = true;
        break;
    case 10:
        s.resp_stall = true;
        s.req_valid = true;
        break;
    case 11:
        s.flush = true;
        break;
    case 12:
        s.bpu_valid = true;
        s.bpu_flag = !s.req_ftq_flag;
        s.bpu_value = static_cast<std::uint8_t>((s.req_ftq_value + 1) & 0x3F);
        break;
    case 13:
        s.way_waymask = 0x00;
        break;
    case 14:
        s.miss_ready = false;
        s.way_waymask = 0x00;
        break;
    case 15:
        s.miss_resp_valid = true;
        break;
    case 16:
        s.way_waymask = 0x10;
        break;
    case 17:
        s.way_waymask = 0x01;
        break;
    case 18:
        s.req_taken_cfi_offset = 31;
        s.req_start_vaddr = (s.req_start_vaddr & ~0x1FULL) | 0x1EULL;
        s.req_next_vaddr = mask_bits((s.req_start_vaddr & ~0x3FULL) + 0x40ULL, 49);
        s.way_vset = static_cast<std::uint16_t>(((s.req_next_vaddr >> 5) & 0xFFu) << 8 |
                                                ((s.req_start_vaddr >> 5) & 0xFFu));
        break;
    default:
        if ((cycle % 19) == 0) {
            s.data_ready = false;
        }
        if ((cycle % 23) == 0) {
            s.way_valid = false;
        }
        if ((cycle % 29) == 0) {
            s.resp_stall = true;
        }
        if ((cycle % 31) == 0) {
            s.flush = true;
        }
        if ((cycle % 37) == 0) {
            s.way_waymask = 0;
        }
        if ((cycle % 41) == 0) {
            s.miss_ready = false;
        }
        if ((cycle % 43) == 0) {
            s.miss_resp_valid = true;
        }
        break;
    }
    return s;
}

Stimulus build_random(int cycle, std::uint32_t& rng)
{
    const std::uint32_t a = xorshift32(rng);
    const std::uint32_t b = xorshift32(rng);
    const std::uint32_t c = xorshift32(rng);
    Stimulus s;
    fill_common(s, cycle, a ^ (b << 1));
    s.rst_n = true;
    s.req_valid = (a & 0x3u) != 0u;
    s.data_ready = (a & 0x4u) == 0u || (cycle & 7) != 0;
    s.way_valid = (a & 0x8u) == 0u || (cycle & 5) != 0;
    s.miss_ready = (b & 0x10u) == 0u;
    s.resp_stall = (b & 0x20u) != 0u;
    s.flush = (c & 0x40u) != 0u;
    s.bpu_valid = (a & 0x80u) != 0u;
    s.bpu_flag = (b & 0x100u) != 0u;
    s.bpu_value = static_cast<std::uint8_t>((c >> 9) & 0x3Fu);
    s.req_backend_exception = (c & 0x8000u) != 0u;
    s.way_is_vs_nonleaf = (b & 0x10000u) != 0u;
    s.way_itlb_pbmt = static_cast<std::uint8_t>((c >> 19) & 3u);
    if ((a & 0x20000u) != 0u) {
        s.way_waymask = 0;
    }
    else {
        s.way_waymask = static_cast<std::uint8_t>((nonzero_waymask(b) << 4) | nonzero_waymask(c));
    }
    s.miss_resp_valid = (a & 0x40000u) != 0u;
    if ((cycle & 15) == 0) {
        s.miss_resp_blk_paddr = (s.way_ptag << 6) | ((s.req_start_vaddr >> 5) & 0x3FULL);
    }
    else if ((cycle & 15) == 1) {
        s.miss_resp_blk_paddr = (s.way_ptag << 6) | ((s.req_next_vaddr >> 5) & 0x3FULL);
    }
    s.miss_resp_corrupt = false;
    s.miss_resp_denied = false;
    s.pmp_mmio = (a & 0x80000u) != 0u;
    s.pmp_instr = true;
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
    SET_FIELD(way_valid, s.way_valid);
    SET_FIELD(way_vset, s.way_vset);
    SET_FIELD(way_waymask, s.way_waymask);
    SET_FIELD(way_maybe_rvc, s.way_maybe_rvc);
    SET_FIELD(way_meta_codes, s.way_meta_codes);
    SET_FIELD(way_ptag, s.way_ptag);
    SET_FIELD(way_itlb_pbmt, s.way_itlb_pbmt);
    SET_FIELD(way_excp_value, s.way_excp_value);
    SET_FIELD(way_gpaddr, s.way_gpaddr);
    SET_FIELD(way_is_vs_nonleaf, s.way_is_vs_nonleaf);
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
    o.way_ready = static_cast<bool>(ref.way_ready);
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
    o.way_ready = static_cast<bool>(grhsim.way_ready);
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
    ok &= compare_u64("way_ready", ref.way_ready, grhsim.way_ready, cycle, phase);
    ok &= compare_u64("miss_req_valid", ref.miss_req_valid, grhsim.miss_req_valid, cycle, phase);
    if (ref.miss_req_valid || grhsim.miss_req_valid) {
        ok &= compare_u64("miss_req_blk_paddr", ref.miss_req_blk_paddr, grhsim.miss_req_blk_paddr, cycle, phase);
        ok &= compare_u64("miss_req_vset", ref.miss_req_vset, grhsim.miss_req_vset, cycle, phase);
    }
    ok &= compare_u64("req_ready", ref.req_ready, grhsim.req_ready, cycle, phase);
    ok &= compare_u64("pmp_req_addr", ref.pmp_req_addr, grhsim.pmp_req_addr, cycle, phase);
    ok &= compare_u64("resp_valid", ref.resp_valid, grhsim.resp_valid, cycle, phase);
    if (ref.resp_valid || grhsim.resp_valid) {
        ok &= compare_u64("resp_doubleline", ref.resp_doubleline, grhsim.resp_doubleline, cycle, phase);
        ok &= compare_u64("resp_vaddr", ref.resp_vaddr, grhsim.resp_vaddr, cycle, phase);
        for (int i = 0; i < 8; ++i) {
            char name[32];
            std::snprintf(name, sizeof(name), "resp_data%d", i);
            ok &= compare_u64(name, ref.resp_data[i], grhsim.resp_data[i], cycle, phase);
        }
        ok &= compare_u64("resp_maybe_rvc", ref.resp_maybe_rvc, grhsim.resp_maybe_rvc, cycle, phase);
        ok &= compare_u64("resp_paddr", ref.resp_paddr, grhsim.resp_paddr, cycle, phase);
        ok &= compare_u64("resp_exception", ref.resp_exception, grhsim.resp_exception, cycle, phase);
        ok &= compare_u64("resp_pmp_mmio", ref.resp_pmp_mmio, grhsim.resp_pmp_mmio, cycle, phase);
        ok &= compare_u64("resp_itlb_pbmt", ref.resp_itlb_pbmt, grhsim.resp_itlb_pbmt, cycle, phase);
        ok &= compare_u64("resp_backend_exception", ref.resp_backend_exception, grhsim.resp_backend_exception, cycle, phase);
        ok &= compare_u64("resp_gpaddr", ref.resp_gpaddr, grhsim.resp_gpaddr, cycle, phase);
        ok &= compare_u64("resp_is_vs_nonleaf", ref.resp_is_vs_nonleaf, grhsim.resp_is_vs_nonleaf, cycle, phase);
    }
    ok &= compare_u64("error0_valid", ref.error0_valid, grhsim.error0_valid, cycle, phase);
    if (ref.error0_valid || grhsim.error0_valid) {
        ok &= compare_u64("error0_paddr", ref.error0_paddr, grhsim.error0_paddr, cycle, phase);
        ok &= compare_u64("error0_report", ref.error0_report, grhsim.error0_report, cycle, phase);
    }
    ok &= compare_u64("error1_valid", ref.error1_valid, grhsim.error1_valid, cycle, phase);
    if (ref.error1_valid || grhsim.error1_valid) {
        ok &= compare_u64("error1_paddr", ref.error1_paddr, grhsim.error1_paddr, cycle, phase);
        ok &= compare_u64("error1_report", ref.error1_report, grhsim.error1_report, cycle, phase);
    }
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

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
    drive(ref, grhsim, false, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "low") ||
        !check_asserts(cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    eval_ref(ref);
    eval_grhsim(grhsim);
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), cycle, "high") ||
        !check_asserts(cycle, "high")) {
        return false;
    }
    ++main_time;
    return true;
}

bool run_directed(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    for (int cycle = 0; cycle < 192; ++cycle) {
        if (!step(ref, grhsim, build_directed(cycle), cycle)) {
            return false;
        }
    }
    return true;
}

bool run_random(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    std::uint32_t rng = 0x51CACE17u;
    for (int cycle = 192; cycle < 4096; ++cycle) {
        if (!step(ref, grhsim, build_random(cycle, rng), cycle)) {
            return false;
        }
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

    if (!run_directed(ref, grhsim) || !run_random(ref, grhsim)) {
        return 1;
    }
    if (ref_assert_count != 0 || grhsim_assert_count != 0) {
        std::fprintf(stderr,
                     "[ASSERT-UNEXPECTED] ref_asserts=%d grhsim_asserts=%d\n",
                     ref_assert_count,
                     grhsim_assert_count);
        return 1;
    }

    std::printf("[PASS] CASE_017 ICacheMainPipe ref == grhsim\n");
    return 0;
}
