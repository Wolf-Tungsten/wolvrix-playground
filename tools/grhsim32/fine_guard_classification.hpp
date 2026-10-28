#pragma once
#include "arrival_context_cost.hpp"
#include <sstream>

// Static trigger classes, not activity probabilities. Even an unconditional
// clocked write can publish no change when its next value equals its old value.
namespace fine_guard {
struct Cause {
    uint64_t clockWrite=0;
    bool direct=false;
    int enable=-1, mask=-1;
    int hold=0;
};
struct RootClass { uint64_t unguardedClock=0, guardedClock=0; };
inline RootClass classify(const arrival_context::Root &root,const std::vector<Cause> &causes) {
    uint64_t eligible=0,conditional=0;
    for(const auto &cause:causes) {
        const auto mask=cause.clockWrite&root.mask&3;
        if(cause.direct&&cause.enable==2&&cause.mask==2&&(root.kind!=1||cause.hold==0))eligible|=mask;
        else conditional|=mask;
    }
    // Fine roots retain state identity, but all writers of one state still
    // contribute. An eligible writer must not conceal another conditional writer.
    auto unguarded=eligible&~conditional;
    if(causes.empty()&&root.kind==0&&root.owner==arrival_context::noOwner)unguarded=root.mask&3;
    return {unguarded,(root.mask&3)&~unguarded};
}
inline std::vector<std::string> split(const std::string &line) {
    std::vector<std::string> row;std::istringstream in(line);std::string field;
    while(std::getline(in,field,','))row.push_back(field);
    return row;
}
inline std::vector<RootClass> read(const arrival_context::Model &model,const std::filesystem::path &folder) {
    std::map<uint32_t,int> holds;
    {std::ifstream f(folder/"writer_holds.csv");std::string line;std::getline(f,line);
     while(std::getline(f,line)){auto r=split(line);if(r.size()!=5)throw std::runtime_error("bad hold row");holds[std::stoul(r[0])]=std::stoi(r[2]);}
     if(!f.eof())throw std::runtime_error("missing writer holds");}
    std::vector<Cause> causes;std::ifstream input(folder/"trigger_causes.csv");std::string line;
    if(!std::getline(input,line))throw std::runtime_error("missing trigger cause header");
    const auto header=split(line);
    std::map<std::string,std::size_t> columns;
    for(std::size_t c=0;c<header.size();++c)columns[header[c]]=c;
    while(std::getline(input,line)) {
        const auto row=split(line);if(row.size()!=header.size())throw std::runtime_error("bad trigger cause row");
        const auto get=[&](const char *key)->const std::string &{return row.at(columns.at(key));};
        if(std::stoul(get("cause"))!=causes.size())throw std::runtime_error("noncontiguous cause IDs");
        causes.push_back({std::stoull(get("clock_write_mask")),bool(std::stoi(get("direct_clock_alias"))),
                          std::stoi(get("enable_proof")),std::stoi(get("write_mask_proof")),
                          holds.contains(std::stoul(get("operation")))?holds.at(std::stoul(get("operation"))):0});
    }
    std::ifstream links(folder/"root_causes.txtdata");std::string magic;std::size_t nr=0,nc=0;
    if(!(links>>magic>>nr>>nc)||magic!="grhsim-trigger-root-causes-v1"||nr!=model.roots.size()||nc!=causes.size())
        throw std::runtime_error("root/cause identity shape mismatch");
    std::vector<RootClass> result(nr);
    for(std::size_t r=0;r<nr;++r) {
        std::size_t id=0,n=0;links>>id>>n;
        if(id!=r)throw std::runtime_error("noncontiguous root IDs");
        std::vector<Cause> contributing;contributing.reserve(n);
        for(std::size_t i=0;i<n;++i) {uint32_t c;links>>c;contributing.push_back(causes.at(c));}
        result[r]=classify(model.roots[r],contributing);
    }
    if(!links)throw std::runtime_error("truncated root cause links");
    return result;
}
}
