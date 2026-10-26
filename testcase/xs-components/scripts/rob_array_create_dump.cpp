// Build once against each model ABI; capture every output word without exclusions.
#define ROB_BENCH_NO_MAIN
#include ROB_BENCH_SOURCE

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    rob_bench::TraceFile trace;
    if (!rob_bench::open_trace(argv[1], trace)) return 1;
    auto model = std::make_unique<GrhSIM_Rob>();
    model->init();
    std::FILE *output = std::fopen(argv[2], "wb");
    if (!output) return 1;
    const std::uint64_t header[]{UINT64_C(0x4152524159435231), trace.cycles, rob_bench::kOutWords};
    bool ok = std::fwrite(header, sizeof(header), 1, output) == 1;
    std::vector<std::uint64_t> words(rob_bench::kOutWords, 0);
    for (std::uint64_t cycle = 0; ok && cycle < trace.cycles; ++cycle) {
        rob_bench::eval_grhsim_trace_out(*model, rob_bench::trace_record(trace, cycle), words.data());
        ok = std::fwrite(words.data(), sizeof(std::uint64_t), words.size(), output) == words.size();
    }
    ok = std::fclose(output) == 0 && ok;
    const auto cycles = trace.cycles;
    rob_bench::close_trace(trace);
    std::cout << "[ARRAY_CREATE_DUMP] cycles=" << cycles << " words=" << words.size()
              << " exclusions=0 status=" << (ok ? "pass" : "fail") << '\n';
    return ok ? 0 : 1;
}
