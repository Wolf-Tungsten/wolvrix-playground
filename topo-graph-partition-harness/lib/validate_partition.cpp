#include "tgp/validator.hpp"

#include <algorithm>
#include <unordered_map>

namespace tgp
{
    ValidationResult validatePartition(const ComputeDag &graph, const PartitionResult &partition)
    {
        ValidationResult result;
        if (partition.graphId != graph.graphId)
        {
            result.fail("partition graph_id does not match graph");
        }
        if (partition.partByNode.size() != graph.nodes.size())
        {
            result.fail("assignment size does not match graph node count");
            return result;
        }

        const std::vector<PartId> partByNode = canonicalizePartByNode(partition.partByNode);
        uint32_t partCount = 0;
        for (const PartId part : partByNode)
        {
            if (part == kInvalidPartId)
            {
                result.fail("assignment contains invalid part id");
                continue;
            }
            partCount = std::max(partCount, static_cast<uint32_t>(part + 1));
        }
        std::vector<uint32_t> counts(partCount, 0);
        for (uint32_t node = 0; node < graph.nodes.size(); ++node)
        {
            const PartId part = partByNode[node];
            if (part >= partCount)
            {
                continue;
            }
            ++counts[part];
        }
        for (uint32_t part = 0; part < partCount; ++part)
        {
            if (counts[part] == 0)
            {
                result.fail("empty part after canonicalization: " + std::to_string(part));
            }
            if (partition.maxNodesPerPart != 0 && counts[part] > partition.maxNodesPerPart)
            {
                result.fail("part exceeds max_nodes_per_part: " + std::to_string(part));
            }
        }

        QuotientGraph quotient = buildQuotientGraph(graph, partition);
        if (quotient.topoOrder.size() != quotient.parts)
        {
            result.fail("quotient graph is cyclic");
        }
        if (!partition.partOrderHint.empty())
        {
            std::vector<PartId> canonicalHint = canonicalizePartByNode(partition.partOrderHint);
            if (canonicalHint.size() != quotient.parts)
            {
                result.fail("part_order_hint size does not match part count");
            }
            else
            {
                std::vector<uint32_t> pos(quotient.parts, UINT32_MAX);
                for (uint32_t i = 0; i < canonicalHint.size(); ++i)
                {
                    const uint32_t part = canonicalHint[i];
                    if (part >= quotient.parts || pos[part] != UINT32_MAX)
                    {
                        result.fail("part_order_hint is not a permutation");
                        break;
                    }
                    pos[part] = i;
                }
                for (const Edge &edge : quotient.edges)
                {
                    if (edge.src < pos.size() && edge.dst < pos.size() && pos[edge.src] >= pos[edge.dst])
                    {
                        result.fail("part_order_hint violates quotient edge order");
                        break;
                    }
                }
            }
        }
        return result;
    }
}
