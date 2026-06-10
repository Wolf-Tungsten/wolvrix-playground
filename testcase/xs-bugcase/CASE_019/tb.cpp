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

enum class Phase {
    Reset,
    Issue,
    WaitAcquire,
    Grant0,
    Grant1,
    WaitResp,
    DrainWayLookup,
    Gap,
    Done,
};

struct Entry {
    std::uint16_t vset = 0;
    std::uint8_t waymask = 0;
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

struct Transaction {
    std::uint64_t blk_paddr = 0;
    std::uint8_t vset = 0;
    std::uint8_t victim_way = 0;
    Entry way_entry;
    std::uint64_t grant_data[8]{};
};

struct Stimulus {
    bool rst_n = false;
    bool hartId = false;
    bool fencei = false;
    bool flush = false;
    bool wfi_req = false;
    bool fetch_valid = false;
    std::uint64_t fetch_blk_paddr = 0;
    std::uint8_t fetch_vset = 0;
    bool prefetch_valid = false;
    std::uint64_t prefetch_blk_paddr = 0;
    std::uint8_t prefetch_vset = 0;
    std::uint8_t victim_way = 0;
    bool mem_acquire_ready = true;
    bool mem_grant_valid = false;
    std::uint8_t mem_grant_opcode = 1;
    std::uint8_t mem_grant_size = 6;
    std::uint8_t mem_grant_source = 0;
    bool mem_grant_denied = false;
    std::uint64_t mem_grant_data[4]{};
    bool mem_grant_corrupt = false;
    bool way_read_ready = false;
    bool way_write_valid = false;
    Entry way_write;
};

struct Outputs {
    bool wfi_safe = false;
    bool fetch_ready = false;
    bool prefetch_ready = false;
    bool miss_resp_valid = false;
    std::uint64_t miss_resp_blk_paddr = 0;
    std::uint8_t miss_resp_vset = 0;
    std::uint8_t miss_resp_waymask = 0;
    std::uint64_t miss_resp_data[8]{};
    std::uint32_t miss_resp_maybe_rvc = 0;
    bool miss_resp_corrupt = false;
    bool miss_resp_denied = false;
    bool meta_write_valid = false;
    std::uint64_t meta_write_ptag = 0;
    std::uint32_t meta_write_maybe_rvc = 0;
    bool meta_write_code = false;
    std::uint8_t meta_write_vset = 0;
    std::uint8_t meta_write_waymask = 0;
    bool data_write_valid = false;
    std::uint8_t data_write_vset = 0;
    std::uint8_t data_write_waymask = 0;
    bool victim_req_valid = false;
    std::uint8_t victim_req_vset = 0;
    bool mem_acquire_valid = false;
    std::uint8_t mem_acquire_source = 0;
    std::uint64_t mem_acquire_address = 0;
    std::uint8_t mem_acquire_alias = 0;
    bool way_read_valid = false;
    std::uint16_t way_read_vset = 0;
    std::uint8_t way_read_waymask = 0;
    std::uint64_t way_read_maybe_rvc = 0;
    std::uint8_t way_read_meta_codes = 0;
    std::uint64_t way_read_ptag = 0;
    std::uint8_t way_read_itlb_pbmt = 0;
    std::uint8_t way_read_excp_value = 0;
    std::uint64_t way_read_gpaddr = 0;
    bool way_read_is_vs_nonleaf = false;
    bool way_write_ready = false;
    bool way_perf_empty = false;
};

struct StepResult {
    bool ok = false;
    Outputs low_ref;
};

struct Driver {
    Phase phase = Phase::Reset;
    int tx_index = 0;
    bool fetch_done = false;
    bool write_done = false;
    bool have_acquire = false;
    std::uint8_t acquire_source = 0;
    int gap_left = 0;
};

struct Coverage {
    int fetch_fires = 0;
    int way_writes = 0;
    int acquire_fires = 0;
    int grant_beats = 0;
    int miss_resps = 0;
    int meta_writes = 0;
    int data_writes = 0;
    int way_reads = 0;
};

static constexpr int kTransactions = 6;
static vluint64_t main_time = 0;
static EvalModel active_model = EvalModel::Ref;
static int ref_assert_count = 0;
static int grhsim_assert_count = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint64_t mask_bits(std::uint64_t value, unsigned width)
{
    return width >= 64 ? value : (value & ((1ULL << width) - 1ULL));
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

Entry make_entry(int seq, std::uint8_t vset, std::uint8_t waymask, std::uint64_t ptag)
{
    Entry e;
    const std::uint8_t other_vset = static_cast<std::uint8_t>(vset ^ 0x5Au);
    const std::uint8_t other_waymask = static_cast<std::uint8_t>(1u << ((seq + 2) & 3));
    e.vset = static_cast<std::uint16_t>((static_cast<std::uint16_t>(other_vset) << 8) | vset);
    e.waymask = static_cast<std::uint8_t>((other_waymask << 4) | (waymask & 0xFu));
    e.maybe_rvc =
        (static_cast<std::uint64_t>(0x11220000u ^ (seq * 0x010101u)) << 32)
        | static_cast<std::uint64_t>(0x33440000u ^ (seq * 0x001111u));
    e.meta_codes = static_cast<std::uint8_t>(
        (parity64((ptag << 32) ^ (e.maybe_rvc & 0xFFFFFFFFULL)) |
         (parity64((ptag << 32) ^ (e.maybe_rvc >> 32)) << 1)) &
        3u);
    e.ptag = ptag & 0xFFFFFFFFFULL;
    e.itlb_pbmt = static_cast<std::uint8_t>((seq + 1) & 3);
    e.excp_value = 0;
    e.gpaddr = mask_bits(0x1234000000ULL + static_cast<std::uint64_t>(seq) * 0x101ULL, 55);
    e.is_vs_nonleaf = (seq & 1) != 0;
    e.ftq_flag = (seq & 2) != 0;
    e.ftq_value = static_cast<std::uint8_t>((0x10 + seq) & 0x3F);
    return e;
}

Transaction make_transaction(int seq)
{
    Transaction tx;
    const std::uint64_t ptag = 0x12000ULL + static_cast<std::uint64_t>(seq) * 0x123ULL;
    const std::uint8_t block_offset = static_cast<std::uint8_t>((seq * 9 + 3) & 0x3Fu);
    tx.blk_paddr = mask_bits((ptag << 6) | block_offset, 42);
    tx.vset = static_cast<std::uint8_t>(0x20 + seq * 17);
    tx.victim_way = static_cast<std::uint8_t>(seq & 3);
    const std::uint8_t waymask = static_cast<std::uint8_t>(1u << tx.victim_way);
    tx.way_entry = make_entry(seq, tx.vset, waymask, ptag);
    for (int i = 0; i < 8; ++i) {
        tx.grant_data[i] =
            (0xC0FFEE0000000000ULL ^ (static_cast<std::uint64_t>(seq) << 40))
            + static_cast<std::uint64_t>(i) * 0x0101010101010101ULL
            + static_cast<std::uint64_t>(seq * 0x1234);
    }
    return tx;
}

const Transaction& current_tx(const Driver& d, const Transaction txs[kTransactions])
{
    return txs[d.tx_index < kTransactions ? d.tx_index : kTransactions - 1];
}

Stimulus build_stimulus(int cycle, const Driver& d, const Transaction txs[kTransactions])
{
    Stimulus s;
    s.rst_n = cycle >= 3;
    s.hartId = (cycle & 1) != 0;
    s.mem_acquire_ready = true;
    if (!s.rst_n || d.phase == Phase::Reset || d.phase == Phase::Done) {
        return s;
    }

    const Transaction& tx = current_tx(d, txs);
    s.fetch_blk_paddr = tx.blk_paddr;
    s.fetch_vset = tx.vset;
    s.prefetch_blk_paddr = tx.blk_paddr ^ 0x11ULL;
    s.prefetch_vset = static_cast<std::uint8_t>(tx.vset ^ 0x33u);
    s.victim_way = tx.victim_way;
    s.way_write = tx.way_entry;

    switch (d.phase) {
    case Phase::Issue:
    case Phase::WaitAcquire:
        s.fetch_valid = !d.fetch_done;
        s.way_write_valid = !d.write_done;
        break;
    case Phase::Grant0:
        s.mem_grant_valid = true;
        s.mem_grant_source = d.acquire_source;
        s.mem_grant_data[0] = tx.grant_data[0];
        s.mem_grant_data[1] = tx.grant_data[1];
        s.mem_grant_data[2] = tx.grant_data[2];
        s.mem_grant_data[3] = tx.grant_data[3];
        break;
    case Phase::Grant1:
        s.mem_grant_valid = true;
        s.mem_grant_source = d.acquire_source;
        s.mem_grant_data[0] = tx.grant_data[4];
        s.mem_grant_data[1] = tx.grant_data[5];
        s.mem_grant_data[2] = tx.grant_data[6];
        s.mem_grant_data[3] = tx.grant_data[7];
        break;
    case Phase::DrainWayLookup:
        s.way_read_ready = true;
        break;
    default:
        break;
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
    SET_FIELD(fencei, s.fencei);
    SET_FIELD(flush, s.flush);
    SET_FIELD(wfi_req, s.wfi_req);
    SET_FIELD(fetch_valid, s.fetch_valid);
    SET_FIELD(fetch_blk_paddr, s.fetch_blk_paddr);
    SET_FIELD(fetch_vset, s.fetch_vset);
    SET_FIELD(prefetch_valid, s.prefetch_valid);
    SET_FIELD(prefetch_blk_paddr, s.prefetch_blk_paddr);
    SET_FIELD(prefetch_vset, s.prefetch_vset);
    SET_FIELD(victim_way, s.victim_way);
    SET_FIELD(mem_acquire_ready, s.mem_acquire_ready);
    SET_FIELD(mem_grant_valid, s.mem_grant_valid);
    SET_FIELD(mem_grant_opcode, s.mem_grant_opcode);
    SET_FIELD(mem_grant_size, s.mem_grant_size);
    SET_FIELD(mem_grant_source, s.mem_grant_source);
    SET_FIELD(mem_grant_denied, s.mem_grant_denied);
    SET_FIELD(mem_grant_data0, s.mem_grant_data[0]);
    SET_FIELD(mem_grant_data1, s.mem_grant_data[1]);
    SET_FIELD(mem_grant_data2, s.mem_grant_data[2]);
    SET_FIELD(mem_grant_data3, s.mem_grant_data[3]);
    SET_FIELD(mem_grant_corrupt, s.mem_grant_corrupt);
    SET_FIELD(way_read_ready, s.way_read_ready);
    SET_FIELD(way_write_valid, s.way_write_valid);
    SET_FIELD(way_write_vset, s.way_write.vset);
    SET_FIELD(way_write_waymask, s.way_write.waymask);
    SET_FIELD(way_write_maybe_rvc, s.way_write.maybe_rvc);
    SET_FIELD(way_write_meta_codes, s.way_write.meta_codes);
    SET_FIELD(way_write_ptag, s.way_write.ptag);
    SET_FIELD(way_write_itlb_pbmt, s.way_write.itlb_pbmt);
    SET_FIELD(way_write_excp_value, s.way_write.excp_value);
    SET_FIELD(way_write_gpaddr, s.way_write.gpaddr);
    SET_FIELD(way_write_is_vs_nonleaf, s.way_write.is_vs_nonleaf);
    SET_FIELD(way_write_ftq_flag, s.way_write.ftq_flag);
    SET_FIELD(way_write_ftq_value, s.way_write.ftq_value);
#undef SET_FIELD
}

Outputs sample_ref(const VRef& ref)
{
    Outputs o;
    o.wfi_safe = static_cast<bool>(ref.wfi_safe);
    o.fetch_ready = static_cast<bool>(ref.fetch_ready);
    o.prefetch_ready = static_cast<bool>(ref.prefetch_ready);
    o.miss_resp_valid = static_cast<bool>(ref.miss_resp_valid);
    o.miss_resp_blk_paddr = static_cast<std::uint64_t>(ref.miss_resp_blk_paddr);
    o.miss_resp_vset = static_cast<std::uint8_t>(ref.miss_resp_vset);
    o.miss_resp_waymask = static_cast<std::uint8_t>(ref.miss_resp_waymask);
    o.miss_resp_data[0] = static_cast<std::uint64_t>(ref.miss_resp_data0);
    o.miss_resp_data[1] = static_cast<std::uint64_t>(ref.miss_resp_data1);
    o.miss_resp_data[2] = static_cast<std::uint64_t>(ref.miss_resp_data2);
    o.miss_resp_data[3] = static_cast<std::uint64_t>(ref.miss_resp_data3);
    o.miss_resp_data[4] = static_cast<std::uint64_t>(ref.miss_resp_data4);
    o.miss_resp_data[5] = static_cast<std::uint64_t>(ref.miss_resp_data5);
    o.miss_resp_data[6] = static_cast<std::uint64_t>(ref.miss_resp_data6);
    o.miss_resp_data[7] = static_cast<std::uint64_t>(ref.miss_resp_data7);
    o.miss_resp_maybe_rvc = static_cast<std::uint32_t>(ref.miss_resp_maybe_rvc);
    o.miss_resp_corrupt = static_cast<bool>(ref.miss_resp_corrupt);
    o.miss_resp_denied = static_cast<bool>(ref.miss_resp_denied);
    o.meta_write_valid = static_cast<bool>(ref.meta_write_valid);
    o.meta_write_ptag = static_cast<std::uint64_t>(ref.meta_write_ptag);
    o.meta_write_maybe_rvc = static_cast<std::uint32_t>(ref.meta_write_maybe_rvc);
    o.meta_write_code = static_cast<bool>(ref.meta_write_code);
    o.meta_write_vset = static_cast<std::uint8_t>(ref.meta_write_vset);
    o.meta_write_waymask = static_cast<std::uint8_t>(ref.meta_write_waymask);
    o.data_write_valid = static_cast<bool>(ref.data_write_valid);
    o.data_write_vset = static_cast<std::uint8_t>(ref.data_write_vset);
    o.data_write_waymask = static_cast<std::uint8_t>(ref.data_write_waymask);
    o.victim_req_valid = static_cast<bool>(ref.victim_req_valid);
    o.victim_req_vset = static_cast<std::uint8_t>(ref.victim_req_vset);
    o.mem_acquire_valid = static_cast<bool>(ref.mem_acquire_valid);
    o.mem_acquire_source = static_cast<std::uint8_t>(ref.mem_acquire_source);
    o.mem_acquire_address = static_cast<std::uint64_t>(ref.mem_acquire_address);
    o.mem_acquire_alias = static_cast<std::uint8_t>(ref.mem_acquire_alias);
    o.way_read_valid = static_cast<bool>(ref.way_read_valid);
    o.way_read_vset = static_cast<std::uint16_t>(ref.way_read_vset);
    o.way_read_waymask = static_cast<std::uint8_t>(ref.way_read_waymask);
    o.way_read_maybe_rvc = static_cast<std::uint64_t>(ref.way_read_maybe_rvc);
    o.way_read_meta_codes = static_cast<std::uint8_t>(ref.way_read_meta_codes);
    o.way_read_ptag = static_cast<std::uint64_t>(ref.way_read_ptag);
    o.way_read_itlb_pbmt = static_cast<std::uint8_t>(ref.way_read_itlb_pbmt);
    o.way_read_excp_value = static_cast<std::uint8_t>(ref.way_read_excp_value);
    o.way_read_gpaddr = static_cast<std::uint64_t>(ref.way_read_gpaddr);
    o.way_read_is_vs_nonleaf = static_cast<bool>(ref.way_read_is_vs_nonleaf);
    o.way_write_ready = static_cast<bool>(ref.way_write_ready);
    o.way_perf_empty = static_cast<bool>(ref.way_perf_empty);
    return o;
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    Outputs o;
    o.wfi_safe = static_cast<bool>(grhsim.wfi_safe);
    o.fetch_ready = static_cast<bool>(grhsim.fetch_ready);
    o.prefetch_ready = static_cast<bool>(grhsim.prefetch_ready);
    o.miss_resp_valid = static_cast<bool>(grhsim.miss_resp_valid);
    o.miss_resp_blk_paddr = static_cast<std::uint64_t>(grhsim.miss_resp_blk_paddr);
    o.miss_resp_vset = static_cast<std::uint8_t>(grhsim.miss_resp_vset);
    o.miss_resp_waymask = static_cast<std::uint8_t>(grhsim.miss_resp_waymask);
    o.miss_resp_data[0] = static_cast<std::uint64_t>(grhsim.miss_resp_data0);
    o.miss_resp_data[1] = static_cast<std::uint64_t>(grhsim.miss_resp_data1);
    o.miss_resp_data[2] = static_cast<std::uint64_t>(grhsim.miss_resp_data2);
    o.miss_resp_data[3] = static_cast<std::uint64_t>(grhsim.miss_resp_data3);
    o.miss_resp_data[4] = static_cast<std::uint64_t>(grhsim.miss_resp_data4);
    o.miss_resp_data[5] = static_cast<std::uint64_t>(grhsim.miss_resp_data5);
    o.miss_resp_data[6] = static_cast<std::uint64_t>(grhsim.miss_resp_data6);
    o.miss_resp_data[7] = static_cast<std::uint64_t>(grhsim.miss_resp_data7);
    o.miss_resp_maybe_rvc = static_cast<std::uint32_t>(grhsim.miss_resp_maybe_rvc);
    o.miss_resp_corrupt = static_cast<bool>(grhsim.miss_resp_corrupt);
    o.miss_resp_denied = static_cast<bool>(grhsim.miss_resp_denied);
    o.meta_write_valid = static_cast<bool>(grhsim.meta_write_valid);
    o.meta_write_ptag = static_cast<std::uint64_t>(grhsim.meta_write_ptag);
    o.meta_write_maybe_rvc = static_cast<std::uint32_t>(grhsim.meta_write_maybe_rvc);
    o.meta_write_code = static_cast<bool>(grhsim.meta_write_code);
    o.meta_write_vset = static_cast<std::uint8_t>(grhsim.meta_write_vset);
    o.meta_write_waymask = static_cast<std::uint8_t>(grhsim.meta_write_waymask);
    o.data_write_valid = static_cast<bool>(grhsim.data_write_valid);
    o.data_write_vset = static_cast<std::uint8_t>(grhsim.data_write_vset);
    o.data_write_waymask = static_cast<std::uint8_t>(grhsim.data_write_waymask);
    o.victim_req_valid = static_cast<bool>(grhsim.victim_req_valid);
    o.victim_req_vset = static_cast<std::uint8_t>(grhsim.victim_req_vset);
    o.mem_acquire_valid = static_cast<bool>(grhsim.mem_acquire_valid);
    o.mem_acquire_source = static_cast<std::uint8_t>(grhsim.mem_acquire_source);
    o.mem_acquire_address = static_cast<std::uint64_t>(grhsim.mem_acquire_address);
    o.mem_acquire_alias = static_cast<std::uint8_t>(grhsim.mem_acquire_alias);
    o.way_read_valid = static_cast<bool>(grhsim.way_read_valid);
    o.way_read_vset = static_cast<std::uint16_t>(grhsim.way_read_vset);
    o.way_read_waymask = static_cast<std::uint8_t>(grhsim.way_read_waymask);
    o.way_read_maybe_rvc = static_cast<std::uint64_t>(grhsim.way_read_maybe_rvc);
    o.way_read_meta_codes = static_cast<std::uint8_t>(grhsim.way_read_meta_codes);
    o.way_read_ptag = static_cast<std::uint64_t>(grhsim.way_read_ptag);
    o.way_read_itlb_pbmt = static_cast<std::uint8_t>(grhsim.way_read_itlb_pbmt);
    o.way_read_excp_value = static_cast<std::uint8_t>(grhsim.way_read_excp_value);
    o.way_read_gpaddr = static_cast<std::uint64_t>(grhsim.way_read_gpaddr);
    o.way_read_is_vs_nonleaf = static_cast<bool>(grhsim.way_read_is_vs_nonleaf);
    o.way_write_ready = static_cast<bool>(grhsim.way_write_ready);
    o.way_perf_empty = static_cast<bool>(grhsim.way_perf_empty);
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
    ok &= compare_u64("wfi_safe", ref.wfi_safe, grhsim.wfi_safe, cycle, phase);
    ok &= compare_u64("fetch_ready", ref.fetch_ready, grhsim.fetch_ready, cycle, phase);
    ok &= compare_u64("prefetch_ready", ref.prefetch_ready, grhsim.prefetch_ready, cycle, phase);
    ok &= compare_u64("way_write_ready", ref.way_write_ready, grhsim.way_write_ready, cycle, phase);
    ok &= compare_u64("way_perf_empty", ref.way_perf_empty, grhsim.way_perf_empty, cycle, phase);
    ok &= compare_u64("victim_req_valid", ref.victim_req_valid, grhsim.victim_req_valid, cycle, phase);
    if (ref.victim_req_valid || grhsim.victim_req_valid) {
        ok &= compare_u64("victim_req_vset", ref.victim_req_vset, grhsim.victim_req_vset, cycle, phase);
    }
    ok &= compare_u64("mem_acquire_valid", ref.mem_acquire_valid, grhsim.mem_acquire_valid, cycle, phase);
    if (ref.mem_acquire_valid || grhsim.mem_acquire_valid) {
        ok &= compare_u64("mem_acquire_source", ref.mem_acquire_source, grhsim.mem_acquire_source, cycle, phase);
        ok &= compare_u64("mem_acquire_address", ref.mem_acquire_address, grhsim.mem_acquire_address, cycle, phase);
        ok &= compare_u64("mem_acquire_alias", ref.mem_acquire_alias, grhsim.mem_acquire_alias, cycle, phase);
    }
    ok &= compare_u64("miss_resp_valid", ref.miss_resp_valid, grhsim.miss_resp_valid, cycle, phase);
    if (ref.miss_resp_valid || grhsim.miss_resp_valid) {
        ok &= compare_u64("miss_resp_blk_paddr", ref.miss_resp_blk_paddr, grhsim.miss_resp_blk_paddr, cycle, phase);
        ok &= compare_u64("miss_resp_vset", ref.miss_resp_vset, grhsim.miss_resp_vset, cycle, phase);
        ok &= compare_u64("miss_resp_waymask", ref.miss_resp_waymask, grhsim.miss_resp_waymask, cycle, phase);
        ok &= compare_u64("miss_resp_maybe_rvc", ref.miss_resp_maybe_rvc, grhsim.miss_resp_maybe_rvc, cycle, phase);
        ok &= compare_u64("miss_resp_corrupt", ref.miss_resp_corrupt, grhsim.miss_resp_corrupt, cycle, phase);
        ok &= compare_u64("miss_resp_denied", ref.miss_resp_denied, grhsim.miss_resp_denied, cycle, phase);
    }
    ok &= compare_u64("meta_write_valid", ref.meta_write_valid, grhsim.meta_write_valid, cycle, phase);
    if (ref.meta_write_valid || grhsim.meta_write_valid) {
        ok &= compare_u64("meta_write_ptag", ref.meta_write_ptag, grhsim.meta_write_ptag, cycle, phase);
        ok &= compare_u64("meta_write_maybe_rvc", ref.meta_write_maybe_rvc, grhsim.meta_write_maybe_rvc, cycle, phase);
        ok &= compare_u64("meta_write_code", ref.meta_write_code, grhsim.meta_write_code, cycle, phase);
        ok &= compare_u64("meta_write_vset", ref.meta_write_vset, grhsim.meta_write_vset, cycle, phase);
        ok &= compare_u64("meta_write_waymask", ref.meta_write_waymask, grhsim.meta_write_waymask, cycle, phase);
    }
    ok &= compare_u64("data_write_valid", ref.data_write_valid, grhsim.data_write_valid, cycle, phase);
    if (ref.data_write_valid || grhsim.data_write_valid) {
        ok &= compare_u64("data_write_vset", ref.data_write_vset, grhsim.data_write_vset, cycle, phase);
        ok &= compare_u64("data_write_waymask", ref.data_write_waymask, grhsim.data_write_waymask, cycle, phase);
        for (int i = 0; i < 8; ++i) {
            char name[32];
            std::snprintf(name, sizeof(name), "data_write_data%d", i);
            ok &= compare_u64(name, ref.miss_resp_data[i], grhsim.miss_resp_data[i], cycle, phase);
        }
    }
    ok &= compare_u64("way_read_valid", ref.way_read_valid, grhsim.way_read_valid, cycle, phase);
    if (ref.way_read_valid || grhsim.way_read_valid) {
        ok &= compare_u64("way_read_vset", ref.way_read_vset, grhsim.way_read_vset, cycle, phase);
        ok &= compare_u64("way_read_waymask", ref.way_read_waymask, grhsim.way_read_waymask, cycle, phase);
        ok &= compare_u64("way_read_maybe_rvc", ref.way_read_maybe_rvc, grhsim.way_read_maybe_rvc, cycle, phase);
        ok &= compare_u64("way_read_meta_codes", ref.way_read_meta_codes, grhsim.way_read_meta_codes, cycle, phase);
        ok &= compare_u64("way_read_ptag", ref.way_read_ptag, grhsim.way_read_ptag, cycle, phase);
        ok &= compare_u64("way_read_itlb_pbmt", ref.way_read_itlb_pbmt, grhsim.way_read_itlb_pbmt, cycle, phase);
        ok &= compare_u64("way_read_excp_value", ref.way_read_excp_value, grhsim.way_read_excp_value, cycle, phase);
        ok &= compare_u64("way_read_gpaddr", ref.way_read_gpaddr, grhsim.way_read_gpaddr, cycle, phase);
        ok &= compare_u64("way_read_is_vs_nonleaf", ref.way_read_is_vs_nonleaf, grhsim.way_read_is_vs_nonleaf, cycle, phase);
    }
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

void advance_driver(Driver& d, Coverage& c, const Stimulus& s, const Outputs& low)
{
    if (!s.rst_n) {
        d = Driver{};
        d.phase = Phase::Reset;
        return;
    }
    if (d.phase == Phase::Reset) {
        d.phase = Phase::Issue;
        return;
    }

    const bool fetch_fire = s.fetch_valid && low.fetch_ready;
    const bool write_fire = s.way_write_valid && low.way_write_ready;
    const bool acquire_fire = s.mem_acquire_ready && low.mem_acquire_valid;
    const bool read_fire = s.way_read_ready && low.way_read_valid;

    if (fetch_fire) {
        d.fetch_done = true;
        ++c.fetch_fires;
    }
    if (write_fire) {
        d.write_done = true;
        ++c.way_writes;
    }
    if (acquire_fire) {
        d.have_acquire = true;
        d.acquire_source = low.mem_acquire_source;
        ++c.acquire_fires;
    }
    if (s.mem_grant_valid) {
        ++c.grant_beats;
    }
    if (low.miss_resp_valid) {
        ++c.miss_resps;
    }
    if (low.meta_write_valid) {
        ++c.meta_writes;
    }
    if (low.data_write_valid) {
        ++c.data_writes;
    }
    if (read_fire) {
        ++c.way_reads;
    }

    switch (d.phase) {
    case Phase::Issue:
    case Phase::WaitAcquire:
        d.phase = d.have_acquire && d.fetch_done && d.write_done ? Phase::Grant0 : Phase::WaitAcquire;
        break;
    case Phase::Grant0:
        d.phase = Phase::Grant1;
        break;
    case Phase::Grant1:
        d.phase = Phase::WaitResp;
        break;
    case Phase::WaitResp:
        if (low.miss_resp_valid) {
            d.phase = Phase::DrainWayLookup;
        }
        break;
    case Phase::DrainWayLookup:
        if (read_fire) {
            ++d.tx_index;
            d.fetch_done = false;
            d.write_done = false;
            d.have_acquire = false;
            d.acquire_source = 0;
            d.gap_left = 1;
            d.phase = d.tx_index >= kTransactions ? Phase::Done : Phase::Gap;
        }
        break;
    case Phase::Gap:
        if (d.gap_left > 0) {
            --d.gap_left;
        }
        else {
            d.phase = Phase::Issue;
        }
        break;
    default:
        break;
    }
}

bool run_cycles(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim)
{
    Transaction txs[kTransactions];
    for (int i = 0; i < kTransactions; ++i) {
        txs[i] = make_transaction(i);
    }

    Driver driver;
    Coverage coverage;
    for (int cycle = 0; cycle < 512; ++cycle) {
        Stimulus s = build_stimulus(cycle, driver, txs);
        StepResult r = step(ref, grhsim, s, cycle);
        if (!r.ok) {
            return false;
        }
        advance_driver(driver, coverage, s, r.low_ref);
        if (driver.phase == Phase::Done) {
            if (coverage.fetch_fires != kTransactions ||
                coverage.way_writes != kTransactions ||
                coverage.acquire_fires != kTransactions ||
                coverage.grant_beats != kTransactions * 2 ||
                coverage.miss_resps != kTransactions ||
                coverage.meta_writes != kTransactions ||
                coverage.data_writes != kTransactions ||
                coverage.way_reads != kTransactions) {
                std::fprintf(stderr,
                             "[COVERAGE-FAIL] fetch=%d write=%d acquire=%d grant=%d resp=%d meta=%d data=%d read=%d\n",
                             coverage.fetch_fires,
                             coverage.way_writes,
                             coverage.acquire_fires,
                             coverage.grant_beats,
                             coverage.miss_resps,
                             coverage.meta_writes,
                             coverage.data_writes,
                             coverage.way_reads);
                return false;
            }
            return true;
        }
    }

    std::fprintf(stderr,
                 "[TIMEOUT] phase=%d tx=%d fetch_done=%d write_done=%d have_acquire=%d source=%u\n",
                 static_cast<int>(driver.phase),
                 driver.tx_index,
                 driver.fetch_done,
                 driver.write_done,
                 driver.have_acquire,
                 driver.acquire_source);
    return false;
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

    if (!run_cycles(ref, grhsim)) {
        return 1;
    }
    if (ref_assert_count != 0 || grhsim_assert_count != 0) {
        std::fprintf(stderr,
                     "[ASSERT-UNEXPECTED] ref_asserts=%d grhsim_asserts=%d\n",
                     ref_assert_count,
                     grhsim_assert_count);
        return 1;
    }

    std::printf("[PASS] CASE_019 ICacheMissUnit+ICacheWayLookup ref == grhsim\n");
    return 0;
}
