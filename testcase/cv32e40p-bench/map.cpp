// Read-only attribution using the emitter's own execution planner.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <cstdlib>

static std::string csv(std::string_view value) {
    std::string out = "\"";
    for (char c : value) { if (c == '"') out += '"'; out += c; }
    return out + '"';
}
int main(int argc, char **argv) {
    using namespace wolvrix::lib;
    try {
        if (argc != 3 && (argc != 4 || (std::string_view(argv[3]) != "--event-regions" &&
                                      std::string_view(argv[3]) != "--shared-event-regions")))
            throw std::runtime_error("usage: map graph.json output.csv [--event-regions|--shared-event-regions]");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing input");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        transform::PassManager manager;
        manager.options().session = &session;
        transform::ActivityScheduleOptions schedule;
        schedule.path = "Cv32Bench";
        schedule.eventRegions = argc == 4;
        schedule.eventRegionsShared = argc == 4 && std::string_view(argv[3]) == "--shared-event-regions";
        if (const char *path = std::getenv("CV32_SCHEDULE_DAG")) schedule.exportComputeDagPath = path;
        manager.addPass(std::make_unique<transform::ActivitySchedulePass>(schedule));
        transform::PassDiagnostics pd;
        if (!manager.run(design, pd).success || pd.hasError()) throw std::runtime_error("schedule failed");
        emit::EmitOptions options;
        options.topOverrides = {"Cv32Bench"}; options.session = &session;
        options.attributes["waveform"] = "off"; options.attributes["perf"] = "off";
        emit::EmitDiagnostics diagnostics;
        emit::GrhSimExecutionPlan plan;
        if (!emit::EmitGrhSimCpp(&diagnostics).analyzeExecutionPlan(design, options, plan).success)
            throw std::runtime_error("analysis failed");
        std::map<unsigned, unsigned> batchByGroup;
        for (const auto &batch : plan.batches)
            for (const auto &word : batch.words)
                for (auto group : word.groups) batchByGroup[group] = batch.index;
        const auto &graph = *design.findGraph("Cv32Bench");
        std::ofstream out(argv[2]);
        out << "batch,phase,group,op_id,op_kind,op_symbol,value_ids,value_symbols,file,line\n";
        for (const auto &group : plan.groups) {
            for (auto id : group.operations) {
                const auto op = graph.getOperation(id);
                std::string ids, names;
                for (auto value : op.results()) {
                    if (!ids.empty()) { ids += ';'; names += ';'; }
                    ids += std::to_string(value.index); names += graph.getValue(value).symbolText();
                }
                const auto loc = op.srcLoc().value_or(grh::SrcLoc{});
                out << batchByGroup.at(group.supernode) << ','
                    << (group.phase == emit::GrhSimExecutionPlan::Phase::Compute ? "compute" : "commit") << ','
                    << group.supernode << ',' << id.index << ',' << grh::toString(op.kind()) << ','
                    << csv(op.symbolText()) << ',' << csv(ids) << ',' << csv(names) << ','
                    << csv(loc.file) << ',' << loc.line << '\n';
            }
        }
        if (!out) throw std::runtime_error("output failed");
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
