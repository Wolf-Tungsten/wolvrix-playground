#include "tgp/scorer.hpp"

#include "tgp/json.hpp"
#include "tgp/validator.hpp"

#include <algorithm>
#include <numeric>
#include <sstream>

namespace tgp
{
    PartitionScore scorePartition(const ComputeDag &graph, const PartitionResult &partition)
    {
        PartitionScore score;
        score.runtimeMs = partition.runtimeMs;
        const std::vector<PartId> partByNode = canonicalizePartByNode(partition.partByNode);
        for (const PartId part : partByNode)
        {
            score.parts = std::max(score.parts, static_cast<uint32_t>(part + 1));
        }
        std::vector<uint64_t> partWeights(score.parts, 0);
        for (uint32_t node = 0; node < graph.nodes.size(); ++node)
        {
            partWeights[partByNode[node]] += graph.nodes[node].weight;
        }
        for (const Edge &edge : graph.edges)
        {
            if (partByNode[edge.src] != partByNode[edge.dst])
            {
                score.cutWeight += edge.weight;
                ++score.cutEdges;
            }
        }
        if (!partWeights.empty())
        {
            score.maxPartWeight = *std::max_element(partWeights.begin(), partWeights.end());
            const uint64_t total = std::accumulate(partWeights.begin(), partWeights.end(), uint64_t{0});
            score.meanPartWeight = static_cast<double>(total) / static_cast<double>(partWeights.size());
            std::sort(partWeights.begin(), partWeights.end());
            const std::size_t p90 = std::min(partWeights.size() - 1,
                                             static_cast<std::size_t>((partWeights.size() * 90) / 100));
            score.p90PartWeight = partWeights[p90];
        }
        QuotientGraph quotient = buildQuotientGraph(graph, partition);
        score.quotientEdges = quotient.edges.size();
        if (!quotient.outDegree.empty())
        {
            const uint64_t total = std::accumulate(quotient.outDegree.begin(), quotient.outDegree.end(), uint64_t{0});
            score.quotientAvgOutDegree = static_cast<double>(total) / static_cast<double>(quotient.outDegree.size());
            std::sort(quotient.outDegree.begin(), quotient.outDegree.end());
            const std::size_t p99 = std::min(quotient.outDegree.size() - 1,
                                             static_cast<std::size_t>((quotient.outDegree.size() * 99) / 100));
            score.quotientP99OutDegree = quotient.outDegree[p99];
        }
        return score;
    }

    std::string scoreToJson(const PartitionScore &score)
    {
        std::ostringstream out;
        out << "{\n";
        out << "  \"cut_weight\":" << score.cutWeight << ",\n";
        out << "  \"cut_edges\":" << score.cutEdges << ",\n";
        out << "  \"parts\":" << score.parts << ",\n";
        out << "  \"max_part_weight\":" << score.maxPartWeight << ",\n";
        out << "  \"mean_part_weight\":" << score.meanPartWeight << ",\n";
        out << "  \"p90_part_weight\":" << score.p90PartWeight << ",\n";
        out << "  \"quotient_edges\":" << score.quotientEdges << ",\n";
        out << "  \"quotient_avg_out_degree\":" << score.quotientAvgOutDegree << ",\n";
        out << "  \"quotient_p99_out_degree\":" << score.quotientP99OutDegree << ",\n";
        out << "  \"runtime_ms\":" << score.runtimeMs << "\n";
        out << "}\n";
        return out.str();
    }
}
