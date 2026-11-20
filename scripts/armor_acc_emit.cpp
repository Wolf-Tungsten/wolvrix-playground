// Emit one XiangShan model from a stored graph with the current library.
// `control` replays the frozen pipeline; `bank` rewrites accumulate-sink
// registers into the accumulate bank right before scheduling; `rewrite` stops
// after that rewrite and only writes its report.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/accumulate_sink.hpp"
#include "transform/activity_schedule.hpp"
#include "transform/reg_to_mem.hpp"
#include "transform/simplify.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

using namespace wolvrix::lib;

int main(int argc, char **argv) {
    try {
        if (argc != 5) throw std::runtime_error("usage: emit control|bank|rewrite graph.json output-dir report.json");
        const std::string mode = argv[1];
        if (mode != "control" && mode != "bank" && mode != "rewrite") throw std::runtime_error("unknown mode");
        std::ifstream input(argv[2]);
        if (!input) throw std::runtime_error("missing input graph");
        std::cerr << "[emit] load graph\n" << std::flush;
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        auto run = [&](std::unique_ptr<transform::Pass> pass, const char *label) {
            std::cerr << "[emit] " << label << " start\n" << std::flush;
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
            std::cerr << "[emit] " << label << " done\n" << std::flush;
        };
        transform::SimplifyOptions simplify;
        simplify.semantics = transform::ConstantFoldOptions::Semantics::TwoState;
        run(std::make_unique<transform::SimplifyPass>(simplify), "simplify");
        transform::RegToMemOptions memory;
        memory.enableOrderedWrites = true;
        run(std::make_unique<transform::RegToMemPass>(memory), "reg-to-mem");
        if (mode != "control") {
            transform::AccumulateSinkOptions bank;
            bank.mode = transform::AccumulateSinkOptions::Mode::Bank;
            bank.reportPath = argv[4];
            run(std::make_unique<transform::AccumulateSinkPass>(bank), "accumulate-sink");
            if (mode == "rewrite") return 0;
        }
        transform::ActivityScheduleOptions schedule;
        schedule.path = "SimTop";
        schedule.maxOpInComputeSupernode = 108;
        schedule.maxOpInComputeNode = 108;
        schedule.splitOversizeComputeNodeMaxOps = 108;
        // Same settings as the frozen driver of the previous round.
        schedule.splitOversizeComputeNodes = false;
        schedule.eventRegions = true;
        schedule.eventRegionsShared = true;
        schedule.eventRegionsSharedConnected = true;
        run(std::make_unique<transform::ActivitySchedulePass>(schedule), "activity-schedule");
        emit::EmitOptions options;
        options.outputDir = argv[3];
        options.topOverrides = {"SimTop"};
        options.session = &session;
        options.attributes = {{"waveform", "off"}, {"perf", "off"},
            {"sched_batch_max_ops", "2048"}, {"sched_batch_max_estimated_lines", "8192"},
            {"sched_batch_target_count", "64"}, {"sched_batches_per_cpp", "1"},
            {"emit_parallelism", "4"}};
        for (const auto *name : {"conditional_mux_cones", "shared_equality_families",
                 "conditional_mux_input_cache", "covered_state_view_notifications",
                 "covered_state_view_inline", "covered_state_view_composition",
                 "covered_state_view_composition_inline"}) options.attributes[name] = "true";
        std::cerr << "[emit] emit start\n" << std::flush;
        emit::EmitDiagnostics diagnostics;
        auto result = emit::EmitGrhSimCpp(&diagnostics).emit(design, options);
        for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
        if (!result.success || diagnostics.hasError()) throw std::runtime_error("emit failed");
        std::cerr << "[emit] emit done\n" << std::flush;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
