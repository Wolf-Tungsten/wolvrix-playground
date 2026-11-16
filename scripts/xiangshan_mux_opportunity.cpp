// Standalone, read-only structural and synthetic-demand analysis of GRH.
// Build: g++ -std=c++20 -O3 scripts/xiangshan_mux_opportunity.cpp -o <out>/analyze
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using U = uint32_t;
using Q = uint64_t;
namespace fs = std::filesystem;
constexpr U NONE = std::numeric_limits<U>::max();
constexpr U PURE = 1, ROOT = 2, MUX = 4, SCALAR = 8, WIRING = 16;

template<class T> std::vector<T> read(std::istream &in, size_t n) {
    std::vector<T> v(n);
    in.read(reinterpret_cast<char *>(v.data()), n * sizeof(T));
    if (!in) throw std::runtime_error("truncated compact graph");
    return v;
}
Q random_word(Q x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

struct Graph {
    U n, nv;
    Q edges;
    std::vector<Q> off, loc, outoff;
    std::vector<U> pred, flags, width, selector, kind, users, positions, topo, muxes, gate;
    std::vector<int8_t> truth;
    std::vector<uint8_t> live;
    U total, root;
    explicit Graph(const fs::path &file) {
        std::ifstream f(file, std::ios::binary);
        char magic[8]; f.read(magic, 8);
        if (std::string(magic, 8) != "MUXGRH01") throw std::runtime_error("wrong format");
        auto h = read<Q>(f, 3); n = h[0]; edges = h[1]; nv = h[2];
        off = read<Q>(f, n+1); pred = read<U>(f, edges); flags = read<U>(f,n);
        width = read<U>(f,n); selector = read<U>(f,n); truth = read<int8_t>(f,n);
        kind = read<U>(f,n); loc = read<Q>(f,n);
        live.resize(n); std::vector<U> work;
        for (U i=1;i<n;++i) if (flags[i]&ROOT) { live[i]=1; work.push_back(i); }
        while (!work.empty()) {
            U v=work.back();work.pop_back();
            for (Q j=off[v];j<off[v+1];++j) if (U p=pred[j];p && !live[p]) { live[p]=1;work.push_back(p); }
        }
        outoff.resize(n+1);
        std::vector<U> degree(n);
        for (U i=1;i<n;++i) if (live[i]) for (Q j=off[i];j<off[i+1];++j)
            if (U p=pred[j]) { ++outoff[p+1];++degree[i]; }
        std::partial_sum(outoff.begin(),outoff.end(),outoff.begin());
        users.resize(outoff.back());positions.resize(users.size());
        auto next=outoff;
        for (U i=1;i<n;++i) if (live[i]) for (Q j=off[i];j<off[i+1];++j)
            if (U p=pred[j]) { Q at=next[p]++;users[at]=i;positions[at]=j-off[i]; }
        for (U i=1;i<n;++i) if (live[i]&&!degree[i]) topo.push_back(i);
        for (size_t at=0;at<topo.size();++at) {
            U v=topo[at];
            for (Q e=outoff[v];e<outoff[v+1];++e) if (!--degree[users[e]]) topo.push_back(users[e]);
        }
        if (topo.size()!=size_t(std::count(live.begin(),live.end(),1)))
            throw std::runtime_error("live combinational cycle; no DAG result reported");
        gate.assign(n,NONE);
        for (U v:topo) if (flags[v]&MUX) { gate[v]=n+2*muxes.size();muxes.push_back(v); }
        root=n+2*muxes.size(); total=root+1;
        std::cerr<<"graph "<<n-1<<" ops; live "<<topo.size()<<"; muxes "<<muxes.size()<<"\n";
    }
    U successor(Q edge, bool scalar=false) const {
        U user=users[edge],pos=positions[edge];
        if ((flags[user]&MUX) && pos>0 && (!scalar||(flags[user]&SCALAR))) return gate[user]+pos-1;
        return user;
    }
    U owner(U v) const { return muxes[(v-n)/2]; }
    bool pure(U v) const { return v<n && (flags[v]&PURE); }
};

// An arm gate postdominates an op exactly when every use path to a required
// output/effect crosses this data operand of this mux. In particular, selector
// dependencies, shared arms and outside consumers cannot enter that region.
std::vector<U> dominators(const Graph &g, bool strict) {
    std::vector<U> parent(g.total,g.root), depth(g.total);
    std::vector<std::array<U,20>> up;
    if (!strict) { up.resize(g.total);up[g.root].fill(g.root); }
    auto install=[&](U v,U p) {
        parent[v]=p;depth[v]=depth[p]+1;
        if (depth[v]>=(1u<<20)) throw std::runtime_error("dominator depth overflow");
        if (!strict) { up[v][0]=p;for (U k=1;k<20;++k) up[v][k]=up[up[v][k-1]][k-1]; }
    };
    auto lca=[&](U a,U b) {
        if (depth[a]<depth[b]) std::swap(a,b);
        U d=depth[a]-depth[b];
        for (U k=0;d;++k,d>>=1) if (d&1) a=up[a][k];
        if (a==b) return a;
        for (int k=19;k>=0;--k) if (up[a][k]!=up[b][k]) {a=up[a][k];b=up[b][k];}
        return parent[a];
    };
    for (auto it=g.topo.rbegin();it!=g.topo.rend();++it) {
        U v=*it,p=g.root;
        if (!(g.flags[v]&ROOT)) {
            if (strict) {
                if ((g.flags[v]&SCALAR) && g.outoff[v+1]-g.outoff[v]==1) p=g.successor(g.outoff[v],true);
            } else {
                p=NONE;
                for (Q e=g.outoff[v];e<g.outoff[v+1];++e) {
                    U u=g.successor(e);p=p==NONE?u:lca(p,u);
                    if (p==g.root) break;
                }
                if (p==NONE) throw std::runtime_error("live unobserved sink");
            }
        }
        install(v,p);
        if (g.flags[v]&MUX) for (U a=0;a<2;++a) install(g.gate[v]+a,v);
    }
    return parent;
}

struct Stats {
    std::vector<Q> subtree;
    std::vector<U> armDepth;
    std::vector<double> kindSaved;
    Q eligible=0,unique=0,nested=0,substantive=0,words=0;
    U maxdepth=0;
    double saved=0,savedSub=0,savedWords=0,saved01=0,saved09=0;
};
Stats analyze_tree(const Graph &g,const std::vector<U> &parent,bool strict,
                   const fs::path &out) {
    std::vector<U> head(g.total,NONE),next(g.total,NONE);
    for (U v:g.topo) {next[v]=head[parent[v]];head[parent[v]]=v;}
    for (U v=g.n;v<g.root;++v) {next[v]=head[parent[v]];head[parent[v]]=v;}
    std::vector<U> yes(g.nv),no(g.nv);
    U uniqueYes=0,uniqueNo=0,contradictions=0,constantBad=0,gates=0;
    auto update=[&](U node,int delta) {
        U mux=g.owner(node);
        if (strict && !(g.flags[mux]&SCALAR)) return;
        bool positive=((node-g.n)%2==0);
        gates+=delta;
        if (g.truth[mux]>=0) { if (positive!=bool(g.truth[mux])) constantBad+=delta;return; }
        U value=g.selector[mux];
        uniqueYes-=bool(yes[value]);uniqueNo-=bool(no[value]);contradictions-=bool(yes[value]&&no[value]);
        (positive?yes[value]:no[value])+=delta;
        uniqueYes+=bool(yes[value]);uniqueNo+=bool(no[value]);contradictions+=bool(yes[value]&&no[value]);
    };
    Stats s;s.subtree.resize(g.total);s.armDepth.resize(g.root-g.n);
    s.kindSaved.resize(*std::max_element(g.kind.begin(),g.kind.end())+1);
    struct Entry {U node, child;};
    std::vector<Entry> stack{{g.root,head[g.root]}};
    while (!stack.empty()) {
        auto &entry=stack.back();
        if (entry.child==NONE) {
            U v=entry.node;stack.pop_back();
            if (v!=g.root) {
                s.subtree[parent[v]]+=s.subtree[v];
                if (v>=g.n) update(v,-1);
            }
            continue;
        }
        U v=entry.child;entry.child=next[v];
        if (v>=g.n) {update(v,1);s.armDepth[v-g.n]=gates;}
        else if (g.pure(v)) {
            s.subtree[v]=1;++s.eligible;
            bool real=!(g.flags[v]&WIRING);Q words=(g.width[v]+63)/64;
            s.substantive+=real;s.words+=words;
            s.unique+=gates>0;s.nested+=gates>1;s.maxdepth=std::max(s.maxdepth,gates);
            double probability=constantBad||contradictions?0:std::exp2(-double(uniqueYes+uniqueNo));
            double saving=1-probability;
            s.saved+=saving;s.savedSub+=saving*real;s.savedWords+=saving*words;
            s.kindSaved[g.kind[v]]+=saving;
            s.saved01+=1-(constantBad||contradictions?0:std::pow(.1,uniqueYes)*std::pow(.9,uniqueNo));
            s.saved09+=1-(constantBad||contradictions?0:std::pow(.9,uniqueYes)*std::pow(.1,uniqueNo));
        }
        stack.push_back({v,head[v]});
    }
    std::ofstream f(out);f.precision(17);
    f<<"eligible\tunique_gated\tnested_gated\tmax_gate_depth\texpected_saved\tsubstantive_ops\texpected_saved_substantive\tword_units\texpected_saved_words\texpected_saved_p01\texpected_saved_p09\n"
     <<s.eligible<<'\t'<<s.unique<<'\t'<<s.nested<<'\t'<<s.maxdepth<<'\t'<<s.saved<<'\t'<<s.substantive<<'\t'<<s.savedSub<<'\t'<<s.words<<'\t'<<s.savedWords<<'\t'<<s.saved01<<'\t'<<s.saved09<<'\n';
    return s;
}

void bounded(const Graph &g,const Stats &strict,const fs::path &out) {
    std::vector<uint8_t> absorbed(g.n);Q roots=0,arms=0,ops=0,sub=0;double saved=0;
    for (auto it=g.topo.rbegin();it!=g.topo.rend();++it) {
        U v=*it;if (!(g.flags[v]&MUX)||!(g.flags[v]&SCALAR)||absorbed[v]) continue;
        bool found=false;
        for (U a=0;a<2;++a) {
            Q count=strict.subtree[g.gate[v]+a];
            if (count<16||count>256) continue;
            found=true;++arms;Q got=0;
            std::vector<U> todo{g.pred[g.off[v]+a+1]};
            while (!todo.empty()) {
                U p=todo.back();todo.pop_back();
                if (!p || !(g.flags[p]&PURE) || !(g.flags[p]&SCALAR) || (g.flags[p]&ROOT) ||
                    g.outoff[p+1]-g.outoff[p]!=1) continue;
                if (absorbed[p]) throw std::runtime_error("overlapping outer-first private cones");
                absorbed[p]=1;++got;sub+=!(g.flags[p]&WIRING);
                for (Q j=g.off[p];j<g.off[p+1];++j) todo.push_back(g.pred[j]);
            }
            if (got!=count) throw std::runtime_error("private tree/subtree size disagreement");
            ops+=got;saved+=got*(g.truth[v]<0?.5:(g.truth[v]!=int(a==0)));
        }
        roots+=found;
    }
    std::ofstream f(out);f<<"roots\tarms\tunique_ops\tsubstantive_ops\texpected_saved\n"<<roots<<'\t'<<arms<<'\t'<<ops<<'\t'<<sub<<'\t'<<saved<<'\n';
}

void monte_carlo(const Graph &g,const fs::path &out,U batches) {
    std::vector<Q> demand(g.n);
    U nk=*std::max_element(g.kind.begin(),g.kind.end())+1;
    std::vector<long double> byKind(nk);std::vector<Q> baseKind(nk);
    for (U v:g.topo) if (g.pure(v)) ++baseKind[g.kind[v]];
    std::ofstream f(out/"demand-batches.tsv");f.precision(17);
    f<<"batch\tassignments\texpected_ops\texpected_substantive\texpected_word_units\n";
    for (U b=0;b<batches;++b) {
        std::fill(demand.begin(),demand.end(),0);
        for (U v:g.topo) if (g.flags[v]&ROOT) demand[v]=~Q(0);
        long double total=0,sub=0,words=0;
        for (auto it=g.topo.rbegin();it!=g.topo.rend();++it) {
            U v=*it;Q m=demand[v];if (!m) continue;
            if (g.pure(v)) {
                U num=std::popcount(m);total+=num;sub+=num*!(g.flags[v]&WIRING);
                words+=Q(num)*((g.width[v]+63)/64);byKind[g.kind[v]]+=num;
            }
            if (g.flags[v]&MUX) {
                Q choice=g.truth[v]>=0?(g.truth[v]?~Q(0):0):
                    random_word(Q(g.selector[v])+Q(b)*0xd1342543de82ef95ULL+20261115);
                demand[g.pred[g.off[v]]]|=m;
                demand[g.pred[g.off[v]+1]]|=m&choice;
                demand[g.pred[g.off[v]+2]]|=m&~choice;
            } else for (Q e=g.off[v];e<g.off[v+1];++e) demand[g.pred[e]]|=m;
        }
        f<<b<<'\t'<<64<<'\t'<<total/64<<'\t'<<sub/64<<'\t'<<words/64<<'\n';f.flush();
        if (b%8==0) std::cerr<<"synthetic demand batch "<<b<<'/'<<batches<<"\n";
    }
    std::ofstream k(out/"demand-kinds.tsv");k.precision(17);k<<"kind_id\tlive_ops\texpected_ops\n";
    for (U i=0;i<nk;++i) k<<i<<'\t'<<baseKind[i]<<'\t'<<byKind[i]/(64*batches)<<'\n';
}

int main(int argc,char **argv) {
    try {
        if (argc<2) throw std::runtime_error("usage: analyze DIRECTORY [batches=64]");
        fs::path out=argv[1];U batches=argc>2?std::stoul(argv[2]):64;
        Graph g(out/"graph.bin");
        auto parent=dominators(g,false);
        auto shared=analyze_tree(g,parent,false,out/"exclusive.tsv");
        std::cerr<<"exclusive union "<<shared.unique<<" expected saved "<<shared.saved<<"\n";
        parent.clear();parent.shrink_to_fit();
        parent=dominators(g,true);
        auto strict=analyze_tree(g,parent,true,out/"single-use-scalar.tsv");
        bounded(g,strict,out/"bounded-scalar.tsv");
        std::ofstream mux(out/"muxes.tsv");
        mux<<"op_index\tjson_offset\tselector_id\tselector_truth\twidth\texclusive_true\texclusive_false\tprivate_scalar_true\tprivate_scalar_false\ttrue_gate_depth\tfalse_gate_depth\n";
        for (U v:g.muxes) mux<<v<<'\t'<<g.loc[v]<<'\t'<<g.selector[v]<<'\t'<<int(g.truth[v])<<'\t'<<g.width[v]<<'\t'
            <<shared.subtree[g.gate[v]]<<'\t'<<shared.subtree[g.gate[v]+1]<<'\t'
            <<strict.subtree[g.gate[v]]<<'\t'<<strict.subtree[g.gate[v]+1]<<'\t'
            <<shared.armDepth[g.gate[v]-g.n]<<'\t'<<shared.armDepth[g.gate[v]+1-g.n]<<'\n';
        std::ofstream kinds(out/"exclusive-kinds.tsv");kinds.precision(17);kinds<<"kind_id\texclusive_expected_saved\tprivate_scalar_expected_saved\n";
        for(U k=0;k<shared.kindSaved.size();++k) kinds<<k<<'\t'<<shared.kindSaved[k]<<'\t'<<strict.kindSaved[k]<<'\n';
        std::ofstream info(out/"graph-stats.tsv");
        info<<"total_ops\tlive_ops\tlive_muxes\tlive_pure\tlive_pure_scalar\n";
        Q scalar=0;for(U v:g.topo) scalar+=g.pure(v)&&bool(g.flags[v]&SCALAR);
        info<<g.n-1<<'\t'<<g.topo.size()<<'\t'<<g.muxes.size()<<'\t'<<shared.eligible<<'\t'<<scalar<<'\n';
        monte_carlo(g,out,batches);
        std::cerr<<"analysis complete\n";
    } catch (const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
