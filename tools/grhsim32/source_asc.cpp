// Read-only exact-symbol attribution to the original, indivisible ASC graph.
#include "repcut_grhsim_assignment_extract.hpp"
#include "grhsim_source_export.hpp"

int main(int argc, char** argv) {
    try {
        if (argc!=5) throw std::runtime_error("usage: source_asc raw.json assignment.txt queries.txt output.csv");
        std::unordered_map<std::string,std::set<uint32_t>> requested;
        { std::ifstream f(argv[3]); std::string line; while(std::getline(f,line)) {
              const auto split=line.find('\t');
              if(split==std::string::npos) throw std::runtime_error("query must contain partition and operation symbol");
              requested[line.substr(split+1)].insert(std::stoul(line.substr(0,split)));
          }
          if(!f.eof()) throw std::runtime_error("cannot read query symbols"); }
        std::vector<uint32_t> assignment;
        { std::ifstream f(argv[2]); uint32_t part; while(f>>part) assignment.push_back(part);
          if(!f.eof()) throw std::runtime_error("cannot read assignment"); }
        grh::Design design;
        { Mapping input(argv[1]); design=grh::Design::fromJsonString(input.text()); }
        if(design.topGraphs().size()!=1) throw std::runtime_error("one raw top required");
        auto& graph=*design.findGraph(design.topGraphs()[0]);
        const auto a=buildPhaseAData(graph);
        std::unordered_set<grh::ValueId,grh::ValueIdHash> inouts;
        for(const auto& port:graph.inoutPorts()) inouts.insert(port.in);
        auto b=buildAscs(graph,a,inouts,[](const std::string& text) {
            if(text.find("progress")==std::string::npos) std::cerr<<text<<'\n';
        });
        if(assignment.size()!=b.ascs.size()) throw std::runtime_error("raw ASC count differs from assignment");
        // buildAscs forms cones; buildPieces constructs the reverse membership
        // used below. Keep the same builder as the clean assignment flow.
        buildPieces(b,a,{});
        std::ofstream out(argv[4]);
        out<<"op_symbol,op_kind,raw_op_index,value_symbols,part,asc_ids\n";
        uint64_t found=0;
        for(uint32_t n=0;n<a.nodeToOp.size();++n) {
            const auto op=graph.getOperation(a.nodeToOp[n]);
            if(!requested.contains(std::string(op.symbolText()))) continue;
            ++found;std::map<uint32_t,std::vector<uint32_t>> owners;
            for(auto asc:b.nodeToAscs.at(n)) if(requested.at(std::string(op.symbolText())).contains(assignment.at(asc)))
                owners[assignment.at(asc)].push_back(asc);
            std::string values;
            for(auto v:op.results()) {if(!values.empty())values+=';';values+=graph.getValue(v).symbolText();}
            for(const auto& [part,ids]:owners) {
                std::string joined;
                for(auto id:ids){if(!joined.empty())joined+=';';joined+=std::to_string(id);}
                out<<grhsim_source_export::csv(op.symbolText())<<','<<grh::toString(op.kind())<<','
                   <<a.nodeToOp[n].index<<','<<grhsim_source_export::csv(values)<<','<<part<<','
                   <<grhsim_source_export::csv(joined)<<'\n';
            }
        }
        if(!out) throw std::runtime_error("ASC map write failed");
        std::cout<<"ASC_MAP atoms="<<b.ascs.size()<<" queried="<<requested.size()<<" exact_symbols="<<found<<'\n';
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
