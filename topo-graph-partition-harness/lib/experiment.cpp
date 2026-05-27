#include "tgp/experiment.hpp"

#include "tgp/algorithm.hpp"
#include "tgp/graph_io.hpp"
#include "tgp/scorer.hpp"
#include "tgp/validator.hpp"

#include <chrono>
#include <csignal>
#include <filesystem>
#include <sstream>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <sstream>

namespace tgp
{
    namespace
    {
        constexpr int kTimeoutExitCode = 4;

        std::string validationToText(const ValidationResult &result)
        {
            std::ostringstream out;
            out << (result.ok ? "ok" : "failed") << "\n";
            for (const std::string &error : result.errors)
            {
                out << "error: " << error << "\n";
            }
            for (const std::string &warning : result.warnings)
            {
                out << "warning: " << warning << "\n";
            }
            return out.str();
        }

        std::string buildRunLog(const ExperimentOptions &options,
                                std::string_view status,
                                std::string_view validation,
                                std::string_view detail = {})
        {
            std::ostringstream log;
            log << "# tgp_run_experiment\n\n";
            log << "- algorithm: " << options.algorithmName << "\n";
            log << "- graph: " << options.graphPath << "\n";
            if (!options.configPath.empty())
            {
                log << "- config: " << options.configPath << "\n";
            }
            if (options.timeLimitSec != 0)
            {
                log << "- time_limit_sec: " << options.timeLimitSec << "\n";
            }
            log << "- status: " << status << "\n";
            if (status == "ok")
            {
                log << "- result: result.json\n";
                log << "- score: score.json\n";
            }
            log << "- validation: " << validation << "\n";
            if (!detail.empty())
            {
                log << "- detail: " << detail << "\n";
            }
            return log.str();
        }

        PartitionResult runAlgorithm(const ComputeDag &graph,
                                     const AlgorithmConfig &config,
                                     const ExperimentOptions &options)
        {
            std::unique_ptr<PartitionAlgorithm> algorithm = createAlgorithm(options.algorithmName);
            return algorithm->run(graph, config);
        }

        int runAlgorithmWithTimeout(const ComputeDag &graph,
                                    const AlgorithmConfig &config,
                                    const ExperimentOptions &options,
                                    PartitionResult &partition,
                                    std::string &error)
        {
            if (options.timeLimitSec == 0)
            {
                partition = runAlgorithm(graph, config, options);
                return 0;
            }

            const std::filesystem::path outDir(options.outDir);
            const std::filesystem::path resultPath = outDir / "result.tmp.json";
            const std::filesystem::path errorPath = outDir / "algorithm.error.txt";
            std::error_code ec;
            std::filesystem::remove(resultPath, ec);
            std::filesystem::remove(errorPath, ec);

            const pid_t child = fork();
            if (child < 0)
            {
                throw std::runtime_error("failed to fork experiment subprocess");
            }
            if (child == 0)
            {
                try
                {
                    PartitionResult childPartition = runAlgorithm(graph, config, options);
                    writeTextFile(resultPath.string(), partitionToJson(childPartition));
                    _exit(0);
                }
                catch (const std::exception &ex)
                {
                    writeTextFile(errorPath.string(), ex.what());
                    _exit(1);
                }
            }

            const auto start = std::chrono::steady_clock::now();
            int status = 0;
            while (true)
            {
                const pid_t waitResult = waitpid(child, &status, WNOHANG);
                if (waitResult == child)
                {
                    break;
                }
                if (waitResult < 0)
                {
                    throw std::runtime_error("waitpid failed for experiment subprocess");
                }

                const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                    std::chrono::steady_clock::now() - start);
                if (elapsed.count() >= static_cast<long long>(options.timeLimitSec))
                {
                    kill(child, SIGKILL);
                    waitpid(child, &status, 0);
                    error = "algorithm timed out after " + std::to_string(options.timeLimitSec) + " seconds";
                    std::filesystem::remove(resultPath, ec);
                    std::filesystem::remove(errorPath, ec);
                    return kTimeoutExitCode;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }

            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
            {
                if (std::filesystem::exists(errorPath))
                {
                    error = readTextFile(errorPath.string());
                    std::filesystem::remove(errorPath, ec);
                }
                else if (WIFSIGNALED(status))
                {
                    error = "algorithm subprocess terminated by signal " + std::to_string(WTERMSIG(status));
                }
                else
                {
                    error = "algorithm subprocess failed";
                }
                std::filesystem::remove(resultPath, ec);
                return 1;
            }

            partition = readPartitionFile(resultPath.string());
            std::filesystem::remove(resultPath, ec);
            std::filesystem::remove(errorPath, ec);
            return 0;
        }
    }

    int runExperiment(const ExperimentOptions &options, std::string &error)
    {
        try
        {
            std::filesystem::create_directories(options.outDir);
            ComputeDag graph = readComputeDagFile(options.graphPath);
            const ValidationResult graphValidation = validateGraph(graph);
            if (!graphValidation.ok)
            {
                writeTextFile(options.outDir + "/log.md", validationToText(graphValidation));
                error = "graph validation failed";
                return 2;
            }

            AlgorithmConfig config = readAlgorithmConfigFile(options.configPath);
            PartitionResult partition;
            const int algorithmRc = runAlgorithmWithTimeout(graph, config, options, partition, error);
            if (algorithmRc != 0)
            {
                writeTextFile(options.outDir + "/log.md",
                              buildRunLog(options,
                                          algorithmRc == kTimeoutExitCode ? "timeout" : "failed",
                                          "not run",
                                          error));
                return algorithmRc;
            }
            writeTextFile(options.outDir + "/result.json", partitionToJson(partition));

            const ValidationResult partitionValidation = validatePartition(graph, partition);
            if (!partitionValidation.ok)
            {
                writeTextFile(options.outDir + "/log.md",
                              buildRunLog(options,
                                          "invalid_partition",
                                          "failed",
                                          validationToText(partitionValidation)));
                error = "partition validation failed";
                return 3;
            }
            const PartitionScore score = scorePartition(graph, partition);
            writeTextFile(options.outDir + "/score.json", scoreToJson(score));

            writeTextFile(options.outDir + "/log.md", buildRunLog(options, "ok", "ok"));
            return 0;
        }
        catch (const std::exception &ex)
        {
            error = ex.what();
            return 1;
        }
    }
}
