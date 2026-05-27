#include "tgp/graph_io.hpp"
#include "tgp/oracle.hpp"

#include <iostream>

int main(int argc, char **argv)
{
    std::string graphPath;
    std::string outPath;
    tgp::OracleOptions options;
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--graph" && i + 1 < argc)
        {
            graphPath = argv[++i];
        }
        else if (arg == "--max-nodes-per-part" && i + 1 < argc)
        {
            options.maxNodesPerPart = static_cast<uint32_t>(std::stoul(argv[++i]));
        }
        else if (arg == "--threads" && i + 1 < argc)
        {
            options.threads = static_cast<uint32_t>(std::stoul(argv[++i]));
        }
        else if (arg == "--prefix-depth" && i + 1 < argc)
        {
            options.prefixDepth = static_cast<uint32_t>(std::stoul(argv[++i]));
        }
        else if (arg == "--time-limit-sec" && i + 1 < argc)
        {
            options.timeLimitSec = static_cast<uint64_t>(std::stoull(argv[++i]));
        }
        else if (arg == "--checkpoint-interval-sec" && i + 1 < argc)
        {
            options.checkpointIntervalSec = static_cast<uint64_t>(std::stoull(argv[++i]));
        }
        else if (arg == "--checkpoint" && i + 1 < argc)
        {
            options.checkpointPath = argv[++i];
        }
        else if (arg == "--resume" && i + 1 < argc)
        {
            options.resumePath = argv[++i];
        }
        else if (arg == "--out" && i + 1 < argc)
        {
            outPath = argv[++i];
        }
    }
    if (graphPath.empty())
    {
        std::cerr << "usage: tgp_oracle --graph <path> [--max-nodes-per-part <n>] [--threads <n>] "
                     "[--prefix-depth <n>] "
                     "[--time-limit-sec <n>] [--checkpoint-interval-sec <n>] "
                     "[--checkpoint <path>] [--resume <path>] [--out <path>]\n";
        return 64;
    }
    try
    {
        tgp::ComputeDag graph = tgp::readComputeDagFile(graphPath);
        const std::string json = tgp::oracleToJson(tgp::runOracle(graph, options));
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
