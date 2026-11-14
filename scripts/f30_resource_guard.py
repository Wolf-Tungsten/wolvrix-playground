"""External, diagnostic-only memory guard for an F30 benchmark child process."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

from benchmark_f29_pass_trace import write_json_atomic


class ProcessMemoryUnavailable(ValueError):
    """/proc has lost the process address space, possibly during exit_mm."""


@dataclass(frozen=True)
class GuardLimits:
    rss_bytes: int = 96 * 1024**3
    psi_percent: float = 25.0
    psi_seconds: float = 8.0
    interval_s: float = 0.25
    terminate_grace_s: float = 2.0

    def validate(self):
        if type(self.rss_bytes) is not int or self.rss_bytes <= 0:
            raise ValueError('resource guard RSS limit must be a positive byte count')
        for field in ('psi_percent', 'psi_seconds', 'interval_s', 'terminate_grace_s'):
            value = getattr(self, field)
            if not math.isfinite(value) or value <= 0:
                raise ValueError('resource guard ' + field + ' must be positive and finite')
        if self.psi_percent > 100 or self.interval_s > 1:
            raise ValueError('resource guard PSI must be <=100%, sampling interval <=1 s')


def process_memory(pid, proc_root=Path('/proc')):
    wanted = {'VmRSS', 'RssAnon', 'RssFile', 'RssShmem', 'VmSwap', 'VmHWM'}
    result = {}
    for line in (proc_root / str(pid) / 'status').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in wanted:
            amount, unit = value.split()
            if unit != 'kB':
                raise ValueError('unexpected /proc memory unit: ' + line)
            result[key] = int(amount) * 1024
    if 'VmRSS' not in result:
        raise ProcessMemoryUnavailable('benchmark VmRSS is unavailable')
    return result


def find_cgroup(pid, proc_root=Path('/proc'), cgroup_root=Path('/sys/fs/cgroup')):
    for line in (proc_root / str(pid) / 'cgroup').read_text().splitlines():
        fields = line.split(':', 2)
        if len(fields) == 3 and fields[:2] == ['0', '']:
            relative = Path(fields[2].lstrip('/'))
            if '..' in relative.parts:
                raise ValueError('unsafe cgroup path')
            path = cgroup_root / relative
            return path if (path / 'memory.current').is_file() else None
    return None


def read_pressure(path):
    pressure = {}
    for line in (path / 'memory.pressure').read_text().splitlines():
        name, *values = line.split()
        pressure[name] = {key: float(value) for key, value in (item.split('=', 1) for item in values)}
    if not all(name in pressure and math.isfinite(pressure[name].get('avg10', float('nan')))
               for name in ('some', 'full')):
        raise ValueError('cgroup PSI lacks finite some/full avg10')
    return pressure


def cgroup_memory(path):
    if path is None:
        return {'available': False, 'error': 'no readable cgroup v2 memory controller; RSS guard remains active'}
    result = {'available': False, 'path': str(path), 'pressure_sources': []}
    try:
        result.update(memory_current_bytes=int((path / 'memory.current').read_text()),
                      memory_stat={key: int(value) for key, value in
                                   (line.split() for line in (path / 'memory.stat').read_text().splitlines())})
        swap = path / 'memory.swap.current'
        if swap.is_file():
            result['swap_current_bytes'] = int(swap.read_text())
        result['available'] = True
    except (OSError, ValueError) as error:
        result['error'] = str(error)
    # systemd-oomd monitors user@*.service aggregate pressure on this host.
    # Keep its PSI separate from the child scope's charged-memory accounting.
    parents = [parent for parent in path.parents
               if parent.name.startswith('user@') and parent.name.endswith('.service')]
    for source in (path, *parents):
        row = {'path': str(source)}
        try:
            row.update(available=True, pressure=read_pressure(source))
            if source == path:
                result['pressure'] = row['pressure']
        except (OSError, ValueError) as error:
            row.update(available=False, error=str(error))
        result['pressure_sources'].append(row)
    return result


class PressureDeadline:
    def __init__(self, limits):
        self.limits = limits
        self.started = None
        self.trigger = None

    def observe(self, sample, now):
        group = sample['cgroup']
        sources = group.get('pressure_sources')
        if sources is None:
            sources = [group] if group.get('available') else []
        readings = [(source['pressure'][name]['avg10'], source.get('path'), name)
                    for source in sources if source.get('available') for name in ('some', 'full')]
        highest = max(readings, key=lambda row: row[0]) if readings else None
        if highest is None or highest[0] < self.limits.psi_percent:
            self.started = None
            self.trigger = None
            return False
        if self.started is None:
            self.started = now
        self.trigger = {'path': highest[1], 'kind': highest[2], 'avg10': highest[0],
                        'started_monotonic_s': self.started, 'sustained_s': now - self.started}
        return now - self.started >= self.limits.psi_seconds


def current_phase(output):
    """Read only small progress files; an incomplete native call has no duration."""
    try:
        summary = json.loads((output / 'summary.json').read_text())
        active = summary.get('active_stage', {})
        if active.get('kind') == 'transform':
            timing = output / summary['mode'] / 'timing.json'
            try:
                passes = json.loads(timing.read_text()).get('passes', [])
            except (OSError, ValueError):
                passes = summary.get('trace' if summary['mode'] == 'trace' else 'no_trace', {}).get('passes', [])
            completed = {row['pass'] for row in passes if row.get('status') == 'passed'}
            active = {**active, 'name': ('comb-loop-elim' if 'comb-loop-elim' not in completed else
                                       'split-static-array' if 'split-static-array' not in completed else
                                       'transform-finish')}
        return active or {'name': 'initialization'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'name': 'initialization'}


def terminate_child(child, grace_s):
    """The child was created with start_new_session; never signal the caller's group."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        result = child.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        result = None
    finally:
        # Helpers belong to the same private group. Clean up even when the main
        # benchmark exited promptly but a helper ignored SIGTERM.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return child.wait(timeout=grace_s) if result is None else result


def annotate_summary(output, guard):
    summary = output / 'summary.json'
    try:
        report = json.loads(summary.read_text())
    except (OSError, ValueError):
        report = {'schema': 'wolvrix.f30.pipeline-benchmark.v1', 'status': 'failed'}
    if not isinstance(report, dict):
        raise ValueError('benchmark summary is not an object')
    report['resource_guard'] = {'diagnostic_only': True, 'path': str(output / 'guard.json'),
                                'status': guard['status']}
    if guard['status'] != 'completed':
        report['termination'] = {'kind': 'resource-guard', 'reason': guard['reason'],
                                 'native_summary_status': report.get('status'),
                                 'returncode': guard['returncode'], 'observed_at_ns': guard['finished_at_ns'],
                                 'last_sample': guard.get('last_sample')}
        report['status'] = 'failed'
    # Preserve all completed stage/pass rows. A killed call gains no fake pass_s,
    # pass_returned, finished_at_ns or successful native completion evidence.
    write_json_atomic(summary, report)


def run_guarded(command, output, limits=GuardLimits(), *, sampler=None):
    """Supervise a private child in this PID namespace, independently of its GIL."""
    limits.validate()
    output = Path(output)
    guard_path, samples_path = output / 'guard.json', output / 'resources.samples.jsonl'
    if guard_path.exists() or samples_path.exists():
        raise ValueError('refusing to overwrite existing resource guard evidence')
    guard = {'schema': 'wolvrix.f30.resource-guard.v1', 'diagnostic_only': True,
             'status': 'running', 'limits': asdict(limits), 'command': command,
             'supervisor_pid': os.getpid(), 'started_at_ns': time.time_ns(),
             'scope': 'benchmark process RSS; cgroup charged memory includes other processes and file cache',
             'limitation': 'sampled RSS stop is not a hard memory cap and can overshoot between samples',
             'samples': str(samples_path), 'sample_count': 0, 'returncode': None}
    write_json_atomic(guard_path, guard)
    pending_signal = []
    def receive_signal(number, frame):
        pending_signal.append(number)
    previous = {number: signal.signal(number, receive_signal) for number in (signal.SIGINT, signal.SIGTERM)}
    child = None
    reason = None
    deadline = PressureDeadline(limits)
    phase_at = 0.0
    phase = {'name': 'initialization'}
    try:
        child = subprocess.Popen(command, start_new_session=True)
        guard['benchmark_pid'] = child.pid
        try:
            group = find_cgroup(child.pid)
        except (OSError, ValueError):
            group = None
        guard['cgroup_path'] = str(group) if group else None
        write_json_atomic(guard_path, guard)
        with samples_path.open('x', encoding='utf-8') as stream:
            while child.poll() is None:
                now = time.monotonic()
                if now - phase_at >= 1.0:
                    phase, phase_at = current_phase(output), now
                if pending_signal:
                    reason = 'supervisor_signal'
                    guard['signal'] = pending_signal[0]
                    break
                try:
                    sample = (sampler(child.pid, group) if sampler else
                              {'process_bytes': process_memory(child.pid), 'cgroup': cgroup_memory(group)})
                except (OSError, ValueError) as error:
                    if child.poll() is not None:
                        break
                    if isinstance(error, (ProcessMemoryUnavailable, FileNotFoundError, ProcessLookupError)):
                        # Linux may drop the address space before waitpid sees
                        # exit. Large address-space teardown can take hundreds of
                        # milliseconds. Reuse the bounded cleanup grace; only a
                        # real exit code resolves this, never a completed summary.
                        waiting = time.monotonic()
                        try:
                            code = child.wait(timeout=limits.terminate_grace_s)
                        except subprocess.TimeoutExpired:
                            pass  # A live child with unreadable RSS still fails closed.
                        else:
                            guard['exit_observation'] = {'sample_error': repr(error), 'returncode': code,
                                                         'waited_s': time.monotonic() - waiting,
                                                         'maximum_wait_s': limits.terminate_grace_s}
                            break
                    reason = 'monitor_error'
                    guard['error'] = repr(error)
                    break
                sample.update(time_ns=time.time_ns(), monotonic_s=now, phase=phase)
                if sample['process_bytes']['VmRSS'] >= limits.rss_bytes:
                    reason = 'rss_limit'
                elif deadline.observe(sample, now):
                    reason = 'cgroup_pressure'
                    guard['pressure_trigger'] = deadline.trigger
                if reason:
                    sample['phase'] = current_phase(output)
                stream.write(json.dumps(sample, separators=(',', ':')) + '\n')
                stream.flush()
                guard.update(last_sample=sample, sample_count=guard['sample_count'] + 1)
                if reason:
                    break
                time.sleep(limits.interval_s)
        if pending_signal and reason is None:
            reason = 'supervisor_signal'
            guard['signal'] = pending_signal[0]
        if reason:
            guard.update(status='failed', reason=reason, stop_requested_at_ns=time.time_ns(),
                         phase=current_phase(output))
            # Persist the exact trigger before any termination signal is sent.
            write_json_atomic(guard_path, guard)
            returncode = terminate_child(child, limits.terminate_grace_s)
        else:
            returncode = child.wait()
            # A child can exit before its watchdog/profiler helpers. The private
            # group belongs to this run even after its leader has returned.
            terminate_child(child, limits.terminate_grace_s)
            guard.update(status='completed' if returncode == 0 else 'failed',
                         reason='child_completed' if returncode == 0 else 'child_exit')
        guard.update(returncode=returncode, finished_at_ns=time.time_ns())
        write_json_atomic(guard_path, guard)
        annotate_summary(output, guard)
        return 0 if guard['status'] == 'completed' else 1
    except BaseException as error:
        guard.update(status='failed', reason=reason or 'supervisor_error', error=repr(error),
                     stop_requested_at_ns=time.time_ns())
        try:
            write_json_atomic(guard_path, guard)
        except BaseException as persistence_error:
            guard['persistence_error'] = repr(persistence_error)
        finally:
            # Disk-full/rename failures must never leave a heavy benchmark alive.
            if child is not None:
                try:
                    guard['returncode'] = terminate_child(child, limits.terminate_grace_s)
                except BaseException as cleanup_error:
                    guard['cleanup_error'] = repr(cleanup_error)
        guard['finished_at_ns'] = time.time_ns()
        for persist in (lambda: write_json_atomic(guard_path, guard),
                        lambda: annotate_summary(output, guard)):
            try:
                persist()
            except BaseException:
                pass  # Preserve the original failure after unconditional cleanup.
        raise
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
