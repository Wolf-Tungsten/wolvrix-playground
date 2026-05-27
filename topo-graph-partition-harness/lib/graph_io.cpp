#include "tgp/graph_io.hpp"

#include "tgp/algorithm.hpp"
#include "tgp/json.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>
#include <stdexcept>

namespace tgp
{
    namespace
    {
        uint32_t asU32(const json::Value &value, std::string_view name)
        {
            if (!value.isInt() || value.integer() < 0 || value.integer() > UINT32_MAX)
            {
                throw std::runtime_error(std::string(name) + " must be a non-negative u32");
            }
            return static_cast<uint32_t>(value.integer());
        }

        uint64_t asU64(const json::Value &value, std::string_view name)
        {
            if (!value.isInt() || value.integer() < 0)
            {
                throw std::runtime_error(std::string(name) + " must be a non-negative integer");
            }
            return static_cast<uint64_t>(value.integer());
        }

        std::string asString(const json::Value &value, std::string_view name)
        {
            if (!value.isString())
            {
                throw std::runtime_error(std::string(name) + " must be a string");
            }
            return value.string();
        }

        bool asBool(const json::Value &value, std::string_view name)
        {
            if (!value.isBool())
            {
                throw std::runtime_error(std::string(name) + " must be a bool");
            }
            return value.boolean();
        }

        std::string optionalString(const json::Value::Object &object, std::string_view key)
        {
            const auto *value = json::find(object, key);
            if (!value || !value->isString())
            {
                return {};
            }
            return value->string();
        }
    }

    std::string readTextFile(const std::string &path)
    {
        std::ifstream in(path);
        if (!in)
        {
            throw std::runtime_error("failed to open file for read: " + path);
        }
        std::ostringstream ss;
        ss << in.rdbuf();
        return ss.str();
    }

    void writeTextFile(const std::string &path, const std::string &text)
    {
        const std::filesystem::path fsPath(path);
        if (fsPath.has_parent_path())
        {
            std::filesystem::create_directories(fsPath.parent_path());
        }
        std::ofstream out(path);
        if (!out)
        {
            throw std::runtime_error("failed to open file for write: " + path);
        }
        out << text;
    }

    void rebuildAdjacency(ComputeDag &graph)
    {
        graph.outBegin.assign(graph.nodes.size() + 1, 0);
        graph.inBegin.assign(graph.nodes.size() + 1, 0);
        for (const Edge &edge : graph.edges)
        {
            ++graph.outBegin[edge.src + 1];
            ++graph.inBegin[edge.dst + 1];
        }
        for (std::size_t i = 1; i < graph.outBegin.size(); ++i)
        {
            graph.outBegin[i] += graph.outBegin[i - 1];
            graph.inBegin[i] += graph.inBegin[i - 1];
        }
        graph.outEdges.assign(graph.edges.size(), 0);
        graph.inEdges.assign(graph.edges.size(), 0);
        std::vector<uint32_t> outCursor = graph.outBegin;
        std::vector<uint32_t> inCursor = graph.inBegin;
        for (uint32_t edgeId = 0; edgeId < graph.edges.size(); ++edgeId)
        {
            const Edge &edge = graph.edges[edgeId];
            graph.outEdges[outCursor[edge.src]++] = edgeId;
            graph.inEdges[inCursor[edge.dst]++] = edgeId;
        }
    }

    ComputeDag readComputeDagFile(const std::string &path)
    {
        json::Value root = json::parse(readTextFile(path));
        if (!root.isObject())
        {
            throw std::runtime_error("compute DAG root must be an object");
        }
        const auto &object = root.object();
        if (asString(json::require(object, "format"), "format") != "wolvrix.compute-op-dag.v1")
        {
            throw std::runtime_error("unsupported compute DAG format");
        }

        ComputeDag graph;
        graph.graphId = asString(json::require(object, "graph_id"), "graph_id");
        if (const auto *source = json::find(object, "source"); source && source->isObject())
        {
            graph.sourcePass = optionalString(source->object(), "pass");
            graph.sourcePath = optionalString(source->object(), "path");
        }
        const auto *optionsValue = json::find(object, "options");
        if (!optionsValue || !optionsValue->isObject())
        {
            throw std::runtime_error("compute DAG options must be an object");
        }
        const auto &optionsObject = optionsValue->object();
        const std::string nodeGranularity = asString(json::require(optionsObject, "node_granularity"),
                                                     "options.node_granularity");
        if (nodeGranularity != "op")
        {
            throw std::runtime_error("compute DAG node_granularity must be op");
        }
        graph.edgeWeight = asString(json::require(optionsObject, "edge_weight"), "options.edge_weight");
        if (graph.edgeWeight != "value_bitwidth_words")
        {
            throw std::runtime_error("compute DAG edge_weight must be value_bitwidth_words");
        }

        const auto &nodes = json::require(object, "nodes").array();
        graph.nodes.reserve(nodes.size());
        for (const json::Value &nodeValue : nodes)
        {
            const auto &nodeObj = nodeValue.object();
            if (json::find(nodeObj, "weight"))
            {
                throw std::runtime_error("nodes[].weight is forbidden; op vertices carry no capacity weight");
            }
            Node node;
            node.id = asU32(json::require(nodeObj, "id"), "nodes[].id");
            node.opId = asU64(json::require(nodeObj, "op_id"), "nodes[].op_id");
            node.topoPos = asU32(json::require(nodeObj, "topo_pos"), "nodes[].topo_pos");
            node.kind = optionalString(nodeObj, "kind");
            node.symbol = optionalString(nodeObj, "symbol");
            if (const auto *attrs = json::find(nodeObj, "attrs"); attrs && attrs->isObject())
            {
                if (const auto *granularity = json::find(attrs->object(), "granularity"))
                {
                    if (!granularity->isString() || granularity->string() != "op")
                    {
                        throw std::runtime_error("nodes[].attrs.granularity must be op when present");
                    }
                }
            }
            graph.nodes.push_back(std::move(node));
        }

        const auto &edges = json::require(object, "edges").array();
        graph.edges.reserve(edges.size());
        uint64_t edgeWeightTotal = 0;
        for (const json::Value &edgeValue : edges)
        {
            const auto &edgeObj = edgeValue.object();
            Edge edge;
            edge.src = asU32(json::require(edgeObj, "src"), "edges[].src");
            edge.dst = asU32(json::require(edgeObj, "dst"), "edges[].dst");
            edge.weight = asU32(json::require(edgeObj, "weight"), "edges[].weight");
            const auto *values = json::find(edgeObj, "values");
            if (!values || !values->isArray())
            {
                throw std::runtime_error("edges[].values must be an array");
            }
            if (values->array().empty())
            {
                throw std::runtime_error("edges[].values must not be empty");
            }
            std::set<uint64_t> seenValues;
            uint64_t valueWidthTotal = 0;
            for (const json::Value &value : values->array())
            {
                if (!value.isObject())
                {
                    throw std::runtime_error("edges[].values[] must be an object");
                }
                const auto &valueObj = value.object();
                const uint64_t id = asU64(json::require(valueObj, "id"), "edges[].values[].id");
                if (!seenValues.insert(id).second)
                {
                    throw std::runtime_error("duplicate value id in edge values list");
                }
                if (json::find(valueObj, "weight") || json::find(valueObj, "activation_weight") ||
                    json::find(valueObj, "propagation_weight"))
                {
                    throw std::runtime_error("edges[].values[] must not carry per-value weight fields");
                }
                const uint64_t width = asU64(json::require(valueObj, "width"), "edges[].values[].width");
                if (width == 0)
                {
                    throw std::runtime_error("edges[].values[].width must be positive");
                }
                valueWidthTotal += width;
            }
            const uint64_t expectedWeight = std::max<uint64_t>(uint64_t{1}, (valueWidthTotal + 63) / 64);
            if (expectedWeight != edge.weight)
            {
                throw std::runtime_error("edge weight does not match ceil(sum(value widths) / 64)");
            }
            graph.edges.push_back(edge);
            edgeWeightTotal += edge.weight;
        }
        if (const auto *stats = json::find(object, "stats"); stats && stats->isObject())
        {
            const auto &statsObj = stats->object();
            if (const auto *nodeCount = json::find(statsObj, "nodes");
                nodeCount && asU64(*nodeCount, "stats.nodes") != graph.nodes.size())
            {
                throw std::runtime_error("stats.nodes does not match nodes array size");
            }
            if (const auto *edgeCount = json::find(statsObj, "edges");
                edgeCount && asU64(*edgeCount, "stats.edges") != graph.edges.size())
            {
                throw std::runtime_error("stats.edges does not match edges array size");
            }
            if (const auto *weightTotal = json::find(statsObj, "edge_weight_total");
                weightTotal && asU64(*weightTotal, "stats.edge_weight_total") != edgeWeightTotal)
            {
                throw std::runtime_error("stats.edge_weight_total does not match edge weights");
            }
        }

        std::sort(graph.edges.begin(), graph.edges.end(), [](const Edge &a, const Edge &b) {
            if (a.src != b.src)
            {
                return a.src < b.src;
            }
            return a.dst < b.dst;
        });
        std::vector<Edge> merged;
        for (const Edge &edge : graph.edges)
        {
            if (!merged.empty() && merged.back().src == edge.src && merged.back().dst == edge.dst)
            {
                merged.back().weight += edge.weight;
            }
            else
            {
                merged.push_back(edge);
            }
        }
        graph.edges = std::move(merged);
        rebuildAdjacency(graph);
        return graph;
    }

    PartitionResult readPartitionFile(const std::string &path)
    {
        json::Value root = json::parse(readTextFile(path));
        if (!root.isObject())
        {
            throw std::runtime_error("partition root must be an object");
        }
        const auto &object = root.object();
        if (asString(json::require(object, "format"), "format") != "wolvrix.compute-op-partition.v1")
        {
            throw std::runtime_error("unsupported partition format");
        }
        PartitionResult result;
        result.graphId = asString(json::require(object, "graph_id"), "graph_id");
        if (const auto *algorithm = json::find(object, "algorithm"); algorithm && algorithm->isObject())
        {
            result.algorithmName = optionalString(algorithm->object(), "name");
            result.algorithmVersion = optionalString(algorithm->object(), "version");
        }
        if (const auto *constraints = json::find(object, "constraints"); constraints && constraints->isObject())
        {
            result.maxNodesPerPart = asU32(json::require(constraints->object(), "max_nodes_per_part"),
                                           "constraints.max_nodes_per_part");
        }
        const auto &assignment = json::require(object, "assignment").array();
        uint32_t maxNode = 0;
        std::vector<std::pair<uint32_t, uint32_t>> pairs;
        pairs.reserve(assignment.size());
        for (const json::Value &entryValue : assignment)
        {
            const auto &entry = entryValue.object();
            const uint32_t node = asU32(json::require(entry, "node"), "assignment[].node");
            const uint32_t part = asU32(json::require(entry, "part"), "assignment[].part");
            maxNode = std::max(maxNode, node);
            pairs.emplace_back(node, part);
        }
        result.partByNode.assign(static_cast<std::size_t>(maxNode) + 1, kInvalidPartId);
        std::vector<uint8_t> seenNode(static_cast<std::size_t>(maxNode) + 1, 0);
        for (const auto &[node, part] : pairs)
        {
            if (seenNode[node]++)
            {
                throw std::runtime_error("duplicate assignment for node: " + std::to_string(node));
            }
            result.partByNode[node] = part;
        }
        std::map<PartId, PartId> canonicalPart;
        PartId nextPart = 0;
        for (PartId &part : result.partByNode)
        {
            if (part == kInvalidPartId)
            {
                continue;
            }
            auto [it, inserted] = canonicalPart.emplace(part, nextPart);
            if (inserted)
            {
                ++nextPart;
            }
            part = it->second;
        }
        if (const auto *hint = json::find(object, "part_order_hint"); hint && hint->isArray())
        {
            for (const json::Value &part : hint->array())
            {
                const PartId original = asU32(part, "part_order_hint[]");
                const auto it = canonicalPart.find(original);
                if (it != canonicalPart.end())
                {
                    result.partOrderHint.push_back(it->second);
                }
            }
        }
        if (const auto *stats = json::find(object, "stats_hint"); stats && stats->isObject())
        {
            if (const auto *runtime = json::find(stats->object(), "runtime_ms"))
            {
                if (runtime->isInt())
                {
                    result.runtimeMs = static_cast<double>(runtime->integer());
                }
            }
        }
        return result;
    }

    AlgorithmConfig readAlgorithmConfigFile(const std::string &path)
    {
        AlgorithmConfig config;
        if (path.empty())
        {
            return config;
        }
        json::Value root = json::parse(readTextFile(path));
        if (!root.isObject())
        {
            throw std::runtime_error("config root must be an object");
        }
        const auto &object = root.object();
        if (const auto *value = json::find(object, "max_nodes_per_part"))
        {
            config.maxNodesPerPart = asU32(*value, "max_nodes_per_part");
        }
        return config;
    }

    std::string partitionToJson(const PartitionResult &partition)
    {
        std::ostringstream out;
        out << "{\n";
        out << "  \"format\":\"wolvrix.compute-op-partition.v1\",\n";
        out << "  \"graph_id\":\"" << json::escape(partition.graphId) << "\",\n";
        out << "  \"algorithm\":{\"name\":\"" << json::escape(partition.algorithmName)
            << "\",\"version\":\"" << json::escape(partition.algorithmVersion) << "\"},\n";
        out << "  \"constraints\":{\"max_nodes_per_part\":" << partition.maxNodesPerPart << "},\n";
        out << "  \"assignment\":[";
        for (std::size_t i = 0; i < partition.partByNode.size(); ++i)
        {
            if (i != 0)
            {
                out << ",";
            }
            out << "{\"node\":" << i << ",\"part\":" << partition.partByNode[i] << "}";
        }
        out << "],\n";
        out << "  \"part_order_hint\":[";
        for (std::size_t i = 0; i < partition.partOrderHint.size(); ++i)
        {
            if (i != 0)
            {
                out << ",";
            }
            out << partition.partOrderHint[i];
        }
        out << "],\n";
        out << "  \"stats_hint\":{\"runtime_ms\":" << partition.runtimeMs << "}\n";
        out << "}\n";
        return out.str();
    }
}
