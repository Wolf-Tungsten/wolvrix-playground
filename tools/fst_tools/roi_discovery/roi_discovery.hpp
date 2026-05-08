#ifndef FST_TOOLS_ROI_DISCOVERY_HPP
#define FST_TOOLS_ROI_DISCOVERY_HPP

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace fsttool::roi
{

    enum class RtlKind
    {
        SystemVerilog,
        Chisel,
    };

    enum class SourceRegionKind
    {
        Module,
        Instance,
        IODecl,
        StateDecl,
        FlowBlock,
        Assignment,
        GenericDecl,
    };

    struct SourceAnchor
    {
        std::filesystem::path file;
        std::string container;
        std::string symbol;
        std::string lineText;
        SourceRegionKind kind = SourceRegionKind::GenericDecl;
        std::uint32_t lineStart = 0;
        std::uint32_t lineEnd = 0;
        int score = 0;
        std::string reason;
    };

    struct FstSignalCandidate
    {
        std::string scope;
        std::string name;
        std::string path;
        std::uint32_t width = 0;
        std::uint32_t handle = 0;
        int score = 0;
        std::string reason;
    };

    class LightweightRtlIndex
    {
    public:
        static std::vector<std::filesystem::path> expandInputs(
            RtlKind kind,
            std::span<const std::filesystem::path> inputs);

        static LightweightRtlIndex build(
            RtlKind kind,
            std::span<const std::filesystem::path> inputs);

        const std::vector<SourceAnchor> &anchors() const noexcept;
        std::vector<SourceAnchor> query(std::string_view hint, std::size_t limit) const;

    private:
        RtlKind kind_ = RtlKind::SystemVerilog;
        std::vector<SourceAnchor> anchors_;
    };

    class FstHierarchyIndex
    {
    public:
        static FstHierarchyIndex load(const std::filesystem::path &path);

        const std::vector<std::string> &scopes() const noexcept;
        const std::vector<FstSignalCandidate> &signals() const noexcept;
        std::vector<FstSignalCandidate> query(std::string_view hint, std::size_t limit) const;

    private:
        std::vector<std::string> scopes_;
        std::vector<FstSignalCandidate> signals_;
    };

    std::optional<RtlKind> parseRtlKind(std::string_view text);
    std::string_view rtlKindName(RtlKind kind) noexcept;
    std::string_view sourceRegionKindName(SourceRegionKind kind) noexcept;

} // namespace fsttool::roi

#endif