// Regenerate the flattened XiangShan graph from RTL, optionally running
// accumulate-sink before lane packing. Passes are built through the same
// name/argument factory that the Python flow uses.
#include "core/grh.hpp"
#include "core/ingest.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "slang/analysis/AnalysisManager.h"
#include "slang/ast/Compilation.h"
#include "slang/driver/Driver.h"
#include <chrono>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

using namespace wolvrix::lib;

int main(int argc, char **argv)
{
    try
    {
        if (argc < 6)
            throw std::runtime_error("usage: frontend control|audit|drop|flat output.json report.json top slang-arguments...");
        const std::string mode = argv[1];
        if (mode != "control" && mode != "audit" && mode != "drop" && mode != "flat") throw std::runtime_error("unknown mode");
        const std::string top = argv[4];
        slang::driver::Driver driver;
        driver.addStandardArgs();
        driver.options.singleUnit = true;
        driver.options.compilationFlags.at(slang::ast::CompilationFlags::AllowTopLevelIfacePorts) = true;
        std::vector<const char *> args{"read_sv"};
        for (int i = 5; i < argc; ++i) args.push_back(argv[i]);
        if (!driver.parseCommandLine(static_cast<int>(args.size()), args.data()) || !driver.processOptions() ||
            !driver.parseAllSources())
            throw std::runtime_error("SystemVerilog parsing failed");
        auto compilation = driver.createCompilation();
        driver.runAnalysis(*compilation);
        for (const auto &diag : compilation->getAllDiagnostics())
            if (slang::getDefaultSeverity(diag.code) >= slang::DiagnosticSeverity::Error || diag.isError())
                throw std::runtime_error("slang reported errors");
        std::cerr << "[frontend] elaborated SystemVerilog\n" << std::flush;

        ingest::ConvertOptions convert;
        convert.abortOnError = true;
        convert.enableLogging = true;
        convert.logLevel = LogLevel::Info;
        ingest::ConvertDriver converter(convert);
        grh::Design design = converter.convert(compilation->getRoot());
        converter.diagnostics().flushThreadLocal();
        if (converter.diagnostics().hasError()) throw std::runtime_error("RTL conversion failed");
        std::cerr << "[frontend] converted RTL\n" << std::flush;

        transform::SessionStore session;
        auto run = [&](std::string_view name, std::vector<std::string> arguments, bool keepDeclared) {
            const auto start = std::chrono::steady_clock::now();
            std::cerr << "[frontend] pass " << name << " start\n" << std::flush;
            std::vector<std::string_view> views(arguments.begin(), arguments.end());
            std::string error;
            auto pass = transform::makePass(name, views, error);
            if (!pass) throw std::runtime_error(std::string(name) + ": " + error);
            transform::PassManager manager;
            manager.options().session = &session;
            manager.options().keepDeclaredSymbols = keepDeclared;
            manager.options().logLevel = LogLevel::Info;
            manager.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
                std::cerr << '[' << tag << "] " << message << '\n';
            };
            manager.addPass(std::move(pass));
            transform::PassDiagnostics diagnostics;
            const auto result = manager.run(design, diagnostics);
            if (!result.success || diagnostics.hasError())
            {
                for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
                throw std::runtime_error(std::string(name) + " failed");
            }
            const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
            std::cerr << "[frontend] pass " << name << " done " << ms << "ms\n" << std::flush;
        };
        for (const char *name : {"xmr-resolve", "memory-read-retime", "multidriven-guard", "blackbox-guard",
                                 "latch-transparent-read", "hier-flatten"})
            run(name, {}, true);
        // "flat" stores the graph right after flattening, for offline audits.
        if (mode != "flat")
        {
            if (mode != "control")
                run("accumulate-sink", {std::string("-mode=") + mode, std::string("-report=") + argv[3]}, true);
            run("comb-lane-pack", {"-enable-declared-roots", "false"}, true);
            run("comb-loop-elim", {}, true);
            run("simplify", {"-semantics", "2state"}, false);
            run("simplify", {"-semantics", "2state"}, false);
            run("memory-init-check", {}, true);
        }

        std::cerr << "[frontend] store start\n" << std::flush;
        store::StoreOptions out;
        const std::filesystem::path target(argv[2]);
        out.outputDir = target.parent_path().string();
        out.outputFilename = target.filename().string();
        out.topOverrides = {top};
        if (!store::StoreJson().store(design, out).success) throw std::runtime_error("JSON write failed");
        std::cerr << "[frontend] store done\n" << std::flush;
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
