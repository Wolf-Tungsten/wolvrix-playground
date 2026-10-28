#include "core/load.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_repcut_package.hpp"
#include "transform/memory_write_coalesce.hpp"
#include "transform/reg_to_mem.hpp"
#include "transform/repcut.hpp"

#include <filesystem>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

using namespace wolvrix::lib;
using namespace wolvrix::lib::transform;

namespace
{
    std::string readFile(const std::filesystem::path &path)
    {
        std::ifstream stream(path, std::ios::binary);
        if (!stream) throw std::runtime_error("cannot open input JSON: " + path.string());
        return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
    }

    std::vector<uint32_t> readAssignment(const std::filesystem::path &path)
    {
        std::ifstream stream(path);
        if (!stream) throw std::runtime_error("cannot open assignment: " + path.string());
        std::vector<uint32_t> labels;
        uint64_t label = 0;
        while (stream >> label)
        {
            if (label > UINT32_MAX) throw std::runtime_error("assignment label out of range");
            labels.push_back(static_cast<uint32_t>(label));
        }
        if (!stream.eof()) throw std::runtime_error("invalid assignment file");
        return labels;
    }

    void check(bool ok, const std::string &message)
    {
        if (!ok) throw std::runtime_error(message);
    }
}

int main(int argc, char **argv)
{
    if (argc != 6)
    {
        std::cerr << "usage: repcut-grhsim-replay input.json assignment work_dir output.json package_dir\n";
        return 2;
    }
    try
    {
        const std::filesystem::path inputPath = argv[1];
        const auto assignment = readAssignment(argv[2]);
        const std::filesystem::path workDir = argv[3];
        const std::filesystem::path outputJson = argv[4];
        const std::filesystem::path packageDir = argv[5];
        const bool emitOnly = std::getenv("WOLVRIX_REPLAY_EMIT_ONLY") != nullptr;
        std::filesystem::create_directories(workDir);
        std::filesystem::create_directories(outputJson.parent_path());
        std::filesystem::create_directories(packageDir);

        std::cerr << "[replay] loading " << inputPath << "\n" << std::flush;
        auto design = load::LoadJson().load(readFile(inputPath));
        check(!design.topGraphs().empty(), "input JSON has no top graph");
        const std::string top = design.topGraphs().front();
        std::cerr << "[replay] top=" << top << " assignment=" << assignment.size() << "\n" << std::flush;

        if (!emitOnly)
        {
            SessionStore session;
            session.emplace(top + ".repcut.replay_assignment",
                            std::make_unique<SessionSlotValue<RepcutReplayAssignment>>(
                                RepcutReplayAssignment{assignment}));
            PassManager manager;
            manager.options().session = &session;
            manager.options().verbosity = PassVerbosity::Info;
            manager.options().logLevel = LogLevel::Info;
            RepcutOptions partition;
            partition.path = top;
            partition.partitionCount = 32;
            partition.imbalanceFactor = 0.015;
            partition.workDir = workDir.string();
            partition.partitioner = "assignment-replay";
            partition.mtKaHyParPreset = "deterministic-quality";
            partition.weightMode = RepcutWeightMode::kClosureAware;
            partition.costModel = RepcutCostModel::kGrhsimV1;
            partition.keepIntermediateFiles = true;
            manager.addPass(std::make_unique<RepcutPass>(partition));
            manager.addPass(std::make_unique<MemoryWriteCoalescePass>());
            RegToMemOptions regOptions;
            regOptions.enableIntent = false;
            regOptions.profitabilityFilter = RegToMemProfitabilityPolicy::None;
            manager.addPass(std::make_unique<RegToMemPass>(regOptions));
            PassDiagnostics passDiagnostics;
            const auto passResult = manager.run(design, passDiagnostics);
            for (const auto &message : passDiagnostics.messages())
                std::cerr << message.message << '\n';
            check(passResult.success, "replay transform pipeline failed");

            store::StoreJson store;
            store::StoreOptions storeOptions;
            storeOptions.outputFilename = outputJson.string();
            storeOptions.topOverrides = {top};
            const auto storeResult = store.store(design, storeOptions);
            check(storeResult.success, "partitioned JSON store failed");
        }

        emit::EmitGrhSimRepCutPackage emitter;
        emit::EmitOptions emitOptions;
        emitOptions.outputDir = packageDir.string();
        emitOptions.topOverrides = {top};
        emit::EmitDiagnostics emitDiagnostics;
        // The package emitter owns the planner/emission pipeline for the
        // homogeneous GrhSIM worker package; no Verilator path is touched.
        emit::EmitGrhSimRepCutPackage packageEmitter(&emitDiagnostics);
        const auto emitResult = packageEmitter.emit(design, emitOptions);
        for (const auto &message : emitDiagnostics.messages())
            std::cerr << message.message << '\n';
        check(emitResult.success, "GrhSIM package emission failed");
        std::cerr << "[replay] PASS package=" << packageDir << '\n';
    }
    catch (const std::exception &error)
    {
        std::cerr << "[replay] FAIL " << error.what() << '\n';
        return 1;
    }
    return 0;
}
