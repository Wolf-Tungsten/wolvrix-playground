#pragma once
#include "repcut_grhsim_context_cost.hpp"
#include <filesystem>
#include <optional>
#include <tuple>
#include <unordered_map>

namespace arrival_context {
using activity_context::Units;
constexpr uint32_t noOwner = UINT32_MAX;
constexpr uint64_t unknown = activity_context::unknown;
constexpr std::size_t units = 6, axes = 36;
using Cost = std::array<uint64_t, axes>;
struct Root { uint32_t owner = noOwner; uint64_t mask = 0; uint32_t kind = 0; }; // 0 entry, 1 deferred state, 2 early effect
struct Item { uint32_t context = 0, demand = 0, sources = 0; uint64_t mask = 0; Units work{}; };
struct Model {
    uint32_t atoms = 0;
    std::vector<bool> compute;
    std::vector<std::vector<uint32_t>> demands, sources;
    std::vector<Root> roots;
    std::vector<Item> items;
};
inline uint64_t nextHalf(uint64_t mask) { return (mask & ~uint64_t{3}) | ((mask & 1) << 1) | ((mask & 2) >> 1); }
inline Cost charge(const Units &work, uint64_t mask, uint32_t wave) {
    Cost out{};
    for (uint32_t s = 0; s < 3; ++s) if (mask & (s == 2 ? unknown : uint64_t{1} << s))
        for (uint32_t u = 0; u < 6; ++u) out[wave*18+s*6+u] = work[u];
    return out;
}
inline Model read(const char *path) {
    std::ifstream file(path); Model m; std::string magic; std::size_t nc,nd,nr,ns,ni;
    if (!(file>>magic>>m.atoms>>nc>>nd>>nr>>ns>>ni) || magic!="grhsim-arrival-context-v1")
        throw std::runtime_error("invalid arrival model");
    m.compute.resize(nc); m.demands.resize(nd); m.roots.resize(nr); m.sources.resize(ns); m.items.resize(ni);
    for(std::size_t c=0;c<nc;++c){unsigned v;file>>v;m.compute[c]=v;}
    for(auto &v:m.demands){std::size_t n;file>>n;v.resize(n);for(auto &x:v)file>>x;}
    for(auto &r:m.roots){file>>r.owner>>r.mask>>r.kind;if(r.kind>2||(r.owner!=noOwner&&r.owner>=m.atoms))throw std::runtime_error("invalid root");}
    for(auto &v:m.sources){std::size_t n;file>>n;v.resize(n);for(auto &x:v){file>>x;if(x>=nr)throw std::runtime_error("invalid source");}}
    for(auto &i:m.items){file>>i.context>>i.demand>>i.sources>>i.mask;for(auto &w:i.work)file>>w;
        if(i.context>=nc||i.demand>=nd||i.sources>=ns)throw std::runtime_error("invalid item");}
    if(!file)throw std::runtime_error("truncated arrival model");
    return m;
}
inline void write(const Model &m, const std::filesystem::path &path) {
    std::ofstream file(path);
    file<<"grhsim-arrival-context-v1 "<<m.atoms<<' '<<m.compute.size()<<' '<<m.demands.size()<<' '<<m.roots.size()<<' '<<m.sources.size()<<' '<<m.items.size()<<'\n';
    for(bool v:m.compute)file<<v<<' ';
    file<<'\n';
    for(const auto &v:m.demands){file<<v.size();for(auto x:v)file<<' '<<x;file<<'\n';}
    for(const auto &r:m.roots)file<<r.owner<<' '<<r.mask<<' '<<r.kind<<'\n';
    for(const auto &v:m.sources){file<<v.size();for(auto x:v)file<<' '<<x;file<<'\n';}
    for(const auto &i:m.items){file<<i.context<<' '<<i.demand<<' '<<i.sources<<' '<<i.mask;for(auto w:i.work)file<<' '<<w;file<<'\n';}
    if(!file)throw std::runtime_error("arrival model output failed");
}
} // namespace arrival_context
