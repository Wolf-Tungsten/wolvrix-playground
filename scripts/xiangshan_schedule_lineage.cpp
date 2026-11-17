// Offline exact mapping of two schedule inventories; no graph generation/runtime.
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
constexpr uint32_t none=std::numeric_limits<uint32_t>::max();
uint32_t symbol(const std::string &s) {
    if(!s.starts_with("_op_"))throw std::runtime_error("unexpected nonnumeric operation symbol: "+s);
    return std::stoul(s.substr(4));
}
std::vector<uint32_t> members(const std::string &path) {
    std::ifstream in(path);if(!in)throw std::runtime_error("missing inventory");
    std::vector<uint32_t> result;std::string name;uint32_t group;
    while(in>>name>>group) {
        const auto id=symbol(name);if(id>=result.size())result.resize(id+100000,none);
        if(result[id]!=none)throw std::runtime_error("duplicate operation");result[id]=group;
    }
    return result;
}
std::vector<uint64_t> edges(const std::string &path) {
    std::ifstream in(path);if(!in)throw std::runtime_error("missing edges");
    std::vector<uint64_t> result;std::string a,b;
    while(in>>a>>b)result.push_back((uint64_t(symbol(a))<<32)|symbol(b));
    std::sort(result.begin(),result.end());return result;
}
int main(int argc,char **argv) {
    try {
        if(argc!=3&&argc!=4)throw std::runtime_error("usage: lineage directory group-count [frozen-model]");
        const std::string root=argv[1];const auto count=std::stoul(argv[2]);
        auto before=members(root+"/unshared-members.tsv"),after=members(root+"/shared-members.tsv");
        const auto n=std::max(before.size(),after.size());before.resize(n,none);after.resize(n,none);
        uint64_t operations=0;std::vector<std::set<uint32_t>> origins(count);
        for(std::size_t i=0;i<n;++i) {
            if((before[i]==none)!=(after[i]==none))throw std::runtime_error("operation set mismatch");
            if(after[i]!=none){++operations;origins.at(after[i]).insert(before[i]);}
        }
        uint64_t matchedComments=0;
        if(argc==4)for(const auto &entry:std::filesystem::directory_iterator(argv[3])) {
            const auto filename=entry.path().filename().string();
            if(filename.find("_sched_")==std::string::npos||!filename.ends_with(".cpp"))continue;
            std::ifstream cpp(entry.path());std::string line;uint32_t group=none;
            while(std::getline(cpp,line)) {
                if(const auto at=line.find("// Supernode ");at!=std::string::npos)group=std::stoul(line.substr(at+13));
                if(const auto at=line.find("// op ");at!=std::string::npos) {
                    const auto end=line.find(' ',at+6);const auto op=symbol(line.substr(at+6,end-at-6));
                    if(group==none||op>=after.size()||after[op]!=group)
                        throw std::runtime_error("frozen C++ operation/group differs from static replay: "+line);
                    ++matchedComments;
                }
            }
        }
        auto a=edges(root+"/unshared-work-edges.tsv"),b=edges(root+"/shared-work-edges.tsv");
        if(a!=b)throw std::runtime_error("exact operand edge multiset mismatch");
        std::vector<uint64_t> removed(count),createdOut(count),createdIn(count),internal(count);
        uint64_t oldBoundary=0,newBoundary=0,removedTotal=0,createdTotal=0,missing=0;
        for(const auto key:a) {
            const uint32_t p=key>>32,c=key;
            if(p>=n||c>=n||after[p]==none||after[c]==none){++missing;
                std::cerr<<"Unscheduled work edge: _op_"<<p<<" -> _op_"<<c<<'\n';continue;}
            const bool oldCross=before[p]!=before[c],newCross=after[p]!=after[c];
            oldBoundary+=oldCross;newBoundary+=newCross;
            if(!newCross)++internal.at(after[p]);
            if(oldCross&&!newCross){++removedTotal;++removed.at(after[p]);}
            if(!oldCross&&newCross){++createdTotal;++createdOut.at(after[p]);++createdIn.at(after[c]);}
        }
        std::ofstream out(root+"/schedule-lineage.json");
        out<<"{\"operations\":"<<operations<<",\"matched_cpp_operation_comments\":"<<matchedComments
           <<",\"operand_edges\":"<<a.size()<<",\"unscheduled_edges\":"<<missing
           <<",\"exact_edge_multiset_equal\":true,\"before_boundary_edges\":"<<oldBoundary
           <<",\"after_boundary_edges\":"<<newBoundary<<",\"removed_edges\":"<<removedTotal
           <<",\"created_edges\":"<<createdTotal<<",\"groups\":[";
        for(std::size_t i=0;i<count;++i) {
            if(i)out<<',';out<<"{\"group\":"<<i<<",\"original_groups\":"<<origins[i].size()
               <<",\"internal_edges\":"<<internal[i]<<",\"removed_boundary_edges\":"<<removed[i]
               <<",\"created_out_edges\":"<<createdOut[i]<<",\"created_in_edges\":"<<createdIn[i]<<'}';
        }
        out<<"],\"limit\":\"Exact static operand-edge occurrences excluding constant/register/latch-read source or consumer. Not unique boundary values, runtime activations or profitability proof.\"}\n";
        std::cout<<operations<<" exact operations; "<<a.size()<<" exact work operand edges; removed "
                 <<removedTotal<<" created "<<createdTotal<<" missing "<<missing<<'\n';
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
