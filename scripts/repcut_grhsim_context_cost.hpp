// Experimental GrhSIM construction model. No timings or previous labels.
#pragma once
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace activity_context {
constexpr std::size_t unitCount = 6, scenarioCount = 3, axisCount = unitCount * scenarioCount;
using Units = std::array<uint64_t, unitCount>;
using Cost = std::array<uint64_t, axisCount>;
constexpr uint64_t unknown = uint64_t{1} << 63;
// scalar expressions, helper word iterations, value publication/checks,
// commit predicates/activation, commit scalar primitives, commit word primitives.
struct Item { uint32_t context = 0, demand = 0; uint64_t mask = 0; Units units{}; };
struct Model {
    uint32_t atoms = 0;
    std::vector<bool> compute;
    std::vector<std::vector<uint32_t>> demands; // original piece IDs, never lane IDs
    std::vector<Item> items;
};

inline Cost inScenarios(const Units &units, uint64_t mask) {
    Cost result{};
    for (std::size_t s = 0; s < scenarioCount; ++s)
        if (mask & (s == 2 ? unknown : uint64_t{1} << s))
            for (std::size_t u = 0; u < unitCount; ++u) result[s * unitCount + u] = units[u];
    return result;
}
inline Model read(const char *path) {
    std::ifstream input(path); std::string format;
    Model m; std::size_t contexts = 0, demands = 0, items = 0;
    if (!(input >> format >> m.atoms >> contexts >> demands >> items) || format != "grhsim-context-cost-v1")
        throw std::runtime_error("invalid backend context model header");
    m.compute.resize(contexts); m.demands.resize(demands); m.items.resize(items);
    for (std::size_t c = 0; c < contexts; ++c) { unsigned kind; input >> kind; m.compute[c] = kind; }
    for (auto &d : m.demands) { std::size_t n; input >> n; d.resize(n); for (auto &p : d) input >> p; }
    for (auto &item : m.items) {
        input >> item.context >> item.demand >> item.mask;
        for (auto &v : item.units) input >> v;
        if (item.context >= contexts || item.demand >= demands) throw std::runtime_error("invalid context item");
    }
    if (!input) throw std::runtime_error("truncated backend context model");
    std::string extra; if (input >> extra) throw std::runtime_error("extra context model data");
    return m;
}

// A template context is fragmented by the proposed assignment. Only members
// actually present on that lane contribute to its coactivation envelope.
// Replanning can create different contexts; these are construction predictions,
// not an assertion that final generated helper groups are invariant.
class State {
    const Model &model;
    std::vector<std::vector<uint32_t>> demandItems;
    std::vector<uint64_t> itemLanes;
    struct Fragment { uint64_t mask = 0; Units units{}; };
    std::vector<std::vector<Fragment>> fragments;
public:
    std::vector<Cost> costs;
    State(const Model &m, uint32_t k) : model(m), demandItems(m.demands.size()),
        itemLanes(m.items.size()), fragments(m.compute.size(), std::vector<Fragment>(k)), costs(k) {
        if (!k || k > 64) throw std::runtime_error("invalid context model K");
        for (uint32_t i = 0; i < m.items.size(); ++i) demandItems.at(m.items[i].demand).push_back(i);
    }
    struct Addition {
        uint32_t lane = 0;
        Cost cost{};
        std::vector<uint32_t> items;
        std::map<uint32_t, Fragment> contexts;
    };
    Addition evaluate(uint32_t lane, const std::vector<uint32_t> &demands) const {
        if (lane >= costs.size()) throw std::runtime_error("invalid context destination");
        Addition result; result.lane = lane; result.cost = costs[lane];
        const auto bit = uint64_t{1} << lane;
        for (auto demand : demands) for (auto id : demandItems.at(demand)) {
            if (itemLanes[id] & bit) continue;
            result.items.push_back(id);
        }
        std::sort(result.items.begin(), result.items.end());
        result.items.erase(std::unique(result.items.begin(), result.items.end()), result.items.end());
        for (auto id : result.items) {
            const auto &item = model.items[id];
            if (!model.compute[item.context]) {
                const auto extra = inScenarios(item.units, item.mask);
                for (std::size_t a = 0; a < axisCount; ++a) result.cost[a] += extra[a];
            }
            auto [it, inserted] = result.contexts.try_emplace(item.context);
            if (inserted) it->second = fragments[item.context][lane];
            it->second.mask |= item.mask;
            if (model.compute[item.context])
                for (std::size_t u = 0; u < unitCount; ++u) it->second.units[u] += item.units[u];
        }
        for (const auto &[context, after] : result.contexts) {
            const auto &before = fragments[context][lane];
            auto oldUnits = before.units, newUnits = after.units;
            const auto check = model.compute[context] ? 2u : 3u;
            if (before.mask) ++oldUnits[check];
            if (after.mask) ++newUnits[check];
            const auto oldCost = inScenarios(oldUnits, before.mask), newCost = inScenarios(newUnits, after.mask);
            for (std::size_t a = 0; a < axisCount; ++a) result.cost[a] += newCost[a] - oldCost[a];
        }
        return result;
    }
    void commit(const Addition &addition) {
        for (auto id : addition.items) {
            const auto bit = uint64_t{1} << addition.lane;
            if (itemLanes[id] & bit) throw std::runtime_error("duplicate context item commit");
            itemLanes[id] |= bit;
        }
        for (const auto &[context, fragment] : addition.contexts) fragments[context][addition.lane] = fragment;
        costs[addition.lane] = addition.cost;
    }
};

// Backend vocabulary is matched here; hardware/module/signal names are not.
// Coverage/shape metadata are retained by the extractor separately. These are
// named primitive units, not fitted CPU instructions or nanoseconds.
inline Units project(const std::map<std::string, uint64_t> &features) {
    Units result{};
    for (const auto &[name, n] : features) {
        if (name == "compute.scalar.native_expr" || name == "compute.scalar.byte_bool" ||
            name == "compute.scalar.helper_call_sites" ||
            name == "compute.scalar.expression_ternary_terms" || name == "compute.scalar.concat_reduction" ||
            name == "compute.state_read.scalar_untracked" || name == "compute.state_read.scalar_change_new" ||
            name == "compute.memory_read.scalar" || name == "compute.memory_read.bounds_check" ||
            name == "compute.priority_condition_terms_upper" || name == "compute.priority_bitmap_groups_upper" ||
            name == "compute.priority_bitmap_roots" || name == "compute.priority_branch_roots" ||
            name == "compute.bool_reduce_and_ops" || name == "compute.bool_reduce_scalar_comparisons" ||
            name == "compute.bool_reduce_root_terms" || name == "compute.bool_reduce_or_ops" ||
            name == "compute.wide.demanded_bit" || name == "compute.wide.demanded_bit_slice" ||
            name == "compute.wide.packed_lane_slice" || name == "compute.side_effect.dpic_call" ||
            name == "compute.side_effect.system_task" || name == "compute.side_effect.system_function") result[0] += n;
        else if (name == "compute.wide.helper_word_iterations" || name == "compute.wide.concat_destination_words" ||
                 name == "compute.bool_reduce_iterations" || name == "compute.wide.helper.cross_word_merges" ||
                 name == "compute.wide.helper_cross_word_merges" ||
                 name == "compute.wide.helper.replication_lanes" ||
                 name == "compute.wide.helper.index_normalizations") result[1] += n;
        else if (name == "compute.bool_reduce_unconditional_stores") result[2] += n;
        else if (name.starts_with("compute.") &&
                 (name.ends_with(".result.change_detect") || name.ends_with(".result.untracked_store"))) result[2] += n;
        else if (name == "event.inner_check_sites" || name == "enable.dynamic_predicates" ||
                 name == "changed.reader_activation_calls_upper" || name == "changed.row_selective_activation_calls_upper" ||
                 name == "changed.producer_dirty_bank_or_sites") result[3] += n;
        else if (name == "enabled.scalar_comparisons" || name == "enabled.scalar_next_values" ||
                 name == "enabled.change_or_terms" || name == "changed.scalar_store_slots_upper") result[4] += n;
        else if (name == "enabled.word_comparisons_upper" || name == "enabled.word_next_values" ||
                 name == "enabled.mask_merge_words" || name == "enabled.unconditional_word_stores" ||
                 name == "enabled.fill_row_iterations" || name == "enabled.memory_row_addresses" ||
                 name == "enabled.row_bounds_checks") result[5] += n;
    }
    return result;
}
} // namespace activity_context
