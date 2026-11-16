#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "transform/dead_code_elim.hpp"
#include "transform/predicate_set.hpp"
#include <fstream>
#include <iostream>
#include <iterator>

int main(int argc, char **argv) {
    using namespace wolvrix::lib;
    try {
        if (argc != 4 || (std::string_view(argv[3]) != "on" && std::string_view(argv[3]) != "off"))
            throw std::runtime_error("usage: predicate graph.json output.json on|off");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing graph");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::PassManager manager;
        manager.options().logLevel = LogLevel::Info;
        manager.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
            std::cerr << '[' << tag << "] " << message << '\n';
        };
        manager.addPass(std::make_unique<transform::PredicateSetPass>(transform::PredicateSetOptions{std::string_view(argv[3]) == "on"}));
        manager.addPass(std::make_unique<transform::DeadCodeElimPass>());
        transform::PassDiagnostics diagnostics;
        if (!manager.run(design, diagnostics).success || diagnostics.hasError()) {
            for (const auto &d : diagnostics.messages()) std::cerr << d.message << '\n';
            throw std::runtime_error("predicate transform failed");
        }
        store::StoreOptions options; options.outputFilename = argv[2]; options.topOverrides = {"Cv32Bench"};
        if (!store::StoreJson().store(design, options).success) throw std::runtime_error("store failed");
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
