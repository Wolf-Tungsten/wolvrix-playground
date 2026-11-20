"""Compile a generated XS model and check its CoreMark trace and counter dump."""
from collections import Counter
import shutil
import sys

from armor_acc_compare import ARCHIVE
from armor_acc_measure import runners
from cv32e40p_compare import ROOT, run
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import clean_environment, identity, parse_run, save
from xiangshan_cv32_ablation_measure import measurement_lock, read, signature

OUT = ROOT / 'build/armor-acc-default-v1'
dest = OUT / sys.argv[1]
prior = ROOT / 'build/armor-acc-v1'
control = prior / 'K/xs'
reference = prior / 'functional-commit-bank'
reference_run = read(reference / 'full/runs/verify-s0.json')
reference_counters = prior / 'perfdump-commit-bank-dump/full-final.perf.txt'
shutil.copytree(control / 'chisel-home', dest / 'chisel-home', dirs_exist_ok=True)
env = dict(clean_environment(), NOOP_HOME=str(ARCHIVE / 'testcase/xiangshan'), LC_ALL='C')
command = read(control / 'compile.command.json')['argv']
run([arg.replace(str(control), str(dest)) for arg in command], dest / 'compile.log', env=env)
binary = identity(dest / 'emu/grhsim-compile/emu')
manifest = read(reference / 'manifest.json')
manifest['models'] = {'default': {'binary': binary}}
with measurement_lock(ROOT / 'build/armor-post-mask-analysis-v1/node029-semantic.lock', wait=True):
    _, setup = runners(dest / 'verify', manifest, ['default'])['default']
    command = [*setup['base'], '-C', '100000', '--dump-difftrace', './trace_s0', '--force-dump-result']
    log = dest / 'verify/coremark.log'
    run(command, log, env=setup['runtime'], cwd=setup['binary'].parent)
    lines = log.read_text().splitlines()
    counters = [line for line in lines if line.startswith('[PERF ]')]
    endpoint = parse_run('\n'.join(line for line in lines if not line.startswith('[PERF ]')) + '\n', 100000)
    assert signature(endpoint) == signature(reference_run)
    trace = compare_traces(reference / 'trace-comparator/compare', reference / 'full/runs/runtime/bin/trace_s0',
                           setup['binary'].parent / 'trace_s0', dest / 'verify/trace.json')
    coverage = validate_trace_coverage(trace, endpoint)
    assert trace['records'] == 99999 and coverage['pass_']
    assert len(counters) == 35063 and Counter(counters) == Counter(reference_counters.read_text().splitlines())
    save(dest / 'verify/result.json', dict(binary=binary, signature=signature(endpoint), trace=coverage,
         counter_lines=len(counters), nonzero_lines=sum(not line.endswith(', 0') for line in counters),
         reference_counters=identity(reference_counters), status='pass'))
