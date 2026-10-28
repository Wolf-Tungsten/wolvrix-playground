#pragma once
#include "event_polarity_activity.hpp"
#include <fstream>
#include <filesystem>
#include <map>
#include <optional>
#include <set>

// Two conditional views of one unchanged execution plan. The clock slice is
// NOT a complete may envelope; the complete envelope is retained independently.
namespace trigger_context {
using namespace event_polarity;
constexpr uint64_t risk = kGrhSimUnknownActivity;
inline uint64_t previous(uint64_t m) { return ((m & 1) << 1) | ((m & 2) >> 1); }
inline uint64_t edgeMask(const GrhSimEventActivity &e, const std::string &edge) {
    return edge == "posedge" ? e.posedge : edge == "negedge" ? e.negedge : e.anyedge;
}
inline std::optional<GrhSimEventActivity> alias(const Graph &g, ValueId v,
                                             const GrhSimActivitySeeds &seeds) {
    bool inverted = false; std::unordered_set<ValueId,ValueIdHash> seen;
    while (seen.insert(v).second) {
        if (auto it = seeds.events.find(v); it != seeds.events.end()) {
            auto e = it->second; if (inverted) std::swap(e.posedge,e.negedge);
            e.anyedge |= e.posedge | e.negedge; return e;
        }
        if (g.valueWidth(v) != 1 || g.valueIsInput(v)) break;
        const auto id = g.valueDef(v); if (!id.valid()) break;
        const auto op = g.getOperation(id); using K = OperationKind;
        if (op.operands().size() != 1 || g.valueWidth(op.operands()[0]) != 1 ||
            (op.kind()!=K::kAssign && op.kind()!=K::kNot && op.kind()!=K::kLogicNot)) break;
        inverted ^= op.kind()!=K::kAssign; v=op.operands()[0];
    }
    return std::nullopt;
}
// Cut at state and primary inputs: synchronous state changes are additional
// event causes, not direct combinational aliases of the caller's clock.
class ClockCone {
    const Graph &graph; ValueId clock;
    std::unordered_map<ValueId,bool,ValueIdHash> memo;
    std::unordered_set<ValueId,ValueIdHash> active;
public:
    ClockCone(const Graph &g,ValueId c):graph(g),clock(c) {}
    bool get(ValueId v,unsigned depth=0) {
        if (v==clock) return true;
        if (auto it=memo.find(v);it!=memo.end()) return it->second;
        if (depth>256 || active.contains(v) || graph.valueIsInput(v)) return false;
        const auto id=graph.valueDef(v); if (!id.valid()) return false;
        const auto op=graph.getOperation(id); using K=OperationKind;
        if (op.kind()==K::kRegisterReadPort || op.kind()==K::kLatchReadPort ||
            op.kind()==K::kMemoryReadPort || op.kind()==K::kDpicCall || op.kind()==K::kSystemFunction) return false;
        active.insert(v); bool result=false;
        for(auto x:op.operands()) result |= get(x,depth+1);
        active.erase(v); memo[v]=result; return result;
    }
};
struct Cause {
    uint32_t operation=0,ordinal=0,value=UINT32_MAX;
    std::string edge;
    uint64_t full=0,clock=0,control=0;
    Level levels{};
    bool direct=false,combinationalClock=false;
};
struct Analysis {
    GrhSimActivityReport full,clock,control,projected;
    std::vector<Cause> causes;
    std::map<uint32_t,std::vector<uint32_t>> operationCauses;
    std::map<std::string,std::vector<uint32_t>> stateCauses;
    uint64_t fullEventReferences=0;
};
inline uint64_t project(uint64_t full,uint64_t normal,uint64_t control) {
    if ((normal & 3) & ~full) throw std::runtime_error("clock slice exceeds full may mask");
    // Preserve even conservative residual envelope uncertainty. This is a risk
    // axis, not a fabricated probability, frequency or third elapsed phase.
    return (normal & 3) | ((control || (normal & risk) || (full & ~normal)) ? risk : 0);
}
inline Analysis analyze(const Graph &graph,const GrhSimExecutionPlan &plan,
                        const GrhSimActivitySeeds &original,ValueId clock) {
    const auto it=original.events.find(clock);
    if(it==original.events.end() || it->second.posedge!=1 || it->second.negedge!=2 ||
       graph.valueWidth(clock)!=1) throw std::invalid_argument("explicit alternating-clock scenario required");
    Analysis a;
    const Known known{{clock,{2,1}}}; Prover proof(graph,known); ClockCone cone(graph,clock);
    a.full=event_polarity::analyze(graph,plan,original,known);
    auto normal=original,control=original;
    for(const auto &input:plan.inputs) {
        normal.inputs[input.value]=input.value==clock ? GrhSimActivityRanges{{0,1,3}} : GrhSimActivityRanges{};
        control.inputs[input.value]=input.value==clock ? GrhSimActivityRanges{} :
            GrhSimActivityRanges{{0,static_cast<uint32_t>(graph.valueWidth(input.value)),risk}};
    }
    for(auto &[v,e]:control.events) e={};
    std::unordered_map<ValueId,GrhSimEventActivity,ValueIdHash> fullEvents;
    for(const auto &event:plan.events) for(auto v:event.values) {
        if(fullEvents.contains(v)) continue;
        const auto resolved=alias(graph,v,original); const auto level=proof.get(v);
        GrhSimEventActivity full{};
        if(resolved) full=*resolved;
        else {
            const auto mask=grhsimActivityInRange(a.full.values.at(v.index),0,graph.valueWidth(v));
            full={mask & ~level.zero,mask & ~level.one,mask};
        }
        fullEvents[v]=full;
        if(resolved) { normal.events[v]=full; control.events[v]={}; }
        else {
            GrhSimEventActivity n{};
            if(cone.get(v)) {
                // Hold non-clock controls fixed. An edge needs both a possible
                // previous level and a possible current level, unlike the full
                // asynchronous envelope which only excludes the current level.
                n.posedge=full.posedge & 3 & ~level.zero & ~previous(level.one);
                n.negedge=full.negedge & 3 & ~level.one & ~previous(level.zero);
                n.anyedge=n.posedge|n.negedge;
            }
            normal.events[v]=n;
            control.events[v]={full.posedge ? risk:0,full.negedge ? risk:0,full.anyedge ? risk:0};
        }
    }
    auto options=GrhSimActivityOptions{};
    options.unseededEvents=GrhSimUnseededEvents::SeededRootsOnly;
    a.clock=analyzeGrhSimActivity(graph,plan,normal,options);
    a.control=analyzeGrhSimActivity(graph,plan,control,options);
    for(const auto &event:plan.events) {
        uint64_t full=0,normalMask=0,controlMask=0;
        for(uint32_t i=0;i<event.values.size();++i) {
            const auto v=event.values[i]; const auto &edge=event.edges.at(i);
            Cause c{event.operation.index,i,v.index,edge,edgeMask(fullEvents.at(v),edge),
                edgeMask(normal.events.at(v),edge),edgeMask(control.events.at(v),edge),
                proof.get(v),bool(alias(graph,v,original)),cone.get(v)};
            full|=c.full;normalMask|=c.clock;controlMask|=c.control;
            a.operationCauses[c.operation].push_back(a.causes.size());a.causes.push_back(c);
            ++a.fullEventReferences;
        }
        if(full!=a.full.eventMasks.at(event.operation.index) || normalMask!=a.clock.eventMasks.at(event.operation.index) ||
            controlMask!=a.control.eventMasks.at(event.operation.index)) throw std::runtime_error("event cause OR does not reconstruct report");
    }
    for(const auto &write:plan.writes) {
        if(!a.operationCauses.contains(write.operation.index)) {
            const auto op=write.operation.index;
            a.operationCauses[op].push_back(a.causes.size());
            a.causes.push_back({op,0,UINT32_MAX,"unqualified",a.full.eventMasks.at(op),
                               a.clock.eventMasks.at(op),a.control.eventMasks.at(op),{},false,false});
        }
        auto &ids=a.stateCauses[write.state];const auto &source=a.operationCauses.at(write.operation.index);
        ids.insert(ids.end(),source.begin(),source.end());
    }
    a.projected=a.full;
    auto merge=[&](auto &dest,const auto &normalMasks,const auto &riskMasks) {
        for(std::size_t i=0;i<dest.size();++i) dest[i]=project(dest[i],normalMasks.at(i),riskMasks.at(i));
    };
    merge(a.projected.operationMasks,a.clock.operationMasks,a.control.operationMasks);
    merge(a.projected.eventMasks,a.clock.eventMasks,a.control.eventMasks);
    merge(a.projected.writeMasks,a.clock.writeMasks,a.control.writeMasks);
    merge(a.projected.computeGroupMasks,a.clock.computeGroupMasks,a.control.computeGroupMasks);
    for(auto &[name,mask]:a.projected.stateMasks)
        mask=project(mask,a.clock.stateMasks.at(name),a.control.stateMasks.at(name));
    for(auto v:graph.values()) {
        const auto &f=a.full.values[v.index],&n=a.clock.values[v.index],&c=a.control.values[v.index];
        std::set<uint32_t> cuts{0,static_cast<uint32_t>(graph.valueWidth(v))};
        for(const auto *ranges:{&f,&n,&c}) for(const auto &r:*ranges){cuts.insert(r.begin);cuts.insert(r.end);}
        auto &dest=a.projected.values[v.index];dest.clear();
        for(auto p=cuts.begin(),q=std::next(p);q!=cuts.end();++p,++q) {
            const auto mask=project(grhsimActivityInRange(f,*p,*q),grhsimActivityInRange(n,*p,*q),grhsimActivityInRange(c,*p,*q));
            if(mask)dest.push_back({*p,*q,mask});
        }
    }
    return a;
}
inline void writeCauses(const Analysis &a,const GrhSimExecutionPlan &plan,const std::filesystem::path &out) {
    std::map<uint32_t,const GrhSimExecutionPlan::Write *> writes;
    for(const auto &w:plan.writes)writes[w.operation.index]=&w;
    std::ofstream file(out/"trigger_causes.csv");
    file<<"cause,operation,ordinal,event_value,edge,direct_clock_alias,combinational_clock,full_mask,clock_mask,control_mask,proven_zero,proven_one,enable_value,enable_proof,write_mask_value,write_mask_proof,full_write_mask,clock_write_mask,control_write_mask\n";
    for(uint32_t id=0;id<a.causes.size();++id) {
        const auto &c=a.causes[id];const auto w=writes.contains(c.operation)?writes.at(c.operation):nullptr;
        file<<id<<','<<c.operation<<','<<c.ordinal<<','<<c.value<<','<<c.edge<<','<<c.direct<<','<<c.combinationalClock
            <<','<<c.full<<','<<c.clock<<','<<c.control<<','<<c.levels.zero<<','<<c.levels.one
            <<','<<(w&&w->enable.valid()?w->enable.index:UINT32_MAX)<<','<<(w?int(w->enableProof):-1)
            <<','<<(w&&w->mask.valid()?w->mask.index:UINT32_MAX)<<','<<(w?int(w->maskNonzeroProof):-1)
            <<','<<a.full.writeMasks[c.operation]<<','<<a.clock.writeMasks[c.operation]<<','<<a.control.writeMasks[c.operation]<<'\n';
    }
    if(!file)throw std::runtime_error("trigger cause output failed");
}
} // namespace trigger_context
