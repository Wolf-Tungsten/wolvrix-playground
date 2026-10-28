#pragma once
#include "core/grh.hpp"
#include <algorithm>
#include <optional>
#include <unordered_set>
#include <vector>

namespace activity_context {
template <class OriginalPiece>
std::vector<uint32_t> consumerPieces(const wolvrix::lib::grh::Graph &graph,
    wolvrix::lib::grh::OperationId source, OriginalPiece originalPiece) {
    using namespace wolvrix::lib::grh;
    std::vector<uint32_t> pieces;
    std::vector<OperationId> queue{source};
    std::unordered_set<OperationId, OperationIdHash> seen{source};
    for (std::size_t q = 0; q < queue.size(); ++q) {
        // These accessors return owning views by value. Their spans must not
        // outlive the Operation/Value object that owns the backing storage.
        const auto operation = graph.getOperation(queue[q]);
        for (auto id : operation.results()) {
            const auto value = graph.getValue(id);
            for (const auto &use : value.users()) {
                const auto consumer = use.operation;
                if (!seen.insert(consumer).second) continue;
                if (const auto piece = originalPiece(consumer)) pieces.push_back(*piece);
                else queue.push_back(consumer);
            }
        }
    }
    std::sort(pieces.begin(), pieces.end());
    pieces.erase(std::unique(pieces.begin(), pieces.end()), pieces.end());
    return pieces;
}
}
