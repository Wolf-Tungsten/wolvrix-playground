// Pre-assignment actual-lowering template; no emitted or compiled code input.
#include "repcut_grhsim_assignment_extract.hpp"
#include "emit/grhsim_activity_model.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include "arrival_context_cost.hpp"
#include "fine_state_provenance.hpp"
#include "repcut_grhsim_context_consumers.hpp"
#include "initial_graph.hpp"
#include <tuple>

using namespace wolvrix::lib::emit;

int main(int argc, char **argv) {
    try {
        if (argc != 4) throw std::runtime_error("usage: raw.json output clock_port");
        grh::Design design;
        { Mapping input(argv[1]); design = grh::Design::fromJsonString(input.text()); }
        if (design.topGraphs().size() != 1) throw std::runtime_error("one raw graph required");
        auto &graph = *design.findGraph(design.topGraphs()[0]);
        const auto clock = graph.inputPortValue(argv[3]);
        if (!clock.valid() || graph.valueWidth(clock) != 1) throw std::runtime_error("invalid scenario clock");
        Extractor extract(graph);
        const std::filesystem::path out(argv[2]); std::filesystem::create_directories(out);
        std::cout << "INITIAL MODEL atoms=" << extract.model.atomCount << std::endl;
        std::vector<uint32_t> nodePiece(extract.a.nodeToOp.size(), UINT32_MAX);
        for (uint32_t p = 0; p < extract.b.pieces.size(); ++p)
            for (auto n : extract.b.pieces[p]) nodePiece[n] = p;
        constexpr std::string_view originAttr = "__grhsim_context_origin";
        for (uint32_t n = 0; n < extract.a.nodeToOp.size(); ++n) {
            if (graph.getOperation(extract.a.nodeToOp[n]).attr(originAttr)) throw std::runtime_error("origin attribute collision");
            graph.setAttr(extract.a.nodeToOp[n], originAttr, static_cast<int64_t>(n));
        }
        std::map<uint64_t,uint32_t> valueOwners;
        for(const auto &v:extract.model.values)valueOwners[v.key]=v.writerAtom;
        std::map<std::string,uint32_t> stateOwners;
        for(auto id:graph.operations()) {
            const auto op=graph.getOperation(id);const auto k=op.kind();
            const char *key=k==OpKind::kRegisterReadPort?"regSymbol":k==OpKind::kLatchReadPort?"latchSymbol":
                            k==OpKind::kMemoryReadPort?"memSymbol":nullptr;
            if(!key)continue;
            const auto attr=op.attr(key);if(!attr||!std::holds_alternative<std::string>(*attr))throw std::runtime_error("missing state");
            for(auto value:op.results())if(valueOwners.contains(value.index)) {
                auto [it,inserted]=stateOwners.emplace(std::get<std::string>(*attr),valueOwners.at(value.index));
                if(!inserted&&it->second!=valueOwners.at(value.index))throw std::runtime_error("state owner disagreement");
            }
        }
        SessionStore session; PassManager manager; manager.options().session = &session;
        ActivityScheduleOptions schedule; schedule.path = graph.symbol();
        manager.addPass(std::make_unique<ActivitySchedulePass>(schedule));
        PassDiagnostics diagnostics;
        if (!manager.run(design, diagnostics).success) throw std::runtime_error("raw schedule failed");
        std::cout << "CONTEXT SCHEDULED" << std::endl;
        EmitOptions options; options.session = &session; options.topOverrides = {graph.symbol()};
        options.attributes = {{"perf", "off"}, {"waveform", "off"}, {"input_dirty_tracking", "0"}};
        EmitDiagnostics emitDiagnostics; EmitGrhSimCpp emitter(&emitDiagnostics);
        GrhSimExecutionPlan plan;
        if (!emitter.analyzeExecutionPlan(design, options, plan).success) throw std::runtime_error("raw backend plan failed");
        std::cout << "CONTEXT PLANNED groups=" << plan.groups.size() << std::endl;
        GrhSimActivitySeeds seeds;
        seeds.events[clock] = {1, 2, 3}; seeds.inputs[clock] = {{0, 1, 3}};
        const auto causeAnalysis = trigger_context::analyze(graph,plan,seeds,clock);
        trigger_context::writeCauses(causeAnalysis,plan,out);
        state_hold::write(graph,plan,out);
        const auto &activity = causeAnalysis.projected;
        std::cout << "TRIGGER DECOMPOSITION PASS events=" << causeAnalysis.fullEventReferences
                  << " causes=" << causeAnalysis.causes.size() << std::endl;
        const auto attributed = attributeGrhSimWork(plan, activity);
        if (!attributed.unattributedFeatures.empty() || attributed.summary.unmodeledCommitBodies ||
            attributed.summary.unmodeledComputeGroups || !plan.unmodeledCommitWrites.empty())
            throw std::runtime_error("uncovered backend work");
        std::cout << "CONTEXT ATTRIBUTED sites=" << attributed.sites.size() << std::endl;

        arrival_context::Provenance provenance(graph,activity,stateOwners,clock,causeAnalysis);
        arrival_context::Model result; result.atoms = extract.model.atomCount;
        std::map<uint32_t, uint32_t> contextIds;
        for (const auto &group : plan.groups) {
            contextIds[group.supernode] = result.compute.size();
            result.compute.push_back(group.phase == GrhSimExecutionPlan::Phase::Compute);
        }
        std::vector<uint32_t> singleDemand(extract.model.pieces.size(), UINT32_MAX);
        std::map<std::vector<uint32_t>, uint32_t> mixedDemands;
        const auto internDemand = [&](std::vector<uint32_t> pieces) {
            sortUnique(pieces);
            pieces.erase(std::remove_if(pieces.begin(), pieces.end(), [&](auto p) {
                return extract.model.pieces.at(p).atoms.empty(); }), pieces.end());
            if (pieces.empty()) return UINT32_MAX;
            if (pieces.size() == 1) {
                auto &id = singleDemand.at(pieces[0]);
                if (id == UINT32_MAX) { id = result.demands.size(); result.demands.push_back(std::move(pieces)); }
                return id;
            }
            auto [it, inserted] = mixedDemands.try_emplace(pieces, result.demands.size());
            if (inserted) result.demands.push_back(std::move(pieces));
            return it->second;
        };
        const auto ancestry = [&](grh::OperationId op) {
            const auto attr = graph.getOperation(op).attr(originAttr);
            if (!attr || !std::holds_alternative<int64_t>(*attr)) throw std::runtime_error("missing raw operation ancestry");
            const auto n = std::get<int64_t>(*attr);
            if (n < 0 || static_cast<uint64_t>(n) >= nodePiece.size()) throw std::runtime_error("invalid raw ancestry");
            return static_cast<uint32_t>(n);
        };
        uint64_t clones = 0, unowned = 0, crossPieceCompute = 0, emptyZero = 0;
        std::unordered_map<grh::OperationId, std::vector<uint32_t>, grh::OperationIdHash> cloneDemands;
        const auto piecesFor = [&](grh::OperationId op) -> std::vector<uint32_t> {
            const auto node = ancestry(op);
            if (op == extract.a.nodeToOp[node]) return {nodePiece.at(node)};
            ++clones;
            if (const auto it = cloneDemands.find(op); it != cloneDemands.end()) return it->second;
            // Source clones belong to their consuming schedule, not to the ASC
            // containing the original register writer/read declaration.
            auto pieces = activity_context::consumerPieces(graph, op,
                [&](grh::OperationId consumer) -> std::optional<uint32_t> {
                    const auto raw = ancestry(consumer);
                    if (consumer == extract.a.nodeToOp[raw]) return nodePiece.at(raw);
                    return std::nullopt;
                });
            cloneDemands.emplace(op, pieces);
            return pieces;
        };
        using Key = std::tuple<uint32_t, uint32_t, uint64_t, uint32_t>;
        std::map<Key, activity_context::Units> aggregated;
        const auto add = [&](uint32_t context, uint64_t mask, const activity_context::Units &units,
                             std::vector<uint32_t> pieces, uint32_t sources) {
            const auto demand = internDemand(std::move(pieces));
            if (demand == UINT32_MAX) { ++unowned; return; }
            if (!mask && std::all_of(units.begin(), units.end(), [](auto v) { return !v; })) { ++emptyZero; return; }
            auto &target = aggregated[{context, demand, mask, sources}];
            for (std::size_t u = 0; u < units.size(); ++u) target[u] += units[u];
        };
        using Kind = GrhSimAttributedWorkReport::Site::Kind;
        for (const auto &site : attributed.sites) {
            const auto context = contextIds.at(site.supernode);
            std::vector<uint32_t> allPieces;
            uint64_t ownMask = 0;
            for (auto op : site.operations) {
                const auto pieces = piecesFor(op);
                allPieces.insert(allPieces.end(), pieces.begin(), pieces.end());
                ownMask |= activity.operationMasks.at(op.index);
            }
            sortUnique(allPieces);
            if (site.kind == Kind::Compute) {
                crossPieceCompute += allPieces.size() > 1;
                std::vector<uint32_t> sources;
                for(auto op:site.operations)sources.push_back(provenance.operation(op));
                add(context, ownMask, activity_context::project(site.features), std::move(allPieces), provenance.merge(sources));
                continue;
            }
            // Additive per-writer primitive features are split by actual member
            // piece. Shared checks/activation retain one interaction site.
            auto common = site.features;
            activity_context::Units perMember{};
            for (const auto &[name, n] : site.features) {
                const auto units = activity_context::project({{name, n}});
                if (n != site.operations.size() || (!units[4] && !units[5])) continue;
                auto unit = activity_context::project({{name, 1}});
                for (std::size_t u = 0; u < unit.size(); ++u) perMember[u] += unit[u];
                common.erase(name);
            }
            if (std::any_of(perMember.begin(), perMember.end(), [](auto v) { return v != 0; }))
                for (auto op : site.operations)
                    add(context, activity.writeMasks.at(op.index), perMember, piecesFor(op), 0);
            add(context, site.mask, activity_context::project(common), std::move(allPieces), 0);
        }
        for (const auto &[key, units] : aggregated) {
            const auto [context, demand, mask, sources] = key;
            result.items.push_back({context, demand, sources, mask, units});
        }
        provenance.writeCauseLinks(out);
        result.roots=std::move(provenance.roots);result.sources=std::move(provenance.sets);
        writeInitialGraph(extract, result, out);
        std::cout<<"ARRIVAL_PROVENANCE roots="<<result.roots.size()<<" source_sets="<<result.sources.size()
                 <<" cycle_edges="<<provenance.cycleEdges<<" unowned_state="<<provenance.unownedStateReferences<<std::endl;
        std::cout << "INITIAL GRAPH COMPLETE items=" << result.items.size()
                  << " unowned=" << unowned << " cross_piece_compute=" << crossPieceCompute
                  << " source_clones=" << clones << " zero_cost=" << emptyZero << std::endl;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
