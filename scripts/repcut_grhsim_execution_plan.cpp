// Static diagnostic only. Inputs: partitioned GRH, actual emitter options, and
// an explicit alternating-clock scenario. Generated code/timings are validation
// outputs, never inputs to planning or activity propagation.
#include "emit/grhsim_cpp.hpp"
#include "emit/grhsim_activity_model.hpp"
#include "transform/activity_schedule.hpp"
#include "transform/repcut_cost_model.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <unordered_set>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

using namespace wolvrix::lib;
using namespace grh;
using namespace emit;
using namespace transform;
using K = OperationKind;

namespace
{
    template<class T> T attr(const Operation &op, std::string_view key, T fallback = {})
    {
        const auto v = op.attr(key); if (v) if (const auto *p = std::get_if<T>(&*v)) return *p;
        return fallback;
    }
    struct Mapping
    {
        int fd; void *data; std::size_t size;
        explicit Mapping(const char *path)
        {
            fd = open(path, O_RDONLY); struct stat st{};
            if (fd < 0 || fstat(fd, &st)) throw std::runtime_error("open input failed");
            size = st.st_size; data = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
            if (data == MAP_FAILED) throw std::runtime_error("mmap failed");
        }
        ~Mapping() { munmap(data, size); close(fd); }
        std::string_view text() const { return {static_cast<const char *>(data), size}; }
    };
    struct Unit
    {
        Graph *graph = nullptr;
        std::string instance;
        std::unordered_map<ValueId, ValueId, ValueIdHash> inputs;
        GrhSimExecutionPlan plan;
        std::vector<uint32_t> weights;
        std::vector<bool> event;
        std::map<std::string, uint64_t> coarseSummary;
        GrhSimActivityReport report;
    };
    struct Driver { std::size_t unit; ValueId value; bool early = false; };

    // Only use legal alias paths when recognizing a clock. Never collapse
    // unrelated roots, or treat an AND-gated clock as an inverted/direct clock.
    std::pair<ValueId, bool> rootOf(const Graph &g, ValueId value)
    {
        bool inverse = false; std::set<uint32_t> seen;
        while (seen.insert(value.index).second)
        {
            if (g.valueIsInput(value)) return {value, inverse};
            auto id = g.valueDef(value); if (!id.valid()) break;
            const auto op = g.getOperation(id);
            if (g.valueWidth(value) != 1 || op.operands().size() != 1 ||
                g.valueWidth(op.operands()[0]) != 1 ||
                (op.kind() != K::kAssign && op.kind() != K::kNot && op.kind() != K::kLogicNot)) break;
            inverse ^= op.kind() != K::kAssign; value = op.operands()[0];
        }
        return {};
    }
    uint64_t delayed(uint64_t mask)
    {
        // This permutation is explicitly for the caller-selected, alternating
        // two-half-cycle harness. It is not a universal multi-clock rule.
        return (mask & ~UINT64_C(3)) | ((mask & 1) << 1) | ((mask & 2) >> 1);
    }
    uint32_t weight(const Graph &g, const Operation &op)
    {
        switch (op.kind())
        {
        case K::kConstant: case K::kRegister: case K::kMemory: case K::kLatch:
        case K::kDpicImport: case K::kAssign: case K::kRegisterReadPort: case K::kLatchReadPort: return 0;
        default: return estimateRepcutOperationCost(g, op, RepcutCostModel::kGrhsimV1).weight;
        }
    }
    void count(std::map<std::string, uint64_t> &m, std::string prefix, uint64_t mask, uint64_t work)
    {
        m[prefix + "_total"] += work;
        if (mask) m[prefix + "_reachable"] += work;
        if (mask & 1) m[prefix + "_rise"] += work;
        if (mask & 2) m[prefix + "_fall"] += work;
        if ((mask & 3) == 3) m[prefix + "_both"] += work;
        if (mask & kGrhSimUnknownActivity) m[prefix + "_unknown"] += work;
        if ((mask & kGrhSimUnknownActivity) && !(mask & 3)) m[prefix + "_unknown_only"] += work;
    }
    std::map<std::string, uint64_t> summarize(const Unit &u)
    {
        std::map<std::string, uint64_t> m;
        m["graph_ops"] = u.graph->operations().size();
        m["groups"] = u.plan.groups.size(); m["batches"] = u.plan.batches.size();
        m["unresolved_events"] = u.report.unresolvedEvents;
        for (const auto &group : u.plan.groups)
        {
            const bool compute = group.phase == GrhSimExecutionPlan::Phase::Compute;
            m[compute ? "compute_groups" : "commit_groups"]++;
            const auto active = u.report.computeGroupMasks[group.activeId];
            if (compute) count(m, "group_count", active, 1);
            for (auto id : group.operations)
            {
                const auto work = u.weights.at(id.index);
                const auto semantic = u.report.operationMasks.at(id.index);
                const auto executed = !compute || u.event[id.index] ? semantic : active;
                count(m, "value_work", semantic, work);
                count(m, "group_work", executed, work);
                if (work)
                {
                    count(m, "value_ops", semantic, 1);
                    count(m, "group_ops", executed, 1);
                }
                if (compute && !u.event[id.index])
                {
                    if ((active & 1) && !(semantic & 1)) m["coactivation_extra_rise_work"] += work;
                    if ((active & 2) && !(semantic & 2)) m["coactivation_extra_fall_work"] += work;
                }
            }
        }
        for (const auto &batch : u.plan.batches)
        {
            uint64_t mask = 0;
            for (const auto &word : batch.words) for (auto g : word.groups)
            {
                const auto it = std::find_if(u.plan.groups.begin(), u.plan.groups.end(),
                    [&](const auto &entry) { return entry.supernode == g; });
                mask |= u.report.computeGroupMasks.at(it->activeId);
            }
            if (batch.phase == GrhSimExecutionPlan::Phase::Compute) count(m, "batch_count", mask, 1);
        }
        for (const auto &input : u.plan.inputs)
        {
            m["input_targets"] += input.targets.size();
            m["input_mask_words"] += input.bitMasks.size();
            m["tracked_inputs"] += input.inputChangeFlag;
        }
        for (const auto &b : u.plan.boundaries) m["boundary_targets"] += b.targets.size();
        for (const auto &s : u.plan.states) { m["state_targets"] += s.targets.size(); m["row_selective_states"] += s.rowSelective; }
        for (const auto &[key, val] : u.plan.storageFeatures) m[key] = val;
        return m;
    }
}

int main(int argc, char **argv)
{
    try
    {
        if (argc != 4) throw std::runtime_error("usage: probe partitioned.json output_dir alternating_clock_port");
        const std::filesystem::path out(argv[2]); std::filesystem::create_directories(out);
        Design design; { Mapping input(argv[1]); design = Design::fromJsonString(input.text()); }
        auto &top = *design.findGraph(design.topGraphs().at(0));
        const auto clock = top.inputPortValue(argv[3]);
        if (!clock.valid() || top.valueWidth(clock) != 1) throw std::runtime_error("explicit clock input missing");
        std::cout << "LOADED " << top.symbol() << " alternating_clock=" << argv[3] << std::endl;
        std::vector<Unit> units;
        std::unordered_map<ValueId, Driver, ValueIdHash> drivers;
        // Capture wrapper bindings before canonicalizing clone port names.
        for (auto instId : top.operations())
        {
            const auto inst = top.getOperation(instId); if (inst.kind() != K::kInstance) continue;
            const auto module = attr<std::string>(inst, "moduleName");
            Unit unit; unit.instance = std::string(inst.symbolText());
            const auto model = "G" + unit.instance + "_model";
            auto &g = design.cloneGraph(module, model); unit.graph = &g;
            const auto ins = attr<std::vector<std::string>>(inst, "inputPortName");
            const auto outs = attr<std::vector<std::string>>(inst, "outputPortName");
            for (std::size_t i = 0; i < ins.size(); ++i) unit.inputs.emplace(g.inputPortValue(ins[i]), inst.operands()[i]);
            for (std::size_t i = 0; i < outs.size(); ++i) drivers.emplace(inst.results()[i], Driver{units.size(), g.outputPortValue(outs[i])});
            units.push_back(std::move(unit));
        }
        if (units.empty()) throw std::runtime_error("no units");
        // Result-producing effects are published early by the wrapper. Discover
        // their provenance instead of silently delaying them like state outputs.
        for (auto &[_, driver] : drivers)
        {
            const auto &g = *units[driver.unit].graph;
            std::vector<ValueId> stack{driver.value}; std::set<uint32_t> seen;
            bool state = false;
            while (!stack.empty())
            {
                const auto v = stack.back(); stack.pop_back(); if (!seen.insert(v.index).second) continue;
                auto id = g.valueDef(v); if (!id.valid()) continue;
                const auto op = g.getOperation(id);
                if (op.kind() == K::kDpicCall) { driver.early = true; continue; }
                if (op.kind() == K::kRegisterReadPort || op.kind() == K::kLatchReadPort || op.kind() == K::kMemoryReadPort)
                { state = true; continue; }
                stack.insert(stack.end(), op.operands().begin(), op.operands().end());
            }
            if (state && driver.early) throw std::runtime_error("mixed state/effect output");
        }
        std::ofstream groups(out / "groups.csv"), batches(out / "batch_groups.csv"), inputs(out / "input_masks.csv");
        groups << "part,group,active_id,phase,operations,estimated_lines,work,group_mask,value_rise_work,value_fall_work\n";
        batches << "part,batch,phase,word,group,active_id,helper_chunks\n";
        inputs << "part,value,target,word,mask\n";
        for (auto &u : units)
        {
            auto &g = *u.graph;
            const auto ins = g.inputPorts(); const auto outs = g.outputPorts();
            std::vector<std::pair<std::string, ValueId>> inPorts, outPorts;
            for (const auto &p : ins) inPorts.emplace_back(p.name, p.value);
            for (const auto &p : outs) outPorts.emplace_back(p.name, p.value);
            for (const auto &[name, _] : inPorts) g.removeInputPort(name);
            for (const auto &[name, _] : outPorts) g.removeOutputPort(name);
            std::map<uint32_t, std::size_t> aliases;
            for (const auto &[_, v] : inPorts) ++aliases[v.index];
            std::unordered_set<ValueId, ValueIdHash> bound;
            std::string tracked;
            for (std::size_t i = 0; i < inPorts.size(); ++i)
            {
                auto v = inPorts[i].second; const auto name = "repcut_port_" + std::to_string(i);
                if (!bound.insert(v).second) continue;
                g.bindInputPort(name, v);
                if ((g.valueWidth(v) + 63) / 64 >= 128 && aliases[v.index] == 1 && drivers.contains(u.inputs.at(v)))
                { if (!tracked.empty()) tracked += ','; tracked += name; }
            }
            for (std::size_t i = 0; i < outPorts.size(); ++i)
                g.bindOutputPort("repcut_port_" + std::to_string(i + inPorts.size()), outPorts[i].second);
            SessionStore session; PassManager manager; manager.options().session = &session;
            ActivityScheduleOptions schedule; schedule.path = g.symbol();
            manager.addPass(std::make_unique<ActivitySchedulePass>(schedule)); PassDiagnostics diagnostics;
            if (!manager.run(design, diagnostics).success) throw std::runtime_error("schedule failed");
            EmitOptions options; options.session = &session; options.topOverrides = {g.symbol()};
            options.sessionPathPrefix = g.symbol(); options.attributes["perf"] = "off"; options.attributes["waveform"] = "off";
            options.attributes["input_dirty_tracking"] = tracked.empty() ? "0" : "1";
            options.attributes["tracked_input_ports"] = tracked;
            EmitDiagnostics emitDiagnostics; EmitGrhSimCpp emitter(&emitDiagnostics);
            if (!emitter.analyzeExecutionPlan(design, options, u.plan).success) throw std::runtime_error("plan failed");
            std::size_t cap = 1;
            for (auto id : g.operations()) cap = std::max(cap, std::size_t(id.index) + 1);
            u.weights.resize(cap); u.event.resize(cap);
            for (auto id : g.operations()) u.weights[id.index] = weight(g, g.getOperation(id));
            for (const auto &event : u.plan.events) u.event[event.operation.index] = true;
            std::map<uint32_t, std::size_t> active;
            for (const auto &group : u.plan.groups) active[group.supernode] = group.activeId;
            for (const auto &batch : u.plan.batches) for (const auto &word : batch.words) for (auto group : word.groups)
                batches << u.instance << ',' << batch.index << ',' << (batch.phase == GrhSimExecutionPlan::Phase::Compute ? "compute" : "commit")
                        << ',' << word.activeWord << ',' << group << ',' << active.at(group) << ',' << word.helperChunks.size() << '\n';
            for (const auto &input : u.plan.inputs) for (const auto &bits : input.bitMasks)
                inputs << u.instance << ',' << input.value.index << ',' << bits.target << ',' << bits.word << ',' << bits.mask << '\n';
            std::cout << "PLANNED " << u.instance << " groups=" << u.plan.groups.size() << " batches=" << u.plan.batches.size() << std::endl;
        }
        std::ofstream summary(out / "summary.csv"); summary << "part,precision,feature,value\n";
        for (const bool precise : {false, true})
        {
            for (auto &u : units) u.report = {};
            bool converged = false;
            for (unsigned round = 0; round < 64; ++round)
            {
                bool changed = false;
                for (auto &u : units)
                {
                    GrhSimActivitySeeds seeds;
                    for (const auto &[local, parent] : u.inputs)
                    {
                        auto [root, inv] = rootOf(top, parent);
                        if (root == clock)
                        {
                            seeds.inputs[local] = {{0, 1, 3}};
                            seeds.events[local] = inv ? GrhSimEventActivity{2, 1, 3} : GrhSimEventActivity{1, 2, 3};
                        }
                        else if (const auto it = drivers.find(parent); it != drivers.end())
                        {
                            const auto &driver = it->second;
                            auto &ranges = seeds.inputs[local];
                            const auto &r = units[driver.unit].report;
                            if (driver.value.index < r.values.size())
                            {
                                ranges = r.values[driver.value.index];
                                if (!driver.early) for (auto &range : ranges) range.mask = delayed(range.mask);
                            }
                        }
                        else
                        {
                            const auto def = top.valueDef(parent);
                            if (def.valid() && top.getOperation(def).kind() == K::kConstant) seeds.inputs[local] = {};
                            // Missing primary inputs are explicitly unknown in the core model.
                        }
                    }
                    auto next = analyzeGrhSimActivity(*u.graph, u.plan, seeds, precise);
                    for (const auto &[_, d] : drivers) if (&u == &units[d.unit])
                    {
                        if (d.value.index >= u.report.values.size() || u.report.values[d.value.index] != next.values[d.value.index])
                            changed = true;
                    }
                    u.report = std::move(next);
                }
                std::cout << "PROPAGATED precision=" << precise << " round=" << round + 1 << " changed=" << changed << std::endl;
                if (!changed) { converged = true; break; }
            }
            if (!converged) throw std::runtime_error("package activity did not converge");
            for (auto &u : units)
            {
                const auto m = summarize(u);
                for (const auto &[key, val] : m) summary << u.instance << ',' << (precise ? "range" : "whole") << ',' << key << ',' << val << '\n';
                if (!precise) { u.coarseSummary = m; continue; }
                for (const auto &group : u.plan.groups)
                {
                    uint64_t w = 0, rise = 0, fall = 0;
                    for (auto id : group.operations)
                    {
                        const auto cost = u.weights[id.index]; w += cost;
                        const auto mask = u.report.operationMasks[id.index];
                        if (mask & 1) rise += cost; if (mask & 2) fall += cost;
                    }
                    groups << u.instance << ',' << group.supernode << ',' << group.activeId << ','
                           << (group.phase == GrhSimExecutionPlan::Phase::Compute ? "compute" : "commit") << ','
                           << group.operations.size() << ',' << group.estimatedLines << ',' << w << ','
                           << u.report.computeGroupMasks[group.activeId] << ',' << rise << ',' << fall << '\n';
                }
            }
        }
        std::cout << "STATIC PLAN AUDIT COMPLETE units=" << units.size() << std::endl;
    }
    catch (const std::exception &e) { std::cerr << e.what() << std::endl; return 1; }
}
