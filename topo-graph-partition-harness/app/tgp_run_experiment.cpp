#include "tgp/experiment.hpp"

#include <iostream>
#include <string>

int main(int argc, char **argv)
{
    tgp::ExperimentOptions options;
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--algorithm" && i + 1 < argc)
        {
            options.algorithmName = argv[++i];
        }
        else if (arg == "--graph" && i + 1 < argc)
        {
            options.graphPath = argv[++i];
        }
        else if (arg == "--config" && i + 1 < argc)
        {
            options.configPath = argv[++i];
        }
        else if (arg == "--out-dir" && i + 1 < argc)
        {
            options.outDir = argv[++i];
        }
        else if (arg == "--time-limit-sec" && i + 1 < argc)
        {
            options.timeLimitSec = static_cast<uint32_t>(std::stoul(argv[++i]));
        }
    }
    if (options.algorithmName.empty() || options.graphPath.empty() || options.outDir.empty())
    {
        std::cerr << "usage: tgp_run_experiment --algorithm <name> --graph <path> --config <path> --out-dir <dir> [--time-limit-sec <n>]\n";
        return 64;
    }
    std::string error;
    const int rc = tgp::runExperiment(options, error);
    if (rc != 0)
    {
        std::cerr << "error: " << error << "\n";
    }
    return rc;
}
