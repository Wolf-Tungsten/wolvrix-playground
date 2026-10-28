#pragma once
#include "emit/grhsim_activity_model.hpp"
#include <functional>
#include <unordered_map>
#include <unordered_set>
#include <stdexcept>
namespace event_polarity {
using namespace wolvrix::lib::grh;
using namespace wolvrix::lib::emit;
struct Level { uint64_t zero=0,one=0; bool operator==(const Level &) const=default; };
using Known=std::unordered_map<ValueId,Level,ValueIdHash>;
// Current levels are caller-supplied facts for symbolic scenarios. Event may
// masks alone do not imply these levels; the caller must provide the contract.
class Prover {
    const Graph &graph;const Known &known;
    std::unordered_map<ValueId,Level,ValueIdHash> memo;
    std::unordered_set<ValueId,ValueIdHash> active;
public:
    Prover(const Graph &g,const Known &k):graph(g),known(k) {
        for(auto [v,l]:known)if(graph.valueWidth(v)!=1||(l.zero&l.one))
            throw std::invalid_argument("invalid current-level scenario fact");
    }
    Level get(ValueId v,unsigned depth=0) {
        if(auto i=known.find(v);i!=known.end())return i->second;
        if(auto i=memo.find(v);i!=memo.end())return i->second;
        if(graph.valueWidth(v)!=1||depth>256||active.contains(v))return {};
        if(graph.valueIsInput(v))return {};
        const auto id=graph.valueDef(v);if(!id.valid())return {};
        const auto op=graph.getOperation(id);const auto &args=op.operands();
        using K=OperationKind;const auto kind=op.kind();Level r{};active.insert(v);
        auto operand=[&](std::size_t i){return get(args[i],depth+1);};
        if(args.size()==1&&(kind==K::kAssign||kind==K::kNot||kind==K::kLogicNot)) {
            r=operand(0);if(kind!=K::kAssign)std::swap(r.zero,r.one);
        } else if(args.size()==2&&(kind==K::kAnd||kind==K::kLogicAnd||kind==K::kOr||kind==K::kLogicOr||kind==K::kXor)) {
            const auto a=operand(0),b=operand(1);
            if(kind==K::kAnd||kind==K::kLogicAnd)r={a.zero|b.zero,a.one&b.one};
            else if(kind==K::kOr||kind==K::kLogicOr)r={a.zero&b.zero,a.one|b.one};
            else r={(a.zero&b.zero)|(a.one&b.one),(a.zero&b.one)|(a.one&b.zero)};
        } else if(args.size()==3&&kind==K::kMux) {
            const auto s=operand(0),t=operand(1),f=operand(2);
            r={(s.one&t.zero)|(s.zero&f.zero)|(t.zero&f.zero),
               (s.one&t.one)|(s.zero&f.one)|(t.one&f.one)};
        }
        active.erase(v);memo.emplace(v,r);return r;
    }
};
inline GrhSimActivityReport analyze(const Graph &graph,const GrhSimExecutionPlan &plan,
        const GrhSimActivitySeeds &original,const Known &known) {
    const auto options=GrhSimActivityOptions{};
    auto activity=analyzeGrhSimActivity(graph,plan,original,options);
    if(known.empty())return activity;
    Prover prover(graph,known);std::unordered_map<ValueId,Level,ValueIdHash> derived;
    for(const auto &event:plan.events)for(auto v:event.values)if(!original.events.contains(v)) {
        const auto proof=prover.get(v);if(proof.zero||proof.one)derived[v]=proof;
    }
    auto seeds=original;
    for(unsigned round=0;round<128;++round) {
        bool changed=false;
        for(auto [v,proof]:derived) {
            const auto mask=grhsimActivityInRange(activity.values.at(v.index),0,1);
            const GrhSimEventActivity next{mask&~proof.zero,mask&~proof.one,mask};
            const auto old=seeds.events.find(v);
            if(old==seeds.events.end()||old->second.posedge!=next.posedge||old->second.negedge!=next.negedge||old->second.anyedge!=next.anyedge) {
                seeds.events[v]=next;changed=true;
            }
        }
        if(!changed)return activity;
        auto next=analyzeGrhSimActivity(graph,plan,seeds,options);
        for(std::size_t i=0;i<activity.eventMasks.size();++i)
            if(next.eventMasks[i]&~activity.eventMasks[i])throw std::runtime_error("event phase refinement grew a may set");
        activity=std::move(next);
    }
    throw std::runtime_error("event phase refinement did not converge");
}
} // namespace event_polarity
