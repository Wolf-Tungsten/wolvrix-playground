#include "fstapi.h"

#include <cstdint>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    fstWriterContext *writer = fstWriterCreate(argv[1], 1);
    if (!writer) return 1;
    fstWriterSetScope(writer, FST_ST_VCD_MODULE, "Rob", nullptr);
    const fstHandle clock = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_INPUT, 1, "clock", 0);
    const fstHandle reset = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_INPUT, 1, "reset", 0);
    const fstHandle bus = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_INPUT, 140, "bus", 0);
    const fstHandle out = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_OUTPUT, 8, "out", 0);
    fstWriterSetUpscope(writer);
    const auto value = [&](std::uint32_t low, std::uint32_t high) {
        const std::uint32_t words[5] = {low, 0x12345678, 0x90abcdef, high, 0xa5b};
        fstWriterEmitValueChangeVec32(writer, bus, 140, words);
    };
    fstWriterEmitTimeChange(writer, 0);
    fstWriterEmitValueChange(writer, clock, "0");
    fstWriterEmitValueChange(writer, reset, "1");
    value(0x1234, 0x80000000);
    fstWriterEmitValueChange32(writer, out, 8, 0x11);
    fstWriterEmitTimeChange(writer, 2);
    // Clock callback may precede the data callbacks at the same timestamp.
    fstWriterEmitValueChange(writer, clock, "1");
    value(0x5678, 0x40000000);
    fstWriterEmitValueChange32(writer, out, 8, 0x22);
    fstWriterEmitTimeChange(writer, 3);
    fstWriterEmitValueChange(writer, clock, "0");
    fstWriterEmitValueChange(writer, reset, "0");
    value(0x9abc, 0x20000000);
    fstWriterEmitValueChange32(writer, out, 8, 0x33);
    fstWriterEmitTimeChange(writer, 4);
    value(0xdef0, 0x10000000);
    fstWriterEmitValueChange32(writer, out, 8, 0x44);
    fstWriterEmitValueChange(writer, clock, "1");
    fstWriterClose(writer);
}
