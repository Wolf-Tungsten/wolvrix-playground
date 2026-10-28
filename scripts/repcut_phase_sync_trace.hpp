#pragma once

// Diagnostic-only instrumentation for the Host-side all-spin phase window.
// It records the release, Host-batch, residual wait, and total time for each
// phase. It is included only in wrapper copies used by the trace builder.

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <chrono>

namespace repcut_phase_sync_trace {

using Clock = std::chrono::steady_clock;

struct Stats {
  std::uint64_t calls{};
  std::uint64_t dispatch_ns{};
  std::uint64_t host_ns{};
  std::uint64_t wait_ns{};
  std::uint64_t total_ns{};
};

inline std::array<Stats, 5> stats{};
inline const char* output_path = nullptr;
inline bool registered = false;

inline Clock::time_point now() {
  return Clock::now();
}

inline std::uint64_t elapsed_ns(Clock::time_point begin, Clock::time_point end) {
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
}

inline void dump() {
  if (output_path == nullptr || *output_path == '\0') {
    return;
  }
  FILE* file = std::fopen(output_path, "w");
  if (file == nullptr) {
    std::fprintf(stderr, "[phase-sync-trace] cannot open %s\n", output_path);
    return;
  }
  static constexpr const char* names[] = {
      "load", "early_eval", "early_update", "normal_eval", "normal_update"};
  for (std::size_t i = 0; i < stats.size(); ++i) {
    const auto& row = stats[i];
    std::fprintf(file,
                 "{\"record_type\":\"phase_sync\",\"schema_version\":1,"
                 "\"phase\":\"%s\",\"calls\":%llu,"
                 "\"dispatch_ns\":%llu,\"host_ns\":%llu,"
                 "\"wait_ns\":%llu,\"total_ns\":%llu}\n",
                 names[i],
                 static_cast<unsigned long long>(row.calls),
                 static_cast<unsigned long long>(row.dispatch_ns),
                 static_cast<unsigned long long>(row.host_ns),
                 static_cast<unsigned long long>(row.wait_ns),
                 static_cast<unsigned long long>(row.total_ns));
  }
  std::fclose(file);
  std::fprintf(stderr, "[phase-sync-trace] PASS file=%s\n", output_path);
}

inline void record(unsigned phase,
                   std::uint64_t dispatch_ns,
                   std::uint64_t host_ns,
                   std::uint64_t wait_ns,
                   std::uint64_t total_ns) {
  if (phase >= stats.size()) {
    return;
  }
  if (!registered) {
    output_path = std::getenv("REPCUT_PHASE_SYNC_TRACE_FILE");
    if (output_path == nullptr || *output_path == '\0') {
      return;
    }
    std::atexit(dump);
    registered = true;
  }
  auto& row = stats[phase];
  ++row.calls;
  row.dispatch_ns += dispatch_ns;
  row.host_ns += host_ns;
  row.wait_ns += wait_ns;
  row.total_ns += total_ns;
}

}  // namespace repcut_phase_sync_trace
