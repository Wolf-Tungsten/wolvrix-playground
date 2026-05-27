#include "tgp/oracle.hpp"

#include "tgp/graph_io.hpp"
#include "tgp/json.hpp"
#include "tgp/validator.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <deque>
#include <limits>
#include <mutex>
#include <sstream>
#include <thread>
#include <unordered_map>

namespace tgp
{
    namespace
    {
        struct PrefixTask
        {
            std::vector<PartId> assignment;
            std::vector<uint32_t> partSizes;
            uint32_t partCount = 0;
            uint32_t depth = 0;
            uint64_t prefixCut = 0;
            uint64_t quotientEdgeCount = 0;
            std::vector<uint32_t> quotientOutDegree;
            std::vector<std::vector<uint32_t>> quotientEdgeCounts;
            uint64_t ordinal = 0;
        };

        constexpr const char *kTaskOrder = "prefix_cut_desc_v1";

        struct AssignDelta
        {
            uint64_t cutDelta = 0;
            std::vector<std::pair<PartId, PartId>> quotientEdges;
        };

        struct SearchGraph
        {
            const ComputeDag &graph;
            std::vector<std::vector<uint32_t>> incidentEdges;
            std::vector<uint32_t> topoOrder;

            explicit SearchGraph(const ComputeDag &input) : graph(input)
            {
                incidentEdges.assign(graph.nodes.size(), {});
                for (uint32_t edgeIndex = 0; edgeIndex < graph.edges.size(); ++edgeIndex)
                {
                    const Edge &edge = graph.edges[edgeIndex];
                    incidentEdges[edge.src].push_back(edgeIndex);
                    incidentEdges[edge.dst].push_back(edgeIndex);
                }
                topoOrder.resize(graph.nodes.size());
                for (uint32_t i = 0; i < topoOrder.size(); ++i)
                {
                    topoOrder[i] = i;
                }
                std::sort(topoOrder.begin(), topoOrder.end(), [&](uint32_t a, uint32_t b) {
                    if (graph.nodes[a].topoPos != graph.nodes[b].topoPos)
                    {
                        return graph.nodes[a].topoPos < graph.nodes[b].topoPos;
                    }
                    return a < b;
                });
            }
        };

        uint64_t pairKey(PartId src, PartId dst)
        {
            return (static_cast<uint64_t>(src) << 32) | static_cast<uint64_t>(dst);
        }

        bool pathExists(const std::vector<std::vector<uint32_t>> &edgeCounts, PartId src, PartId dst)
        {
            if (src == dst)
            {
                return true;
            }
            if (src >= edgeCounts.size() || dst >= edgeCounts.size())
            {
                return false;
            }
            std::vector<uint8_t> seen(edgeCounts.size(), 0);
            std::deque<PartId> queue;
            seen[src] = 1;
            queue.push_back(src);
            while (!queue.empty())
            {
                const PartId part = queue.front();
                queue.pop_front();
                for (PartId next = 0; next < edgeCounts[part].size(); ++next)
                {
                    if (edgeCounts[part][next] == 0 || seen[next])
                    {
                        continue;
                    }
                    if (next == dst)
                    {
                        return true;
                    }
                    seen[next] = 1;
                    queue.push_back(next);
                }
            }
            return false;
        }

        bool ensurePartCount(std::vector<std::vector<uint32_t>> &edgeCounts,
                             std::vector<uint32_t> &outDegree,
                             uint32_t partCount)
        {
            if (partCount <= edgeCounts.size())
            {
                return false;
            }
            for (auto &row : edgeCounts)
            {
                row.resize(partCount, 0);
            }
            edgeCounts.resize(partCount);
            for (auto &row : edgeCounts)
            {
                row.resize(partCount, 0);
            }
            outDegree.resize(partCount, 0);
            return true;
        }

        std::vector<std::pair<uint64_t, uint64_t>> makeCompletedRanges(const std::vector<uint8_t> &completed)
        {
            std::vector<std::pair<uint64_t, uint64_t>> ranges;
            uint64_t index = 0;
            while (index < completed.size())
            {
                while (index < completed.size() && !completed[index])
                {
                    ++index;
                }
                const uint64_t begin = index;
                while (index < completed.size() && completed[index])
                {
                    ++index;
                }
                if (begin != index)
                {
                    ranges.emplace_back(begin, index);
                }
            }
            return ranges;
        }

        uint64_t countCompletedTasks(const std::vector<uint8_t> &completed)
        {
            uint64_t count = 0;
            for (const uint8_t value : completed)
            {
                count += value ? 1 : 0;
            }
            return count;
        }

        uint64_t firstIncompleteTask(const std::vector<uint8_t> &completed)
        {
            for (uint64_t index = 0; index < completed.size(); ++index)
            {
                if (!completed[index])
                {
                    return index;
                }
            }
            return completed.size();
        }

        uint32_t asCheckpointU32(const json::Value &value)
        {
            if (!value.isInt() || value.integer() < 0 || value.integer() > UINT32_MAX)
            {
                throw std::runtime_error("checkpoint value is not a u32");
            }
            return static_cast<uint32_t>(value.integer());
        }

        uint64_t asCheckpointU64(const json::Value &value)
        {
            if (!value.isInt() || value.integer() < 0)
            {
                throw std::runtime_error("checkpoint value is not a u64");
            }
            return static_cast<uint64_t>(value.integer());
        }

        double asCheckpointDouble(const json::Value &value)
        {
            if (value.isInt())
            {
                return static_cast<double>(value.integer());
            }
            if (std::holds_alternative<double>(value.storage))
            {
                return std::get<double>(value.storage);
            }
            throw std::runtime_error("checkpoint value is not numeric");
        }

        std::string asCheckpointString(const json::Value &value)
        {
            if (!value.isString())
            {
                throw std::runtime_error("checkpoint value is not a string");
            }
            return value.string();
        }

        PartitionScore parseCheckpointScore(const json::Value &value)
        {
            if (!value.isObject())
            {
                throw std::runtime_error("checkpoint score must be object");
            }
            const auto &object = value.object();
            PartitionScore score;
            score.cutWeight = asCheckpointU64(json::require(object, "cut_weight"));
            score.cutEdges = asCheckpointU64(json::require(object, "cut_edges"));
            score.parts = asCheckpointU32(json::require(object, "parts"));
            score.maxPartSize = asCheckpointU64(json::require(object, "max_part_size"));
            score.meanPartSize = asCheckpointDouble(json::require(object, "mean_part_size"));
            score.p90PartSize = asCheckpointU64(json::require(object, "p90_part_size"));
            score.quotientEdges = asCheckpointU64(json::require(object, "quotient_edges"));
            score.quotientAvgOutDegree = asCheckpointDouble(json::require(object, "quotient_avg_out_degree"));
            score.quotientP99OutDegree = asCheckpointU64(json::require(object, "quotient_p99_out_degree"));
            score.runtimeMs = asCheckpointDouble(json::require(object, "runtime_ms"));
            return score;
        }

        PartitionResult parseCheckpointPartition(const json::Value &value)
        {
            if (!value.isObject())
            {
                throw std::runtime_error("checkpoint partition must be object");
            }
            const auto &object = value.object();
            PartitionResult partition;
            partition.graphId = asCheckpointString(json::require(object, "graph_id"));
            if (const auto *algorithm = json::find(object, "algorithm"); algorithm && algorithm->isObject())
            {
                const auto &algorithmObject = algorithm->object();
                if (const auto *name = json::find(algorithmObject, "name"))
                {
                    partition.algorithmName = asCheckpointString(*name);
                }
                if (const auto *version = json::find(algorithmObject, "version"))
                {
                    partition.algorithmVersion = asCheckpointString(*version);
                }
            }
            if (const auto *constraints = json::find(object, "constraints"); constraints && constraints->isObject())
            {
                const auto &constraintsObject = constraints->object();
                partition.maxNodesPerPart = asCheckpointU32(json::require(constraintsObject, "max_nodes_per_part"));
            }

            const auto &assignment = json::require(object, "assignment").array();
            uint32_t maxNode = 0;
            std::vector<std::pair<uint32_t, PartId>> pairs;
            pairs.reserve(assignment.size());
            for (const json::Value &entryValue : assignment)
            {
                const auto &entry = entryValue.object();
                const uint32_t node = asCheckpointU32(json::require(entry, "node"));
                const PartId part = asCheckpointU32(json::require(entry, "part"));
                maxNode = std::max(maxNode, node);
                pairs.emplace_back(node, part);
            }
            partition.partByNode.assign(static_cast<std::size_t>(maxNode) + 1, kInvalidPartId);
            for (const auto &[node, part] : pairs)
            {
                partition.partByNode[node] = part;
            }
            if (const auto *hint = json::find(object, "part_order_hint"); hint && hint->isArray())
            {
                for (const json::Value &part : hint->array())
                {
                    partition.partOrderHint.push_back(asCheckpointU32(part));
                }
            }
            if (const auto *stats = json::find(object, "stats_hint"); stats && stats->isObject())
            {
                if (const auto *runtime = json::find(stats->object(), "runtime_ms"))
                {
                    partition.runtimeMs = asCheckpointDouble(*runtime);
                }
            }
            return partition;
        }

        struct ResumeState
        {
            uint64_t searchedStates = 0;
            uint64_t prunedBySize = 0;
            uint64_t prunedByBound = 0;
            uint64_t prunedByCycle = 0;
            std::vector<std::pair<uint64_t, uint64_t>> completedTaskRanges;
            PartitionResult incumbent;
            PartitionScore score;
            bool hasIncumbent = false;
        };

        uint32_t choosePrefixDepth(const ComputeDag &graph, uint32_t threads)
        {
            if (graph.nodes.empty())
            {
                return 0;
            }
            uint32_t depth = std::min<uint32_t>(static_cast<uint32_t>(graph.nodes.size()), 8);
            while (depth < graph.nodes.size() && depth < 12)
            {
                uint64_t approx = 1;
                for (uint32_t i = 0; i < depth; ++i)
                {
                    approx *= static_cast<uint64_t>(i + 1);
                    if (approx >= static_cast<uint64_t>(std::max<uint32_t>(threads, 1)) * 512)
                    {
                        return depth;
                    }
                }
                ++depth;
            }
            return depth;
        }

        void enumeratePrefixTasks(const SearchGraph &searchGraph,
                                  const OracleOptions &options,
                                  uint32_t prefixDepth,
                                  std::vector<PrefixTask> &tasks,
                                  std::atomic_bool &timeExpired,
                                  const std::chrono::steady_clock::time_point &start)
        {
            const ComputeDag &graph = searchGraph.graph;
            std::vector<PartId> current(graph.nodes.size(), kInvalidPartId);
            std::vector<uint32_t> partSizes;
            std::vector<std::vector<uint32_t>> quotientEdgeCounts;
            std::vector<uint32_t> quotientOutDegree;
            uint64_t prefixCut = 0;
            uint64_t quotientEdgeCount = 0;
            uint64_t ordinal = 0;
            const auto timedOut = [&]() {
                if (options.timeLimitSec == 0)
                {
                    return false;
                }
                const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                    std::chrono::steady_clock::now() - start).count();
                return static_cast<uint64_t>(elapsed) >= options.timeLimitSec;
            };

            const auto computeDelta = [&](uint32_t node, PartId part) {
                AssignDelta delta;
                std::unordered_map<uint64_t, std::pair<PartId, PartId>> uniquePairs;
                for (const uint32_t edgeIndex : searchGraph.incidentEdges[node])
                {
                    const Edge &edge = graph.edges[edgeIndex];
                    const bool nodeIsSrc = edge.src == node;
                    const uint32_t otherNode = nodeIsSrc ? edge.dst : edge.src;
                    const PartId otherPart = current[otherNode];
                    if (otherPart == kInvalidPartId || otherPart == part)
                    {
                        continue;
                    }
                    delta.cutDelta += edge.weight;
                    const PartId srcPart = nodeIsSrc ? part : otherPart;
                    const PartId dstPart = nodeIsSrc ? otherPart : part;
                    uniquePairs.emplace(pairKey(srcPart, dstPart), std::make_pair(srcPart, dstPart));
                }
                delta.quotientEdges.reserve(uniquePairs.size());
                for (const auto &[key, value] : uniquePairs)
                {
                    (void)key;
                    delta.quotientEdges.push_back(value);
                }
                return delta;
            };

            const auto applyDelta = [&](const AssignDelta &delta) {
                uint64_t addedQuotientEdges = 0;
                for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                {
                    uint32_t &count = quotientEdgeCounts[srcPart][dstPart];
                    if (count == 0)
                    {
                        ++quotientOutDegree[srcPart];
                        ++addedQuotientEdges;
                    }
                    ++count;
                }
                prefixCut += delta.cutDelta;
                quotientEdgeCount += addedQuotientEdges;
                return addedQuotientEdges;
            };

            const auto undoDelta = [&](const AssignDelta &delta, uint64_t addedQuotientEdges) {
                for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                {
                    uint32_t &count = quotientEdgeCounts[srcPart][dstPart];
                    --count;
                    if (count == 0)
                    {
                        --quotientOutDegree[srcPart];
                    }
                }
                prefixCut -= delta.cutDelta;
                quotientEdgeCount -= addedQuotientEdges;
            };

            const auto dfs = [&](const auto &self, uint32_t node, uint32_t partCount) -> void {
                if (timeExpired.load(std::memory_order_relaxed) || timedOut())
                {
                    timeExpired.store(true, std::memory_order_relaxed);
                    return;
                }
                if (node == prefixDepth)
                {
                    PrefixTask task;
                    task.assignment.reserve(prefixDepth);
                    for (uint32_t i = 0; i < prefixDepth; ++i)
                    {
                        task.assignment.push_back(current[searchGraph.topoOrder[i]]);
                    }
                    task.partSizes = partSizes;
                    task.partCount = partCount;
                    task.depth = prefixDepth;
                    task.prefixCut = prefixCut;
                    task.quotientEdgeCount = quotientEdgeCount;
                    task.quotientOutDegree = quotientOutDegree;
                    task.quotientEdgeCounts = quotientEdgeCounts;
                    task.ordinal = ordinal++;
                    tasks.push_back(std::move(task));
                    return;
                }
                const uint32_t actualNode = searchGraph.topoOrder[node];
                for (PartId part = 0; part <= partCount; ++part)
                {
                    const bool newPart = part == partCount;
                    if (newPart)
                    {
                        partSizes.push_back(0);
                    }
                    const uint32_t nextPartCount = newPart ? partCount + 1 : partCount;
                    const bool resized = ensurePartCount(quotientEdgeCounts, quotientOutDegree, nextPartCount);
                    const uint32_t nextSize = partSizes[part] + 1;
                    const bool allowed = options.maxNodesPerPart == 0 || nextSize <= options.maxNodesPerPart;
                    if (allowed)
                    {
                        const AssignDelta delta = computeDelta(actualNode, part);
                        bool cyclic = false;
                        for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                        {
                            if (quotientEdgeCounts[srcPart][dstPart] == 0 &&
                                pathExists(quotientEdgeCounts, dstPart, srcPart))
                            {
                                cyclic = true;
                                break;
                            }
                        }
                        if (cyclic)
                        {
                            if (resized)
                            {
                                quotientEdgeCounts.pop_back();
                                for (auto &row : quotientEdgeCounts)
                                {
                                    row.pop_back();
                                }
                                quotientOutDegree.pop_back();
                            }
                            if (newPart)
                            {
                                partSizes.pop_back();
                            }
                            continue;
                        }
                        const uint64_t addedQuotientEdges = applyDelta(delta);
                        partSizes[part] = nextSize;
                        current[actualNode] = part;
                        self(self, node + 1, nextPartCount);
                        current[actualNode] = kInvalidPartId;
                        --partSizes[part];
                        undoDelta(delta, addedQuotientEdges);
                    }
                    if (newPart)
                    {
                        partSizes.pop_back();
                    }
                    if (resized)
                    {
                        quotientEdgeCounts.pop_back();
                        for (auto &row : quotientEdgeCounts)
                        {
                            row.pop_back();
                        }
                        quotientOutDegree.pop_back();
                    }
                    if (timeExpired.load(std::memory_order_relaxed))
                    {
                        return;
                    }
                }
            };
            dfs(dfs, 0, 0);
        }

        ResumeState readResumeState(const std::string &path,
                                    const ComputeDag &graph,
                                    const OracleOptions &options,
                                    uint32_t prefixDepth,
                                    uint64_t totalTasks,
                                    std::string_view taskOrder)
        {
            ResumeState state;
            if (path.empty())
            {
                return state;
            }
            try
            {
                json::Value root = json::parse(readTextFile(path));
                if (!root.isObject())
                {
                    return state;
                }
                const auto &object = root.object();
                if (const auto *format = json::find(object, "format");
                    !format || !format->isString() || format->string() != "wolvrix.tgp-oracle-checkpoint.v1")
                {
                    return state;
                }
                const auto *graphId = json::find(object, "graph_id");
                if (!graphId || !graphId->isString() || graphId->string() != graph.graphId)
                {
                    return state;
                }
                const auto *checkpointTaskOrder = json::find(object, "task_order");
                if (!checkpointTaskOrder || !checkpointTaskOrder->isString() ||
                    checkpointTaskOrder->string() != taskOrder)
                {
                    return state;
                }
                const auto *maxNodesPerPart = json::find(object, "max_nodes_per_part");
                if (!maxNodesPerPart || !maxNodesPerPart->isInt() ||
                    maxNodesPerPart->integer() < 0 ||
                    static_cast<uint32_t>(maxNodesPerPart->integer()) != options.maxNodesPerPart)
                {
                    return state;
                }
                const auto *checkpointPrefixDepth = json::find(object, "prefix_depth");
                if (!checkpointPrefixDepth || !checkpointPrefixDepth->isInt() ||
                    checkpointPrefixDepth->integer() < 0 ||
                    static_cast<uint32_t>(checkpointPrefixDepth->integer()) != prefixDepth)
                {
                    return state;
                }
                const auto *checkpointTotalTasks = json::find(object, "total_tasks");
                if (!checkpointTotalTasks || !checkpointTotalTasks->isInt() ||
                    checkpointTotalTasks->integer() < 0 ||
                    static_cast<uint64_t>(checkpointTotalTasks->integer()) != totalTasks)
                {
                    return state;
                }
                if (const auto *ranges = json::find(object, "completed_task_ranges");
                    ranges && ranges->isArray())
                {
                    for (const json::Value &rangeValue : ranges->array())
                    {
                        if (!rangeValue.isArray() || rangeValue.array().size() != 2)
                        {
                            continue;
                        }
                        const uint64_t begin = asCheckpointU64(rangeValue.array()[0]);
                        const uint64_t end = asCheckpointU64(rangeValue.array()[1]);
                        if (begin < end && end <= totalTasks)
                        {
                            state.completedTaskRanges.emplace_back(begin, end);
                        }
                    }
                }
                else if (const auto *completed = json::find(object, "completed_tasks");
                         completed && completed->isInt() && completed->integer() > 0)
                {
                    const uint64_t end = std::min<uint64_t>(static_cast<uint64_t>(completed->integer()), totalTasks);
                    state.completedTaskRanges.emplace_back(0, end);
                }
                if (const auto *searchedStates = json::find(object, "searched_states");
                    searchedStates && searchedStates->isInt() && searchedStates->integer() > 0)
                {
                    state.searchedStates = static_cast<uint64_t>(searchedStates->integer());
                }
                if (const auto *pruned = json::find(object, "pruned_by_size");
                    pruned && pruned->isInt() && pruned->integer() > 0)
                {
                    state.prunedBySize = static_cast<uint64_t>(pruned->integer());
                }
                if (const auto *pruned = json::find(object, "pruned_by_bound");
                    pruned && pruned->isInt() && pruned->integer() > 0)
                {
                    state.prunedByBound = static_cast<uint64_t>(pruned->integer());
                }
                if (const auto *pruned = json::find(object, "pruned_by_cycle");
                    pruned && pruned->isInt() && pruned->integer() > 0)
                {
                    state.prunedByCycle = static_cast<uint64_t>(pruned->integer());
                }
                if (const auto *incumbent = json::find(object, "incumbent"); incumbent && incumbent->isObject())
                {
                    state.incumbent = parseCheckpointPartition(*incumbent);
                    state.hasIncumbent = !state.incumbent.partByNode.empty();
                }
                if (const auto *score = json::find(object, "incumbent_score"); score && score->isObject())
                {
                    state.score = parseCheckpointScore(*score);
                }
            }
            catch (const std::exception &)
            {
                return ResumeState{};
            }
            return state;
        }

        std::string checkpointToJson(const OracleResult &result)
        {
            std::ostringstream out;
            out << "{\n";
            out << "  \"format\":\"wolvrix.tgp-oracle-checkpoint.v1\",\n";
            out << "  \"graph_id\":\"" << json::escape(result.graphId) << "\",\n";
            out << "  \"task_order\":\"" << json::escape(result.taskOrder) << "\",\n";
            out << "  \"max_nodes_per_part\":" << result.maxNodesPerPart << ",\n";
            out << "  \"threads\":" << result.threads << ",\n";
            out << "  \"checkpoint_interval_sec\":" << result.checkpointIntervalSec << ",\n";
            out << "  \"elapsed_ms\":" << result.elapsedMs << ",\n";
            out << "  \"status\":\"" << json::escape(result.status) << "\",\n";
            out << "  \"optimal\":" << (result.optimal ? "true" : "false") << ",\n";
            out << "  \"bounded\":" << (result.bounded ? "true" : "false") << ",\n";
            out << "  \"prefix_depth\":" << result.prefixDepth << ",\n";
            out << "  \"total_tasks\":" << result.totalTasks << ",\n";
            out << "  \"completed_tasks\":" << result.completedTasks << ",\n";
            out << "  \"next_task\":" << result.nextTask << ",\n";
            out << "  \"completed_task_ranges\":[";
            for (std::size_t i = 0; i < result.completedTaskRanges.size(); ++i)
            {
                if (i != 0)
                {
                    out << ",";
                }
                out << "[" << result.completedTaskRanges[i].first << ","
                    << result.completedTaskRanges[i].second << "]";
            }
            out << "],\n";
            out << "  \"searched_states\":" << result.searchedStates << ",\n";
            out << "  \"pruned_by_size\":" << result.prunedBySize << ",\n";
            out << "  \"pruned_by_cycle\":" << result.prunedByCycle << ",\n";
            out << "  \"pruned_by_bound\":" << result.prunedByBound << ",\n";
            out << "  \"lower_bound_cut_weight\":" << result.lowerBoundCutWeight << ",\n";
            if (result.incumbent.partByNode.empty())
            {
                out << "  \"gap_cut_weight\":null,\n";
            }
            else
            {
                out << "  \"gap_cut_weight\":" << (result.score.cutWeight - result.lowerBoundCutWeight) << ",\n";
            }
            out << "  \"incumbent_score\":" << scoreToJson(result.score) << ",\n";
            out << "  \"incumbent\":" << partitionToJson(result.incumbent);
            out << "}\n";
            return out.str();
        }

        void writeCheckpointIfRequested(const OracleOptions &options, const OracleResult &result)
        {
            if (options.checkpointPath.empty())
            {
                return;
            }
            writeTextFile(options.checkpointPath, checkpointToJson(result));
        }

        void updateElapsed(OracleResult &result, const std::chrono::steady_clock::time_point &start)
        {
            const auto elapsed = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - start);
            result.elapsedMs = elapsed.count();
        }

        PartitionResult makeTopoWindowIncumbent(const ComputeDag &graph, uint32_t maxNodesPerPart)
        {
            AlgorithmConfig config;
            config.maxNodesPerPart = maxNodesPerPart;
            auto algorithm = createAlgorithm("topo-window");
            PartitionResult incumbent = algorithm->run(graph, config);
            incumbent.algorithmName = "brute_force_oracle.initial_topo_window";
            return incumbent;
        }

        struct Search
        {
            const SearchGraph &searchGraph;
            const ComputeDag &graph;
            const OracleOptions &options;
            OracleResult result;
            std::vector<PartId> current;
            std::vector<uint32_t> partSizes;
            std::vector<std::vector<uint32_t>> quotientEdgeCounts;
            std::vector<uint32_t> quotientOutDegree;
            uint64_t bestCut = std::numeric_limits<uint64_t>::max();
            uint64_t currentCut = 0;
            uint64_t quotientEdgeCount = 0;
            std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();

            Search(const SearchGraph &input, const OracleOptions &inputOptions)
                : searchGraph(input), graph(input.graph), options(inputOptions)
            {
            }

            bool timedOut() const
            {
                if (options.timeLimitSec == 0)
                {
                    return false;
                }
                const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                    std::chrono::steady_clock::now() - start).count();
                return static_cast<uint64_t>(elapsed) >= options.timeLimitSec;
            }

            void run()
            {
                current.assign(graph.nodes.size(), kInvalidPartId);
                dfs(0, 0);
            }

            void runTask(const PrefixTask &task, uint64_t globalBest)
            {
                current.assign(graph.nodes.size(), kInvalidPartId);
                for (uint32_t i = 0; i < task.assignment.size(); ++i)
                {
                    current[searchGraph.topoOrder[i]] = task.assignment[i];
                }
                partSizes = task.partSizes;
                quotientEdgeCounts = task.quotientEdgeCounts;
                quotientOutDegree = task.quotientOutDegree;
                currentCut = task.prefixCut;
                quotientEdgeCount = task.quotientEdgeCount;
                bestCut = globalBest;
                dfs(task.depth, task.partCount);
            }

            AssignDelta computeDelta(uint32_t node, PartId part) const
            {
                AssignDelta delta;
                std::unordered_map<uint64_t, std::pair<PartId, PartId>> uniquePairs;
                for (const uint32_t edgeIndex : searchGraph.incidentEdges[node])
                {
                    const Edge &edge = graph.edges[edgeIndex];
                    const bool nodeIsSrc = edge.src == node;
                    const uint32_t otherNode = nodeIsSrc ? edge.dst : edge.src;
                    const PartId otherPart = current[otherNode];
                    if (otherPart == kInvalidPartId || otherPart == part)
                    {
                        continue;
                    }
                    delta.cutDelta += edge.weight;
                    const PartId srcPart = nodeIsSrc ? part : otherPart;
                    const PartId dstPart = nodeIsSrc ? otherPart : part;
                    uniquePairs.emplace(pairKey(srcPart, dstPart), std::make_pair(srcPart, dstPart));
                }
                delta.quotientEdges.reserve(uniquePairs.size());
                for (const auto &[key, value] : uniquePairs)
                {
                    (void)key;
                    delta.quotientEdges.push_back(value);
                }
                return delta;
            }

            bool wouldCreateCycle(const AssignDelta &delta) const
            {
                for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                {
                    if (quotientEdgeCounts[srcPart][dstPart] == 0 &&
                        pathExists(quotientEdgeCounts, dstPart, srcPart))
                    {
                        return true;
                    }
                }
                return false;
            }

            uint64_t applyDelta(const AssignDelta &delta)
            {
                uint64_t addedQuotientEdges = 0;
                for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                {
                    uint32_t &count = quotientEdgeCounts[srcPart][dstPart];
                    if (count == 0)
                    {
                        ++quotientOutDegree[srcPart];
                        ++addedQuotientEdges;
                    }
                    ++count;
                }
                currentCut += delta.cutDelta;
                quotientEdgeCount += addedQuotientEdges;
                return addedQuotientEdges;
            }

            void undoDelta(const AssignDelta &delta, uint64_t addedQuotientEdges)
            {
                for (const auto &[srcPart, dstPart] : delta.quotientEdges)
                {
                    uint32_t &count = quotientEdgeCounts[srcPart][dstPart];
                    --count;
                    if (count == 0)
                    {
                        --quotientOutDegree[srcPart];
                    }
                }
                currentCut -= delta.cutDelta;
                quotientEdgeCount -= addedQuotientEdges;
            }

            void dfs(uint32_t node, uint32_t partCount)
            {
                if (!result.status.empty())
                {
                    return;
                }
                if (timedOut())
                {
                    result.status = "timeout without bound";
                    return;
                }
                ++result.searchedStates;
                if (currentCut >= bestCut)
                {
                    ++result.prunedByBound;
                    return;
                }
                if (node == graph.nodes.size())
                {
                    PartitionResult candidate;
                    candidate.graphId = graph.graphId;
                    candidate.algorithmName = "brute_force_oracle";
                    candidate.algorithmVersion = "0.1";
                    candidate.partByNode = current;
                    candidate.maxNodesPerPart = options.maxNodesPerPart;
                    const ValidationResult validation = validatePartition(graph, candidate);
                    if (!validation.ok)
                    {
                        ++result.prunedByCycle;
                        return;
                    }
                    const PartitionScore score = scorePartition(graph, candidate);
                    if (score.cutWeight < bestCut)
                    {
                        bestCut = score.cutWeight;
                        result.incumbent = candidate;
                        result.score = score;
                    }
                    return;
                }

                const uint32_t actualNode = searchGraph.topoOrder[node];
                for (PartId part = 0; part <= partCount; ++part)
                {
                    const bool newPart = part == partCount;
                    if (newPart)
                    {
                        partSizes.push_back(0);
                    }
                    const uint32_t nextPartCount = newPart ? partCount + 1 : partCount;
                    const bool resized = ensurePartCount(quotientEdgeCounts, quotientOutDegree, nextPartCount);
                    const uint32_t nextSize = partSizes[part] + 1;
                    const bool allowed = options.maxNodesPerPart == 0 || nextSize <= options.maxNodesPerPart;
                    if (allowed)
                    {
                        const AssignDelta delta = computeDelta(actualNode, part);
                        if (wouldCreateCycle(delta))
                        {
                            ++result.prunedByCycle;
                            if (resized)
                            {
                                quotientEdgeCounts.pop_back();
                                for (auto &row : quotientEdgeCounts)
                                {
                                    row.pop_back();
                                }
                                quotientOutDegree.pop_back();
                            }
                            if (newPart)
                            {
                                partSizes.pop_back();
                            }
                            continue;
                        }
                        const uint64_t addedQuotientEdges = applyDelta(delta);
                        partSizes[part] = nextSize;
                        current[actualNode] = part;
                        dfs(node + 1, nextPartCount);
                        current[actualNode] = kInvalidPartId;
                        --partSizes[part];
                        undoDelta(delta, addedQuotientEdges);
                        if (!result.status.empty())
                        {
                            if (newPart)
                            {
                                partSizes.pop_back();
                            }
                            if (resized)
                            {
                                quotientEdgeCounts.pop_back();
                                for (auto &row : quotientEdgeCounts)
                                {
                                    row.pop_back();
                                }
                                quotientOutDegree.pop_back();
                            }
                            return;
                        }
                    }
                    else
                    {
                        ++result.prunedBySize;
                    }
                    if (newPart)
                    {
                        partSizes.pop_back();
                    }
                    if (resized)
                    {
                        quotientEdgeCounts.pop_back();
                        for (auto &row : quotientEdgeCounts)
                        {
                            row.pop_back();
                        }
                        quotientOutDegree.pop_back();
                    }
                }
            }
        };
    }

    OracleResult runOracle(const ComputeDag &graph, const OracleOptions &options)
    {
        const auto start = std::chrono::steady_clock::now();
        const uint32_t threads = std::max<uint32_t>(options.threads, 1);
        OracleResult result;
        result.graphId = graph.graphId;
        result.maxNodesPerPart = options.maxNodesPerPart;
        result.threads = threads;
        result.checkpointIntervalSec = options.checkpointIntervalSec;
        result.taskOrder = kTaskOrder;
        result.checkpointPath = options.checkpointPath;

        if (options.maxNodesPerPart == 0 || graph.nodes.size() <= options.maxNodesPerPart)
        {
            result.incumbent.graphId = graph.graphId;
            result.incumbent.algorithmName = "brute_force_oracle";
            result.incumbent.algorithmVersion = "0.1";
            result.incumbent.maxNodesPerPart = options.maxNodesPerPart;
            result.incumbent.partByNode.assign(graph.nodes.size(), 0);
            if (!graph.nodes.empty())
            {
                result.incumbent.partOrderHint.push_back(0);
            }
            result.score = scorePartition(graph, result.incumbent);
            result.lowerBoundCutWeight = 0;
            result.optimal = result.score.cutWeight == 0;
            result.bounded = true;
            result.status = result.optimal ? "optimal" : "invalid singleton bound";
            result.totalTasks = 1;
            result.completedTasks = 1;
            result.nextTask = 1;
            result.prefixDepth = 0;
            result.searchedStates = 1;
            result.completedTaskRanges.emplace_back(0, 1);
            updateElapsed(result, start);
            writeCheckpointIfRequested(options, result);
            return result;
        }

        SearchGraph searchGraph(graph);
        std::atomic_bool timeExpired{false};
        const uint32_t prefixDepth = options.prefixDepth == 0
                                         ? choosePrefixDepth(graph, threads)
                                         : std::min<uint32_t>(options.prefixDepth,
                                                              static_cast<uint32_t>(graph.nodes.size()));
        std::vector<PrefixTask> tasks;
        enumeratePrefixTasks(searchGraph, options, prefixDepth, tasks, timeExpired, start);
        std::stable_sort(tasks.begin(), tasks.end(), [](const PrefixTask &a, const PrefixTask &b) {
            if (a.prefixCut != b.prefixCut)
            {
                return a.prefixCut > b.prefixCut;
            }
            if (a.partCount != b.partCount)
            {
                return a.partCount > b.partCount;
            }
            return a.ordinal < b.ordinal;
        });
        result.prefixDepth = prefixDepth;
        result.totalTasks = tasks.size();

        const ResumeState resume = readResumeState(options.resumePath,
                                                   graph,
                                                   options,
                                                   prefixDepth,
                                                   tasks.size(),
                                                   kTaskOrder);
        result.searchedStates = resume.searchedStates;
        result.prunedBySize = resume.prunedBySize;
        result.prunedByBound = resume.prunedByBound;
        result.prunedByCycle = resume.prunedByCycle;
        std::vector<uint8_t> taskCompleted(tasks.size(), 0);
        for (const auto &[begin, end] : resume.completedTaskRanges)
        {
            for (uint64_t task = begin; task < end && task < taskCompleted.size(); ++task)
            {
                taskCompleted[task] = 1;
            }
        }
        result.completedTasks = countCompletedTasks(taskCompleted);
        result.nextTask = firstIncompleteTask(taskCompleted);
        result.completedTaskRanges = makeCompletedRanges(taskCompleted);
        if (resume.hasIncumbent)
        {
            result.incumbent = resume.incumbent;
            result.score = resume.score;
        }
        else
        {
            result.incumbent = makeTopoWindowIncumbent(graph, options.maxNodesPerPart);
            result.score = scorePartition(graph, result.incumbent);
        }

        std::mutex mutex;
        uint64_t bestCut = result.incumbent.partByNode.empty()
                               ? std::numeric_limits<uint64_t>::max()
                               : result.score.cutWeight;
        std::atomic<uint64_t> nextTask{0};
        std::chrono::steady_clock::time_point lastCheckpoint = start;

        const auto maybeWriteCheckpoint = [&]() {
            if (options.checkpointPath.empty() || options.checkpointIntervalSec == 0)
            {
                return;
            }
            const auto now = std::chrono::steady_clock::now();
            const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - lastCheckpoint).count();
            if (static_cast<uint64_t>(elapsed) < options.checkpointIntervalSec)
            {
                return;
            }
            lastCheckpoint = now;
            updateElapsed(result, start);
            writeCheckpointIfRequested(options, result);
        };

        const auto worker = [&]() {
            while (!timeExpired.load(std::memory_order_relaxed))
            {
                const uint64_t taskIndex = nextTask.fetch_add(1, std::memory_order_relaxed);
                if (taskIndex >= tasks.size())
                {
                    return;
                }
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    if (taskCompleted[taskIndex])
                    {
                        continue;
                    }
                }
                uint64_t localBest = std::numeric_limits<uint64_t>::max();
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    localBest = bestCut;
                }
                if (tasks[taskIndex].prefixCut >= localBest)
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    if (!taskCompleted[taskIndex])
                    {
                        taskCompleted[taskIndex] = 1;
                        ++result.searchedStates;
                        ++result.prunedByBound;
                        result.completedTasks = countCompletedTasks(taskCompleted);
                        result.nextTask = firstIncompleteTask(taskCompleted);
                        result.completedTaskRanges = makeCompletedRanges(taskCompleted);
                        maybeWriteCheckpoint();
                    }
                    if (bestCut == 0)
                    {
                        timeExpired.store(true, std::memory_order_relaxed);
                    }
                    continue;
                }
                Search search(searchGraph, options);
                search.start = start;
                search.runTask(tasks[taskIndex], localBest);
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    const bool taskComplete = search.result.status.empty();
                    result.searchedStates += search.result.searchedStates;
                    result.prunedBySize += search.result.prunedBySize;
                    result.prunedByBound += search.result.prunedByBound;
                    result.prunedByCycle += search.result.prunedByCycle;
                    if (taskComplete)
                    {
                        taskCompleted[taskIndex] = 1;
                        result.completedTasks = countCompletedTasks(taskCompleted);
                        result.nextTask = firstIncompleteTask(taskCompleted);
                        result.completedTaskRanges = makeCompletedRanges(taskCompleted);
                    }
                    if (!search.result.incumbent.partByNode.empty() && search.result.score.cutWeight < bestCut)
                    {
                        bestCut = search.result.score.cutWeight;
                        result.incumbent = std::move(search.result.incumbent);
                        result.score = search.result.score;
                    }
                    maybeWriteCheckpoint();
                    if (bestCut == 0 || !search.result.status.empty())
                    {
                        timeExpired.store(true, std::memory_order_relaxed);
                    }
                }
            }
        };

        std::vector<std::thread> workers;
        workers.reserve(threads);
        for (uint32_t i = 0; i < threads; ++i)
        {
            workers.emplace_back(worker);
        }
        for (std::thread &thread : workers)
        {
            thread.join();
        }

        if (result.incumbent.partByNode.empty())
        {
            result.incumbent = makeTopoWindowIncumbent(graph, options.maxNodesPerPart);
            result.score = scorePartition(graph, result.incumbent);
        }
        if (!result.incumbent.partByNode.empty() && result.score.cutWeight == 0)
        {
            result.completedTaskRanges = makeCompletedRanges(taskCompleted);
            result.lowerBoundCutWeight = 0;
            result.optimal = true;
            result.bounded = true;
            result.status = "optimal by zero cut bound";
        }
        else if (timeExpired.load(std::memory_order_relaxed) || result.completedTasks < result.totalTasks)
        {
            result.lowerBoundCutWeight = 0;
            result.completedTasks = countCompletedTasks(taskCompleted);
            result.nextTask = firstIncompleteTask(taskCompleted);
            result.completedTaskRanges = makeCompletedRanges(taskCompleted);
            result.optimal = false;
            result.bounded = true;
            result.status = result.incumbent.partByNode.empty() ? "timeout without bound" : "timeout with bound";
        }
        else
        {
            result.completedTasks = tasks.size();
            result.nextTask = tasks.size();
            result.completedTaskRanges = makeCompletedRanges(taskCompleted);
            result.lowerBoundCutWeight = result.score.cutWeight;
            result.optimal = true;
            result.bounded = true;
            result.status = "optimal";
        }
        updateElapsed(result, start);
        writeCheckpointIfRequested(options, result);
        return result;
    }

    std::string oracleToJson(const OracleResult &result)
    {
        std::ostringstream out;
        out << "{\n";
        out << "  \"optimal\":" << (result.optimal ? "true" : "false") << ",\n";
        out << "  \"bounded\":" << (result.bounded ? "true" : "false") << ",\n";
        out << "  \"status\":\"" << json::escape(result.status) << "\",\n";
        out << "  \"graph_id\":\"" << json::escape(result.graphId) << "\",\n";
        out << "  \"task_order\":\"" << json::escape(result.taskOrder) << "\",\n";
        out << "  \"max_nodes_per_part\":" << result.maxNodesPerPart << ",\n";
        out << "  \"score\":" << scoreToJson(result.score) << ",\n";
        out << "  \"lower_bound\":{\"cut_weight\":" << result.lowerBoundCutWeight << "},\n";
        if (result.incumbent.partByNode.empty())
        {
            out << "  \"gap\":{\"cut_weight\":null},\n";
        }
        else
        {
            out << "  \"gap\":{\"cut_weight\":" << (result.score.cutWeight - result.lowerBoundCutWeight) << "},\n";
        }
        out << "  \"proof\":{\"searched_states\":" << result.searchedStates
            << ",\"pruned_by_size\":" << result.prunedBySize
            << ",\"pruned_by_cycle\":" << result.prunedByCycle
            << ",\"pruned_by_bound\":" << result.prunedByBound
            << ",\"prefix_depth\":" << result.prefixDepth
            << ",\"total_tasks\":" << result.totalTasks
            << ",\"completed_tasks\":" << result.completedTasks
            << ",\"next_task\":" << result.nextTask
            << ",\"completed_task_ranges\":[";
        for (std::size_t i = 0; i < result.completedTaskRanges.size(); ++i)
        {
            if (i != 0)
            {
                out << ",";
            }
            out << "[" << result.completedTaskRanges[i].first << ","
                << result.completedTaskRanges[i].second << "]";
        }
        out << "]"
            << ",\"threads\":" << result.threads
            << ",\"checkpoint_interval_sec\":" << result.checkpointIntervalSec
            << ",\"elapsed_ms\":" << result.elapsedMs
            << ",\"checkpoint\":\"" << json::escape(result.checkpointPath) << "\"},\n";
        out << "  \"incumbent\":" << partitionToJson(result.incumbent);
        out << "}\n";
        return out.str();
    }
}
