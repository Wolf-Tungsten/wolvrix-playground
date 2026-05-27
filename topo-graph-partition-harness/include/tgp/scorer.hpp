#ifndef TGP_SCORER_HPP
#define TGP_SCORER_HPP

#include "tgp/graph.hpp"
#include "tgp/partition.hpp"

#include <cstdint>
#include <string>

namespace tgp
{
    struct PartitionScore
    {
        uint64_t cutWeight = 0;
        uint64_t cutEdges = 0;
        uint32_t parts = 0;
        uint64_t maxPartWeight = 0;
        double meanPartWeight = 0.0;
        uint64_t p90PartWeight = 0;
        uint64_t quotientEdges = 0;
        double quotientAvgOutDegree = 0.0;
        uint64_t quotientP99OutDegree = 0;
        double runtimeMs = 0.0;
    };

    PartitionScore scorePartition(const ComputeDag &graph, const PartitionResult &partition);
    std::string scoreToJson(const PartitionScore &score);
}

#endif
