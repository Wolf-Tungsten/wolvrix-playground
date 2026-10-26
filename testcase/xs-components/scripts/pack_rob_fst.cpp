// Stream the settled state before each rising edge into RobTrc01 records.
#include "fstapi.h"

#include <algorithm>
#include <bit>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
struct Slice {
    unsigned bit;
    unsigned width;
    int offset;
    unsigned words;
    std::string name;
};

struct Reader {
    fstReaderContext *ctx;
    ~Reader() { if (ctx) fstReaderClose(ctx); }
};

struct Packer {
    std::vector<std::vector<Slice>> slices;
    std::vector<std::uint64_t> record;
    std::vector<std::pair<fstHandle, std::string>> pending;
    std::ofstream output;
    fstHandle clockHandle = 0;
    std::uint64_t timestamp = 0;
    std::uint64_t cycles = 0;
    std::uint64_t resetCycles = 0;
    std::uint64_t firstTime = 0;
    std::uint64_t lastTime = 0;
    std::uint64_t maxCycles = std::numeric_limits<std::uint64_t>::max();
    bool clock = false;
    bool initialized = false;
    bool firstReset = false;

    void emit() {
        if (cycles >= maxCycles) return;
        if (!cycles) {
            firstReset = record[0] & 1;
            firstTime = timestamp;
        }
        lastTime = timestamp;
        resetCycles += record[0] & 1;
        output.write(reinterpret_cast<const char *>(record.data()), record.size() * 8);
        if (!output) throw std::runtime_error("replay write failed");
        ++cycles;
        if (cycles % 10000 == 0) std::cout << "[FST_PACK] cycles=" << cycles << std::endl;
    }

    void flush() {
        if (pending.empty()) return;
        bool nextClock = clock;
        for (const auto &[handle, value] : pending) {
            if (handle == clockHandle) nextClock = value == "1";
        }
        // Verilator dumps after eval. All changes at this timestamp belong
        // to the edge being observed; replay needs the preceding low phase.
        if (initialized && !clock && nextClock) emit();
        for (const auto &[handle, value] : pending) {
            std::vector<std::uint64_t> words((value.size() + 63) / 64, 0);
            for (std::size_t bit = 0; bit < value.size(); ++bit) {
                const char digit = value[value.size() - 1 - bit];
                if (digit != '0' && digit != '1') {
                    throw std::runtime_error("unknown FST value for handle " + std::to_string(handle));
                }
                if (digit == '1') words[bit / 64] |= UINT64_C(1) << (bit % 64);
            }
            for (const Slice &slice : slices.at(handle)) {
                if (slice.offset == -2) continue;
                if (slice.bit + slice.width > value.size()) {
                    throw std::runtime_error("FST slice outside value: " + slice.name);
                }
                for (unsigned word = 0; word < slice.words; ++word) {
                    const unsigned bit = slice.bit + 64 * word;
                    std::uint64_t result = 0;
                    if (64 * word < slice.width) {
                        result = words.at(bit / 64) >> (bit % 64);
                        if (bit % 64 && bit / 64 + 1 < words.size()) {
                            result |= words[bit / 64 + 1] << (64 - bit % 64);
                        }
                        const unsigned width = std::min(64u, slice.width - 64 * word);
                        if (width < 64) result &= (UINT64_C(1) << width) - 1;
                    }
                    if (slice.offset == -1) {
                        if (result) throw std::runtime_error("nonzero static input: " + slice.name);
                    } else {
                        record.at(slice.offset + word) = result;
                    }
                }
            }
        }
        clock = nextClock;
        initialized = true;
        pending.clear();
    }

    static void callback(void *user, std::uint64_t time, fstHandle handle, const unsigned char *value) {
        auto &packer = *static_cast<Packer *>(user);
        if (!packer.pending.empty() && time != packer.timestamp) {
            if (time < packer.timestamp) throw std::runtime_error("FST callbacks out of time order");
            packer.flush();
        }
        packer.timestamp = time;
        packer.pending.emplace_back(handle, reinterpret_cast<const char *>(value));
    }
};
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc < 5 || argc > 7) {
            std::cerr << "usage: pack_rob_fst WAVE PLAN OUTPUT SUMMARY [MIN_CYCLES] [MAX_CYCLES]\n";
            return 2;
        }
        static_assert(std::endian::native == std::endian::little);
        const std::uint64_t minimum = argc > 5 ? std::stoull(argv[5]) : 100000;
        Packer packer;
        if (argc > 6) packer.maxCycles = std::stoull(argv[6]);
        std::ifstream plan(argv[2]);
        std::uint32_t inWords, outWords;
        if (!(plan >> inWords >> outWords)) throw std::runtime_error("bad plan header");
        packer.record.resize(1 + inWords + outWords, 0);
        Reader reader{fstReaderOpen(argv[1])};
        if (!reader.ctx) throw std::runtime_error("cannot open waveform");
        packer.slices.resize(fstReaderGetMaxHandle(reader.ctx) + 1);
        fstReaderClrFacProcessMaskAll(reader.ctx);
        fstHandle handle;
        Slice slice;
        while (plan >> handle >> slice.bit >> slice.width >> slice.offset >> slice.words >> slice.name) {
            if (slice.offset == -2) packer.clockHandle = handle;
            packer.slices.at(handle).push_back(slice);
            fstReaderSetFacProcessMask(reader.ctx, handle);
        }
        if (!plan.eof() || !packer.clockHandle) throw std::runtime_error("bad plan rows or missing clock");
        const std::string partial = std::string(argv[3]) + ".partial";
        packer.output.open(partial, std::ios::binary | std::ios::trunc);
        if (!packer.output) throw std::runtime_error("cannot open replay output");
        packer.output.write("RobTrc01", 8);
        packer.output.write(reinterpret_cast<const char *>(&packer.cycles), 8);
        packer.output.write(reinterpret_cast<const char *>(&inWords), 4);
        packer.output.write(reinterpret_cast<const char *>(&outWords), 4);
        fstReaderIterBlocks2(reader.ctx, Packer::callback, nullptr, &packer, nullptr);
        packer.flush();
        if (packer.cycles < minimum || !packer.firstReset) {
            throw std::runtime_error("trace too short or does not start in reset: " + std::to_string(packer.cycles));
        }
        packer.output.seekp(8);
        packer.output.write(reinterpret_cast<const char *>(&packer.cycles), 8);
        packer.output.close();
        if (!packer.output) throw std::runtime_error("cannot finalize replay");
        std::filesystem::rename(partial, argv[3]);
        std::ofstream summary(argv[4]);
        summary << "{\n  \"cycles\": " << packer.cycles
                << ",\n  \"reset_cycles\": " << packer.resetCycles
                << ",\n  \"first_reset\": true,\n  \"first_rising_time\": " << packer.firstTime
                << ",\n  \"last_rising_time\": " << packer.lastTime
                << ",\n  \"in_words\": " << inWords << ",\n  \"out_words\": " << outWords
                << ",\n  \"bytes\": " << std::filesystem::file_size(argv[3]) << "\n}\n";
        std::cout << "[FST_PACK] done cycles=" << packer.cycles << " reset_cycles=" << packer.resetCycles
                  << " first_time=" << packer.firstTime << " last_time=" << packer.lastTime << '\n';
    } catch (const std::exception &error) {
        std::cerr << "[FST_PACK] ERROR: " << error.what() << '\n';
        return 1;
    }
}
