#include "core/grh.hpp"
#include "core/store.hpp"
#include "core/transform.hpp"
#include "transform/dead_code_elim.hpp"
#include "transform/slice_demand.hpp"
#include <fstream>
#include <iostream>
#include <iterator>

int main(int argc,char **argv) {
    using namespace wolvrix::lib;
    try {
        if(argc!=4 || (std::string_view(argv[3])!="on" && std::string_view(argv[3])!="off"))
            throw std::runtime_error("usage: slice-demand graph.json output.json on|off");
        std::ifstream input(argv[1]);if(!input)throw std::runtime_error("missing graph");
        auto design=grh::Design::fromJsonString(std::string(std::istreambuf_iterator<char>(input),{}));
        transform::PassManager manager;manager.options().logLevel=LogLevel::Info;
        manager.options().logSink=[](LogLevel,std::string_view tag,std::string_view msg){std::cerr<<'['<<tag<<"] "<<msg<<'\n';};
        manager.addPass(std::make_unique<transform::SliceDemandPass>(transform::SliceDemandOptions{std::string_view(argv[3])=="on"}));
        manager.addPass(std::make_unique<transform::DeadCodeElimPass>());
        transform::PassDiagnostics pd;
        if(!manager.run(design,pd).success || pd.hasError()) {
            for(const auto &d:pd.messages())std::cerr<<d.message<<'\n';
            throw std::runtime_error("slice-demand failed");
        }
        store::StoreOptions options;options.outputFilename=argv[2];options.topOverrides={"Cv32Bench"};
        if(!store::StoreJson().store(design,options).success)throw std::runtime_error("store failed");
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
