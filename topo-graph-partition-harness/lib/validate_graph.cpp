#include "tgp/validator.hpp"

#include <algorithm>
#include <numeric>
#include <unordered_set>

namespace tgp
{
    void ValidationResult::fail(std::string message)
    {
        ok = false;
        errors.push_back(std::move(message));
    }

    ValidationResult validateGraph(const ComputeDag &graph)
    {
        ValidationResult result;
        if (graph.graphId.empty())
        {
            result.fail("graph_id is empty");
        }
        std::vector<uint8_t> seen(graph.nodes.size(), 0);
        std::vector<uint32_t> topoSeen(graph.nodes.size(), 0);
        for (const Node &node : graph.nodes)
        {
            if (node.id >= graph.nodes.size())
            {
                result.fail("node id out of range: " + std::to_string(node.id));
                continue;
            }
            if (seen[node.id]++)
            {
                result.fail("duplicate node id: " + std::to_string(node.id));
            }
            if (node.topoPos >= graph.nodes.size())
            {
                result.fail("topo_pos out of range for node: " + std::to_string(node.id));
            }
            else
            {
                ++topoSeen[node.topoPos];
            }
        }
        for (uint32_t id = 0; id < seen.size(); ++id)
        {
            if (!seen[id])
            {
                result.fail("missing node id: " + std::to_string(id));
            }
            if (id < topoSeen.size() && topoSeen[id] != 1)
            {
                result.fail("topo_pos is not a permutation at position: " + std::to_string(id));
            }
        }
        for (const Edge &edge : graph.edges)
        {
            if (edge.src >= graph.nodes.size() || edge.dst >= graph.nodes.size())
            {
                result.fail("edge endpoint out of range");
                continue;
            }
            if (edge.src == edge.dst)
            {
                result.fail("self edge at node: " + std::to_string(edge.src));
            }
            if (edge.weight == 0)
            {
                result.fail("edge weight must be positive");
            }
            if (graph.nodes[edge.src].topoPos >= graph.nodes[edge.dst].topoPos)
            {
                result.fail("edge violates topo_pos order: " + std::to_string(edge.src) + " -> " +
                            std::to_string(edge.dst));
            }
        }
        std::vector<uint32_t> topo;
        if (!topologicalOrder(static_cast<uint32_t>(graph.nodes.size()), graph.edges, topo))
        {
            result.fail("input graph is not a DAG");
        }
        return result;
    }
}
