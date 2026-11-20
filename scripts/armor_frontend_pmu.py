"""CPU96 baseline/candidate PMU diagnostics for the one-bit lane experiment."""
import argparse
from collections import Counter
import csv
from pathlib import Path
import platform
import resource
import signal
import subprocess

from cv32e40p_compare import CXX
from grhsim_single_baseline import Baseline, identity, save
from xiangshan_cv32_ablation_measure import measurement_lock, read, signature, verify

FRONTEND = 'de_no_dispatch_per_slot.no_ops_from_frontend'
IC_MISS = 'ic_tag_hit_miss.instruction_cache_miss'
EVENTS = ['cycles:u', 'instructions:u', FRONTEND + ':u', IC_MISS + ':u']


class PerfObserver:
    def __init__(self, directory, mode):
        self.directory = directory
        self.mode = mode
        self.process = None

    def start(self, pid, started):
        if self.mode == 'stat':
            args = ['stat', '-x', ',', '--no-big-num', '--no-scale', '-e', ','.join(EVENTS),
                    '-o', str(self.directory/'stat.csv')]
        else:
            args = ['record', '-e', FRONTEND + ':u', '-c', '10000000',
                    '-o', str(self.directory/'frontend.data')]
        command = ['perf', *args, '-p', str(pid)]
        save(self.directory/(self.mode+'-command.json'), command)
        with (self.directory/(self.mode+'.log')).open('w') as stream:
            self.process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)

    def finish(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        code = self.process.wait(timeout=30)
        self.process = None
        if code not in (0, -signal.SIGINT, 128 + signal.SIGINT):
            raise RuntimeError(f'perf {self.mode} failed ({code})')


def groups(samples):
    counts = Counter()
    for line in samples.splitlines():
        if not line.strip():
            continue
        prefix, delim, suffix = line.strip().rpartition(' (')
        if not delim:
            raise ValueError('missing DSO in perf script sample: '+line)
        symbol = prefix.partition(' ')[2]
        dso = Path(suffix.rstrip(')')).name
        if 'GrhSIM_SimTop::eval_compute_batch_' in symbol:
            phase = 'compute'
        elif 'GrhSIM_SimTop::eval_commit_batch_' in symbol:
            phase = 'commit'
        elif 'GrhSIM_SimTop::' in symbol:
            phase = 'other_model'
        elif 'nemu' in dso.lower():
            phase = 'NEMU'
        elif dso == 'emu':
            phase = 'harness_and_other_emu'
        else:
            phase = 'library_or_unresolved'
        counts[phase] += 1
    if not counts['compute'] or not counts['commit']:
        raise ValueError('perf symbols do not cover compute and commit')
    return dict(counts)


def run(archive, out, binary):
    if not platform.node().startswith('node030'):
        raise ValueError('CPU96 measurements require node030')
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    reference = archive/'build/xs/indexed-snapshot-20261117-v3'
    original = read(reference/'measurement/candidate/runs/runtime_plan.json')
    inputs = {row['role']: row['source'] for row in original['files'] if row['role'] != 'library'}
    for record in inputs.values():
        verify(record)
    binary = binary or Path(inputs['binary']['path'])
    expected = signature(read(reference/'measurement/candidate/runs/round00.json'))
    args = argparse.Namespace(output=out, binary=binary, image=Path(inputs['image']['path']),
        nemu=Path(inputs['reference']['path']), compiler=CXX, tools_dir=None, sim_primitives='none',
        xs_source=archive/'testcase/xiangshan', cpu=96, jobs=1, cycles=100000, repeats=1)
    with measurement_lock(archive/'build/xs/xiangshan-cpu96-measure.lock'):
        runner = Baseline(args)
        prepared = runner.prepare_measurement()
        rows = {}
        for mode in ('stat', 'record'):
            observe = PerfObserver(out, mode)
            try:
                row = runner.run_sample(prepared, 'frontend-'+mode, 100000, process_observer=observe)
            finally:
                observe.finish()
            if signature(row) != expected:
                raise ValueError('baseline/PMU signature mismatch')
            rows[mode] = row
        summarize(out, binary, rows)


def summarize(out, binary, rows):
    counts = {}
    for cells in csv.reader((out/'stat.csv').read_text().splitlines()):
        if len(cells) >= 5 and cells[2] in EVENTS:
            percent = float(cells[4])
            if percent < 99.0:
                raise ValueError('PMU counter multiplexing: '+str(cells))
            counts[cells[2]] = dict(value=int(cells[0]), running_percent=percent,
                per_guest_cycle=int(cells[0])/rows['stat']['guest_cycles'])
    if set(counts) != set(EVENTS):
        raise ValueError('missing stat events: '+str(counts))
    report = subprocess.check_output(['perf', 'script', '-i', out/'frontend.data', '-F', 'ip,sym,dso'],
                                     text=True, errors='replace')
    (out/'symbols.txt').write_text(report)
    save(out/'report.json', dict(binary=identity(binary), events=counts, sample_groups=groups(report),
        runs=rows, scope='User-space process attach after launch, including initialization and harness. '
        'Symbol counts are samples, not per-phase exact stalls.'))
    print('PMU complete', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--binary', type=Path)
    a = p.parse_args()
    run(a.archive.resolve(), a.output.resolve(), a.binary)
