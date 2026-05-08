#include "roi_discovery.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <optional>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <vector>

using namespace fsttool::roi;

namespace
{

    struct Options
    {
        std::optional<std::filesystem::path> fstPath;
        std::optional<RtlKind> rtlKind;
        std::vector<std::filesystem::path> rtlInputs;
        std::optional<std::filesystem::path> artifactPrefix;
        std::string hint;
        std::size_t limit = 8;
    };

    int fail(const std::string &message)
    {
        std::cerr << "[fst_discover] " << message << '\n';
        return 1;
    }

    std::string jsonEscape(std::string_view text)
    {
        std::string out;
        out.reserve(text.size() + 8);
        for (char ch : text)
        {
            switch (ch)
            {
            case '\\':
                out += "\\\\";
                break;
            case '"':
                out += "\\\"";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\r':
                out += "\\r";
                break;
            case '\t':
                out += "\\t";
                break;
            default:
                out.push_back(ch);
                break;
            }
        }
        return out;
    }

    std::string tsvEscape(std::string_view text)
    {
        std::string out;
        out.reserve(text.size());
        for (char ch : text)
        {
            if (ch == '\t' || ch == '\n' || ch == '\r')
            {
                out.push_back(' ');
                continue;
            }
            out.push_back(ch);
        }
        return out;
    }

    void ensureParentDir(const std::filesystem::path &path)
    {
        const std::filesystem::path parent = path.parent_path();
        if (!parent.empty())
        {
            std::filesystem::create_directories(parent);
        }
    }

    std::filesystem::path withSuffix(const std::filesystem::path &prefix, std::string_view suffix)
    {
        return std::filesystem::path(prefix.string() + std::string(suffix));
    }

    void printUsage()
    {
        std::cout << "usage: fst_discover [--fst PATH] [--rtl-kind sv|chisel] [--rtl PATH]... [--hint TEXT] [--limit N] [--artifact-prefix PATH_PREFIX]\n";
    }

    Options parseArgs(int argc, char **argv)
    {
        Options options;
        for (int i = 1; i < argc; ++i)
        {
            const std::string_view arg(argv[i]);
            auto requireValue = [&](std::string_view flag) -> std::string_view {
                if (i + 1 >= argc)
                {
                    throw std::runtime_error("missing value for " + std::string(flag));
                }
                return argv[++i];
            };

            if (arg == "--help" || arg == "-h")
            {
                printUsage();
                std::exit(0);
            }
            if (arg == "--fst")
            {
                options.fstPath = std::filesystem::path(requireValue(arg));
                continue;
            }
            if (arg == "--rtl-kind")
            {
                const std::optional<RtlKind> kind = parseRtlKind(requireValue(arg));
                if (!kind)
                {
                    throw std::runtime_error("unsupported rtl kind");
                }
                options.rtlKind = kind;
                continue;
            }
            if (arg == "--rtl")
            {
                options.rtlInputs.emplace_back(requireValue(arg));
                continue;
            }
            if (arg == "--artifact-prefix")
            {
                options.artifactPrefix = std::filesystem::path(requireValue(arg));
                continue;
            }
            if (arg == "--hint")
            {
                options.hint = std::string(requireValue(arg));
                continue;
            }
            if (arg == "--limit")
            {
                options.limit = static_cast<std::size_t>(std::stoul(std::string(requireValue(arg))));
                continue;
            }
            throw std::runtime_error("unknown argument: " + std::string(arg));
        }

        if (!options.fstPath && options.rtlInputs.empty())
        {
            throw std::runtime_error("provide at least one of --fst or --rtl");
        }
        if (!options.rtlInputs.empty() && !options.rtlKind)
        {
            throw std::runtime_error("--rtl-kind is required when --rtl is provided");
        }
        return options;
    }

    void printSourceAnchors(std::ostream &out, const std::vector<SourceAnchor> &anchors)
    {
        for (std::size_t i = 0; i < anchors.size(); ++i)
        {
            const SourceAnchor &anchor = anchors[i];
            out << "    {\n"
                << "      \"file\": \"" << jsonEscape(anchor.file.generic_string()) << "\",\n"
                << "      \"container\": \"" << jsonEscape(anchor.container) << "\",\n"
                << "      \"symbol\": \"" << jsonEscape(anchor.symbol) << "\",\n"
                << "      \"kind\": \"" << sourceRegionKindName(anchor.kind) << "\",\n"
                << "      \"line\": " << anchor.lineStart << ",\n"
                << "      \"score\": " << anchor.score << ",\n"
                << "      \"reason\": \"" << jsonEscape(anchor.reason) << "\"\n"
                << "    }";
            if (i + 1 != anchors.size())
            {
                out << ',';
            }
            out << '\n';
        }
    }

    void printSignals(std::ostream &out, const std::vector<FstSignalCandidate> &signals)
    {
        for (std::size_t i = 0; i < signals.size(); ++i)
        {
            const FstSignalCandidate &signal = signals[i];
            out << "    {\n"
                << "      \"path\": \"" << jsonEscape(signal.path) << "\",\n"
                << "      \"width\": " << signal.width << ",\n"
                << "      \"handle\": " << signal.handle << ",\n"
                << "      \"score\": " << signal.score << ",\n"
                << "      \"reason\": \"" << jsonEscape(signal.reason) << "\"\n"
                << "    }";
            if (i + 1 != signals.size())
            {
                out << ',';
            }
            out << '\n';
        }
    }

    void writeMetadataJson(std::ostream &out,
                           const Options &options,
                           const std::vector<SourceAnchor> &anchors,
                           const std::vector<FstSignalCandidate> &signals,
                           std::size_t exportedSignalRows)
    {
        const std::string artifactPrefix = options.artifactPrefix ? options.artifactPrefix->generic_string() : std::string();
        out << "{\n"
            << "  \"query\": {\n"
            << "    \"hint\": \"" << jsonEscape(options.hint) << "\",\n"
            << "    \"rtl_kind\": \"" << (options.rtlKind ? std::string(rtlKindName(*options.rtlKind)) : std::string()) << "\"\n"
            << "  },\n"
            << "  \"artifacts\": {\n"
            << "    \"artifact_prefix\": \"" << jsonEscape(artifactPrefix) << "\",\n"
            << "    \"metadata_json\": \"" << (artifactPrefix.empty() ? std::string() : jsonEscape(artifactPrefix + ".metadata.json")) << "\",\n"
            << "    \"signals_tsv\": \"" << (artifactPrefix.empty() ? std::string() : jsonEscape(artifactPrefix + ".signals.tsv")) << "\",\n"
            << "    \"expected_ai_report\": \"" << (artifactPrefix.empty() ? std::string() : jsonEscape(artifactPrefix + ".ai.md")) << "\",\n"
            << "    \"exported_signal_rows\": " << exportedSignalRows << "\n"
            << "  },\n"
            << "  \"candidate_regions\": [\n";
        printSourceAnchors(out, anchors);
        out << "  ],\n"
            << "  \"candidate_signals\": [\n";
        printSignals(out, signals);
        out << "  ]\n"
            << "}\n";
    }

    void writeSignalsTsv(const std::filesystem::path &path,
                         const std::vector<FstSignalCandidate> &allSignals,
                         const std::vector<FstSignalCandidate> &rankedSignals)
    {
        ensureParentDir(path);
        std::ofstream out(path);
        if (!out)
        {
            throw std::runtime_error("failed to write signals tsv: " + path.string());
        }

        struct RankedInfo
        {
            std::size_t rank = 0;
            int score = 0;
            std::string reason;
        };

        std::unordered_map<std::uint32_t, RankedInfo> rankedByHandle;
        for (std::size_t i = 0; i < rankedSignals.size(); ++i)
        {
            rankedByHandle.emplace(rankedSignals[i].handle, RankedInfo{i + 1, rankedSignals[i].score, rankedSignals[i].reason});
        }

        out << "path\tscope\tname\twidth\thandle\tcandidate_rank\tcandidate_score\tcandidate_reason\n";
        for (const FstSignalCandidate &signal : allSignals)
        {
            const auto it = rankedByHandle.find(signal.handle);
            out << tsvEscape(signal.path) << '\t'
                << tsvEscape(signal.scope) << '\t'
                << tsvEscape(signal.name) << '\t'
                << signal.width << '\t'
                << signal.handle << '\t';
            if (it != rankedByHandle.end())
            {
                out << it->second.rank << '\t'
                    << it->second.score << '\t'
                    << tsvEscape(it->second.reason);
            }
            else
            {
                out << "\t\t";
            }
            out << '\n';
        }
    }

} // namespace

int main(int argc, char **argv)
{
    try
    {
        const Options options = parseArgs(argc, argv);

        std::vector<SourceAnchor> anchors;
        if (options.rtlKind)
        {
            const LightweightRtlIndex index = LightweightRtlIndex::build(*options.rtlKind, options.rtlInputs);
            anchors = index.query(options.hint, options.limit);
        }

        std::vector<FstSignalCandidate> allSignals;
        std::vector<FstSignalCandidate> signals;
        if (options.fstPath)
        {
            const FstHierarchyIndex index = FstHierarchyIndex::load(*options.fstPath);
            allSignals = index.signals();
            signals = index.query(options.hint, options.limit);
        }

        if (options.artifactPrefix)
        {
            const std::filesystem::path metadataPath = withSuffix(*options.artifactPrefix, ".metadata.json");
            const std::filesystem::path signalsTsvPath = withSuffix(*options.artifactPrefix, ".signals.tsv");

            ensureParentDir(metadataPath);
            std::ofstream metadataOut(metadataPath);
            if (!metadataOut)
            {
                throw std::runtime_error("failed to write metadata json: " + metadataPath.string());
            }
            writeMetadataJson(metadataOut, options, anchors, signals, allSignals.size());
            writeSignalsTsv(signalsTsvPath, allSignals, signals);
        }

        writeMetadataJson(std::cout, options, anchors, signals, allSignals.size());
        return 0;
    }
    catch (const std::exception &ex)
    {
        return fail(ex.what());
    }
}