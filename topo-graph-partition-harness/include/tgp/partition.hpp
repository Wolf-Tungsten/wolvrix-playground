#ifndef TGP_PARTITION_HPP
#define TGP_PARTITION_HPP

#include "tgp/graph.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace tgp
{
    struct PartitionResult
    {
        std::string graphId;
        std::string algorithmName = "unknown";
        std::string algorithmVersion = "0.1";
        std::vector<PartId> partByNode;
        std::vector<PartId> partOrderHint;
        uint32_t maxNodeWeight = 0;
        bool allowOversizeSingleton = true;
        double runtimeMs = 0.0;
    };
}

#endif
