#!/usr/bin/env python3
"""Collect structural evidence and available functional/performance artifacts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from grhsim_single_baseline import identity, save


def type_layout(name):
    scalar = {'bool': 1, 'std::uint8_t': 1, 'std::uint16_t': 2,
              'std::uint32_t': 4, 'std::uint64_t': 8}
    if name in scalar:
        return scalar[name], scalar[name]
    match = re.fullmatch(r'std::array<(.+), (\d+)>', name)
    if not match:
        raise ValueError('unrecognized emitted state type: ' + name)
    size, align = type_layout(match[1])
    return max(1, size * int(match[2])), align


def structure(folder):
    model=folder/'model'; header=(model/'grhsim_SimTop.hpp').read_text()
    schedule=json.loads((model/'activity_schedule_supernode_stats.json').read_text())
    log=(folder/'logs/emit.log').read_text()
    last=lambda pattern: int(re.findall(pattern,log)[-1]) if re.findall(pattern,log) else None
    body=header.split('struct state_logic_storage_t {',1)[1].split('};',1)[0]
    fields=re.findall(r'^\s+(.+?)\s+\w+;',body,re.M)
    offset=0; max_align=1
    for name in fields:
        size,align=type_layout(name);max_align=max(max_align,align)
        offset=(offset+align-1)//align*align+size
    state_bytes=(offset+max_align-1)//max_align*max_align
    memories=re.findall(r'^\s+(std::array<.+>)\s+(state_(?:mem|reg_to_mem)_\w+)\s*=',header,re.M)
    return dict(binary=identity(folder/'emu/grhsim-compile/emu'),
        cpp_files=len(list(model.glob('*.cpp'))),cpp_bytes=sum(p.stat().st_size for p in model.glob('*.cpp')),
        register_state_slots=len(fields),register_state_types=dict(Counter(fields)),
        register_state_storage_bytes=state_bytes,
        memory_objects=len(memories),memory_payload_bytes=sum(type_layout(t)[0] for t,n in memories),
        memory_origin=dict(Counter('reg-to-mem' if n.startswith('state_reg_to_mem_') else 'memory' for t,n in memories)),
        event_edge_slots=int(re.search(r'grhsim_event_edge_kind, (\d+)> event_edge_storage_',header)[1]),
        graph_ops=last(r'graph_ops=(\d+)'),graph_values=last(r'graph_values=(\d+)'),
        source_state_read_sets=last(r'state_read_sets=(\d+)'),
        state_shadow_count=int(re.search(r'kStateShadowCount = (\d+)',header)[1]),
        commit_write_count=int(re.search(r'kWriteCount = (\d+)',header)[1]),
        schedule=schedule,emitter=json.loads((model/'grhsim_emit_stats.json').read_text()),
        model_manifest=json.loads((model/'simulation_model_manifest.json').read_text()),
        caveat='Storage counts/types come from emitted C++; bytes use x86-64 scalar/std::array layout. Shadow/write counts are exported constants. No runtime update-count instrumentation.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    args=p.parse_args();root=args.study.resolve()
    result=dict(variants={v:structure(root/v) for v in 'AB'})
    for name in ('rtl-structure','pre-grh-counts','source-audit','comparison/summary','control-aa/summary'):
        path=root/(name+'.json')
        if path.exists():result[name]=json.loads(path.read_text())
    save(root/'review.json',result)

if __name__=='__main__':main()
