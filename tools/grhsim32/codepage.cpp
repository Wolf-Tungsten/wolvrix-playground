#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <link.h>
#include <sys/mman.h>
#include <sys/auxv.h>
#include <unistd.h>

// Remap executable code at startup while preserving all virtual addresses.
// This DSO executes outside the regions it remaps.
namespace {
constexpr std::uintptr_t huge = 2u * 1024u * 1024u;
constexpr int collapse = 25; // MADV_COLLAPSE, Linux 6.1+.
struct Run { const char *mode; std::size_t bytes{}, huge_bytes{}, regions{}; };

[[noreturn]] void fail(const char *what) {
    std::fprintf(stderr, "[codepage] FAIL %s: %s\n", what, std::strerror(errno));
    std::_Exit(123);
}

std::size_t anon_huge_bytes(std::uintptr_t start, std::uintptr_t end) {
    FILE *in = std::fopen("/proc/self/smaps", "r");
    if (!in) fail("smaps");
    char line[512];
    unsigned long a{}, b{}, kb{};
    bool selected = false;
    std::size_t total = 0;
    while (std::fgets(line, sizeof(line), in)) {
        if (std::sscanf(line, "%lx-%lx", &a, &b) == 2) {
            selected = a >= start && b <= end;
        } else if (selected && std::sscanf(line, "AnonHugePages: %lu kB", &kb) == 1) {
            total += kb * 1024u;
        }
    }
    std::fclose(in);
    return total;
}

int visit(dl_phdr_info *info, std::size_t, void *opaque) {
    if (info->dlpi_name && *info->dlpi_name) return 0;
    auto &run = *static_cast<Run *>(opaque);
    for (std::size_t i = 0; i < info->dlpi_phnum; ++i) {
        const auto &ph = info->dlpi_phdr[i];
        if (ph.p_type != PT_LOAD || ph.p_flags != (PF_R | PF_X)) continue;
        const auto lo = info->dlpi_addr + ph.p_vaddr;
        const auto hi = lo + ph.p_memsz;
        const auto begin = (lo + huge - 1) & ~(huge - 1);
        const auto end = hi & ~(huge - 1);
        if (begin >= end) continue;
        const auto count = end - begin;
        void *original = reinterpret_cast<void *>(begin);
        if (std::strcmp(run.mode, "file")) {
            void *reserve = mmap(nullptr, count + huge, PROT_READ | PROT_WRITE,
                                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            if (reserve == MAP_FAILED) fail("mmap");
            auto raw = reinterpret_cast<std::uintptr_t>(reserve);
            auto aligned = (raw + huge - 1) & ~(huge - 1);
            if (aligned > raw && munmap(reserve, aligned - raw)) fail("unmap prefix");
            const auto tail = raw + count + huge - (aligned + count);
            if (tail && munmap(reinterpret_cast<void *>(aligned + count), tail)) fail("unmap suffix");
            void *copy = reinterpret_cast<void *>(aligned);
            const bool large = !std::strcmp(run.mode, "thp") || !std::strcmp(run.mode, "auto");
            if (madvise(copy, count, large ? MADV_HUGEPAGE : MADV_NOHUGEPAGE)) fail("madvise policy");
            std::memcpy(copy, original, count);
            if (std::memcmp(copy, original, count)) fail("copied bytes differ");
            if (large && madvise(copy, count, collapse) && std::strcmp(run.mode, "auto"))
                fail("MADV_COLLAPSE");
            if (mprotect(copy, count, PROT_READ | PROT_EXEC)) fail("mprotect RX");
            if (mremap(copy, count, count, MREMAP_MAYMOVE | MREMAP_FIXED, original) != original)
                fail("mremap exact address");
        }
        const auto observed = anon_huge_bytes(begin, end);
        const auto expected = !std::strcmp(run.mode, "thp") ? count : 0;
        if (std::strcmp(run.mode, "auto") && observed != expected) fail("unexpected huge-page coverage");
        std::fprintf(stderr, "[codepage] region=%lx-%lx bytes=%zu anon_huge=%zu\n",
                     begin, end, count, observed);
        run.bytes += count;
        run.huge_bytes += observed;
        ++run.regions;
    }
    return 1;
}

__attribute__((constructor)) void initialize() {
    // A simulator may load the preload DSO again while bringing up its
    // reference model.  The first constructor has already remapped the main
    // executable before worker creation; a second pass would see only the
    // already-replaced mappings and would fail the strict coverage check.
    // Keep the probe process-local and one-shot through the process
    // environment, which is shared by later dlopen namespaces.
    // AT_RANDOM changes across exec(), even when helper programs exec in the
    // same PID. A later dlopen namespace in this executable sees the same value.
    char execution[64];
    const auto *random = reinterpret_cast<const unsigned char *>(getauxval(AT_RANDOM));
    int position = std::snprintf(execution, sizeof(execution), "%d:", getpid());
    if (random)
        for (unsigned i = 0; i < 16; ++i)
            position += std::snprintf(execution + position, sizeof(execution) - position, "%02x", random[i]);
    const char *previous = std::getenv("REPCUT_CODEPAGE_ONCE_DONE");
    if (previous && !std::strcmp(previous, execution)) return;
    const char *mode = std::getenv("REPCUT_CODEPAGE_MODE");
    if (!mode) return;
    if (std::strcmp(mode, "file") && std::strcmp(mode, "small") && std::strcmp(mode, "thp") && std::strcmp(mode, "auto"))
        fail("unknown mode");
    DIR *tasks = opendir("/proc/self/task");
    if (!tasks) fail("task directory");
    unsigned threads = 0;
    while (auto *entry = readdir(tasks)) if (entry->d_name[0] != '.') ++threads;
    closedir(tasks);
    if (threads != 1) fail("remap must precede worker creation");
    const auto start = std::chrono::steady_clock::now();
    Run run{mode};
    dl_iterate_phdr(visit, &run);
    if (!run.regions) {
        if (std::strcmp(mode, "auto")) fail("no complete executable huge-page region");
        return;
    }
    if (setenv("REPCUT_CODEPAGE_ONCE_DONE", execution, 1)) fail("setenv marker");
    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::fprintf(stderr, "[codepage] PASS mode=%s bytes=%zu anon_huge=%zu regions=%zu setup_s=%.6f pid=%d\n",
                 mode, run.bytes, run.huge_bytes, run.regions, elapsed, getpid());
}
}
