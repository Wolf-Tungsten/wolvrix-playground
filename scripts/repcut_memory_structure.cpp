// Reuse RepCut's actual cone and ownership rules in a read-only research tool.
#include "repcut_grhsim_assignment_extract.hpp"

namespace
{
    std::ofstream table(const std::filesystem::path &path)
    {
        std::ofstream out(path);
        out.exceptions(std::ios::badbit | std::ios::failbit);
        return out;
    }

    std::string tsv(std::string text)
    {
        if (text.find_first_of("\t\r\n") != std::string::npos)
            throw std::runtime_error("control character in graph identifier");
        return text;
    }

    uint64_t coneWeight(const grh::Graph &graph, const PhaseAData &a,
                        const PhaseBData &b, const AscInfo &asc,
                        std::vector<uint32_t> &weights)
    {
        std::unordered_set<NodeId> nodes(asc.combOps.begin(), asc.combOps.end());
        for (auto i : asc.sinks)
            if (b.sinks[i].kind == SinkRef::Kind::Operation)
                nodes.insert(a.opToNode.at(b.sinks[i].op));
        uint64_t result = 0;
        for (auto node : nodes)
            result += calculateNodeWeight(graph, a, node, weights, RepcutCostModel::kLegacy);
        return result;
    }

    void capture(const grh::Graph &graph, const PhaseAData &a, const PhaseBData &b,
                 const std::unordered_set<grh::ValueId, grh::ValueIdHash> &inouts,
                 const std::filesystem::path &output)
    {
        const auto analysis = output / "analysis", incidence = output / "capture";
        std::filesystem::create_directories(analysis);
        std::filesystem::create_directories(incidence);
        auto sinks = table(analysis / "state_sink_to_asc.tsv");
        sinks << "sink_index\tasc_id\tkind\top_index\top_symbol\tstate_symbol\n";
        auto memories = table(analysis / "memory_symbol_to_asc.tsv");
        memories << "memory_symbol\tasc_id\n";
        std::map<std::string, uint32_t> memoryOwners;
        std::unordered_map<std::string, bool> supported;
        for (std::size_t i = 0; i < b.sinks.size(); ++i)
        {
            const auto &sink = b.sinks[i];
            sinks << i << '\t' << b.sinkToAsc[i] << '\t';
            if (sink.kind == SinkRef::Kind::OutputValue)
            {
                sinks << "output\t-1\t\t\n";
                continue;
            }
            const auto op = graph.getOperation(sink.op);
            const auto symbol = getAttrString(op, "regSymbol").value_or(
                getAttrString(op, "latchSymbol").value_or(getAttrString(op, "memSymbol").value_or("")));
            sinks << toString(op.kind()) << '\t' << sink.op.index << '\t'
                  << tsv(std::string(op.symbolText())) << '\t' << tsv(symbol) << '\n';
            if (op.kind() == OpKind::kMemoryWritePort)
            {
                const auto [it, added] = memoryOwners.emplace(symbol, b.sinkToAsc[i]);
                if (!added && it->second != b.sinkToAsc[i])
                    throw std::runtime_error("memory writer ownership split");
                bool eligible = op.operands().size() >= 4;
                if (eligible)
                {
                    const auto def = graph.valueDef(op.operands()[3]);
                    eligible = def.valid() && graph.getOperation(def).kind() == OpKind::kConstant;
                    const auto edges = getAttrStrings(op, "eventEdge");
                    eligible = eligible && edges && edges->size() == op.operands().size() - 4;
                }
                auto [support, first] = supported.emplace(symbol, eligible);
                if (!first) support->second = support->second && eligible;
            }
        }
        for (const auto &[symbol, owner] : memoryOwners)
            memories << tsv(symbol) << '\t' << owner << '\n';
        auto shapes = table(analysis / "memory_shapes.json");
        shapes << '{';
        bool firstShape = true;
        for (auto id : graph.operations())
        {
            const auto op = graph.getOperation(id);
            if (op.kind() != OpKind::kMemory) continue;
            const auto width = getAttr<int64_t>(op, "width").value_or(0);
            const auto rows = getAttr<int64_t>(op, "row").value_or(0);
            const std::string symbol(op.symbolText());
            if (!firstShape) shapes << ',';
            firstShape = false;
            shapes << '\"' << jsonEscape(symbol) << "\":{\"rows\":" << rows
                   << ",\"width\":" << width << ",\"eligible\":"
                   << (rows > 0 && width > 0 && supported.contains(symbol) && supported.at(symbol) ? "true" : "false") << '}';
        }
        shapes << "}\n";
        {
            auto out = table(incidence / "sink_memory_cone.tsv");
            out << "sink_index\tmemory_symbol\n";
            MemSymbolIntern intern;
            MemSymbolMemo memo;
            memo.nodeToMemSymbolIds.resize(a.nodeToOp.size());
            memo.nodeState.resize(a.nodeToOp.size());
            for (std::size_t i = 0; i < b.sinks.size(); ++i)
            {
                std::unordered_set<uint32_t> symbols;
                MemSymbolCollectStats stats;
                collectConeMemSymbolIds(graph, a, b.sinks[i], inouts, intern, memo, symbols, stats);
                for (auto id : symbols) out << i << '\t' << tsv(intern.idToSymbol.at(id)) << '\n';
            }
        }
        {
            auto out = table(incidence / "sink_effect_result.tsv");
            out << "sink_index\teffect_op_index\teffect_op_symbol\tsrc_file\tsrc_line\n";
            EffectResultMemo memo;
            memo.nodeToEffectResultOps.resize(a.nodeToOp.size());
            memo.nodeState.resize(a.nodeToOp.size());
            for (std::size_t i = 0; i < b.sinks.size(); ++i)
            {
                std::unordered_set<grh::OperationId, grh::OperationIdHash> effects;
                EffectResultCollectStats stats;
                collectConeEffectResultOps(graph, a, b.sinks[i], inouts, memo, effects, stats);
                for (auto id : effects)
                    out << i << '\t' << id.index << '\t'
                        << tsv(std::string(graph.getOperation(id).symbolText())) << "\t\t0\n";
            }
        }
        std::vector<uint32_t> weights(a.nodeToOp.size(), UINT32_MAX);
        uint32_t largest = 0;
        uint64_t maximum = 0;
        for (uint32_t i = 0; i < b.ascs.size(); ++i)
        {
            const auto weight = coneWeight(graph, a, b, b.ascs[i], weights);
            if (weight > maximum) { maximum = weight; largest = i; }
        }
        std::ostringstream summary;
        summary << "{\"asc_count\":" << b.ascs.size() << ",\"sink_count\":" << b.sinks.size()
                << ",\"node_count\":" << a.nodeToOp.size() << ",\"max_full_closure_asc_id\":" << largest
                << ",\"max_full_closure_weight\":" << maximum << ",\"max_sinks\":" << b.ascs.at(largest).sinks.size() << '}';
        table(analysis / "summary.json") << summary.str() << '\n';
        std::cout << "CAPTURE_PASS " << summary.str() << std::endl;
    }

    void metrics(const grh::Graph &graph, const PhaseAData &a, const PhaseBData &b,
                 const std::unordered_set<grh::ValueId, grh::ValueIdHash> &inouts,
                 const std::filesystem::path &requests, const std::filesystem::path &output)
    {
        std::ifstream input(requests);
        std::string line;
        if (!std::getline(input, line) || line != "candidate_id\tcomponent_rank\tsink_index")
            throw std::runtime_error("invalid cone metric request header");
        std::map<std::string, std::map<unsigned, AscInfo>> candidates;
        while (std::getline(input, line))
        {
            std::istringstream row(line);
            std::string name; unsigned rank; std::size_t sink;
            if (!(row >> name >> rank >> sink) || sink >= b.sinks.size())
                throw std::runtime_error("invalid cone metric request");
            candidates[name][rank].sinks.push_back(sink);
        }
        std::vector<uint32_t> weights(a.nodeToOp.size(), UINT32_MAX), visited(a.nodeToOp.size());
        uint32_t epoch = 0;
        auto records = table(output / "metrics.json");
        records << '[';
        bool firstRecord = true;
        for (auto &[name, groups] : candidates)
        {
            uint64_t maximum = 0, sum = 0;
            std::set<std::size_t> covered;
            std::optional<uint32_t> original;
            for (auto &[rank, asc] : groups)
            {
                for (auto sink : asc.sinks)
                {
                    if (!covered.insert(sink).second) throw std::runtime_error("duplicate sink in candidate");
                    if (!original) original = b.sinkToAsc[sink];
                    if (*original != b.sinkToAsc[sink]) throw std::runtime_error("candidate crosses input ASC");
                }
                collectAscCone(graph, a, b.sinks, inouts, visited, ++epoch, asc);
                const auto work = coneWeight(graph, a, b, asc, weights);
                maximum = std::max(maximum, work); sum += work;
            }
            if (!original || covered.size() != b.ascs[*original].sinks.size())
                throw std::runtime_error("candidate does not cover its complete source ASC");
            const auto before = coneWeight(graph, a, b, b.ascs[*original], weights);
            if (sum < before) throw std::runtime_error("component cone union lost work");
            if (!firstRecord) records << ',';
            firstRecord = false;
            records << "{\"name\":\"" << jsonEscape(name) << "\",\"baseline_work\":" << before
                    << ",\"max_work\":" << maximum << ",\"total_work\":" << sum
                    << ",\"extra_work\":" << sum - before << ",\"groups\":" << groups.size() << '}';
        }
        records << "]\n";
        std::cout << "METRICS_PASS candidates=" << candidates.size() << std::endl;
    }
}

int main(int argc, char **argv)
{
    try
    {
        if (argc < 4 || argc > 5) throw std::runtime_error("usage: memory_structure capture|metrics input.json output [requests.tsv]");
        grh::Design design;
        { Mapping input(argv[2]); design = grh::Design::fromJsonString(input.text()); }
        if (design.topGraphs().size() != 1) throw std::runtime_error("expected one flat top graph");
        const auto &graph = *design.findGraph(design.topGraphs()[0]);
        std::cout << "LOADED " << graph.symbol() << std::endl;
        const auto a = buildPhaseAData(graph);
        std::unordered_set<grh::ValueId, grh::ValueIdHash> inouts;
        for (const auto &port : graph.inoutPorts()) inouts.insert(port.in);
        const auto b = buildAscs(graph, a, inouts, [](const auto &s) { std::cout << s << std::endl; });
        const std::filesystem::path output(argv[3]);
        std::filesystem::create_directories(output);
        if (std::string_view(argv[1]) == "capture" && argc == 4) capture(graph, a, b, inouts, output);
        else if (std::string_view(argv[1]) == "metrics" && argc == 5) metrics(graph, a, b, inouts, argv[4], output);
        else throw std::runtime_error("invalid mode or arguments");
    }
    catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
