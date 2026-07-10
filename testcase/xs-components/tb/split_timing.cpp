// Standalone profiler: time grhsim clock-low eval vs clock-high eval separately,
// vs gsim single step(). Wraps model classes to add the no-op profile method that
// the shared bench header expects, so we can reuse its drive/sample helpers.
#include TOP_HEADER
#include GRHSIM_HEADER

struct GsimWrap : GSIM_BASE { void set_runtime_profile_enabled(bool) {} };
struct GrhWrap  : GRHSIM_BASE { void set_runtime_profile_enabled(bool) {} };

#define GSIM_CLASS GsimWrap
#define GRHSIM_CLASS GrhWrap
#include "xs_component_bench.hpp"

#include <chrono>
#include <cstdio>
using namespace xs_component_bench;

int main(int argc, char **argv) {
    unsigned count = (argc > 1) ? std::strtoul(argv[1], nullptr, 10) : 2000000;
    auto vectors = make_vectors(count);
    using clk = std::chrono::steady_clock;
    volatile std::uint64_t sink = 0;

    GRHSIM_CLASS grhsim; grhsim.init(); reset_grhsim(grhsim);
    double t_low = 0, t_high = 0;
    for (const auto &in : vectors) {
        drive_grhsim(grhsim, in);
        grhsim.clock = false; auto a = clk::now(); grhsim.eval(); auto b = clk::now();
        sink ^= sample_grhsim(grhsim).checksum;
        grhsim.clock = true;  auto c = clk::now(); grhsim.eval(); auto d = clk::now();
        t_low  += std::chrono::duration<double, std::milli>(b - a).count();
        t_high += std::chrono::duration<double, std::milli>(d - c).count();
    }

    GSIM_CLASS gsim; reset_gsim(gsim);
    double t_gsim = 0;
    for (const auto &in : vectors) {
        drive_gsim(gsim, in); gsim.set_clock(1);
        auto a = clk::now(); gsim.step(); auto b = clk::now();
        sink ^= sample_gsim(gsim).checksum;
        t_gsim += std::chrono::duration<double, std::milli>(b - a).count();
    }

    std::printf("top=%s vectors=%u\n", TOP_NAME, count);
    std::printf("grhsim clock-LOW  eval : %10.2f ms\n", t_low);
    std::printf("grhsim clock-HIGH eval : %10.2f ms\n", t_high);
    std::printf("grhsim TOTAL           : %10.2f ms\n", t_low + t_high);
    std::printf("gsim   step (1/cycle)  : %10.2f ms\n", t_gsim);
    std::printf("ratio grhsim/gsim      : %10.3f\n", (t_low + t_high) / t_gsim);
    std::printf("clock-LOW share of grhsim: %.1f%%\n", 100.0 * t_low / (t_low + t_high));
    std::printf("sink=%llu\n", (unsigned long long)sink);
    return 0;
}
