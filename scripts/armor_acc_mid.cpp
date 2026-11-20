// Continue from a stored post-flatten graph: optional accumulate-sink step,
// lane packing, loop elimination, simplification, then store the result.
#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

using namespace wolvrix::lib;

int main(int argc, char **argv)
{
    try
    {
        if (argc != 6) throw std::runtime_error("usage: mid control|drop|keep flat.json output.json report.json top");
        const std::string mode = argv[1];
        if (mode != "control" && mode != "drop" && mode != "keep") throw std::runtime_error("unknown mode");
        std::ifstream input(argv[2]);
        if (!input) throw std::runtime_error("missing input graph");
        std::cerr << "[mid] load start\n" << std::flush;
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        std::cerr << "[mid] load done\n" << std::flush;
        transform::SessionStore session;
        auto run = [&](std::string_view name, std::vector<std::string> arguments, bool keepDeclared) {
            const auto start = std::chrono::steady_clock::now();
            std::cerr << "[mid] pass " << name << " start\n" << std::flush;
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
            for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
            if (!result.success || diagnostics.hasError()) throw std::runtime_error(std::string(name) + " failed");
            const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
            std::cerr << "[mid] pass " << name << " done " << ms << "ms\n" << std::flush;
        };
        if (mode == "drop") run("accumulate-sink", {"-mode=drop", std::string("-report=") + argv[4]}, true);
        if (mode == "keep")
        {
            run("accumulate-sink", {"-mode=audit", std::string("-report=") + argv[4]}, true);
            run("comb-lane-pack", {"-enable-declared-roots", "false", "-skip-accumulate-sinks", "true"}, true);
        }
        else
        {
            run("comb-lane-pack", {"-enable-declared-roots", "false"}, true);
        }
        run("comb-loop-elim", {}, true);
        run("simplify", {"-semantics", "2state"}, false);
        run("simplify", {"-semantics", "2state"}, false);
        run("memory-init-check", {}, true);
        std::cerr << "[mid] store start\n" << std::flush;
        store::StoreOptions out;
        const std::filesystem::path target(argv[3]);
        out.outputDir = target.parent_path().string();
        out.outputFilename = target.filename().string();
        out.topOverrides = {argv[5]};
        if (!store::StoreJson().store(design, out).success) throw std::runtime_error("JSON write failed");
        std::cerr << "[mid] store done\n" << std::flush;
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
