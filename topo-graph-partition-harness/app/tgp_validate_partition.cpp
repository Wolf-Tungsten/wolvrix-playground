#include "tgp/graph_io.hpp"
#include "tgp/validator.hpp"

#include <iostream>

int main(int argc, char **argv)
{
    std::string graphPath;
    std::string partitionPath;
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--graph" && i + 1 < argc)
        {
            graphPath = argv[++i];
        }
        else if (arg == "--partition" && i + 1 < argc)
        {
            partitionPath = argv[++i];
        }
    }
    if (graphPath.empty() || partitionPath.empty())
    {
        std::cerr << "usage: tgp_validate_partition --graph <path> --partition <path>\n";
        return 64;
    }
    try
    {
        tgp::ComputeDag graph = tgp::readComputeDagFile(graphPath);
        tgp::PartitionResult partition = tgp::readPartitionFile(partitionPath);
        const tgp::ValidationResult result = tgp::validatePartition(graph, partition);
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
