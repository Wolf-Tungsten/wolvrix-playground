// Run the accumulate-sink audit on a stored graph and write its report.
#include "core/grh.hpp"
#include "core/transform.hpp"
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
        if (argc != 3) throw std::runtime_error("usage: audit graph.json report.json");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing input graph");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        const std::string report = std::string("-report=") + argv[2];
        const std::vector<std::string_view> args{"-mode=audit", report};
        std::string error;
        auto pass = transform::makePass("accumulate-sink", args, error);
        if (!pass) throw std::runtime_error(error);
        transform::PassManager manager;
        manager.options().logLevel = LogLevel::Info;
        manager.options().logSink = [](LogLevel, std::string_view tag, std::string_view message) {
            std::cerr << '[' << tag << "] " << message << '\n';
        };
        manager.addPass(std::move(pass));
        transform::PassDiagnostics diagnostics;
        const auto result = manager.run(design, diagnostics);
        for (const auto &d : diagnostics.messages()) std::cout << d.message << '\n';
        if (!result.success || diagnostics.hasError()) throw std::runtime_error("audit failed");
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
