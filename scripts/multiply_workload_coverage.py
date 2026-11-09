#!/usr/bin/env python3
"""Check committed instruction coverage in the directed workload's DiffTest trace."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
from grhsim_single_baseline import identity,save


def parse_instructions(disassembly):
    instructions=[]
    pattern=re.compile(r'^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+([a-z][a-z0-9.]*)\s*(.*?)\s*$')
    for line in disassembly.splitlines():
        match=pattern.match(line)
        if not match:
            continue
        pc,encoding,mnemonic,operands=match.groups()
        operands=operands.split('#',1)[0].strip()
        args=[part.strip() for part in operands.split(',')]
        instructions.append(dict(pc=int(pc,16),encoding=int(encoding,16),mnemonic=mnemonic,
            operands=args))
    return instructions


def fused_mulw7_sites(instructions):
    """Return scalar multiply sites, treating XiangShan's MULW7 fusion as one commit.

    XiangShan commits the leading ANDI with nFused=1 and does not emit a
    separate commit record for the following MULW. The follower remains the
    instruction whose multiply capability is being covered, but its trace
    predicate is the leader PC/encoding plus nFused.
    """
    multiply=lambda item:any(operation in item['mnemonic']
        for operation in ('mul','macc','msac','madd','msub'))
    sites=[];consumed=set()
    for index,item in enumerate(instructions):
        if not multiply(item) or index in consumed:
            continue
        if item['mnemonic']=='mulw' and index > 0:
            leader=instructions[index-1]
            if (leader['mnemonic']=='andi' and len(leader['operands'])==3 and
                leader['operands'][2] in ('127','0x7f') and
                len(item['operands'])==3 and leader['operands'][0]==item['operands'][0] and
                item['operands'][1]==leader['operands'][0] and
                item['operands'][1]!=item['operands'][2]):
                sites.append(dict(pc=item['pc'],encoding=item['encoding'],mnemonic='mulw7',
                    source_mnemonic='mulw',fused_from=dict(pc=leader['pc'],
                        instruction=leader['encoding'],mnemonic=leader['mnemonic']),
                    trace_pc=leader['pc'],trace_instruction=leader['encoding'],
                    require_fused=True))
                consumed.add(index)
                continue
        sites.append(dict(pc=item['pc'],encoding=item['encoding'],mnemonic=item['mnemonic'],
            source_mnemonic=item['mnemonic'],trace_pc=item['pc'],
            trace_instruction=item['encoding'],require_fused=False))
        consumed.add(index)
    return sites


def main():
    p=argparse.ArgumentParser();p.add_argument('--header',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True);p.add_argument('--disassembly',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    instructions=parse_instructions(args.disassembly.read_text())
    sites=fused_mulw7_sites(instructions)
    assert sites
    lines=[]
    for i,site in enumerate(sites):
        fused=' || c.nFused < 1' if site['require_fused'] else ''
        lines.append(f"case UINT64_C({site['trace_pc']}): if(c.instr!=UINT32_C({site['trace_instruction']}){fused})return 6; ++counts[{i}]; break;")
    code='#include '+json.dumps(str(args.header.resolve()))+'\n'+r'''
#include <cstdint>
#include <fstream>
#include <iostream>
#include <array>
int main(int argc,char**argv){
  std::array<std::uint64_t,COUNT> counts{};DiffTestState state{};
  for(int n=1;n<argc;++n){
    std::ifstream stream(argv[n],std::ios::binary);if(!stream)return 2;
    while(stream.read(reinterpret_cast<char*>(&state),sizeof state)){
      for(const auto&c:state.commit)if(c.valid){switch(c.pc){CASES default:break;}}
    }
    if(!stream.eof())return 3;
  }
  for(auto count:counts)std::cout<<count<<'\n';
}
'''
    code=code.replace('COUNT',str(len(sites))).replace('CASES','\n'.join(lines))
    source=out/'coverage.cpp';source.write_text(code)
    subprocess.run(['c++','-std=c++20','-O2',str(source),'-o',str(out/'coverage')],check=True)
    files=sorted(args.trace.glob('*.bin'),key=lambda p:int(p.stem));assert files
    result=subprocess.check_output([str(out/'coverage'),*[str(p) for p in files]],text=True)
    counts=[int(n) for n in result.split()];assert len(counts)==len(sites)
    rows=[]
    for site,count in zip(sites,counts):
        row=dict(pc=hex(site['pc']),instruction=hex(site['encoding']),
            mnemonic=site['mnemonic'],source_mnemonic=site['source_mnemonic'],commits=count)
        if site['require_fused']:
            row['fused_from']={**site['fused_from'],
                'pc':hex(site['fused_from']['pc']),
                'instruction':hex(site['fused_from']['instruction'])}
        rows.append(row)
    summary=Counter()
    for row in rows:summary[row['mnemonic']]+=row['commits']
    save(out/'summary.json',dict(pass_=all(counts),instruction_sites=rows,mnemonics=dict(summary),
        header=identity(args.header),disassembly=identity(args.disassembly),trace=[identity(p) for p in files]))
    if not all(counts):raise ValueError('directed multiply instruction did not retire')
    print(json.dumps(dict(summary)))


if __name__=='__main__':main()
