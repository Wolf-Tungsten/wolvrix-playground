#pragma once
#include "fine_guard_classification.hpp"
#include <climits>

// Six independent static load dimensions. No traces, old labels or timing fit.
inline void writeInitialGraph(const Extractor &extract, const arrival_context::Model &backend,
                              const std::filesystem::path &folder)
{
    using Load = std::array<uint64_t, 6>;
    const auto classes = fine_guard::read(backend, folder);
    std::vector<Load> demandWork(backend.demands.size()), weights(extract.model.atomCount);
    for (const auto &item : backend.items)
    {
        if (!backend.compute.at(item.context)) continue;
        uint64_t mask = 0, unguarded = 0;
        for (const auto rootId : backend.sources.at(item.sources))
        {
            const auto &root = backend.roots.at(rootId);
            auto m = root.mask, u = classes.at(rootId).unguardedClock;
            if (root.kind == 1 && root.owner != arrival_context::noOwner)
            {
                m |= arrival_context::nextHalf(m);
                u |= arrival_context::nextHalf(u);
            }
            mask |= m;
            unguarded |= u;
        }
        auto &work = demandWork.at(item.demand);
        for (unsigned phase = 0; phase < 2; ++phase)
            if (mask & (uint64_t{1} << phase))
                work[phase + ((unguarded & (uint64_t{1} << phase)) ? 0 : 2)] += item.work[0];
        if (mask & arrival_context::unknown) work[4] += item.work[0];
        work[5] += item.work[0];
    }
    for (std::size_t d = 0; d < backend.demands.size(); ++d)
    {
        std::vector<uint32_t> atoms;
        for (const auto piece : backend.demands[d])
        {
            const auto &pins = extract.model.pieces.at(piece).atoms;
            atoms.insert(atoms.end(), pins.begin(), pins.end());
        }
        sortUnique(atoms);
        if (atoms.empty()) continue;
        for (std::size_t axis = 0; axis < 6; ++axis)
        {
            const auto quotient = demandWork[d][axis] / atoms.size();
            const auto remainder = demandWork[d][axis] % atoms.size();
            for (std::size_t i = 0; i < atoms.size(); ++i)
                weights[atoms[(d + i) % atoms.size()]][axis] += quotient + (i < remainder);
        }
    }
    // Piece sharing uses the same closure-aware communication weights as
    // RepCut. Add state-value edges with unit weight, as in the accepted method.
    RepcutAssignmentEvaluator normalized(extract.model);
    std::vector<std::pair<std::vector<uint32_t>, uint32_t>> valueEdges;
    for (const auto &value : normalized.model().values)
    {
        if (value.writerAtom == kRepcutNoAtom) continue;
        auto pins = value.readerAtoms;
        pins.push_back(value.writerAtom);
        sortUnique(pins);
        if (pins.size() > 1) valueEdges.emplace_back(std::move(pins), 1);
    }
    std::size_t edges = valueEdges.size();
    for (const auto &piece : extract.model.pieces) edges += piece.atoms.size() > 1;
    std::ofstream output(folder / "initial.hgr");
    output << edges << ' ' << weights.size() << " 11 6\n";
    const auto emitEdge = [&](const auto &pins, uint32_t weight)
    {
        output << weight;
        for (const auto atom : pins) output << ' ' << atom + 1;
        output << '\n';
    };
    for (std::size_t p = 0; p < extract.model.pieces.size(); ++p)
        if (extract.model.pieces[p].atoms.size() > 1)
            emitEdge(extract.model.pieces[p].atoms, extract.hyperWeights.at(p));
    for (const auto &[pins, weight] : valueEdges) emitEdge(pins, weight);
    for (const auto &load : weights)
    {
        for (std::size_t axis = 0; axis < 6; ++axis)
        {
            if (load[axis] > INT_MAX) throw std::runtime_error("six-axis node weight exceeds solver range");
            output << (axis ? " " : "") << load[axis];
        }
        output << '\n';
    }
    if (!output) throw std::runtime_error("initial graph output failed");
    std::cout << "INITIAL_GRAPH nodes=" << weights.size() << " edges=" << edges << " dimensions=6\n";
}
