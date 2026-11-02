// Slang elaborated-AST candidate discovery. No textual substitutions or files
// are written here; the Python layer applies an approved, source-bound edit.
#include "slang/analysis/AnalysisManager.h"
#include "slang/ast/ASTVisitor.h"
#include "slang/ast/Compilation.h"
#include "slang/ast/EvalContext.h"
#include "slang/driver/Driver.h"
#include "slang/syntax/AllSyntax.h"
#include "slang/text/Json.h"
#include <fstream>
#include <map>
#include <set>
#include <iostream>

using namespace slang;
using namespace slang::ast;
struct Names : ASTVisitor<Names, true, true> {
    std::set<const ValueSymbol*> values;
    void handle(const NamedValueExpression& expression) { values.insert(&expression.symbol); }
};
struct Discover : ASTVisitor<Discover, true, true> {
    std::vector<const ContinuousAssignSymbol*> assignments;
    std::set<const ValueSymbol*> events;
    void handle(const ContinuousAssignSymbol& symbol) { assignments.push_back(&symbol); }
    void handle(const SignalEventControl& control) {
        Names names; control.expr.visit(names);
        events.insert(names.values.begin(),names.values.end());
        if (control.iffCondition) { control.iffCondition->visit(names); events.insert(names.values.begin(),names.values.end()); }
    }
};
struct Candidate {
    std::string file, before, after;
    uint64_t begin=0,end=0,line=0,column=0,endLine=0,endColumn=0,width=0;
    bool safe=true; std::set<std::string> instances;
};

int main(int argc, char** argv) {
    try {
        if (argc < 4) throw std::runtime_error("usage: rtl_rewrite output.json top [slang filelist/options]");
        driver::Driver driver; driver.addStandardArgs(); driver.options.singleUnit=true;
        driver.options.compilationFlags.at(CompilationFlags::AllowTopLevelIfacePorts)=true;
        std::vector<const char*> args{argv[0],"--top",argv[2]};
        for (int i=3;i<argc;++i) args.push_back(argv[i]);
        if (!driver.parseCommandLine(args.size(),args.data()) || !driver.processOptions() || !driver.parseAllSources())
            throw std::runtime_error("RTL parse failed");
        auto compilation=driver.createCompilation();
        driver.runAnalysis(*compilation); driver.reportCompilation(*compilation,true);
        if (!driver.reportDiagnostics(true)) throw std::runtime_error("RTL elaboration failed");
        Discover discovery; compilation->getRoot().visit(discovery);
        // Protect combinational cones that feed event expressions, including
        // asynchronous reset and gated clock, by resolved symbol identity.
        bool changed=true;
        while (changed) {
            changed=false;
            for (auto* symbol:discovery.assignments) {
                const auto& expression=symbol->getAssignment();
                if (expression.kind!=ExpressionKind::Assignment) continue;
                const auto& assign=expression.as<AssignmentExpression>();
                Names lhs,rhs; assign.left().visit(lhs); assign.right().visit(rhs);
                bool feeds=false; for(auto* value:lhs.values) feeds |= discovery.events.contains(value);
                if (feeds) for(auto* value:rhs.values) changed |= discovery.events.insert(value).second;
            }
        }
        std::map<std::tuple<std::string,uint64_t,uint64_t>,Candidate> candidates;
        auto& sm=driver.sourceManager;
        for (auto* symbol:discovery.assignments) {
            const auto& expression=symbol->getAssignment();
            if (expression.kind!=ExpressionKind::Assignment) continue;
            const auto& assign=expression.as<AssignmentExpression>();
            // Only a complete RHS slice of a simple unsigned packed value.
            // Preserve the assignment process, driver, scheduling and 4-state type.
            const auto& rhs=assign.right();
            const auto range=rhs.sourceRange;
            if (!sm.isFileLoc(range.start()) || !sm.isFileLoc(range.end()) || range.start().buffer()!=range.end().buffer()) continue;
            const auto file=sm.getFullPath(range.start().buffer()).string();
            const auto key=std::make_tuple(file,range.start().offset(),range.end().offset());
            auto& item=candidates[key];
            item.file=file; item.begin=range.start().offset();item.end=range.end().offset();
            item.instances.insert(symbol->getHierarchicalPath());
            if (rhs.kind!=ExpressionKind::RangeSelect) { item.safe=false; continue; }
            const auto& select=rhs.as<RangeSelectExpression>();
            bool safe=!symbol->getDelay() && !assign.timingControl && !assign.isCompound();
            const auto& base=select.value();
            safe &= base.kind==ExpressionKind::NamedValue;
            safe &= base.type->isSimpleBitVector() && !base.type->isSigned() && !rhs.type->isSigned();
            safe &= base.type->getBitWidth()==rhs.type->getBitWidth() && base.type->isFourState()==rhs.type->isFourState();
            safe &= select.getSelectionKind()==RangeSelectionKind::Simple;
            Names lhs;assign.left().visit(lhs);
            for(auto* value:lhs.values) safe &= !discovery.events.contains(value);
            if (safe) {
                EvalContext eval(*symbol);
                const auto left=select.left().eval(eval),right=select.right().eval(eval);
                const auto bounds=base.type->getFixedRange();
                safe &= left.isInteger() && right.isInteger();
                if(safe) {
                    const auto l=left.integer().as<int64_t>(),r=right.integer().as<int64_t>();
                    safe &= l && r && *l==bounds.left && *r==bounds.right;
                }
            }
            // Slang's bound NamedValue can carry the whole selected name's
            // source range. Use its CST identifier token, not that broad range.
            safe &= rhs.syntax && rhs.syntax->kind==syntax::SyntaxKind::IdentifierSelectName;
            std::string replacement;
            if (safe) {
                const auto& name=rhs.syntax->as<syntax::IdentifierSelectNameSyntax>();
                safe &= name.selectors.size()==1 && sm.isFileLoc(name.identifier.location());
                replacement=std::string(name.identifier.rawText());
                if (!replacement.empty() && replacement.front()=='\\') replacement+=' ';
            }
            item.safe &= safe;
            if (!safe) continue;
            const auto text=sm.getSourceText(range.start().buffer());
            if(item.end>text.size() || item.begin>=item.end) throw std::runtime_error("invalid AST source range");
            if(!item.after.empty() && item.after!=replacement) item.safe=false;
            item.before=std::string(text.substr(item.begin,item.end-item.begin));item.after=replacement;
            if(item.before==item.after || item.after.empty()) item.safe=false;
            item.line=sm.getLineNumber(range.start());item.column=sm.getColumnNumber(range.start());
            item.endLine=sm.getLineNumber(range.end());item.endColumn=sm.getColumnNumber(range.end());item.width=rhs.type->getBitWidth();
        }
        JsonWriter json;json.startObject();json.writeProperty("schema_version");json.writeValue(uint64_t(1));
        json.writeProperty("engine");json.writeValue("slang-elaborated-ast"sv);
        json.writeProperty("rule");json.writeValue("unsigned-full-width-static-slice"sv);
        json.writeProperty("candidates");json.startArray();
        uint64_t accepted=0,rejected=0;
        for (const auto& [key,item]:candidates) {
            if(!item.safe) {++rejected;continue;}
            ++accepted;json.startObject();
            for(const auto& [name,value]:std::initializer_list<std::pair<std::string_view,std::string_view>>{
                {"file",item.file},{"before",item.before},{"after",item.after}}) {json.writeProperty(name);json.writeValue(value);}
            for(const auto& [name,value]:std::initializer_list<std::pair<std::string_view,uint64_t>>{
                {"begin",item.begin},{"end",item.end},{"line",item.line},{"column",item.column},
                {"end_line",item.endLine},{"end_column",item.endColumn},{"width",item.width}}) {json.writeProperty(name);json.writeValue(value);}
            json.writeProperty("instances");json.startArray();for(const auto& name:item.instances)json.writeValue(name);json.endArray();
            json.endObject();
        }
        json.endArray();json.writeProperty("rejected_sites");json.writeValue(rejected);json.endObject();
        std::ofstream output(argv[1]);output<<json.view()<<'\n';if(!output) throw std::runtime_error("cannot write AST candidates");
        std::cerr<<"[rtl-rewrite] candidates="<<accepted<<" rejected="<<rejected<<'\n';
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
