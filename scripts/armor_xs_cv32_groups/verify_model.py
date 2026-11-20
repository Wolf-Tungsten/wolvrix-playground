"""Compare a 100k CoreMark window and final perf counters with the frozen TNO0017 reference."""
from collections import Counter
from pathlib import Path
import os
import resource
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT / 'scripts'))
from armor_dispatch_diag import runtime
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import parse_run, save
from xiangshan_cv32_ablation_measure import read, signature, verify

def run(name, cpu):
    ref = ROOT / 'build/armor-expression-default-v1/coremark-default'
    binary = read(OUT / name / 'binary.json')
    verify(binary)
    dest = OUT / 'correctness' / name
    dest.mkdir(parents=True)
    rt, env, emu = runtime(dest, Path(binary['path']))
    command = ['taskset','-c',str(cpu),'numactl','--membind=1','setarch','x86_64','-R',
               *emu, '-C','100000','--dump-difftrace','./trace_s0','--force-dump-result']
    with (dest/'run.log').open('w') as stream:
        subprocess.run(command, cwd=rt/'bin', env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    def decode(path):
        lines = path.read_text().splitlines()
        counters = Counter(line for line in lines if line.startswith('[PERF ]'))
        row = parse_run('\n'.join(line for line in lines if not line.startswith('[PERF ]')), 100000)
        return row, counters
    expected, ref_counters = decode(ref/'run.log')
    row, counters = decode(dest/'run.log')
    if signature(expected) != signature(row) or counters != ref_counters or sum(counters.values()) != 35063:
        raise ValueError(f'{name} endpoint or final counters differ')
    comp = ROOT/'build/armor-dispatch-v1/timing-v1/trace-comparator/compare'
    trace = compare_traces(comp, ref/'runtime/bin/trace_s0', rt/'bin/trace_s0', dest/'trace.json')
    coverage = validate_trace_coverage(trace, row)
    if coverage['records'] != 99999:
        raise ValueError('incomplete trace')
    save(dest/'result.json', dict(binary=binary, signature=signature(row), coverage=coverage,
         final_perf_lines=sum(counters.values()), command=command, reference=str(ref)))
    print('verified', name, flush=True)

if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    run(sys.argv[1], int(sys.argv[2]))
