#include "roi_discovery.hpp"

#include <array>
#include <filesystem>
#include <iostream>
#include <string>

using namespace fsttool::roi;

namespace
{

    int fail(const std::string &message)
    {
        std::cerr << "[test_roi_discovery] " << message << '\n';
        return 1;
    }

    template <typename Predicate>
    bool anyMatch(const std::vector<SourceAnchor> &anchors, Predicate predicate)
    {
        for (const SourceAnchor &anchor : anchors)
        {
            if (predicate(anchor))
            {
                return true;
            }
        }
        return false;
    }

} // namespace

int main()
{
    try
    {
        const std::filesystem::path dataRoot = std::filesystem::path(ROI_DISCOVERY_TESTDATA_DIR);
        const std::filesystem::path svPath = dataRoot / "lightweight_sample.sv";
        const std::filesystem::path scalaPath = dataRoot / "lightweight_sample.scala";

        if (!std::filesystem::exists(svPath) || !std::filesystem::exists(scalaPath))
        {
            return fail("missing roi test fixtures");
        }

        {
            const std::array<std::filesystem::path, 1> inputs{svPath};
            const LightweightRtlIndex index = LightweightRtlIndex::build(RtlKind::SystemVerilog, inputs);
            if (index.anchors().empty())
            {
                return fail("expected sv index to contain anchors");
            }

            const std::vector<SourceAnchor> hits = index.query("writeback data", 4);
            if (!anyMatch(hits, [](const SourceAnchor &anchor) {
                    return anchor.symbol == "writeback_data" && anchor.kind == SourceRegionKind::StateDecl;
                }))
            {
                return fail("expected writeback_data state candidate for sv query");
            }

            const std::vector<SourceAnchor> moduleHits = index.query("helper stage", 4);
            if (!anyMatch(moduleHits, [](const SourceAnchor &anchor) {
                    return anchor.symbol == "HelperStage" && anchor.kind == SourceRegionKind::Module;
                }))
            {
                return fail("expected HelperStage module candidate for sv query");
            }
        }

        {
            const std::array<std::filesystem::path, 1> inputs{scalaPath};
            const LightweightRtlIndex index = LightweightRtlIndex::build(RtlKind::Chisel, inputs);
            if (index.anchors().empty())
            {
                return fail("expected chisel index to contain anchors");
            }

            const std::vector<SourceAnchor> hits = index.query("writeback retry", 6);
            if (!anyMatch(hits, [](const SourceAnchor &anchor) {
                    return anchor.symbol == "writebackReg" && anchor.kind == SourceRegionKind::StateDecl;
                }))
            {
                return fail("expected writebackReg state candidate for chisel query");
            }

            const std::vector<SourceAnchor> ioHits = index.query("req valid", 6);
            if (!anyMatch(ioHits, [](const SourceAnchor &anchor) {
                    return anchor.symbol == "reqValid" && anchor.kind == SourceRegionKind::IODecl;
                }))
            {
                return fail("expected reqValid io candidate for chisel query");
            }
        }
    }
    catch (const std::exception &ex)
    {
        return fail(std::string("unexpected exception: ") + ex.what());
    }
    return 0;
}