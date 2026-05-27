#ifndef TGP_ORACLE_HPP
#define TGP_ORACLE_HPP

#include "tgp/algorithm.hpp"
#include "tgp/scorer.hpp"

#include <cstdint>
#include <string>

namespace tgp
{
    struct OracleOptions
    {
        uint32_t maxNodeWeight = 128;
        bool allowOversizeSingleton = true;
        uint32_t threads = 1;
        uint64_t timeLimitSec = 0;
        std::string checkpointPath;
        std::string resumePath;
    };

    struct OracleResult
    {
        bool optimal = false;
        bool bounded = false;
        PartitionResult incumbent;
        PartitionScore score;
        uint64_t lowerBoundCutWeight = 0;
        uint64_t searchedStates = 0;
        uint64_t prunedByWeight = 0;
        uint64_t prunedByBound = 0;
        uint64_t prunedByCycle = 0;
        uint64_t totalTasks = 0;
        uint64_t completedTasks = 0;
        uint64_t nextTask = 0;
        uint32_t prefixDepth = 0;
        std::string status;
        std::string checkpointPath;
    };

    OracleResult runOracle(const ComputeDag &graph, const OracleOptions &options);
    std::string oracleToJson(const OracleResult &result);
}

#endif
