"""Validate measurement provenance and summarize paired kernel experiments."""
from collections import Counter
import csv
import json
import math
from pathlib import Path
import re
import statistics

from chisel_pattern_bench import CASES, DISTRIBUTIONS, STATEFUL, identity, save


def validate_samples(data, distributions=DISTRIBUTIONS):
    if data.get('verified_vectors',0)<1000000:
        raise ValueError('missing two-seed / five-distribution functional validation')
    rows=data.get('samples',[])
    if len(rows)!=8*len(distributions):raise ValueError('incomplete measurement window')
    seen=set()
    for r in rows:
        key=r['distribution'],r['pair']
        if key in seen or r['distribution'] not in distributions or r['pair'] not in range(8):
            raise ValueError('duplicate or invalid paired sample')
        seen.add(key)
        if r['order']!=('AB' if r['pair']%2==0 else 'BA'):raise ValueError('incorrect AB/BA order')
        for field in ['generated_ns','software_ns']+(['compute_slice_ns','slice_software_ns'] if 'compute_slice_ns' in r else []):
            if not isinstance(r.get(field),(float,int)) or not math.isfinite(r[field]) or r[field]<=0:
                raise ValueError('invalid measurement value')
    return rows


def assembly_function(text, pattern):
    headers=list(re.finditer(r'^([0-9a-f]+) <([^\n]+)>:\n',text,re.M))
    for index,m in enumerate(headers):
        if re.search(pattern,m[2]):
            end=headers[index+1].start() if index+1<len(headers) else len(text)
            body=text[m.end():end]
            # objdump -d separates address, bytes and mnemonic using tabs.
            mnemonics=[]
            for line in body.splitlines():
                fields=line.split('\t')
                if len(fields)>=3 and fields[2].strip():mnemonics.append(fields[2].strip().split()[0])
            return dict(name=m[2],address=int(m[1],16),instructions=len(mnemonics),
                        mnemonics=dict(Counter(mnemonics)),body=body)
    return None


def summarize(root):
    root=Path(root)
    errors=json.loads((root/'errors.json').read_text())
    if errors:raise ValueError('benchmark run contains failures')
    results={}
    for name in CASES:
        case=root/'cases'/name
        build=json.loads((case/'build.json').read_text())
        for rec in [build['binary'],*build['inputs'],*build['generated']]:
            actual=identity(rec['path'])
            if actual['sha256']!=rec['sha256'] or actual['bytes']!=rec['bytes']:
                raise ValueError(f'changed benchmark input or binary: {rec["path"]}')
        data=json.loads((case/'measurement.json').read_text())
        rows=validate_samples(data)
        if data['kind']!=CASES.index(name):raise ValueError('case identifier mismatch')
        if name in STATEFUL and not data.get('pre_and_post_edge_checked'):
            raise ValueError('stateful case lacks pre/post-edge checks')
        assembly=(case/'assembly.txt').read_text()
        symbols=(case/'symbols.txt').read_text()
        functions={}
        for label,pattern in [('generated',r'^GrhSIM_Pattern::research_compute\('),('software',r'^Software::step\(')]:
            record=assembly_function(assembly,pattern)
            if record:
                match=re.search(r'^[0-9a-f]+\s+([0-9a-f]+)\s+\w\s+'+re.escape(record['name'])+r'$',symbols,re.M)
                if match:record['bytes']=int(match[1],16)
                (case/(label+'_function.asm')).write_text(record.pop('body'))
                functions[label]=record
        summary=[]
        for distribution in DISTRIBUTIONS:
            group=[r for r in rows if r['distribution']==distribution]
            row=dict(distribution=distribution,pairs=8)
            fields=['generated_ns','software_ns']+(['compute_slice_ns','slice_software_ns'] if 'compute_slice_ns' in group[0] else [])
            for field in fields:row[field]=statistics.median(r[field] for r in group)
            for label,a,b in [('eval','generated_ns','software_ns'),*([('kernel','compute_slice_ns','slice_software_ns')] if 'compute_slice_ns' in group[0] else [])]:
                ratios=[100*(r[b]/r[a]-1) for r in group]
                row[label+'_delta_percent']=statistics.median(ratios)
                row[label+'_delta_min']=min(ratios);row[label+'_delta_max']=max(ratios)
                row[label+'_delta_iqr']=statistics.quantiles(ratios,n=4)[2]-statistics.quantiles(ratios,n=4)[0]
            summary.append(row)
        results[name]=dict(case=name,verified_vectors=data['verified_vectors'],stateful=name in STATEFUL,
            pre_and_post_edge_checked=data.get('pre_and_post_edge_checked',False),summary=summary,
            assembly=functions,normalization=build['signature']['normalization'],
            generated_cpp_bytes=sum(p.stat().st_size for p in (case/'model').glob('grhsim*.cpp')),
            model_path=str(case/'model'),rtl_path=str(case/'rtl/Pattern.sv'),graph_path=str(case/'model/normalized.json'),
            artifact_dir=str(case),build=identity(case/'build.json'),measurement=identity(case/'measurement.json'))
        for label,path in [('raw',case/'graph.json'),('normalized',case/'model/normalized.json')]:
            graph=json.loads(path.read_text())
            results[name][label+'_op_counts']=dict(Counter(op['kind'] for g in graph['graphs'] for op in g['ops']))
    save(root/'validated_results.json',dict(schema_version=1,cases=results,total_verified=sum(r['verified_vectors'] for r in results.values())))
    keys=['case','distribution','stateful','verified_vectors','generated_cpp_bytes','generated_ns','software_ns',
          'compute_slice_ns','slice_software_ns','kernel_delta_percent','kernel_delta_min','kernel_delta_max','eval_delta_percent','pairs']
    with (root/'results.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader()
        for name,r in results.items():
            for s in r['summary']:w.writerow(dict(r,**s))
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    args=parser.parse_args();r=summarize(args.root);print('VALIDATED',len(r),'cases',sum(x['verified_vectors'] for x in r.values()),'vectors/cycles')
