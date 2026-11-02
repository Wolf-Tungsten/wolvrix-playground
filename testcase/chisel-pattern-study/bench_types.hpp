#pragma once
#include <cstdint>
struct Input { uint64_t a,b,c,d; uint8_t sel; bool reset; };
struct Output {
    uint64_t y=0,z=0;
    bool operator==(const Output&) const = default;
};
