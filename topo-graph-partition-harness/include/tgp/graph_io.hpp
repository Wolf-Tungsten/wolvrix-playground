#ifndef TGP_GRAPH_IO_HPP
#define TGP_GRAPH_IO_HPP

#include "tgp/graph.hpp"
#include "tgp/partition.hpp"
#include "tgp/algorithm.hpp"

#include <string>

namespace tgp
{
    ComputeDag readComputeDagFile(const std::string &path);
    PartitionResult readPartitionFile(const std::string &path);
    AlgorithmConfig readAlgorithmConfigFile(const std::string &path);

    void writeTextFile(const std::string &path, const std::string &text);
    std::string readTextFile(const std::string &path);
    std::string partitionToJson(const PartitionResult &partition);
}

#endif
