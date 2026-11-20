from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT/'scripts'))
from grhsim_single_baseline import identity, save
from xiangshan_cv32_ablation_measure import read
from build_models import CHECKPOINT, TOOLS

def structure(name):
    model = OUT/name/'model'
    stats = read(model/'activity_schedule_supernode_stats.json')
    log = (OUT/name/'emit.log').read_text()
    source = sorted(model.glob('grhsim_SimTop_sched_*.cpp'))
    cones = caches = shared_ops = 0
    for f in source:
        code = f.read_bytes()
        cones += code.count(b'// Conditional mux cone:')
        caches += code.count(b'// Conditional mux input cache:')
        shared_ops += sum(map(int,re.findall(rb'// Conditional mux shared arm:[^\n]*? added=(\d+)',code)))
    match = re.search(r'\[GRHSIM_COVERED_STATE_VIEWS\] values=(\d+)',log)
    def metrics(tag):
        line = next((l for l in log.splitlines() if 'activity-schedule '+tag+': ' in l), '')
        return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)\b',line)}
    return dict(compute=stats['compute_supernodes'], commit=stats['commit_supernodes'],
                boundary_values=stats['boundary_values'], activation_edges=stats['boundary_activation_edges'],
                state_read_edges=stats['state_read_activation_edges'], batches=len(source),
                mux_cones=cones, mux_input_caches=caches, shared_arm_ops=shared_ops,
                covered_values=int(match[1]) if match else 0,
                split=metrics('compute-node final split detail'), event_regions=metrics('event-regions'),
                shared_regions=metrics('shared event-regions'), elf_bytes=read(OUT/name/'binary.json')['bytes'])

if __name__ == '__main__':
    result = {n:structure(n) for n in ['base','full','events','mux','views']}
    save(OUT/'models.json',result)
    save(OUT/'inputs.json',dict(checkpoint=identity(CHECKPOINT),
         wolvrix=identity(TOOLS/'libwolvrix-lib.so'), python_binding=identity(TOOLS/'python/wolvrix/_wolvrix.so'),
         compiler=identity('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')))
    print(result)
