// List the operations of a graph that exist only to feed accumulate-bank
// registers. The graph goes through the same steps as the bank emit driver
// (simplify, reg-to-mem, accumulate-sink in bank mode); then everything that
// no design sink depends on is the counter-only cone.
//
// Design sinks: DPI calls, system tasks, instances and output ports. State is
// live when a live operation reads it, and then so are its writers. A bank
// register never is, because only on-demand task arguments read it, and those
// arguments do not keep their other inputs alive either.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "transform/accumulate_sink.hpp"
#include "transform/reg_to_mem.hpp"
#include "transform/simplify.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace wolvrix::lib;
using grh::OperationId;
using grh::OperationKind;
using grh::ValueId;

namespace {
std::string stringAttr(const grh::Operation &op, std::string_view key) {
    const auto attr = op.attr(key);
    const std::string *value = attr ? std::get_if<std::string>(&*attr) : nullptr;
    return value ? *value : std::string();
}
bool boolAttr(const grh::Operation &op, std::string_view key) {
    const auto attr = op.attr(key);
    const bool *value = attr ? std::get_if<bool>(&*attr) : nullptr;
    return value && *value;
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: cone graph.json output.tsv");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("missing input graph");
        auto design = grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input), {}));
        transform::SessionStore session;
        auto run = [&](std::unique_ptr<transform::Pass> pass, const char *label, bool keepDeclared) {
            std::cerr << "[cone] " << label << " start\n" << std::flush;
            transform::PassManager manager;
            manager.options().session = &session;
            manager.options().keepDeclaredSymbols = keepDeclared;
            manager.addPass(std::move(pass));
            transform::PassDiagnostics diagnostics;
            const auto result = manager.run(design, diagnostics);
            if (!result.success || diagnostics.hasError()) throw std::runtime_error(label);
        };
        transform::SimplifyOptions simplify;
        simplify.semantics = transform::ConstantFoldOptions::Semantics::TwoState;
        run(std::make_unique<transform::SimplifyPass>(simplify), "simplify", false);
        transform::RegToMemOptions memory;
        memory.enableOrderedWrites = true;
        run(std::make_unique<transform::RegToMemPass>(memory), "reg-to-mem", true);
        transform::AccumulateSinkOptions bank;
        bank.mode = transform::AccumulateSinkOptions::Mode::Bank;
        run(std::make_unique<transform::AccumulateSinkPass>(bank), "accumulate-sink", true);

        std::ofstream out(argv[2]);
        for (const auto &entry : design.graphs()) {
            grh::Graph &graph = *entry.second;
            // Writers of each state element, by the symbol attribute they carry.
            std::unordered_map<std::string, std::vector<OperationId>> writers;
            std::unordered_set<std::string> bankRegisters;
            for (OperationId id : graph.operations()) {
                const grh::Operation op = graph.getOperation(id);
                switch (op.kind()) {
                case OperationKind::kRegisterWritePort:
                    if (boolAttr(op, transform::kAccumulateAttr)) bankRegisters.insert(stringAttr(op, "regSymbol"));
                    else writers["r:" + stringAttr(op, "regSymbol")].push_back(id);
                    break;
                case OperationKind::kLatchWritePort: writers["l:" + stringAttr(op, "latchSymbol")].push_back(id); break;
                case OperationKind::kMemoryWritePort:
                case OperationKind::kMemoryFillPort:
                case OperationKind::kBehaviorStateGroup: writers["m:" + stringAttr(op, "memSymbol")].push_back(id); break;
                default: break;
                }
            }
            std::unordered_set<OperationId, grh::OperationIdHash> live;
            std::vector<OperationId> pending;
            auto mark = [&](OperationId id) {
                if (id.valid() && live.insert(id).second) pending.push_back(id);
            };
            for (const auto &port : graph.outputPorts()) mark(graph.valueDef(port.value));
            for (const auto &port : graph.inoutPorts()) { mark(graph.valueDef(port.out)); mark(graph.valueDef(port.oe)); }
            for (OperationId id : graph.operations()) {
                const grh::Operation op = graph.getOperation(id);
                switch (op.kind()) {
                case OperationKind::kDpicCall:
                case OperationKind::kSystemTask:
                case OperationKind::kSystemFunction:
                case OperationKind::kInstance:
                case OperationKind::kBlackbox:
                    mark(id);
                    break;
                default:
                    if (boolAttr(op, "hasSideEffects")) mark(id);
                    break;
                }
            }
            while (!pending.empty()) {
                const OperationId id = pending.back();
                pending.pop_back();
                const grh::Operation op = graph.getOperation(id);
                // On-demand task arguments are counter output: neither the
                // bank register nor the increment they add is a design value.
                if (boolAttr(op, transform::kAccumulateDemandAttr)) continue;
                std::string key;
                if (op.kind() == OperationKind::kRegisterReadPort) {
                    const std::string symbol = stringAttr(op, "regSymbol");
                    if (bankRegisters.contains(symbol)) continue;
                    key = "r:" + symbol;
                } else if (op.kind() == OperationKind::kLatchReadPort) key = "l:" + stringAttr(op, "latchSymbol");
                else if (op.kind() == OperationKind::kMemoryReadPort) key = "m:" + stringAttr(op, "memSymbol");
                if (!key.empty())
                    if (const auto it = writers.find(key); it != writers.end())
                        for (OperationId writer : it->second) mark(writer);
                for (ValueId operand : op.operands()) mark(graph.valueDef(operand));
            }
            std::map<std::string, std::size_t> kinds;
            std::size_t cone = 0, total = 0;
            for (OperationId id : graph.operations()) {
                const grh::Operation op = graph.getOperation(id);
                const OperationKind kind = op.kind();
                if (kind == OperationKind::kRegister || kind == OperationKind::kMemory || kind == OperationKind::kLatch ||
                    kind == OperationKind::kDpicImport || kind == OperationKind::kConstant) continue;
                ++total;
                if (live.contains(id)) continue;
                ++cone;
                ++kinds[std::string(grh::toString(kind))];
                std::string target = stringAttr(op, "regSymbol");
                if (target.empty()) target = stringAttr(op, "memSymbol");
                std::string result;
                if (!op.results().empty()) result = std::string(graph.symbolText(graph.valueSymbol(op.results().front())));
                out << op.symbolText() << '\t' << grh::toString(kind) << '\t'
                    << (boolAttr(op, transform::kAccumulateAttr) ? "bank" : boolAttr(op, transform::kAccumulateDemandAttr) ? "demand" : "-")
                    << '\t' << target << '\t' << result << '\n';
            }
            std::cerr << "[cone] graph " << graph.symbol() << " operations " << total << " counter-only " << cone
                      << " bank registers " << bankRegisters.size() << '\n';
            for (const auto &[kind, count] : kinds) std::cerr << "[cone]   " << kind << ' ' << count << '\n';
        }
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
