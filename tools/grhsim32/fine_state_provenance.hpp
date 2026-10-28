// Source provenance preserves writer ownership until assignment time.
#pragma once
#include "arrival_context_cost.hpp"
#include "core/grh.hpp"
#include "emit/grhsim_activity_model.hpp"
#include "trigger_context_activity.hpp"
#include "state_hold_analysis.hpp"
#include <unordered_set>

namespace arrival_context {
struct VectorHash {
    std::size_t operator()(const std::vector<uint32_t> &v) const {
        std::size_t h=0xcbf29ce484222325ULL;
        for(auto x:v)h=(h^x)*0x100000001b3ULL;
        return h;
    }
};
class Provenance {
    using Graph=wolvrix::lib::grh::Graph;
    using OpId=wolvrix::lib::grh::OperationId;
    using ValueId=wolvrix::lib::grh::ValueId;
    using Kind=wolvrix::lib::grh::OperationKind;
    const Graph &graph;
    const wolvrix::lib::emit::GrhSimActivityReport &activity;
    const std::map<std::string,uint32_t> &owners;
    ValueId clock;
    const trigger_context::Analysis &causes;
    std::map<uint32_t,std::set<uint32_t>> rootCauses;
    uint32_t annotate(uint32_t sid,const std::vector<uint32_t> &ids) {
        for(auto rid:sets.at(sid))rootCauses[rid].insert(ids.begin(),ids.end());
        return sid;
    }
    std::vector<uint32_t> memo;
    std::vector<uint8_t> visiting;
    std::map<std::tuple<uint32_t,uint64_t,uint32_t,std::string>,uint32_t> rootIds;
    std::map<uint32_t,std::string> rootStates;
    std::unordered_map<std::vector<uint32_t>,uint32_t,VectorHash> setIds;
    uint32_t fallback=0;
    template<class T> static T attr(const wolvrix::lib::grh::Operation &op,const char *name) {
        const auto a=op.attr(name);return a&&std::holds_alternative<T>(*a)?std::get<T>(*a):T{};
    }
    uint32_t root(uint32_t owner,uint64_t mask,uint32_t kind,const std::string &stateName = {}) {
        if(!mask)return 0;
        auto [it,added]=rootIds.try_emplace({owner,mask,kind,stateName},roots.size());
        if(added) { roots.push_back({owner,mask,kind}); if(!stateName.empty())rootStates[it->second]=stateName; }
        return intern({it->second});
    }
    std::optional<uint32_t> fixed(OpId id) {
        const auto op=graph.getOperation(id); const auto kind=op.kind();
        if(kind==Kind::kConstant||kind==Kind::kRegister||kind==Kind::kLatch||kind==Kind::kMemory||kind==Kind::kDpicImport)
            return 0;
        if(kind==Kind::kRegisterReadPort||kind==Kind::kLatchReadPort) return state(op);
        if(kind==Kind::kRegisterWritePort||kind==Kind::kLatchWritePort||kind==Kind::kMemoryWritePort||
           kind==Kind::kMemoryFillPort||kind==Kind::kDpicCall||kind==Kind::kSystemTask)
            return annotate(root(noOwner,activity.operationMasks.at(id.index),0),
                causes.operationCauses.contains(id.index)?causes.operationCauses.at(id.index):std::vector<uint32_t>{});
        return std::nullopt;
    }
    uint32_t state(const wolvrix::lib::grh::Operation &op) {
        const auto key=op.kind()==Kind::kMemoryReadPort?"memSymbol":
                       op.kind()==Kind::kLatchReadPort?"latchSymbol":"regSymbol";
        const auto symbol=attr<std::string>(op,key);
        const auto mask=activity.stateMasks.find(symbol);
        if(mask==activity.stateMasks.end()||!mask->second)return 0;
        const auto owner=owners.find(symbol);
        if(owner==owners.end()||owner->second==noOwner){++unownedStateReferences;return root(noOwner,unknown,0);}
        return annotate(root(owner->second,mask->second,1,symbol),causes.stateCauses.at(symbol));
    }
    uint32_t value(ValueId id) {
        if(graph.valueIsInput(id))return root(noOwner,id==clock?3:unknown,0);
        const auto op=graph.valueDef(id);
        return op.valid()?memo.at(op.index):fallback;
    }
public:
    std::vector<Root> roots;
    std::vector<std::vector<uint32_t>> sets;
    uint64_t cycleEdges=0,unownedStateReferences=0,visits=0;
    Provenance(const Graph &g,const wolvrix::lib::emit::GrhSimActivityReport &a,
               const std::map<std::string,uint32_t> &o,ValueId c,const trigger_context::Analysis &t)
        :graph(g),activity(a),owners(o),clock(c),causes(t) {
        std::size_t n=1;for(auto op:g.operations())n=std::max(n,std::size_t(op.index)+1);
        memo.assign(n,UINT32_MAX);visiting.resize(n);
        intern({});fallback=root(noOwner,unknown,0);
    }
    void writeCauseLinks(const std::filesystem::path &out) const {
        std::ofstream stateFile(out/"root_states.txtdata");
        stateFile<<"grhsim-fine-root-states-v1 "<<rootStates.size()<<'\n';
        for(const auto &[id,name]:rootStates)stateFile<<id<<' '<<std::quoted(name)<<'\n';
        std::ofstream file(out/"root_causes.txtdata");
        file<<"grhsim-trigger-root-causes-v1 "<<roots.size()<<' '<<causes.causes.size()<<'\n';
        for(uint32_t id=0;id<roots.size();++id) {
            file<<id<<' '<<(rootCauses.contains(id)?rootCauses.at(id).size():0);
            if(rootCauses.contains(id))for(auto cause:rootCauses.at(id))file<<' '<<cause;
            file<<'\n';
        }
        if(!file)throw std::runtime_error("root cause links output failed");
    }
    uint32_t intern(std::vector<uint32_t> v) {
        std::sort(v.begin(),v.end());v.erase(std::unique(v.begin(),v.end()),v.end());
        auto [it,added]=setIds.try_emplace(v,sets.size());
        if(added)sets.push_back(std::move(v));
        return it->second;
    }
    uint32_t merge(const std::vector<uint32_t> &ids) {
        if(ids.empty())return 0;
        if(std::all_of(ids.begin(),ids.end(),[&](auto x){return x==ids[0];}))return ids[0];
        std::vector<uint32_t> v;
        for(auto id:ids) v.insert(v.end(),sets.at(id).begin(),sets.at(id).end());
        return intern(std::move(v));
    }
    uint32_t operation(OpId requested) {
        if(memo.at(requested.index)!=UINT32_MAX)return memo[requested.index];
        std::vector<std::pair<OpId,std::size_t>> stack{{requested,0}};
        while(!stack.empty()) {
            auto &[id,next]=stack.back();
            if(memo[id.index]!=UINT32_MAX){visiting[id.index]=0;stack.pop_back();continue;}
            if(auto terminal=fixed(id)){memo[id.index]=*terminal;visiting[id.index]=0;stack.pop_back();++visits;continue;}
            visiting[id.index]=1;
            const auto op=graph.getOperation(id);
            bool pushed=false;
            while(next<op.operands().size()) {
                const auto operand=op.operands()[next++];
                const auto dependency=graph.valueDef(operand);
                if(!dependency.valid()||graph.valueIsInput(operand)||memo[dependency.index]!=UINT32_MAX)continue;
                if(visiting[dependency.index]){++cycleEdges;continue;}
                stack.push_back({dependency,0});pushed=true;break;
            }
            if(pushed)continue;
            std::vector<uint32_t> sources;
            for(auto operand:op.operands()) {
                auto s=value(operand);sources.push_back(s==UINT32_MAX?fallback:s);
            }
            if(op.kind()==Kind::kMemoryReadPort)sources.push_back(state(op));
            if(op.kind()==Kind::kSystemFunction)sources.push_back(fallback);
            memo[id.index]=merge(sources);
            visiting[id.index]=0;stack.pop_back();++visits;
        }
        return memo[requested.index];
    }
};
} // namespace arrival_context
