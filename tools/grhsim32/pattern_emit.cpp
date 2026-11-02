// Standalone research fixtures: the normal frontend and emitter, no IR rewrite.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "core/store.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include "transform/memory_write_coalesce.hpp"
#include "transform/reg_to_mem.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>

using namespace wolvrix::lib;

int main(int argc, char **argv) {
    try {
        if (argc != 4 && argc != 5) throw std::runtime_error("usage: pattern_emit input.json top output_directory [raw|postpartition]");
        const std::string profile = argc==5 ? argv[4] : "raw";
        if (profile!="raw" && profile!="postpartition") throw std::runtime_error("unknown normalization profile");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("cannot read input");
        auto design = grh::Design::fromJsonString(
            std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        transform::PassManager manager;
        manager.options().session = &session;
        if (profile=="postpartition") {
            manager.addPass(std::make_unique<transform::MemoryWriteCoalescePass>());
            transform::RegToMemOptions reg;
            reg.enableIntent = false;
            reg.profitabilityFilter = transform::RegToMemProfitabilityPolicy::VerilatorV1;
            manager.addPass(std::make_unique<transform::RegToMemPass>(reg));
        }
        transform::ActivityScheduleOptions schedule;
        schedule.path = argv[2];
        manager.addPass(std::make_unique<transform::ActivitySchedulePass>(schedule));
        transform::PassDiagnostics pd;
        auto result = manager.run(design, pd);
        for (const auto &d : pd.messages()) std::cerr << d.message << '\n';
        if (!result.success || pd.hasError()) throw std::runtime_error("scheduling failed");
        emit::EmitOptions options;
        options.outputDir = argv[3];
        options.topOverrides = {argv[2]};
        options.session = &session;
        options.attributes["waveform"] = "off";
        options.attributes["perf"] = "off";
        options.attributes["emit_parallelism"] = "1";
        emit::EmitDiagnostics ed;
        const auto emitted = emit::EmitGrhSimCpp(&ed).emit(design, options);
        for (const auto &d : ed.messages()) std::cerr << d.message << '\n';
        if (!emitted.success || ed.hasError()) throw std::runtime_error("emission failed");
        store::StoreOptions stored;
        stored.outputFilename = (std::filesystem::path(argv[3])/"normalized.json").string();
        stored.topOverrides = {argv[2]};
        if (!store::StoreJson().store(design,stored).success) throw std::runtime_error("normalized graph store failed");
        std::cout << "PASS " << argv[2] << '\n';
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
