#ifndef TGP_ALGORITHM_HPP
#define TGP_ALGORITHM_HPP

#include "tgp/graph.hpp"
#include "tgp/partition.hpp"

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace tgp
{
    struct AlgorithmConfig
    {
        uint32_t maxNodeWeight = 128;
        bool allowOversizeSingleton = true;
    };

    class PartitionAlgorithm
    {
    public:
        virtual ~PartitionAlgorithm() = default;
        virtual std::string_view name() const = 0;
        virtual PartitionResult run(const ComputeDag &graph, const AlgorithmConfig &config) = 0;
    };

    std::unique_ptr<PartitionAlgorithm> createAlgorithm(std::string_view name);
    std::vector<std::string> availableAlgorithms();
}

#endif
