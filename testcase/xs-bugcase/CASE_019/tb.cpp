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

static constexpr int kTransactions = 12;
static constexpr int kSources = 16;
static constexpr int kFetchTransactions = 4;
static constexpr int kPrefetchTransactions = kTransactions - kFetchTransactions;
static constexpr int kFetchWindow = 14;
static constexpr int kGrantStartDepth = 4;

static constexpr int kStateUnissued = 0;
static constexpr int kStateIssued = 1;
static constexpr int kStateAcquired = 2;
static constexpr int kStateGrant0 = 3;
static constexpr int kStateGrant1 = 4;
static constexpr int kStateResponded = 5;

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
    std::uint64_t data_write_data[8]{};
    bool victim_req_valid = false;
    std::uint8_t victim_req_vset = 0;
    bool mem_acquire_valid = false;
    std::uint8_t mem_acquire_source = 0;
    std::uint64_t mem_acquire_address = 0;
    std::uint8_t mem_acquire_alias = 0;
    bool refill_valid = false;
    std::uint64_t refill_addr = 0;
    std::uint64_t refill_data[8]{};
    std::uint8_t refill_mask = 0;
    std::uint8_t refill_coreid = 0;
    std::uint8_t refill_index = 0;
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
    int next_fetch = 0;
    int next_prefetch = kFetchTransactions;
    int next_write = 0;
    int current_grant_source = -1;
    int responses_seen = 0;
    int data_writes_seen = 0;
    int way_reads_seen = 0;
    int tx_state[kTransactions]{};
    bool tx_write_done[kTransactions]{};
    bool source_valid[kSources]{};
    int source_tx[kSources]{};
    int source_beat[kSources]{};
};

struct Coverage {
    int fetch_fires = 0;
    int prefetch_fires = 0;
    int way_writes = 0;
    int acquire_fires = 0;
    int grant_beats = 0;
    int miss_resps = 0;
    int meta_writes = 0;
    int data_writes = 0;
    int way_reads = 0;
};

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
    const std::uint64_t byte_addr = 0x80000000ULL + static_cast<std::uint64_t>(seq) * 0x40ULL;
    tx.blk_paddr = mask_bits(byte_addr >> 6, 42);
    tx.vset = static_cast<std::uint8_t>(0x20 + seq * 13);
    tx.victim_way = static_cast<std::uint8_t>(seq & 3);
    const std::uint64_t ptag = tx.blk_paddr >> 6;
    const std::uint8_t waymask = static_cast<std::uint8_t>(1u << tx.victim_way);
    tx.way_entry = make_entry(seq, tx.vset, waymask, ptag);
    for (int i = 0; i < 8; ++i) {
        tx.grant_data[i] =
            (0xC0DE000000000000ULL ^ (static_cast<std::uint64_t>(seq) << 48))
            | ((byte_addr + static_cast<std::uint64_t>(i) * 8ULL) & 0xFFFFFFFFFFFFULL);
    }
    return tx;
}

int find_tx_by_acquire_address(const Transaction txs[kTransactions], std::uint64_t address)
{
    for (int i = 0; i < kTransactions; ++i) {
        if (((txs[i].blk_paddr << 6) & 0xFFFFFFFFFFFFULL) == (address & 0xFFFFFFFFFFFFULL)) {
            return i;
        }
    }
    return -1;
}

int count_inflight_fetches(const Driver& d)
{
    int count = 0;
    for (int i = 0; i < kTransactions; ++i) {
        if (d.tx_state[i] >= kStateIssued && d.tx_state[i] < kStateResponded) {
            ++count;
        }
    }
    return count;
}

int count_acquired_not_done(const Driver& d)
{
    int count = 0;
    for (int i = 0; i < kTransactions; ++i) {
        if (d.tx_state[i] >= kStateAcquired && d.tx_state[i] < kStateResponded) {
            ++count;
        }
    }
    return count;
}

int choose_grant_source(const Driver& d)
{
    for (int source = kSources - 1; source >= 0; --source) {
        if (d.source_valid[source] && d.source_beat[source] < 2) {
            return source;
        }
    }
    return -1;
}

int find_source_for_tx(const Driver& d, int tx_index)
{
    for (int source = 0; source < kSources; ++source) {
        if (d.source_valid[source] && d.source_tx[source] == tx_index) {
            return source;
        }
    }
    return -1;
}

const char* state_name(int state)
{
    switch (state) {
    case kStateUnissued:
        return "unissued";
    case kStateIssued:
        return "issued";
    case kStateAcquired:
        return "acquired";
    case kStateGrant0:
        return "grant0";
    case kStateGrant1:
        return "grant1";
    case kStateResponded:
        return "responded";
    default:
        return "unknown";
    }
}

Stimulus build_stimulus(int cycle, const Driver& d, const Transaction txs[kTransactions])
{
    Stimulus s;
    s.rst_n = cycle >= 3;
    s.hartId = (cycle & 1) != 0;
    s.mem_acquire_ready = true;
    if (!s.rst_n) {
        return s;
    }

    if (d.next_fetch < kFetchTransactions && count_inflight_fetches(d) < kFetchWindow) {
        const Transaction& tx = txs[d.next_fetch];
        s.fetch_valid = true;
        s.fetch_blk_paddr = tx.blk_paddr;
        s.fetch_vset = tx.vset;
        s.victim_way = tx.victim_way;
    }
    else {
        s.fetch_blk_paddr = txs[kTransactions - 1].blk_paddr;
        s.fetch_vset = txs[kTransactions - 1].vset;
        s.victim_way = txs[kTransactions - 1].victim_way;
    }

    if (d.next_prefetch < kTransactions && count_inflight_fetches(d) < kFetchWindow) {
        const Transaction& tx = txs[d.next_prefetch];
        s.prefetch_valid = true;
        s.prefetch_blk_paddr = tx.blk_paddr;
        s.prefetch_vset = tx.vset;
    }

    if (d.next_write < kTransactions) {
        const Transaction& tx = txs[d.next_write];
        s.way_write_valid = !d.tx_write_done[d.next_write];
        s.way_write = tx.way_entry;
    }

    const bool all_requests_issued = d.next_fetch >= kFetchTransactions && d.next_prefetch >= kTransactions;
    const bool enough_pending = count_acquired_not_done(d) >= kGrantStartDepth;
    if (d.current_grant_source >= 0 || enough_pending || all_requests_issued) {
        const int source = d.current_grant_source >= 0 ? d.current_grant_source : choose_grant_source(d);
        if (source >= 0 && source < kSources && d.source_valid[source]) {
            const int tx_index = d.source_tx[source];
            const int beat = d.source_beat[source];
            const Transaction& tx = txs[tx_index];
            const int lane_base = beat == 0 ? 0 : 4;
            s.mem_grant_valid = true;
            s.mem_grant_source = static_cast<std::uint8_t>(source);
            s.mem_grant_data[0] = tx.grant_data[lane_base + 0];
            s.mem_grant_data[1] = tx.grant_data[lane_base + 1];
            s.mem_grant_data[2] = tx.grant_data[lane_base + 2];
            s.mem_grant_data[3] = tx.grant_data[lane_base + 3];
        }
    }

    if (d.responses_seen > d.way_reads_seen || all_requests_issued) {
        s.way_read_ready = true;
    }

    if (!s.prefetch_valid) {
        s.prefetch_blk_paddr = txs[(cycle + 3) % kTransactions].blk_paddr ^ 0x40ULL;
        s.prefetch_vset = static_cast<std::uint8_t>(txs[(cycle + 3) % kTransactions].vset ^ 0x33u);
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
    o.data_write_data[0] = static_cast<std::uint64_t>(ref.data_write_data0);
    o.data_write_data[1] = static_cast<std::uint64_t>(ref.data_write_data1);
    o.data_write_data[2] = static_cast<std::uint64_t>(ref.data_write_data2);
    o.data_write_data[3] = static_cast<std::uint64_t>(ref.data_write_data3);
    o.data_write_data[4] = static_cast<std::uint64_t>(ref.data_write_data4);
    o.data_write_data[5] = static_cast<std::uint64_t>(ref.data_write_data5);
    o.data_write_data[6] = static_cast<std::uint64_t>(ref.data_write_data6);
    o.data_write_data[7] = static_cast<std::uint64_t>(ref.data_write_data7);
    o.victim_req_valid = static_cast<bool>(ref.victim_req_valid);
    o.victim_req_vset = static_cast<std::uint8_t>(ref.victim_req_vset);
    o.mem_acquire_valid = static_cast<bool>(ref.mem_acquire_valid);
    o.mem_acquire_source = static_cast<std::uint8_t>(ref.mem_acquire_source);
    o.mem_acquire_address = static_cast<std::uint64_t>(ref.mem_acquire_address);
    o.mem_acquire_alias = static_cast<std::uint8_t>(ref.mem_acquire_alias);
    o.refill_valid = static_cast<bool>(ref.refill_valid);
    o.refill_addr = static_cast<std::uint64_t>(ref.refill_addr);
    o.refill_data[0] = static_cast<std::uint64_t>(ref.refill_data0);
    o.refill_data[1] = static_cast<std::uint64_t>(ref.refill_data1);
    o.refill_data[2] = static_cast<std::uint64_t>(ref.refill_data2);
    o.refill_data[3] = static_cast<std::uint64_t>(ref.refill_data3);
    o.refill_data[4] = static_cast<std::uint64_t>(ref.refill_data4);
    o.refill_data[5] = static_cast<std::uint64_t>(ref.refill_data5);
    o.refill_data[6] = static_cast<std::uint64_t>(ref.refill_data6);
    o.refill_data[7] = static_cast<std::uint64_t>(ref.refill_data7);
    o.refill_mask = static_cast<std::uint8_t>(ref.refill_mask);
    o.refill_coreid = static_cast<std::uint8_t>(ref.refill_coreid);
    o.refill_index = static_cast<std::uint8_t>(ref.refill_index);
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
    o.data_write_data[0] = static_cast<std::uint64_t>(grhsim.data_write_data0);
    o.data_write_data[1] = static_cast<std::uint64_t>(grhsim.data_write_data1);
    o.data_write_data[2] = static_cast<std::uint64_t>(grhsim.data_write_data2);
    o.data_write_data[3] = static_cast<std::uint64_t>(grhsim.data_write_data3);
    o.data_write_data[4] = static_cast<std::uint64_t>(grhsim.data_write_data4);
    o.data_write_data[5] = static_cast<std::uint64_t>(grhsim.data_write_data5);
    o.data_write_data[6] = static_cast<std::uint64_t>(grhsim.data_write_data6);
    o.data_write_data[7] = static_cast<std::uint64_t>(grhsim.data_write_data7);
    o.victim_req_valid = static_cast<bool>(grhsim.victim_req_valid);
    o.victim_req_vset = static_cast<std::uint8_t>(grhsim.victim_req_vset);
    o.mem_acquire_valid = static_cast<bool>(grhsim.mem_acquire_valid);
    o.mem_acquire_source = static_cast<std::uint8_t>(grhsim.mem_acquire_source);
    o.mem_acquire_address = static_cast<std::uint64_t>(grhsim.mem_acquire_address);
    o.mem_acquire_alias = static_cast<std::uint8_t>(grhsim.mem_acquire_alias);
    o.refill_valid = static_cast<bool>(grhsim.refill_valid);
    o.refill_addr = static_cast<std::uint64_t>(grhsim.refill_addr);
    o.refill_data[0] = static_cast<std::uint64_t>(grhsim.refill_data0);
    o.refill_data[1] = static_cast<std::uint64_t>(grhsim.refill_data1);
    o.refill_data[2] = static_cast<std::uint64_t>(grhsim.refill_data2);
    o.refill_data[3] = static_cast<std::uint64_t>(grhsim.refill_data3);
    o.refill_data[4] = static_cast<std::uint64_t>(grhsim.refill_data4);
    o.refill_data[5] = static_cast<std::uint64_t>(grhsim.refill_data5);
    o.refill_data[6] = static_cast<std::uint64_t>(grhsim.refill_data6);
    o.refill_data[7] = static_cast<std::uint64_t>(grhsim.refill_data7);
    o.refill_mask = static_cast<std::uint8_t>(grhsim.refill_mask);
    o.refill_coreid = static_cast<std::uint8_t>(grhsim.refill_coreid);
    o.refill_index = static_cast<std::uint8_t>(grhsim.refill_index);
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
    ok &= compare_u64("refill_valid", ref.refill_valid, grhsim.refill_valid, cycle, phase);
    if (ref.refill_valid || grhsim.refill_valid) {
        ok &= compare_u64("refill_addr", ref.refill_addr, grhsim.refill_addr, cycle, phase);
        ok &= compare_u64("refill_mask", ref.refill_mask, grhsim.refill_mask, cycle, phase);
        ok &= compare_u64("refill_coreid", ref.refill_coreid, grhsim.refill_coreid, cycle, phase);
        ok &= compare_u64("refill_index", ref.refill_index, grhsim.refill_index, cycle, phase);
        for (int i = 0; i < 8; ++i) {
            char name[32];
            std::snprintf(name, sizeof(name), "refill_data%d", i);
            ok &= compare_u64(name, ref.refill_data[i], grhsim.refill_data[i], cycle, phase);
        }
    }
    ok &= compare_u64("miss_resp_valid", ref.miss_resp_valid, grhsim.miss_resp_valid, cycle, phase);
    if (ref.miss_resp_valid || grhsim.miss_resp_valid) {
        ok &= compare_u64("miss_resp_blk_paddr", ref.miss_resp_blk_paddr, grhsim.miss_resp_blk_paddr, cycle, phase);
        ok &= compare_u64("miss_resp_vset", ref.miss_resp_vset, grhsim.miss_resp_vset, cycle, phase);
        ok &= compare_u64("miss_resp_waymask", ref.miss_resp_waymask, grhsim.miss_resp_waymask, cycle, phase);
        ok &= compare_u64("miss_resp_maybe_rvc", ref.miss_resp_maybe_rvc, grhsim.miss_resp_maybe_rvc, cycle, phase);
        ok &= compare_u64("miss_resp_corrupt", ref.miss_resp_corrupt, grhsim.miss_resp_corrupt, cycle, phase);
        ok &= compare_u64("miss_resp_denied", ref.miss_resp_denied, grhsim.miss_resp_denied, cycle, phase);
        for (int i = 0; i < 8; ++i) {
            char name[32];
            std::snprintf(name, sizeof(name), "miss_resp_data%d", i);
            ok &= compare_u64(name, ref.miss_resp_data[i], grhsim.miss_resp_data[i], cycle, phase);
        }
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
            ok &= compare_u64(name, ref.data_write_data[i], grhsim.data_write_data[i], cycle, phase);
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

bool advance_driver(Driver& d,
                    Coverage& c,
                    const Stimulus& s,
                    const Outputs& low,
                    const Transaction txs[kTransactions],
                    int cycle)
{
    if (!s.rst_n) {
        d = Driver{};
        return true;
    }

    const bool fetch_fire = s.fetch_valid && low.fetch_ready;
    const bool prefetch_fire = s.prefetch_valid && low.prefetch_ready;
    const bool write_fire = s.way_write_valid && low.way_write_ready;
    const bool acquire_fire = s.mem_acquire_ready && low.mem_acquire_valid;
    const bool read_fire = s.way_read_ready && low.way_read_valid;

    if (fetch_fire) {
        if (d.next_fetch >= kFetchTransactions) {
            std::fprintf(stderr, "[DRIVER-FAIL] cycle=%d unexpected fetch fire\n", cycle);
            return false;
        }
        d.tx_state[d.next_fetch] = kStateIssued;
        ++d.next_fetch;
        ++c.fetch_fires;
    }
    if (prefetch_fire) {
        if (d.next_prefetch >= kTransactions) {
            std::fprintf(stderr, "[DRIVER-FAIL] cycle=%d unexpected prefetch fire\n", cycle);
            return false;
        }
        d.tx_state[d.next_prefetch] = kStateIssued;
        ++d.next_prefetch;
        ++c.prefetch_fires;
    }
    if (write_fire) {
        if (d.next_write >= kTransactions) {
            std::fprintf(stderr, "[DRIVER-FAIL] cycle=%d unexpected way write fire\n", cycle);
            return false;
        }
        d.tx_write_done[d.next_write] = true;
        ++d.next_write;
        ++c.way_writes;
    }
    if (acquire_fire) {
        const int source = low.mem_acquire_source;
        const int tx_index = find_tx_by_acquire_address(txs, low.mem_acquire_address);
        if (source < 0 || source >= kSources || tx_index < 0) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d unknown acquire source=%d address=0x%llx\n",
                         cycle,
                         source,
                         static_cast<unsigned long long>(low.mem_acquire_address));
            return false;
        }
        if (d.source_valid[source]) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d duplicate acquire source=%d old_tx=%d new_tx=%d\n",
                         cycle,
                         source,
                         d.source_tx[source],
                         tx_index);
            return false;
        }
        if (d.tx_state[tx_index] < kStateIssued || d.tx_state[tx_index] >= kStateAcquired) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d acquire tx=%d state=%s\n",
                         cycle,
                         tx_index,
                         state_name(d.tx_state[tx_index]));
            return false;
        }
        d.source_valid[source] = true;
        d.source_tx[source] = tx_index;
        d.source_beat[source] = 0;
        d.tx_state[tx_index] = kStateAcquired;
        ++c.acquire_fires;
    }
    if (s.mem_grant_valid) {
        const int source = s.mem_grant_source;
        if (source < 0 || source >= kSources || !d.source_valid[source]) {
            std::fprintf(stderr, "[DRIVER-FAIL] cycle=%d grant for unknown source=%d\n", cycle, source);
            return false;
        }
        const int tx_index = d.source_tx[source];
        const int beat = d.source_beat[source];
        if (beat < 0 || beat >= 2) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d extra grant source=%d tx=%d beat=%d\n",
                         cycle,
                         source,
                         tx_index,
                         beat);
            return false;
        }
        d.source_beat[source] = beat + 1;
        d.tx_state[tx_index] = beat == 0 ? kStateGrant0 : kStateGrant1;
        d.current_grant_source = beat == 0 ? source : -1;
        ++c.grant_beats;
    }
    if (low.miss_resp_valid) {
        const int tx_index = find_tx_by_acquire_address(txs, low.miss_resp_blk_paddr << 6);
        if (tx_index < 0) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d unknown response blk=0x%llx\n",
                         cycle,
                         static_cast<unsigned long long>(low.miss_resp_blk_paddr));
            return false;
        }
        if (d.tx_state[tx_index] < kStateGrant1) {
            std::fprintf(stderr,
                         "[DRIVER-FAIL] cycle=%d response tx=%d state=%s\n",
                         cycle,
                         tx_index,
                         state_name(d.tx_state[tx_index]));
            return false;
        }
        const int source = find_source_for_tx(d, tx_index);
        if (source >= 0) {
            d.source_valid[source] = false;
        }
        d.tx_state[tx_index] = kStateResponded;
        ++d.responses_seen;
        ++c.miss_resps;
    }
    if (low.meta_write_valid) {
        ++c.meta_writes;
    }
    if (low.data_write_valid) {
        ++d.data_writes_seen;
        ++c.data_writes;
    }
    if (read_fire) {
        ++d.way_reads_seen;
        ++c.way_reads;
    }
    return true;
}

bool coverage_complete(const Coverage& coverage)
{
    return coverage.fetch_fires == kFetchTransactions &&
           coverage.prefetch_fires == kPrefetchTransactions &&
           coverage.way_writes == kTransactions &&
           coverage.acquire_fires == kTransactions &&
           coverage.grant_beats == kTransactions * 2 &&
           coverage.miss_resps == kTransactions &&
           coverage.meta_writes == kTransactions &&
           coverage.data_writes == kTransactions &&
           coverage.way_reads == kTransactions;
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
        if (!advance_driver(driver, coverage, s, r.low_ref, txs, cycle)) {
            return false;
        }
        if (coverage_complete(coverage)) {
            return true;
        }
    }

    std::fprintf(stderr,
                 "[TIMEOUT] fetch=%d/%d prefetch=%d/%d write=%d/%d acquire=%d/%d grant=%d/%d resp=%d/%d meta=%d/%d data=%d/%d read=%d/%d next_fetch=%d next_prefetch=%d next_write=%d current_grant_source=%d\n",
                 coverage.fetch_fires,
                 kFetchTransactions,
                 coverage.prefetch_fires,
                 kPrefetchTransactions,
                 coverage.way_writes,
                 kTransactions,
                 coverage.acquire_fires,
                 kTransactions,
                 coverage.grant_beats,
                 kTransactions * 2,
                 coverage.miss_resps,
                 kTransactions,
                 coverage.meta_writes,
                 kTransactions,
                 coverage.data_writes,
                 kTransactions,
                 coverage.way_reads,
                 kTransactions,
                 driver.next_fetch,
                 driver.next_prefetch,
                 driver.next_write,
                 driver.current_grant_source);
    for (int i = 0; i < kTransactions; ++i) {
        std::fprintf(stderr, "[TIMEOUT-TX] tx=%d state=%s write=%d\n", i, state_name(driver.tx_state[i]), driver.tx_write_done[i]);
    }
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
