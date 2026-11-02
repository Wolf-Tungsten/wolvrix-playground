#include "abi.hpp"
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static volatile uint64_t observed = 0;
using Function = Output (*)(const Input&,bool);

static void mask(Input &x) {
    if constexpr (Width % 64) x.x.back() &= (uint64_t(1) << (Width % 64)) - 1;
}
static Output reference(const Input &x) {
    unsigned i=0;
    while(i<Width && ((x.x[i/64]>>(i%64))&1)==0) ++i;
    const unsigned index=i==Width ? Width-1 : i;
    return {index,index,index,i!=Width,i==Width?x.fallback:i};
}
static uint64_t verified=0;
static void check(const Input &x) {
    const auto expected=reference(x);
    for (auto fn : {run_a,run_b}) for (bool compute : {false,true}) {
        const auto actual=fn(x,compute);
        if (!(actual==expected)) {
            std::cerr<<"width="<<Width<<" vector="<<verified<<" compute="<<compute
                <<" expected="<<expected.index<<","<<expected.fallback
                <<" actual="<<actual.index<<","<<actual.fallback<<'\n';
            throw std::runtime_error("GrhSIM/reference mismatch");
        }
    }
    if (!(run_v(x)==expected)) throw std::runtime_error("Verilator/reference mismatch");
    ++verified;
}
static double time(Function fn, const std::vector<Input>& values,bool compute) {
    uint64_t checksum=0;
    const auto start=std::chrono::steady_clock::now();
    for(unsigned repeat=0;repeat<3;++repeat) for(const auto &x:values) {
        const auto y=fn(x,compute);
        checksum+=y.index+y.parallel+y.flagged+y.valid+y.fallback;
    }
    const auto end=std::chrono::steady_clock::now();
    observed=checksum;
    return std::chrono::duration<double,std::nano>(end-start).count()/(3*values.size());
}

int main() {
 try {
    Input edge;
    for(uint32_t d:{0u,1u,0xffffffffu}) {edge.fallback=d;check(edge);}
    for(unsigned i=0;i<Width;++i) {
        edge.x.fill(0);edge.x[i/64]=uint64_t(1)<<(i%64);check(edge);
        edge.x[0]|=1;check(edge);
    }
    if constexpr(Width<=16) for(uint64_t v=0;v<(uint64_t(1)<<Width);++v) {
        edge.x[0]=v;edge.fallback=uint32_t(v*65537);check(edge);
    }
    std::cout<<std::boolalpha<<"{\"width\":"<<Width<<",\"samples\":[";
    bool comma=false;
    for(const std::string mode:{"random","sparse","dense","toggle1","hold99"}) {
        std::vector<Input> measured;
        for(uint64_t seed:{UINT64_C(0x274671),UINT64_C(0xadb935)}) {
            std::mt19937_64 rng(seed);Input current;
            std::vector<Input> values;values.reserve(100000);
            for(unsigned i=0;i<100000;++i) {
                const bool hold=mode=="hold99" && i%100;
                if(!hold) {
                    if(mode=="sparse") {
                        current.x.fill(0);
                        if(i%17) {unsigned bit=rng()%Width;current.x[bit/64]|=uint64_t(1)<<(bit%64);}
                    } else if(mode=="dense") {
                        for(auto &word:current.x)word=rng()|rng()|rng();
                    } else if(mode=="toggle1") {
                        unsigned bit=rng()%Width;current.x[bit/64]^=uint64_t(1)<<(bit%64);
                    } else for(auto &word:current.x)word=rng();
                    current.fallback=uint32_t(rng());
                }
                current.unused=uint8_t(rng()); // Must not be an intrinsic dependency.
                mask(current);
                if(i%10007==0)current.x.fill(0);
                check(current);values.push_back(current);
            }
            if(measured.empty())measured=std::move(values);
        }
        if (std::getenv("PRIORITY_VERIFY_ONLY")) continue;
        for(bool compute:{false,true}) {
            (void)time(run_a,measured,compute);(void)time(run_b,measured,compute);
            for(unsigned pair=0;pair<8;++pair) {
                double a,b;
                if(pair%2) {b=time(run_b,measured,compute);a=time(run_a,measured,compute);}
                else {a=time(run_a,measured,compute);b=time(run_b,measured,compute);}
                if(comma)std::cout<<',';comma=true;
                std::cout<<"{\"distribution\":\""<<mode<<"\",\"compute\":"<<compute
                    <<",\"pair\":"<<pair<<",\"a_ns\":"<<a<<",\"b_ns\":"<<b<<'}';
            }
        }
    }
    std::cout<<"],\"verified\":"<<verified<<"}\n";
 } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
