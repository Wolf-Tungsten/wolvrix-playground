#include <cstdint>

#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

#define GRHSIM_TEST 1
#define VWolf GrhSIM_xs_bugcase_tb

static std::uint64_t get_chunk(const unsigned _BitInt(7552) &vec, int chunk) {
    return static_cast<std::uint64_t>(vec >> (chunk * 64));
}

#include "tb.cpp"
