#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <vector>

namespace {
    template<unsigned Width>
    using Element = std::conditional_t<Width == 1, bool,
                    std::conditional_t<Width == 8, std::uint8_t, std::uint64_t>>;

    template<unsigned Count, unsigned Width>
    struct Input {
        std::uint64_t mask;
        std::array<Element<Width>, Count> data;
    };

    template<unsigned Width>
    constexpr std::uint64_t widthMask() {
        if constexpr (Width == 64) return UINT64_MAX;
        else return (UINT64_C(1) << Width) - 1;
    }

    template<unsigned Count, unsigned Width, std::size_t... I>
    std::uint64_t eagerImpl(const Input<Count, Width> &input, std::index_sequence<I...>) {
        // The expanded circuit: eager per-element AND (or mux) and a left OR fold.
        return (UINT64_C(0) | ... |
                ((UINT64_C(0) - ((input.mask >> I) & 1)) &
                 static_cast<std::uint64_t>(input.data[I]) & widthMask<Width>()));
    }

    template<unsigned Count, unsigned Width>
    __attribute__((noinline)) std::uint64_t eager(const Input<Count, Width> &input) {
        return eagerImpl(input, std::make_index_sequence<Count>{});
    }

    template<unsigned Count, unsigned Width>
    __attribute__((noinline)) std::uint64_t sparse(const Input<Count, Width> &input) {
        auto remaining = input.mask & widthMask<Count>();
        std::uint64_t result = 0;
        while (remaining != 0) {
            const auto index = std::countr_zero(remaining);
            result |= static_cast<std::uint64_t>(input.data[index]) & widthMask<Width>();
            if constexpr (Width == 1) if (result != 0) break;
            remaining &= remaining - 1;
        }
        return result;
    }

    std::uint64_t next(std::uint64_t &state) {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        return state;
    }

    volatile std::uint64_t consumed = 0;

    template<class T>
    double measure(const std::vector<T> &inputs, std::uint64_t (*function)(const T &)) {
        std::array<double, 5> samples;
        for (auto &sample : samples) {
            const auto start = std::chrono::steady_clock::now();
            std::uint64_t sum = 0;
            for (unsigned repeat = 0; repeat < 1024; ++repeat) {
                asm volatile("" ::: "memory");
                for (const auto &input : inputs) sum += function(input);
            }
            const auto stop = std::chrono::steady_clock::now();
            consumed = consumed ^ sum;
            sample = std::chrono::duration<double, std::nano>(stop - start).count() /
                     (1024 * inputs.size());
        }
        std::sort(samples.begin(), samples.end());
        return samples[2];
    }

    template<unsigned Count, unsigned Width>
    void bench(std::uint64_t &state, unsigned hits, bool zeroData) {
        std::vector<Input<Count, Width>> inputs(1024);
        for (auto &input : inputs) {
            input.mask = hits == Count ? widthMask<Count>() : 0;
            while (std::popcount(input.mask) < int(hits))
                input.mask |= UINT64_C(1) << (next(state) % Count);
            for (auto &element : input.data)
                element = static_cast<Element<Width>>(zeroData ? 0 : next(state) & widthMask<Width>());
            if (eager(input) != sparse(input)) throw std::runtime_error("maskedOr mismatch");
        }
        const double before = measure(inputs, &eager<Count, Width>);
        const double after = measure(inputs, &sparse<Count, Width>);
        std::printf("%u\t%u\t%u\t%s\t%.3f\t%.3f\t%.3f\n",
                    Count, Width, hits, zeroData ? "zero" : "random", before, after, before / after);
    }

    template<unsigned Count, unsigned Width>
    void cases(std::uint64_t &state) {
        for (const unsigned hits : {0u, 1u, 4u, Count}) bench<Count, Width>(state, hits, false);
        if constexpr (Width == 1) bench<Count, Width>(state, Count, true);
    }
}

int main(int argc, char **argv) {
    std::uint64_t state = argc > 1 ? std::strtoull(argv[1], nullptr, 0) : 20261016;
    if (!state) return 1;
    std::printf("# seed=%llu; compiler=%s; median of 5, 1048576 calls/sample\n",
                static_cast<unsigned long long>(state), __VERSION__);
    std::puts("terms\twidth\thits\tdata\teager_ns\tsparse_ns\tspeedup");
    cases<48, 1>(state);
    cases<64, 1>(state);
    cases<48, 8>(state);
    cases<64, 64>(state);
    return 0;
}
