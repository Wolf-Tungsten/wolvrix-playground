#include "roi_discovery.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_set>

#include "fstapi.h"

namespace fsttool::roi
{

    namespace
    {

        struct QueryTerms
        {
            std::string loweredHint;
            std::vector<std::string> tokens;
        };

        std::string toLowerCopy(std::string_view text)
        {
            std::string lowered;
            lowered.reserve(text.size());
            for (unsigned char raw : text)
            {
                lowered.push_back(static_cast<char>(std::tolower(raw)));
            }
            return lowered;
        }

        std::string trimCopy(std::string_view text)
        {
            std::size_t begin = 0;
            while (begin < text.size() && std::isspace(static_cast<unsigned char>(text[begin])))
            {
                ++begin;
            }
            std::size_t end = text.size();
            while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1])))
            {
                --end;
            }
            return std::string(text.substr(begin, end - begin));
        }

        std::string stripLineComment(std::string_view line)
        {
            const std::size_t pos = line.find("//");
            if (pos == std::string_view::npos)
            {
                return trimCopy(line);
            }
            return trimCopy(line.substr(0, pos));
        }

        QueryTerms buildTerms(std::string_view hint)
        {
            QueryTerms terms;
            terms.loweredHint = toLowerCopy(trimCopy(hint));
            std::string token;
            for (char ch : terms.loweredHint)
            {
                if (std::isalnum(static_cast<unsigned char>(ch)) || ch == '_')
                {
                    token.push_back(ch);
                    continue;
                }
                if (!token.empty())
                {
                    terms.tokens.push_back(token);
                    token.clear();
                }
            }
            if (!token.empty())
            {
                terms.tokens.push_back(std::move(token));
            }
            return terms;
        }

        bool hasAllowedExtension(RtlKind kind, const std::filesystem::path &path)
        {
            const std::string ext = toLowerCopy(path.extension().string());
            if (kind == RtlKind::SystemVerilog)
            {
                return ext == ".sv" || ext == ".v" || ext == ".svh" || ext == ".vh";
            }
            return ext == ".scala" || ext == ".sc";
        }

        int defaultPriority(SourceRegionKind kind)
        {
            switch (kind)
            {
            case SourceRegionKind::Module:
                return 90;
            case SourceRegionKind::StateDecl:
                return 80;
            case SourceRegionKind::IODecl:
                return 70;
            case SourceRegionKind::FlowBlock:
                return 55;
            case SourceRegionKind::Assignment:
                return 45;
            case SourceRegionKind::Instance:
                return 40;
            case SourceRegionKind::GenericDecl:
                return 35;
            }
            return 0;
        }

        bool isKeyword(std::string_view token)
        {
            static const std::unordered_set<std::string_view> keywords = {
                "module", "endmodule", "input", "output", "inout", "logic", "reg", "wire", "var",
                "signed", "unsigned", "assign", "always", "always_ff", "always_comb", "always_latch",
                "if", "else", "begin", "end", "class", "extends", "val", "new", "when", "switch",
                "Bool", "UInt", "SInt", "Bundle", "Vec", "Input", "Output", "IO", "Flipped",
                "Reg", "RegInit", "RegNext", "Wire", "WireInit", "Module"
            };
            return keywords.contains(token);
        }

        std::optional<std::string> pickTrailingIdentifier(std::string_view text)
        {
            static const std::regex identRegex(R"(([A-Za-z_][A-Za-z0-9_$]*))");
            const std::string materialized(text);
            std::vector<std::string> identifiers;
            for (std::sregex_iterator it(materialized.begin(), materialized.end(), identRegex), end; it != end; ++it)
            {
                const std::string value = it->str();
                if (isKeyword(value))
                {
                    continue;
                }
                identifiers.push_back(value);
            }
            if (identifiers.empty())
            {
                return std::nullopt;
            }
            return identifiers.back();
        }

        void appendAnchor(std::vector<SourceAnchor> &anchors,
                          const std::filesystem::path &path,
                          const std::string &container,
                          std::string symbol,
                          std::string lineText,
                          SourceRegionKind kind,
                          std::uint32_t lineNumber)
        {
            if (symbol.empty())
            {
                return;
            }
            anchors.push_back(SourceAnchor{
                .file = path,
                .container = container,
                .symbol = std::move(symbol),
                .lineText = std::move(lineText),
                .kind = kind,
                .lineStart = lineNumber,
                .lineEnd = lineNumber,
                .score = 0,
                .reason = {},
            });
        }

        void scanSystemVerilogFile(const std::filesystem::path &path,
                                   std::vector<SourceAnchor> &anchors)
        {
            static const std::regex moduleRegex(R"(^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*))");
            static const std::regex instanceRegex(R"(^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\()");
            static const std::regex assignRegex(R"(^\s*assign\s+([A-Za-z_][A-Za-z0-9_$]*))");

            std::ifstream input(path);
            if (!input)
            {
                throw std::runtime_error("failed to open RTL source: " + path.string());
            }

            std::string container;
            std::string line;
            std::uint32_t lineNumber = 0;
            while (std::getline(input, line))
            {
                ++lineNumber;
                const std::string trimmed = stripLineComment(line);
                if (trimmed.empty())
                {
                    continue;
                }

                std::smatch match;
                if (std::regex_search(trimmed, match, moduleRegex))
                {
                    container = match[1].str();
                    appendAnchor(anchors, path, container, container, trimmed, SourceRegionKind::Module, lineNumber);
                    continue;
                }
                if (trimmed.rfind("endmodule", 0) == 0)
                {
                    container.clear();
                    continue;
                }
                if (std::regex_search(trimmed, match, instanceRegex))
                {
                    const std::string moduleName = match[1].str();
                    if (!isKeyword(moduleName))
                    {
                        appendAnchor(anchors, path, container, match[2].str(), trimmed, SourceRegionKind::Instance, lineNumber);
                        continue;
                    }
                }
                if (trimmed.rfind("always", 0) == 0)
                {
                    appendAnchor(anchors, path, container, "always@" + std::to_string(lineNumber), trimmed, SourceRegionKind::FlowBlock, lineNumber);
                    continue;
                }
                if (std::regex_search(trimmed, match, assignRegex))
                {
                    appendAnchor(anchors, path, container, match[1].str(), trimmed, SourceRegionKind::Assignment, lineNumber);
                    continue;
                }
                if (trimmed.rfind("input", 0) == 0 || trimmed.rfind("output", 0) == 0 || trimmed.rfind("inout", 0) == 0)
                {
                    if (auto symbol = pickTrailingIdentifier(trimmed))
                    {
                        appendAnchor(anchors, path, container, *symbol, trimmed, SourceRegionKind::IODecl, lineNumber);
                    }
                    continue;
                }
                if (trimmed.rfind("logic", 0) == 0 || trimmed.rfind("reg", 0) == 0 || trimmed.rfind("wire", 0) == 0)
                {
                    if (auto symbol = pickTrailingIdentifier(trimmed))
                    {
                        appendAnchor(anchors, path, container, *symbol, trimmed, SourceRegionKind::StateDecl, lineNumber);
                    }
                }
            }
        }

        void scanChiselFile(const std::filesystem::path &path,
                            std::vector<SourceAnchor> &anchors)
        {
            static const std::regex classRegex(R"(^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s+extends\s+([A-Za-z0-9_().]+))");
            static const std::regex valRegex(R"(^\s*val\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$)");

            std::ifstream input(path);
            if (!input)
            {
                throw std::runtime_error("failed to open RTL source: " + path.string());
            }

            std::string container;
            std::string line;
            std::uint32_t lineNumber = 0;
            while (std::getline(input, line))
            {
                ++lineNumber;
                const std::string trimmed = stripLineComment(line);
                if (trimmed.empty())
                {
                    continue;
                }

                std::smatch match;
                if (std::regex_search(trimmed, match, classRegex))
                {
                    container = match[1].str();
                    appendAnchor(anchors, path, container, container, trimmed, SourceRegionKind::Module, lineNumber);
                    continue;
                }
                if (trimmed.rfind("when", 0) == 0)
                {
                    appendAnchor(anchors, path, container, "when@" + std::to_string(lineNumber), trimmed, SourceRegionKind::FlowBlock, lineNumber);
                    continue;
                }
                if (trimmed.rfind("switch", 0) == 0)
                {
                    appendAnchor(anchors, path, container, "switch@" + std::to_string(lineNumber), trimmed, SourceRegionKind::FlowBlock, lineNumber);
                    continue;
                }
                if (std::regex_search(trimmed, match, valRegex))
                {
                    const std::string symbol = match[1].str();
                    const std::string rhs = match[2].str();
                    SourceRegionKind kind = SourceRegionKind::GenericDecl;
                    if (rhs.find("IO(") != std::string::npos ||
                        rhs.find("Input(") != std::string::npos ||
                        rhs.find("Output(") != std::string::npos ||
                        rhs.find("Flipped(") != std::string::npos)
                    {
                        kind = SourceRegionKind::IODecl;
                    }
                    else if (rhs.find("Reg") != std::string::npos || rhs.find("Wire") != std::string::npos)
                    {
                        kind = SourceRegionKind::StateDecl;
                    }
                    appendAnchor(anchors, path, container, symbol, trimmed, kind, lineNumber);
                }
            }
        }

        int scoreTextCandidate(std::string_view symbol,
                               std::string_view container,
                               std::string_view lineText,
                               SourceRegionKind kind,
                               const QueryTerms &terms,
                               std::string &reason)
        {
            int score = defaultPriority(kind);
            const std::string loweredSymbol = toLowerCopy(symbol);
            const std::string loweredContainer = toLowerCopy(container);
            const std::string loweredLine = toLowerCopy(lineText);
            if (terms.tokens.empty())
            {
                reason = "default priority";
                return score;
            }

            int matchedTokens = 0;
            std::string localReason;
            for (const std::string &token : terms.tokens)
            {
                if (loweredSymbol == token)
                {
                    score += 120;
                    ++matchedTokens;
                    localReason = "exact symbol match";
                    continue;
                }
                if (loweredSymbol.find(token) != std::string::npos)
                {
                    score += 60;
                    ++matchedTokens;
                    if (localReason.empty())
                    {
                        localReason = "symbol token match";
                    }
                    continue;
                }
                if (!loweredContainer.empty() && loweredContainer.find(token) != std::string::npos)
                {
                    score += 30;
                    ++matchedTokens;
                    if (localReason.empty())
                    {
                        localReason = "container token match";
                    }
                    continue;
                }
                if (loweredLine.find(token) != std::string::npos)
                {
                    score += 15;
                    ++matchedTokens;
                    if (localReason.empty())
                    {
                        localReason = "source line token match";
                    }
                }
            }

            if (matchedTokens == 0)
            {
                return 0;
            }
            if (matchedTokens == static_cast<int>(terms.tokens.size()))
            {
                score += 20;
            }
            reason = localReason.empty() ? "token match" : localReason;
            return score;
        }

        std::string joinScope(const std::vector<std::string> &scopes)
        {
            std::ostringstream stream;
            for (std::size_t i = 0; i < scopes.size(); ++i)
            {
                if (i != 0)
                {
                    stream << '.';
                }
                stream << scopes[i];
            }
            return stream.str();
        }

    } // namespace

    std::optional<RtlKind> parseRtlKind(std::string_view text)
    {
        const std::string lowered = toLowerCopy(text);
        if (lowered == "sv" || lowered == "systemverilog" || lowered == "verilog")
        {
            return RtlKind::SystemVerilog;
        }
        if (lowered == "chisel" || lowered == "scala")
        {
            return RtlKind::Chisel;
        }
        return std::nullopt;
    }

    std::string_view rtlKindName(RtlKind kind) noexcept
    {
        switch (kind)
        {
        case RtlKind::SystemVerilog:
            return "sv";
        case RtlKind::Chisel:
            return "chisel";
        }
        return "unknown";
    }

    std::string_view sourceRegionKindName(SourceRegionKind kind) noexcept
    {
        switch (kind)
        {
        case SourceRegionKind::Module:
            return "module";
        case SourceRegionKind::Instance:
            return "instance";
        case SourceRegionKind::IODecl:
            return "io";
        case SourceRegionKind::StateDecl:
            return "state";
        case SourceRegionKind::FlowBlock:
            return "flow";
        case SourceRegionKind::Assignment:
            return "assign";
        case SourceRegionKind::GenericDecl:
            return "decl";
        }
        return "decl";
    }

    std::vector<std::filesystem::path> LightweightRtlIndex::expandInputs(
        RtlKind kind,
        std::span<const std::filesystem::path> inputs)
    {
        std::vector<std::filesystem::path> expanded;
        std::unordered_set<std::string> seen;
        for (const std::filesystem::path &input : inputs)
        {
            std::error_code ec;
            if (std::filesystem::is_regular_file(input, ec))
            {
                if (hasAllowedExtension(kind, input))
                {
                    const std::string key = std::filesystem::weakly_canonical(input, ec).string();
                    if (seen.insert(key).second)
                    {
                        expanded.push_back(input);
                    }
                }
                continue;
            }
            if (!std::filesystem::is_directory(input, ec))
            {
                continue;
            }
            for (std::filesystem::recursive_directory_iterator it(input, ec), end; it != end; it.increment(ec))
            {
                if (ec)
                {
                    break;
                }
                if (!it->is_regular_file(ec) || ec)
                {
                    continue;
                }
                const std::filesystem::path path = it->path();
                if (!hasAllowedExtension(kind, path))
                {
                    continue;
                }
                const std::string key = std::filesystem::weakly_canonical(path, ec).string();
                if (seen.insert(key).second)
                {
                    expanded.push_back(path);
                }
            }
        }
        std::sort(expanded.begin(), expanded.end());
        return expanded;
    }

    LightweightRtlIndex LightweightRtlIndex::build(
        RtlKind kind,
        std::span<const std::filesystem::path> inputs)
    {
        LightweightRtlIndex index;
        index.kind_ = kind;
        const std::vector<std::filesystem::path> files = expandInputs(kind, inputs);
        for (const std::filesystem::path &path : files)
        {
            if (kind == RtlKind::SystemVerilog)
            {
                scanSystemVerilogFile(path, index.anchors_);
            }
            else
            {
                scanChiselFile(path, index.anchors_);
            }
        }
        return index;
    }

    const std::vector<SourceAnchor> &LightweightRtlIndex::anchors() const noexcept
    {
        return anchors_;
    }

    std::vector<SourceAnchor> LightweightRtlIndex::query(std::string_view hint, std::size_t limit) const
    {
        const QueryTerms terms = buildTerms(hint);
        std::vector<SourceAnchor> ranked;
        ranked.reserve(anchors_.size());
        for (const SourceAnchor &anchor : anchors_)
        {
            SourceAnchor candidate = anchor;
            candidate.score = scoreTextCandidate(anchor.symbol,
                                                anchor.container,
                                                anchor.lineText,
                                                anchor.kind,
                                                terms,
                                                candidate.reason);
            if (candidate.score <= 0)
            {
                continue;
            }
            ranked.push_back(std::move(candidate));
        }

        std::sort(ranked.begin(), ranked.end(), [](const SourceAnchor &lhs, const SourceAnchor &rhs) {
            if (lhs.score != rhs.score)
            {
                return lhs.score > rhs.score;
            }
            if (lhs.file != rhs.file)
            {
                return lhs.file.generic_string() < rhs.file.generic_string();
            }
            if (lhs.lineStart != rhs.lineStart)
            {
                return lhs.lineStart < rhs.lineStart;
            }
            return lhs.symbol < rhs.symbol;
        });

        if (ranked.size() > limit)
        {
            ranked.resize(limit);
        }
        return ranked;
    }

    FstHierarchyIndex FstHierarchyIndex::load(const std::filesystem::path &path)
    {
        fstReaderContext *ctx = fstReaderOpen(path.c_str());
        if (!ctx)
        {
            throw std::runtime_error("failed to open fst: " + path.string());
        }

        struct ReaderGuard
        {
            fstReaderContext *ctx = nullptr;
            ~ReaderGuard()
            {
                if (ctx)
                {
                    fstReaderClose(ctx);
                }
            }
        } guard{ctx};

        FstHierarchyIndex index;
        std::vector<std::string> scopeStack;
        while (fstHier *hier = fstReaderIterateHier(ctx))
        {
            if (hier->htyp == FST_HT_SCOPE)
            {
                scopeStack.emplace_back(hier->u.scope.name ? hier->u.scope.name : "");
                index.scopes_.push_back(joinScope(scopeStack));
                continue;
            }
            if (hier->htyp == FST_HT_UPSCOPE)
            {
                if (!scopeStack.empty())
                {
                    scopeStack.pop_back();
                }
                continue;
            }
            if (hier->htyp != FST_HT_VAR)
            {
                continue;
            }
            FstSignalCandidate candidate;
            candidate.scope = joinScope(scopeStack);
            candidate.name = hier->u.var.name ? hier->u.var.name : "";
            candidate.path = candidate.scope.empty() ? candidate.name : candidate.scope + "." + candidate.name;
            candidate.width = hier->u.var.length;
            candidate.handle = hier->u.var.handle;
            index.signals_.push_back(std::move(candidate));
        }
        return index;
    }

    const std::vector<std::string> &FstHierarchyIndex::scopes() const noexcept
    {
        return scopes_;
    }

    const std::vector<FstSignalCandidate> &FstHierarchyIndex::signals() const noexcept
    {
        return signals_;
    }

    std::vector<FstSignalCandidate> FstHierarchyIndex::query(std::string_view hint, std::size_t limit) const
    {
        const QueryTerms terms = buildTerms(hint);
        std::vector<FstSignalCandidate> ranked;
        ranked.reserve(signals_.size());
        for (const FstSignalCandidate &signal : signals_)
        {
            FstSignalCandidate candidate = signal;
            candidate.score = scoreTextCandidate(signal.name,
                                                signal.scope,
                                                signal.path,
                                                SourceRegionKind::StateDecl,
                                                terms,
                                                candidate.reason);
            if (candidate.score <= 0)
            {
                continue;
            }
            ranked.push_back(std::move(candidate));
        }

        std::sort(ranked.begin(), ranked.end(), [](const FstSignalCandidate &lhs, const FstSignalCandidate &rhs) {
            if (lhs.score != rhs.score)
            {
                return lhs.score > rhs.score;
            }
            if (lhs.path != rhs.path)
            {
                return lhs.path < rhs.path;
            }
            return lhs.handle < rhs.handle;
        });

        if (ranked.size() > limit)
        {
            ranked.resize(limit);
        }
        return ranked;
    }

} // namespace fsttool::roi