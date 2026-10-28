// Diagnose retained reference FST data; this does not execute an RTL model.
#include "fstapi.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr std::size_t rows = 352;
constexpr std::size_t lanes = 8;
constexpr std::size_t columns = 7;
constexpr std::array<const char *, columns> names{
    "ldest", "pdest", "rfWen", "fpWen", "vecWen", "v0Wen", "isMove"};
constexpr std::array<unsigned, columns> widths{6, 8, 1, 1, 1, 1, 1};
using State = std::array<std::array<unsigned, rows>, columns>;

enum class Role { Clock, Reset, Enable, Pointer, Data, State };
struct Binding {
    Role role;
    std::size_t column = 0;
    std::size_t index = 0;
    unsigned width = 1;
};
struct Snapshot {
    State state{};
    std::array<std::array<unsigned, lanes>, columns> data{};
    std::array<unsigned, lanes> enable{};
    std::array<unsigned, lanes> pointer{};
    bool clock = false;
    bool reset = false;
};
struct LaneStats {
    std::uint64_t enabled = 0;
    std::uint64_t sameOld = 0;
    std::uint64_t winning = 0;
    std::uint64_t winningSameOld = 0;
};
struct ColumnStats {
    std::array<LaneStats, lanes> lane{};
    std::uint64_t unchangedEdges = 0;
    std::uint64_t writtenUnchangedEdges = 0;
    std::uint64_t touchedLeaves = 0;
    std::uint64_t unchangedTouchedLeaves = 0;
};
struct Prediction {
    State state{};
    std::array<ColumnStats, columns> stats{};
    std::uint64_t time = 0;
    unsigned enabled = 0;
    unsigned collisions = 0;
    bool unchanged = true;
    bool reset = false;
};
struct Report {
    std::uint64_t risingEdges = 0;
    std::uint64_t resetEdges = 0;
    std::uint64_t resetPairs = 0;
    std::uint64_t validatedEdges = 0;
    std::uint64_t failedEdges = 0;
    std::uint64_t mismatchedLeaves = 0;
    std::uint64_t writtenEdges = 0;
    std::uint64_t unchangedEdges = 0;
    std::uint64_t writtenUnchangedEdges = 0;
    std::uint64_t collisions = 0;
    std::uint64_t unverifiedTail = 0;
    std::uint64_t firstTime = 0;
    std::uint64_t lastTime = 0;
    std::array<ColumnStats, columns> column{};
    std::vector<std::string> mismatches;
};

std::string quote(const std::string &text) {
    std::ostringstream output;
    output << '"';
    for (const char ch : text) {
        if (ch == '"' || ch == '\\') output << '\\';
        if (ch == '\n') output << "\\n";
        else output << ch;
    }
    return output.str() + '"';
}

std::map<std::string, Binding> bindings(const std::string &scope) {
    std::map<std::string, Binding> result;
    const auto add = [&](const std::string &name, Binding binding) {
        result.emplace(scope + '.' + name, binding);
    };
    const auto parent = scope.substr(0, scope.find_last_of('.'));
    result.emplace(parent + ".clock", Binding{Role::Clock});
    add("reset", {Role::Reset});
    for (std::size_t lane = 0; lane < lanes; ++lane) {
        add("realNeedAlloc_" + std::to_string(lane), {Role::Enable, 0, lane});
        add("enqPtrVec_" + std::to_string(lane) + "_value", {Role::Pointer, 0, lane, 9});
        for (std::size_t column = 0; column < columns; ++column) {
            add("io_req_" + std::to_string(lane) + "_bits_" + names[column],
                {Role::Data, column, lane, widths[column]});
        }
    }
    for (std::size_t column = 0; column < columns; ++column) {
        for (std::size_t row = 0; row < rows; ++row) {
            add("renameBuffer_" + std::to_string(row) + "_info_" + names[column],
                {Role::State, column, row, widths[column]});
        }
    }
    return result;
}

Prediction predict(const Snapshot &snapshot, std::uint64_t time) {
    Prediction result;
    result.time = time;
    result.reset = snapshot.reset;
    result.state = snapshot.state;
    if (snapshot.reset) return result;
    std::array<int, rows> winner;
    winner.fill(-1);
    unsigned allocated = 0;
    for (std::size_t lane = 0; lane < lanes; ++lane) {
        if (!snapshot.enable[lane]) continue;
        // RTL selects enqPtrVec[popcount(realNeedAlloc[0:lane])], excluding lane.
        const unsigned row = snapshot.pointer[allocated++];
        if (row >= rows) throw std::runtime_error("enabled RAB write has an out-of-range address");
        ++result.enabled;
        if (winner[row] >= 0) ++result.collisions;
        winner[row] = static_cast<int>(lane);
        for (std::size_t column = 0; column < columns; ++column) {
            const unsigned value = snapshot.data[column][lane];
            auto &stats = result.stats[column].lane[lane];
            ++stats.enabled;
            stats.sameOld += value == snapshot.state[column][row];
            result.state[column][row] = value;
        }
    }
    for (std::size_t column = 0; column < columns; ++column) {
        auto &stats = result.stats[column];
        bool unchanged = true;
        for (std::size_t row = 0; row < rows; ++row) {
            const bool same = result.state[column][row] == snapshot.state[column][row];
            unchanged &= same;
            if (winner[row] < 0) continue;
            ++stats.touchedLeaves;
            stats.unchangedTouchedLeaves += same;
            auto &laneStats = stats.lane[winner[row]];
            ++laneStats.winning;
            laneStats.winningSameOld += same;
        }
        stats.unchangedEdges = unchanged;
        stats.writtenUnchangedEdges = unchanged && result.enabled;
        result.unchanged &= unchanged;
    }
    return result;
}

void accumulate(Report &report, const Prediction &prediction) {
    ++report.validatedEdges;
    report.writtenEdges += prediction.enabled != 0;
    report.unchangedEdges += prediction.unchanged;
    report.writtenUnchangedEdges += prediction.enabled && prediction.unchanged;
    report.collisions += prediction.collisions;
    for (std::size_t column = 0; column < columns; ++column) {
        auto &dest = report.column[column];
        const auto &source = prediction.stats[column];
        dest.unchangedEdges += source.unchangedEdges;
        dest.writtenUnchangedEdges += source.writtenUnchangedEdges;
        dest.touchedLeaves += source.touchedLeaves;
        dest.unchangedTouchedLeaves += source.unchangedTouchedLeaves;
        for (std::size_t lane = 0; lane < lanes; ++lane) {
            dest.lane[lane].enabled += source.lane[lane].enabled;
            dest.lane[lane].sameOld += source.lane[lane].sameOld;
            dest.lane[lane].winning += source.lane[lane].winning;
            dest.lane[lane].winningSameOld += source.lane[lane].winningSameOld;
        }
    }
}

struct Analyzer {
    Snapshot snapshot;
    Report report;
    std::vector<std::vector<Binding>> byHandle;
    std::vector<std::pair<fstHandle, unsigned>> pending;
    std::vector<bool> known;
    std::optional<Prediction> previous;
    std::uint64_t timestamp = 0;
    bool initialized = false;

    void edge() {
        if (report.risingEdges == 0) {
            for (std::size_t handle = 0; handle < byHandle.size(); ++handle) {
                if (!byHandle[handle].empty() && !known[handle])
                    throw std::runtime_error("required FST signal has no initial value");
            }
            report.firstTime = timestamp;
        }
        ++report.risingEdges;
        report.lastTime = timestamp;
        report.resetEdges += snapshot.reset;
        if (previous) {
            if (previous->reset || snapshot.reset) {
                ++report.resetPairs;
            } else {
                std::uint64_t mismatches = 0;
                for (std::size_t column = 0; column < columns; ++column) {
                    for (std::size_t row = 0; row < rows; ++row) {
                        if (previous->state[column][row] == snapshot.state[column][row]) continue;
                        ++mismatches;
                        if (report.mismatches.size() < 12) {
                            report.mismatches.push_back("edge " + std::to_string(previous->time) +
                                " -> " + std::to_string(timestamp) + " " + names[column] + '[' +
                                std::to_string(row) + "] expected=" + std::to_string(previous->state[column][row]) +
                                " actual=" + std::to_string(snapshot.state[column][row]));
                        }
                    }
                }
                report.mismatchedLeaves += mismatches;
                if (mismatches) ++report.failedEdges;
                else accumulate(report, *previous);
            }
        }
        previous = predict(snapshot, timestamp);
    }

    void assign(fstHandle handle, unsigned value) {
        known[handle] = true;
        for (const auto &binding : byHandle[handle]) {
            switch (binding.role) {
            case Role::Clock: snapshot.clock = value; break;
            case Role::Reset: snapshot.reset = value; break;
            case Role::Enable: snapshot.enable[binding.index] = value; break;
            case Role::Pointer: snapshot.pointer[binding.index] = value; break;
            case Role::Data: snapshot.data[binding.column][binding.index] = value; break;
            case Role::State: snapshot.state[binding.column][binding.index] = value; break;
            }
        }
    }

    void flush() {
        if (pending.empty()) return;
        bool nextClock = snapshot.clock;
        for (const auto &[handle, value] : pending) {
            for (const auto &binding : byHandle[handle]) {
                if (binding.role == Role::Clock) nextClock = value;
            }
        }
        // Identical to pack_rob_fst.cpp: all callbacks at an edge timestamp
        // are post-eval updates. Sample the preceding settled low phase first.
        if (initialized && !snapshot.clock && nextClock) edge();
        for (const auto &[handle, value] : pending) assign(handle, value);
        initialized = true;
        pending.clear();
    }

    static void callback(void *user, std::uint64_t time, fstHandle handle, const unsigned char *value) {
        auto &analyzer = *static_cast<Analyzer *>(user);
        if (!analyzer.pending.empty() && time != analyzer.timestamp) {
            if (time < analyzer.timestamp) throw std::runtime_error("out-of-order FST timestamps");
            analyzer.flush();
        }
        analyzer.timestamp = time;
        unsigned parsed = 0;
        const auto width = analyzer.byHandle.at(handle).front().width;
        unsigned count = 0;
        for (; *value; ++value) {
            if (*value != '0' && *value != '1') throw std::runtime_error("unknown value in required RAB signal");
            parsed = (parsed << 1) | (*value - '0');
            ++count;
        }
        if (count != width) throw std::runtime_error("required RAB signal value width changed");
        analyzer.pending.emplace_back(handle, parsed);
    }
};

Report analyze(const std::filesystem::path &wave, const std::string &scope) {
    struct Reader {
        fstReaderContext *ctx;
        ~Reader() { if (ctx) fstReaderClose(ctx); }
    } reader{fstReaderOpen(wave.c_str())};
    if (!reader.ctx) throw std::runtime_error("cannot open FST: " + wave.string());
    Analyzer analyzer;
    analyzer.byHandle.resize(fstReaderGetMaxHandle(reader.ctx) + 1);
    analyzer.known.resize(analyzer.byHandle.size(), false);
    auto required = bindings(scope);
    std::vector<std::string> scopes;
    fstReaderClrFacProcessMaskAll(reader.ctx);
    while (fstHier *hier = fstReaderIterateHier(reader.ctx)) {
        if (hier->htyp == FST_HT_SCOPE) {
            scopes.emplace_back(hier->u.scope.name);
        } else if (hier->htyp == FST_HT_UPSCOPE) {
            if (!scopes.empty()) scopes.pop_back();
        } else if (hier->htyp == FST_HT_VAR) {
            std::string path;
            for (const auto &part : scopes) path += part + '.';
            path += hier->u.var.name;
            if (const auto dimension = path.find(" ["); dimension != std::string::npos) path.erase(dimension);
            const auto found = required.find(path);
            if (found == required.end()) continue;
            if (found->second.width != hier->u.var.length)
                throw std::runtime_error("required RAB signal width differs: " + path);
            auto &aliases = analyzer.byHandle.at(hier->u.var.handle);
            if (!aliases.empty() && aliases.front().width != found->second.width)
                throw std::runtime_error("aliased required RAB widths differ");
            aliases.push_back(found->second);
            fstReaderSetFacProcessMask(reader.ctx, hier->u.var.handle);
            required.erase(found);
        }
    }
    if (!required.empty()) throw std::runtime_error("required RAB signal missing: " + required.begin()->first);
    fstReaderIterBlocks2(reader.ctx, Analyzer::callback, nullptr, &analyzer, nullptr);
    analyzer.flush();
    analyzer.report.unverifiedTail = analyzer.previous && !analyzer.previous->reset;
    if (analyzer.report.validatedEdges == 0) throw std::runtime_error("no non-reset edge pair was validated");
    return analyzer.report;
}

void writeReport(const std::filesystem::path &output, const std::filesystem::path &wave,
                 const std::string &scope, const Report &report, double wallSeconds) {
    std::ofstream stream(output);
    if (!stream) throw std::runtime_error("cannot open report: " + output.string());
    stream << "{\n  \"schema\": \"wolvrix.rab-write-stats.v1\",\n"
           << "  \"waveform\": " << quote(wave.string()) << ",\n  \"scope\": " << quote(scope) << ",\n"
           << "  \"validation_passed\": " << (report.failedEdges ? "false" : "true") << ",\n"
           << "  \"wall_s\": " << wallSeconds << ",\n"
           << "  \"semantics\": {\"sample\": \"settled low phase before each rising timestamp group\", "
           << "\"address\": \"enqPtrVec[popcount(realNeedAlloc lanes strictly before this lane)].value\", "
           << "\"mask\": \"all logical bits of each recorded column\", "
           << "\"priority\": \"higher lane overwrites lower lane at the same address\", "
           << "\"same_as_old\": \"each lane compared with pre-edge state, including superseded lanes\", "
           << "\"included_edges\": \"both this and next edge are non-reset; full next-edge state reconstruction passes\"},\n"
           << "  \"missing_columns\": [\"vlWen\", \"robIdx.flag\", \"robIdx.value\"],\n"
           << "  \"rising_edges\": " << report.risingEdges << ",\n  \"reset_edges\": " << report.resetEdges
           << ",\n  \"excluded_pairs_with_reset\": " << report.resetPairs
           << ",\n  \"validated_edges\": " << report.validatedEdges
           << ",\n  \"validation_failed_edges\": " << report.failedEdges
           << ",\n  \"mismatched_leaves\": " << report.mismatchedLeaves
           << ",\n  \"unverified_tail_edges\": " << report.unverifiedTail
           << ",\n  \"first_rising_time\": " << report.firstTime
           << ",\n  \"last_rising_time\": " << report.lastTime
           << ",\n  \"edges_with_writes\": " << report.writtenEdges
           << ",\n  \"all_recorded_columns_unchanged_edges\": " << report.unchangedEdges
           << ",\n  \"written_edges_all_recorded_columns_unchanged\": " << report.writtenUnchangedEdges
           << ",\n  \"superseded_lane_writes\": " << report.collisions << ",\n  \"columns\": {\n";
    for (std::size_t column = 0; column < columns; ++column) {
        const auto &stats = report.column[column];
        stream << "    " << quote(names[column]) << ": {\"width\": " << widths[column]
               << ", \"final_unchanged_edges\": " << stats.unchangedEdges
               << ", \"written_final_unchanged_edges\": " << stats.writtenUnchangedEdges
               << ", \"touched_leaves\": " << stats.touchedLeaves
               << ", \"unchanged_touched_leaves\": " << stats.unchangedTouchedLeaves << ", \"lanes\": [";
        for (std::size_t lane = 0; lane < lanes; ++lane) {
            const auto &entry = stats.lane[lane];
            if (lane) stream << ", ";
            stream << "{\"lane\": " << lane << ", \"enabled_writes\": " << entry.enabled
                   << ", \"same_as_old_writes\": " << entry.sameOld
                   << ", \"winning_writes\": " << entry.winning
                   << ", \"winning_same_as_old_writes\": " << entry.winningSameOld << '}';
        }
        stream << "]}" << (column + 1 == columns ? "\n" : ",\n");
    }
    stream << "  },\n  \"first_mismatches\": [";
    for (std::size_t i = 0; i < report.mismatches.size(); ++i) {
        if (i) stream << ", ";
        stream << quote(report.mismatches[i]);
    }
    stream << "]\n}\n";
    if (!stream) throw std::runtime_error("cannot write report");
}

void writeFixture(const std::filesystem::path &path, bool corrupt) {
    fstWriterContext *writer = fstWriterCreate(path.c_str(), 1);
    if (!writer) throw std::runtime_error("cannot create fixture");
    std::map<std::string, fstHandle> handles;
    const auto required = bindings("Rob.rab");
    fstWriterSetScope(writer, FST_ST_VCD_MODULE, "Rob", nullptr);
    handles["Rob.clock"] = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_INPUT, 1, "clock", 0);
    fstWriterSetScope(writer, FST_ST_VCD_MODULE, "rab", nullptr);
    for (const auto &[name, binding] : required) {
        if (name == "Rob.clock") continue;
        handles[name] = fstWriterCreateVar(writer, FST_VT_VCD_WIRE, FST_VD_IMPLICIT,
            binding.width, name.substr(8).c_str(), 0);
    }
    fstWriterSetUpscope(writer);
    fstWriterSetUpscope(writer);
    const auto emit = [&](const std::string &name, unsigned value) {
        const auto &binding = required.at(name);
        fstWriterEmitValueChange32(writer, handles.at(name), binding.width, value);
    };
    const auto local = [&](const std::string &name, unsigned value) { emit("Rob.rab." + name, value); };
    const auto clock = [&](unsigned time, unsigned value) {
        fstWriterEmitTimeChange(writer, time);
        emit("Rob.clock", value);
    };
    fstWriterEmitTimeChange(writer, 0);
    for (const auto &[name, binding] : required) emit(name, name == "Rob.rab.reset");
    clock(2, 1);
    clock(3, 0);
    local("reset", 0);
    local("enqPtrVec_0_value", 5);
    local("enqPtrVec_1_value", 5);
    local("realNeedAlloc_2", 1);
    local("realNeedAlloc_5", 1);
    for (const auto name : names) local(std::string("io_req_2_bits_") + name, 1);
    clock(4, 1);
    // Same-timestamp input changes must not affect the preceding low phase.
    local("realNeedAlloc_2", 0);
    local("realNeedAlloc_5", 0);
    clock(5, 0);
    local("enqPtrVec_0_value", 7);
    local("realNeedAlloc_1", 1);
    for (std::size_t column = 0; column < columns; ++column)
        local(std::string("io_req_1_bits_") + names[column], column == 0 ? 5 : column == 1 ? 93 : 1);
    clock(6, 1);
    local("realNeedAlloc_1", 0);
    for (std::size_t column = 0; column < columns; ++column)
        local(std::string("renameBuffer_7_info_") + names[column], column == 0 ? 5 : column == 1 ? 93 : 1);
    clock(7, 0);
    clock(8, 1);
    if (corrupt) local("renameBuffer_99_info_ldest", 1);
    clock(9, 0);
    clock(10, 1);
    fstWriterClose(writer);
}

void selftest(const std::filesystem::path &directory) {
    std::filesystem::create_directories(directory);
    for (const bool corrupt : {false, true}) {
        const auto wave = directory / (corrupt ? "corrupt.fst" : "valid.fst");
        writeFixture(wave, corrupt);
        const auto report = analyze(wave, "Rob.rab");
        writeReport(directory / (corrupt ? "corrupt.json" : "valid.json"), wave, "Rob.rab", report, 0);
        if (report.risingEdges != 5 || report.resetEdges != 1 || report.resetPairs != 1 || report.unverifiedTail != 1)
            throw std::runtime_error("selftest edge/reset accounting failed");
        if (corrupt) {
            if (report.failedEdges != 1 || report.mismatchedLeaves != 1)
                throw std::runtime_error("selftest failed to detect an unwritten state mismatch");
            continue;
        }
        if (report.failedEdges || report.validatedEdges != 3 || report.writtenEdges != 2 ||
            report.writtenUnchangedEdges != 1 || report.unchangedEdges != 2 || report.collisions != 1)
            throw std::runtime_error("selftest write/priority accounting failed");
        for (const auto &column : report.column) {
            if (column.touchedLeaves != 2 || column.unchangedTouchedLeaves != 1 ||
                column.lane[2].enabled != 1 || column.lane[2].sameOld != 0 || column.lane[2].winning != 0 ||
                column.lane[5].enabled != 1 || column.lane[5].sameOld != 1 || column.lane[5].winningSameOld != 1 ||
                column.lane[1].enabled != 1 || column.lane[1].sameOld != 0 || column.lane[1].winning != 1)
                throw std::runtime_error("selftest per-lane/full-mask accounting failed");
        }
    }
    std::cout << "[rab-write-stats] selftest passed: timestamp grouping, reset exclusion, prefix allocation, "
                 "lane priority, unchanged writes, and next-edge mismatch detection\n";
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc == 3 && std::string(argv[1]) == "--selftest") {
            selftest(argv[2]);
            return 0;
        }
        if (argc != 4) {
            std::cerr << "usage: rab_write_stats WAVE RAB_SCOPE OUTPUT_JSON\n"
                         "       rab_write_stats --selftest WORK_DIRECTORY\n";
            return 2;
        }
        const auto start = std::chrono::steady_clock::now();
        const auto report = analyze(argv[1], argv[2]);
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        writeReport(argv[3], argv[1], argv[2], report, elapsed);
        std::cout << "[rab-write-stats] rising_edges=" << report.risingEdges
                  << " validated_edges=" << report.validatedEdges << " failed_edges=" << report.failedEdges
                  << " written_edges=" << report.writtenEdges
                  << " written_unchanged_edges=" << report.writtenUnchangedEdges
                  << " wall_s=" << elapsed << '\n';
        return report.failedEdges ? 1 : 0;
    } catch (const std::exception &error) {
        std::cerr << "[rab-write-stats] ERROR: " << error.what() << '\n';
        return 1;
    }
}
