"""Supervise the native GRH calls in a complete F35 trace capture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

from benchmark_f29_pass_trace import write_json_atomic
from capture_f32_pipeline import native_rows
from f33_guard import positive


EVENT_FD = 'F35_STAGE_EVENTS_FD'
EVENT_SCHEMA = 'wolvrix.f35.stage-event.v1'
REPORT_SCHEMA = 'wolvrix.f35.guard.v1'
MAX_EVENT_BYTES = 4096

# The entries follow the GRH order, which differs from the GSIM order.
# Some FUNC_TRACED_TIMER calls use a native timer label distinct from the
# inventory/trace boundary, including the first production DCE.
GSIM_CALLS = {
    'comb-loop-elim#0': ('DetectLoop', 'DetectLoop#0'),
    'split-static-array#0': ('SplitArray', 'SplitArray#0'),
    'dead-code-elim#0': ('RemoveDeadNodes', 'RemoveDeadNodes#0'),
    'expr-opt#0': ('ExprOpt', 'ExprOpt#0'),
    'used-bits#0': ('{g->usedBits()}', '{g->usedBits()}#0'),
    'split-nodes#0': ('{g->splitNodes()}', '{g->splitNodes()}#0'),
    'dead-code-elim#1': ('RemoveDeadNodes1', 'RemoveDeadNodes1#0'),
    'constant-analysis#0': ('ConstantAnalysis', 'ConstantAnalysis#0'),
    'dead-code-elim#2': ('RemoveDeadNodes2', 'RemoveDeadNodes#1'),
    'alias-analysis#0': ('AliasAnalysis', 'AliasAnalysis#0'),
    'pattern-detect#0': ('PatternDetect', 'PatternDetect#0'),
    'common-expr#0': ('CommonExpr', 'CommonExpr#0'),
    'dead-code-elim#3': ('RemoveDeadNodes3', 'RemoveDeadNodes#2'),
}
PASSES = ('xmr-resolve#0', 'hier-flatten#0', *GSIM_CALLS)
F36_PASSES = (*PASSES[:2], 'remove-singleton-state-axis#0', *PASSES[2:])
GSIM_TIMER_ORDER = (
    ('{strbuf = readFile(InputFileName, size, mapSize)}',
     '{strbuf = readFile(InputFileName, size, mapSize)}#0'),
    ('{globalRoot= parseFIR(strbuf)}', '{globalRoot= parseFIR(strbuf)}#0'),
    ('Init', 'Init#0'),
    GSIM_CALLS['split-static-array#0'],
    GSIM_CALLS['comb-loop-elim#0'],
    ('TopoSort', 'TopoSort#0'),
    ('InferAllWidth', 'InferAllWidth#0'),
    *(GSIM_CALLS[logical] for logical in PASSES[4:]),
)


def read_gsim_times(timing_path):
    """Validate the unique, complete timer for every frozen GSIM call."""
    rows = [row for row in native_rows(Path(timing_path), 'gsim') if row.get('scope') == 'pass']
    order = [(row.get('stage'), row.get('pass_instance')) for row in rows]
    if tuple(order) != GSIM_TIMER_ORDER or any(row.get('batch_count') != 1 for row in rows):
        raise ValueError('GSIM timings must cover a single production capture through the fourth DCE')
    return {key: positive(row['wall_s'], key[1] + ' reference') for key, row in zip(order, rows)}


def reference_budgets(timing_path, *, xmr_limit_s, flatten_limit_s):
    """Bind each GRH call to exactly one complete timer in the frozen run."""
    times = read_gsim_times(timing_path)
    return {
        PASSES[0]: positive(xmr_limit_s, 'xmr-resolve limit'),
        PASSES[1]: positive(flatten_limit_s, 'hier-flatten limit'),
        **{logical: positive(2 * times[key], logical + ' budget') for logical, key in GSIM_CALLS.items()},
    }


def stage_event_options(run_id, instance, last_boundary):
    """Use in the supervised child at the normal Session.run_pass entry."""
    return {'stage_event_fd': int(os.environ[EVENT_FD]), 'stage_event_run_id': run_id,
            'stage_event_instance': instance, 'stage_event_boundary': last_boundary}


class Passes:
    def __init__(self, run_id, budgets, passes=PASSES):
        self.run_id = run_id
        self.budgets = budgets
        self.passes = passes
        self.completed = {}
        self.active = None
        self.trigger = None
        self.last_timestamp = 0

    def consume(self, event, now):
        if (not isinstance(event, dict) or event.get('schema') != EVENT_SCHEMA or
                event.get('run_id') != self.run_id or not isinstance(event.get('input_boundary'), str) or
                not event['input_boundary']):
            raise ValueError('invalid GRH stage event identity')
        key = event.get('logical_instance')
        if not isinstance(key, str):
            raise ValueError('invalid GRH stage event pass instance')
        stamp = positive(event.get('monotonic_s'), 'event monotonic_s')
        if stamp > now or stamp < self.last_timestamp:
            raise ValueError('invalid GRH monotonic stage event timestamp')
        if event.get('event') == 'start':
            expected = self.passes[len(self.completed)] if len(self.completed) < len(self.passes) else None
            if self.active is not None or key not in self.budgets or key != expected:
                raise ValueError('unexpected GRH stage start: ' + repr(key))
            self.active = event
        elif event.get('event') == 'end':
            if (self.active is None or self.active['logical_instance'] != key or
                    self.active['input_boundary'] != event['input_boundary']):
                raise ValueError('GRH stage end does not match its start: ' + repr(key))
            duration = positive(event.get('wall_s'), 'native pass wall_s')
            started = self.active['monotonic_s']
            if duration > stamp - started + 1e-6:
                raise ValueError('native duration exceeds GRH stage event interval')
            if duration > self.budgets[key]:
                self.trigger = self.timeout('completed-pass-over-budget', now, native_wall_s=duration)
            else:
                self.completed[key] = duration
                self.active = None
        else:
            raise ValueError('unknown GRH stage event: ' + repr(event.get('event')))
        self.last_timestamp = stamp

    def remaining(self, now):
        if self.active is None:
            return None
        return self.active['monotonic_s'] + self.budgets[self.active['logical_instance']] - now

    def timeout(self, kind, now, **evidence):
        key = self.active['logical_instance']
        budget = self.budgets[key]
        started = self.active['monotonic_s']
        return {'kind': kind, 'logical_instance': key, 'last_complete_boundary': self.active['input_boundary'],
                'budget_s': budget, 'started_monotonic_s': started, 'deadline_monotonic_s': started + budget,
                'observed_monotonic_s': now, 'elapsed_s': now - started, **evidence}


def kill_group(child, trigger):
    trigger.update(signal=signal.SIGKILL.value, termination_monotonic_s=time.monotonic())
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        trigger['process_group_already_exited'] = True


def supervise(child, pipe, tracker, events, output, min_free_bytes):
    pending = b''
    shutdown = []
    next_disk_check = 0
    previous = {number: signal.signal(number, lambda signum, frame: shutdown.append(signum))
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        while True:
            if shutdown:
                return {'kind': 'supervisor-signal', 'received_signal': shutdown[0]}
            now = time.monotonic()
            if min_free_bytes and now >= next_disk_check:
                next_disk_check = now + 1
                free_bytes = shutil.disk_usage(output).free
                if free_bytes < min_free_bytes:
                    return {'kind': 'capture-disk-space', 'free_bytes': free_bytes,
                            'min_free_bytes': min_free_bytes}
            remaining = tracker.remaining(now)
            delay = 0.1 if remaining is None else max(0, min(0.1, remaining))
            ready, _, _ = select.select([pipe], [], [], delay)
            if ready:
                chunk = os.read(pipe, 65536)
                if not chunk:
                    code = child.poll()
                    if pending:
                        return {'kind': 'invalid-pass-events', 'error': 'truncated stage event'}
                    if len(tracker.completed) != len(tracker.passes):
                        return {'kind': 'incomplete-pass-events', 'returncode_at_eof': code}
                    while code is None and not shutdown:
                        try:
                            code = child.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            continue
                    if shutdown:
                        return {'kind': 'supervisor-signal', 'received_signal': shutdown[0]}
                    return {'kind': 'child-failed', 'returncode': code} if code else None
                records = (pending + chunk).split(b'\n')
                pending = records.pop()
                if len(pending) > MAX_EVENT_BYTES:
                    raise ValueError('unterminated GRH stage event exceeds pipe limit')
                for line in records:
                    if len(line) > MAX_EVENT_BYTES:
                        raise ValueError('GRH stage event exceeds pipe limit')
                    event = json.loads(line)
                    tracker.consume(event, time.monotonic())
                    events.write(json.dumps(event) + '\n')
                    if tracker.trigger:
                        return tracker.trigger
            now = time.monotonic()
            remaining = tracker.remaining(now)
            if remaining is not None and remaining <= 0:
                return tracker.timeout('running-pass-at-budget', now)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def run_guarded(command, output, *, run_id, budgets, env=None, min_free_bytes=0, passes=PASSES):
    """Kill only the child's private group. Persist evidence after signalling."""
    if not isinstance(run_id, str) or not run_id or set(budgets) != set(passes):
        raise ValueError('GRH supervisor requires a run ID and a budget for every pass')
    resolved = {key: positive(budgets[key], key + ' budget') for key in passes}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    guard_path = output / 'guard.json'
    trigger_path = output / 'guard-trigger.json'
    events_path = output / 'stage-events.jsonl'
    log_path = output / 'grh.log'
    if any(path.exists() for path in (trigger_path, events_path, log_path)):
        raise ValueError('refusing to overwrite GRH capture evidence in ' + str(output))
    report = {'schema': REPORT_SCHEMA, 'run_id': run_id, 'status': 'running', 'budgets_s': resolved,
              'started_at_ns': time.time_ns(), 'supervisor_pid': os.getpid()}
    with guard_path.open('x') as stream:
        json.dump(report, stream)
        stream.write('\n')
    tracker = Passes(run_id, resolved, passes=passes)
    receive, send = os.pipe()
    child = None
    trigger = None
    try:
        child_env = dict(os.environ if env is None else env)
        child_env[EVENT_FD] = str(send)
        with log_path.open('x') as logs, events_path.open('x', buffering=1) as events:
            try:
                child = subprocess.Popen(command, env=child_env, pass_fds=(send,), start_new_session=True,
                                         stdout=logs, stderr=subprocess.STDOUT)
            finally:
                os.close(send)
            report['child_pid'] = child.pid
            try:
                trigger = supervise(child, receive, tracker, events, output, min_free_bytes)
            except (OSError, ValueError) as error:
                trigger = {'kind': 'invalid-pass-events', 'error': str(error)}
            if trigger is not None:
                kill_group(child, trigger)
            child.wait()
    except BaseException as error:
        trigger = {'kind': 'supervisor-failed', 'error': repr(error)}
        if child is not None:
            kill_group(child, trigger)
            child.wait()
        raise
    finally:
        os.close(receive)
        if trigger is None:
            report['status'] = 'completed'
        else:
            performance = trigger['kind'] in ('running-pass-at-budget', 'completed-pass-over-budget')
            report.update(status='performance-blocked' if performance else 'failed', trigger=trigger)
            if performance:
                report['next_action'] = 'optimize-pass'
            write_json_atomic(trigger_path, trigger)
        report.update(pass_times_s=tracker.completed, returncode=child.returncode if child else None,
                      finished_at_ns=time.time_ns())
        write_json_atomic(guard_path, report)
    return 0 if trigger is None else 2
