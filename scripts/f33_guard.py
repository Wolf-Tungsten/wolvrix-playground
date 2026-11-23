"""F33 matched-pass references and an external, fail-closed deadline supervisor."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import time

from benchmark_f29_pass_trace import sha256, write_json_atomic
from f30_resource_guard import (GuardLimits, PressureDeadline, cgroup_memory,
                                find_cgroup, process_memory, terminate_child)


PASSES = ('constant-analysis#0', 'dead-code-elim#2')
BOUNDARIES = dict(zip(PASSES, ('Q0', 'Q1')))
# The unique third-DCE stage preserves GSIM's historical repeated timer identity.
GSIM_TIMERS = dict(zip(PASSES, ('ConstantAnalysis#0', 'RemoveDeadNodes#1')))
REFERENCE_SCHEMA = 'wolvrix.f33.reference.v1'
EVENT_SCHEMA = 'wolvrix.f33.stage-event.v1'
MAX_EVENT_BYTES = 16 * 1024


@dataclass(frozen=True)
class Window:
    name: str
    boundary_prefix: str
    calls: tuple[tuple[str, str, str], ...]

    @property
    def passes(self):
        return tuple(logical for logical, _, _ in self.calls)

    @property
    def boundaries(self):
        return {logical: self.boundary_prefix + str(i) for i, logical in enumerate(self.passes)}

    @property
    def reference_schema(self):
        return f'wolvrix.{self.name}.reference.v1'

    @property
    def guard_schema(self):
        return f'wolvrix.{self.name}.guard.v1'


F33 = Window('f33', 'Q', tuple(zip(PASSES, GSIM_TIMERS.values(), ('ConstantAnalysis', 'RemoveDeadNodes2'))))
F34 = Window('f34', 'R', (
    ('alias-analysis#0', 'AliasAnalysis#0', 'AliasAnalysis'),
    ('pattern-detect#0', 'PatternDetect#0', 'PatternDetect'),
    ('common-expr#0', 'CommonExpr#0', 'CommonExpr'),
    ('dead-code-elim#3', 'RemoveDeadNodes#2', 'RemoveDeadNodes3'),
))


def positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be finite and strictly positive')
    return float(value)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_identity(identity):
    if not isinstance(identity, dict):
        raise ValueError('reference identity must be an object')
    if identity.get('semantics') != '2state':
        raise ValueError('paired semantics must be explicitly 2state')
    if type(identity.get('batch_count')) is not int or identity['batch_count'] < 1:
        raise ValueError('reference requires a positive fresh-graph batch count')
    for name in ('input', 'configuration'):
        if not isinstance(identity.get(name), dict) or not identity[name]:
            raise ValueError('missing reference ' + name + ' identity')
    if re.fullmatch('[0-9a-f]{64}', str(identity['input'].get('sha256'))) is None:
        raise ValueError('missing source input SHA-256')
    for engine in ('grh', 'gsim'):
        native = identity.get(engine)
        if not isinstance(native, dict) or not isinstance(native.get('build'), dict) or not native['build']:
            raise ValueError('missing ' + engine + ' build identity')
        for key in ('source_sha256', 'binary_sha256'):
            if re.fullmatch('[0-9a-f]{64}', str(native.get(key))) is None:
                raise ValueError('missing ' + engine + ' ' + key)
    canonical(identity)
    return identity


def evidence_files(records):
    if not isinstance(records, list) or not records:
        raise ValueError('reference lacks immutable raw evidence')
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('path'), str):
            raise ValueError('invalid raw reference evidence')
        path = Path(record['path'])
        if not path.is_file() or sha256(path) != record.get('sha256'):
            raise ValueError('reference artifact is missing or changed: ' + str(path))


def reference_sample_identity(identity, window):
    validate_identity(identity)
    # GSIM measurements are independent of the GRH binary. The resulting
    # reference still pins the complete pair for the guarded GRH run.
    return {key: value for key, value in identity.items() if window != F34 or key != 'grh'}


def sample_times(sample, identity, window=F33):
    recorded_identity = sample.get('reference_identity') if isinstance(sample, dict) else None
    if (not isinstance(sample, dict) or sample.get('status') != 'completed' or
            sample.get('engine') != 'gsim' or sample.get('resource_interference') is not False or
            reference_sample_identity(recorded_identity, window) != reference_sample_identity(identity, window) or
            sample.get('fresh_graphs') != identity['batch_count'] or not sample.get('run_id')):
        raise ValueError('invalid or mismatched GSIM reference sample')
    records = sample.get('reference_evidence')
    evidence_files(records)
    times = sample.get('pass_times_s')
    if not isinstance(times, dict) or set(times) != set(window.passes):
        raise ValueError('GSIM reference requires exactly the window logical passes')
    times = {key: positive(times[key], key + ' native reference') for key in window.passes}
    artifacts = {row.get('kind'): Path(row['path']) for row in records}
    if any(sum(row.get('kind') == kind for row in records) != 1
           for kind in ('native-timing', 'stage-events', 'guard')):
        raise ValueError('reference requires unique native timer, stage-event and guard evidence')
    timers = [json.loads(line) for line in artifacts['native-timing'].read_text().splitlines() if line.strip()]
    if window == F34 and [(row.get('pass_instance'), row.get('stage')) for row in timers
                          if row.get('scope') == 'pass'][-len(window.calls):] != [
                              (timer, stage) for _, timer, stage in window.calls]:
        raise ValueError('GSIM reference did not finish in the expected pass order')
    for key, timer, expected_stage in window.calls:
        native = [row for row in timers if row.get('scope') == 'pass' and
                  row.get('pass_instance') == timer]
        if (len(native) != 1 or native[0].get('schema') != 'gsim-stage-timing.v1' or
                native[0].get('clock') != 'steady_clock' or native[0].get('complete') is not True or
                native[0].get('stage') != expected_stage or native[0].get('wall_s') != times[key] or
                native[0].get('batch_count', 1) != identity['batch_count']):
            raise ValueError('reference summary is not bound to its complete native timer: ' + key)
    tracker = PassDeadline(sample['run_id'], 'gsim', {}, identity['batch_count'], window=window)
    for line in artifacts['stage-events'].read_text().splitlines():
        tracker.consume(json.loads(line), time.monotonic())
    if (tracker.errors or tuple(tracker.completed) != window.passes or tracker.active or
            {key: event['wall_s'] for key, event in tracker.completed.items()} != times):
        raise ValueError('reference has invalid or mismatched native start/end events')
    guard = json.loads(artifacts['guard'].read_text())
    if (guard.get('schema') != window.guard_schema or guard.get('status') != 'completed' or
            guard.get('run_id') != sample['run_id'] or guard.get('engine') != 'gsim' or
            guard.get('resource_interference') is not False or guard.get('reference_identity') != recorded_identity or
            guard.get('pass_times_s') != times or guard.get('event_errors')):
        raise ValueError('reference did not complete with a valid independent supervisor')
    return times


def build_reference(samples, identity, window=F33):
    """Lock medians from complete, independent GSIM runs without a budget floor."""
    validate_identity(identity)
    if not isinstance(samples, list) or len(samples) < 3:
        raise ValueError('at least three valid GSIM reference samples are required')
    times = [sample_times(sample, identity, window) for sample in samples]
    if len({sample['run_id'] for sample in samples}) != len(samples):
        raise ValueError('GSIM reference samples must have distinct run identities')
    passes = {}
    for key, timer, _ in window.calls:
        raw = [row[key] for row in times]
        median = statistics.median(raw)
        tolerance = max(0.03 * median, 0.010)
        deviation = max(abs(value - median) for value in raw)
        if window == F33 and deviation > tolerance:
            raise ValueError('unstable GSIM reference; investigate environment or use fresh-graph calibration: ' + key)
        budget = positive(2 * median, key + ' budget')
        passes[key] = {'input_boundary': window.boundaries[key], 'native_timer': timer,
                       'samples_s': raw, 'median_s': median, 'budget_s': budget,
                       'jitter_tolerance_s': tolerance}
        if window == F34:
            passes[key].update(max_deviation_s=deviation, within_formal_jitter=deviation <= tolerance)
    return {'schema': window.reference_schema, 'identity': identity, 'passes': passes,
            'samples': samples, 'multiplier': 2, 'created_at_ns': time.time_ns()}


def validate_reference(reference, expected_identity, window=F33):
    validate_identity(expected_identity)
    if (not isinstance(reference, dict) or reference.get('schema') != window.reference_schema or
            reference.get('identity') != expected_identity or reference.get('multiplier') != 2):
        raise ValueError(f'missing or mismatched {window.name.upper()} GSIM reference')
    rebuilt = build_reference(reference.get('samples'), expected_identity, window)
    if reference.get('passes') != rebuilt['passes']:
        raise ValueError('GSIM reference medians/budgets/mapping were modified')
    return {key: rebuilt['passes'][key]['budget_s'] for key in window.passes}


def append_event(path, *, run_id, engine, logical_instance, event, wall_s=None, monotonic_s=None,
                 batch_count=1, window=F33):
    """Emit before/after native work; never hold exports inside the pass interval."""
    record = {'schema': f'wolvrix.{window.name}.stage-event.v1', 'run_id': run_id, 'engine': engine,
              'logical_instance': logical_instance, 'input_boundary': window.boundaries[logical_instance],
              'event': event, 'monotonic_s': time.monotonic() if monotonic_s is None else monotonic_s,
              'batch_count': batch_count}
    if wall_s is not None:
        record['wall_s'] = positive(wall_s, 'native pass wall_s')
    data = (canonical(record) + '\n').encode('utf-8')
    if len(data) > MAX_EVENT_BYTES:
        raise ValueError('stage event exceeds maximum line size')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.write(fd, data) != len(data):
            raise OSError('incomplete stage event append')
    finally:
        os.close(fd)
    return record


class PassDeadline:
    """Ordered, latched logical calls; damaged progress cannot clear an active call."""
    def __init__(self, run_id, engine, budgets, batch_count=1, *, window=F33):
        self.run_id, self.engine = run_id, engine
        self.batch_count = batch_count
        self.budgets = dict(budgets)
        self.passes = window.passes
        self.boundaries = window.boundaries
        self.active = None
        self.completed = {}
        self.events = []
        self.errors = []
        self.trigger = None
        self.last_timestamp = None

    def consume(self, event, now):
        try:
            if not isinstance(event, dict):
                raise ValueError('event is not an object')
            key = event.get('logical_instance')
            stamp = positive(event.get('monotonic_s'), 'event monotonic_s')
            if (event.get('run_id') != self.run_id or event.get('engine') != self.engine or
                    key not in self.boundaries or event.get('input_boundary') != self.boundaries[key] or
                    event.get('batch_count', 1) != self.batch_count):
                raise ValueError('event run/engine/logical occurrence/boundary identity mismatch')
            if stamp > now + 0.001 or (self.last_timestamp is not None and stamp < self.last_timestamp):
                raise ValueError('stage event has an impossible/nonmonotonic timestamp')
            kind = event.get('event')
            if kind == 'start':
                expected = self.passes[len(self.completed)] if len(self.completed) < len(self.passes) else None
                if self.active is not None or key != expected or key in self.completed:
                    raise ValueError('duplicate, overlapping or out-of-order pass start')
                self.active = dict(event)
            elif kind == 'end':
                duration = positive(event.get('wall_s'), 'native pass wall_s')
                if self.active is None or self.active['logical_instance'] != key:
                    raise ValueError('pass end has no matching latched start')
                if stamp < self.active['monotonic_s']:
                    raise ValueError('pass end precedes start')
                self.completed[key] = dict(event)
                self.active = None
                if key in self.budgets and duration > self.budgets[key]:
                    self.trigger = {'kind': 'completed-pass-over-budget', 'logical_instance': key,
                                    'input_boundary': self.boundaries[key], 'budget_s': self.budgets[key],
                                    'native_wall_s': duration, 'observed_monotonic_s': now}
            else:
                raise ValueError('unknown stage event kind')
            self.last_timestamp = stamp
            self.events.append(dict(event))
        except (KeyError, TypeError, ValueError) as error:
            self.errors.append({'error': str(error), 'event': event, 'observed_monotonic_s': now})
        return self.trigger

    def observe(self, now):
        if self.trigger is not None:
            return self.trigger
        if self.active is None:
            return None
        key = self.active['logical_instance']
        if key in self.budgets:
            deadline = self.active['monotonic_s'] + self.budgets[key]
            if now >= deadline:
                self.trigger = {'kind': 'running-pass-at-budget', 'logical_instance': key,
                                'input_boundary': self.boundaries[key], 'budget_s': self.budgets[key],
                                'started_monotonic_s': self.active['monotonic_s'], 'deadline_monotonic_s': deadline,
                                'observed_monotonic_s': now, 'observation_delay_s': now - deadline,
                                'elapsed_s': now - self.active['monotonic_s']}
        return self.trigger


@dataclass(frozen=True)
class SupervisorLimits:
    resources: GuardLimits = GuardLimits()
    poll_s: float = 0.010
    prefix_s: float = 1800.0
    between_passes_s: float = 1800.0
    suffix_s: float = 1800.0
    overall_s: float = 7200.0
    sampler_stall_s: float = 2.0

    def validate(self):
        self.resources.validate()
        for name in ('poll_s', 'prefix_s', 'between_passes_s', 'suffix_s', 'overall_s', 'sampler_stall_s'):
            positive(getattr(self, name), name)
        if self.poll_s > 0.050:
            raise ValueError('deadline poll interval must be <=50ms (250ms maximum observation delay)')


def _send(channel, kind, value):
    data = canonical({'kind': kind, 'value': value}).encode()
    if len(data) > 60000:
        data = canonical({'kind': 'worker-error', 'value': 'monitor message exceeds bound'}).encode()
    pending = memoryview(data + b'\n')
    while pending:
        count = os.write(channel, pending)
        if count <= 0:
            raise OSError('incomplete monitor pipe write')
        pending = pending[count:]


def _event_worker(channel, path, interval):
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    offset, pending, identity = 0, b'', None
    last_error = None
    while True:
        try:
            stat = path.stat()
            current = (stat.st_dev, stat.st_ino)
            if (identity is not None and identity != current) or stat.st_size < offset:
                raise ValueError('append-only stage event stream was replaced/truncated')
            identity = current
            with path.open('rb') as stream:
                stream.seek(offset)
                data = stream.read(65536)
            offset += len(data)
            pending += data
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                try:
                    if len(line) > MAX_EVENT_BYTES:
                        raise ValueError('stage event line exceeds bound')
                    event = json.loads(line)
                    _send(channel, 'event', event)
                except (UnicodeError, ValueError) as error:
                    _send(channel, 'event-error', str(error))
            if len(pending) > MAX_EVENT_BYTES:
                _send(channel, 'event-error', 'unterminated stage event line exceeds bound')
                return
            _send(channel, 'event-reader-heartbeat', time.monotonic())
            last_error = None
        except FileNotFoundError:
            # Startup absence is expected; absence after start does not reset it.
            if offset and last_error != 'missing':
                _send(channel, 'event-error', 'stage event stream disappeared')
                last_error = 'missing'
            _send(channel, 'event-reader-heartbeat', time.monotonic())
        except (OSError, ValueError) as error:
            message = str(error)
            if last_error != message:
                _send(channel, 'event-error', message)
                last_error = message
            _send(channel, 'event-reader-heartbeat', time.monotonic())
        time.sleep(interval)


def _resource_worker(channel, pid, limits, sampler, samples_path):
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        group = find_cgroup(pid)
    except (OSError, ValueError):
        group = None
    while True:
        try:
            sample = (sampler(pid, group) if sampler else
                      {'process_bytes': process_memory(pid), 'cgroup': cgroup_memory(group)})
            sample = {'monotonic_s': time.monotonic(), **sample}
            _send(channel, 'resource', sample)
            # Potentially blocking diagnostic writes stay outside the deadline
            # observer, just like /proc/cgroup reads and arbitrary samplers.
            with samples_path.open('a') as stream:
                stream.write(canonical(sample) + '\n')
        except (OSError, ValueError) as error:
            _send(channel, 'resource-error', repr(error))
        time.sleep(limits.interval_s)


class _PipeReader:
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.pending = b''

    def close(self):
        os.close(self.descriptor)


def _pipe_worker(target, receive, send, args):
    os.close(receive)
    try:
        target(send, *args)
    finally:
        os.close(send)


def _start_worker(target, args):
    receive, send = os.pipe()
    os.set_blocking(receive, False)
    worker = multiprocessing.get_context('fork').Process(
        target=_pipe_worker, args=(target, receive, send, args), daemon=True)
    worker.start()
    os.close(send)
    return worker, _PipeReader(receive)


def _stop_worker(worker, channel, grace):
    channel.close()
    # Only its own private group may be signalled; setsid may not yet have run.
    for number in (signal.SIGTERM, signal.SIGKILL):
        try:
            if os.getpgid(worker.pid) == worker.pid:
                os.killpg(worker.pid, number)
            else:
                os.kill(worker.pid, number)
        except ProcessLookupError:
            pass
        worker.join(timeout=grace)
        if not worker.is_alive():
            break


def _messages(channel):
    # Bound backlog work so event flooding cannot starve deadline checks.
    for _ in range(64):
        if b'\n' not in channel.pending:
            try:
                data = os.read(channel.descriptor, 65536)
            except BlockingIOError:
                return
            if not data:
                if channel.pending:
                    raise ValueError('truncated monitor pipe message')
                return
            channel.pending += data
            if b'\n' not in channel.pending:
                if len(channel.pending) > 60000:
                    raise ValueError('monitor pipe message exceeds bound')
                return
        line, channel.pending = channel.pending.split(b'\n', 1)
        if len(line) > 60000:
            raise ValueError('monitor pipe message exceeds bound')
        yield json.loads(line)


def _annotate_summary(output, report):
    path = output / 'summary.json'
    try:
        summary = json.loads(path.read_text())
    except (OSError, ValueError):
        summary = {}
    summary['guard'] = {'path': str(output / 'guard.json'), 'status': report['status']}
    if report['status'] != 'completed':
        summary.update(status=report['status'], next_action=report.get('next_action'),
                       termination=report.get('trigger'), valid_checkpoint=False)
    write_json_atomic(path, summary)


def run_guarded(command, output, *, run_id, engine, identity, reference=None,
                limits=SupervisorLimits(), sampler=None, require_passes=True, require_reference=True,
                window=F33):
    """Launch a private group; monitor workers cannot block deadline observation."""
    limits.validate()
    validate_identity(identity)
    if engine not in ('grh', 'gsim') or not isinstance(run_id, str) or not run_id:
        raise ValueError('guard requires an explicit engine and run_id')
    budgets = (validate_reference(reference, identity, window)
               if engine == 'grh' and require_passes and (require_reference or reference is not None) else {})
    if reference is not None and engine == 'gsim':
        raise ValueError('GSIM reference collection must not use GRH pass budgets')
    output = Path(output)
    guard_path, trigger_path = output / 'guard.json', output / 'guard-trigger.json'
    resources_path, events_path = output / 'resources.samples.jsonl', output / 'stage-events.jsonl'
    for path in (guard_path, trigger_path, resources_path, events_path):
        if path.exists():
            raise ValueError('refusing to overwrite guard/failure evidence: ' + str(path))
    output.mkdir(parents=True, exist_ok=True)
    report = {'schema': window.guard_schema, 'status': 'running', 'run_id': run_id, 'engine': engine,
              'reference_identity': identity, 'budgets_s': budgets, 'command': command,
              'limits': asdict(limits), 'started_at_ns': time.time_ns(), 'supervisor_pid': os.getpid(),
              'resource_scope': 'sampled process RSS and cgroup PSI; diagnostic, not a hard memory cap',
              'resource_interference': False, 'sample_count': 0, 'returncode': None}
    # Exclusive reservation prevents an accidental second writer even before spawn.
    with guard_path.open('x') as stream:
        stream.write(canonical(report) + '\n')
    resources_path.touch(exist_ok=False)
    tracker = PassDeadline(run_id, engine, budgets, identity['batch_count'], window=window)
    pressure = PressureDeadline(limits.resources)
    workers = []
    child = None
    trigger = None
    started = time.monotonic()
    idle_started = started
    last_resource = started
    last_reader = started
    resource_error = None
    pending_signal = []
    previous = {number: signal.signal(number, lambda signum, frame: pending_signal.append(signum))
                for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        child = subprocess.Popen(command, start_new_session=True)
        report['benchmark_pid'] = child.pid
        workers.append(_start_worker(_event_worker, (events_path, min(0.005, limits.poll_s))))
        workers.append(_start_worker(_resource_worker, (child.pid, limits.resources, sampler, resources_path)))
        report['monitor_pids'] = [worker.pid for worker, _ in workers]
        write_json_atomic(guard_path, report)
        with resources_path.open('r'):
            exit_observed = None
            while True:
                now = time.monotonic()
                # Drain immediately available events before the threshold check:
                # a reliable completed native duration equal to budget is valid.
                old_completed = len(tracker.completed)
                for message in _messages(workers[0][1]):
                    if message['kind'] == 'event':
                        tracker.consume(message['value'], now)
                    elif message['kind'] == 'event-reader-heartbeat':
                        last_reader = now
                    else:
                        tracker.errors.append({'error': message['value'], 'observed_monotonic_s': now})
                if len(tracker.completed) != old_completed:
                    idle_started = now
                code = child.poll()
                trigger = tracker.trigger if code is not None else tracker.observe(now)
                if trigger:
                    report.update(status='performance-blocked', next_action='optimize-pass')
                    break
                if code is not None:
                    if exit_observed is None:
                        exit_observed = now
                    # Permit the isolated reader to drain final bytes after exit.
                    if now - exit_observed >= 0.100:
                        if code:
                            trigger = {'kind': 'child-failed', 'returncode': code}
                        elif (tuple(tracker.completed) != (tracker.passes if require_passes else ()) or
                              tracker.active):
                            trigger = {'kind': 'incomplete-pass-events'}
                        elif tracker.errors:
                            trigger = {'kind': 'invalid-pass-events'}
                        else:
                            report['status'] = 'completed'
                        break
                if pending_signal:
                    trigger = {'kind': 'supervisor-signal', 'signal': pending_signal[0]}
                    break
                if now - started >= limits.overall_s:
                    trigger = {'kind': 'overall-timeout', 'limit_s': limits.overall_s}
                    break
                if tracker.active is None:
                    count = len(tracker.completed)
                    name, bound = (('prefix', limits.prefix_s) if not count else
                                   ('suffix', limits.suffix_s) if count == len(tracker.passes) else
                                   ('between-passes', limits.between_passes_s))
                    if now - idle_started >= bound:
                        trigger = {'kind': name + '-timeout', 'limit_s': bound}
                        break
                for message in _messages(workers[1][1]):
                    last_resource = now
                    if message['kind'] != 'resource':
                        if child.poll() is None:
                            if resource_error is None:
                                resource_error = (now, message['value'])
                        continue
                    sample = message['value']
                    resource_error = None
                    report.update(last_sample=sample, sample_count=report['sample_count'] + 1)
                    if sample['process_bytes']['VmRSS'] >= limits.resources.rss_bytes:
                        trigger = {'kind': 'rss-limit', 'rss_bytes': sample['process_bytes']['VmRSS']}
                    elif pressure.observe(sample, now):
                        trigger = {'kind': 'sustained-memory-pressure', **pressure.trigger}
                    if trigger:
                        report['resource_interference'] = True
                        break
                if trigger:
                    break
                if resource_error and now - resource_error[0] >= limits.resources.terminate_grace_s and code is None:
                    trigger = {'kind': 'resource-monitor-failed', 'error': resource_error[1]}
                    break
                if now - last_resource > limits.sampler_stall_s and code is None:
                    trigger = {'kind': 'resource-sampler-stalled', 'limit_s': limits.sampler_stall_s}
                    break
                if not workers[0][0].is_alive() and code is None:
                    trigger = {'kind': 'event-reader-failed'}
                    break
                if now - last_reader >= 0.200 and code is None:
                    trigger = {'kind': 'event-reader-stalled', 'limit_s': 0.200}
                    break
                # Adapt to tiny calibrated budgets; never add a minimum budget.
                delay = limits.poll_s
                if tracker.active and tracker.active['logical_instance'] in budgets:
                    delay = min(delay, budgets[tracker.active['logical_instance']] / 20)
                time.sleep(delay)
        if trigger is not None:
            if report['status'] == 'running':
                report['status'] = 'failed'
            last_boundary = (tracker.boundaries[trigger['logical_instance']]
                             if trigger.get('logical_instance') in tracker.boundaries else
                             window.boundary_prefix + str(len(tracker.completed)))
            trigger = {**trigger, 'requested_at_ns': time.time_ns(),
                       'termination_requested_monotonic_s': time.monotonic(),
                       'last_complete_boundary': last_boundary,
                       'partial_boundary_valid': False}
            report['trigger'] = trigger
            # Persist before the first signal, including when the child exited late.
            write_json_atomic(trigger_path, trigger)
            write_json_atomic(guard_path, report)
            report['signal_sent_monotonic_s'] = time.monotonic()
            terminate_child(child, limits.resources.terminate_grace_s)
        else:
            # Successful main processes can leave helpers alive in the same group.
            terminate_child(child, limits.resources.terminate_grace_s)
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        if child is not None:
            # Failure evidence also precedes cleanup signals on supervisor faults.
            if not trigger_path.exists():
                write_json_atomic(trigger_path, {'kind': 'supervisor-failed', 'error': repr(error),
                                                'requested_at_ns': time.time_ns()})
            terminate_child(child, limits.resources.terminate_grace_s)
        raise
    finally:
        for worker, channel in workers:
            _stop_worker(worker, channel, limits.resources.terminate_grace_s)
        for number, handler in previous.items():
            signal.signal(number, handler)
        report.update(returncode=child.returncode if child else None,
                      events=tracker.events, event_errors=tracker.errors,
                      pass_times_s={key: value['wall_s'] for key, value in tracker.completed.items()},
                      completed_passes=list(tracker.completed), finished_at_ns=time.time_ns(),
                      finished_monotonic_s=time.monotonic(), wall_s=time.monotonic() - started)
        write_json_atomic(guard_path, report)
        _annotate_summary(output, report)
    return 0 if report['status'] == 'completed' else 2
