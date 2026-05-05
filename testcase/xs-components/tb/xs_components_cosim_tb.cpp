#include "XsComponents.h"
#include "grhsim_XsComponents.hpp"

#include <array>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Inputs {
    bool reset = false;
    std::uint64_t src1 = 0;
    std::uint64_t src2 = 0;
    std::uint8_t func = 0;
    std::uint8_t begin = 0;
    std::uint8_t end = 0;
    std::uint8_t vsew = 0;
    std::uint16_t maskUsed = 0;
    std::uint8_t vdIdx = 0;
    bool fixedTaken = false;
    bool vma = false;
    bool vta = false;
};

struct Outputs {
    bool taken = false;
    bool mispredict = false;
    std::uint64_t aluOut = 0;
    std::uint16_t activeEn = 0;
    std::uint16_t agnosticEn = 0;
    std::uint64_t debug = 0;
};

std::string hex64(std::uint64_t value)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return os.str();
}

std::string hex16(std::uint16_t value)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(4) << std::setfill('0') << value;
    return os.str();
}

std::uint64_t rol64(std::uint64_t value, unsigned amount)
{
    amount &= 63U;
    return amount == 0 ? value : (value << amount) | (value >> (64U - amount));
}

std::uint64_t ror64(std::uint64_t value, unsigned amount)
{
    amount &= 63U;
    return amount == 0 ? value : (value >> amount) | (value << (64U - amount));
}

bool signed_lt(std::uint64_t lhs, std::uint64_t rhs)
{
    const bool lhsSign = ((lhs >> 63U) & 1U) != 0;
    const bool rhsSign = ((rhs >> 63U) & 1U) != 0;
    return (lhsSign != rhsSign) ? lhsSign : lhs < rhs;
}

std::uint8_t scaled_byte(std::uint8_t value, std::uint8_t vsew)
{
    return static_cast<std::uint8_t>(value << (vsew & 3U));
}

class ReferenceModel {
public:
    Outputs cycle(const Inputs &in)
    {
        if (in.reset) {
            src1_ = 0;
            src2_ = 0;
            func_ = 0;
        } else {
            src1_ = in.src1;
            src2_ = in.src2;
            func_ = in.func & 0x3fU;
        }
        return eval_outputs(in);
    }

private:
    Outputs eval_outputs(const Inputs &in) const
    {
        const std::uint8_t funcLo = func_ & 0x3U;
        bool takenBase = false;
        if (funcLo == 0) {
            takenBase = (src1_ ^ src2_) == 0;
        } else if (funcLo == 1) {
            takenBase = signed_lt(src1_, src2_);
        } else if (funcLo == 2) {
            takenBase = src1_ < src2_;
        }

        Outputs out;
        out.taken = takenBase ^ (((func_ >> 2U) & 1U) != 0);
        out.mispredict = in.fixedTaken ^ out.taken;

        std::uint64_t logicSel = 0;
        if (funcLo == 0) {
            logicSel = src1_ & src2_;
        } else if (funcLo == 1) {
            logicSel = src1_ | src2_;
        } else if (funcLo == 2) {
            logicSel = src1_ ^ src2_;
        } else {
            logicSel = src1_ + src2_;
        }

        static constexpr std::array<unsigned, 4> shiftAmounts{1, 2, 3, 4};
        static constexpr std::array<unsigned, 4> rotateAmounts{1, 8, 16, 32};
        const unsigned idx = funcLo;
        const std::uint8_t shiftMode = (func_ >> 2U) & 0x3U;
        std::uint64_t shiftSel = 0;
        if (shiftMode == 0) {
            shiftSel = src1_ << shiftAmounts[idx];
        } else if (shiftMode == 1) {
            shiftSel = src1_ >> shiftAmounts[idx];
        } else if (shiftMode == 2) {
            shiftSel = rol64(src1_, rotateAmounts[idx]);
        } else {
            shiftSel = ror64(src1_, rotateAmounts[idx]);
        }
        out.aluOut = logicSel ^ shiftSel;

        const std::uint8_t vsew = in.vsew & 0x3U;
        const std::uint8_t startBytes = scaled_byte(in.begin, vsew);
        const std::uint8_t vlBytes = scaled_byte(in.end, vsew);
        const unsigned segBase = static_cast<unsigned>(in.vdIdx & 0x7U) * 16U;
        std::uint16_t bodySeg = 0;
        std::uint16_t tailSeg = 0;
        for (unsigned i = 0; i < 16; ++i) {
            const std::uint8_t pos = static_cast<std::uint8_t>(segBase + i);
            if (pos >= startBytes && pos < vlBytes) {
                bodySeg |= static_cast<std::uint16_t>(1U << i);
            }
            if (pos >= vlBytes) {
                tailSeg |= static_cast<std::uint16_t>(1U << i);
            }
        }

        std::uint16_t maskEn = 0;
        for (unsigned i = 0; i < 16; ++i) {
            unsigned maskIdx = i;
            if (vsew == 1) {
                maskIdx = i / 2U;
            } else if (vsew == 2) {
                maskIdx = i / 4U;
            } else if (vsew == 3) {
                maskIdx = i / 8U;
            }
            if (((in.maskUsed >> maskIdx) & 1U) != 0) {
                maskEn |= static_cast<std::uint16_t>(1U << i);
            }
        }

        const std::uint16_t activeRaw = static_cast<std::uint16_t>(bodySeg & maskEn);
        const std::uint16_t agnosticRaw = static_cast<std::uint16_t>(
            (in.vma ? static_cast<std::uint16_t>(~maskEn) : 0U) & bodySeg |
            (in.vta ? tailSeg : 0U));
        const bool emptyRange = in.begin >= in.end;
        out.activeEn = emptyRange ? 0 : activeRaw;
        out.agnosticEn = emptyRange ? 0 : agnosticRaw;
        out.debug = ((out.aluOut & 0xffffffffULL) << 32U) |
                    (static_cast<std::uint64_t>(activeRaw) << 16U) |
                    static_cast<std::uint64_t>(agnosticRaw);
        out.debug ^= (static_cast<std::uint64_t>(activeRaw != 0) << 1U) |
                     static_cast<std::uint64_t>(out.taken);
        return out;
    }

    std::uint64_t src1_ = 0;
    std::uint64_t src2_ = 0;
    std::uint8_t func_ = 0;
};

void drive_gsim(SXsComponents &dut, const Inputs &in)
{
    dut.set_reset(in.reset ? 1 : 0);
    dut.set_io$$src1(in.src1);
    dut.set_io$$src2(in.src2);
    dut.set_io$$func(in.func & 0x3fU);
    dut.set_io$$begin(in.begin);
    dut.set_io$$end(in.end);
    dut.set_io$$vsew(in.vsew & 0x3U);
    dut.set_io$$maskUsed(in.maskUsed);
    dut.set_io$$vdIdx(in.vdIdx & 0x7U);
    dut.set_io$$fixedTaken(in.fixedTaken ? 1 : 0);
    dut.set_io$$vma(in.vma ? 1 : 0);
    dut.set_io$$vta(in.vta ? 1 : 0);
}

Outputs sample_gsim(SXsComponents &dut)
{
    return Outputs{
        static_cast<bool>(dut.get_io$$taken()),
        static_cast<bool>(dut.get_io$$mispredict()),
        dut.get_io$$aluOut(),
        dut.get_io$$activeEn(),
        dut.get_io$$agnosticEn(),
        dut.get_io$$debug(),
    };
}

Outputs cycle_gsim(SXsComponents &dut, const Inputs &in)
{
    drive_gsim(dut, in);
    dut.set_clock(0);
    dut.step();
    dut.set_clock(1);
    dut.step();
    dut.set_clock(0);
    return sample_gsim(dut);
}

void drive_grhsim(GrhSIM_XsComponents &dut, const Inputs &in)
{
    dut.reset = in.reset;
    dut.io_src1 = in.src1;
    dut.io_src2 = in.src2;
    dut.io_func = in.func & 0x3fU;
    dut.io_begin = in.begin;
    dut.io_end = in.end;
    dut.io_vsew = in.vsew & 0x3U;
    dut.io_maskUsed = in.maskUsed;
    dut.io_vdIdx = in.vdIdx & 0x7U;
    dut.io_fixedTaken = in.fixedTaken;
    dut.io_vma = in.vma;
    dut.io_vta = in.vta;
}

Outputs sample_grhsim(const GrhSIM_XsComponents &dut)
{
    return Outputs{
        dut.io_taken,
        dut.io_mispredict,
        dut.io_aluOut,
        dut.io_activeEn,
        dut.io_agnosticEn,
        dut.io_debug,
    };
}

Outputs cycle_grhsim(GrhSIM_XsComponents &dut, const Inputs &in)
{
    drive_grhsim(dut, in);
    dut.clock = false;
    dut.eval();
    dut.clock = true;
    dut.eval();
    const Outputs out = sample_grhsim(dut);
    dut.clock = false;
    dut.eval();
    return out;
}

void report_field_mismatch(const char *model, const char *field, std::uint64_t got,
                           std::uint64_t expected, unsigned cycle)
{
    std::cerr << "[FAIL] cycle=" << cycle << " model=" << model << " field=" << field
              << " got=" << hex64(got) << " expected=" << hex64(expected) << "\n";
}

bool compare_outputs(const char *model, const Outputs &got, const Outputs &expected,
                     unsigned cycle)
{
    bool ok = true;
    auto check = [&](const char *field, std::uint64_t lhs, std::uint64_t rhs) {
        if (lhs != rhs) {
            report_field_mismatch(model, field, lhs, rhs, cycle);
            ok = false;
        }
    };
    check("taken", got.taken, expected.taken);
    check("mispredict", got.mispredict, expected.mispredict);
    check("aluOut", got.aluOut, expected.aluOut);
    check("activeEn", got.activeEn, expected.activeEn);
    check("agnosticEn", got.agnosticEn, expected.agnosticEn);
    check("debug", got.debug, expected.debug);
    return ok;
}

std::uint64_t mix64(std::uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

std::vector<Inputs> make_vectors(unsigned count)
{
    std::vector<Inputs> vectors;
    vectors.reserve(count + 4U);
    for (unsigned i = 0; i < 2; ++i) {
        Inputs in;
        in.reset = true;
        vectors.push_back(in);
    }

    const std::array<std::uint64_t, 8> specials{
        0ULL,
        1ULL,
        0xffffffffffffffffULL,
        0x8000000000000000ULL,
        0x7fffffffffffffffULL,
        0x0123456789abcdefULL,
        0xfedcba9876543210ULL,
        0x00ff00ff55aa55aaULL,
    };

    for (unsigned i = 0; i < count; ++i) {
        Inputs in;
        const std::uint64_t a = mix64(i * 3ULL + 1ULL);
        const std::uint64_t b = mix64(i * 3ULL + 2ULL);
        in.src1 = (i < specials.size()) ? specials[i] : a;
        in.src2 = (i < specials.size()) ? specials[specials.size() - 1U - i] : b;
        in.func = static_cast<std::uint8_t>((i * 11U + (a >> 61U)) & 0x3fU);
        in.begin = static_cast<std::uint8_t>((a >> 8U) & 0xffU);
        in.end = static_cast<std::uint8_t>((b >> 16U) & 0xffU);
        if ((i % 9U) == 0U) {
            in.begin = static_cast<std::uint8_t>(i & 0x7fU);
            in.end = static_cast<std::uint8_t>(in.begin + 1U + (i % 31U));
        } else if ((i % 13U) == 0U) {
            in.begin = 200;
            in.end = 17;
        }
        in.vsew = static_cast<std::uint8_t>(i & 3U);
        in.maskUsed = static_cast<std::uint16_t>((a ^ (b >> 17U)) & 0xffffU);
        if ((i % 17U) == 0U) {
            in.maskUsed = static_cast<std::uint16_t>(1U << ((i / 17U) & 15U));
        }
        in.vdIdx = static_cast<std::uint8_t>((a >> 32U) & 0x7U);
        in.fixedTaken = ((b >> 5U) & 1U) != 0;
        in.vma = ((a >> 7U) & 1U) != 0;
        in.vta = ((b >> 9U) & 1U) != 0;
        vectors.push_back(in);
    }
    return vectors;
}

void print_trace_line(unsigned cycle, const Inputs &in, const Outputs &ref)
{
    std::cout << "cycle=" << std::dec << cycle
              << " reset=" << in.reset
              << " func=0x" << std::hex << static_cast<unsigned>(in.func)
              << " src1=" << hex64(in.src1)
              << " src2=" << hex64(in.src2)
              << " begin=0x" << std::setw(2) << std::setfill('0') << static_cast<unsigned>(in.begin)
              << " end=0x" << std::setw(2) << static_cast<unsigned>(in.end)
              << " vsew=" << std::dec << static_cast<unsigned>(in.vsew)
              << " vdIdx=" << static_cast<unsigned>(in.vdIdx)
              << " mask=" << hex16(in.maskUsed)
              << " taken=" << ref.taken
              << " mispredict=" << ref.mispredict
              << " aluOut=" << hex64(ref.aluOut)
              << " activeEn=" << hex16(ref.activeEn)
              << " agnosticEn=" << hex16(ref.agnosticEn)
              << " debug=" << hex64(ref.debug)
              << std::setfill(' ') << "\n";
}

} // namespace

int main(int argc, char **argv)
{
    unsigned cycles = 256;
    bool trace = true;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg == "--quiet") {
            trace = false;
        } else if (arg == "--cycles" && i + 1 < argc) {
            cycles = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else {
            std::cerr << "usage: " << argv[0] << " [--cycles N] [--quiet]\n";
            return 2;
        }
    }

    SXsComponents gsim;
    GrhSIM_XsComponents grhsim;
    ReferenceModel ref;
    grhsim.init();

    const auto vectors = make_vectors(cycles);
    unsigned mismatches = 0;
    for (unsigned cycle = 0; cycle < vectors.size(); ++cycle) {
        const Inputs &in = vectors[cycle];
        const Outputs expected = ref.cycle(in);
        const Outputs gsimOut = cycle_gsim(gsim, in);
        const Outputs grhsimOut = cycle_grhsim(grhsim, in);

        const bool gsimOk = compare_outputs("gsim", gsimOut, expected, cycle);
        const bool grhsimOk = compare_outputs("grhsim", grhsimOut, expected, cycle);
        if (!gsimOk || !grhsimOk) {
            ++mismatches;
            print_trace_line(cycle, in, expected);
            if (mismatches >= 16) {
                std::cerr << "[FAIL] stopping after 16 mismatching cycles\n";
                return 1;
            }
        } else if (trace) {
            print_trace_line(cycle, in, expected);
        }
    }

    if (mismatches != 0) {
        std::cerr << "[FAIL] mismatching cycles=" << mismatches << "\n";
        return 1;
    }
    std::cout << "[PASS] xs-components cosim cycles=" << vectors.size()
              << " checked reference=gsim=grhsim\n";
    return 0;
}
