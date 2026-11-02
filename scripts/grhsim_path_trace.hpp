#pragma once
// Opt-in diagnostic only. Existing worker barriers publish each step context.
#include "grhsim_cp_config.hpp"
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <vector>
#include <sys/syscall.h>
#include <unistd.h>

namespace grhsim_path_trace {
using Clock = std::chrono::steady_clock;
struct Record {
    uint64_t step, start, end, thread;
    uint32_t part, batch, round, word, mask, kind, clock, after_commit;
};
static_assert(sizeof(Record) == 64);
struct alignas(64) Lane { std::vector<Record> records; };
inline std::array<Lane, partition_count + 1> lanes;
inline bool initialized = false, enabled = false, previous_reset = true;
inline uint64_t current_step = 0, nonreset_steps = 0, window_steps = 0, window_index = 0;
inline uint32_t clock_level = 0, warmup = 1000, cycles = 10000, stride = 64;
inline uint32_t selected_part = UINT32_MAX;
inline const char* filename = nullptr;
inline thread_local uint32_t lane_id = UINT32_MAX, round_id = 0, after_commit = 0;
inline thread_local uint64_t thread_id = 0;

[[noreturn]] inline void fail(const char* message) {
    std::fprintf(stderr, "[critical-path] FAIL %s\n", message);
    std::abort();
}
inline uint32_t option(const char* name, uint32_t fallback) {
    const auto* value = std::getenv(name);
    if (!value) return fallback;
    char* end; const auto n = std::strtoull(value, &end, 10);
    if (!*value || *end || *value == '-' || n > UINT32_MAX) fail("invalid integer option");
    return uint32_t(n);
}
inline uint64_t timestamp(Clock::time_point value) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch()).count();
}
inline void dump() {
    if (window_steps != uint64_t(cycles) * 2) fail("incomplete post-reset sampling window");
    FILE* stream = std::fopen(filename, "wb");
    if (!stream) fail("cannot open trace");
    const auto write = [&](const void* data, size_t size) {
        if (std::fwrite(data, 1, size, stream) != size) fail("trace write failed");
    };
    write("GRHCP001", 8);
    const uint32_t header[] = {1, sizeof(Record), partition_count, warmup, cycles, stride, selected_part, 0};
    uint64_t count = 0;
    for (const auto& lane : lanes) count += lane.records.size();
    write(header, sizeof(header)); write(&count, sizeof(count));
    for (const auto& lane : lanes) write(lane.records.data(), lane.records.size() * sizeof(Record));
    if (std::fclose(stream)) fail("trace close failed");
    std::fprintf(stderr, "[critical-path] PASS steps=%llu records=%llu file=%s\n",
        (unsigned long long)window_steps, (unsigned long long)count, filename);
}
inline void begin(uint64_t step, bool clock, bool reset) {
    if (!initialized) {
        filename = std::getenv("GRHSIM_CP_TRACE");
        if (!filename || !*filename) fail("GRHSIM_CP_TRACE is required");
        warmup = option("GRHSIM_CP_WARMUP", 1000); cycles = option("GRHSIM_CP_CYCLES", 10000);
        stride = option("GRHSIM_CP_STRIDE", 64); selected_part = option("GRHSIM_CP_PART", UINT32_MAX);
        if (!cycles || cycles > 1000000 || warmup > 1000000 ||
            (selected_part != UINT32_MAX && selected_part >= partition_count)) fail("invalid window or part");
        for (auto& lane : lanes) lane.records.reserve(size_t(cycles) * 6);
        if (std::atexit(dump)) fail("atexit registration");
        initialized = true;
    }
    if (step != current_step + 1) fail("non-consecutive model steps");
    current_step = step; clock_level = clock; enabled = false;
    if (reset) {
        if (!previous_reset) fail("reset reasserted during diagnostic run");
        return;
    }
    previous_reset = false;
    window_index = nonreset_steps++;
    enabled = window_index >= uint64_t(warmup)*2 && window_index < uint64_t(warmup+cycles)*2;
    if (enabled) ++window_steps;
}
inline void enter(uint32_t part) {
    lane_id = part; round_id = 0; after_commit = 0;
    if (!thread_id) thread_id = uint64_t(syscall(SYS_gettid));
}
inline void phase(uint32_t part, uint32_t kind, Clock::time_point start, Clock::time_point end) {
    if (!enabled) return;
    if (part > partition_count || end < start) fail("invalid phase timestamp");
    if (!thread_id) thread_id = uint64_t(syscall(SYS_gettid));
    lanes[part].records.push_back({current_step,timestamp(start),timestamp(end),thread_id,
        part,UINT32_MAX,0,UINT32_MAX,0,kind,clock_level,0});
}
inline void round(uint64_t n) { round_id = uint32_t(n); }
inline void committed(bool activated) { after_commit = activated; }
inline bool sample() {
    // Sample adjacent half-cycles together; include both clock levels.
    return enabled && stride && lane_id == selected_part &&
        ((window_index/2 - warmup) % stride == 0);
}
template<class F> inline void batch(uint32_t id, uint32_t kind, uint32_t word, uint32_t mask, F&& fn) {
    if (!sample()) { fn(); return; }
    const auto start = Clock::now(); fn(); const auto end = Clock::now();
    lanes[lane_id].records.push_back({current_step,timestamp(start),timestamp(end),thread_id,
        lane_id,id,round_id,word,mask,kind,clock_level,after_commit});
}
} // namespace grhsim_path_trace
