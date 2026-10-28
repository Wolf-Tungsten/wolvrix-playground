#pragma once

// Diagnostic-only wrapper instrumentation. Reuses the wrapper's clock reads;
// it never changes a model, and writes the trace only after simulation exits.
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace repcut_cycle_trace {
inline constexpr uint32_t capacity = 210000;
inline constexpr uint32_t parts = 32;
inline constexpr uint32_t fields = 3;
inline std::array<uint32_t*, parts> lanes{};
inline uint32_t* globals = nullptr;
inline std::atomic<uint32_t> cursor{0};
inline uint32_t count = 0;
inline const char* filename = nullptr;

[[noreturn]] inline void fail(const char* reason) {
    std::fprintf(stderr, "[cycle-trace] FAIL %s\n", reason);
    std::abort();
}

inline uint32_t narrow(uint64_t value) {
    if (value >= std::numeric_limits<uint32_t>::max()) fail("duration overflow");
    return static_cast<uint32_t>(value);
}

inline void dump() {
    FILE* file = std::fopen(filename, "wb");
    if (!file) fail("cannot open trace file");
    const auto write = [&](const void* data, size_t size) {
        if (std::fwrite(data, 1, size, file) != size) fail("cannot write trace file");
    };
    write("GRHCYC01", 8);
    const uint32_t header[] = {1, count, parts, fields};
    write(header, sizeof(header));
    write(globals, size_t(count) * 4 * sizeof(uint32_t));
    for (const auto* lane : lanes) write(lane, size_t(count) * fields * sizeof(uint32_t));
    if (std::fclose(file)) fail("cannot close trace file");
    std::fprintf(stderr, "[cycle-trace] PASS steps=%u parts=%u file=%s\n", count, parts, filename);
}

inline void begin(uint64_t step, bool clock, bool reset) {
    if (!globals) {
        filename = std::getenv("REPCUT_CYCLE_TRACE_FILE");
        if (!filename || !*filename) fail("REPCUT_CYCLE_TRACE_FILE required for diagnostic binary");
        globals = static_cast<uint32_t*>(std::aligned_alloc(64, size_t(capacity) * 4 * 4));
        if (!globals) fail("global allocation failed");
        std::memset(globals, 0xff, size_t(capacity) * 4 * 4);
        for (auto& lane : lanes) {
            lane = static_cast<uint32_t*>(std::aligned_alloc(64, size_t(capacity) * fields * 4));
            if (!lane) fail("lane allocation failed");
            std::memset(lane, 0xff, size_t(capacity) * fields * 4);
        }
        if (std::atexit(dump)) fail("atexit failed");
    }
    if (step != uint64_t(count) + 1 || step > capacity) fail("unexpected step or capacity exceeded");
    cursor.store(count, std::memory_order_relaxed);
    globals[size_t(count) * 4] = unsigned(clock) | (unsigned(reset) << 1);
    ++count;
}

inline void record(unsigned part, unsigned phase, uint64_t ns) {
    // Each lane has one writer; existing dispatch/done barriers publish the
    // cursor and finish all writes before the next step. No new barrier/clock.
    lanes[part][size_t(cursor.load(std::memory_order_relaxed)) * fields + phase] = narrow(ns);
}

inline void finish(uint64_t input, uint64_t eval, uint64_t update) {
    auto* row = globals + size_t(cursor.load(std::memory_order_relaxed)) * 4;
    row[1] = narrow(input);
    row[2] = narrow(eval);
    row[3] = narrow(update);
}
}  // namespace repcut_cycle_trace
