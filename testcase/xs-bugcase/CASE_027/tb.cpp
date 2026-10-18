#include "grhsim_ingest_struct_array_partial_write.hpp"

#include <array>
#include <cstdint>
#include <cstdio>

int main() {
    GrhSIM_ingest_struct_array_partial_write sim;
    sim.init();
    std::array<uint32_t, 4> dynamic{};
    std::array<uint32_t, 4> fixed{};
    constexpr auto pack = [](uint32_t set, uint32_t mask, uint32_t hi, uint32_t lo) {
        return (set << 14) | (mask << 6) | (hi << 3) | lo;
    };
    constexpr std::array constants = {
        pack(0x03, 0x80, 7, 0), pack(0x6a, 0x40, 5, 6),
        pack(0x2d, 0x20, 3, 4), pack(0x50, 0x10, 1, 2)
    };
    uint32_t random = 0x726170;
    unsigned checks = 0;
    for (unsigned cycle = 0; cycle < 512; ++cycle) {
        random = random * 1664525U + 1013904223U;
        const unsigned index = cycle % 4;
        const bool reset = cycle == 0 || cycle == 127 || cycle == 300;
        const bool valid = (cycle % 7) != 0;
        sim.clk = 0;
        sim.reset = reset;
        sim.write_valid = valid;
        sim.write_idx = index;
        sim.write_bits = random & 0x1fffffU;
        sim.eval();
        sim.clk = 1;
        sim.eval();
        if (reset) {
            dynamic.fill(0);
            fixed.fill(0);
        } else if (valid) {
            dynamic[index] = sim.write_bits;
            fixed = constants;
        }
        for (unsigned read = 0; read < 4; ++read) {
            sim.write_idx = read;
            sim.eval();
            if (sim.static_bits != fixed[read] || sim.dynamic_bits != dynamic[read] ||
                sim.member_bits != dynamic[read] || sim.scalar_bits != dynamic[read] ||
                sim.member_scalar_bits != dynamic[read]) {
                std::printf("[FAIL] cycle=%u lane=%u static=%x expected=%x "
                            "dynamic=%x member=%x scalar=%x member_scalar=%x expected=%x\n", cycle, read,
                            unsigned(sim.static_bits), fixed[read], unsigned(sim.dynamic_bits),
                            unsigned(sim.member_bits), unsigned(sim.scalar_bits),
                            unsigned(sim.member_scalar_bits), dynamic[read]);
                return 1;
            }
            checks += 5;
        }
    }
    std::printf("[PASS] cycles=512 lane_field_checks=%u static/dynamic/nested writes\n", checks);
    return 0;
}
