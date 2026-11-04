#include "core/grh.hpp"
#include "core/ingest.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "transform/xmr_resolve.hpp"
#include "transform/memory_read_retime.hpp"
#include "transform/multidriven_guard.hpp"
#include "transform/blackbox_guard.hpp"
#include "transform/latch_transparent_read.hpp"
#include "transform/hier_flatten.hpp"
#include "transform/comb_lane_pack.hpp"
#include "transform/comb_loop_elim.hpp"
#include "transform/simplify.hpp"
#include "transform/memory_init_check.hpp"
#include "slang/driver/Driver.h"
#include "slang/ast/Compilation.h"
#include "slang/analysis/AnalysisManager.h"
#include <iostream>
#include <memory>
#include <thread>

using namespace wolvrix::lib;
using namespace wolvrix::lib::transform;

int main(int argc, char **argv)
{
    try
    {
        if (argc < 4) throw std::runtime_error("usage: frontend output.json top [slang arguments...]");
        slang::driver::Driver driver;
        driver.addStandardArgs();
        driver.options.singleUnit = true;
        driver.options.compilationFlags.at(slang::ast::CompilationFlags::AllowTopLevelIfacePorts) = true;
        std::vector<const char *> args{argv[0], "--top", argv[2]};
        for (int i = 3; i < argc; ++i) args.push_back(argv[i]);
        if (!driver.parseCommandLine(args.size(), args.data()) || !driver.processOptions() || !driver.parseAllSources())
            throw std::runtime_error("SystemVerilog parsing failed");
        auto compilation = driver.createCompilation();
        driver.runAnalysis(*compilation);
        driver.reportCompilation(*compilation, true);
        if (!driver.reportDiagnostics(true)) throw std::runtime_error("SystemVerilog compilation failed");
        std::cerr << "[frontend] elaborated SystemVerilog\n" << std::flush;
        ingest::ConvertOptions options;
        options.threadCount = std::max(1u, std::thread::hardware_concurrency());
        options.enableLogging = true;
        options.logLevel = LogLevel::Info;
        ingest::ConvertDriver converter(options);
        auto design = [&]() {
            try { return converter.convert(compilation->getRoot()); }
            catch (...) {
                converter.diagnostics().flushThreadLocal();
                for (const auto& d : converter.diagnostics().messages()) std::cerr << d.message << '\n';
                throw;
            }
        }();
        converter.diagnostics().flushThreadLocal();
        if (converter.diagnostics().hasError()) throw std::runtime_error("RTL conversion failed");
        std::cerr << "[frontend] converted RTL; lowering graph\n" << std::flush;
        PassManager passes;
        SessionStore session;
        passes.options().session = &session;
        passes.options().logLevel = LogLevel::Info;
        passes.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
            std::cerr << '[' << tag << "] " << message << '\n' << std::flush;
        };
        passes.addPass(std::make_unique<XmrResolvePass>());
        passes.addPass(std::make_unique<MemoryReadRetimePass>());
        passes.addPass(std::make_unique<MultiDrivenGuardPass>());
        passes.addPass(std::make_unique<BlackboxGuardPass>());
        passes.addPass(std::make_unique<LatchTransparentReadPass>());
        passes.addPass(std::make_unique<HierFlattenPass>());
        CombLanePackOptions packing;
        packing.enableDeclaredRoots = false;
        passes.addPass(std::make_unique<CombLanePackPass>(packing));
        passes.addPass(std::make_unique<CombLoopElimPass>());
        SimplifyOptions simplify;
        simplify.semantics = ConstantFoldOptions::Semantics::TwoState;
        passes.addPass(std::make_unique<SimplifyPass>(simplify));
        passes.addPass(std::make_unique<MemoryInitCheckPass>());
        PassDiagnostics diagnostics;
        if (!passes.run(design, diagnostics).success) throw std::runtime_error("RTL lowering failed");
        std::cerr << "[frontend] storing lowered graph\n" << std::flush;
        store::StoreOptions store;
        store.outputFilename = argv[1];
        store.topOverrides = {argv[2]};
        if (!store::StoreJson().store(design, store).success) throw std::runtime_error("JSON write failed");
        std::cout << "GENERATED " << argv[1] << '\n';
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
