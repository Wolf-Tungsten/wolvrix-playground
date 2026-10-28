#pragma once

// Diagnostic only. Time calls in the dispatcher without recompiling compute
// bodies. Labels come from independent wrapper traces, never this probe.
#include "batch_probe_sizes.hpp"
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <vector>

namespace repcut_batch_probe {
using Clock = std::chrono::steady_clock;
constexpr unsigned waves = 4; // Last bucket includes round four and later.
#ifdef REPCUT_GROUP_COUNTS_ONLY
constexpr bool counts_only = true;
#else
constexpr bool counts_only = false;
#endif
struct GroupCounter { std::uint64_t entries{}, repeated{}; };
struct Counter {
    std::uint64_t ns{}, calls{}, active{}, all_on{};
    std::array<std::uint64_t, 8> entry_bits{};
};
struct Sample {
    std::uint64_t step{}, eval_ns{}, active_ns{};
    unsigned clock{}, scope{}, rounds{};
    std::uint64_t group_entries{}, repeated_entries{};
};
struct Lane {
    std::vector<Counter> counters = std::vector<Counter>(4 * waves * batch_capacity);
    std::vector<Sample> samples;
#ifdef REPCUT_GROUP_COUNTS_ONLY
    std::vector<GroupCounter> groups;
    std::vector<std::uint64_t> last_group_step;
#endif
};
inline std::array<Lane, partition_count> lanes;
inline std::once_flag initialized;
inline std::vector<unsigned char> labels, flags;
inline std::uint32_t label_steps = 0;
inline unsigned enabled_part = partition_count;
inline thread_local bool selected = false;
inline thread_local unsigned part = 0, context = 0, wave = 0;
inline thread_local Sample current;

[[noreturn]] inline void fail(const char* why) {
    std::fprintf(stderr, "[batch-probe] FAIL %s\n", why);
    std::abort();
}
inline void dump() {
    const char* path = std::getenv("REPCUT_BATCH_COUNTS");
    if (!path) fail("missing output path");
    FILE* out = std::fopen(path, "w");
    if (!out) fail("open output");
    std::fputs("part,clock,scope,wave,batch,ns,calls,active,all_on,bit0,bit1,bit2,bit3,bit4,bit5,bit6,bit7\n", out);
    for (unsigned p = 0; p < partition_count; ++p) {
        const auto& lane = lanes[p];
        for (unsigned c = 0; c < 4; ++c) for (unsigned w = 0; w < waves; ++w)
            for (unsigned b = 0; b < batch_capacity; ++b) {
                const auto& r = lane.counters[(c * waves + w) * batch_capacity + b];
                if (!r.calls) continue;
                std::fprintf(out, "%u,%u,%u,%u,%u,%llu,%llu,%llu,%llu", p, c / 2, c % 2 + 1, w, b,
                    (unsigned long long)r.ns, (unsigned long long)r.calls,
                    (unsigned long long)r.active, (unsigned long long)r.all_on);
                for (auto n : r.entry_bits) std::fprintf(out, ",%llu", (unsigned long long)n);
                std::fputc('\n', out);
            }
    }
    if (std::fclose(out)) fail("close counts");
    const char* sample_path = std::getenv("REPCUT_BATCH_STEPS");
    if (!sample_path || !(out = std::fopen(sample_path, "w"))) fail("open samples");
    std::fputs("part,step,clock,scope,eval_ns,active_ns,rounds,group_entries,repeated_entries\n", out);
    for (unsigned p = 0; p < partition_count; ++p) for (const auto& r : lanes[p].samples)
        std::fprintf(out, "%u,%llu,%u,%u,%llu,%llu,%u,%llu,%llu\n", p, (unsigned long long)r.step,
            r.clock, r.scope, (unsigned long long)r.eval_ns, (unsigned long long)r.active_ns, r.rounds,
            (unsigned long long)r.group_entries, (unsigned long long)r.repeated_entries);
    if (std::fclose(out)) fail("close samples");
#ifdef REPCUT_GROUP_COUNTS_ONLY
    const char* group_path = std::getenv("REPCUT_GROUP_COUNTS");
    if (!group_path || !(out = std::fopen(group_path, "w"))) fail("open group counts");
    std::fputs("part,clock,scope,wave,group,entries,repeated\n", out);
    for (unsigned c = 0; c < 4; ++c) for (unsigned w = 0; w < waves; ++w)
        for (unsigned g = 0; g < group_capacity; ++g) {
            const auto& r = lanes[enabled_part].groups[(c * waves + w) * group_capacity + g];
            if (!r.entries) continue;
            std::fprintf(out, "%u,%u,%u,%u,%u,%llu,%llu\n", enabled_part,c/2,c%2+1,w,g,
                (unsigned long long)r.entries,(unsigned long long)r.repeated);
        }
    if (std::fclose(out)) fail("close group counts");
#endif
    std::fprintf(stderr, "[batch-probe] PASS part=%u samples=%zu\n", enabled_part, lanes[enabled_part].samples.size());
}
inline void initialize() {
    const char* path = std::getenv("REPCUT_BATCH_LABELS");
    const char* part_text = std::getenv("REPCUT_PROFILE_PART");
    if (!path || !part_text) fail("missing labels or part");
    enabled_part = std::strtoul(part_text, nullptr, 10);
    if (enabled_part >= partition_count) fail("invalid part");
    FILE* in = std::fopen(path, "rb");
    if (!in) fail("open labels");
    char magic[8]; std::uint32_t header[3];
    if (std::fread(magic, 1, 8, in) != 8 || std::memcmp(magic, "GRHBAT01", 8) ||
        std::fread(header, sizeof(header), 1, in) != 1 || header[0] != 1 ||
        !header[1] || header[2] != partition_count) fail("invalid labels");
    label_steps = header[1]; flags.resize(label_steps);
    labels.resize(std::size_t(label_steps) * partition_count);
    if (std::fread(flags.data(), 1, flags.size(), in) != flags.size() ||
        std::fread(labels.data(), 1, labels.size(), in) != labels.size() ||
        std::fgetc(in) != EOF || std::fclose(in)) fail("label length");
    lanes[enabled_part].samples.reserve(4096);
#ifdef REPCUT_GROUP_COUNTS_ONLY
    lanes[enabled_part].groups.resize(4 * waves * group_capacity);
    lanes[enabled_part].last_group_step.resize(group_capacity);
#endif
    if (std::atexit(dump)) fail("atexit");
}
inline void begin(unsigned p, std::uint64_t step, bool clock, bool reset) {
    std::call_once(initialized, initialize);
    selected = false;
    if (p != enabled_part) return;
    if (!step || step > label_steps || flags[step - 1] != (unsigned(clock) | (unsigned(reset) << 1)))
        fail("clock/reset/step mismatch");
    const unsigned scope = labels[std::size_t(p) * label_steps + step - 1];
    if (!scope) return;
    if (reset || scope > 2) fail("invalid cohort");
    selected = true; part = p; context = unsigned(clock) * 2 + scope - 1; wave = 0;
    current = {step, 0, 0, unsigned(clock), scope, 0};
}
inline void round(std::uint64_t n) {
    if (!selected) return;
    if (!n) fail("zero round");
    current.rounds = n;
    wave = n < waves ? unsigned(n - 1) : waves - 1;
}
template<class F> inline void measure(unsigned batch, std::uint8_t active, std::uint8_t mask, F&& call) {
    if (batch >= batch_capacity || (active & ~mask)) fail("batch flags");
    auto& r = lanes[part].counters[(context * waves + wave) * batch_capacity + batch];
    ++r.calls;
    if (!active) { call(); return; }
    ++r.active; r.all_on += active == mask;
    for (unsigned i = 0; i < 8; ++i) r.entry_bits[i] += bool(active & (1u << i));
    if constexpr (counts_only) { call(); return; }
    const auto start = Clock::now();
    call();
    const auto end = Clock::now();
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    if (ns < 0) fail("negative duration");
    r.ns += ns; current.active_ns += ns;
}
inline void group(unsigned id) {
#ifdef REPCUT_GROUP_COUNTS_ONLY
    if (!selected) return;
    if (id >= group_capacity) fail("group capacity");
    auto& lane = lanes[part];
    auto& r = lane.groups[(context * waves + wave) * group_capacity + id];
    const bool repeated = lane.last_group_step[id] == current.step;
    ++r.entries; r.repeated += repeated;
    ++current.group_entries; current.repeated_entries += repeated;
    lane.last_group_step[id] = current.step;
#else
    fail("group hook in timing probe");
#endif
}
inline void end(std::uint64_t ns) {
    if (!selected) return;
    if (current.active_ns > ns) fail("time reconciliation");
    current.eval_ns = ns;
    lanes[part].samples.push_back(current);
    selected = false;
}
} // namespace repcut_batch_probe
