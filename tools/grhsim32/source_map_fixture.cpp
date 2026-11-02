#include "grhsim_source_export.hpp"
#include "core/store.hpp"
#include <iostream>

using namespace wolvrix::lib;

int main(int argc, char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("usage: source_map_fixture artifact_directory");
        const std::filesystem::path out(argv[1]);std::filesystem::create_directories(out);
        grh::Design design;auto& graph=design.createGraph("fixture");design.markAsTop("fixture");
        auto value=[&](const std::string& name){return graph.createValue(graph.internSymbol(name),8,false);};
        const auto input=value("a");graph.bindInputPort("a",input);
        std::vector<grh::OperationId> operations;
        auto op=[&](grh::OperationKind kind,const std::string& name,grh::ValueId operand){
            const auto id=graph.createOperation(kind,graph.internSymbol(name));
            graph.addOperand(id,operand);const auto result=value(name+"_value");graph.addResult(id,result);
            graph.setOpSrcLoc(id,{"fixture.sv",uint32_t(operations.size()+1),1,uint32_t(operations.size()+1),12,"rtl","fixture","retained source"});
            operations.push_back(id);return result;
        };
        auto address=input;
        for(unsigned i=0;i<5;++i) address=op(grh::OperationKind::kNot,"address"+std::to_string(i),address);
        const auto read=op(grh::OperationKind::kMemoryReadPort,"memory_read",address);
        graph.setAttr(graph.valueDef(read),"memSymbol",std::string("memory"));
        const auto next=op(grh::OperationKind::kNot,"after_memory",read);
        const auto last=op(grh::OperationKind::kNot,"result",next);graph.bindOutputPort("y",last);
        auto& clone=design.cloneGraph("fixture","clone");
        for(auto id:operations) {
            const auto a=graph.opSrcLoc(id),b=clone.opSrcLoc(clone.findOperation(graph.getOperation(id).symbolText()));
            if(!a||!b||a->file!=b->file||a->endColumn!=b->endColumn||a->pass!=b->pass)
                throw std::runtime_error("clone lost source provenance");
        }
        store::StoreOptions stored;stored.outputFilename=(out/"fixture.json").string();
        if(!store::StoreJson().store(design,stored).success) throw std::runtime_error("store failed");
        std::ifstream saved(out/"fixture.json");std::string json((std::istreambuf_iterator<char>(saved)),{});
        auto roundtrip=grh::Design::fromJsonString(json);
        const auto* restored=roundtrip.findGraph("fixture");
        const auto restoredLoc=restored->opSrcLoc(restored->findOperation("address0"));
        if(!restoredLoc || restoredLoc->endColumn!=12)
            throw std::runtime_error("roundtrip lost source range");
        emit::GrhSimExecutionPlan plan;
        plan.groups.push_back({0,0,emit::GrhSimExecutionPlan::Phase::Compute,8,operations});
        plan.batches.push_back({0,emit::GrhSimExecutionPlan::Phase::Compute,8,{{0,{0},{}}}});
        emit::GrhSimActivityReport activity;
        std::vector<uint32_t> weights(operations.back().index+1,1);
        activity.operationMasks.assign(weights.size(),3);activity.computeGroupMasks={3};
        grhsim_source_export::write(graph,plan,activity,weights,"inst_part_0",out);
        // Even though the memory address has a long combinational cone, the
        // path beginning at the memory result must not include that cone.
        std::ifstream paths(out/"inst_part_0.paths.csv");std::string line;std::getline(paths,line);
        std::map<std::pair<int,int>,std::vector<unsigned>> chains;
        while(std::getline(paths,line)) {
            std::vector<std::string> fields;std::istringstream row(line);std::string field;
            while(std::getline(row,field,',')) fields.push_back(field);
            chains[{std::stoi(fields[1]),std::stoi(fields[2])}].push_back(std::stoul(fields[6]));
        }
        bool found=false;
        for(const auto& [key,path]:chains) if(path.back()==graph.valueDef(last).index) {
            found=true;if(path.size()!=3||path.front()!=graph.valueDef(read).index)
                throw std::runtime_error("static path crossed a memory boundary");
        }
        if(!found) throw std::runtime_error("missing memory-result path");
        for(auto kind:{grh::OperationKind::kRegisterReadPort,grh::OperationKind::kLatchReadPort,
                       grh::OperationKind::kMemoryWritePort,grh::OperationKind::kDpicCall,grh::OperationKind::kSystemTask})
            if(!grhsim_source_export::boundary(kind)) throw std::runtime_error("missing semantic boundary");
        std::cout<<"source-map fixture PASS\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
