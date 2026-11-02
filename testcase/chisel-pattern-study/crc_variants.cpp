// CRC follow-up: one binary and one indirect-call loop for all alternatives.
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include "bench_types.hpp"
#include "grhsim_Pattern.hpp"

using Function = Output (*)(GrhSIM_Pattern&, const Input&);
volatile uint64_t checksum = 0;

__attribute__((noinline)) Output generated(GrhSIM_Pattern& model, const Input& input) {
    return model.research_compute(input);
}

__attribute__((noinline)) Output serial(GrhSIM_Pattern&, const Input& input) {
    uint32_t value = uint32_t(input.a);
    for (int i = 31; i >= 16; --i) {
        if (value & (1u << i)) value ^= 0x11021u << (i - 16);
    }
    return {value, 0};
}

__attribute__((noinline)) Output lookup(GrhSIM_Pattern&, const Input& input) {
    static constexpr auto lut = [] {
        std::array<uint16_t, 256> table{};
        for (unsigned i = 0; i < 256; ++i) {
            uint32_t value = i << 16;
            for (int j = 23; j >= 16; --j) {
                if (value & (1u << j)) value ^= 0x11021u << (j - 16);
            }
            table[i] = value;
        }
        return table;
    }();
    uint16_t value = 0;
    for (int byte = 3; byte >= 0; --byte) {
        value = uint16_t((uint32_t(value) << 8) ^ ((input.a >> (byte * 8)) & 255) ^ lut[value >> 8]);
    }
    return {value, 0};
}

// Match the generated adapter's tail jump; every alternative has one adapter.
__attribute__((noinline)) Output serial_entry(GrhSIM_Pattern& model, const Input& input) {
    return serial(model, input);
}

__attribute__((noinline)) Output lookup_entry(GrhSIM_Pattern& model, const Input& input) {
    return lookup(model, input);
}

std::vector<Input> inputs(uint64_t seed, const std::string& mode, size_t count) {
    std::mt19937_64 rng(seed);
    std::vector<Input> result;
    result.reserve(count);
    Input previous{};
    for (size_t i = 0; i < count; ++i) {
        Input x{};
        x.a = rng();
        if (mode == "sparse") x.a = UINT64_C(1) << (x.a & 31);
        if (mode == "dense") x.a = uint32_t(~(1u << (x.a & 31)));
        if (mode == "toggle1" && i) x.a = previous.a ^ (UINT64_C(1) << (x.a & 31));
        if (mode == "hold99" && i % 100) x = previous;
        if (i % 1024 < 2) x.a = i % 1024 ? UINT32_MAX : 0;
        result.push_back(x);
        previous = x;
    }
    return result;
}

// All alternatives use this exact caller. No templates or candidate-specific loops.
__attribute__((noinline)) double measure(Function function, GrhSIM_Pattern& model,
                                        const std::vector<Input>& values, unsigned loops) {
    uint64_t sum = 0;
    const auto start = std::chrono::steady_clock::now();
    for (unsigned k = 0; k < loops; ++k) {
        for (const auto& x : values) {
            const auto y = function(model, x);
            sum += y.y ^ (y.z * 17);
        }
    }
    const auto end = std::chrono::steady_clock::now();
    checksum = sum;
    return double(std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count()) /
           (loops * values.size());
}

int main() {
    GrhSIM_Pattern model;
    model.init();
    model.reset = true; model.clock = false; model.eval();
    model.clock = true; model.eval();
    model.reset = false; model.clock = false; model.eval();
    constexpr std::array<const char*, 5> modes{"random", "sparse", "dense", "toggle1", "hold99"};
    uint64_t verified = 0;
    for (uint64_t seed : {UINT64_C(0x37c159), UINT64_C(0x95d273)}) {
        for (const char* mode : modes) {
            for (const auto& x : inputs(seed, mode, 100000)) {
                model.io_a = x.a; model.eval();
                const Output reference{model.io_y, model.io_z};
                if (reference != generated(model, x) || reference != serial(model, x) || reference != lookup(model, x)) {
                    throw std::runtime_error("CRC control mismatch");
                }
                ++verified;
            }
        }
    }
    std::cout << "{\"verified_vectors\":" << verified << ",\"samples\":[";
    bool first = true;
    const std::array<Function, 2> candidates{serial_entry, lookup_entry};
    const std::array<const char*, 2> names{"serial", "lookup"};
    for (const char* mode : modes) {
        const auto values = inputs(0x37c159, mode, 16384);
        for (unsigned pair = 0; pair < 8; ++pair) {
            // Alternate candidate ordering too, while retaining AB/BA within each pair.
            for (unsigned iteration = 0; iteration < 2; ++iteration) {
                const unsigned candidate = (iteration + pair) % 2;
                measure(generated, model, values, 1);
                measure(candidates[candidate], model, values, 1);
                double baseline, replacement;
                if (pair % 2 == 0) {
                    baseline = measure(generated, model, values, 32);
                    replacement = measure(candidates[candidate], model, values, 32);
                } else {
                    replacement = measure(candidates[candidate], model, values, 32);
                    baseline = measure(generated, model, values, 32);
                }
                if (!first) std::cout << ',';
                first = false;
                std::cout << "{\"distribution\":\"" << mode << "\",\"variant\":\"" << names[candidate]
                          << "\",\"pair\":" << pair << ",\"order\":\"" << (pair % 2 ? "BA" : "AB")
                          << "\",\"generated_ns\":" << baseline << ",\"candidate_ns\":" << replacement << '}';
            }
        }
    }
    std::cout << "],\"checksum\":" << checksum << "}\n";
}
