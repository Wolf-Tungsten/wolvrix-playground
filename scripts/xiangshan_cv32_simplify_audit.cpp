// Offline replay of the frozen simplify stage; never emits or runs a model.
// Compile separately against each frozen library and its matching headers.
#include "core/grh.hpp"
#include "core/transform.hpp"
#include "transform/simplify.hpp"
#ifdef AUDIT_SCHEDULE
#include "transform/activity_schedule.hpp"
#include "transform/reg_to_mem.hpp"
#include <numeric>
#include <unordered_map>
#endif
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <sstream>
#include <stdexcept>

using namespace wolvrix::lib;

std::string quoted(std::string_view input) {
    std::string result="\"";
    for (const unsigned char c:input) {
        if(c=='"'||c=='\\') {result+='\\';result+=c;}
        else if(c<32) {const char *digits="0123456789abcdef";result+="\\u00";result+=digits[c>>4];result+=digits[c&15];}
        else result+=c;
    }
    return result+'"';
}
int64_t attr(const grh::Operation &op,const char *key,int64_t fallback=-1) {
    const auto v=op.attr(key);return v&&std::holds_alternative<int64_t>(*v)?std::get<int64_t>(*v):fallback;
}

void inventory(const grh::Graph &g,const std::string &path) {
    std::ofstream out(path);std::map<std::string,uint64_t> kinds;bool first=true;
    out<<"{\"packed_concats\":[";
    for(const auto id:g.operations()) {
        const auto op=g.getOperation(id);++kinds[std::string(grh::toString(op.kind()))];
        if(op.kind()!=grh::OperationKind::kConcat || attr(op,"svPackedArray.version")!=1)continue;
        if(!first)out<<',';first=false;
        const auto result=g.getValue(op.results().front());
        std::map<int32_t,uint64_t> widths;std::map<std::string,uint64_t> users;
        for(const auto v:op.operands())++widths[g.valueWidth(v)];
        for(const auto &user:result.users())++users[std::string(grh::toString(g.getOperation(user.operation).kind()))];
        out<<"{\"operation\":"<<quoted(op.symbolText())<<",\"op_id\":"<<id.index
           <<",\"value\":"<<quoted(result.symbolText())<<",\"value_id\":"<<result.id().index
           <<",\"width\":"<<result.width()<<",\"operands\":"<<op.operands().size()
           <<",\"element_count\":"<<attr(op,"svPackedArray.elementCount")
           <<",\"element_width\":"<<attr(op,"svPackedArray.elementWidth")<<",\"width_histogram\":{";
        bool f=true;for(auto [w,n]:widths){if(!f)out<<',';f=false;out<<quoted(std::to_string(w))<<':'<<n;}
        out<<"},\"users\":{";f=true;for(const auto &[k,n]:users){if(!f)out<<',';f=false;out<<quoted(k)<<':'<<n;}
        out<<"},\"inputs\":[";f=true;
        for(const auto v:op.operands()) {
            if(!f)out<<',';f=false;const auto value=g.getValue(v);const auto def=g.valueDef(v);
            out<<"{\"value\":"<<quoted(value.symbolText())<<",\"width\":"<<value.width();
            if(def.valid()) {
                const auto producer=g.getOperation(def);
                out<<",\"kind\":"<<quoted(grh::toString(producer.kind()));
                if(producer.kind()==grh::OperationKind::kSliceStatic)
                    out<<",\"low\":"<<attr(producer,"sliceStart")<<",\"high\":"<<attr(producer,"sliceEnd")
                       <<",\"source\":"<<quoted(g.getValue(producer.operands().front()).symbolText());
            }
            out<<'}';
        }
        out<<"]}";
    }
    out<<"],\"op_counts\":{";first=true;
    for(const auto &[k,n]:kinds){if(!first)out<<',';first=false;out<<quoted(k)<<':'<<n;}
    out<<"},\"value_count\":"<<g.values().size()<<"}\n";
    if(!out)throw std::runtime_error("audit output failed");
}

#ifdef AUDIT_SCHEDULE
void scheduleInventory(grh::Design &design,const std::string &prefix) {
    transform::SessionStore session;
    const auto run=[&](std::unique_ptr<transform::Pass> pass) {
        transform::PassManager pm;pm.options().session=&session;
        pm.options().logLevel=LogLevel::Info;
        pm.options().logSink=[](LogLevel,std::string_view tag,std::string_view message){std::cerr<<'['<<tag<<"] "<<message<<'\n';};
        pm.addPass(std::move(pass));transform::PassDiagnostics diag;
        if(!pm.run(design,diag).success||diag.hasError())throw std::runtime_error("schedule replay failed");
    };
    transform::RegToMemOptions memory;memory.enableOrderedWrites=true;
    run(std::make_unique<transform::RegToMemPass>(memory));
    transform::ActivityScheduleOptions options;options.path="SimTop";
    options.maxOpInComputeSupernode=108;options.maxOpInComputeNode=108;
    options.splitOversizeComputeNodes=false;options.splitOversizeComputeNodeMaxOps=108;
    options.eventRegions=true;options.eventRegionsShared=true;
#ifdef AUDIT_NO_SHARED
    options.eventRegionsShared=false;
#endif
    run(std::make_unique<transform::ActivitySchedulePass>(options));
    const auto &groups=dynamic_cast<const transform::SessionSlotValue<transform::ActivityScheduleSupernodeToOps>&>(
        *session.at("SimTop.activity_schedule.supernode_to_ops")).value;
    const auto &g=*design.findGraph("SimTop");
    // Compact exact ownership/def-use mapping for cross-schedule attribution.
    // Symbols (not transient ValueIds) are used across the two frozen replays.
    std::ofstream members(prefix+"-members.tsv"),edgesOut(prefix+"-work-edges.tsv");
    for(std::size_t sid=0;sid<groups.size();++sid)for(const auto id:groups[sid]) {
        const auto op=g.getOperation(id);members<<op.symbolText()<<'\t'<<sid<<'\n';
        if(op.kind()==grh::OperationKind::kConstant || op.kind()==grh::OperationKind::kRegisterReadPort ||
           op.kind()==grh::OperationKind::kLatchReadPort)continue;
        for(const auto v:op.operands()) {
            const auto def=g.valueDef(v);if(!def.valid())continue;const auto producer=g.getOperation(def);
            if(producer.kind()==grh::OperationKind::kConstant || producer.kind()==grh::OperationKind::kRegisterReadPort ||
               producer.kind()==grh::OperationKind::kLatchReadPort)continue;
            edgesOut<<producer.symbolText()<<'\t'<<op.symbolText()<<'\n';
        }
    }
    std::ofstream out(prefix+"-connectivity.json");out<<"{\"groups\":[";
    bool first=true;
    for(std::size_t sid=0;sid<groups.size();++sid) {
        const auto &ops=groups[sid];
        std::unordered_map<uint32_t,std::size_t> vertices;
        std::map<std::string,uint64_t> kinds;
        for(const auto id:ops) {
            const auto op=g.getOperation(id);++kinds[std::string(grh::toString(op.kind()))];
            if(op.kind()!=grh::OperationKind::kRegisterReadPort && op.kind()!=grh::OperationKind::kLatchReadPort &&
               op.kind()!=grh::OperationKind::kConstant)vertices.emplace(id.index,vertices.size());
        }
        std::vector<std::size_t> parent(vertices.size());std::iota(parent.begin(),parent.end(),0u);
        const auto root=[&](std::size_t v){while(parent[v]!=v){parent[v]=parent[parent[v]];v=parent[v];}return v;};
        uint64_t edges=0;
        for(const auto id:ops)if(vertices.contains(id.index)) {
            const auto op=g.getOperation(id);
            for(const auto value:op.operands()) {
                const auto def=g.valueDef(value);
                if(!def.valid()||!vertices.contains(def.index))continue;
                ++edges;parent[root(vertices.at(id.index))]=root(vertices.at(def.index));
            }
        }
        std::map<std::size_t,uint64_t> sizes;for(std::size_t i=0;i<parent.size();++i)++sizes[root(i)];
        uint64_t singleton=0,largest=0;for(const auto &[_,n]:sizes){singleton+=n==1;largest=std::max(largest,n);}
        if(!first)out<<',';first=false;
        out<<"{\"group\":"<<sid<<",\"ops\":"<<ops.size()<<",\"work_vertices\":"<<vertices.size()
           <<",\"internal_edges\":"<<edges<<",\"components\":"<<sizes.size()<<",\"singletons\":"<<singleton
           <<",\"largest_component\":"<<largest<<",\"kinds\":{";
        bool f=true;for(const auto &[k,n]:kinds){if(!f)out<<',';f=false;out<<quoted(k)<<':'<<n;}
        out<<"}}";
    }
    out<<"],\"limit\":\"Static def-use weak components of non-constant, non-state-read operations; external/common roots do not connect vertices. Not execution counts or a profitability proof.\"}\n";
}
#endif

int main(int argc,char **argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: audit graph.json output-prefix");
        std::ifstream input(argv[1]);if(!input)throw std::runtime_error("missing graph");
        std::cerr<<"load graph\n";
        auto design=grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input),{}));
        auto *graph=design.findGraph("SimTop");if(!graph)throw std::runtime_error("missing SimTop");
        inventory(*graph,std::string(argv[2])+"-input.json");
        transform::SimplifyOptions options;options.semantics=transform::ConstantFoldOptions::Semantics::TwoState;
        transform::PassManager manager;manager.options().keepDeclaredSymbols=false;
        manager.addPass(std::make_unique<transform::SimplifyPass>(options));
        transform::PassDiagnostics diagnostics;std::cerr<<"simplify\n";
        const auto result=manager.run(design,diagnostics);
        if(!result.success||diagnostics.hasError())throw std::runtime_error("simplify failed");
        inventory(*graph,std::string(argv[2])+"-simplified.json");
#ifdef AUDIT_SCHEDULE
        scheduleInventory(design,argv[2]);
#endif
        std::cerr<<"offline inventory done\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
