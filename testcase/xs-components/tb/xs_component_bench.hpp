#pragma once

#include TOP_HEADER
#include GRHSIM_HEADER

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <type_traits>
#include <vector>

#ifndef TOP_NAME
#error TOP_NAME must be defined
#endif

#ifndef GSIM_CLASS
#error GSIM_CLASS must be defined
#endif

#ifndef GRHSIM_CLASS
#error GRHSIM_CLASS must be defined
#endif

#ifndef GSIM_IO_IN0_WIDTH
#define GSIM_IO_IN0_WIDTH 64
#endif
#ifndef GSIM_IO_IN1_WIDTH
#define GSIM_IO_IN1_WIDTH 64
#endif
#ifndef GSIM_IO_IN2_WIDTH
#define GSIM_IO_IN2_WIDTH 64
#endif
#ifndef GSIM_IO_IN3_WIDTH
#define GSIM_IO_IN3_WIDTH 64
#endif
#ifndef GSIM_IO_IN4_WIDTH
#define GSIM_IO_IN4_WIDTH 64
#endif
#ifndef GSIM_IO_IN5_WIDTH
#define GSIM_IO_IN5_WIDTH 64
#endif
#ifndef GSIM_IO_CTRL_WIDTH
#define GSIM_IO_CTRL_WIDTH 64
#endif

namespace xs_component_bench {

struct Inputs {
    std::uint64_t in0 = 0;
    std::uint64_t in1 = 0;
    std::uint64_t in2 = 0;
    std::uint64_t in3 = 0;
    std::uint64_t in4 = 0;
    std::uint64_t in5 = 0;
    std::uint64_t ctrl = 0;
};

struct Outputs {
    std::uint64_t out0 = 0;
    std::uint64_t out1 = 0;
    std::uint64_t out2 = 0;
    std::uint64_t out3 = 0;
    std::uint64_t flags = 0;
    std::uint64_t checksum = 0;
};

inline std::uint64_t splitmix64(std::uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

inline std::string hex64(std::uint64_t value)
{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return os.str();
}

inline std::uint64_t fold_output(const Outputs &out)
{
    std::uint64_t acc = out.checksum ^ 0xd6e8feb86659fd93ULL;
    acc ^= splitmix64(out.out0);
    acc ^= splitmix64(out.out1 + 1);
    acc ^= splitmix64(out.out2 + 2);
    acc ^= splitmix64(out.out3 + 3);
    acc ^= splitmix64(out.flags + 4);
    return acc;
}

template <unsigned Width>
inline std::uint64_t mask_width(std::uint64_t value)
{
    if constexpr (Width == 0U) {
        return 0;
    }
    else if constexpr (Width >= 64U) {
        return value;
    }
    else {
        return value & ((UINT64_C(1) << Width) - UINT64_C(1));
    }
}

template <unsigned Width, typename T>
inline T gsim_port_value(std::uint64_t value)
{
    static_assert(std::is_integral_v<T>, "GSIM port storage must be integral");
    return static_cast<T>(mask_width<Width>(value));
}

inline std::vector<Inputs> make_vectors(unsigned count)
{
    std::vector<Inputs> vectors;
    vectors.reserve(count + 2);
    vectors.push_back({});
    vectors.push_back({~0ULL, 0, 1, 2, 0xffff, 0, 0x1234});
    for (unsigned i = 0; i < count; ++i) {
        const std::uint64_t base = splitmix64(0x5853434f4d504f4eULL + i);
        Inputs in;
        in.in0 = splitmix64(base ^ 0x00);
        in.in1 = splitmix64(base ^ 0x11);
        in.in2 = splitmix64(base ^ 0x22);
        in.in3 = splitmix64(base ^ 0x33);
        in.in4 = splitmix64(base ^ 0x44);
        in.in5 = splitmix64(base ^ 0x55);
        in.ctrl = splitmix64(base ^ 0x66);
        if ((i % 17U) == 0U) {
            in.in0 = i & 0xffU;
            in.in1 = (i + 23U) & 0xffU;
            in.in2 = 0xffffU >> (i & 7U);
            in.in4 = 0x00ffU << (i & 7U);
            in.ctrl = (in.ctrl & ~0x7fULL) | (i & 0x7fU);
        }
        vectors.push_back(in);
    }
    return vectors;
}

inline void drive_gsim(GSIM_CLASS &dut, const Inputs &in)
{
    dut.set_reset(0);
    dut.set_io$$in0(gsim_port_value<GSIM_IO_IN0_WIDTH, decltype(dut.io$$in0)>(in.in0));
    dut.set_io$$in1(gsim_port_value<GSIM_IO_IN1_WIDTH, decltype(dut.io$$in1)>(in.in1));
    dut.set_io$$in2(gsim_port_value<GSIM_IO_IN2_WIDTH, decltype(dut.io$$in2)>(in.in2));
    dut.set_io$$in3(gsim_port_value<GSIM_IO_IN3_WIDTH, decltype(dut.io$$in3)>(in.in3));
    dut.set_io$$in4(gsim_port_value<GSIM_IO_IN4_WIDTH, decltype(dut.io$$in4)>(in.in4));
    dut.set_io$$in5(gsim_port_value<GSIM_IO_IN5_WIDTH, decltype(dut.io$$in5)>(in.in5));
    dut.set_io$$ctrl(gsim_port_value<GSIM_IO_CTRL_WIDTH, decltype(dut.io$$ctrl)>(in.ctrl));
}

inline Outputs sample_gsim(GSIM_CLASS &dut)
{
    return Outputs{
        dut.get_io$$out0(),
        dut.get_io$$out1(),
        dut.get_io$$out2(),
        dut.get_io$$out3(),
        dut.get_io$$flags(),
        dut.get_io$$checksum(),
    };
}

inline Outputs eval_gsim(GSIM_CLASS &dut, const Inputs &in)
{
    drive_gsim(dut, in);
    dut.set_clock(1);
    dut.step();
    return sample_gsim(dut);
}

inline void reset_gsim(GSIM_CLASS &dut)
{
    dut.set_reset(1);
    dut.set_clock(1);
    dut.step();
    dut.set_reset(0);
    dut.set_clock(0);
}

inline void drive_grhsim(GRHSIM_CLASS &dut, const Inputs &in)
{
    dut.reset = false;
    dut.io_in0 = in.in0;
    dut.io_in1 = in.in1;
    dut.io_in2 = in.in2;
    dut.io_in3 = in.in3;
    dut.io_in4 = in.in4;
    dut.io_in5 = in.in5;
    dut.io_ctrl = in.ctrl;
}

inline Outputs sample_grhsim(const GRHSIM_CLASS &dut)
{
    return Outputs{dut.io_out0, dut.io_out1, dut.io_out2, dut.io_out3, dut.io_flags, dut.io_checksum};
}

inline Outputs eval_grhsim(GRHSIM_CLASS &dut, const Inputs &in)
{
    drive_grhsim(dut, in);
    dut.clock = false;
    dut.eval();
    Outputs out = sample_grhsim(dut);
    dut.clock = true;
    dut.eval();
    return out;
}

inline void reset_grhsim(GRHSIM_CLASS &dut)
{
    dut.reset = true;
    dut.clock = false;
    dut.eval();
    dut.clock = true;
    dut.eval();
    dut.reset = false;
    dut.clock = false;
    dut.eval();
}

inline bool same(const Outputs &lhs, const Outputs &rhs)
{
    return lhs.out0 == rhs.out0 && lhs.out1 == rhs.out1 && lhs.out2 == rhs.out2 && lhs.out3 == rhs.out3 &&
           lhs.flags == rhs.flags && lhs.checksum == rhs.checksum;
}

inline bool verify_models(const std::vector<Inputs> &vectors, unsigned count)
{
    GSIM_CLASS gsim;
    GRHSIM_CLASS grhsim;
    grhsim.init();
    reset_gsim(gsim);
    reset_grhsim(grhsim);
    const unsigned limit = std::min<unsigned>(count, vectors.size());
    for (unsigned i = 0; i < limit; ++i) {
        const Outputs gsim_out = eval_gsim(gsim, vectors[i]);
        const Outputs grhsim_out = eval_grhsim(grhsim, vectors[i]);
        if (!same(gsim_out, grhsim_out)) {
            std::cerr << "[FAIL] top=" << TOP_NAME << " vector=" << i << "\n"
                      << "  out0 gsim=" << hex64(gsim_out.out0) << " grhsim=" << hex64(grhsim_out.out0) << "\n"
                      << "  out1 gsim=" << hex64(gsim_out.out1) << " grhsim=" << hex64(grhsim_out.out1) << "\n"
                      << "  out2 gsim=" << hex64(gsim_out.out2) << " grhsim=" << hex64(grhsim_out.out2) << "\n"
                      << "  out3 gsim=" << hex64(gsim_out.out3) << " grhsim=" << hex64(grhsim_out.out3) << "\n"
                      << "  flags gsim=" << hex64(gsim_out.flags) << " grhsim=" << hex64(grhsim_out.flags) << "\n"
                      << "  checksum gsim=" << hex64(gsim_out.checksum)
                      << " grhsim=" << hex64(grhsim_out.checksum) << "\n";
            return false;
        }
    }
    std::cout << "[VERIFY] top=" << TOP_NAME << " vectors=" << limit << " status=pass\n";
    return true;
}

template <typename EvalFn>
std::pair<double, std::uint64_t> run_benchmark_once(const std::vector<Inputs> &vectors, EvalFn eval)
{
    std::uint64_t accum = 0;
    const auto begin = std::chrono::steady_clock::now();
    for (const Inputs &input : vectors) {
        accum ^= fold_output(eval(input));
    }
    const auto end = std::chrono::steady_clock::now();
    const double ms = std::chrono::duration<double, std::milli>(end - begin).count();
    return {ms, accum};
}

template <typename EvalFn>
void run_benchmark(const char *label, const std::vector<Inputs> &vectors, unsigned repeat, EvalFn eval)
{
    (void)run_benchmark_once(vectors, eval);
    std::vector<double> samples;
    samples.reserve(repeat);
    std::uint64_t checksum = 0;
    for (unsigned i = 0; i < repeat; ++i) {
        const auto [ms, accum] = run_benchmark_once(vectors, eval);
        checksum = accum;
        samples.push_back(ms);
        if (repeat > 1) {
            const double run_vectors_per_s = vectors.empty() ? 0.0 : static_cast<double>(vectors.size()) * 1000.0 / ms;
            std::cout << "[BENCH_RUN] model=" << label << " top=" << TOP_NAME << " run=" << i
                      << " vectors=" << vectors.size()
                      << " ms=" << std::fixed << std::setprecision(3) << ms
                      << " vectors_per_s=" << std::setprecision(2) << run_vectors_per_s
                      << " checksum=" << hex64(accum) << "\n";
        }
    }
    auto sorted = samples;
    std::sort(sorted.begin(), sorted.end());
    const double min_ms = sorted.empty() ? std::numeric_limits<double>::quiet_NaN() : sorted.front();
    const double median_ms = sorted.empty() ? std::numeric_limits<double>::quiet_NaN() : sorted[sorted.size() / 2u];
    const double ms = min_ms;
    const double vectors_per_s = vectors.empty() ? 0.0 : static_cast<double>(vectors.size()) * 1000.0 / ms;
    std::cout << "[BENCH] model=" << label << " top=" << TOP_NAME << " vectors=" << vectors.size()
              << " repeat=" << repeat
              << " ms=" << std::fixed << std::setprecision(3) << ms
              << " min_ms=" << std::setprecision(3) << min_ms
              << " median_ms=" << std::setprecision(3) << median_ms
              << " vectors_per_s=" << std::setprecision(2) << vectors_per_s
              << " checksum=" << hex64(checksum) << "\n";
}

inline int run(int argc, char **argv)
{
    unsigned vectors = 100000;
    unsigned verify = 2048;
    unsigned repeat = 1;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg == "--vectors" && i + 1 < argc) {
            vectors = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--verify" && i + 1 < argc) {
            verify = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
        } else if (arg == "--repeat" && i + 1 < argc) {
            repeat = static_cast<unsigned>(std::strtoul(argv[++i], nullptr, 0));
            if (repeat == 0) {
                repeat = 1;
            }
        } else {
            std::cerr << "usage: " << argv[0] << " [--vectors N] [--verify N] [--repeat N]\n";
            return 2;
        }
    }

    const auto inputs = make_vectors(vectors);
    if (!verify_models(inputs, verify)) {
        return 1;
    }

    GSIM_CLASS gsim;
    GRHSIM_CLASS grhsim;
    grhsim.init();
    reset_gsim(gsim);
    reset_grhsim(grhsim);
    run_benchmark("gsim", inputs, repeat, [&](const Inputs &input) { return eval_gsim(gsim, input); });
    run_benchmark("grhsim", inputs, repeat, [&](const Inputs &input) { return eval_grhsim(grhsim, input); });
    return 0;
}

} // namespace xs_component_bench
