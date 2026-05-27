#include "tgp/graph_io.hpp"
#include "tgp/scorer.hpp"

#include <iostream>

int main(int argc, char **argv)
{
    std::string graphPath;
    std::string partitionPath;
    std::string outPath;
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
        else if (arg == "--out" && i + 1 < argc)
        {
            outPath = argv[++i];
        }
    }
    if (graphPath.empty() || partitionPath.empty())
    {
        std::cerr << "usage: tgp_score_partition --graph <path> --partition <path> [--out <path>]\n";
        return 64;
    }
    try
    {
        tgp::ComputeDag graph = tgp::readComputeDagFile(graphPath);
        tgp::PartitionResult partition = tgp::readPartitionFile(partitionPath);
        const std::string json = tgp::scoreToJson(tgp::scorePartition(graph, partition));
        if (outPath.empty())
        {
            std::cout << json;
        }
        else
        {
            tgp::writeTextFile(outPath, json);
        }
        return 0;
    }
    catch (const std::exception &ex)
    {
        std::cerr << "error: " << ex.what() << "\n";
        return 1;
    }
}
