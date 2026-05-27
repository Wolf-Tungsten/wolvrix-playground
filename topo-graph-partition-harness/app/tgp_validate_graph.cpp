#include "tgp/graph_io.hpp"
#include "tgp/validator.hpp"

#include <iostream>

int main(int argc, char **argv)
{
    std::string graphPath;
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--graph" && i + 1 < argc)
        {
            graphPath = argv[++i];
        }
    }
    if (graphPath.empty())
    {
        std::cerr << "usage: tgp_validate_graph --graph <path>\n";
        return 64;
    }
    try
    {
        tgp::ComputeDag graph = tgp::readComputeDagFile(graphPath);
        const tgp::ValidationResult result = tgp::validateGraph(graph);
        for (const std::string &error : result.errors)
        {
            std::cerr << "error: " << error << "\n";
        }
        if (result.ok)
        {
            std::cout << "ok\n";
            return 0;
        }
        return 1;
    }
    catch (const std::exception &ex)
    {
        std::cerr << "error: " << ex.what() << "\n";
        return 1;
    }
}
