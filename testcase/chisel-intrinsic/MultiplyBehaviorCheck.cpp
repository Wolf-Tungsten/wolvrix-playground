#include "grhsim_MultiplyFixture.hpp"
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#ifndef MODEL_LATENCY
#define MODEL_LATENCY 2
#endif

using Row = std::array<std::uint64_t, 8>;
struct Expected { bool valid = false; std::uint64_t data = 0, flags = 0; };

int main(int argc, char **argv) {
    if (argc < 2) return 9;
    std::ifstream stream(argv[1], std::ios::binary);
    if (!stream) return 10;
    std::vector<Row> rows;
    Row row;
    while (stream.read(reinterpret_cast<char *>(row.data()), sizeof(row))) rows.push_back(row);
    if (!stream.eof() || rows.empty()) return 11;
    const bool bench = argc > 2;
    const std::string scenario = bench ? argv[2] : "check";
    GrhSIM_MultiplyFixture m; m.init();
    std::array<Expected, MODEL_LATENCY> pipe{};
    std::uint64_t hash = 0, transactions = 0;
    auto verify = [&](std::size_t cycle, const char *edge) {
        const auto &want = pipe.back();
        if (m.io_outValid != want.valid ||
            (want.valid && (m.io_result != want.data || m.io_flags != want.flags))) {
            std::fprintf(stderr, "cycle=%zu %s valid=%d/%d result=%016llx/%016llx flags=%x/%llx\n",
                cycle, edge, int(m.io_outValid), int(want.valid),
                (unsigned long long)m.io_result, (unsigned long long)want.data,
                unsigned(m.io_flags), (unsigned long long)want.flags);
            return false;
        }
        return true;
    };
    const auto start = std::chrono::steady_clock::now();
    const std::size_t count = bench ? 10000 : rows.size();
    for (std::size_t i = 0; i < count; ++i) {
        const auto &r = rows[i]; const auto c = r[3];
        m.io_a=r[0]; m.io_b=r[1]; m.io_c=r[2];
        m.io_op=c&31; m.io_format=(c>>5)&3; m.io_rm=(c>>7)&7;
        m.io_signedA=(c>>10)&1; m.io_signedB=(c>>11)&1; m.io_signedC=(c>>12)&1;
        m.io_high=(c>>13)&1; m.io_macc=(c>>14)&1; m.io_sub=(c>>15)&1;
        m.io_widen=(c>>16)&1; m.io_fixed=(c>>17)&1; m.io_uop=(c>>18)&1;
        m.io_canonical=(c>>19)&7; m.reset=r[5];
        m.io_valid=bench ? !m.reset && (scenario=="active" || (scenario=="sparse" && i%8==0)) : bool(r[4]);
        m.clock=false; m.eval();
        if (!bench && !m.reset && !verify(i,"low")) return 1;
        for (int j=MODEL_LATENCY-1;j>0;--j) pipe[j]=pipe[j-1];
        pipe[0]={bool(m.io_valid),r[6],r[7]};
        if (m.reset) pipe.fill({});
        m.clock=true; m.eval();
        if (!bench && !verify(i,"rise")) return 2;
        const auto result=m.io_result; const auto flags=m.io_flags; const bool valid=m.io_outValid;
        m.eval();
        if (!bench && (result!=m.io_result || flags!=m.io_flags || valid!=m.io_outValid)) return 3;
        if (!bench) {
            m.io_a ^= UINT64_C(0xffffffffffffffff);
            m.io_b ^= UINT64_C(0x8000000000000000);
            m.eval();
            if (result!=m.io_result || flags!=m.io_flags || valid!=m.io_outValid) return 4;
            m.io_a=r[0]; m.io_b=r[1]; m.eval();
        }
        if (m.io_outValid) {
            hash=(hash ^ m.io_result ^ (std::uint64_t(m.io_flags)<<32))*UINT64_C(1099511628211);
            ++transactions;
        }
    }
    const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
    std::printf("{\"pass\":true,\"cycles\":%zu,\"transactions\":%llu,\"hash\":\"%016llx\",\"ns\":%lld}\n",
        count,(unsigned long long)transactions,(unsigned long long)hash,(long long)ns);
}
