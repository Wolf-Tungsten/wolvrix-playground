#pragma once
#include "core/grh.hpp"
#include "emit/grhsim_execution_plan.hpp"
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <set>

namespace state_hold {
using namespace wolvrix::lib::grh;
// Some denotes a syntactic old-value arm, not a proved feasible path or rate.
enum class Hold { None=0, Some=1, Always=2 };
class Analyzer {
    const Graph &graph;
    std::string state;
    OperationKind readKind;
    uint32_t width;
    std::map<uint32_t,Hold> memo;
    std::set<uint32_t> active;
public:
    Analyzer(const Graph &g,std::string s,OperationKind k,uint32_t w):
        graph(g),state(std::move(s)),readKind(k),width(w) {}
    Hold get(ValueId v,unsigned depth=0) {
        if(depth>256 || graph.valueWidth(v)!=width || graph.valueIsInput(v))return Hold::None;
        if(memo.contains(v.index))return memo.at(v.index);
        if(!active.insert(v.index).second)return Hold::None;
        auto result=Hold::None;
        const auto id=graph.valueDef(v);
        if(id.valid()) {
            const auto op=graph.getOperation(id);
            if(op.kind()==readKind) {
                const auto a=op.attr(readKind==OperationKind::kRegisterReadPort?"regSymbol":"latchSymbol");
                if(a && std::holds_alternative<std::string>(*a) && std::get<std::string>(*a)==state)result=Hold::Always;
            } else if(op.kind()==OperationKind::kAssign && op.operands().size()==1)result=get(op.operands()[0],depth+1);
            else if(op.kind()==OperationKind::kMux && op.operands().size()==3) {
                const auto a=get(op.operands()[1],depth+1),b=get(op.operands()[2],depth+1);
                if(a==Hold::Always && b==Hold::Always)result=Hold::Always;
                else if(a!=Hold::None || b!=Hold::None)result=Hold::Some;
            }
        }
        active.erase(v.index);memo[v.index]=result;return result;
    }
};
inline Hold classify(const Graph &g,const wolvrix::lib::emit::GrhSimExecutionPlan::Write &w) {
    const auto op=g.getOperation(w.operation);
    if(w.memory || op.operands().size()<3)return Hold::None;
    if(op.kind()!=OperationKind::kRegisterWritePort && op.kind()!=OperationKind::kLatchWritePort)return Hold::None;
    Analyzer a(g,w.state,op.kind()==OperationKind::kRegisterWritePort?OperationKind::kRegisterReadPort:OperationKind::kLatchReadPort,w.dataWidth);
    return a.get(op.operands()[1]);
}
inline void write(const Graph &g,const wolvrix::lib::emit::GrhSimExecutionPlan &plan,const std::filesystem::path &out) {
    std::ofstream f(out/"writer_holds.csv");
    f<<"operation,memory,hold_class,enable_proof,mask_proof\n";
    std::map<int,uint64_t> counts;
    for(const auto &w:plan.writes) {
        const int h=int(classify(g,w));++counts[h];
        f<<w.operation.index<<','<<w.memory<<','<<h<<','<<int(w.enableProof)<<','<<int(w.maskNonzeroProof)<<'\n';
    }
    if(!f)throw std::runtime_error("writer hold output failed");
    std::cout<<"STATE HOLD writers="<<plan.writes.size()<<" none="<<counts[0]<<" conditional_path="<<counts[1]<<" all_paths_old="<<counts[2]<<std::endl;
}
}
