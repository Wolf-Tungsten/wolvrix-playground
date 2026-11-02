// One executable per generated fixture. No random generation in timed loops.
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include <immintrin.h>
#include "bench_types.hpp"
#include "grhsim_Pattern.hpp"

constexpr bool stateful = (PATTERN_KIND >= 23 && PATTERN_KIND <= 27) || (PATTERN_KIND >= 37 && PATTERN_KIND <= 42) || PATTERN_KIND==45;
static volatile uint64_t observed = 0;

struct Software {
    static constexpr unsigned table_depth = (PATTERN_KIND==37||PATTERN_KIND==42)?64:16;
    std::array<uint32_t,table_depth> table{};
    std::array<uint8_t,8> cam{};
    uint8_t cam_valid=0;
    std::array<uint64_t,8> bins{};
    std::array<uint8_t,8> age{};
    std::array<uint32_t,8> queue{};
    uint64_t state=0, lfsr=UINT64_C(0x1234567887654321);
    unsigned head=0,tail=0,count=0;

    Output inspect(const Input& x) const {
        Output r;
        if constexpr(PATTERN_KIND==23||PATTERN_KIND==37||PATTERN_KIND==42) {
            r.y=table[x.b&(table_depth-1)];
            if constexpr(PATTERN_KIND!=42)for(auto v:table)r.z^=v;
        }
        if constexpr(PATTERN_KIND==24||PATTERN_KIND==40||PATTERN_KIND==41)r.y=state;
        if constexpr(PATTERN_KIND==25)r.y=lfsr;
        if constexpr(PATTERN_KIND==26||PATTERN_KIND==38) {
            const bool valid=count>0||(PATTERN_KIND==38&&(x.sel&1));
            r.y=count?queue[head]:(valid?uint32_t(x.a):0);r.z=(count<<2)|((count<8)<<1)|valid;
        }
        if constexpr(PATTERN_KIND==27)for(unsigned i=0;i<8;++i){
            r.y|=uint64_t(((x.b>>i)&1)&&uint8_t(age[i]|~uint8_t(x.b))==255)<<i;r.z|=uint64_t(age[i])<<(i*8);
        }
        if constexpr(PATTERN_KIND==39) {
            for(unsigned i=0;i<8;++i)r.y|=uint64_t((cam_valid&(1u<<i))&&cam[i]==uint8_t(x.b))<<i;
            r.z=(cam_valid&(1u<<(x.c&7)))?cam[x.c&7]:0;
        }
        if constexpr(PATTERN_KIND==45){r.y=bins[x.b&7];for(auto n:bins)r.z+=n;}
        return r;
    }

    __attribute__((noinline)) Output step(const Input& x) {
        Output r;
        const uint64_t a=x.a,b=x.b,c=x.c;
        if constexpr (PATTERN_KIND == 0) r.y=std::popcount(a & 65535);
        if constexpr (PATTERN_KIND == 1) r.y=std::popcount(a);
        if constexpr (PATTERN_KIND == 33) r.y=std::popcount(uint32_t(a));
        if constexpr (PATTERN_KIND == 2) r.y=(a & (a-1))!=0;
        if constexpr (PATTERN_KIND == 3) r.y=std::popcount(a & 4095)>=3;
        if constexpr (PATTERN_KIND == 34) r.y=std::popcount(a & 65535)>=3;
        if constexpr (PATTERN_KIND == 4) r.y=std::countr_zero(a);
        if constexpr (PATTERN_KIND == 32) r.y=(a&65535)?std::countr_zero(a&65535):16;
        if constexpr (PATTERN_KIND == 5) {
            r.y=((a&0xaaaa)!=0) | (((a&0xcccc)!=0)<<1) |
                (((a&0xf0f0)!=0)<<2) | (((a&0xff00)!=0)<<3);
        }
        if constexpr (PATTERN_KIND == 6) {
            for(unsigned i=0;i<8;++i) if(b & (1u<<i)) r.y|=(a>>(8*i))&255;
        }
        if constexpr (PATTERN_KIND == 35) {
            for(unsigned i=0;i<4;++i) if(b & (1u<<i)) r.y|=(a>>(16*i))&65535;
        }
        if constexpr (PATTERN_KIND == 7) {
            unsigned i=(b&255)?std::countr_zero(b&255):7;
            r.y=(a>>(8*i))&255;
        }
        if constexpr (PATTERN_KIND == 8) {
            uint64_t m=a&65535;
            for(unsigned i=0;i<4;++i) if(b&(1u<<i)) {
                uint64_t v=m & (0-m);r.y|=v<<(16*i);m^=v;
            }
        }
        if constexpr (PATTERN_KIND == 9) r.y=std::rotl(a,int((x.sel&7)*8));
        if constexpr (PATTERN_KIND == 10) r.y=a<<((x.sel&7)*8);
        if constexpr (PATTERN_KIND == 11) r.y=__builtin_bitreverse64(a);
        if constexpr (PATTERN_KIND == 12 || PATTERN_KIND == 13) {
            unsigned n=0;unsigned __int128 packed=0;
            for(unsigned i=0;i<16;++i) {n+=(a>>i)&1;packed|=static_cast<unsigned __int128>(n)<<(5*i);}
            r.y=uint64_t(packed);r.z=uint64_t(packed>>64);
        }
        if constexpr (PATTERN_KIND == 14) {auto t=a^(a>>32);t^=t>>16;t^=t>>8;r.y=t&255;}
        if constexpr (PATTERN_KIND == 15) r.y=std::popcount(a)&1;
        if constexpr (PATTERN_KIND == 16) {
            // Systematic SEC(38,32): parity masks derived from Hamming positions.
            constexpr auto masks=[] {
                std::array<uint32_t,6> out{};unsigned data=0;
                for(unsigned pos=1;data<32;++pos) if(!std::has_single_bit(pos)) {
                    for(unsigned p=0;p<6;++p) if(pos&(1u<<p))out[p]|=1u<<data;
                    ++data;
                }
                return out;
            }();
            r.y=uint32_t(a);
            for(unsigned p=0;p<6;++p)r.y|=uint64_t(std::popcount(uint32_t(a)&masks[p])&1)<<(32+p);
        }
        if constexpr (PATTERN_KIND == 17) {
            // Polynomial remainder, same explicit polynomial and bit order as Rocket CRC.
            uint32_t value=uint32_t(a);
            for(int i=31;i>=16;--i) if(value&(1u<<i))value^=0x11021u<<(i-16);
            r.y=value;
        }
        if constexpr (PATTERN_KIND == 30) {
            static constexpr auto lut=[] {
                std::array<uint16_t,256> t{};
                for(unsigned i=0;i<256;++i) {
                    uint32_t v=i<<16;
                    for(int j=23;j>=16;--j)if(v&(1u<<j))v^=0x11021u<<(j-16);
                    t[i]=v;
                }return t;
            }();
            uint16_t v=0;
            for(int byte=3;byte>=0;--byte)v=uint16_t((uint32_t(v)<<8)^((a>>(byte*8))&255)^lut[v>>8]);
            r.y=v;
        }
        if constexpr (PATTERN_KIND == 18) {
            uint32_t v=uint32_t(a);v^=v>>16;v^=v>>8;v^=v>>4;v^=v>>2;v^=v>>1;r.y=v;
        }
        if constexpr (PATTERN_KIND == 19 || PATTERN_KIND == 36) {
            static constexpr auto lut=[] {
                std::array<uint8_t,256> t{};
                for(unsigned i=0;i<256;++i)t[i]=((i*29)^(i>>2)^0xa7)&255;
                return t;
            }();r.y=lut[a&(PATTERN_KIND==19?255:15)];
        }
        if constexpr (PATTERN_KIND == 20) {
            for(unsigned i=0;i<8;++i)r.y|=uint64_t(((a>>(8*i))&255)==(b&255))<<i;
        }
        if constexpr (PATTERN_KIND == 21) {
            std::array<uint16_t,4> t{};
            for(unsigned i=0;i<4;++i)t[i]=a>>(16*i);
            std::sort(t.begin(),t.end());
            for(unsigned i=0;i<4;++i)r.y|=uint64_t(t[i])<<(16*i);
        }
        if constexpr (PATTERN_KIND == 31) {
            uint16_t w=a,x=a>>16,y=a>>32,z=a>>48;
            auto swap=[](uint16_t& l,uint16_t& r){auto lo=std::min(l,r),hi=std::max(l,r);l=lo;r=hi;};
            swap(w,x);swap(y,z);swap(w,y);swap(x,z);swap(x,y);
            r.y=w|(uint64_t(x)<<16)|(uint64_t(y)<<32)|(uint64_t(z)<<48);
        }
        if constexpr (PATTERN_KIND == 22) r.y=a+b+c;
        if constexpr (PATTERN_KIND == 28) r.y=a;
        if constexpr (PATTERN_KIND == 29) r.y=a+b+c;
        if constexpr (PATTERN_KIND == 23 || PATTERN_KIND == 37 || PATTERN_KIND==42) {
            if(x.reset)table.fill(0);else if(x.sel&128)table[x.sel&(table_depth-1)]=uint32_t(a);
            r.y=table[b&(table_depth-1)];
            if constexpr(PATTERN_KIND!=42)for(auto v:table)r.z^=v;
        }
        if constexpr (PATTERN_KIND == 24) {
            if(x.reset)state=0;else {
                uint64_t mask=0;for(unsigned i=0;i<8;++i)if(x.sel&(1u<<i))mask|=UINT64_C(255)<<(8*i);
                state=(state&~mask)|(a&mask);
            }r.y=state;
        }
        if constexpr (PATTERN_KIND == 25) {
            if(x.reset)lfsr=UINT64_C(0x1234567887654321);
            else if(x.sel&1) lfsr=lfsr?((lfsr>>1)|(uint64_t(std::popcount(lfsr&27)&1)<<63)):1;
            r.y=lfsr;
        }
        if constexpr (PATTERN_KIND == 26 || PATTERN_KIND == 38) {
            if(x.reset) {head=tail=count=0;}
            else {
                const bool bypass=PATTERN_KIND==38 && !count && (x.sel&2);
                const bool push=(x.sel&1)&&count<8&&!bypass,pop=(x.sel&2)&&count>0;
                if(push){queue[tail]=uint32_t(a);tail=(tail+1)&7;}
                if(pop)head=(head+1)&7;
                count+=unsigned(push);count-=unsigned(pop);
            }
            const bool valid=count>0||(PATTERN_KIND==38&&(x.sel&1));
            r.y=count?queue[head]:(valid?uint32_t(a):0);r.z=(count<<2)|((count<8)<<1)|valid;
        }
        if constexpr (PATTERN_KIND == 27) {
            if(x.reset)age.fill(0);
            else if(x.sel&128)for(unsigned i=0;i<8;++i)age[i]=((x.sel&7)==i)?(1u<<i):(age[i]|(1u<<(x.sel&7)));
            for(unsigned i=0;i<8;++i){
                r.y|=uint64_t(((b>>i)&1)&&uint8_t(age[i]|~uint8_t(b))==255)<<i;
                r.z|=uint64_t(age[i])<<(i*8);
            }
        }
        if constexpr (PATTERN_KIND == 39) {
            if(x.reset)cam_valid=0;
            else if(x.sel&128){cam_valid|=1u<<(x.sel&7);cam[x.sel&7]=a;}
            for(unsigned i=0;i<8;++i)r.y|=uint64_t((cam_valid&(1u<<i))&&cam[i]==uint8_t(b))<<i;
            r.z=(cam_valid&(1u<<(c&7)))?cam[c&7]:0;
        }
        if constexpr (PATTERN_KIND == 40 || PATTERN_KIND == 41) {state=x.reset?0:a;r.y=state;}
        if constexpr (PATTERN_KIND == 43 || PATTERN_KIND == 44) {
            constexpr std::array<unsigned,16> positions{0,3,7,11,16,21,25,28,33,38,42,47,50,55,59,63};
            constexpr uint64_t mask=[positions] {uint64_t m=0;for(unsigned p:positions)m|=UINT64_C(1)<<p;return m;}();
#if defined(__BMI2__)
            if constexpr(PATTERN_KIND==43)r.y=_pext_u64(a,mask);else r.y=_pdep_u64(a&65535,mask);
#else
            for(unsigned i=0;i<16;++i)
                if constexpr(PATTERN_KIND==43)r.y|=((a>>positions[i])&1)<<i;
                else r.y|=((a>>i)&1)<<positions[i];
#endif
        }
        if constexpr(PATTERN_KIND==45) {
            if(x.reset)bins.fill(0);
            else if(x.sel&1)++bins[a<8?0:a>=40?7:((a-8)/4)];
            r.y=bins[b&7];for(auto n:bins)r.z+=n;
        }
        if constexpr(PATTERN_KIND==46)r.y=(x.sel&1)?uint32_t(a)/(uint32_t(b)|1):0;
#ifdef PATTERN_TEST_FAULT
        r.y ^= 1;
#endif
        return r;
    }
};

struct Generated {
    GrhSIM_Pattern model;
    Generated() {
        model.init();model.reset=true;model.clock=false;model.eval();model.clock=true;model.eval();
        model.clock=false;model.reset=false;model.eval();
    }
    __attribute__((noinline)) Output step(const Input& x) {
        model.io_a=x.a;model.io_b=x.b;model.io_c=x.c;model.io_d=x.d;model.io_sel=x.sel;
        model.reset=x.reset;
        if constexpr (stateful) {model.clock=false;model.eval();model.clock=true;model.eval();}
        else model.eval();
        return {model.io_y,model.io_z};
    }
    Output preview(const Input& x) {
        model.io_a=x.a;model.io_b=x.b;model.io_c=x.c;model.io_d=x.d;model.io_sel=x.sel;
        model.reset=x.reset;model.clock=false;model.eval();return {model.io_y,model.io_z};
    }
};

std::vector<Input> inputs(uint64_t seed,const std::string& mode,size_t count) {
    std::mt19937_64 rng(seed);std::vector<Input> v;v.reserve(count);
    Input previous{};
    for(size_t i=0;i<count;++i) {
        Input x{rng(),rng(),rng(),rng(),uint8_t(rng()),false};
        if constexpr(PATTERN_KIND==45)x.a%=56;
        if(mode=="sparse") {x.a=UINT64_C(1)<<(x.a&63);x.b=1u<<(x.b&7);x.sel=1u<<(x.sel&7);}
        if(mode=="dense") {x.a=~(UINT64_C(1)<<(x.a&63));x.b=~(UINT64_C(1)<<(x.b&63));x.sel=uint8_t(~(1u<<(x.sel&7)));}
        if(mode=="toggle1" && i) {auto bit=x.a&63;x=previous;x.a^=UINT64_C(1)<<bit;}
        if(mode=="hold99" && i%100) x=previous;
        // Directed boundaries within both seeded streams, also during performance runs.
        if(i%1024<4) {
            x.a=(i%1024==0)?0:(i%1024==1)?UINT64_MAX:(i%1024==2)?UINT64_C(1)<<63:UINT64_C(0x8000800080008000);
            x.b=(i%2)?UINT64_MAX:0;x.sel=(i%2)?255:0;
        }
        // Directed protocol / address / clipping cases independent of random coverage.
        if constexpr(PATTERN_KIND==45)if(i>0&&i<=56){x.a=i-1;x.b=(i-1)&7;x.sel=1;}
        if constexpr(PATTERN_KIND==23||PATTERN_KIND==37||PATTERN_KIND==42)
            if(i>0&&i<=128){x.sel=i<=64?uint8_t(128|((i-1)&63)):0;x.b=(i-1)&63;}
        if constexpr(PATTERN_KIND==26||PATTERN_KIND==38)
            if(i>0&&i<49)x.sel=i<=16?1:i<=32?2:3;
        if constexpr(PATTERN_KIND==39)if(i>0&&i<=16){x.sel=128|((i-1)&7);x.a=i<=8?42:(i-1)&7;x.b=42;x.c=(i-1)&7;}
        if constexpr(stateful) x.reset=(i==0 || i%4093==0);
        previous=x;v.push_back(x);
    }
    return v;
}

void verify(const std::vector<Input>& v,const char* label) {
    Generated g;Software s;
    for(size_t i=0;i<v.size();++i) {
        if constexpr(stateful) if(g.preview(v[i])!=s.inspect(v[i])) {
            std::cerr<<"pre-edge mismatch "<<label<<" i="<<i<<'\n';std::exit(1);
        }
        const auto a=g.step(v[i]),b=s.step(v[i]);
        if(a!=b) {
            std::cerr<<"mismatch "<<label<<" i="<<i<<" input="<<v[i].a<<","<<v[i].b<<","<<unsigned(v[i].sel)
                     <<" generated="<<a.y<<","<<a.z<<" software="<<b.y<<","<<b.z<<'\n';
            std::exit(1);
        }
#if HAS_COMPUTE_SLICE
        const auto c=g.model.research_compute(v[i]);
        if(c!=a)throw std::runtime_error("extracted compute slice mismatch");
#endif
    }
}

template<class F> double measure(F fn,const std::vector<Input>& v,unsigned loops) {
    uint64_t sum=0;
    const auto start=std::chrono::steady_clock::now();
    for(unsigned k=0;k<loops;++k)for(const auto& x:v){auto y=fn(x);sum+=y.y^(y.z*17);}
    const auto end=std::chrono::steady_clock::now();
    observed=sum;
    return double(std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count())/(loops*v.size());
}

int main(int argc,char**argv) {
    const bool verify_only=argc>1&&std::string(argv[1])=="--verify";
    const unsigned loops=argc>1&&!verify_only?std::stoul(argv[1]):4;
    uint64_t checked=0;
    for(uint64_t seed:{UINT64_C(0x37c159),UINT64_C(0x95d273)})for(auto mode:{"random","sparse","dense","toggle1","hold99"}) {
        auto v=inputs(seed,mode,100000);verify(v,mode);checked+=v.size();
    }
    // Exhaust all complete input spaces that fit 2^16; otherwise random + directed.
    if constexpr(PATTERN_KIND==0 || PATTERN_KIND==3 || PATTERN_KIND==5 || PATTERN_KIND==12 || PATTERN_KIND==13 || PATTERN_KIND==19 || PATTERN_KIND==32 || PATTERN_KIND==34 || PATTERN_KIND==36 || PATTERN_KIND==44) {
        constexpr unsigned bits=PATTERN_KIND==3?12:PATTERN_KIND==19?8:PATTERN_KIND==36?4:16;
        std::vector<Input> v;for(unsigned i=0;i<(1u<<bits);++i)v.push_back({i,0,0,0,0,false});
        verify(v,"exhaustive");checked+=v.size();
    }
    if(verify_only){std::cout<<"{\"verified_vectors\":"<<checked<<",\"status\":\"pass\"}\n";return 0;}
    std::cout<<"{\"kind\":"<<PATTERN_KIND<<",\"verified_vectors\":"<<checked<<",\"pre_and_post_edge_checked\":"<<(stateful?"true":"false")<<",\"samples\":[";
    bool first=true;
    for(auto mode:{"random","sparse","dense","toggle1","hold99"}) {
        auto v=inputs(0x37c159,mode,16384);
        for(unsigned pair=0;pair<8;++pair) {
            Generated g;Software s;
            measure([&](const Input& x){return g.step(x);},v,1);
            measure([&](const Input& x){return s.step(x);},v,1);
            double a,b,core=0,coreSoftware=0;
            if(pair%2==0){a=measure([&](const Input& x){return g.step(x);},v,loops);b=measure([&](const Input& x){return s.step(x);},v,loops);}
            else{b=measure([&](const Input& x){return s.step(x);},v,loops);a=measure([&](const Input& x){return g.step(x);},v,loops);}
#if HAS_COMPUTE_SLICE
            measure([&](const Input& x){return g.model.research_compute(x);},v,1);
            if(pair%2==0) {
                core=measure([&](const Input& x){return g.model.research_compute(x);},v,loops);
                coreSoftware=measure([&](const Input& x){return s.step(x);},v,loops);
            } else {
                coreSoftware=measure([&](const Input& x){return s.step(x);},v,loops);
                core=measure([&](const Input& x){return g.model.research_compute(x);},v,loops);
            }
#endif
            if(!first)std::cout<<',';first=false;
            std::cout<<"{\"distribution\":\""<<mode<<"\",\"pair\":"<<pair<<",\"order\":\""<<(pair%2?"BA":"AB")
                     <<"\",\"generated_ns\":"<<a<<",\"software_ns\":"<<b;
#if HAS_COMPUTE_SLICE
            std::cout<<",\"compute_slice_ns\":"<<core<<",\"slice_software_ns\":"<<coreSoftware;
#endif
            std::cout<<'}';
        }
    }
    std::cout<<"],\"checksum\":"<<observed<<"}\n";
}
