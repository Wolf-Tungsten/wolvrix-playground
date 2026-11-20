// Replay the emitter's Boolean lane planner on its frozen scheduling sidecars.
#include "grhsim_bool_lane_pack.hpp"
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace wolvrix::lib::emit::bool_lanes;

std::vector<std::string> fields(const std::string &s, char delim)
{
    std::vector<std::string> result;
    size_t begin = 0;
    for (;;)
    {
        size_t end = s.find(delim, begin);
        result.emplace_back(s.substr(begin, end - begin));
        if (end == std::string::npos)
            return result;
        begin = end + 1;
    }
}

int main(int argc, char **argv)
{
    try
    {
        if (argc != 4)
            throw std::runtime_error("usage: audit batch.tsv packs.tsv counts.tsv");
        std::ifstream input(argv[1]);
        std::ofstream packs(argv[2]), counts(argv[3]);
        if (!input || !packs || !counts)
            throw std::runtime_error("cannot open audit files");
        packs.exceptions(std::ios::badbit | std::ios::failbit);
        counts.exceptions(std::ios::badbit | std::ios::failbit);
        Id group = 0;
        bool guarded = false;
        std::vector<Row> rows;
        auto finish = [&]
        {
            if (rows.empty())
                return;
            auto p = Planner(rows, guarded).run();
            using Key = std::tuple<unsigned, uint64_t, unsigned, Kind>;
            std::map<Key, std::vector<Id>> buckets;
            std::unordered_map<Id, unsigned> levels;
            for (const auto &row : rows)
            {
                unsigned depth = 0;
                for (auto input : row.args)
                    if (auto it = levels.find(input); it != levels.end())
                        depth = std::max(depth, it->second + 1);
                if (row.value)
                    levels[row.value] = depth;
                if (!guarded && bitOp(row) && plain(row))
                    buckets[{row.epoch, row.arm, depth, row.kind}].push_back(row.value);
            }
            // Additional offline-only breakdown of the singleton counter. Multiple discarded trials can
            // refer to the same row; those are counted separately below.
            std::map<std::pair<uint64_t, Kind>, unsigned> epochFree;
            std::map<std::pair<unsigned, Kind>, unsigned> armFree;
            std::map<std::pair<unsigned, uint64_t>, std::map<Kind, unsigned>> scopes;
            std::map<Kind, unsigned> kinds;
            for (const auto &[key, values] : buckets)
            {
                auto [epoch, arm, level, kind] = key;
                epochFree[{arm, kind}] += values.size();
                armFree[{epoch, kind}] += values.size();
                scopes[{epoch, arm}][kind] += values.size();
                kinds[kind] += values.size();
            }
            for (const auto &[key, values] : buckets)
                if (values.size() == 1)
                {
                    auto [epoch, arm, level, kind] = key;
                    const char *reason = scopes[{epoch, arm}][kind] > 1 ? "different_depth"
                                         : armFree[{epoch, kind}] > 1   ? "different_arm"
                                         : epochFree[{arm, kind}] > 1   ? "different_epoch"
                                         : kinds[kind] > 1              ? "different_arm_and_epoch"
                                                                        : "no_kind_peer_in_group";
                    ++p.counters[reason];
                }

            for (auto &[k, v] : p.counters)
                counts << group << '\t' << k << '\t' << v << '\n';
            for (auto &s : p.packs)
            {
                packs << group << '\t' << s.anchor << '\t' << s.sink << '\t' << s.roots.size() << '\t' << s.levels
                      << '\t' << s.gatheredBits << '\t' << s.gatherOps << '\t' << s.broadcastOps << '\t'
                      << s.extracts << '\t' << s.scalarCost << '\t' << s.packedCost << '\t' << s.named << '\t';
                for (size_t i = 0; i < s.members.size(); ++i)
                    packs << (i ? "," : "") << s.members[i];
                packs << '\n';
            }
            rows.clear();
        };
        for (std::string line; std::getline(input, line);)
        {
            auto f = fields(line, '\t');
            if (f[0] == "G")
            {
                finish();
                group = std::stoul(f.at(1));
                guarded = std::stoul(f.at(2));
                continue;
            }
            if (f.size() != 13)
                throw std::runtime_error("malformed sidecar");
            Row r;
            r.op = std::stoul(f[0]);
            r.kind = kindFromName(f[1]);
            r.value = std::stoul(f[2]);
            r.width = std::stoul(f[3]);
            r.epoch = std::stoul(f[4]);
            r.arm = std::stoull(f[5]);
            r.flags = std::stoul(f[6]);
            r.uses = std::stoul(f[7]);
            r.slot = std::stoll(f[8]);
            r.symbol = std::move(f[9]);
            r.source = std::move(f[10]);
            r.attr = std::move(f[11]);
            if (!f[12].empty())
                for (const auto &s : fields(f[12], ','))
                    r.args.push_back(std::stoul(s));
            rows.push_back(std::move(r));
        }
        if (!input.eof())
            throw std::runtime_error("input read failed");
        finish();
    }
    catch (const std::exception &e)
    {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
