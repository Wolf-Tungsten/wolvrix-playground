#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool redirect_valid = false;
    bool redirect_level = false;
    bool redirect_robIdx_flag = false;
    std::uint16_t redirect_robIdx_value = 0;

    bool rob_pendingPtr_flag = false;
    std::uint16_t rob_pendingPtr_value = 0;

    bool req_valid = false;
    std::uint16_t req_robIdx_value = 0;
    std::uint64_t req_vaddr = 0;
    std::uint64_t req_paddr = 0;
    std::uint16_t req_mask = 0;
    bool req_nc = false;
    bool req_mmio = false;

    bool mmioOut_ready = false;
    bool ncOut_ready = false;
    bool uncache_req_ready = false;
    bool uncache_idResp_valid = false;
    std::uint8_t uncache_idResp_mid = 0;
    std::uint8_t uncache_idResp_sid = 0;
    bool uncache_resp_valid = false;
    std::uint64_t uncache_resp_data = 0;
    bool uncache_resp_denied = false;
    bool uncache_resp_corrupt = false;
};

struct Outputs {
    bool flush = false;
    bool mmioSelect = false;
    bool slaveId_valid = false;
    std::uint8_t slaveId_bits = 0;
    bool mmioOut_valid = false;
    bool ncOut_valid = false;
    bool uncache_req_valid = false;
    std::uint64_t uncache_req_addr = 0;
    std::uint8_t uncache_req_mask = 0;
    bool exception_valid = false;
    std::uint64_t mmioRawData_lqData = 0;
    bool dbg_req_valid = false;
    bool dbg_slaveAccept = false;
    std::uint8_t dbg_uncacheState = 0;
    bool dbg_needFlushReg = false;
    std::uint8_t dbg_slaveId = 0;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

const char *phase_name(int phase)
{
    switch (phase) {
    case 0: return "pre-posedge";
    case 1: return "posedge";
    case 2: return "post-posedge";
    default: return "unknown";
    }
}

void drive_inputs(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim,
                  bool rst_n, const Stimulus &s)
{
    ref.rst_n = rst_n;
    ref.redirect_valid = s.redirect_valid;
    ref.redirect_level = s.redirect_level;
    ref.redirect_robIdx_flag = s.redirect_robIdx_flag;
    ref.redirect_robIdx_value = s.redirect_robIdx_value;
    ref.rob_pendingPtr_flag = s.rob_pendingPtr_flag;
    ref.rob_pendingPtr_value = s.rob_pendingPtr_value;
    ref.req_valid = s.req_valid;
    ref.req_robIdx_value = s.req_robIdx_value;
    ref.req_vaddr = s.req_vaddr;
    ref.req_paddr = s.req_paddr;
    ref.req_mask = s.req_mask;
    ref.req_nc = s.req_nc;
    ref.req_mmio = s.req_mmio;
    ref.mmioOut_ready = s.mmioOut_ready;
    ref.ncOut_ready = s.ncOut_ready;
    ref.uncache_req_ready = s.uncache_req_ready;
    ref.uncache_idResp_valid = s.uncache_idResp_valid;
    ref.uncache_idResp_mid = s.uncache_idResp_mid;
    ref.uncache_idResp_sid = s.uncache_idResp_sid;
    ref.uncache_resp_valid = s.uncache_resp_valid;
    ref.uncache_resp_data = s.uncache_resp_data;
    ref.uncache_resp_denied = s.uncache_resp_denied;
    ref.uncache_resp_corrupt = s.uncache_resp_corrupt;

    grhsim.rst_n = rst_n;
    grhsim.redirect_valid = s.redirect_valid;
    grhsim.redirect_level = s.redirect_level;
    grhsim.redirect_robIdx_flag = s.redirect_robIdx_flag;
    grhsim.redirect_robIdx_value = s.redirect_robIdx_value;
    grhsim.rob_pendingPtr_flag = s.rob_pendingPtr_flag;
    grhsim.rob_pendingPtr_value = s.rob_pendingPtr_value;
    grhsim.req_valid = s.req_valid;
    grhsim.req_robIdx_value = s.req_robIdx_value;
    grhsim.req_vaddr = s.req_vaddr;
    grhsim.req_paddr = s.req_paddr;
    grhsim.req_mask = s.req_mask;
    grhsim.req_nc = s.req_nc;
    grhsim.req_mmio = s.req_mmio;
    grhsim.mmioOut_ready = s.mmioOut_ready;
    grhsim.ncOut_ready = s.ncOut_ready;
    grhsim.uncache_req_ready = s.uncache_req_ready;
    grhsim.uncache_idResp_valid = s.uncache_idResp_valid;
    grhsim.uncache_idResp_mid = s.uncache_idResp_mid;
    grhsim.uncache_idResp_sid = s.uncache_idResp_sid;
    grhsim.uncache_resp_valid = s.uncache_resp_valid;
    grhsim.uncache_resp_data = s.uncache_resp_data;
    grhsim.uncache_resp_denied = s.uncache_resp_denied;
    grhsim.uncache_resp_corrupt = s.uncache_resp_corrupt;
}

Outputs sample_ref(const VRef &ref)
{
    return Outputs{
        static_cast<bool>(ref.flush),
        static_cast<bool>(ref.mmioSelect),
        static_cast<bool>(ref.slaveId_valid),
        static_cast<std::uint8_t>(ref.slaveId_bits),
        static_cast<bool>(ref.mmioOut_valid),
        static_cast<bool>(ref.ncOut_valid),
        static_cast<bool>(ref.uncache_req_valid),
        static_cast<std::uint64_t>(ref.uncache_req_addr),
        static_cast<std::uint8_t>(ref.uncache_req_mask),
        static_cast<bool>(ref.exception_valid),
        static_cast<std::uint64_t>(ref.mmioRawData_lqData),
        static_cast<bool>(ref.dbg_req_valid),
        static_cast<bool>(ref.dbg_slaveAccept),
        static_cast<std::uint8_t>(ref.dbg_uncacheState),
        static_cast<bool>(ref.dbg_needFlushReg),
        static_cast<std::uint8_t>(ref.dbg_slaveId),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb &grhsim)
{
    return Outputs{
        grhsim.flush,
        grhsim.mmioSelect,
        grhsim.slaveId_valid,
        static_cast<std::uint8_t>(grhsim.slaveId_bits),
        grhsim.mmioOut_valid,
        grhsim.ncOut_valid,
        grhsim.uncache_req_valid,
        grhsim.uncache_req_addr,
        static_cast<std::uint8_t>(grhsim.uncache_req_mask),
        grhsim.exception_valid,
        grhsim.mmioRawData_lqData,
        grhsim.dbg_req_valid,
        grhsim.dbg_slaveAccept,
        static_cast<std::uint8_t>(grhsim.dbg_uncacheState),
        grhsim.dbg_needFlushReg,
        static_cast<std::uint8_t>(grhsim.dbg_slaveId),
    };
}

bool compare_outputs(const Outputs &ref, const Outputs &dut, int cycle, int phase)
{
    bool ok = true;
    auto mismatch_bool = [&](const char *name, bool a, bool b) {
        if (a != b) {
            std::fprintf(stderr,
                         "[MISMATCH] cycle=%d phase=%s %s ref=%u grhsim=%u\n",
                         cycle, phase_name(phase), name,
                         static_cast<unsigned>(a), static_cast<unsigned>(b));
            ok = false;
        }
    };
    auto mismatch_u8 = [&](const char *name, std::uint8_t a, std::uint8_t b) {
        if (a != b) {
            std::fprintf(stderr,
                         "[MISMATCH] cycle=%d phase=%s %s ref=0x%02x grhsim=0x%02x\n",
                         cycle, phase_name(phase), name,
                         static_cast<unsigned>(a), static_cast<unsigned>(b));
            ok = false;
        }
    };
    auto mismatch_u64 = [&](const char *name, std::uint64_t a, std::uint64_t b) {
        if (a != b) {
            std::fprintf(stderr,
                         "[MISMATCH] cycle=%d phase=%s %s ref=0x%016llx grhsim=0x%016llx\n",
                         cycle, phase_name(phase), name,
                         static_cast<unsigned long long>(a),
                         static_cast<unsigned long long>(b));
            ok = false;
        }
    };

    mismatch_bool("flush", ref.flush, dut.flush);
    mismatch_bool("mmioSelect", ref.mmioSelect, dut.mmioSelect);
    mismatch_bool("slaveId_valid", ref.slaveId_valid, dut.slaveId_valid);
    mismatch_u8("slaveId_bits", ref.slaveId_bits, dut.slaveId_bits);
    mismatch_bool("mmioOut_valid", ref.mmioOut_valid, dut.mmioOut_valid);
    mismatch_bool("ncOut_valid", ref.ncOut_valid, dut.ncOut_valid);
    mismatch_bool("uncache_req_valid", ref.uncache_req_valid, dut.uncache_req_valid);
    mismatch_u64("uncache_req_addr", ref.uncache_req_addr, dut.uncache_req_addr);
    mismatch_u8("uncache_req_mask", ref.uncache_req_mask, dut.uncache_req_mask);
    mismatch_bool("exception_valid", ref.exception_valid, dut.exception_valid);
    mismatch_u64("mmioRawData_lqData", ref.mmioRawData_lqData, dut.mmioRawData_lqData);
    mismatch_bool("dbg_req_valid", ref.dbg_req_valid, dut.dbg_req_valid);
    mismatch_bool("dbg_slaveAccept", ref.dbg_slaveAccept, dut.dbg_slaveAccept);
    mismatch_u8("dbg_uncacheState", ref.dbg_uncacheState, dut.dbg_uncacheState);
    mismatch_bool("dbg_needFlushReg", ref.dbg_needFlushReg, dut.dbg_needFlushReg);
    mismatch_u8("dbg_slaveId", ref.dbg_slaveId, dut.dbg_slaveId);
    return ok;
}

void print_trace(int cycle, int phase, const Stimulus &s, const Outputs &ref, const Outputs &dut)
{
    std::printf(
        "[TRACE] cycle=%d phase=%s "
        "req_v=%u req_mmio=%u req_nc=%u req_rob=0x%03x pptr=0x%03x "
        "req_rdy=%u id_v=%u id_mid=0x%02x id_sid=0x%x resp_v=%u resp_data=0x%016llx wb_rdy=%u "
        "ref_state=%u ref_req=%u ref_acc=%u ref_mmio=%u ref_flush=%u ref_wb=%u ref_raw=0x%016llx "
        "grh_state=%u grh_req=%u grh_acc=%u grh_mmio=%u grh_flush=%u grh_wb=%u grh_raw=0x%016llx\n",
        cycle, phase_name(phase),
        static_cast<unsigned>(s.req_valid),
        static_cast<unsigned>(s.req_mmio),
        static_cast<unsigned>(s.req_nc),
        static_cast<unsigned>(s.req_robIdx_value),
        static_cast<unsigned>(s.rob_pendingPtr_value),
        static_cast<unsigned>(s.uncache_req_ready),
        static_cast<unsigned>(s.uncache_idResp_valid),
        static_cast<unsigned>(s.uncache_idResp_mid),
        static_cast<unsigned>(s.uncache_idResp_sid),
        static_cast<unsigned>(s.uncache_resp_valid),
        static_cast<unsigned long long>(s.uncache_resp_data),
        static_cast<unsigned>(s.mmioOut_ready),
        static_cast<unsigned>(ref.dbg_uncacheState),
        static_cast<unsigned>(ref.dbg_req_valid),
        static_cast<unsigned>(ref.dbg_slaveAccept),
        static_cast<unsigned>(ref.mmioOut_valid),
        static_cast<unsigned>(ref.flush),
        static_cast<unsigned>(ref.exception_valid),
        static_cast<unsigned long long>(ref.mmioRawData_lqData),
        static_cast<unsigned>(dut.dbg_uncacheState),
        static_cast<unsigned>(dut.dbg_req_valid),
        static_cast<unsigned>(dut.dbg_slaveAccept),
        static_cast<unsigned>(dut.mmioOut_valid),
        static_cast<unsigned>(dut.flush),
        static_cast<unsigned>(dut.exception_valid),
        static_cast<unsigned long long>(dut.mmioRawData_lqData));
}

void eval_both(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim)
{
    ref.eval();
    grhsim.eval();
    ++main_time;
}

void phase_eval(VRef &ref, GrhSIM_xs_bugcase_tb &grhsim, bool clk)
{
    ref.clk = clk;
    grhsim.clk = clk;
    eval_both(ref, grhsim);
}

Stimulus make_cycle(int cycle)
{
    Stimulus s;
    s.rob_pendingPtr_flag = false;
    s.rob_pendingPtr_value = 0x012;
    s.req_mmio = true;
    s.req_nc = false;
    s.req_mask = 0x00f0;
    s.req_paddr = 0x0000000040600004ULL;
    s.req_vaddr = 0x0000000080001ceeULL;
    s.req_robIdx_value = 0x012;
    s.uncache_idResp_mid = 0x05;
    s.uncache_idResp_sid = 0x9;
    s.mmioOut_ready = true;

    switch (cycle) {
    case 0:
        s.req_valid = true;
        break;
    case 1:
        s.req_valid = true;
        s.uncache_req_ready = true;
        break;
    case 2:
        s.uncache_idResp_valid = true;
        break;
    case 3:
        s.uncache_resp_valid = true;
        s.uncache_resp_data = 0x1122334455667788ULL;
        break;
    case 4:
        break;
    case 5:
        s.req_valid = true;
        s.req_robIdx_value = 0x013;
        s.rob_pendingPtr_value = 0x013;
        s.req_paddr = 0x0000000040600004ULL;
        s.req_vaddr = 0x00000000800001cf2ULL;
        break;
    case 6:
        s.req_valid = true;
        s.req_robIdx_value = 0x013;
        s.rob_pendingPtr_value = 0x013;
        s.req_paddr = 0x0000000040600004ULL;
        s.req_vaddr = 0x00000000800001cf2ULL;
        s.uncache_req_ready = true;
        break;
    case 7:
        s.req_valid = false;
        s.uncache_idResp_valid = true;
        s.uncache_idResp_sid = 0x6;
        break;
    case 8:
        s.uncache_resp_valid = true;
        s.uncache_resp_data = 0xaabbccddeeff0011ULL;
        s.mmioOut_ready = false;
        break;
    case 9:
        s.mmioOut_ready = false;
        break;
    case 10:
        s.mmioOut_ready = true;
        break;
    case 11:
        s.req_valid = true;
        s.req_robIdx_value = 0x014;
        s.rob_pendingPtr_value = 0x015;
        s.req_paddr = 0x0000000040600004ULL;
        s.req_vaddr = 0x000000008000027c0ULL;
        break;
    case 12:
        s.req_valid = true;
        s.req_robIdx_value = 0x014;
        s.rob_pendingPtr_value = 0x015;
        s.req_paddr = 0x0000000040600004ULL;
        s.req_vaddr = 0x000000008000027c0ULL;
        s.redirect_valid = true;
        s.redirect_level = true;
        s.redirect_robIdx_value = 0x014;
        break;
    case 13:
        break;
    default:
        break;
    }
    return s;
}

} // namespace

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);
    Verilated::randReset(0);
    Verilated::randSeed(1);

    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

    Stimulus init{};
    drive_inputs(ref, grhsim, false, init);
    for (int i = 0; i < 2; ++i) {
        phase_eval(ref, grhsim, false);
        phase_eval(ref, grhsim, true);
        phase_eval(ref, grhsim, false);
    }

    int mismatches = 0;
    const int cycles = 14;
    for (int cycle = 0; cycle < cycles; ++cycle) {
        const Stimulus s = make_cycle(cycle);
        drive_inputs(ref, grhsim, true, s);

        for (int phase = 0; phase < 3; ++phase) {
            phase_eval(ref, grhsim, phase == 1);
            const Outputs ref_out = sample_ref(ref);
            const Outputs dut_out = sample_grhsim(grhsim);
            print_trace(cycle, phase, s, ref_out, dut_out);
            if (!compare_outputs(ref_out, dut_out, cycle, phase)) {
                ++mismatches;
            }
        }
    }

    if (mismatches != 0) {
        std::fprintf(stderr, "[FAIL] mismatches=%d\n", mismatches);
        return 1;
    }

    std::printf("[PASS] CASE_007 ref == grhsim\n");
    return 0;
}
