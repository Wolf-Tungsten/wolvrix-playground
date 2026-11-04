#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "emit/grhsim_cpp.hpp"
#include "transform/activity_schedule.hpp"
#include "transform/simplify.hpp"
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace wolvrix::lib;

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("usage: activity_trace_fixture artifact-directory");
        const std::filesystem::path root(argv[1]);
        for (const std::string name : {"E", "C", "E-export", "C-export", "E-self", "C-self"}) {
            const bool fold = name[0] == 'C';
            const bool replay = name.find("self") != std::string::npos;
            const bool trace = name.find("export") != std::string::npos || replay;
            if (replay) setenv("WOLVRIX_RESEARCH_SOURCE_ORDER",
                (root / (fold ? "C-export" : "E-export") / "trace/source-order.keys.txt").c_str(), 1);
            else unsetenv("WOLVRIX_RESEARCH_SOURCE_ORDER");
            const auto out = root / name;
            std::filesystem::create_directories(out);
            setenv("WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE", fold ? "1" : "0", 1);
            if (trace) setenv("WOLVRIX_ACTIVITY_STAGE_TRACE", (out / "trace").c_str(), 1);
            else unsetenv("WOLVRIX_ACTIVITY_STAGE_TRACE");
            grh::Design design;
            auto& g = design.createGraph("fixture"); design.markAsTop("fixture");
            auto input = [&](std::string n) {
                auto v = g.createValue(g.internSymbol(n), 2, false); g.bindInputPort(n, v); return v;
            };
            auto a = input("a"), b = input("b"), c = input("c"), d = input("d"), x = input("x");
            auto op = [&](grh::OperationKind kind, std::string n, std::vector<grh::ValueId> args) {
                auto id = g.createOperation(kind, g.internSymbol(n + "_op"));
                for (auto v : args) g.addOperand(id, v);
                auto result = g.createValue(g.internSymbol(n), 2, false); g.addResult(id, result);
                g.setOpSrcLoc(id, {"owner-fixture.sv", id.index, 1, id.index, 30, "fixture", "", n});
                return result;
            };
            auto shared = op(grh::OperationKind::kXor, "shared", {a,b});
            auto table = op(grh::OperationKind::kDecodeTable, "zero_table", {x});
            g.setAttr(g.valueDef(table), "decode.table", std::string("WDT1|P|2|2|2|0|3|1,1,0,3;2,2,0,3"));
            auto slow = op(grh::OperationKind::kOr, "delayed_d", {table,d});
            auto first = op(grh::OperationKind::kOr, "first", {shared,slow});
            auto second = op(grh::OperationKind::kAnd, "second", {shared,c});
            // Root traversal and topological order are different orders.
            g.bindOutputPort("second", second); g.bindOutputPort("first", first);
            transform::SessionStore session;
            transform::PassManager pm; pm.options().session = &session;
            transform::SimplifyOptions simplify;
            simplify.semantics = transform::ConstantFoldOptions::Semantics::TwoState;
            pm.addPass(std::make_unique<transform::SimplifyPass>(simplify));
            transform::PassDiagnostics diag;
            if (!pm.run(design,diag).success || diag.hasError()) throw std::runtime_error("simplify failed");
            store::StoreOptions so; so.outputFilename=(out/"before.json").string();
            if (!store::StoreJson().store(design,so).success) throw std::runtime_error("store failed");
            transform::PassManager schedule; schedule.options().session = &session;
            schedule.addPass(std::make_unique<transform::ActivitySchedulePass>(transform::ActivityScheduleOptions{
                .path="fixture", .maxOpInComputeSupernode=128, .enableCoarsen=false}));
            if (!schedule.run(design,diag).success || diag.hasError()) throw std::runtime_error("schedule failed");
            const auto& slot = *session.at("fixture.activity_schedule.summary_stats");
            std::ofstream(out/"stats.json") << dynamic_cast<const transform::SessionSlotValue<std::string>&>(slot).value;
            emit::EmitOptions options; options.outputDir=(out/"model").string();
            options.session=&session; options.sessionPathPrefix="fixture";
            options.attributes["waveform"]="off"; options.attributes["perf"]="off";
            emit::EmitDiagnostics emitDiag;
            if (!emit::EmitGrhSimCpp(&emitDiag).emit(design,options).success || emitDiag.hasError())
                throw std::runtime_error("emit failed");
        }
        unsetenv("WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE"); unsetenv("WOLVRIX_ACTIVITY_STAGE_TRACE");
        unsetenv("WOLVRIX_RESEARCH_SOURCE_ORDER");
    } catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
