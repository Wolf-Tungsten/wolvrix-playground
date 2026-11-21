#include "difftest-state.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

struct Commit {
    std::uint64_t pc;
    std::uint32_t instruction;
    std::uint8_t fused;
    std::uint64_t cycle;
};
std::vector<Commit> commits(const char *file) {
    std::ifstream input(file, std::ios::binary);
    if (!input) throw std::runtime_error(file);
    DiffTestState record{};
    std::vector<Commit> result;
    while (input.read(reinterpret_cast<char *>(&record), sizeof record)) {
        for (const auto &c : record.commit) {
            if (c.valid) result.push_back({c.pc, c.instr, c.nFused, record.trap.cycleCnt});
        }
    }
    if (!input.eof() || input.gcount() || result.empty()) throw std::runtime_error("invalid trace");
    return result;
}
int main(int argc, char **argv) {
    if (argc != 3) return 1;
    const auto a = commits(argv[1]), b = commits(argv[2]);
    std::size_t common = 0;
    while (common < a.size() && common < b.size() && a[common].pc == b[common].pc &&
           a[common].instruction == b[common].instruction && a[common].fused == b[common].fused) ++common;
    std::cout << "{\"grhsim_commit_packets\":" << a.size() << ",\"gsim_commit_packets\":" << b.size()
              << ",\"common_prefix_packets\":" << common << ",\"grhsim_first_cycle\":" << a.front().cycle
              << ",\"gsim_first_cycle\":" << b.front().cycle << "}\n";
}
