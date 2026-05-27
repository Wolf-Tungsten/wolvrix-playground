#include "tgp/oracle.hpp"

#include "tgp/graph_io.hpp"
#include "tgp/json.hpp"
#include "tgp/validator.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <limits>
#include <mutex>
#include <sstream>
#include <thread>

namespace tgp
{
    namespace
    {
        struct PrefixTask
        {
            std::vector<PartId> assignment;
            std::vector<uint64_t> partWeights;
            uint32_t partCount = 0;
        };

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

        bool asCheckpointBool(const json::Value &value)
        {
            if (!value.isBool())
            {
                throw std::runtime_error("checkpoint value is not bool");
            }
            return value.boolean();
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
            score.maxPartWeight = asCheckpointU64(json::require(object, "max_part_weight"));
            score.meanPartWeight = asCheckpointDouble(json::require(object, "mean_part_weight"));
            score.p90PartWeight = asCheckpointU64(json::require(object, "p90_part_weight"));
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
                partition.maxNodeWeight = asCheckpointU32(json::require(constraintsObject, "max_node_weight"));
                if (const auto *allow = json::find(constraintsObject, "allow_oversize_singleton"))
                {
                    partition.allowOversizeSingleton = asCheckpointBool(*allow);
                }
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
            uint64_t nextTask = 0;
            uint64_t searchedStates = 0;
            uint64_t prunedByWeight = 0;
            uint64_t prunedByBound = 0;
            uint64_t prunedByCycle = 0;
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
            while (depth < graph.nodes.size() && depth < 14)
            {
                uint64_t approx = 1;
                for (uint32_t i = 0; i < depth; ++i)
                {
                    approx *= static_cast<uint64_t>(i + 1);
                    if (approx >= static_cast<uint64_t>(std::max<uint32_t>(threads, 1)) * 16)
                    {
                        return depth;
                    }
                }
                ++depth;
            }
            return depth;
        }

        void enumeratePrefixTasks(const ComputeDag &graph,
                                  const OracleOptions &options,
                                  uint32_t prefixDepth,
                                  std::vector<PrefixTask> &tasks,
                                  std::atomic_bool &timeExpired,
                                  const std::chrono::steady_clock::time_point &start)
        {
            std::vector<PartId> current(graph.nodes.size(), kInvalidPartId);
            std::vector<uint64_t> partWeights;
            const auto timedOut = [&]() {
                if (options.timeLimitSec == 0)
                {
                    return false;
                }
                const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                    std::chrono::steady_clock::now() - start).count();
                return static_cast<uint64_t>(elapsed) >= options.timeLimitSec;
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
                    task.assignment = current;
                    task.partWeights = partWeights;
                    task.partCount = partCount;
                    tasks.push_back(std::move(task));
                    return;
                }
                for (uint32_t part = 0; part <= partCount; ++part)
                {
                    const bool newPart = part == partCount;
                    if (newPart)
                    {
                        partWeights.push_back(0);
                    }
                    const uint64_t nextWeight = partWeights[part] + graph.nodes[node].weight;
                    bool allowed = options.maxNodeWeight == 0 || nextWeight <= options.maxNodeWeight;
                    if (!allowed && options.allowOversizeSingleton && partWeights[part] == 0 &&
                        graph.nodes[node].weight > options.maxNodeWeight)
                    {
                        allowed = true;
                    }
                    if (allowed)
                    {
                        partWeights[part] = nextWeight;
                        current[node] = part;
                        self(self, node + 1, newPart ? partCount + 1 : partCount);
                        current[node] = kInvalidPartId;
                        partWeights[part] -= graph.nodes[node].weight;
                    }
                    if (newPart)
                    {
                        partWeights.pop_back();
                    }
                    if (timeExpired.load(std::memory_order_relaxed))
                    {
                        return;
                    }
                }
            };
            dfs(dfs, 0, 0);
        }

        ResumeState readResumeState(const std::string &path)
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
                if (const auto *nextTask = json::find(object, "next_task");
                    nextTask && nextTask->isInt() && nextTask->integer() > 0)
                {
                    state.nextTask = static_cast<uint64_t>(nextTask->integer());
                }
                else if (const auto *completed = json::find(object, "completed_tasks");
                         completed && completed->isInt() && completed->integer() > 0)
                {
                    state.nextTask = static_cast<uint64_t>(completed->integer());
                }
                if (const auto *searchedStates = json::find(object, "searched_states");
                    searchedStates && searchedStates->isInt() && searchedStates->integer() > 0)
                {
                    state.searchedStates = static_cast<uint64_t>(searchedStates->integer());
                }
                if (const auto *pruned = json::find(object, "pruned_by_weight");
                    pruned && pruned->isInt() && pruned->integer() > 0)
                {
                    state.prunedByWeight = static_cast<uint64_t>(pruned->integer());
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
            out << "  \"status\":\"" << json::escape(result.status) << "\",\n";
            out << "  \"optimal\":" << (result.optimal ? "true" : "false") << ",\n";
            out << "  \"bounded\":" << (result.bounded ? "true" : "false") << ",\n";
            out << "  \"prefix_depth\":" << result.prefixDepth << ",\n";
            out << "  \"total_tasks\":" << result.totalTasks << ",\n";
            out << "  \"completed_tasks\":" << result.completedTasks << ",\n";
            out << "  \"next_task\":" << result.nextTask << ",\n";
            out << "  \"searched_states\":" << result.searchedStates << ",\n";
            out << "  \"pruned_by_weight\":" << result.prunedByWeight << ",\n";
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

        struct Search
        {
            const ComputeDag &graph;
            const OracleOptions &options;
            OracleResult result;
            std::vector<PartId> current;
            std::vector<uint64_t> partWeights;
            uint64_t bestCut = std::numeric_limits<uint64_t>::max();
            std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();

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
                current = task.assignment;
                partWeights = task.partWeights;
                bestCut = globalBest;
                dfs(static_cast<uint32_t>(taskDepth(task)), task.partCount);
            }

            static std::size_t taskDepth(const PrefixTask &task)
            {
                std::size_t depth = 0;
                while (depth < task.assignment.size() && task.assignment[depth] != kInvalidPartId)
                {
                    ++depth;
                }
                return depth;
            }

            uint64_t currentCutPrefix(uint32_t upto) const
            {
                uint64_t cut = 0;
                for (const Edge &edge : graph.edges)
                {
                    if (edge.src < upto && edge.dst < upto &&
                        current[edge.src] != current[edge.dst])
                    {
                        cut += edge.weight;
                    }
                }
                return cut;
            }

            void dfs(uint32_t node, uint32_t partCount)
            {
                if (timedOut())
                {
                    result.status = "timeout without bound";
                    return;
                }
                ++result.searchedStates;
                const uint64_t prefixCut = currentCutPrefix(node);
                if (prefixCut >= bestCut)
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
                    candidate.maxNodeWeight = options.maxNodeWeight;
                    candidate.allowOversizeSingleton = options.allowOversizeSingleton;
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

                for (uint32_t part = 0; part <= partCount; ++part)
                {
                    const bool newPart = part == partCount;
                    if (newPart)
                    {
                        partWeights.push_back(0);
                    }
                    const uint64_t nextWeight = partWeights[part] + graph.nodes[node].weight;
                    bool allowed = options.maxNodeWeight == 0 || nextWeight <= options.maxNodeWeight;
                    if (!allowed && options.allowOversizeSingleton && partWeights[part] == 0 &&
                        graph.nodes[node].weight > options.maxNodeWeight)
                    {
                        allowed = true;
                    }
                    if (allowed)
                    {
                        partWeights[part] = nextWeight;
                        current[node] = part;
                        dfs(node + 1, newPart ? partCount + 1 : partCount);
                        current[node] = kInvalidPartId;
                        partWeights[part] -= graph.nodes[node].weight;
                    }
                    else
                    {
                        ++result.prunedByWeight;
                    }
                    if (newPart)
                    {
                        partWeights.pop_back();
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
        result.checkpointPath = options.checkpointPath;

        std::atomic_bool timeExpired{false};
        const uint32_t prefixDepth = choosePrefixDepth(graph, threads);
        std::vector<PrefixTask> tasks;
        enumeratePrefixTasks(graph, options, prefixDepth, tasks, timeExpired, start);
        result.prefixDepth = prefixDepth;
        result.totalTasks = tasks.size();
        const ResumeState resume = readResumeState(options.resumePath);
        const uint64_t resumeNextTask = std::min<uint64_t>(resume.nextTask, tasks.size());
        result.nextTask = resumeNextTask;
        result.completedTasks = resumeNextTask;
        result.searchedStates = resume.searchedStates;
        result.prunedByWeight = resume.prunedByWeight;
        result.prunedByBound = resume.prunedByBound;
        result.prunedByCycle = resume.prunedByCycle;
        if (resume.hasIncumbent)
        {
            result.incumbent = resume.incumbent;
            result.score = resume.score;
        }

        std::mutex mutex;
        uint64_t bestCut = resume.hasIncumbent ? resume.score.cutWeight : std::numeric_limits<uint64_t>::max();
        std::atomic<uint64_t> nextTask{resumeNextTask};
        std::atomic<uint64_t> firstIncompleteTask{tasks.size()};

        const auto worker = [&]() {
            while (!timeExpired.load(std::memory_order_relaxed))
            {
                const uint64_t taskIndex = nextTask.fetch_add(1, std::memory_order_relaxed);
                if (taskIndex >= tasks.size())
                {
                    return;
                }
                uint64_t localBest = std::numeric_limits<uint64_t>::max();
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    localBest = bestCut;
                }
                Search search{graph, options};
                search.start = start;
                search.runTask(tasks[taskIndex], localBest);
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    result.searchedStates += search.result.searchedStates;
                    result.prunedByWeight += search.result.prunedByWeight;
                    result.prunedByBound += search.result.prunedByBound;
                    result.prunedByCycle += search.result.prunedByCycle;
                    result.completedTasks = std::max<uint64_t>(result.completedTasks, taskIndex + 1);
                    result.nextTask = std::min<uint64_t>(result.completedTasks, tasks.size());
                    if (!search.result.incumbent.partByNode.empty() && search.result.score.cutWeight < bestCut)
                    {
                        bestCut = search.result.score.cutWeight;
                        result.incumbent = std::move(search.result.incumbent);
                        result.score = search.result.score;
                    }
                    if (!search.result.status.empty())
                    {
                        uint64_t observed = firstIncompleteTask.load(std::memory_order_relaxed);
                        while (taskIndex < observed &&
                               !firstIncompleteTask.compare_exchange_weak(observed,
                                                                           taskIndex,
                                                                           std::memory_order_relaxed))
                        {
                        }
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
            AlgorithmConfig config;
            config.maxNodeWeight = options.maxNodeWeight;
            config.allowOversizeSingleton = options.allowOversizeSingleton;
            auto algorithm = createAlgorithm("topo-window");
            result.incumbent = algorithm->run(graph, config);
            result.score = scorePartition(graph, result.incumbent);
        }
        if (timeExpired.load(std::memory_order_relaxed) || result.completedTasks < result.totalTasks)
        {
            result.lowerBoundCutWeight = 0;
            const uint64_t resumeTask = std::min(firstIncompleteTask.load(std::memory_order_relaxed),
                                                 nextTask.load(std::memory_order_relaxed));
            result.nextTask = std::min<uint64_t>(resumeTask, tasks.size());
            result.completedTasks = std::min(result.completedTasks, result.nextTask);
            result.optimal = false;
            result.bounded = true;
            result.status = result.incumbent.partByNode.empty() ? "timeout without bound" : "timeout with bound";
        }
        else
        {
            result.lowerBoundCutWeight = result.score.cutWeight;
            result.optimal = true;
            result.bounded = true;
            result.status = "optimal";
        }
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
            << ",\"pruned_by_weight\":" << result.prunedByWeight
            << ",\"pruned_by_cycle\":" << result.prunedByCycle
            << ",\"pruned_by_bound\":" << result.prunedByBound
            << ",\"prefix_depth\":" << result.prefixDepth
            << ",\"total_tasks\":" << result.totalTasks
            << ",\"completed_tasks\":" << result.completedTasks
            << ",\"next_task\":" << result.nextTask
            << ",\"checkpoint\":\"" << json::escape(result.checkpointPath) << "\"},\n";
        out << "  \"incumbent\":" << partitionToJson(result.incumbent);
        out << "}\n";
        return out.str();
    }
}
