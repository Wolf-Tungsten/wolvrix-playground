// Replay the same frozen graph with either the old or new simplification library.
#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "transform/simplify.hpp"
#include <fstream>
#include <iostream>
#include <iterator>

int main(int argc, char **argv) {
    using namespace wolvrix::lib;
    try {
        if (argc != 3) throw std::runtime_error("usage: simplify graph.json output.json");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing graph");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SimplifyOptions options;
        options.semantics = transform::ConstantFoldOptions::Semantics::TwoState;
        transform::PassManager manager;
        manager.addPass(std::make_unique<transform::SimplifyPass>(options));
        transform::PassDiagnostics pd;
        const auto result = manager.run(design, pd);
        for (const auto &d : pd.messages()) std::cerr << d.message << '\n';
        if (!result.success || pd.hasError()) throw std::runtime_error("simplify failed");
        store::StoreOptions saved;
        saved.outputFilename = argv[2];
        saved.topOverrides = {"Cv32Bench"};
        if (!store::StoreJson().store(design, saved).success) throw std::runtime_error("store failed");
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
