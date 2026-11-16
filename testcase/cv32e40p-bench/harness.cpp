#ifdef CV32_GRHSIM
#include "grhsim_Cv32Bench.hpp"
using Model = GrhSIM_Cv32Bench;
#else
#include "VCv32Bench.h"
#include "verilated.h"
using Model = VCv32Bench;
#endif
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <sched.h>
#include <sstream>
#include <string>
#include <vector>
#include <sys/personality.h>

using Clock = std::chrono::steady_clock;
static double seconds(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}
static std::string hex(const std::string &s) {
    std::string out;
    for (unsigned char c : s) { out += "0123456789abcdef"[c >> 4]; out += "0123456789abcdef"[c & 15]; }
    return out;
}
static void audit(const std::string &prefix) {
    for (const auto *name : {"maps", "numa_maps", "status"}) {
        std::ifstream in(std::string("/proc/self/") + name);
        std::ofstream out(prefix + "." + name); out << in.rdbuf();
    }
    unsigned tasks = 0;
    for (const auto &unused : std::filesystem::directory_iterator("/proc/self/task")) { (void)unused; ++tasks; }
    cpu_set_t mask; CPU_ZERO(&mask); sched_getaffinity(0, sizeof(mask), &mask);
    std::ofstream out(prefix + ".placement.json");
    out << "{\"threads\":" << tasks << ",\"cpu\":" << sched_getcpu()
        << ",\"affinity_count\":" << CPU_COUNT(&mask)
        << ",\"aslr_disabled\":" << ((personality(0xffffffffUL) & ADDR_NO_RANDOMIZE) ? "true" : "false") << "}\n";
}
int main(int argc, char **argv) {
    unsigned repeats = 1; uint64_t limit = 50000000;
    std::string trace_path, audit_path;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (i+1 == argc) return 2;
        if (arg == "--repeats") repeats = std::stoul(argv[++i]);
        else if (arg == "--max-cycles") limit = std::stoull(argv[++i]);
        else if (arg == "--trace") trace_path = argv[++i];
        else if (arg == "--audit") audit_path = argv[++i];
        else return 2;
    }
    if (!repeats || !limit) return 2;
#ifndef CV32_GRHSIM
    auto context = std::make_unique<VerilatedContext>();
    context->threads(1); context->randReset(0);
#endif
    double init_s = 0, sim_s = 0;
    uint64_t total_cycles = 0, completed_cycles = 0;
    std::string expected_uart;
    std::ofstream trace;
    if (!trace_path.empty()) { trace.open(trace_path, std::ios::binary); if (!trace) return 3; }
    for (unsigned rep = 0; rep < repeats; ++rep) {
        auto started = Clock::now();
#ifdef CV32_GRHSIM
        auto model = std::make_unique<Model>();
        model->init();
#else
        auto model = std::make_unique<Model>(context.get());
#endif
        auto &m = *model;
        m.clk_i = 0; m.rst_ni = 0; m.load_en_i = 0; m.load_addr_i = 0; m.load_data_i = 0; m.eval();
        std::ifstream image("image/workload.bin", std::ios::binary);
        if (!image) return 7;
        std::vector<unsigned char> bytes(std::istreambuf_iterator<char>(image), {});
        if (bytes.empty() || bytes.size() % 4 || bytes.size() > 4*1024*1024) return 7;
        m.load_en_i = 1;
        for (std::size_t pos = 0; pos < bytes.size(); pos += 4) {
            m.load_addr_i = pos;
            m.load_data_i = uint32_t(bytes[pos]) | (uint32_t(bytes[pos+1]) << 8) |
                           (uint32_t(bytes[pos+2]) << 16) | (uint32_t(bytes[pos+3]) << 24);
            m.clk_i = 0; m.eval(); m.clk_i = 1; m.eval();
        }
        m.load_en_i = 0; m.clk_i = 0; m.eval();
        for (unsigned i = 0; i < 4; ++i) { m.clk_i = 1; m.eval(); m.clk_i = 0; m.eval(); }
        m.rst_ni = 1;
        init_s += seconds(started);
        if (!audit_path.empty() && rep == 0) audit(audit_path + ".start");
        std::string uart; uint64_t cycle = 0;
        started = Clock::now();
        for (; cycle < limit; ++cycle) {
            m.clk_i = 0; m.eval();
            if (trace.is_open()) {
                std::array<uint32_t, 9> event{uint32_t(cycle), uint32_t(cycle >> 32),
                    uint32_t(m.obs_ireq_o), m.obs_ireq_o ? uint32_t(m.obs_iaddr_o) : 0,
                    uint32_t(m.obs_dreq_o), m.obs_dreq_o ? uint32_t(m.obs_daddr_o) : 0,
                    m.obs_dreq_o ? uint32_t(m.obs_dwe_o) : 0,
                    m.obs_dreq_o ? uint32_t(m.obs_dbe_o) : 0,
                    (m.obs_dreq_o && m.obs_dwe_o) ? uint32_t(m.obs_dwdata_o) : 0};
                trace.write(reinterpret_cast<const char *>(event.data()), sizeof(event));
            }
            m.clk_i = 1; m.eval();
            if (m.uart_valid_o) uart += char(m.uart_data_o);
            if (m.fault_o) { std::cerr << "bus fault at cycle " << cycle << '\n'; return 4; }
            if (m.exit_valid_o) break;
        }
        sim_s += seconds(started);
        if (!m.exit_valid_o || m.exit_code_o) {
            std::cerr << "exit failure cycles=" << cycle << " valid=" << unsigned(m.exit_valid_o)
                      << " code=" << m.exit_code_o << " uart=" << uart << '\n'; return 5;
        }
        ++cycle;
        if (rep && (uart != expected_uart || cycle != completed_cycles)) return 6;
        expected_uart = uart; completed_cycles = cycle; total_cycles += cycle;
        if (!audit_path.empty() && rep+1 == repeats) audit(audit_path + ".end");
#if defined(CV32_GRHSIM) && WOLVRIX_GRHSIM_PERF
        const auto p = m.perf_counters();
        std::cout << "CV32_PERF {\"evals\":" << p.evalCount << ",\"rounds\":" << p.totalRoundCount
                  << ",\"round1\":" << p.round1Count << ",\"round2\":" << p.round2Count
                  << ",\"compute_batches\":" << p.computeBatchExecCount
                  << ",\"commit_batches\":" << p.commitBatchExecCount
                  << ",\"scheduled_memory_reads\":" << p.scheduledMemoryReads
                  << ",\"touched_shadows\":" << p.touchedStateShadowCount
                  << ",\"touched_writes\":" << p.touchedWriteCount << "}\n";
#endif
    }
    std::cout.precision(12);
    std::cout << "CV32_RESULT {\"repeats\":" << repeats << ",\"cycles\":" << completed_cycles
              << ",\"total_cycles\":" << total_cycles << ",\"exit_code\":0,\"init_s\":" << init_s
              << ",\"sim_s\":" << sim_s << ",\"uart_hex\":\"" << hex(expected_uart) << "\"}\n";
    return 0;
}
