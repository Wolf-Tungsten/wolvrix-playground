// Replay one frozen, flattened XiangShan graph with the pre/post-CV32 libraries.
// Compile against each library's own headers: ActivityScheduleOptions changed ABI.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include "transform/reg_to_mem.hpp"
#include "transform/simplify.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

using namespace wolvrix::lib;

#ifndef XS_ABLATE_SHARED
#define XS_ABLATE_SHARED 0
#endif
#ifndef XS_ABLATE_CONES
#define XS_ABLATE_CONES 0
#endif
#ifndef XS_SHARED_EVENT_REGIONS_COST_GUARD
#define XS_SHARED_EVENT_REGIONS_COST_GUARD 0
#endif

int main(int argc, char **argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: emit pre_reg_to_mem.json output");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing input graph");
        std::cerr << "[replay] load frozen graph\n" << std::flush;
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        auto run = [&](std::unique_ptr<transform::Pass> pass, const char *label) {
            std::cerr << "[replay] " << label << " start\n" << std::flush;
            transform::PassManager manager;
            manager.options().session = &session;
            if (std::string(label) == "simplify") manager.options().keepDeclaredSymbols = false;
            manager.options().logLevel = LogLevel::Info;
            manager.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
                std::cerr << '[' << tag << "] " << message << '\n';
            };
            manager.addPass(std::move(pass));
            transform::PassDiagnostics diagnostics;
            auto result = manager.run(design, diagnostics);
            for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
            if (!result.success || diagnostics.hasError()) throw std::runtime_error(label);
            std::cerr << "[replay] " << label << " done\n" << std::flush;
        };
        transform::SimplifyOptions simplify;
        simplify.semantics = transform::ConstantFoldOptions::Semantics::TwoState;
        run(std::make_unique<transform::SimplifyPass>(simplify), "simplify");
        transform::RegToMemOptions memory;
        memory.enableOrderedWrites = true;
        run(std::make_unique<transform::RegToMemPass>(memory), "reg-to-mem");
        transform::ActivityScheduleOptions schedule;
        schedule.path = "SimTop";
        schedule.maxOpInComputeSupernode = 108;
        schedule.maxOpInComputeNode = 108;
        schedule.splitOversizeComputeNodes = true;
        schedule.splitOversizeComputeNodeMaxOps = 108;
#if XS_CV32_OPTIMIZED
        // Event regions require whole compute nodes; the existing XiangShan
        // scheduler otherwise splits oversized nodes into different groups.
        schedule.splitOversizeComputeNodes = false;
        schedule.eventRegions = true;
        schedule.eventRegionsShared = !XS_ABLATE_SHARED;
#if XS_SHARED_EVENT_REGIONS_CONNECTED
        schedule.eventRegionsSharedConnected = true;
#endif
#if XS_SHARED_EVENT_REGIONS_CYCLE_REFINEMENT
        schedule.eventRegionsSharedCycleRefinement = true;
#endif
#if XS_SHARED_EVENT_REGIONS_COST_GUARD
        schedule.eventRegionsSharedCostGuard = true;
#endif
#endif
        run(std::make_unique<transform::ActivitySchedulePass>(schedule), "activity-schedule");
        emit::EmitOptions options;
        options.outputDir = argv[2];
        options.topOverrides = {"SimTop"};
        options.session = &session;
        options.attributes = {{"waveform", "off"}, {"perf", "off"},
            {"sched_batch_max_ops", "2048"}, {"sched_batch_max_estimated_lines", "8192"},
            {"sched_batch_target_count", "64"}, {"sched_batches_per_cpp", "1"},
            {"emit_parallelism", "4"}};
#if XS_CV32_OPTIMIZED
        for (const auto *name : {"conditional_mux_cones", "shared_equality_families",
                 "conditional_mux_input_cache", "covered_state_view_notifications",
                 "covered_state_view_inline", "covered_state_view_composition",
                 "covered_state_view_composition_inline"}) options.attributes[name] = "true";
#endif
#if XS_CROSS_REGION_STATE_VIEWS
        options.attributes["covered_state_view_cross_region"] = "true";
#endif
#if XS_ABLATE_CONES
        options.attributes["conditional_mux_cones"] = "false";
        options.attributes["conditional_mux_input_cache"] = "false";
#endif
        std::cerr << "[replay] emit start\n" << std::flush;
        emit::EmitDiagnostics diagnostics;
        auto result = emit::EmitGrhSimCpp(&diagnostics).emit(design, options);
        for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
        if (!result.success || diagnostics.hasError()) throw std::runtime_error("emit failed");
        std::cerr << "[replay] emit done\n" << std::flush;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
