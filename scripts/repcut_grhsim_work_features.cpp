#include "emit/grhsim_activity_model.hpp"
#include <cstdlib>

using namespace wolvrix::lib;
using namespace emit;
using namespace grh;
GrhSimActivityReport workActivity(const Graph &, const GrhSimExecutionPlan &, const GrhSimActivitySeeds &, bool);
#define analyzeGrhSimActivity workActivity
#include "repcut_grhsim_execution_plan.cpp"
#undef analyzeGrhSimActivity

namespace
{
    std::set<std::string> exported;
    std::map<std::pair<std::string, bool>, GrhSimWorkReport> finalWork;
    std::ofstream inventory, bodies, compute;
    const char *bodyName(GrhSimExecutionPlan::CommitWriteBody::Kind kind)
    {
        using Kind = GrhSimExecutionPlan::CommitWriteBody::Kind;
        switch (kind) {
        case Kind::Lockstep: return "lockstep";
        case Kind::SameReader: return "same_reader";
        case Kind::OrderedMemoryAffine: return "ordered_memory";
        default: return "single";
        }
    }
    std::string csvText(std::string_view text)
    {
        std::string out = "\"";
        for (auto c : text) { if (c == '"') out += '"'; out += c; }
        return out + '"';
    }
    void exportWork(const Graph &graph, const GrhSimExecutionPlan &plan, const GrhSimWorkReport &work)
    {
        const std::string part(graph.symbol());
        if (!exported.insert(part).second) return;
        if (!inventory.is_open())
        {
            const auto *dir = std::getenv("WORK_FEATURES_OUT");
            if (!dir) throw std::runtime_error("WORK_FEATURES_OUT missing");
            const std::filesystem::path path(dir);
            inventory.open(path / "work_inventory.csv"); inventory << "part,feature,value\n";
            bodies.open(path / "commit_bodies.csv"); bodies << "part,run,body,kind,operations\n";
            compute.open(path / "compute_lowering.csv"); compute << "part,supernode,feature,value\n";
        }
        auto counts = work.staticFeatures;
        counts["commit.writers"] = plan.writes.size();
        std::unordered_map<OperationId, unsigned, OperationIdHash> writerVisits, computeVisits;
        for (std::size_t r = 0; r < plan.commitWriteRuns.size(); ++r)
        {
            const auto &run = plan.commitWriteRuns[r];
            counts["commit.enable_groups"] += run.enables.size();
            for (std::size_t b = 0; b < run.bodies.size(); ++b)
            {
                const auto &body = run.bodies[b];
                const std::string kind = bodyName(body.kind);
                ++counts["commit." + kind + "_bodies"];
                counts["commit." + kind + "_members"] += body.operations.size();
                std::string symbols;
                for (auto op : body.operations)
                {
                    ++writerVisits[op];
                    if (!symbols.empty()) symbols += ';'; symbols += graph.getOperation(op).symbolText();
                }
                bodies << part << ',' << r << ',' << b << ',' << kind << ',' << csvText(symbols) << '\n';
                for (const auto &[name, count] : body.enabledWork) counts["enabled." + name] += count;
                for (const auto &[name, count] : body.changedWork) counts["changed." + name] += count;
            }
        }
        for (const auto &entry : plan.computeLowering)
        {
            ++counts["compute.groups"];
            counts["compute.lowered_operations"] += entry.loweredOperations.size();
            for (auto op : entry.loweredOperations) ++computeVisits[op];
            for (auto op : entry.genericOperations) ++computeVisits[op];
            for (const auto &[name, count] : entry.features)
            {
                compute << part << ',' << entry.supernode << ',' << name << ',' << count << '\n';
                counts["compute." + name] += count;
            }
        }
        for (const auto &write : plan.writes)
            if (writerVisits[write.operation] != 1) throw std::runtime_error("writer membership is not exact");
        for (const auto &group : plan.groups)
            if (group.phase == GrhSimExecutionPlan::Phase::Compute)
                for (auto op : group.operations)
                {
                    ++counts["compute.scheduled_operations"];
                    if (computeVisits[op] != 1) throw std::runtime_error("compute lowering membership is not exact");
                }
        for (const auto &[name, count] : counts) inventory << part << ',' << name << ',' << count << '\n';
        inventory.flush(); bodies.flush(); compute.flush();
        std::cout << "WORK FEATURES " << part << " generic=" << work.genericComputeOperations
                  << " unmodeled=" << work.unmodeledCommitBodies + work.unmodeledComputeGroups << std::endl;
    }
    struct Output
    {
        ~Output()
        {
            const auto *dir = std::getenv("WORK_FEATURES_OUT"); if (!dir) return;
            std::ofstream out(std::filesystem::path(dir) / "work_conditional.csv");
            out << "part,precision,mask,feature,value\n";
            std::ofstream buckets(std::filesystem::path(dir) / "backend_cost.csv");
            buckets << "part,precision,mask,family,feature,value\n";
            std::ofstream mechanisms(std::filesystem::path(dir) / "mechanism_cost.csv");
            mechanisms << "part,precision,mask,unit,feature,value\n";
            for (const auto &[key, work] : finalWork)
            {
                for (const auto &[mask, features] : work.conditionalFeatures)
                    for (const auto &[name, count] : features)
                        out << key.first << ',' << (key.second ? "range" : "whole") << ',' << mask
                            << ',' << name << ',' << count << '\n';
                const auto report = bucketizeGrhSimWork(work);
                for (const auto &[mask, families] : report.conditionalFeatures)
                    for (const auto &[family, features] : families)
                        for (const auto &[name, count] : features)
                            buckets << key.first << ',' << (key.second ? "range" : "whole") << ',' << mask
                                    << ',' << family << ',' << name << ',' << count << '\n';
                for (const auto &[mask, features] : report.unbucketedFeatures)
                    for (const auto &[name, count] : features)
                        buckets << key.first << ',' << (key.second ? "range" : "whole") << ',' << mask
                                << ",UNBUCKETED," << name << ',' << count << '\n';
                const auto units = projectGrhSimMechanismUnits(report);
                for (const auto &[mask, attribution] : units.conditionalAttribution)
                    for (const auto &[unit, features] : attribution)
                        for (const auto &[name, count] : features)
                            mechanisms << key.first << ',' << (key.second ? "range" : "whole") << ',' << mask
                                       << ',' << unit << ',' << name << ',' << count << '\n';
                for (const auto &[mask, features] : units.unmappedFeatures)
                    for (const auto &[name, count] : features)
                        mechanisms << key.first << ',' << (key.second ? "range" : "whole") << ',' << mask
                                   << ",UNMAPPED," << name << ',' << count << '\n';
            }
        }
    } output;
}

GrhSimActivityReport workActivity(const Graph &graph, const GrhSimExecutionPlan &plan,
                                  const GrhSimActivitySeeds &seeds, bool full)
{
    GrhSimActivityOptions options;
    options.unseededEvents = full ? GrhSimUnseededEvents::ValueDependencies : GrhSimUnseededEvents::SeededRootsOnly;
    auto activity = analyzeGrhSimActivity(graph, plan, seeds, options);
    auto work = summarizeGrhSimWork(plan, activity);
    exportWork(graph, plan, work);
    finalWork[{std::string(graph.symbol()), full}] = std::move(work);
    return activity;
}
