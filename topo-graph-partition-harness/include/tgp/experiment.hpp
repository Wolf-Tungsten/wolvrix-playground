#ifndef TGP_EXPERIMENT_HPP
#define TGP_EXPERIMENT_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace tgp
{
    struct ExperimentOptions
    {
        std::string algorithmName;
        std::string graphPath;
        std::string configPath;
        std::string outDir;
        uint32_t timeLimitSec = 0;
    };

    int runExperiment(const ExperimentOptions &options, std::string &error);
}

#endif
