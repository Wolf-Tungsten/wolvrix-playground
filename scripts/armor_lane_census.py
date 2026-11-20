"""Apply the shared C++ planner to every frozen compute scheduling sidecar."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import re

from grhsim_single_baseline import identity, save


def census(tool, model, out, require_emitted=False):
    files = sorted(model.glob('*.lanes.tsv'))
    if not files:
        raise ValueError('no lane inventory for '+str(model))
    out.mkdir(parents=True, exist_ok=True)

    def batch(f):
        name=f.name.split('.')[0]
        packfile, countfile = (out/(name+ext) for ext in ('.packs.tsv','.counts.tsv'))
        subprocess.run([tool,f,packfile,countfile],check=True)
        members=[row.split('\t') for row in packfile.read_text().splitlines()]
        pattern=re.compile(r'// Boolean lane pack: first=(\d+) lanes=(\d+) levels=(\d+) members=(\d+)')
        expected=Counter((row[12].split(',')[0],row[3],row[4],str(len(row[12].split(',')))) for row in members)
        with f.with_suffix('').with_suffix('').open() as stream:
            actual=Counter(m.groups() for line in stream if 'Boolean lane pack:' in line if (m:=pattern.search(line)))
        return packfile,countfile,(expected==actual)


    total=Counter()
    members=set()
    gates=[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for packs,counts,equal in pool.map(batch,files):
            gates.append(equal)
            for row in counts.read_text().splitlines():
                _,key,value=row.split('\t')
                total[key]+=int(value)
            for row in packs.read_text().splitlines():
                grp,anchor,sink,lanes,depth,gather,cost,bcasts,exits,old,new,named,ids=row.split('\t')
                unique={int(x) for x in ids.split(',')}
                if len(unique)!=len(ids.split(',')) or members.intersection(unique):
                    raise ValueError('overlapping packs in '+row)
                members.update(unique)
                total.update(packs=1,roots=int(lanes),covered_bit_ops=len(unique),scalar_estimate=int(old),
                    packed_estimate=int(new),individual_input_bits=int(gather),gather_ops=int(cost),
                    broadcast_words=int(bcasts),scalar_exits=int(exits),reductions=bool(int(sink)),
                    named_packs=int(named))
                total['depth_'+depth]+=1
    save(out/'summary.json',dict(counters=dict(total),batches=len(files),tool=identity(tool),members_match_source=all(gates)))
    if require_emitted and not all(gates):
        raise ValueError('planned members or sizes differ from emitted pack markers')
    print(dict(total),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('model',type=Path);p.add_argument('output',type=Path);p.add_argument('--tool',required=True,type=Path)
    p.add_argument('--require-emitted',action='store_true',help='require one matching source marker per pack')
    a=p.parse_args();census(a.tool.resolve(),a.model,a.output,a.require_emitted)
