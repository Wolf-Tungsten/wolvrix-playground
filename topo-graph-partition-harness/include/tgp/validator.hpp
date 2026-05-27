#ifndef TGP_VALIDATOR_HPP
#define TGP_VALIDATOR_HPP

#include "tgp/graph.hpp"
#include "tgp/partition.hpp"

#include <string>
#include <vector>

namespace tgp
{
    struct ValidationResult
    {
        bool ok = true;
        std::vector<std::string> errors;
        std::vector<std::string> warnings;

        void fail(std::string message);
    };

    struct QuotientGraph
    {
        uint32_t parts = 0;
        std::vector<Edge> edges;
        std::vector<uint32_t> topoOrder;
        std::vector<uint32_t> outDegree;
    };

    ValidationResult validateGraph(const ComputeDag &graph);
    ValidationResult validatePartition(const ComputeDag &graph, const PartitionResult &partition);
    std::vector<PartId> canonicalizePartByNode(const std::vector<PartId> &partByNode);
    QuotientGraph buildQuotientGraph(const ComputeDag &graph, const PartitionResult &partition);
    bool topologicalOrder(uint32_t nodeCount, const std::vector<Edge> &edges, std::vector<uint32_t> &order);
}

#endif
