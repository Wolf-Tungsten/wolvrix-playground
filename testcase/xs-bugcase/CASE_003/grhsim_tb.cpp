#include <array>
#include <cstdint>

#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

#define GRHSIM_TEST 1
#define VWolf GrhSIM_xs_bugcase_tb

static std::uint64_t get_chunk(const std::array<std::uint64_t, 118> &vec, int chunk) {
    return vec[chunk];
}

#include "tb.cpp"
