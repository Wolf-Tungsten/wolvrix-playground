#!/usr/bin/env python3
"""Frozen compact indexed-snapshot experiment on the shared-arm XS/CV32 models."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, identity, run, save, sample, signature, summarize_named
from cv32e40p_event_regions_compare import check as cv_check, source_inventory as cv_inventory
from cv32e40p_repair_compare import GRAPH, HARNESS, emit_environment, same_sources, compile_model, native_library, verify
from grhsim_single_baseline import clean_environment
from xiangshan_cv32_compare import HISTORICAL, XS, verify_identity
from xiangshan_packed_storage_compare import check_harness_source, check_model, source_inventory, source_shape
from xiangshan_cv32_ablation_measure import measurement_lock

XS_BASE = ROOT / 'build/xs/shared-arm-20261117-v1'
CV_BASE = ROOT / 'build/cv32e40p/shared-arm-v1'
BASE = 'grhsim_shared_arm'
CANDIDATE = 'grhsim_indexed_snapshot'
OPTION = 'WOLVRIX_GRHSIM_INDEXED_CONCAT_SNAPSHOT_ARRAY'


def read(path):
    return json.loads(path.read_text())


def contract(folder):
    digest=hashlib.sha256(); sites=[]; old_views=0
    for path in sorted(folder.glob('*_sched_*.cpp')):
        text=path.read_text()
        lines=[line for line in text.splitlines() if re.search(
            r'// (?:Supernode |op |Covered state view:|Composed state expression:|Conditional mux|Shared equality)|'
            r'const bool grhsim_changed_|supernode_active_(?:curr|next)_\[',line)]
        digest.update((path.name+'\n'+'\n'.join(lines)).encode())
        old_views+=text.count('// Indexed concat:')
        for match in re.finditer(r'Indexed concat snapshot array: value=(\d+) lane_width=(\d+) lanes=(\d+)',text):
            value,width,lanes=map(int,match.groups())
            sites.append(dict(file=path.name,line=text.count('\n',0,match.start())+1,value=value,lane_width=width,lanes=lanes,
                              snapshot_bytes=lanes*(1 if width<=8 else 2 if width<=16 else 4 if width<=32 else 8)))
    return dict(schedule_activation_hash=digest.hexdigest(),sites=sites,legacy_views=old_views,
                views=old_views+len(sites),snapshot_bytes=sum(x['snapshot_bytes'] for x in sites))


def check_structure(before,after):
    old,new=contract(before),contract(after)
    assert old['schedule_activation_hash']==new['schedule_activation_hash']
    assert old['views']==new['views'] and not old['sites'] and new['sites']
    for path in before.glob('*.hpp'):
        text=(after/path.name).read_text()
        # Only the enabled runtime helper may be added to a header.
        begin=text.find('template <std::size_t LaneWidth, std::size_t SliceWidth, typename Index, typename Lane, std::size_t N>')
        if begin>=0:
            end=text.index('template <typename T>\ninline std::size_t grhsim_index_in_range_words',begin)
            text=text[:begin]+text[end:]
        assert text==path.read_text(),path.name
    evalfile=next(before.glob('*_eval.cpp'))
    assert evalfile.read_bytes()==(after/evalfile.name).read_bytes()
    return dict(off_equal_latest=True,before=old,candidate=new)


def policy():
    return dict(pairs=3,cpu=96,numa=1,aslr=False,threads=1,variants=['full','candidate'],cycles=100000,
        verification_seeds=[0,1],feedback=False,
        rule='Existing indexed-concat view only. Uniform 1..64-bit fields; nonconstant operands must already be '
             'named local snapshots, not persistent fields, ports or covered state views. Store reversed native '
             'lanes at the concat snapshot and read only the requested slice. Array bytes <= unique local captures * sizeof(void*). '
             'Keep old width, high-index, truncation, source-order and snapshot proofs.',
        baseline='Exact TNO0048 shared-arm candidates for both designs. Only indexed_concat_snapshot_array is new; aligned_array_slice stays off.',
        order='Three fixed AB/BA pairs, no retries, dropped samples, threshold tuning or extra combinations.',
        diagnostics='Offline C++/ELF and CV32 behavior counts. No additional PMU sampling in this experiment.')


def prepare_xs(out, tools):
    check_harness_source(); check_model(XS_BASE / 'candidate')
    out.mkdir(parents=True, exist_ok=False)
    native = out / 'native'; snap = out / 'snapshot'; native.mkdir(); snap.mkdir()
    shutil.copytree(ROOT / 'wolvrix/include', native / 'include')
    shutil.copytree(ROOT / 'wolvrix/lib', snap / 'lib')
    shutil.copy2(native_library(tools), native / 'libwolvrix-lib.so')
    for path in (ROOT / 'scripts/xiangshan_cv32_emit.cpp', Path(__file__).resolve()):
        shutil.copy2(path, snap / path.name)
    (snap / 'wolvrix.patch').write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    (out / 'full').symlink_to(XS_BASE / 'candidate', target_is_directory=True)
    candidate = out / 'candidate'; candidate.mkdir()
    shutil.copytree(out / 'full/chisel-home', candidate / 'chisel-home')
    config = read(out / 'full/configuration.json')
    config.update(variant='indexed_snapshot', indexed_concat_snapshot_array=True,
                  native_library=identity(native / 'libwolvrix-lib.so'))
    save(candidate / 'configuration.json', config); save(out / 'policy.json', policy())
    paths = [p for folder in (native, snap) for p in sorted(folder.rglob('*')) if p.is_file()]
    paths += [out / 'policy.json', candidate / 'configuration.json', HISTORICAL / 'pre_reg_to_mem.json']
    paths += [ROOT / 'scripts' / name for name in ('indexed_snapshot_compare.py', 'xiangshan_cv32_ablation_measure.py',
              'grhsim_single_baseline.py', 'grhsim_single_compare.py', 'grhsim_difftrace.py', 'grhsim_numa.py')]
    save(out / 'inputs.json', [identity(p) for p in paths])


def check_inputs(out):
    for record in read(out / 'inputs.json'): verify_identity(record)


def check_xs(out):
    check_inputs(out)
    for record in read(out / 'build.json')['files']: verify_identity(record)
    for name in ('full', 'candidate'): check_model(out / name)


def build_xs(out):
    assert platform.node().startswith('node030'); check_inputs(out)
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    native = out / 'native'; target = out / 'candidate'
    env = clean_environment(); env.update(NOOP_HOME=str(XS), LC_ALL='C', LD_LIBRARY_PATH=str(native),
        WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0', WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
    command = [arg.replace(str(XS_BASE / 'native'), str(native)).replace(str(XS_BASE / 'snapshot'), str(out / 'snapshot'))
               for arg in read(XS_BASE / 'logs/native.command.json')['argv']]
    command[-1] = str(native / 'emit')
    run(command, out / 'logs/native.log', env=env)
    def emit(flag):
        local = env.copy(); local[OPTION] = str(flag)
        folder = target / 'model' if flag else out / 'off-source'
        run([native / 'emit', HISTORICAL / 'pre_reg_to_mem.json', folder], out / 'logs' / f'emit-{flag}.log', env=local)
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(emit, (0, 1)))
    assert source_shape(source_inventory(out / 'off-source')) == source_shape(read(out / 'full/model-sources.json')), 'off source drift'
    save(out / 'structure.json', check_structure(out / 'full/model', target / 'model'))
    save(target / 'model-sources.json', source_inventory(target / 'model'))
    command = [arg.replace(str(XS_BASE / 'candidate'), str(target))
               for arg in read(XS_BASE / 'candidate/logs/compile.command.json')['argv']]
    run(command, target / 'logs/compile.log', env=env)
    save(target / 'binary.json', identity(target / 'emu/grhsim-compile/emu'))
    files = source_inventory(out / 'off-source') + read(target / 'model-sources.json')
    files += [identity(out / 'structure.json'), identity(target / 'model-sources.json'), identity(target / 'binary.json'),
              read(target / 'binary.json'), identity(native / 'emit')]
    save(out / 'build.json', dict(inputs=identity(out / 'inputs.json'), files=files,
                                binaries={n: read(out / n / 'binary.json') for n in ('full', 'candidate')}))
    check_xs(out); print('XS candidate frozen', flush=True)


def build_cv(out, tools):
    assert platform.node().startswith('node030'); original = cv_check(CV_BASE)
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'): (out / name).symlink_to(CV_BASE / name)
    native = out / 'native-frozen'; native.mkdir(); snap = out / 'source-snapshot'; snap.mkdir()
    for path in (tools / 'cv32e40p_emit', native_library(tools)): shutil.copy2(path, native / path.name)
    for path in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'testcase/cv32e40p-bench/emit.cpp', Path(__file__).resolve()):
        shutil.copy2(path, snap / path.name)
    save(out / 'hypothesis.json', policy())
    env = emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1', CV32_SHARED_EVENT_REGIONS_CONNECTED='1',
        WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1', WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1', WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1', WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1',
        WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0', WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1')
    inventories = []
    for name, flag in ((BASE, '0'), (CANDIDATE, '1')):
        env[OPTION] = flag
        run([native / 'cv32e40p_emit', GRAPH, out / name, 'off'], out / 'logs' / (name + '-emit.log'), env=env)
        assert identity(out / name / 'normalized.json')['sha256'] == identity(CV_BASE / BASE / 'normalized.json')['sha256']
        inventories += list(cv_inventory(out / name).values())
    assert same_sources(out / BASE, CV_BASE / BASE), 'CV32 off source drift'
    save(out / 'structure.json', check_structure(out / BASE, out / CANDIDATE))
    compile_model(out / CANDIDATE, out, CANDIDATE, 12)
    (out / 'verilator').mkdir()
    for name in (BASE, 'verilator'): shutil.copy2(original['binaries'][name]['path'], out / name / 'emu')
    names = [BASE, CANDIDATE, 'verilator']
    frozen = [identity(p) for p in (CV_BASE / 'build.json', GRAPH, HARNESS, CXX, out / 'hypothesis.json',
              out / 'structure.json', out / 'verification.json', *native.iterdir(), *snap.iterdir())] + inventories
    save(out / 'build.json', dict(backends=names, candidate=CANDIDATE, comparisons=[BASE, 'verilator'], flags=CFLAGS,
        binaries={name: identity(out / name / 'emu') for name in names}, frozen_inputs=frozen))
    cv_check(out); print('CV32 candidate frozen', flush=True)


def measure_cv(out):
    with measurement_lock():
        manifest = cv_check(out); functional = read(out / 'functional.json')
        assert functional['status'] == 'pass' and functional['build'] == identity(out / 'build.json')
        if (out / 'pairs.json').exists(): raise FileExistsError('measurement already started')
        names = manifest['backends']; warmups = {n: sample(out, n, 'coremark', 'warmup') for n in names}
        save(out / 'measurement-policy.json', dict(rounds=3, warmups=warmups, cpu=96, numa=1, aslr=False,
             order='forward/reverse alternating', retries=0, feedback=False))
        rows = []
        for i in range(3):
            order = names if i % 2 == 0 else names[::-1]; row = dict(pair=i, order=order)
            for name in order:
                row[name] = sample(out, name, 'coremark', f'pair{i:02d}')
                assert signature(row[name]) == signature(functional['workloads']['coremark'][name])
            rows.append(row); save(out / 'pairs.json', rows); print(f'CV32 round {i+1}/3', flush=True)
        stats = {name: summarize_named(rows, CANDIDATE, name) for name in (BASE, 'verilator')}
        save(out / 'summary.json', stats); cv_check(out)
        print(json.dumps({name: result['wall_s'] for name, result in stats.items()}, indent=2), flush=True)


def measure_xs(out):
    import xiangshan_cv32_ablation_measure as protocol
    check_xs(out); protocol.VARIANTS = ('full', 'candidate'); protocol.ROUNDS = 3
    result = protocol.measure(out, out / 'measurement', XS / 'ready-to-run/coremark-2-iteration.bin',
                              XS / 'ready-to-run/riscv64-nemu-interpreter-so')
    check_xs(out); save(out / 'report.json', dict(comparisons=result['comparisons'], build=identity(out / 'build.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare-xs', 'build-xs', 'check-xs', 'measure-xs', 'build-cv', 'verify-cv', 'measure-cv'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'prepare-xs': prepare_xs(out, args.tools.resolve())
    elif args.stage == 'build-cv': build_cv(out, args.tools.resolve())
    elif args.stage == 'verify-cv':
        with measurement_lock(): verify(out)
    else: {'build-xs': build_xs, 'check-xs': check_xs, 'measure-xs': measure_xs, 'measure-cv': measure_cv}[args.stage](out)
