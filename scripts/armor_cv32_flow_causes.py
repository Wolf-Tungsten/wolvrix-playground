"""Replay the two TNO0018 endpoints and isolate CV32 graph, scheduling and emission choices."""
import argparse
import filecmp
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from armor_cv32_xs_defaults import CXX, FLAGS, FROZEN, LOCK, OUT as PREV, ROOT, RUN2, TOOLS
from cv32e40p_compare import environment, identity, run, sample, save, summarize_named
from grhsim_elf_section_identity import sections
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify

OUT = ROOT/'build/armor-cv32-xs-causes-v1'
CV = FROZEN.parent/'concat-slices-v1/candidate.json'
XS = PREV/'xs-default/model/wolvrix_xs_pre_reg_to_mem_accumulate_bank.json'
EVENT = {'event_regions': True, 'event_regions_shared': True, 'event_regions_shared_connected': True}
VIEWS = ['COVERED_STATE_VIEW_NOTIFICATIONS', 'COVERED_STATE_VIEW_INLINE',
         'COVERED_STATE_VIEW_COMPOSITION', 'COVERED_STATE_VIEW_COMPOSITION_INLINE']
MUX = ['CONDITIONAL_MUX_CONES', 'CONDITIONAL_MUX_INPUT_CACHE', 'CONDITIONAL_MUX_SHARED_ARM']
SCHEDULE = {'events', 'node', 'super'}
EMITTER = {'batch', 'alias', 'views', 'mux', 'equality'}
ALL = SCHEDULE | EMITTER
# Flags are changes from XS to CV settings. 'graph' uses the CV frontend output.
VARIANTS = {
    'xs': set(), 'cv': ALL | {'graph'}, 'cv-off': ALL | {'graph', 'off'},
    'graph': {'graph'}, 'schedule': SCHEDULE, 'emitter': EMITTER, 'both': ALL,
    'events': {'events'}, 'node': {'node'}, 'super': {'super'},
    'limits': {'node', 'super'}, 'batch': {'batch'}, 'alias': {'alias'},
    'views': {'views'}, 'mux': {'mux'}, 'equality': {'equality'},
    'events-emitter': {'events'} | EMITTER, 'limits-emitter': {'node', 'super'} | EMITTER,
    'private': {'private'}, 'shared': {'shared'}, 'no-regmem': ALL | {'no-regmem'},
    'before-concat': ALL | {'before-concat'},
    'events-mux': {'events', 'mux'}, 'events-views': {'events', 'views'},
    'events-mux-views': {'events', 'mux', 'views'}, 'events-cones': {'events', 'cones'},
    'events-cones-cache': {'events', 'cones', 'cache'},
}


def emit(name):
    import wolvrix
    from wolvrix_xs_grhsim import require_ok, write_supernode_stats
    switches = VARIANTS[name]
    model = OUT/name/'model'
    model.mkdir(parents=True)
    cv_graph = 'graph' in switches or 'before-concat' in switches
    graph = CV if cv_graph else XS
    if 'before-concat' in switches:
        graph = RUN2/'graph.json'
    os.environ.update(WOLVRIX_GRHSIM_LOGIC_EAGER_OPERAND_CHARS='0' if 'off' in switches else '4096',
                      WOLVRIX_GRHSIM_KEEP_X86_MEMORY_CMOV='0' if 'off' in switches else '1',
                      WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=str(int('alias' in switches)))
    for group, options in [('views', VIEWS), ('mux', MUX), ('equality', ['SHARED_EQUALITY_FAMILIES'])]:
        for opt in options:
            os.environ['WOLVRIX_GRHSIM_'+opt] = str(int(group in switches))
    if 'cones' in switches:
        os.environ['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CONES']='1'
    if 'cache' in switches:
        os.environ['WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE']='1'
    schedule = dict(path='Cv32Bench')
    if 'events' in switches:
        schedule.update(EVENT)
    elif 'private' in switches or 'shared' in switches:
        schedule.update(event_regions=True, event_regions_shared='shared' in switches)
    if 'node' not in switches:
        schedule.update(max_op_in_compute_node=108, split_oversize_compute_nodes=True,
                        split_oversize_compute_node_max_ops=108)
    if 'super' not in switches:
        schedule.update(max_op_in_compute_supernode=108)
    batches = {} if 'batch' in switches else dict(sched_batch_max_ops=2048, sched_batch_max_estimated_lines=8192,
                                                   sched_batch_target_count=64)
    save(model.parent/'config.json', dict(graph=identity(graph), switches=sorted(switches), schedule=schedule,
         batches=batches, environment={k: v for k,v in os.environ.items() if k.startswith('WOLVRIX_GRHSIM_')}))
    with wolvrix.Session() as sess:
        require_ok(sess.read_json_file(str(graph), out_design='design.main'), 'read')
        if not cv_graph and 'no-regmem' not in switches:
            require_ok(sess.run_pass('reg-to-mem', design='design.main', ordered_writes=True, decoded_write_storage=True), 'reg-to-mem')
        if not cv_graph:
            require_ok(sess.run_pass('accumulate-sink', design='design.main', args=['-mode=bank']), 'bank')
        require_ok(sess.run_pass('activity-schedule', design='design.main', **schedule), 'schedule')
        write_supernode_stats(sess, 'Cv32Bench.activity_schedule.supernode_to_ops', model)
        require_ok(sess.emit_grhsim_cpp(design='design.main', output=str(model), top=['Cv32Bench'],
                                        waveform='off', perf='off', emit_parallelism=4, **batches), 'emit')


def build(name):
    dest = OUT/name
    model = dest/'model'
    if (dest/'build.json').exists():
        verify(read(dest/'build.json')['binary'])
        return
    if not (dest/'emit.result.json').exists() or read(dest/'emit.result.json')['returncode'] != 0:
        run([sys.executable, __file__, 'emit', name], dest/'emit.log',
            env=dict(environment(), PYTHONPATH=str(TOOLS/'python'), LD_LIBRARY_PATH=str(TOOLS)))
    reference = {'xs':'xs-default', 'cv':'cv-on', 'cv-off':'cv-off'}.get(name)
    files = sorted([*model.glob('*.cpp'), *model.glob('*.hpp'), model/'Makefile'])
    if reference:
        frozen = PREV/reference/'model'
        if {p.name for p in files} != {p.name for p in frozen.iterdir() if p.suffix in ('.cpp','.hpp') or p.name=='Makefile'}:
            raise ValueError(f'{name}: generated file set differs')
        # Reloading the XS checkpoint renumbers operation IDs in emitter comments.
        for src in files:
            if filecmp.cmp(src, frozen/src.name, shallow=False):
                continue
            actual = [line for line in src.read_bytes().splitlines() if not line.lstrip().startswith(b'//')]
            original = [line for line in (frozen/src.name).read_bytes().splitlines() if not line.lstrip().startswith(b'//')]
            if actual != original:
                raise ValueError(f'{name}: executable source differs in {src.name}')
        (dest/'emu').symlink_to(PREV/reference/'emu')
    else:
        run(['make', '-C', model, '-j6', 'CXX='+str(CXX), 'CXXFLAGS='+' '.join(FLAGS)], dest/'compile.log')
        run([CXX, *FLAGS, '-DCV32_GRHSIM', '-I', model, RUN2/'inputs/fixture/harness.cpp',
             model/'libgrhsim_Cv32Bench.a', '-o', dest/'emu'], dest/'link.log')
    stats=read(model/'activity_schedule_supernode_stats.json')
    save(dest/'build.json', dict(binary=identity(dest/'emu'), reference=reference, files=len(files),
         sections=sections(dest/'emu'), supernodes=stats['supernodes'], compute=stats['compute_supernodes'],
         commit=stats['commit_supernodes'], batches=len(list(model.glob('*_sched_*.cpp')))))
    print('built', name, flush=True)


def setup():
    OUT.mkdir(exist_ok=True)
    for name in ('firmware','verification.json'):
        if not (OUT/name).exists():
            (OUT/name).symlink_to(FROZEN/name)


def scout(names):
    expected=read(OUT/'verification.json')['workloads']['coremark']['verilator']['trace']['sha256']
    with measurement_lock(LOCK, wait=True):
        for name in names:
            dest=OUT/name
            verify(read(dest/'build.json')['binary'])
            if (dest/'pmu.json').exists():
                continue
            row=sample(OUT,name,'coremark','verify',trace=True)
            if row['trace']['sha256'] != expected:
                raise ValueError(name+': differing bus trace')
            events='instructions:u,cycles:u,branches:u,branch-misses:u'
            sample(OUT,name,'coremark','counts',perf=['stat','-x,','-o',dest/'perf.csv','-e',events])
            counts={}
            for line in (dest/'perf.csv').read_text().splitlines():
                f=line.split(',')
                if len(f)>4 and f[2] in events.split(','):
                    if float(f[4])<95:
                        raise ValueError('multiplexed events: '+line)
                    counts[f[2].split(':')[0]]=int(f[0])/row['cycles']
            if len(counts)!=4:
                raise ValueError('incomplete counters for '+name)
            save(dest/'pmu.json', dict(per_guest_cycle=counts, trace_sha256=expected))
            print(name, counts,flush=True)


def work(names):
    from cv32e40p_event_region_counts import main as count_regions
    source=OUT/'counter-inputs'
    source.mkdir(exist_ok=True)
    binaries={}
    for name in names:
        model=OUT/name/'model'
        if not (model/'emu').exists():
            (model/'emu').symlink_to(OUT/name/'emu')
        if not (source/name).exists():
            (source/name).symlink_to(model)
        binaries[name]=identity(model/'emu')
    for item in ('firmware','verification.json'):
        if not (source/item).exists():
            (source/item).symlink_to(OUT/item)
    save(source/'build.json',dict(binaries=binaries))
    with measurement_lock(LOCK,wait=True):
        for name in names:
            output=OUT/name/'work'
            if not (output/'counts.json').exists():
                count_regions(source,output,6,backend=name,harness_path=RUN2/'inputs/fixture/harness.cpp')


def profile(names):
    with measurement_lock(LOCK,wait=True):
        for name in names:
            dest=OUT/name
            data=dest/'cycles.data'
            sample(OUT,name,'coremark','profile',perf=['record','-e','cycles:u','-c','200003','-o',data])
            result=subprocess.run(['perf','report','--stdio','--no-children','--percent-limit','0.1',
                                   '--sort','dso,symbol','-i',data],capture_output=True,text=True,check=True)
            (dest/'profile.txt').write_text(result.stdout)


def timing(label,names,rounds):
    dest=OUT/label
    dest.mkdir()
    # Rotations of a balanced first row, with reversed orders on the next cycle.
    n=len(names)
    first = [0] + [i//2+1 if i%2==0 else n-1-i//2 for i in range(n-1)]
    orders=[[names[(j+i)%n] for j in (first if i//n%2==0 else first[::-1])] for i in range(rounds)]
    save(dest/'orders.json',orders)
    rows=[]
    with measurement_lock(LOCK,wait=True):
        for name in names:
            if not (OUT/name/'pmu.json').is_file():
                raise ValueError('verify before timing '+name)
            sample(OUT,name,'coremark',label+'-warmup')
        for i,order in enumerate(orders):
            rows.append({name:sample(OUT,name,'coremark',f'{label}-{i+1}') for name in order})
            save(dest/'rows.json',rows)
            print('round',i+1,flush=True)
    save(dest/'summary.json',{name:dict(wall_s=statistics.mean(r[name]['wall_s'] for r in rows),
         comparisons={ref:summarize_named(rows,name,ref)['wall_s'] for ref in names if ref!=name}) for name in names})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['build','emit','scout','timing','profile','work'])
    p.add_argument('names',nargs='+',choices=VARIANTS)
    p.add_argument('--label',default='timing')
    p.add_argument('--rounds',type=int,default=8)
    a=p.parse_args()
    if a.stage != 'emit' and not platform.node().startswith('node030'):
        p.error('these native builds and measurements use node030')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    if a.stage=='emit':
        emit(a.names[0])
    elif a.stage=='build':
        setup()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(build,a.names))
    elif a.stage=='scout':
        scout(a.names)
    elif a.stage=='work':
        work(a.names)
    elif a.stage=='profile':
        profile(a.names)
    else:
        timing(a.label,a.names,a.rounds)
