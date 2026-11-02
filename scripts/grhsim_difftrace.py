"""Compare generated Difftest records, ignoring C padding and invalid payloads."""
from pathlib import Path
import json
import re
import subprocess
from grhsim_single_baseline import identity, save


def build_comparator(header, directory):
    header=Path(header).resolve();directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    structs={}
    for body,name in re.findall(r'typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;',header.read_text(),re.S):
        fields=[]
        for line in body.splitlines():
            line=line.strip()
            if not line:continue
            match=re.fullmatch(r'(\w+)\s+(\w+)\s*((?:\[\d+\])*)\s*;',line)
            if not match:raise ValueError('unrecognized Difftest field: '+line)
            fields.append((match[1],match[2],[int(n) for n in re.findall(r'\d+',match[3])]))
        structs[name]=fields
    if 'DiffTestState' not in structs:raise ValueError('missing DiffTestState')
    code=[];primitive_fields=0
    def emit(typ,a,b,depth=0):
        nonlocal primitive_fields
        fields=structs[typ];valid=next((f for f in fields if f[1]=='valid'),None)
        if valid:
            if valid[2]:raise ValueError('array validity is unsupported')
            code.append(f'if ({a}.valid != {b}.valid) return "{a}.valid";')
            code.append(f'if ({a}.valid) {{')
        for field_type,name,dims in fields:
            if name=='valid':continue
            left=a+'.'+name;right=b+'.'+name
            if field_type in structs:
                for i,n in enumerate(dims):
                    index=f'i{depth}_{i}';code.append(f'for (unsigned {index}=0; {index}<{n}; ++{index}) {{')
                    left+='['+index+']';right+='['+index+']'
                special=typ=='DiffTestState' and name=='commit_data'
                if special:
                    if dims!=next(f[2] for f in structs['DiffTestState'] if f[1]=='commit'):
                        raise ValueError('commit data/valid dimensions differ')
                    code.append(f'if ({a}.commit[i{depth}_0].valid) {{')
                emit(field_type,left,right,depth+1)
                if special:code.append('}')
                code.extend('}' for _ in dims)
            else:
                if not re.fullmatch(r'u?int(8|16|32|64)_t',field_type):raise ValueError('unsupported trace scalar '+field_type)
                code.append(f'if (std::memcmp(&{left}, &{right}, sizeof({left}))) return "{left}";')
                primitive_fields+=1
        if valid:code.append('}')
    emit('DiffTestState','a','b')
    source=directory/'compare.cpp'
    source.write_text('#include '+json.dumps(str(header))+'\n'+r'''
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>
const char* difference(const DiffTestState &a,const DiffTestState &b) {
'''+ '\n'.join(code)+r'''
return nullptr;
}
int main(int argc,char **argv) {
 if(argc!=3)return 2;
 std::ifstream fa(argv[1],std::ios::binary),fb(argv[2],std::ios::binary);
 if(!fa||!fb)return 3;
 DiffTestState a{},b{};uint64_t count=0,first=0,last=0;
 while(true){
  fa.read(reinterpret_cast<char*>(&a),sizeof a);fb.read(reinterpret_cast<char*>(&b),sizeof b);
  const auto na=fa.gcount(),nb=fb.gcount();
  if(!na&&!nb)break;
  if(na!=sizeof a||nb!=sizeof b){std::cerr<<"missing/partial record at "<<count<<'\n';return 4;}
  if(const char* field=difference(a,b)){std::cerr<<"mismatch record="<<count<<" field="<<field<<'\n';return 5;}
  if(!count)first=a.trap.cycleCnt;last=a.trap.cycleCnt;++count;
 }
 if(!count)return 6;
 std::cout<<"{\"records\":"<<count<<",\"record_bytes\":"<<sizeof a
   <<",\"first_cycle\":"<<first<<",\"last_cycle\":"<<last<<"}\n";
}
''')
    command=['c++','-std=c++20','-O2',str(source),'-o',str(directory/'compare')]
    save(directory/'build.json',dict(header=identity(header),source=identity(source),command=command,
        primitive_field_checks=primitive_fields,valid_gated_types=[k for k,v in structs.items() if any(f[1]=='valid' for f in v)],
        note='commit_data[i] additionally gated by commit[i].valid; C structure padding ignored'))
    subprocess.run(command,check=True)
    return directory/'compare'


def compare_traces(comparator,a,b,output):
    a,b=Path(a),Path(b)
    names_a=sorted(p.name for p in a.glob('*.bin'));names_b=sorted(p.name for p in b.glob('*.bin'))
    if not names_a or names_a!=names_b:raise ValueError('missing/mismatched trace chunks')
    indices=sorted(int(Path(n).stem) for n in names_a)
    if indices!=list(range(len(indices))):raise ValueError('missing trace chunk sequence')
    chunks=[]
    for i in indices:
        name=f'{i}.bin'
        result=subprocess.run([comparator,a/name,b/name],text=True,capture_output=True)
        if result.returncode:
            save(output,dict(pass_=False,chunk=name,stdout=result.stdout,stderr=result.stderr))
            raise ValueError('Difftest trace differs: '+result.stderr)
        chunks.append(dict(name=name,**json.loads(result.stdout),a=identity(a/name),b=identity(b/name)))
    record=dict(pass_=True,chunks=chunks,records=sum(c['records'] for c in chunks),
                scope='All generated Difftest fields in order; validity-gated payloads; cycle fields included')
    save(output,record);return record
