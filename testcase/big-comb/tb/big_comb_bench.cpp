#include "BigComb.h"
#include "grhsim_BigComb.hpp"

#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Inputs {
    std::array<std::uint64_t, 32> in{};
    std::uint64_t ctrl = 0;
    std::uint16_t sel = 0;
};

struct Outputs {
    std::array<std::uint64_t, 16> out{};
    std::uint64_t flags = 0;
    std::uint64_t checksum = 0;
};

std::uint64_t splitmix64(std::uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

std::uint64_t fold_output(const Outputs &out)
{
    std::uint64_t acc = out.flags ^ (out.checksum + 0xd6e8feb86659fd93ULL);
    for (std::size_t i = 0; i < out.out.size(); ++i) {
        acc ^= splitmix64(out.out[i] + i * 0x9e3779b97f4a7c15ULL);
    }
    return acc;
}

std::string hex64(std::uint64_t value)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return os.str();
}

std::vector<Inputs> make_vectors(unsigned count)
{
    std::vector<Inputs> vectors;
    vectors.reserve(count);
    for (unsigned i = 0; i < count; ++i) {
        Inputs v;
        const std::uint64_t base = splitmix64(0x3141592653589793ULL + i);
        for (unsigned lane = 0; lane < v.in.size(); ++lane) {
            std::uint64_t x = splitmix64(base ^ (lane * 0x100000001b3ULL) ^ (i * 0x9e3779b97f4a7c15ULL));
            if ((i & 31U) == lane) {
                x = 0;
            } else if (((i + lane) % 37U) == 0U) {
                x = ~0ULL;
            } else if (((i ^ lane) % 41U) == 0U) {
                x = 1ULL << ((i + lane) & 63U);
            }
            v.in[lane] = x;
        }
        v.ctrl = splitmix64(base ^ 0x0123456789abcdefULL);
        v.sel = static_cast<std::uint16_t>(splitmix64(base ^ 0xfedcba9876543210ULL) & 0xffffU);
        if ((i % 17U) == 0U) {
            v.sel = static_cast<std::uint16_t>(1U << ((i / 17U) & 15U));
        }
        vectors.push_back(v);
    }
    return vectors;
}

void drive_gsim(SBigComb &dut, const Inputs &in)
{
    dut.set_io$$in0(in.in[0]);
    dut.set_io$$in1(in.in[1]);
    dut.set_io$$in2(in.in[2]);
    dut.set_io$$in3(in.in[3]);
    dut.set_io$$in4(in.in[4]);
    dut.set_io$$in5(in.in[5]);
    dut.set_io$$in6(in.in[6]);
    dut.set_io$$in7(in.in[7]);
    dut.set_io$$in8(in.in[8]);
    dut.set_io$$in9(in.in[9]);
    dut.set_io$$in10(in.in[10]);
    dut.set_io$$in11(in.in[11]);
    dut.set_io$$in12(in.in[12]);
    dut.set_io$$in13(in.in[13]);
    dut.set_io$$in14(in.in[14]);
    dut.set_io$$in15(in.in[15]);
    dut.set_io$$in16(in.in[16]);
    dut.set_io$$in17(in.in[17]);
    dut.set_io$$in18(in.in[18]);
    dut.set_io$$in19(in.in[19]);
    dut.set_io$$in20(in.in[20]);
    dut.set_io$$in21(in.in[21]);
    dut.set_io$$in22(in.in[22]);
    dut.set_io$$in23(in.in[23]);
    dut.set_io$$in24(in.in[24]);
    dut.set_io$$in25(in.in[25]);
    dut.set_io$$in26(in.in[26]);
    dut.set_io$$in27(in.in[27]);
    dut.set_io$$in28(in.in[28]);
    dut.set_io$$in29(in.in[29]);
    dut.set_io$$in30(in.in[30]);
    dut.set_io$$in31(in.in[31]);
    dut.set_io$$ctrl(in.ctrl);
    dut.set_io$$sel(in.sel);
}

Outputs sample_gsim(SBigComb &dut)
{
    return Outputs{{
                       dut.get_io$$out0(), dut.get_io$$out1(), dut.get_io$$out2(), dut.get_io$$out3(),
                       dut.get_io$$out4(), dut.get_io$$out5(), dut.get_io$$out6(), dut.get_io$$out7(),
                       dut.get_io$$out8(), dut.get_io$$out9(), dut.get_io$$out10(), dut.get_io$$out11(),
                       dut.get_io$$out12(), dut.get_io$$out13(), dut.get_io$$out14(), dut.get_io$$out15(),
                   },
                   dut.get_io$$flags(),
                   dut.get_io$$checksum()};
}

Outputs eval_gsim(SBigComb &dut, const Inputs &in)
{
    drive_gsim(dut, in);
    dut.step();
    return sample_gsim(dut);
}

void drive_grhsim(GrhSIM_BigComb &dut, const Inputs &in)
{
    dut.io_in0 = in.in[0];
    dut.io_in1 = in.in[1];
    dut.io_in2 = in.in[2];
    dut.io_in3 = in.in[3];
    dut.io_in4 = in.in[4];
    dut.io_in5 = in.in[5];
    dut.io_in6 = in.in[6];
    dut.io_in7 = in.in[7];
    dut.io_in8 = in.in[8];
    dut.io_in9 = in.in[9];
    dut.io_in10 = in.in[10];
    dut.io_in11 = in.in[11];
    dut.io_in12 = in.in[12];
    dut.io_in13 = in.in[13];
    dut.io_in14 = in.in[14];
    dut.io_in15 = in.in[15];
    dut.io_in16 = in.in[16];
    dut.io_in17 = in.in[17];
    dut.io_in18 = in.in[18];
    dut.io_in19 = in.in[19];
    dut.io_in20 = in.in[20];
    dut.io_in21 = in.in[21];
    dut.io_in22 = in.in[22];
    dut.io_in23 = in.in[23];
    dut.io_in24 = in.in[24];
    dut.io_in25 = in.in[25];
    dut.io_in26 = in.in[26];
    dut.io_in27 = in.in[27];
    dut.io_in28 = in.in[28];
    dut.io_in29 = in.in[29];
    dut.io_in30 = in.in[30];
    dut.io_in31 = in.in[31];
    dut.io_ctrl = in.ctrl;
    dut.io_sel = in.sel;
}

Outputs sample_grhsim(const GrhSIM_BigComb &dut)
{
    return Outputs{{
                       dut.io_out0, dut.io_out1, dut.io_out2, dut.io_out3,
                       dut.io_out4, dut.io_out5, dut.io_out6, dut.io_out7,
                       dut.io_out8, dut.io_out9, dut.io_out10, dut.io_out11,
                       dut.io_out12, dut.io_out13, dut.io_out14, dut.io_out15,
                   },
                   dut.io_flags,
                   dut.io_checksum};
}

Outputs eval_grhsim(GrhSIM_BigComb &dut, const Inputs &in)
{
    drive_grhsim(dut, in);
    dut.eval();
    return sample_grhsim(dut);
}

bool verify_models(const std::vector<Inputs> &vectors, unsigned count)
{
    SBigComb gsim;
    GrhSIM_BigComb grhsim;
    grhsim.init();
    const unsigned limit = std::min<unsigned>(count, vectors.size());
    for (unsigned i = 0; i < limit; ++i) {
        const Outputs gsimOut = eval_gsim(gsim, vectors[i]);
        const Outputs grhsimOut = eval_grhsim(grhsim, vectors[i]);
        if (gsimOut.flags != grhsimOut.flags || gsimOut.checksum != grhsimOut.checksum ||
            gsimOut.out != grhsimOut.out) {
            std::cerr << "[FAIL] mismatch vector=" << i << "\n";
            for (std::size_t lane = 0; lane < gsimOut.out.size(); ++lane) {
                if (gsimOut.out[lane] != grhsimOut.out[lane]) {
                    std::cerr << "  out" << lane << " gsim=" << hex64(gsimOut.out[lane])
                              << " grhsim=" << hex64(grhsimOut.out[lane]) << "\n";
                }
            }
            std::cerr << "  flags gsim=" << hex64(gsimOut.flags)
                      << " grhsim=" << hex64(grhsimOut.flags) << "\n";
            std::cerr << "  checksum gsim=" << hex64(gsimOut.checksum)
                      << " grhsim=" << hex64(grhsimOut.checksum) << "\n";
            return false;
        }
    }
    std::cout << "[VERIFY] vectors=" << limit << " status=pass\n";
    return true;
}

template <typename EvalFn>
void run_benchmark(const char *label, const std::vector<Inputs> &vectors, EvalFn eval)
{
    std::uint64_t accum = 0;
    const auto begin = std::chrono::steady_clock::now();
    for (const Inputs &input : vectors) {
        accum ^= fold_output(eval(input));
    }
    const auto end = std::chrono::steady_clock::now();
    const double ms = std::chrono::duration<double, std::milli>(end - begin).count();
    const double vectorsPerSecond = vectors.empty() ? 0.0 : static_cast<double>(vectors.size()) * 1000.0 / ms;
    std::cout << "[BENCH] model=" << label
              << " vectors=" << vectors.size()
              << " ms=" << std::fixed << std::setprecision(3) << ms
              << " vectors_per_s=" << std::setprecision(2) << vectorsPerSecond
              << " checksum=" << hex64(accum)
              << "\n";
}

} // namespace

int main(int argc, char **argv)
{
    unsigned vectors = 100000;
    unsigned verify = 2048;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg == "--vectors" && i + 1 < argc) {
            vectors = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--verify" && i + 1 < argc) {
            verify = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else {
            std::cerr << "usage: " << argv[0] << " [--vectors N] [--verify N]\n";
            return 2;
        }
    }

    const auto inputs = make_vectors(vectors);
    if (!verify_models(inputs, verify)) {
        return 1;
    }

    SBigComb gsim;
    GrhSIM_BigComb grhsim;
    grhsim.init();
    run_benchmark("gsim", inputs, [&](const Inputs &input) { return eval_gsim(gsim, input); });
    run_benchmark("grhsim", inputs, [&](const Inputs &input) { return eval_grhsim(grhsim, input); });
    return 0;
}
