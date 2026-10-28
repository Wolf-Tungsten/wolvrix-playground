// Read-only diagnostic: reuse the existing private ASC builder in this TU.
// No production RepCut source or algorithm is changed by this executable.
#include "../wolvrix/lib/transform/repcut.cpp"
#include "transform/repcut_assignment_model.hpp"

#include <iostream>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

using namespace wolvrix::lib;
using namespace wolvrix::lib::transform;
using OpKind = grh::OperationKind;

namespace
{
    struct Mapping
    {
        int fd = -1;
        void *data = MAP_FAILED;
        std::size_t size = 0;
        explicit Mapping(const char *path)
        {
            fd = open(path, O_RDONLY);
            struct stat st{};
            if (fd < 0 || fstat(fd, &st) != 0 || st.st_size <= 0)
                throw std::runtime_error("cannot open nonempty input");
            size = st.st_size;
            data = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
            if (data == MAP_FAILED) throw std::runtime_error("mmap failed");
        }
        ~Mapping() { if (data != MAP_FAILED) munmap(data, size); if (fd >= 0) close(fd); }
        std::string_view text() const { return {static_cast<const char *>(data), size}; }
    };

    bool stateWrite(OpKind k)
    {
        return k == OpKind::kRegisterWritePort || k == OpKind::kMemoryWritePort ||
               k == OpKind::kLatchWritePort || k == OpKind::kMemoryFillPort;
    }

    bool noRecurringWork(OpKind k)
    {
        return k == OpKind::kConstant || k == OpKind::kRegister || k == OpKind::kMemory ||
               k == OpKind::kLatch || k == OpKind::kDpicImport || k == OpKind::kAssign ||
               k == OpKind::kRegisterReadPort || k == OpKind::kLatchReadPort;
    }

    template <class T> void sortUnique(std::vector<T> &v)
    {
        std::sort(v.begin(), v.end());
        v.erase(std::unique(v.begin(), v.end()), v.end());
    }

    struct Extractor
    {
        const grh::Graph &g;
        PhaseAData a;
        PhaseBData b;
        std::vector<uint32_t> pieceWeights, edgeWeights, hyperWeights;
        RepcutAssignmentModel model;
        uint64_t readOnlyValues = 0, memoryValues = 0, effectValues = 0;

        explicit Extractor(const grh::Graph &graph) : g(graph)
        {
            std::unordered_set<grh::ValueId, grh::ValueIdHash> inoutInputs;
            for (const auto &p : g.inoutPorts()) inoutInputs.insert(p.in);
            auto log = [](const std::string &s) {
                if (s.find("progress") == std::string::npos) std::cout << s << std::endl;
            };
            a = buildPhaseAData(g);
            std::cout << "PHASE_A nodes=" << a.nodeToOp.size() << std::endl;
            b = buildAscs(g, a, inoutInputs, log);
            buildPieces(b, a, log);
            std::vector<uint32_t> nodeWeights;
            std::vector<uint64_t> receiverExposure;
            std::vector<HyperGraph::HyperEdge> valueEdges;
            std::size_t clamps = 0;
            buildHyperGraph(g, a, b, RepcutWeightMode::kClosureAware, RepcutCostModel::kGrhsimV1,
                            1, 0, nodeWeights, pieceWeights, edgeWeights, hyperWeights,
                            receiverExposure, valueEdges, clamps);
            std::cout << "HYPERGRAPH BUILT" << std::endl;
            model.adapter = "grhsim-raw-structure-v2";
            model.atomCount = b.ascs.size();
            model.featureNames = {"grhsim_v1_closure_work", "grhsim_v1_recurring_work",
                                  "raw_operation_count", "state_write_count"};
            model.pieces.reserve(b.pieces.size());
            for (std::size_t p = 0; p < b.pieces.size(); ++p)
            {
                uint64_t recurring = 0, writes = 0;
                for (const auto node : b.pieces[p])
                {
                    const auto op = g.getOperation(a.nodeToOp[node]);
                    if (!noRecurringWork(op.kind()))
                        recurring += estimateRepcutOperationCost(g, op, RepcutCostModel::kGrhsimV1).weight;
                    writes += stateWrite(op.kind());
                }
                model.pieces.push_back({b.pieces[p].empty() ? std::vector<uint32_t>{} : b.pieceToAscs[p],
                    {b.pieces[p].empty() ? 0 : pieceWeights[p], recurring, b.pieces[p].size(), writes}});
            }
            std::cout << "PIECE FEATURES BUILT" << std::endl;

            std::unordered_map<std::string, StorageInfo> registers, latches, memories;
            collectStorageInfos(g, registers, latches, memories);
            extractStorage(registers, false);
            extractStorage(latches, false);
            extractStorage(memories, true);
            for (const auto id : g.operations())
            {
                const auto op = g.getOperation(id);
                if (!opProducesEffectResult(op)) continue;
                const auto &owners = b.nodeToAscs[a.opToNode.at(id)];
                if (owners.empty()) continue;
                if (owners.size() != 1) throw std::runtime_error("effect has multiple owners");
                for (const auto value : op.results())
                {
                    model.values.push_back({value.index, owners[0],
                                            static_cast<uint64_t>(g.valueWidth(value)), readers(value)});
                    ++effectValues;
                }
            }
            std::cout << "MODEL atoms=" << model.atomCount << " pieces=" << model.pieces.size()
                      << " values=" << model.values.size() << " read_only_modeled=" << readOnlyValues
                      << " memory_values=" << memoryValues << " effect_values=" << effectValues << std::endl;
        }

        std::vector<uint32_t> readers(grh::ValueId value) const
        {
            std::vector<uint32_t> result;
            const auto v = g.getValue(value);
            for (const auto &user : v.users())
            {
                const auto it = a.opToNode.find(user.operation);
                if (it == a.opToNode.end()) throw std::runtime_error("unknown user operation");
                const auto &atoms = b.nodeToAscs[it->second];
                result.insert(result.end(), atoms.begin(), atoms.end());
            }
            // A direct top-level output reads from the value's owner; its
            // otherwise-empty output ASC does not create another unit reader.
            sortUnique(result);
            return result;
        }

        void extractStorage(const std::unordered_map<std::string, StorageInfo> &storage, bool memory)
        {
            for (const auto &[name, info] : storage)
            {
                (void)name;
                std::set<uint32_t> owners;
                for (const auto wr : info.writePorts)
                    for (const auto atom : b.nodeToAscs[a.opToNode.at(wr)]) owners.insert(atom);
                if (owners.size() > 1) throw std::runtime_error("storage writers not in one ASC");
                uint32_t inferredOwner = kRepcutNoAtom;
                if (owners.empty() && !memory)
                {
                    RepcutInferredOwner group;
                    for (const auto rd : info.readPorts)
                    {
                        const auto op = g.getOperation(rd);
                        for (const auto value : op.results())
                        {
                            const auto val = g.getValue(value);
                            for (const auto &user : val.users())
                                group.userAtoms.push_back(b.nodeToAscs[a.opToNode.at(user.operation)]);
                        }
                    }
                    inferredOwner = model.inferredOwners.size();
                    model.inferredOwners.push_back(std::move(group));
                }
                for (const auto rd : info.readPorts)
                {
                    const auto op = g.getOperation(rd);
                    for (const auto value : op.results())
                    {
                        const auto consumers = readers(value);
                        if (owners.empty())
                        {
                            if (memory)
                            {
                                if (!consumers.empty()) throw std::runtime_error("read-only memory needs separate owner policy");
                                continue;
                            }
                            if (!consumers.empty()) ++readOnlyValues;
                            model.values.push_back({value.index, kRepcutNoAtom,
                                static_cast<uint64_t>(g.valueWidth(value)), consumers, inferredOwner});
                            continue;
                        }
                        if (memory)
                        {
                            ++memoryValues;
                            for (const auto atom : consumers)
                                if (atom != *owners.begin()) throw std::runtime_error("memory ownership constraint failed");
                        }
                        model.values.push_back({value.index, *owners.begin(),
                                                static_cast<uint64_t>(g.valueWidth(value)), consumers});
                    }
                }
            }
        }
    };

    std::vector<uint32_t> loadAssignment(const std::filesystem::path &path, std::size_t count)
    {
        std::ifstream file(path);
        if (!file) throw std::runtime_error("assignment open failed: " + path.string());
        std::vector<uint32_t> assignment;
        uint64_t value = 0;
        while (file >> value)
        {
            if (value > std::numeric_limits<uint32_t>::max()) throw std::runtime_error("assignment id overflow");
            assignment.push_back(value);
        }
        if (!file.eof() || assignment.size() != count) throw std::runtime_error("assignment length or format mismatch");
        return assignment;
    }

    void writeReport(const RepcutAssignmentReport &report, const RepcutAssignmentModel &model,
                     const std::filesystem::path &prefix)
    {
        std::ofstream out(prefix.string() + ".parts.csv");
        if (!out) throw std::runtime_error("output open failed");
        out << "part";
        for (const auto &name : model.featureNames) out << ',' << name;
        out << ",piece_copies,send_calls,send_scalar_calls,send_wide_calls,send_bytes,send_full64_blocks,send_tail_calls,send_tail_bytes,send_peers,receive_calls,receive_bytes,receive_peers\n";
        for (std::size_t p = 0; p < report.parts.size(); ++p)
        {
            const auto &r = report.parts[p];
            out << p;
            for (const auto f : r.features) out << ',' << f;
            out << ',' << r.pieceCopies << ',' << r.sent.calls << ',' << r.sent.scalarCalls << ',' << r.sent.wideCalls
                << ',' << r.sent.storageBytes << ',' << r.sent.full64ByteBlocks << ',' << r.sent.tailCalls
                << ',' << r.sent.tailBytes << ',' << r.sendPeers << ',' << r.received.calls << ','
                << r.received.storageBytes << ',' << r.receivePeers << '\n';
        }
        std::ofstream transfers(prefix.string() + ".transfers.csv");
        if (!transfers) throw std::runtime_error("transfer output open failed");
        transfers << "owner,readers,width,members,storage_bytes,full64_blocks,tail_bytes\n";
        for (const auto &group : report.transfers)
        {
            transfers << group.ownerPart << ',';
            for (const auto p : group.readerParts) transfers << p << ';';
            transfers << ',' << group.width << ',';
            for (const auto &m : group.members) transfers << m.key << ':' << m.width << ':' << m.lowBit << ';';
            transfers << ',' << group.perReader.storageBytes << ',' << group.perReader.full64ByteBlocks
                      << ',' << group.perReader.tailBytes << '\n';
        }
        std::cout << "REPORT " << prefix << " total_features=";
        for (const auto f : report.totalFeatures) std::cout << f << ',';
        std::cout << " groups=" << report.transfers.size() << " calls=" << report.totalTransfers.calls
                  << " bytes=" << report.totalTransfers.storageBytes << std::endl;
    }

    void writeModel(const RepcutAssignmentModel &model, const std::filesystem::path &path)
    {
        // Inspectable cache for subsequent search experiments, avoiding RTL reload.
        std::ofstream out(path);
        if (!out) throw std::runtime_error("model cache open failed");
        out << "repcut-assignment-model-v2\n" << model.adapter << '\n'
            << model.atomCount << ' ' << model.featureNames.size() << ' ' << model.pieces.size()
            << ' ' << model.values.size() << ' ' << model.inferredOwners.size() << '\n';
        for (const auto &name : model.featureNames) out << name << '\n';
        for (const auto &p : model.pieces)
        {
            out << p.atoms.size();
            for (const auto a : p.atoms) out << ' ' << a;
            for (const auto f : p.features) out << ' ' << f;
            out << '\n';
        }
        for (const auto &v : model.values)
        {
            out << v.key << ' ' << v.writerAtom << ' ' << v.width << ' ' << v.inferredOwner << ' ' << v.readerAtoms.size();
            for (const auto a : v.readerAtoms) out << ' ' << a;
            out << '\n';
        }
        for (const auto &g : model.inferredOwners)
        {
            out << g.userAtoms.size() << '\n';
            for (const auto &u : g.userAtoms)
            {
                out << u.size();
                for (const auto a : u) out << ' ' << a;
                out << '\n';
            }
        }
        if (!out) throw std::runtime_error("model cache write failed");
    }

}
