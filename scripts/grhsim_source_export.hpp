#pragma once

// Optional diagnostic output; consumes the exact plan, never changes the graph.
#include "emit/grhsim_activity_model.hpp"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>

namespace grhsim_source_export {
using namespace wolvrix::lib;
using K = grh::OperationKind;

inline std::string csv(std::string_view value) {
    std::string result = "\"";
    for (char c : value) { if (c == '"') result += '"'; result += c; }
    return result + '"';
}

inline bool boundary(K kind) {
    switch (kind) {
    case K::kRegister: case K::kRegisterReadPort: case K::kRegisterWritePort:
    case K::kLatch: case K::kLatchReadPort: case K::kLatchWritePort:
    case K::kMemory: case K::kMemoryReadPort: case K::kMemoryWritePort:
    case K::kMemoryFillPort: case K::kDpicCall: case K::kDpicImport: case K::kSystemTask:
        return true;
    default: return false;
    }
}

inline bool sink(K kind) {
    return kind == K::kRegisterWritePort || kind == K::kLatchWritePort ||
           kind == K::kMemoryWritePort || kind == K::kMemoryFillPort ||
           kind == K::kDpicCall || kind == K::kSystemTask;
}

inline void write(const grh::Graph &graph, const emit::GrhSimExecutionPlan &plan,
                  const emit::GrhSimActivityReport &activity,
                  const std::vector<uint32_t> &weights, const std::string &part,
                  const std::filesystem::path &directory) {
    std::ofstream ops(directory / (part + ".sources.csv"));
    std::ofstream paths(directory / (part + ".paths.csv"));
    std::ofstream batches(directory / (part + ".batches.csv"));
    std::ofstream ports(directory / (part + ".ports.csv"));
    if (!ops || !paths || !batches || !ports) throw std::runtime_error("cannot open source mapping outputs");
    ops << "part,batch,phase,group,active_id,op_index,op_symbol,op_kind,work,activity_mask,group_mask,value_ids,value_symbols,file,line,column,end_line,end_column,origin,pass,note,location_kind,fanout,boundary,storage\n";
    batches << "part,batch,phase,estimated_lines,groups,active_words\n";
    ports << "part,direction,name,value,symbol,width\n";
    const auto portRow = [&](const auto &port, const char *direction) {
        ports << csv(part) << ',' << direction << ',' << csv(port.name) << ',' << port.value.index
              << ',' << csv(graph.getValue(port.value).symbolText()) << ',' << graph.valueWidth(port.value) << '\n';
    };
    for (const auto &p : graph.inputPorts()) portRow(p, "input");
    for (const auto &p : graph.outputPorts()) portRow(p, "output");
    std::map<uint32_t, std::size_t> groupBatch;
    for (const auto &batch : plan.batches) {
        std::string groups, words;
        for (const auto &word : batch.words) {
            if (!words.empty()) words += ';'; words += std::to_string(word.activeWord);
            for (auto group : word.groups) {
                if (!groupBatch.emplace(group, batch.index).second)
                    throw std::runtime_error("group appears in multiple batches");
                if (!groups.empty()) groups += ';'; groups += std::to_string(group);
            }
        }
        batches << csv(part) << ',' << batch.index << ','
                << (batch.phase == emit::GrhSimExecutionPlan::Phase::Compute ? "compute" : "commit")
                << ',' << batch.estimatedLines << ',' << csv(groups) << ',' << csv(words) << '\n';
    }
    for (const auto &group : plan.groups) {
        for (auto id : group.operations) {
            const auto op = graph.getOperation(id);
            auto loc = op.srcLoc();
            std::string locationKind = loc && !loc->file.empty() && loc->line ? "operation" : "unknown";
            std::string valueIds, symbols;
            uint64_t fanout = 0;
            for (auto valueId : op.results()) {
                const auto value = graph.getValue(valueId);
                if (!valueIds.empty()) { valueIds += ';'; symbols += ';'; }
                valueIds += std::to_string(valueId.index); symbols += value.symbolText();
                fanout += value.users().size();
                if (locationKind == "unknown" && value.srcLoc() && !value.srcLoc()->file.empty() && value.srcLoc()->line) {
                    loc = value.srcLoc(); locationKind = "result";
                }
            }
            std::string storage;
            for (const auto key : {"regSymbol", "memSymbol", "latchSymbol"}) {
                auto attr = op.attr(key);
                if (attr) if (const auto *name = std::get_if<std::string>(&*attr)) storage = *name;
            }
            const auto source = loc.value_or(grh::SrcLoc{});
            ops << csv(part) << ',';
            if (groupBatch.contains(group.supernode)) ops << groupBatch.at(group.supernode);
            ops << ',' << (group.phase == emit::GrhSimExecutionPlan::Phase::Compute ? "compute" : "commit")
                << ',' << group.supernode << ',' << group.activeId << ',' << id.index << ',' << csv(op.symbolText())
                << ',' << grh::toString(op.kind()) << ',' << weights.at(id.index) << ',' << activity.operationMasks.at(id.index)
                << ',' << activity.computeGroupMasks.at(group.activeId) << ',' << csv(valueIds) << ',' << csv(symbols)
                << ',' << csv(source.file) << ',' << source.line << ',' << source.column << ',' << source.endLine
                << ',' << source.endColumn << ',' << csv(source.origin) << ',' << csv(source.pass) << ',' << csv(source.note)
                << ',' << locationKind << ',' << fanout << ',' << boundary(op.kind()) << ',' << csv(storage) << '\n';
        }
    }

    // Structural weighted paths. A state/effect read begins a new path and a
    // state/effect write ends one. No cross-cycle or implicit memory edge.
    const auto ids = graph.operations();
    std::vector<std::vector<uint32_t>> next(weights.size());
    std::vector<uint32_t> degree(weights.size()), order;
    std::vector<std::array<uint64_t, 2>> length(weights.size());
    std::vector<std::array<uint32_t, 2>> pred(weights.size(), {UINT32_MAX, UINT32_MAX});
    std::vector<std::array<uint32_t, 2>> unknown(weights.size());
    for (auto id : ids) {
        const auto op = graph.getOperation(id);
        if (boundary(op.kind()) && !sink(op.kind())) continue;
        std::set<uint32_t> deps;
        for (auto value : op.operands()) {
            const auto definition = graph.valueDef(value);
            if (!definition.valid() || sink(graph.getOperation(definition).kind())) continue;
            deps.insert(definition.index);
        }
        degree[id.index] = deps.size();
        for (auto dep : deps) next[dep].push_back(id.index);
    }
    std::queue<uint32_t> ready;
    for (auto id : ids) if (!degree[id.index]) ready.push(id.index);
    while (!ready.empty()) {
        const auto id = ready.front(); ready.pop(); order.push_back(id);
        const auto mask = activity.operationMasks.at(id);
        for (unsigned clock = 0; clock < 2; ++clock) {
            const bool may = (mask & (clock ? 1 : 2)) || (mask & emit::kGrhSimUnknownActivity);
            length[id][clock] += may ? weights[id] : 0;
            unknown[id][clock] += bool(mask & emit::kGrhSimUnknownActivity);
        }
        for (auto target : next[id]) {
            for (unsigned clock = 0; clock < 2; ++clock)
                if (length[id][clock] > length[target][clock]) {
                    length[target][clock] = length[id][clock];
                    pred[target][clock] = id; unknown[target][clock] = unknown[id][clock];
                }
            if (--degree[target] == 0) ready.push(target);
        }
    }
    if (order.size() != ids.size()) throw std::runtime_error("combinational dependency cycle in source-path view");
    paths << "part,clock,rank,work,unknown_operations,position,op_index\n";
    for (unsigned clock = 0; clock < 2; ++clock) {
        auto endpoints = order;
        std::sort(endpoints.begin(), endpoints.end(), [&](auto a, auto b) {
            return length[a][clock] != length[b][clock] ? length[a][clock] > length[b][clock] : a < b;
        });
        std::set<uint32_t> covered;
        unsigned rank = 0;
        for (auto endpoint : endpoints) {
            if (!length[endpoint][clock] || covered.contains(endpoint)) continue;
            if (++rank > 10) break;
            std::vector<uint32_t> path;
            for (auto id = endpoint; id != UINT32_MAX; id = pred[id][clock]) { path.push_back(id); covered.insert(id); }
            std::reverse(path.begin(), path.end());
            for (std::size_t i = 0; i < path.size(); ++i)
                paths << csv(part) << ',' << clock << ',' << rank << ',' << length[endpoint][clock] << ','
                      << unknown[endpoint][clock] << ',' << i << ',' << path[i] << '\n';
        }
    }
    if (!ops || !paths || !batches || !ports) throw std::runtime_error("source mapping write failed");
}
} // namespace grhsim_source_export
