#include "tgp/validator.hpp"

#include <algorithm>
#include <map>
#include <queue>

namespace tgp
{
    bool topologicalOrder(uint32_t nodeCount, const std::vector<Edge> &edges, std::vector<uint32_t> &order)
    {
        std::vector<uint32_t> indegree(nodeCount, 0);
        std::vector<std::vector<uint32_t>> out(nodeCount);
        for (const Edge &edge : edges)
        {
            if (edge.src >= nodeCount || edge.dst >= nodeCount)
            {
                return false;
            }
            out[edge.src].push_back(edge.dst);
            ++indegree[edge.dst];
        }
        std::queue<uint32_t> ready;
        for (uint32_t node = 0; node < nodeCount; ++node)
        {
            if (indegree[node] == 0)
            {
                ready.push(node);
            }
        }
        order.clear();
        order.reserve(nodeCount);
        while (!ready.empty())
        {
            const uint32_t node = ready.front();
            ready.pop();
            order.push_back(node);
            for (const uint32_t succ : out[node])
            {
                if (--indegree[succ] == 0)
                {
                    ready.push(succ);
                }
            }
        }
        return order.size() == nodeCount;
    }

    std::vector<PartId> canonicalizePartByNode(const std::vector<PartId> &partByNode)
    {
        std::vector<PartId> parts;
        parts.reserve(partByNode.size());
        for (const PartId part : partByNode)
        {
            if (part != kInvalidPartId)
            {
                parts.push_back(part);
            }
        }
        std::sort(parts.begin(), parts.end());
        parts.erase(std::unique(parts.begin(), parts.end()), parts.end());
        std::map<PartId, PartId> canonical;
        for (PartId index = 0; index < parts.size(); ++index)
        {
            canonical.emplace(parts[index], index);
        }
        std::vector<PartId> out = partByNode;
        for (PartId &part : out)
        {
            if (part == kInvalidPartId)
            {
                continue;
            }
            part = canonical.at(part);
        }
        return out;
    }

    QuotientGraph buildQuotientGraph(const ComputeDag &graph, const PartitionResult &partition)
    {
        const std::vector<PartId> partByNode = canonicalizePartByNode(partition.partByNode);
        QuotientGraph quotient;
        for (const PartId part : partByNode)
        {
            if (part != kInvalidPartId)
            {
                quotient.parts = std::max(quotient.parts, static_cast<uint32_t>(part + 1));
            }
        }

        std::vector<Edge> edges;
        for (const Edge &edge : graph.edges)
        {
            const PartId srcPart = partByNode[edge.src];
            const PartId dstPart = partByNode[edge.dst];
            if (srcPart == dstPart)
            {
                continue;
            }
            edges.push_back(Edge{srcPart, dstPart, edge.weight});
        }
        std::sort(edges.begin(), edges.end(), [](const Edge &a, const Edge &b) {
            if (a.src != b.src)
            {
                return a.src < b.src;
            }
            return a.dst < b.dst;
        });
        for (const Edge &edge : edges)
        {
            if (!quotient.edges.empty() &&
                quotient.edges.back().src == edge.src &&
                quotient.edges.back().dst == edge.dst)
            {
                quotient.edges.back().weight += edge.weight;
            }
            else
            {
                quotient.edges.push_back(edge);
            }
        }
        quotient.outDegree.assign(quotient.parts, 0);
        for (const Edge &edge : quotient.edges)
        {
            if (edge.src < quotient.outDegree.size())
            {
                ++quotient.outDegree[edge.src];
            }
        }
        topologicalOrder(quotient.parts, quotient.edges, quotient.topoOrder);
        return quotient;
    }
}
