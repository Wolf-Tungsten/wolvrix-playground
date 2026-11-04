#pragma once
// Only copied into a diagnostic package; never included by production emit.
#include <array>
#include <bit>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace decode_counts {
struct Row {
    uint64_t fires=0, checks=0, changes=0, active_writes=0, active_nonzero=0, active_new_bits=0, dirty_writes=0;
};
struct Counters {
    std::array<Row,131072> groups{};
    std::array<uint64_t,4096> calls{}, empty{};
    uint64_t total_fires=0, evals=0, rounds=0, clock_high_evals=0;
    uint32_t current=131071;
    ~Counters() {
        const char* path=std::getenv("WOLVRIX_CONSTANT_COUNTS");
        if (!path || !*path) return;
        FILE* f=std::fopen(path,"w");
        if (!f) { std::perror("counts output"); std::abort(); }
        std::fprintf(f,"kind\tid\tfires\tchecks\tchanges\tactive_writes\tactive_nonzero\tactive_new_bits\tdirty_writes\n");
        for (unsigned i=0;i<groups.size();++i) {
            const auto& r=groups[i];
            if (r.fires || r.checks || r.active_writes || r.dirty_writes)
                std::fprintf(f,"group\t%u\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\n",i,
                  (unsigned long long)r.fires,(unsigned long long)r.checks,(unsigned long long)r.changes,
                  (unsigned long long)r.active_writes,(unsigned long long)r.active_nonzero,
                  (unsigned long long)r.active_new_bits,(unsigned long long)r.dirty_writes);
        }
        for (unsigned i=0;i<calls.size();++i) if(calls[i])
            std::fprintf(f,"batch\t%u\t%llu\t%llu\t0\t0\t0\t0\t0\n",i,(unsigned long long)calls[i],(unsigned long long)empty[i]);
        std::fprintf(f,"eval\t0\t%llu\t%llu\t%llu\t0\t0\t0\t0\n",(unsigned long long)evals,
                     (unsigned long long)rounds,(unsigned long long)clock_high_evals);
        if(std::fclose(f)) std::abort();
    }
};
inline Counters counts;
inline void fire(uint32_t group) {
    counts.current=group; ++counts.groups[group].fires; ++counts.total_fires;
}
inline bool change(bool changed) {
    auto& row=counts.groups[counts.current]; ++row.checks; row.changes+=changed; return changed;
}
template<class T, class U> inline void activate(T& target, U mask) {
    const T narrowed=static_cast<T>(mask);
    auto& row=counts.groups[counts.current]; ++row.active_writes; row.active_nonzero+=narrowed!=0;
    row.active_new_bits+=std::popcount(static_cast<uint64_t>(narrowed & static_cast<T>(~target)));
    target|=narrowed;
}
template<class T> inline void activate_words(uint8_t* target, size_t offset, T mask) {
    T previous; std::memcpy(&previous,target+offset,sizeof(T));
    activate(previous,mask); std::memcpy(target+offset,&previous,sizeof(T));
}
struct Batch {
    unsigned id; uint64_t before; uint32_t previous;
    explicit Batch(unsigned n):id(n),before(counts.total_fires),previous(counts.current) { ++counts.calls[id]; counts.current=131071; }
    ~Batch(){ counts.empty[id]+=before==counts.total_fires; counts.current=previous; }
};
inline void eval(bool clock) { ++counts.evals; counts.clock_high_evals+=clock; counts.current=131071; }
inline void round() { ++counts.rounds; }
inline void dirty() { ++counts.groups[counts.current].dirty_writes; }
}
