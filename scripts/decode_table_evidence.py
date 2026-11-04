#!/usr/bin/env python3
"""Join captured tables to flattened GRH operations and generated C++ helpers."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

from grhsim_single_baseline import save


def symbol(payload):
    value = 14695981039346656037
    for byte in payload.encode():
        value = ((value ^ byte)*1099511628211) & ((1 << 64)-1)
    return 'grhsim_decode_'+format(value, 'x')


def collect(build):
    build = Path(build).resolve()
    coverage = json.loads((build/'coverage.json').read_text())
    manifest = json.loads((build/'B/chisel-home/build/simulation_primitives.json').read_text())
    tables = {t['table_id']:dict(t, cpp_symbol=symbol(manifest['decode_tables'][t['table_id']]),
        grh=[], cpp=[], rtl=[]) for t in coverage['tables']}
    symbols = {r['cpp_symbol']:r for r in tables.values()}
    for variant in ('A','B'):
        path = build/variant/'pre_reg_to_mem.json';count = 0
        with path.open() as stream:
            for line_number, line in enumerate(stream,1):
                if '"kind": "kDecodeTable"' not in line:
                    continue
                op = json.loads(line.strip().removesuffix(','))
                payload = op['attrs']['decode.table']['v']
                key = hashlib.sha256(payload.encode()).hexdigest()
                if variant == 'A':
                    raise ValueError('decode intrinsic in baseline GRH')
                if key not in tables or len(op['in']) != 1 or len(op['out']) != 1:
                    raise ValueError('unknown table or impure shape')
                count += 1
                tables[key]['grh'].append(dict(file=str(path),line=line_number,symbol=op['sym'],
                    inputs=op['in'],outputs=op['out'],rtl=op.get('loc')))
        print(variant,'flattened decode operations',count,flush=True)
    for path in sorted((build/'B/model').glob('*')):
        if path.suffix not in ('.cpp','.hpp'):
            continue
        with path.open() as stream:
            for line_number, line in enumerate(stream,1):
                if 'grhsim_decode_' not in line:
                    continue
                stats = re.search(r'// decode-stats (\w+) dense=(\d+) nodes=(\d+) depth=(\d+) max_leaf=(\d+) storage=(\d+)',line)
                if stats:
                    s=stats.groups();symbols[s[0]]['codegen']=dict(zip(['dense','nodes','depth','max_leaf','storage_bytes'],map(int,s[1:])))
                for name in set(re.findall(r'\b(grhsim_decode_[0-9a-f]+)\(',line)):
                    symbols[name]['cpp'].append(dict(file=str(path),line=line_number,kind='definition' if path.suffix=='.hpp' else 'call'))
    for table in tables.values():
        seen = set()
        for op in table['grh']:
            loc=op['rtl']
            if loc:
                token=(loc['file'],loc['line'],loc.get('col',0))
                if token not in seen:
                    seen.add(token);table['rtl'].append(loc)
        # DCE may remove or fold instances; retain zeroes, do not force coverage counts to match.
        table['flat_operation_count']=len(table['grh'])
        table['cpp_call_count']=sum(x['kind']=='call' for x in table['cpp'])
    save(build/'source_chain.json',list(tables.values()))
    with (build/'source_chain.csv').open('w') as stream:
        w=csv.writer(stream);w.writerow(['table_id','input_width','output_width','rows','elaborated_instances','flat_ops','cpp_calls','cpp_symbol','scala_sites'])
        for t in tables.values():
            w.writerow([t['table_id'],t['input_width'],t['output_width'],t['rows'],t['instances'],t['flat_operation_count'],t['cpp_call_count'],t['cpp_symbol'],json.dumps(t['sites'],ensure_ascii=False)])
    return tables


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True)
    collect(p.parse_args().build)
