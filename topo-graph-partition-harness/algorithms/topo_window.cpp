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
                result.maxNodeWeight = config.maxNodeWeight;
                result.allowOversizeSingleton = config.allowOversizeSingleton;
                result.partByNode.assign(graph.nodes.size(), 0);

                uint32_t part = 0;
                uint64_t currentWeight = 0;
                for (const uint32_t node : order)
                {
                    const uint32_t weight = graph.nodes[node].weight;
                    if (currentWeight != 0 && config.maxNodeWeight != 0 &&
                        currentWeight + weight > config.maxNodeWeight)
                    {
                        ++part;
                        currentWeight = 0;
                    }
                    result.partByNode[node] = part;
                    currentWeight += weight;
                    if (config.maxNodeWeight != 0 && weight > config.maxNodeWeight)
                    {
                        ++part;
                        currentWeight = 0;
                    }
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
