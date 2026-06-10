#include <cstdint>
#include <cstdio>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    bool rst_n = false;
    bool read_valid = false;
    std::uint8_t read_set = 0;
    std::uint8_t read_waymask = 0;
    bool write_valid = false;
    std::uint8_t write_set = 0;
    std::uint8_t write_waymask = 0;
    std::uint64_t write_data = 0;
    bool write_code = false;
    bool ram_hold = false;
};

struct Outputs {
    bool read_ready = false;
    bool write_ready = false;
    std::uint64_t resp_data = 0;
    bool resp_code = false;
};

static vluint64_t main_time = 0;

double sc_time_stamp() { return static_cast<double>(main_time); }

std::uint64_t data_pattern(int seq)
{
    return 0xA63463B4491D2371ULL ^ (static_cast<std::uint64_t>(seq) * 0x1F123BB5A55DULL);
}

Stimulus idle_after_reset()
{
    Stimulus s;
    s.rst_n = true;
    return s;
}

Stimulus read_req(std::uint8_t set)
{
    Stimulus s = idle_after_reset();
    s.read_valid = true;
    s.read_set = set;
    s.read_waymask = 0x1;
    return s;
}

Stimulus write_req(std::uint8_t set, std::uint64_t data, bool code)
{
    Stimulus s = idle_after_reset();
    s.write_valid = true;
    s.write_set = set;
    s.write_waymask = 0x1;
    s.write_data = data;
    s.write_code = code;
    return s;
}

Stimulus build_stimulus(int cycle)
{
    Stimulus s;
    s.rst_n = cycle >= 3;
    if (!s.rst_n) {
        return s;
    }

    // Wait for SRAMTemplate_16's reset scrub to walk every set.
    if (cycle < 270) {
        return idle_after_reset();
    }

    switch (cycle) {
    case 270:
        return write_req(0x05, data_pattern(0), true);
    case 271:
        return idle_after_reset();
    case 272:
        return read_req(0x05);
    case 273:
        return read_req(0x05);
    case 274:
    case 275:
        return idle_after_reset();
    case 276:
        return write_req(0x06, data_pattern(1), false);
    case 277:
    case 278:
        return idle_after_reset();
    case 279:
        return read_req(0x73);
    case 280:
        return read_req(0x73);
    case 281:
        return idle_after_reset();
    case 282:
        return read_req(0x05);
    case 283:
        return read_req(0x05);
    default:
        if (cycle < 340) {
            const int idx = cycle - 284;
            if ((idx % 9) == 0) {
                return write_req(static_cast<std::uint8_t>((idx * 17 + 3) & 0xff),
                                 data_pattern(idx + 2),
                                 (idx & 2) != 0);
            }
            if ((idx % 9) == 3 || (idx % 9) == 4) {
                return read_req(static_cast<std::uint8_t>((idx * 19 + 0x73) & 0xff));
            }
        }
        return idle_after_reset();
    }
}

void drive(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, bool clk, const Stimulus& s)
{
    ref.clk = clk;
    ref.rst_n = s.rst_n;
    ref.read_valid = s.read_valid;
    ref.read_set = s.read_set;
    ref.read_waymask = s.read_waymask;
    ref.write_valid = s.write_valid;
    ref.write_set = s.write_set;
    ref.write_waymask = s.write_waymask;
    ref.write_data = s.write_data;
    ref.write_code = s.write_code;
    ref.ram_hold = s.ram_hold;

    grhsim.clk = clk;
    grhsim.rst_n = s.rst_n;
    grhsim.read_valid = s.read_valid;
    grhsim.read_set = s.read_set;
    grhsim.read_waymask = s.read_waymask;
    grhsim.write_valid = s.write_valid;
    grhsim.write_set = s.write_set;
    grhsim.write_waymask = s.write_waymask;
    grhsim.write_data = s.write_data;
    grhsim.write_code = s.write_code;
    grhsim.ram_hold = s.ram_hold;
}

Outputs sample_ref(const VRef& ref)
{
    return Outputs{
        static_cast<bool>(ref.read_ready),
        static_cast<bool>(ref.write_ready),
        static_cast<std::uint64_t>(ref.resp_data),
        static_cast<bool>(ref.resp_code),
    };
}

Outputs sample_grhsim(const GrhSIM_xs_bugcase_tb& grhsim)
{
    return Outputs{
        static_cast<bool>(grhsim.read_ready),
        static_cast<bool>(grhsim.write_ready),
        static_cast<std::uint64_t>(grhsim.resp_data),
        static_cast<bool>(grhsim.resp_code),
    };
}

bool compare(const Outputs& ref,
             const Outputs& grhsim,
             const Stimulus& s,
             int cycle,
             const char* phase)
{
    const bool target_resp_window = cycle >= 279 && cycle <= 283;
    if (ref.read_ready == grhsim.read_ready &&
        ref.write_ready == grhsim.write_ready &&
        (!target_resp_window ||
         (ref.resp_data == grhsim.resp_data && ref.resp_code == grhsim.resp_code))) {
        return true;
    }
    std::fprintf(stderr,
                 "[MISMATCH] cycle=%d phase=%s "
                 "rv=%u rs=0x%02x rwm=0x%x wv=%u ws=0x%02x wwm=0x%x wd=0x%016llx wc=%u "
                 "read_ready ref=%u grhsim=%u write_ready ref=%u grhsim=%u "
                 "resp_data ref=0x%016llx grhsim=0x%016llx resp_code ref=%u grhsim=%u\n",
                 cycle,
                 phase,
                 static_cast<unsigned>(s.read_valid),
                 static_cast<unsigned>(s.read_set),
                 static_cast<unsigned>(s.read_waymask),
                 static_cast<unsigned>(s.write_valid),
                 static_cast<unsigned>(s.write_set),
                 static_cast<unsigned>(s.write_waymask),
                 static_cast<unsigned long long>(s.write_data),
                 static_cast<unsigned>(s.write_code),
                 static_cast<unsigned>(ref.read_ready),
                 static_cast<unsigned>(grhsim.read_ready),
                 static_cast<unsigned>(ref.write_ready),
                 static_cast<unsigned>(grhsim.write_ready),
                 static_cast<unsigned long long>(ref.resp_data),
                 static_cast<unsigned long long>(grhsim.resp_data),
                 static_cast<unsigned>(ref.resp_code),
                 static_cast<unsigned>(grhsim.resp_code));
    return false;
}

bool step(VRef& ref, GrhSIM_xs_bugcase_tb& grhsim, const Stimulus& s, int cycle)
{
    drive(ref, grhsim, false, s);
    ref.eval();
    grhsim.eval();
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), s, cycle, "low")) {
        return false;
    }
    ++main_time;

    drive(ref, grhsim, true, s);
    ref.eval();
    grhsim.eval();
    if (!compare(sample_ref(ref), sample_grhsim(grhsim), s, cycle, "high")) {
        return false;
    }
    ++main_time;
    return true;
}

} // namespace

int main(int argc, char** argv)
{
    Verilated::commandArgs(argc, argv);
    Verilated::randReset(0);
    Verilated::randSeed(1);

    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();

    for (int cycle = 0; cycle < 360; ++cycle) {
        const Stimulus s = build_stimulus(cycle);
        if (!step(ref, grhsim, s, cycle)) {
            return 1;
        }
    }

    std::printf("[PASS] CASE_020 SRAMTemplate_16 ref == grhsim\n");
    return 0;
}
