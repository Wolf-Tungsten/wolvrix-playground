#include "tgp/algorithm.hpp"

#include <algorithm>
#include <chrono>
#include <stdexcept>

namespace tgp
{
    namespace
    {
        class TopoWindowAlgorithm final : public PartitionAlgorithm
        {
        public:
            std::string_view name() const override { return "topo-window"; }

            PartitionResult run(const ComputeDag &graph, const AlgorithmConfig &config) override
            {
                const auto start = std::chrono::steady_clock::now();
                std::vector<uint32_t> order(graph.nodes.size());
                for (uint32_t i = 0; i < order.size(); ++i)
                {
                    order[i] = i;
                }
                std::sort(order.begin(), order.end(), [&](uint32_t a, uint32_t b) {
                    return graph.nodes[a].topoPos < graph.nodes[b].topoPos;
                });

                PartitionResult result;
                result.graphId = graph.graphId;
                result.algorithmName = "topo-window";
                result.algorithmVersion = "0.1";
                result.maxNodesPerPart = config.maxNodesPerPart;
                result.partByNode.assign(graph.nodes.size(), 0);

                uint32_t part = 0;
                uint32_t currentSize = 0;
                for (const uint32_t node : order)
                {
                    if (currentSize != 0 && config.maxNodesPerPart != 0 &&
                        currentSize + 1 > config.maxNodesPerPart)
                    {
                        ++part;
                        currentSize = 0;
                    }
                    result.partByNode[node] = part;
                    ++currentSize;
                }
                uint32_t partCount = 0;
                for (const PartId assignedPart : result.partByNode)
                {
                    partCount = std::max(partCount, static_cast<uint32_t>(assignedPart + 1));
                }
                result.partOrderHint.resize(partCount);
                for (uint32_t i = 0; i < result.partOrderHint.size(); ++i)
                {
                    result.partOrderHint[i] = i;
                }
                const auto elapsed = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - start);
                result.runtimeMs = elapsed.count();
                return result;
            }
        };
    }

    std::unique_ptr<PartitionAlgorithm> createAlgorithm(std::string_view name)
    {
        if (name == "topo-window" || name == "topo_window")
        {
            return std::make_unique<TopoWindowAlgorithm>();
        }
        throw std::runtime_error("unknown algorithm: " + std::string(name));
    }

    std::vector<std::string> availableAlgorithms()
    {
        return {"topo-window"};
    }
}
