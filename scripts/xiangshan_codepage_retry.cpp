#include <cerrno>
#include <cstdio>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

// Preserve already collapsed extents when one extent temporarily lacks memory.
// Only the process-local startup code mapping uses MADV_COLLAPSE (Linux value 25).
extern "C" int madvise(void* address, size_t length, int advice) noexcept {
    int result = static_cast<int>(syscall(SYS_madvise, address, length, advice));
    if (advice != 25 || result == 0) return result;
    unsigned retries = 0;
    while (result != 0 && (errno == ENOMEM || errno == EAGAIN) && retries < 100) {
        const timespec pause{0, 20000000};
        nanosleep(&pause, nullptr);
        ++retries;
        result = static_cast<int>(syscall(SYS_madvise, address, length, advice));
    }
    if (result == 0 && retries != 0)
        std::fprintf(stderr, "[codepage-retry] retained progress, retries=%u bytes=%zu\n", retries, length);
    return result;
}
