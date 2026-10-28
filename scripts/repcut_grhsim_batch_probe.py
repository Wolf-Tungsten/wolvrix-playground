#!/usr/bin/env python3
"""Frozen-cohort batch attribution using an unchanged compiled compute archive.

This diagnoses longest eval *bodies*, not last completion or ordinary walltime.
Only dispatcher and wrapper objects change. Per-part runs avoid concurrently
timing batches on several lanes. Entry activity masks are not group-entry
counts: an earlier group may activate another group in the same batch.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys

import repcut_cycle_trace as archive
import repcut_cost_model_compare as common
import repcut_formal_zero_thp_compare as thp
import repcut_grhsim_critical_profile as critical
from repcut_grhsim_plan_gate import identity, save

ROOT = Path(__file__).resolve().parents[1]
HEADER = Path(__file__).with_suffix('.hpp')
RETRY = ROOT / 'build/xs_native_verilator_scaling_20261012/setup_tools/collapse_retry.so'


def traces(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['status'] != 'pass':
        raise ValueError('incomplete trace campaign')
    # Separate wrapper builds may differ in __FILE__. Their model archive
    # provenance is checked separately against the exact production source.
    paths = [directory / (r['name'] + '.trace.bin') for r in manifest['runs'] if r['pair']]
    if len(paths) < 2:
        raise ValueError('need independently repeated reference traces')
    return paths


def prepare(args):
    import numpy as np
    source, out = args.source, args.output
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'selection.json').exists():
        raise ValueError('refusing to replace a completed probe preparation')
    paths = traces(args.trace / 'runs')
    source_binary = identity(source / 'harness/grhsim-compile/emu')
    build = json.loads((args.trace / 'build.json').read_text())
    for record in build.values():
        if record['source_before']['harness/grhsim-compile/emu']['sha256'] != source_binary['sha256']:
            raise ValueError('reference trace is from a different production binary')
    profile = critical.summarize(paths)
    save(out / 'critical_profile.json', profile)
    parts = [r['part'] for r in sorted(profile['all']['eval']['parts'],
             key=lambda r: (-r['exclusive_margin_us'], r['part']))[:args.part_limit]]
    if len(parts) < 2:
        raise ValueError('select at least two lanes for attribution')
    flags, winners = None, []
    for path in paths:
        raw = path.read_bytes()
        magic, version, count, k, fields = struct.unpack_from('<8s4I', raw)
        if (magic, version, fields) != (b'GRHCYC01', 1, 3):
            raise ValueError('invalid trace')
        values = np.frombuffer(raw, dtype='<u4', offset=24)
        current = values[:count * 4].reshape(count, 4)[:, 0]
        if flags is not None and not np.array_equal(flags, current):
            raise ValueError('reference steps differ')
        flags = current.copy()
        lanes = values[count * 4:].reshape(k, count, fields)
        winners.append(lanes[:, :, 1].argmax(axis=0))
    labels = np.zeros((k, count), dtype='u1')
    cohorts = []
    votes = np.asarray(winners)
    threshold = len(paths) // 2 + 1
    for p in parts:
        hits = (votes == p).sum(axis=0)
        for clock in (0, 1):
            for scope, condition in ((1, hits >= threshold), (2, hits == 0)):
                available = np.flatnonzero(condition & (flags == clock))
                if not len(available):
                    raise ValueError(f'empty cohort: {p}, {clock}, {scope}')
                selected = available[np.linspace(0, len(available) - 1,
                    min(args.per_cohort, len(available)), dtype=int)]
                labels[p, selected] = scope
                cohorts.append(dict(part=p, clock=clock, scope=scope,
                                    available=len(available), selected=len(selected)))
    with (out / 'labels.bin').open('wb') as stream:
        stream.write(struct.pack('<8s3I', b'GRHBAT01', 1, count, k))
        flags.astype('u1').tofile(stream)
        labels.tofile(stream)
    package = source / 'package'
    dest = out / 'sources'
    dest.mkdir(exist_ok=True)
    sites, inputs, batch_max = [], {}, 0
    for p in parts:
        path = package / f'grhsim_Gpart_{p}_model_eval.cpp'
        text = path.read_text()
        needle = '        ++fixed_point_round_count;'
        if text.count(needle) != 1:
            raise ValueError('unexpected dispatcher rounds')
        text = text.replace(needle, needle + '\n        repcut_batch_probe::round(fixed_point_round_count);')
        def instrument(match):
            nonlocal batch_max
            b = int(match[1]); batch_max = max(batch_max, b)
            batch_file = package / f'grhsim_Gpart_{p}_model_sched_{b}.cpp'
            cpp = batch_file.read_text()
            masks = re.findall(r'constexpr std::uint8_t dispatchMask = UINT8_C\((\d+)\);', cpp)
            words = re.findall(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\] & dispatchMask\);', cpp)
            if len(masks) != 1 or len(words) != 1:
                raise ValueError(f'unsupported multiple activity words: {batch_file}')
            groups = re.findall(r'// Supernode (\d+):[^\n]*\n\s*if \((?:unlikely|GRHSIM_LIKELY)\(activeWordFlags & UINT8_C\((\d+)\)\)\)', cpp)
            if not groups or len(groups) != int(masks[0]).bit_count() or len(groups) != len(re.findall(r'// Supernode \d+:', cpp)):
                raise ValueError(f'group-mask mismatch: {batch_file.name} groups={groups} mask={masks}')
            sites.append(dict(part=p, batch=b, mask=int(masks[0]), word=int(words[0]),
                              groups=[dict(group=int(g), bit=int(bit).bit_length()-1) for g, bit in groups],
                              source=identity(batch_file)))
            call = f'this->eval_compute_batch_{b}();'
            return (f'        if (repcut_batch_probe::selected) {{\n'
                    f'            repcut_batch_probe::measure({b}, static_cast<std::uint8_t>(supernode_active_curr_[{words[0]}u] & UINT8_C({masks[0]})), UINT8_C({masks[0]}), [&] {{ {call} }});\n'
                    f'        }} else {{ {call} }}')
        text, calls = re.subn(r'        this->eval_compute_batch_(\d+)\(\);', instrument, text)
        if not calls:
            raise ValueError('no compute calls')
        (dest / path.name).write_text('#include "repcut_grhsim_batch_probe.hpp"\n' + text)
        inputs[path.name] = identity(path)
    path = package / 'wolvi_repcut_grhsim_sim_eval_0.cpp'
    text = path.read_text()
    for p in parts:
        pattern = rf'(void WolviRepCutGrhSimSim::run_eval_part_{p}_\([^\n]+\) \{{.*?\n\}})'
        def wrap(match):
            body = match[0]
            begin = '  const auto evalBegin = WolviClock::now();'
            end = '  const auto evalEnd = WolviClock::now();'
            if body.count(begin) != 1 or body.count(end) != 1:
                raise ValueError('unexpected wrapper')
            return body.replace(begin, f'  repcut_batch_probe::begin({p}, step_count_, top_in_clock_, top_in_reset_);\n' + begin).replace(
                end, end + '\n  repcut_batch_probe::end(elapsed_ns_(evalBegin, evalEnd));')
        text, n = re.subn(pattern, wrap, text, flags=re.S)
        if n != 1: raise ValueError('wrapper missing')
    (dest / path.name).write_text('#include "repcut_grhsim_batch_probe.hpp"\n' + text)
    inputs[path.name] = identity(path)
    (dest / 'batch_probe_sizes.hpp').write_text('#pragma once\nnamespace repcut_batch_probe {\n'
        f'inline constexpr unsigned partition_count = {k}, batch_capacity = {batch_max + 1};\n}}\n')
    shutil.copy2(HEADER, dest / HEADER.name)
    save(out / 'selection.json', dict(status='pass', diagnostic_only=True, parts=parts,
        source=str(source), binary=source_binary, archive=identity(package / 'libgrhsim_SimTop.a'),
        emitter=identity(source / 'emit.json'), reference_traces=[identity(p) for p in paths],
        stable_winner_min_votes=threshold, repetitions=len(paths), cohorts=cohorts,
        labels=identity(out / 'labels.bin'), source_inputs=inputs, sites=sites,
        scope='1: stable max eval body; 2: never max in discovery; equal clock levels, evenly sampled steps; diagnostic only'))
    print('PREPARE PASS', parts, cohorts, flush=True)


def build(args):
    if socket.gethostname().split('.')[0] != 'node030' or not os.sched_getaffinity(0) <= set(range(96, 128)):
        raise ValueError('build must use reserved node030 CPUs')
    out = args.output
    info = json.loads((out / 'selection.json').read_text())
    source = Path(info['source']) / 'package'
    def one(name):
        cpp, obj = out / 'sources' / name, out / (name[:-4] + '.o')
        command = [str(archive.LLVM / 'clang++'), '-std=c++20', '-O3', '-march=native', '-pthread',
                   '-I', str(source), '-I', str(cpp.parent), '-c', str(cpp), '-o', str(obj)]
        if info.get('counts_only'):
            command.append('-DREPCUT_GROUP_COUNTS_ONLY=1')
        with obj.with_suffix('.log').open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        archive.align_object(obj)
        return obj
    with ThreadPoolExecutor(max_workers=min(24, len(info['source_inputs']))) as pool:
        objects = list(pool.map(one, info['source_inputs']))
    original = source / 'libgrhsim_SimTop.a'
    target = out / original.name
    if identity(original) != info['archive']:
        raise ValueError('archive changed')
    shutil.copy2(original, target)
    subprocess.run([str(archive.LLVM / 'llvm-ar'), 'rcs', str(target), *map(str, objects)], check=True)
    old, new = archive.archive_hashes(original), archive.archive_hashes(target)
    changed = [n for n in old if old[n] != new[n]]
    if list(old) != list(new) or set(changed) != {o.name for o in objects}:
        raise ValueError('unexpected archive changes')
    binary = archive.link_harness(out, source, target)
    (out / 'emu').symlink_to(binary)
    alignment = thp.audit_compute_alignment(binary, 64)
    save(out / 'build.json', dict(status='pass', diagnostic_only=True, binary=identity(binary),
        unchanged_members=len(old)-len(changed), changed_members=changed, alignment=alignment,
        source_archive=info['archive'], source_binary=info['binary'], source_emitter=info['emitter']))
    print('BUILD PASS',len(changed),'changed objects;',len(old)-len(changed),'unchanged',flush=True)


def run(args):
    out = args.output
    info = json.loads((out / 'selection.json').read_text())
    proof = json.loads((out / 'build.json').read_text())
    if identity(out / 'emu')['sha256'] != proof['binary']['sha256']:
        raise ValueError('probe binary changed')
    original = common.command_for
    run_parts = args.run_parts or info['parts'][:2]
    if len(run_parts) != 2 or any(p not in info['parts'] for p in run_parts):
        raise ValueError('run parts must be two prepared lanes')
    def command_for(spec, binaries, directory):
        binary = str(binaries[spec['variant']])
        command = thp.with_codepage(original(spec, binaries, directory), binary, 'preferred', RETRY)
        index = command.index(binary)
        part = run_parts[common.VARIANTS.index(spec['variant'])]
        command[index:index] = [f'REPCUT_PROFILE_PART={part}',
            f'REPCUT_BATCH_LABELS={out / "labels.bin"}',
            f'REPCUT_BATCH_COUNTS={directory / (spec["name"] + ".batches.csv")}',
            f'REPCUT_GROUP_COUNTS={directory / (spec["name"] + ".groups.csv")}',
            f'REPCUT_BATCH_STEPS={directory / (spec["name"] + ".steps.csv")}']
        return command
    common.command_for = command_for
    run_dir = out / args.run_name
    sys.argv = [sys.argv[0], '--pairs', str(args.pairs), '--cycles', '100000', '--output', str(run_dir)]
    for variant in common.VARIANTS:
        sys.argv += [f'--{variant}-binary', str(out / 'emu'), f'--{variant}-package', str(Path(info['source']) / 'package')]
    try:
        common.main()
        thp.audit_thp(run_dir)
    finally:
        common.command_for = original
    for name in ('manifest.json', 'summary.json'):
        path = run_dir / name
        record = json.loads(path.read_text())
        record.update(diagnostic_only=True, timing_use='batch attribution only; variants profile different lanes of the same ELF')
        save(path, record)


def prepare_counts(args):
    reference = args.reference_probe
    if reference is None: raise ValueError('--reference-probe required')
    info = json.loads((reference / 'selection.json').read_text())
    out = args.output
    out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(reference / 'sources', out / 'sources')
    shutil.copy2(HEADER, out / 'sources' / HEADER.name)
    shutil.copy2(reference / 'labels.bin',out / 'labels.bin')
    max_group=max(g['group'] for r in info['sites'] for g in r['groups'])
    config=out / 'sources/batch_probe_sizes.hpp'
    config.write_text(config.read_text()+'\nnamespace repcut_batch_probe {\n'
                      f'inline constexpr unsigned group_capacity = {max_group+1};\n}}\n')
    inputs=dict(info['source_inputs'])
    for site in info['sites']:
        path=Path(site['source']['path']);text=path.read_text()
        pattern=r'(// Supernode (\d+):[^\n]*\n\s*if \((?:unlikely|GRHSIM_LIKELY)\(activeWordFlags & UINT8_C\(\d+\)\)\) \{)'
        text,count=re.subn(pattern,lambda m:m[1]+f'\n        repcut_batch_probe::group({m[2]});',text)
        if count!=len(site['groups']):raise ValueError('group hook mismatch')
        (out/'sources'/path.name).write_text('#include "repcut_grhsim_batch_probe.hpp"\n'+text)
        inputs[path.name]=site['source']
    info.update(counts_only=True,source_inputs=inputs,reference_probe=identity(reference/'selection.json'),
                labels=identity(out/'labels.bin'))
    save(out/'selection.json',info)
    print('COUNTS PREPARE PASS',len(inputs),flush=True)


def report(args):
    out = args.output
    info = json.loads((out / 'selection.json').read_text())
    if info.get('counts_only'):
        raise ValueError('group-count-only probes require inventory reconciliation; their batch times are intentionally zero')
    runs = []
    for manifest_path in sorted(out.glob('runs*/manifest.json')):
        manifest = json.loads(manifest_path.read_text())
        if manifest['status'] != 'pass': raise ValueError('incomplete run')
        runs.extend((manifest_path.parent, r) for r in manifest['runs'])
    if not runs: raise ValueError('no runs')
    counters, samples = defaultdict(Counter), defaultdict(list)
    per_run = []
    for directory, run in runs:
        if not run['pair']: continue
        batch_file = directory / (run['name'] + '.batches.csv')
        step_file = directory / (run['name'] + '.steps.csv')
        counts = list(csv.DictReader(batch_file.open()))
        steps = list(csv.DictReader(step_file.open()))
        selected = [a for a in run['command'] if a.startswith('REPCUT_PROFILE_PART=')]
        if len(selected) != 1: raise ValueError('ambiguous profiled lane')
        part = int(selected[0].split('=')[1])
        expected = sum(r['selected'] for r in info['cohorts'] if r['part'] == part)
        if len(steps) != expected or any(int(r['part']) != part for r in steps + counts):
            raise ValueError('sample count/part mismatch')
        if sum(int(r['ns']) for r in counts) != sum(int(r['active_ns']) for r in steps):
            raise ValueError('batch/sample time reconciliation')
        for r in steps:
            samples[part, int(r['clock']), int(r['scope'])].append({k:int(v) for k,v in r.items()})
        for r in counts:
            key = tuple(int(r[k]) for k in ('part','clock','scope','wave','batch'))
            counters[key].update({k:int(v) for k,v in r.items() if k not in ('part','clock','scope','wave','batch')})
        per_run.append(dict(run=directory.name+'/'+run['name'], part=part, batches=identity(batch_file), samples=identity(step_file)))
    results=[]
    for (part,clock,scope), steps in sorted(samples.items()):
        batches=defaultdict(Counter); by_wave=Counter()
        for (p,c,s,w,b), values in counters.items():
            if (p,c,s)!=(part,clock,scope): continue
            batches[b].update(values); by_wave[w]+=values['ns']
        total=sum(r['active_ns'] for r in steps)
        rows=[dict(batch=b, active_ns=v['ns'], active_share_pct=100*v['ns']/total,
                   active_us_per_step=v['ns']/len(steps)/1000,
                   active_calls_per_step=v['active']/len(steps), calls_per_step=v['calls']/len(steps),
                   all_on_fraction=v['all_on']/v['active'] if v['active'] else 0,
                   entry_bits_per_step=[v[f'bit{i}']/len(steps) for i in range(8)]) for b,v in batches.items()]
        rows.sort(key=lambda r:-r['active_ns'])
        results.append(dict(part=part,clock=clock,scope=scope,samples=len(steps),
            instrumented_eval_us=sum(r['eval_ns'] for r in steps)/len(steps)/1000,
            active_us=total/len(steps)/1000,rounds=dict(Counter(r['rounds'] for r in steps)),
            wave_active_us={str(w):v/len(steps)/1000 for w,v in sorted(by_wave.items())},
            top1_pct=rows[0]['active_share_pct'],top10_pct=sum(r['active_share_pct'] for r in rows[:10]),
            batches=rows))
    result=dict(status='pass',diagnostic_only=True,scope=info['scope'],parts=info['parts'],
                samples=results,inputs=per_run,selection=identity(out/'selection.json'),
                caveats=['Active-call timing includes probe perturbation; not ordinary walltime.',
                         'Entry masks omit in-batch activation; do not treat them as actual group-entry counts.',
                         'A batch contains scheduling groups, not necessarily one ASC.'])
    save(out/'report.json',result)
    for row in results:
        print(json.dumps({k:v for k,v in row.items() if k!='batches'}),flush=True)
        print('TOP',row['part'],[(r['batch'],round(r['active_us_per_step'],3),round(r['active_share_pct'],1)) for r in row['batches'][:8]],flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','prepare_counts','build','run','report'))
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--part-limit',type=int,default=2)
    parser.add_argument('--per-cohort',type=int,default=512)
    parser.add_argument('--pairs',type=int,default=2)
    parser.add_argument('--run-parts',type=int,nargs=2)
    parser.add_argument('--run-name',default='runs')
    parser.add_argument('--reference-probe',type=Path)
    args=parser.parse_args()
    globals()[args.action](args)
