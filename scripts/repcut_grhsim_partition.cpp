#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "transform/mem_to_reg.hpp"
#include "transform/memory_write_coalesce.hpp"
#include "transform/reg_to_mem.hpp"
#include "transform/repcut.hpp"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>

using namespace wolvrix::lib;
using namespace wolvrix::lib::transform;

int main(int argc, char **argv)
{
    try
    {
        if (argc != 6) throw std::runtime_error("usage: partition raw.json out_dir K threads | replay raw.json out_dir K assignment | memory raw.json out.json selected.txt row_limit");
        const int fd = open(argv[2], O_RDONLY);
        struct stat st{};
        if (fd < 0 || fstat(fd, &st) || st.st_size <= 0) throw std::runtime_error("input open failed");
        void *data = mmap(nullptr, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
        if (data == MAP_FAILED) throw std::runtime_error("input mmap failed");
        auto design = grh::Design::fromJsonString({static_cast<const char *>(data), std::size_t(st.st_size)});
        munmap(data, st.st_size); close(fd);
        if (design.topGraphs().size() != 1) throw std::runtime_error("one raw top required");
        const auto top = design.topGraphs()[0];
        PassManager manager;
        SessionStore session;
        manager.options().session = &session;
        manager.options().verbosity = PassVerbosity::Info;
        manager.options().logLevel = LogLevel::Info;
        std::filesystem::path output(argv[3]);
        std::set<std::string> selected;
        if (std::string_view(argv[1]) == "memory")
        {
            MemToRegOptions options;
            options.rowLimit = std::stoll(argv[5]);
            options.strictInit = false;
            std::ifstream list(argv[4]);
            std::string symbol;
            while (std::getline(list, symbol))
            {
                if (symbol.empty() || symbol.find_first_of("\r\t") != std::string::npos || !selected.insert(symbol).second)
                    throw std::runtime_error("invalid or duplicate selected memory");
                options.memorySymbols.push_back(symbol);
            }
            if (!list.eof()) throw std::runtime_error("selected memory file read failed");
            std::set<std::string> found;
            for (const auto &[name, graph] : design.graphs())
                for (auto id : graph->operations())
                {
                    const auto op = graph->getOperation(id);
                    if (op.kind() == grh::OperationKind::kMemory && selected.contains(std::string(op.symbolText())))
                        found.insert(std::string(op.symbolText()));
                }
            if (found != selected) throw std::runtime_error("selected memory does not exist in input");
            // Empty selection means no change, not the pass's select-all mode.
            if (!selected.empty()) manager.addPass(std::make_unique<MemToRegPass>(options));
        }
        else if (std::string_view(argv[1]) == "partition" || std::string_view(argv[1]) == "replay")
        {
            std::filesystem::create_directories(output);
            RepcutOptions options;
            options.path = top;
            options.partitionCount = std::stoul(argv[4]);
            if (std::string_view(argv[1]) == "partition")
                options.mtKaHyParThreads = std::stoul(argv[5]);
            else
            {
                std::ifstream input(argv[5]);
                RepcutReplayAssignment assignment;
                uint64_t label;
                while (input >> label)
                {
                    if (label >= options.partitionCount) throw std::runtime_error("assignment label outside partition range");
                    assignment.atomPartitions.push_back(static_cast<uint32_t>(label));
                }
                if (!input.eof() || assignment.atomPartitions.empty()) throw std::runtime_error("invalid replay assignment");
                session.emplace(top + ".repcut.replay_assignment",
                                std::make_unique<SessionSlotValue<RepcutReplayAssignment>>(std::move(assignment)));
                options.partitioner = "assignment-replay";
            }
            options.weightMode = RepcutWeightMode::kClosureAware;
            options.costModel = RepcutCostModel::kGrhsimV1;
            options.workDir = (output / "work").string();
            options.keepIntermediateFiles = true;
            manager.addPass(std::make_unique<RepcutPass>(options));
            manager.addPass(std::make_unique<MemoryWriteCoalescePass>());
            RegToMemOptions merge;
            merge.enableIntent = false;
            merge.profitabilityFilter = RegToMemProfitabilityPolicy::VerilatorV1;
            manager.addPass(std::make_unique<RegToMemPass>(merge));
            output /= "partitioned.json";
        }
        else throw std::runtime_error("unknown mode");
        PassDiagnostics diagnostics;
        const auto result = manager.run(design, diagnostics);
        for (const auto &message : diagnostics.messages()) std::cerr << message.message << '\n';
        if (!result.success || diagnostics.hasError()) throw std::runtime_error("transform pipeline failed");
        if (!selected.empty())
        {
            for (const auto &[name, graph] : design.graphs())
                for (auto id : graph->operations())
                {
                    const auto op = graph->getOperation(id);
                    if (op.kind() == grh::OperationKind::kMemory && selected.contains(std::string(op.symbolText())))
                        throw std::runtime_error("selected memory was not converted");
                }
        }
        store::StoreOptions options;
        options.outputFilename = output.string();
        options.topOverrides = {top};
        if (!store::StoreJson().store(design, options).success) throw std::runtime_error("JSON store failed");
        std::cout << "PASS " << output << std::endl;
    }
    catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
