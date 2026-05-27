#ifndef TGP_GRAPH_HPP
#define TGP_GRAPH_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace tgp
{
    using NodeId = uint32_t;
    using PartId = uint32_t;

    inline constexpr PartId kInvalidPartId = UINT32_MAX;

    struct Node
    {
        NodeId id = 0;
        uint64_t opId = 0;
        std::string kind;
        std::string symbol;
        uint32_t topoPos = 0;
    };

    struct Edge
    {
        NodeId src = 0;
        NodeId dst = 0;
        uint32_t weight = 1;
    };

    struct ComputeDag
    {
        std::string graphId;
        std::string sourcePass;
        std::string sourcePath;
        std::string edgeWeight = "value_bitwidth_words";
        std::vector<Node> nodes;
        std::vector<Edge> edges;
        std::vector<uint32_t> outBegin;
        std::vector<uint32_t> outEdges;
        std::vector<uint32_t> inBegin;
        std::vector<uint32_t> inEdges;
    };

    void rebuildAdjacency(ComputeDag &graph);
}

#endif
