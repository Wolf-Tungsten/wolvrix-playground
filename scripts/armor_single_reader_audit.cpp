// Inspect single-target values in a WOLVRIX_ACTIVITY_STAGE_TRACE dump.
// Build with a C++20 compiler. Usage: armor_single_reader_audit TRACE_DIR [--visits FILE] CAP ...
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using Id = std::uint32_t;
using Path = std::filesystem::path;
constexpr Id missing = std::numeric_limits<Id>::max();

Id readId(std::string_view field)
{
    Id value;
    const auto result = std::from_chars(field.data(), field.data() + field.size(), value);
    if (result.ec != std::errc{} || result.ptr != field.data() + field.size())
        throw std::runtime_error("invalid numeric field: " + std::string(field));
    return value;
}

// These dumps contain native uint32_t words and length-prefixed ID arrays.
class Dump
{
public:
    explicit Dump(const Path &path) : path_(path)
    {
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        const auto length = input.tellg();
        if (length < 0 || static_cast<std::size_t>(length) % sizeof(Id) != 0) fail();
        words_.resize(static_cast<std::size_t>(length) / sizeof(Id));
        input.seekg(0);
        if (!input.read(reinterpret_cast<char *>(words_.data()), length)) fail();
    }

    Id word()
    {
        if (pos_ == words_.size()) fail();
        return words_[pos_++];
    }

    std::span<const Id> ids()
    {
        const auto count = word();
        if (count > words_.size() - pos_) fail();
        const auto values = std::span(words_).subspan(pos_, count);
        pos_ += count;
        return values;
    }

    void finish() const { if (pos_ != words_.size()) fail(); }
    void rewind() { pos_ = 0; }

private:
    [[noreturn]] void fail() const { throw std::runtime_error("invalid stage dump: " + path_.string()); }
    Path path_;
    std::vector<Id> words_;
    std::size_t pos_ = 0;
};

template<class Visitor>
void visitRows(const Path &path, Visitor visit)
{
    std::ifstream stream(path);
    std::string line;
    if (!std::getline(stream, line)) throw std::runtime_error("missing TSV header: " + path.string());
    std::vector<std::string_view> columns;
    while (std::getline(stream, line))
    {
        columns.clear();
        std::string_view rest(line);
        for (auto tab = rest.find('\t'); tab != rest.npos; tab = rest.find('\t'))
        {
            columns.push_back(rest.substr(0, tab));
            rest.remove_prefix(tab + 1);
        }
        columns.push_back(rest);
        visit(columns);
    }
    if (stream.bad()) throw std::runtime_error("cannot read " + path.string());
}

void assignOwner(std::vector<Id> &owners, Id member, Id owner)
{
    if (member >= owners.size()) owners.resize(static_cast<std::size_t>(member) + 1, missing);
    if (owners[member] != missing) throw std::runtime_error("duplicate membership");
    owners[member] = owner;
}

struct FitCount
{
    std::size_t fits = 0;
    std::size_t fitsAndOrder = 0;
    std::size_t fitsWithoutOldReader = 0;
    std::size_t colder = 0;
    std::size_t equal = 0;
    std::size_t hotter = 0;
};

void audit(const Path &dir, std::map<std::size_t, FitCount> limits, const Path &visits)
{
    Dump clusters(dir / "clusters-after-coarsen-topo.groups.bin");
    const Id clusterCount = clusters.word();
    std::vector<Id> nodeCluster, opCluster;
    for (Id cluster = 0; cluster < clusterCount; ++cluster)
        for (Id node : clusters.ids()) assignOwner(nodeCluster, node, cluster);
    clusters.finish();

    Dump nodes(dir / "nodes-final.nodes.bin");
    const Id nodeCount = nodes.word();
    if (nodeCount != nodeCluster.size()) throw std::runtime_error("node inventory differs");
    std::vector<std::size_t> clusterOps(clusterCount);
    for (Id node = 0; node < nodeCount; ++node)
    {
        nodes.word();
        const auto operations = nodes.ids();
        nodes.ids();
        const Id cluster = nodeCluster[node];
        clusterOps.at(cluster) += operations.size();
        for (Id op : operations) assignOwner(opCluster, op, cluster);
    }
    nodes.finish();

    Dump members(dir / "final-compute-members.groups.bin");
    const Id groupCount = members.word();
    std::vector<std::size_t> groupOps(groupCount);
    std::vector<Id> clusterGroup(clusterCount, missing), rank(groupCount, missing);
    for (Id group = 0; group < groupCount; ++group)
    {
        for (Id node : members.ids())
        {
            const Id cluster = nodeCluster.at(node);
            if (clusterGroup.at(cluster) == missing)
            {
                clusterGroup[cluster] = group;
                groupOps[group] += clusterOps[cluster];
            }
            else if (clusterGroup[cluster] != group)
                throw std::runtime_error("final groups split a coarsened cluster");
        }
    }
    members.finish();
    std::vector<std::uint64_t> fires;
    if (!visits.empty())
    {
        // Native uint64_t visit counts indexed by compute supernode ID, including ID gaps.
        const auto last = std::find_if(groupOps.rbegin(), groupOps.rend(), [](auto n) { return n != 0; });
        fires.resize(static_cast<std::size_t>(last.base() - groupOps.begin()));
        std::ifstream input(visits, std::ios::binary);
        if (!input.read(reinterpret_cast<char *>(fires.data()), fires.size() * sizeof(fires[0])) ||
            input.peek() != std::ifstream::traits_type::eof())
            throw std::runtime_error("group visit count differs from the schedule: " + visits.string());
    }
    Dump topo(dir / "final-supernode-topo.order.bin");
    const auto order = topo.ids();
    if (order.size() != groupCount) throw std::runtime_error("topological group count differs");
    for (Id i = 0; i < order.size(); ++i) rank.at(order[i]) = i;
    topo.finish();

    Dump fanout(dir / "final-value-fanout.groups.bin");
    const Id valueCount = fanout.word();
    std::vector<Id> producer(valueCount + 1, missing), earliest(clusterCount, missing);
    std::vector<char> ordinaryOp(opCluster.size()), ordinary(valueCount + 1), oldReader(valueCount + 1);
    visitRows(dir / "after-clone.ops.tsv", [&](const auto &row) {
        const auto op = readId(row.at(0));
        const auto kind = row.at(1);
        if (op < ordinaryOp.size())
            ordinaryOp[op] = kind != "kConstant" && kind != "kRegisterReadPort" &&
                             kind != "kLatchReadPort" && kind != "kMemoryReadPort";
    });
    visitRows(dir / "after-clone.values.tsv", [&](const auto &row) {
        const auto value = readId(row.at(0));
        const auto def = readId(row.at(4));
        if (value <= valueCount && def != 0 && def < opCluster.size())
        {
            producer[value] = opCluster[def];
            ordinary[value] = ordinaryOp[def];
        }
    });

    // A cluster moved to its reader must precede the readers of all its outputs.
    // The final fanout omits uses internal to an old group. Recover them from node inputs.
    nodes.rewind();
    nodes.word();
    for (Id node = 0; node < nodeCount; ++node)
    {
        nodes.word();
        nodes.ids();
        const Id target = nodeCluster[node];
        const Id group = clusterGroup.at(target);
        for (Id value : nodes.ids())
        {
            const Id source = producer.at(value);
            if (source == missing || source == target) continue;
            earliest[source] = std::min(earliest[source], rank.at(group));
            if (clusterGroup[source] == group) oldReader[value] = true;
        }
    }
    nodes.finish();
    for (Id value = 1; value <= valueCount; ++value)
    {
        const auto targets = fanout.ids();
        if (producer[value] != missing)
            for (Id target : targets)
            {
                auto &first = earliest[producer[value]];
                first = std::min(first, rank.at(target));
            }
    }
    fanout.finish();

    std::size_t compute = 0, commit = 0, internal = 0, orderFits = 0;
    fanout.rewind();
    fanout.word();
    for (Id value = 1; value <= valueCount; ++value)
    {
        const auto targets = fanout.ids();
        const Id source = producer[value];
        if (!ordinary[value] || source == missing || targets.size() != 1) continue;
        const Id target = targets.front();
        if (groupOps.at(target) == 0) { ++commit; continue; }
        ++compute;
        internal += oldReader[value];
        const bool orderOK = earliest[source] >= rank[target];
        orderFits += orderOK;
        const auto needed = groupOps[target] + clusterOps[source];
        for (auto it = limits.lower_bound(needed); it != limits.end(); ++it)
        {
            ++it->second.fits;
            it->second.fitsAndOrder += orderOK;
            it->second.fitsWithoutOldReader += !oldReader[value];
            if (orderOK && !fires.empty())
            {
                const auto old = fires.at(clusterGroup[source]), next = fires.at(target);
                it->second.colder += next < old;
                it->second.equal += next == old;
                it->second.hotter += next > old;
            }
        }
    }
    fanout.finish();
    std::cout << "ordinary_total " << compute + commit << "\ncompute_target " << compute
              << "\ncommit_target " << commit << "\nother_read_in_old_group " << internal
              << "\nfixed_order_ok " << orderFits << "\n";
    std::cout << "cap\tfits\tfits_and_order_ok\tfits_without_old_reader";
    if (!fires.empty()) std::cout << "\torder_ok_colder\torder_ok_equal\torder_ok_hotter";
    std::cout << '\n';
    for (const auto &[cap, count] : limits)
    {
        std::cout << cap << '\t' << count.fits << '\t' << count.fitsAndOrder
                  << '\t' << count.fitsWithoutOldReader;
        if (!fires.empty()) std::cout << '\t' << count.colder << '\t' << count.equal << '\t' << count.hotter;
        std::cout << '\n';
    }
}
} // namespace

int main(int argc, char **argv)
{
    if (argc < 3) {
        std::cerr << "usage: armor_single_reader_audit STAGE_TRACE_DIRECTORY [--visits FILE] CAP ...\n";
        return 2;
    }
    try
    {
        std::map<std::size_t, FitCount> limits;
        Path visits;
        for (int i = 2; i < argc; ++i)
        {
            if (std::string_view(argv[i]) == "--visits" && i + 1 < argc) visits = argv[++i];
            else limits.try_emplace(readId(argv[i]));
        }
        if (limits.empty()) throw std::runtime_error("supply at least one group capacity");
        audit(argv[1], std::move(limits), visits);
    }
    catch (const std::exception &e)
    {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
