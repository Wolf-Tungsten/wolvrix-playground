#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <cstdlib>

int main(int argc, char **argv) {
    using namespace wolvrix::lib;
    try {
        if (argc != 4) throw std::runtime_error("usage: emit graph.json output off|eval");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing graph");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        transform::PassManager manager;
        manager.options().session = &session;
        manager.options().logLevel = LogLevel::Info;
        manager.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
            std::cerr << '[' << tag << "] " << message << '\n';
        };
        transform::ActivityScheduleOptions schedule;
        schedule.path = "Cv32Bench";
        if (const char *mode = std::getenv("CV32_EVENT_REGIONS")) {
            if (std::string(mode) != "0" && std::string(mode) != "1")
                throw std::runtime_error("CV32_EVENT_REGIONS must be 0 or 1");
            schedule.eventRegions = std::string(mode) == "1";
        }
        if (const char *mode = std::getenv("CV32_EVENT_REGIONS_SHARED")) {
            if (std::string(mode) != "0" && std::string(mode) != "1")
                throw std::runtime_error("CV32_EVENT_REGIONS_SHARED must be 0 or 1");
            schedule.eventRegionsShared = std::string(mode) == "1";
        }
        if (const char *mode = std::getenv("CV32_SHARED_EVENT_REGIONS_COST_GUARD")) {
            if (std::string(mode) != "0" && std::string(mode) != "1")
                throw std::runtime_error("CV32_SHARED_EVENT_REGIONS_COST_GUARD must be 0 or 1");
            schedule.eventRegionsSharedCostGuard = std::string(mode) == "1";
        }
        if (const char *mode = std::getenv("CV32_SHARED_EVENT_REGIONS_CYCLE_REFINEMENT")) {
            if (std::string(mode) != "0" && std::string(mode) != "1")
                throw std::runtime_error("CV32_SHARED_EVENT_REGIONS_CYCLE_REFINEMENT must be 0 or 1");
            schedule.eventRegionsSharedCycleRefinement = std::string(mode) == "1";
        }
        if (const char *mode = std::getenv("CV32_SHARED_EVENT_REGIONS_CONNECTED")) {
            if (std::string(mode) != "0" && std::string(mode) != "1")
                throw std::runtime_error("CV32_SHARED_EVENT_REGIONS_CONNECTED must be 0 or 1");
            schedule.eventRegionsSharedConnected = std::string(mode) == "1";
        }
        manager.addPass(std::make_unique<transform::ActivitySchedulePass>(schedule));
        transform::PassDiagnostics pd;
        auto result = manager.run(design, pd);
        for (const auto &d : pd.messages()) std::cerr << d.message << '\n';
        if (!result.success || pd.hasError()) throw std::runtime_error("schedule failed");
        emit::EmitOptions options;
        options.outputDir = argv[2];
        options.topOverrides = {"Cv32Bench"};
        options.session = &session;
        options.attributes["waveform"] = "off";
        options.attributes["perf"] = argv[3];
        emit::EmitDiagnostics ed;
        auto emitted = emit::EmitGrhSimCpp(&ed).emit(design, options);
        for (const auto &d : ed.messages()) std::cerr << d.message << '\n';
        if (!emitted.success || ed.hasError()) throw std::runtime_error("emit failed");
        store::StoreOptions saved;
        saved.outputFilename = std::string(argv[2]) + "/normalized.json";
        saved.topOverrides = {"Cv32Bench"};
        if (!store::StoreJson().store(design, saved).success) throw std::runtime_error("store failed");
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
