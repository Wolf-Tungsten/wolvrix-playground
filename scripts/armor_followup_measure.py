"""Compare each frozen backend against A in eight alternating three-model rounds."""
import argparse
import platform
import re
import resource
import time
from pathlib import Path

from armor_followup_compare import ARCHIVE, BASE_CV, BASE_XS, OLD, OUT
from armor_mask_layout_measure import FIRMWARE, LOCK
from cv32e40p_compare import identity, sample, save, signature, summarize_named
from cv32e40p_event_region_counts import main as count_regions
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import Baseline
import xiangshan_cv32_ablation_measure as xs_protocol
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify

VARIANTS = ('full','commit','factor')
ORDERS = [list(VARIANTS if i % 2 == 0 else VARIANTS[::-1]) for i in range(8)]
VARIANT_KEYS = {'commit':'C', 'factor':'F'}
CV_ARCHIVE = BASE_CV.parent


def cross_design_identity(design):
    expected = read(OUT/'policy.json')['baseline'][design]
    verify(expected)
    if not read(OUT/'A'/design/'sources.json')['unchanged']:
        raise ValueError(f'{design} off replay drifted')
    result = {'full':expected}
    for name, code in VARIANT_KEYS.items():
        binary = read(OUT/code/design/'binary.json')
        verify(binary)
        result[name] = binary
    return result


def count_merged_notifications(probes, file_name, source):
    """One saved OR for each additional changed member with the same reader byte."""
    marker = '// Same-reader scalar commit group:'
    if marker not in source:
        return source
    original = (BASE_CV / file_name).read_text()
    op = re.compile(r'// op (\S+) \[kRegisterWritePort\]')
    old = list(op.finditer(original))
    by_op = {m[1]: original[m.end():old[i+1].start() if i+1<len(old) else len(original)] for i,m in enumerate(old)}
    groups = re.compile(r'^(?P<indent> *)// Same-reader scalar commit group: (\d+) writes\.\n(?P=indent)\{\n(.*?)^(?P=indent)\}', re.M | re.S)

    def literal_ors(body):
        lines = [line.strip() for line in body.splitlines() if re.match(r'\s*supernode_active_curr_\[.*?\] \|=',line)]
        if any(not re.fullmatch(r'supernode_active_curr_\[\d+u\] \|= UINT8_C\(\d+\);',line) for line in lines):
            raise ValueError('unhandled activation form in CV32 commit witness')
        return lines

    def observe(m):
        members = op.findall(m[3])
        emitted = literal_ors(m[3])
        if len(members)!=int(m[2]) or any(literal_ors(by_op[x])!=emitted for x in members):
            raise ValueError('commit activation lists differ')
        if not emitted:
            return m[0]
        count = ' + '.join(f'unsigned(changed_{i})' for i in range(len(members)))
        hit = probes.hit('commit_saved_direct_ors', f'({count} - unsigned(any_changed)) * {len(emitted)}u')
        result,n = re.subn(r'(const bool any_changed = [^\n]+;)',lambda a:a[1]+'\n'+hit,m[0])
        if n!=1:raise ValueError('missing group change predicate')
        return result
    result,n = groups.subn(observe,source)
    if n!=source.count(marker):raise ValueError('incomplete same-reader group coverage')
    return result


def measure_cv():
    with measurement_lock(LOCK,wait=True):
        images = cross_design_identity('cv')
        dst = OUT/'measurement/cv'
        dst.mkdir(parents=True)
        (dst/'firmware').symlink_to(CV_ARCHIVE/'firmware',target_is_directory=True)
        (dst/'verification.json').symlink_to(CV_ARCHIVE/'verification.json')
        expected = read(dst/'verification.json')['workloads']
        for name,v in images.items():
            (dst/name).symlink_to(Path(v['path']).parent,target_is_directory=True)
        save(dst/'build.json',dict(binaries=images))
        save(dst/'measurement-policy.json',dict(rounds=8,orders=ORDERS,lock=str(LOCK),cpu=96,numa=1,aslr=False))
        functional = {}
        for workload in ('smoke','coremark'):
            workload_rows = {}
            for name in VARIANTS:
                row = sample(dst,name,workload,'verify-'+workload,trace=True)
                golden = expected[workload]['verilator']
                if signature(row)!=signature(golden) or row['trace']['sha256']!=golden['trace']['sha256'] or row['trace']['bytes']!=row['cycles']*36:
                    raise ValueError('incomplete or mismatched CV32 trace')
                workload_rows[name] = row
            functional[workload] = workload_rows
        save(dst/'functional.json',functional)
        baseline_counts = ARCHIVE/'build/cv32e40p/indexed-snapshot-counts-v3'
        if read(baseline_counts/'inputs.json')['model'] != images['full']:
            raise ValueError('baseline counter binary mismatch')
        counters = read(baseline_counts/'counts.json')
        count_checks = {}
        saved = {}
        for name in VARIANT_KEYS:
            out = dst/(name+'-diagnostic')
            count_regions(dst,out,8,detailed=True,backend=name,harness_path=ARCHIVE/'build/cv32e40p/run2/inputs/fixture/harness.cpp',
                          extra_instrument=count_merged_notifications if name=='commit' else None)
            actual = read(out/'counts.json')
            for workload,row in actual.items():
                before=counters[workload]
                comparable=dict(row['counts'])
                if name=='commit':
                    delta=comparable.pop('commit_saved_direct_ors')
                    key='direct_active_or_executions'
                    saved[workload]=dict(baseline=before['counts'][key],candidate=comparable[key],avoided=delta)
                    comparable[key]=[n+skip for n,skip in zip(comparable[key],delta)]
                if len(before['counts'])!=331 or comparable!=before['counts'] or row['trace']['sha256']!=before['trace']['sha256'] or row['cycles']!=before['cycles']:
                    raise ValueError(f'{name} {workload} region count or bus trace mismatch')
            count_checks[name] = identity(out/'counts.json')
        save(dst/'counts-check.json',dict(baseline=identity(baseline_counts/'counts.json'),variants=count_checks,per_workload=331,direct_or_reconciliation=saved))
        warm={name:sample(dst,name,'coremark','warmup') for name in VARIANTS}
        save(dst/'warmup.json',warm)
        pairs=[]
        for i,order in enumerate(ORDERS):
            row=dict(round=i,order=order)
            for name in order:row[name]=sample(dst,name,'coremark',f'round{i:02d}')
            pairs.append(row);save(dst/'rounds.json',pairs)
            print('CV32 round',i+1,flush=True)
        for binary in images.values():verify(binary)
        result={name:summarize_named(pairs,name,'full') for name in VARIANT_KEYS}
        save(dst/'summary.json',result)


def xs_manifest():
    images=cross_design_identity('xs')
    machine=read(OUT/'machine.json')
    for name,elt in images.items():
        if elt!=machine['binaries'][name]:raise ValueError(name+' machine-code identity mismatch')
    source=OUT/'xs-inputs';source.mkdir(exist_ok=True)
    for name, target in [('full',BASE_XS),*((n,OUT/k/'xs') for n,k in VARIANT_KEYS.items())]:
        if not (source/name).exists():(source/name).symlink_to(target,target_is_directory=True)
    save(source/'policy.json',dict(experiment=read(OUT/'policy.json'),orders=ORDERS))
    save(source/'inputs.json',[identity(OUT/p) for p in ('policy.json','machine.json','source-audit.json')])
    xs_protocol.VARIANTS=VARIANTS
    return xs_protocol.freeze(source,FIRMWARE/'coremark-2-iteration.bin',FIRMWARE/'riscv64-nemu-interpreter-so')


def xs_runners(dest,manifest,names):
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    result={}
    for name in names:
        model=manifest['models'][name]
        args=argparse.Namespace(output=dest/name,binary=Path(model['binary']['path']),
            image=Path(manifest['image']['path']),nemu=Path(manifest['nemu']['path']),
            compiler=Path(read(OUT/'frozen/inputs.json')['compiler']['path']).with_name('clang++'),
            cpu=96,cycles=100000,jobs=1,repeats=1,sim_primitives='none',tools_dir=None,skip_idle_check=True)
        runner=Baseline(args)
        result[name]=(runner,runner.prepare_measurement())
    return result


def verify_xs():
    reference=OLD.parent/'measurement/xs'
    manifest=xs_manifest()
    dest=OUT/'functional-xs'
    with measurement_lock(OUT.parent/'armor-post-mask-analysis-v1/node029-semantic.lock'):
        dest.mkdir()
        save(dest/'manifest.json',manifest)
        setups=xs_runners(dest,manifest,VARIANT_KEYS)
        results={}
        for label,cycles,seed in [('smoke',10000,0),('verify-s0',100000,0),('verify-s1',100000,1)]:
            old=read(reference/'full/runs'/(label+'.json'))
            assert old['binary_sha256']==manifest['models']['full']['binary']['sha256']
            for name,(runner,setup) in setups.items():
                extra=[] if label=='smoke' else ['--dump-difftrace',f'./trace_s{seed}']
                run=runner.run_sample(setup,label,cycles,seed,extra)
                assert xs_protocol.signature(run)==xs_protocol.signature(old)
                result=dict(run=run)
                if extra:
                    prior=read(reference/f'trace-candidate-s{seed}.json')
                    for chunk in prior['chunks']:verify(chunk['a'])
                    schema=manifest['models'][name]['schema']
                    comparator=xs_protocol.build_comparator(schema['path'],dest/'trace-comparator') if not (dest/'trace-comparator/compare').exists() else dest/'trace-comparator/compare'
                    trace=compare_traces(comparator,reference/f'full/runs/runtime/bin/trace_s{seed}',
                                         setup['binary'].parent/f'trace_s{seed}',dest/f'{name}-s{seed}.json')
                    trace['coverage']=[validate_trace_coverage(trace,x) for x in (old,run)]
                    assert trace['pass_'] and trace['records']==99999 and all(x['pass_'] for x in trace['coverage'])
                    save(dest/f'{name}-s{seed}.json',trace)
                    result['trace']=identity(dest/f'{name}-s{seed}.json')
                results[f'{label}-{name}']=result
                print('XS functional',label,name,flush=True)
        xs_protocol.check_frozen(manifest)
        save(dest/'verified.json',dict(status='pass',host=platform.node(),runs=results,
            baseline=manifest['models']['full']['binary'],current={n:manifest['models'][n]['binary'] for n in VARIANT_KEYS},
            scope='Released C/F compared to frozen released A, same inputs and endpoint. Diagnostic timing unused.'))


def measure_xs():
    while not (OUT/'functional-xs/verified.json').exists():
        time.sleep(10)
    manifest=xs_manifest()
    gate=read(OUT/'functional-xs/verified.json')
    if any(gate['current'][n]!=manifest['models'][n]['binary'] for n in VARIANT_KEYS):raise ValueError('functional binary identity changed')
    with measurement_lock(LOCK,wait=True):
        dest=OUT/'measurement/xs';dest.mkdir(parents=True)
        save(dest/'manifest.json',manifest)
        save(dest/'measurement-policy.json',dict(order=ORDERS,rounds=8,placement='node030 CPU96 NUMA1, single thread, ASLR off',lock=str(LOCK),
                                                functional=identity(OUT/'functional-xs/verified.json')))
        setups=xs_runners(dest,manifest,VARIANTS)
        expected=xs_protocol.signature(gate['runs']['verify-s0-commit']['run'])
        def sample_xs(name,label):
            runner,prep=setups[name]
            row=runner.run_sample(prep,label,100000,0,[])
            if xs_protocol.signature(row)!=expected:raise ValueError('unexpected timed endpoint')
            return row
        save(dest/'warmups.json',{name:sample_xs(name,'warmup') for name in VARIANTS})
        rounds=[]
        for i,order in enumerate(ORDERS):
            row=dict(round=i,order=order)
            for name in order:row[name]=sample_xs(name,f'round{i:02d}')
            rounds.append(row);save(dest/'rounds.json',rounds)
            print('XS round',i+1,'of 8',flush=True)
        xs_protocol.check_frozen(manifest)
        save(dest/'summary.json',dict(comparisons=xs_protocol.summaries(rounds),functional_signature=expected,rounds=rounds))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design',choices=('cv','xs','xs-verify'))
    args=parser.parse_args()
    expected_host='node029' if args.design=='xs-verify' else 'node030'
    if not platform.node().startswith(expected_host):parser.error('required host '+expected_host)
    while True:
        try:
            {'cv':measure_cv,'xs':measure_xs,'xs-verify':verify_xs}[args.design]()
            break
        except RuntimeError as exc:
            if not str(exc).startswith('CPU96 measurement lock is held:'):raise
            print('Waiting for the shared measurement lock.',flush=True)
            time.sleep(30)
