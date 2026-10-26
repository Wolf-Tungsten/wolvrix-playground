// Bounded diagnostic over the exact frozen ROB trace and bench adapters.
#define ROB_BENCH_NO_MAIN
#include ROB_BENCH_SOURCE

#include <chrono>
#include <cstdlib>

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    char* end = nullptr;
    const auto limit = std::strtoull(argv[2], &end, 10);
    if (!end || *end || !limit) return 2;
    rob_bench::TraceFile trace;
    if (!rob_bench::open_trace(argv[1], trace)) return 1;
    const auto cycles = std::min<std::uint64_t>(limit, trace.cycles);
    auto model = std::make_unique<GrhSIM_Rob>();
    const auto begin = std::chrono::steady_clock::now();
    model->init();
    const auto initialized = std::chrono::steady_clock::now();
    std::vector<std::uint64_t> words(rob_bench::kOutWords, 0);
    std::uint64_t checksum = UINT64_C(14695981039346656037);
    for (std::uint64_t cycle = 0; cycle < cycles; ++cycle) {
        rob_bench::eval_grhsim_trace_out(*model, rob_bench::trace_record(trace, cycle), words.data());
        for (const auto word : words) {
            checksum ^= word;
            checksum *= UINT64_C(1099511628211);
        }
    }
    const auto finished = std::chrono::steady_clock::now();
#ifdef ROB_EXECUTION_COUNTS
    const auto* counterPath = std::getenv("WOLVRIX_GRHSIM_EXECUTION_COUNTS");
    if (!counterPath) return 2;
    auto* counterFile = std::fopen(counterPath, "w");
    if (!counterFile) return 1;
    model->dump_execution_counts(counterFile);
    if (std::fclose(counterFile)) return 1;
#endif
    std::cout << "cycles=" << cycles << " checksum=" << checksum
              << " init_seconds=" << std::chrono::duration<double>(initialized - begin).count()
              << " run_seconds=" << std::chrono::duration<double>(finished - initialized).count() << '\n';
    rob_bench::close_trace(trace);
    return 0;
}
