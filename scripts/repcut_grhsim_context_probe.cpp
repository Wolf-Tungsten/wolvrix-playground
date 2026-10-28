// Pre-assignment actual-lowering template; no emitted or compiled code input.
#include "repcut_grhsim_assignment_extract.hpp"
#include "emit/grhsim_activity_model.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include "repcut_grhsim_context_cost.hpp"
#include "repcut_grhsim_context_consumers.hpp"
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
        {
            RepcutAssignmentEvaluator normalized(extract.model);
            writeModel(normalized.model(), out / "source_model.txtdata");
        }
        std::cout << "CONTEXT RAW MODEL SERIALIZED" << std::endl;
        std::vector<uint32_t> nodePiece(extract.a.nodeToOp.size(), UINT32_MAX);
        for (uint32_t p = 0; p < extract.b.pieces.size(); ++p)
            for (auto n : extract.b.pieces[p]) nodePiece[n] = p;
        constexpr std::string_view originAttr = "__grhsim_context_origin";
        for (uint32_t n = 0; n < extract.a.nodeToOp.size(); ++n) {
            if (graph.getOperation(extract.a.nodeToOp[n]).attr(originAttr)) throw std::runtime_error("origin attribute collision");
            graph.setAttr(extract.a.nodeToOp[n], originAttr, static_cast<int64_t>(n));
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
        const auto activity = analyzeGrhSimActivity(graph, plan, seeds, GrhSimActivityOptions{});
        const auto attributed = attributeGrhSimWork(plan, activity);
        if (!attributed.unattributedFeatures.empty() || attributed.summary.unmodeledCommitBodies ||
            attributed.summary.unmodeledComputeGroups || !plan.unmodeledCommitWrites.empty())
            throw std::runtime_error("uncovered backend work");
        std::cout << "CONTEXT ATTRIBUTED sites=" << attributed.sites.size() << std::endl;

        activity_context::Model result; result.atoms = extract.model.atomCount;
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
        using Key = std::tuple<uint32_t, uint32_t, uint64_t>;
        std::map<Key, activity_context::Units> aggregated;
        std::map<std::string, uint64_t> sourceFeatures;
        // Research-only backend shape export.  These are generic lowering
        // features, rather than module/signal names: spread them back to the
        // source ASCs so a future allocator can consume an assignment-
        // independent proxy.  Keep the dimensions explicit and compact; the
        // full source feature ledger remains source_features.csv.
        const std::vector<std::string> shapeFeatures = {
            "compute.constant.wide_temporary",
            "compute.wide.concat_destination_words",
            "compute.wide.concat_source_words",
            "compute.wide.concat_wordwise",
            "compute.wide.helper.cross_word_merges",
            "compute.wide.helper.index_normalizations",
            "compute.wide.helper.kAdd",
            "compute.wide.helper.kAnd",
            "compute.wide.helper.kAssign",
            "compute.wide.helper.kConcat",
            "compute.wide.helper.kEq",
            "compute.wide.helper.kLShr",
            "compute.wide.helper.kMux",
            "compute.wide.helper.kNot",
            "compute.wide.helper.kOr",
            "compute.wide.helper.kReduceAnd",
            "compute.wide.helper.kReduceOr",
            "compute.wide.helper.kReduceXor",
            "compute.wide.helper.kReplicate",
            "compute.wide.helper.kShl",
            "compute.wide.helper.kSliceArray",
            "compute.wide.helper.kSliceDynamic",
            "compute.wide.helper.kSliceStatic",
            "compute.wide.helper.kSub",
            "compute.wide.helper.kXor",
            "compute.wide.helper.reduce_word_iterations",
            "compute.wide.helper.replication_lanes",
            "compute.wide.helper_cross_word_merges",
            "compute.wide.helper_operand_words",
            "compute.wide.helper_output_words",
            "compute.wide.helper_word_iterations",
            "compute.wide.operand_words",
            "compute.wide.packed_lane_concat",
            "compute.wide.packed_lane_slice",
            "compute.wide.result.change_detect",
            "compute.wide.result.materialized",
            "compute.wide.result.temporary",
            "compute.wide.result.untracked_store",
            "compute.wide.result_words",
            "compute.wide.to_scalar_result",
        };
        std::unordered_map<std::string, std::size_t> shapeIndex;
        for (std::size_t i = 0; i < shapeFeatures.size(); ++i) shapeIndex.emplace(shapeFeatures[i], i);
        std::vector<uint64_t> atomShape(extract.model.atomCount * shapeFeatures.size(), 0);
        std::vector<uint64_t> unownedShape(shapeFeatures.size(), 0);
        uint64_t shapeSites = 0, shapeAtoms = 0;
        const auto add = [&](uint32_t context, uint64_t mask, const activity_context::Units &units,
                             std::vector<uint32_t> pieces) {
            const auto demand = internDemand(std::move(pieces));
            if (demand == UINT32_MAX) { ++unowned; return; }
            if (!mask && std::all_of(units.begin(), units.end(), [](auto v) { return !v; })) { ++emptyZero; return; }
            auto &target = aggregated[{context, demand, mask}];
            for (std::size_t u = 0; u < units.size(); ++u) target[u] += units[u];
        };
        using Kind = GrhSimAttributedWorkReport::Site::Kind;
        for (const auto &site : attributed.sites) {
            const auto context = contextIds.at(site.supernode);
            for (const auto &[name, n] : site.features) sourceFeatures[name] += n;
            std::vector<uint32_t> allPieces;
            uint64_t ownMask = 0;
            for (auto op : site.operations) {
                const auto pieces = piecesFor(op);
                allPieces.insert(allPieces.end(), pieces.begin(), pieces.end());
                ownMask |= activity.operationMasks.at(op.index);
            }
            sortUnique(allPieces);
            std::vector<uint32_t> allAtoms;
            for (const auto piece : allPieces) {
                const auto &atoms = extract.model.pieces.at(piece).atoms;
                allAtoms.insert(allAtoms.end(), atoms.begin(), atoms.end());
            }
            sortUnique(allAtoms);
            bool hasShape = false;
            for (const auto &[name, n] : site.features) {
                const auto it = shapeIndex.find(name);
                if (it == shapeIndex.end() || !n) continue;
                hasShape = true;
                if (allAtoms.empty()) {
                    unownedShape[it->second] += n;
                    continue;
                }
                const auto q = n / allAtoms.size();
                const auto r = n % allAtoms.size();
                for (std::size_t i = 0; i < allAtoms.size(); ++i)
                    atomShape[static_cast<std::size_t>(allAtoms[i]) * shapeFeatures.size() + it->second]
                        += q + (i < r);
            }
            if (hasShape) {
                ++shapeSites;
                shapeAtoms += allAtoms.size();
            }
            if (site.kind == Kind::Compute) {
                crossPieceCompute += allPieces.size() > 1;
                add(context, ownMask, activity_context::project(site.features), std::move(allPieces));
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
                    add(context, activity.writeMasks.at(op.index), perMember, piecesFor(op));
            add(context, site.mask, activity_context::project(common), std::move(allPieces));
        }
        // Check full source-feature attribution even for metadata not projected
        // into a primitive cost. Coverage is not confused with zero runtime.
        std::map<std::string, uint64_t> expected;
        for (const auto &[mask, features] : attributed.summary.conditionalFeatures)
            for (const auto &[name, n] : features) expected[name] += n;
        if (sourceFeatures != expected) throw std::runtime_error("backend source-feature attribution not conserved");
        for (const auto &[key, units] : aggregated) {
            const auto [context, demand, mask] = key;
            result.items.push_back({context, demand, mask, units});
        }
        std::ofstream file(out / "contexts.txtdata");
        file << "grhsim-context-cost-v1 " << result.atoms << ' ' << result.compute.size() << ' '
             << result.demands.size() << ' ' << result.items.size() << '\n';
        for (bool compute : result.compute) file << compute << ' '; file << '\n';
        for (const auto &d : result.demands) { file << d.size(); for (auto p : d) file << ' ' << p; file << '\n'; }
        for (const auto &item : result.items) {
            file << item.context << ' ' << item.demand << ' ' << item.mask;
            for (auto u : item.units) file << ' ' << u; file << '\n';
        }
        if (!file) throw std::runtime_error("context output failed");
        std::ofstream metadata(out / "coverage.txt");
        metadata << "atoms=" << result.atoms << "\npieces=" << extract.model.pieces.size()
                 << "\ncontexts=" << result.compute.size() << "\nitems=" << result.items.size()
                 << "\nsource_clones=" << clones << "\nunowned_records=" << unowned
                 << "\ncross_piece_compute_sites=" << crossPieceCompute
                 << "\nzero_cost_zero_mask_records=" << emptyZero
                 << "\nraw_source_features_conserved=true\nassignment_dependent_replan_required=true\n";
        std::ofstream featureFile(out / "source_features.csv"); featureFile << "feature,count,projected_axis\n";
        for (const auto &[name, n] : sourceFeatures) {
            featureFile << name << ',' << n << ',';
            const auto units = activity_context::project({{name, n}});
            for (std::size_t u = 0; u < units.size(); ++u) if (units[u]) featureFile << u << ';';
            featureFile << '\n';
        }
        std::ofstream atomFeatureFile(out / "atom_backend_features.csv");
        atomFeatureFile << "atom,feature,count\n";
        uint64_t atomFeatureRows = 0;
        for (uint32_t atom = 0; atom < extract.model.atomCount; ++atom)
            for (std::size_t i = 0; i < shapeFeatures.size(); ++i) {
                const auto n = atomShape[static_cast<std::size_t>(atom) * shapeFeatures.size() + i];
                if (!n) continue;
                atomFeatureFile << atom << ',' << shapeFeatures[i] << ',' << n << '\n';
                ++atomFeatureRows;
            }
        if (!atomFeatureFile) throw std::runtime_error("atom backend feature output failed");
        std::ofstream atomFeatureMeta(out / "atom_backend_features.txt");
        atomFeatureMeta << "feature_schema=generic_backend_lowering_shape_v1\n"
                        << "shape_features=" << shapeFeatures.size() << '\n'
                        << "shape_sites=" << shapeSites << '\n'
                        << "shape_atom_memberships=" << shapeAtoms << '\n'
                        << "atom_feature_rows=" << atomFeatureRows << '\n';
        for (std::size_t i = 0; i < shapeFeatures.size(); ++i)
            atomFeatureMeta << shapeFeatures[i] << ",unowned," << unownedShape[i] << '\n';
        std::cout << "BACKEND CONTEXT EXTRACTION PASS items=" << result.items.size()
                  << " unowned=" << unowned << " cross_piece_compute=" << crossPieceCompute
                  << " shape_rows=" << atomFeatureRows << std::endl;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
