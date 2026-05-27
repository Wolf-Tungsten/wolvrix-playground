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
        std::vector<uint64_t> partSizes(score.parts, 0);
        for (uint32_t node = 0; node < graph.nodes.size(); ++node)
        {
            ++partSizes[partByNode[node]];
        }
        for (const Edge &edge : graph.edges)
        {
            if (partByNode[edge.src] != partByNode[edge.dst])
            {
                score.cutWeight += edge.weight;
                ++score.cutEdges;
            }
        }
        if (!partSizes.empty())
        {
            score.maxPartSize = *std::max_element(partSizes.begin(), partSizes.end());
            const uint64_t total = std::accumulate(partSizes.begin(), partSizes.end(), uint64_t{0});
            score.meanPartSize = static_cast<double>(total) / static_cast<double>(partSizes.size());
            std::sort(partSizes.begin(), partSizes.end());
            const std::size_t p90 = std::min(partSizes.size() - 1,
                                             static_cast<std::size_t>((partSizes.size() * 90) / 100));
            score.p90PartSize = partSizes[p90];
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
        out << "  \"max_part_size\":" << score.maxPartSize << ",\n";
        out << "  \"mean_part_size\":" << score.meanPartSize << ",\n";
        out << "  \"p90_part_size\":" << score.p90PartSize << ",\n";
        out << "  \"quotient_edges\":" << score.quotientEdges << ",\n";
        out << "  \"quotient_avg_out_degree\":" << score.quotientAvgOutDegree << ",\n";
        out << "  \"quotient_p99_out_degree\":" << score.quotientP99OutDegree << ",\n";
        out << "  \"runtime_ms\":" << score.runtimeMs << "\n";
        out << "}\n";
        return out.str();
    }
}
