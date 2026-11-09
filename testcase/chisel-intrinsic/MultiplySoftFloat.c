#include <stdint.h>
#include "softfloat.h"

/* Independent oracle only. Not linked into the simulated design. */
uint64_t multiply_reference(unsigned width, uint64_t a, uint64_t b, uint64_t c,
                            unsigned fused, unsigned rm, unsigned widen, uint32_t *flags) {
    softfloat_roundingMode = rm;
    softfloat_detectTininess = softfloat_tininess_afterRounding;
    softfloat_exceptionFlags = 0;
    uint64_t result;
    if (width == 16) {
        float16_t x = {(uint16_t)a}, y = {(uint16_t)b}, z = {(uint16_t)c};
        result = (fused ? f16_mulAdd(x, y, z) : f16_mul(x, y)).v;
    } else if (width == 32) {
        float32_t x = {(uint32_t)a}, y = {(uint32_t)b}, z = {(uint32_t)c};
        if (widen) {
            float16_t ax = {(uint16_t)a}, by = {(uint16_t)b};
            x = f16_to_f32(ax); y = f16_to_f32(by);
        }
        result = (fused ? f32_mulAdd(x, y, z) : f32_mul(x, y)).v;
    } else {
        float64_t x = {a}, y = {b}, z = {c};
        if (widen) {
            float32_t ax = {(uint32_t)a}, by = {(uint32_t)b};
            x = f32_to_f64(ax); y = f32_to_f64(by);
        }
        result = (fused ? f64_mulAdd(x, y, z) : f64_mul(x, y)).v;
    }
    *flags = softfloat_exceptionFlags;
    return result;
}
