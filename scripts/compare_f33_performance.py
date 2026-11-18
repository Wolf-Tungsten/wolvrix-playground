"""Apply the F33 native-pass and continuous-window performance gates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

from f33_guard import PASSES, PassDeadline

ROOT = Path(__file__).resolve().parents[1]
GROUP_SCHEMA = 'wolvrix.f33.performance-group.v1'
RESULT_SCHEMA = 'wolvrix.f33.performance-results.v1'
SAMPLE_SCHEMA = 'wolvrix.f33.performance-sample.v1'
METRICS = (*PASSES, 'window')
MINIMUM_PER_ENGINE = 3
JITTER_RELATIVE = 0.03
JITTER_ABSOLUTE_S = 0.010
EXPECTED = {
    'grh': {
        PASSES[0]: ('constant-analysis', 'constant-analysis#0'),
        PASSES[1]: ('dead-code-elim', 'dead-code-elim#0'),
    },
    'gsim': {
        PASSES[0]: ('ConstantAnalysis', 'ConstantAnalysis#0'),
        PASSES[1]: ('RemoveDeadNodes2', 'RemoveDeadNodes#1'),
    },
}


def positive(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(field + ' must be finite and positive')
    return float(value)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


class Artifacts:
    def __init__(self):
        self.records = {}
        self.stats = {}

    @staticmethod
    def stat(path):
        value = Path(path).stat()
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns

    def check(self, path, expected):
        if not isinstance(path, str) or not path:
            raise ValueError('artifact path is missing')
        if (not isinstance(expected, str) or len(expected) != 64 or
                any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('artifact SHA256 is invalid')
        resolved = Path(path).resolve()
        key = str(resolved)
        before = self.stat(resolved)
        actual = self.records.get(key)
        if actual is None:
            actual = sha256(resolved)
            after = self.stat(resolved)
            if before != after:
                raise ValueError('artifact changed while hashing: ' + key)
            self.records[key] = actual
            self.stats[key] = after
        elif before != self.stats[key]:
            raise ValueError('artifact changed during comparison: ' + key)
        if actual != expected:
            raise ValueError('artifact SHA256 mismatch: ' + key)
        return resolved

    def recheck(self):
        for path, identity in self.stats.items():
            if self.stat(path) != identity:
                raise ValueError('artifact changed during comparison: ' + path)


def verify_timing_files(sample, engine, artifacts):
    files = sample.get('timing_files')
    if not isinstance(files, list) or not files:
        raise ValueError('sample lacks raw native timing files')
    rows = []
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('invalid native timing file record')
        path = artifacts.check(item.get('path'), item.get('sha256'))
        if path in seen:
            raise ValueError('duplicate native timing file')
        seen.add(path)
        parsed = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if item.get('rows') is not None and item['rows'] != parsed:
            raise ValueError('sample timer rows differ from raw timer file: ' + str(path))
        for row in parsed:
            if (not isinstance(row, dict) or row.get('schema') != engine + '-stage-timing.v1' or
                    row.get('clock') != 'steady_clock' or row.get('complete') is not True or
                    row.get('scope') not in ('pass', 'window', 'boundary')):
                raise ValueError('invalid native timer row for ' + engine)
            duration = row.get('wall_s')
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                raise ValueError('invalid native timer duration')
            rows.append(row)

    times = sample.get('pass_times_s')
    if not isinstance(times, dict) or set(times) != set(PASSES):
        raise ValueError('sample must record exactly the two F33 pass times')
    for logical, (stage, instance) in EXPECTED[engine].items():
        matches = [row for row in rows if row.get('scope') == 'pass' and row.get('stage') == stage and
                   row.get('pass_instance') == instance]
        if len(matches) != 1:
            raise ValueError('missing or ambiguous native pass timer: ' + logical)
        recorded = positive(times[logical], logical)
        if matches[0]['wall_s'] != recorded:
            raise ValueError('summary pass time differs from native timer: ' + logical)
    windows = [row for row in rows if row.get('scope') == 'window']
    window_time = positive(sample.get('window_s'), 'window_s')
    window = sample.get('window', {})
    if window.get('wall_s') != window_time or window.get('clock') != 'steady_clock':
        raise ValueError('summary window time differs from its recorded monotonic interval')
    native_sum = sum(times.values())
    if window_time < native_sum:
        raise ValueError('continuous window is shorter than its two native passes')
    if engine == 'gsim':
        if (len(windows) != 1 or windows[0].get('stage') != 'F33Window' or
                windows[0].get('pass_instance') != 'F33Window#0' or
                windows[0]['wall_s'] != window_time or
                window.get('native_timer') != windows[0] or window.get('source') != 'native'):
            raise ValueError('missing or mismatched native GSIM F33Window timer')
    elif (windows or window.get('source') != 'runner-monotonic' or
          window.get('native_pass_sum_s') != native_sum or
          window.get('framework_overhead_s') != window_time - native_sum):
        raise ValueError('invalid GRH runner-monotonic window evidence')
    return {**times, 'window': window_time}


def verify_events(sample, guard, artifacts):
    path = artifacts.check(sample.get('event_file'), sample.get('event_sha256'))
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    tracker = PassDeadline(sample['run_id'], sample['engine'], {})
    for event in events:
        # Replay historical timestamps independently of the current host's uptime.
        tracker.consume(event, math.inf)
    guarded_times = sample.get('guard_pass_times_s', sample['pass_times_s'])
    if (tracker.errors or tracker.active or tuple(tracker.completed) != PASSES or
            events != guard.get('events') or guard.get('event_errors') != [] or
            guarded_times != guard.get('pass_times_s') or guarded_times !=
            {key: event['wall_s'] for key, event in tracker.completed.items()}):
        raise ValueError('guard times differ from complete F33 stage events')
    span = events[-1]['monotonic_s'] - events[0]['monotonic_s']
    if not sum(guarded_times.values()) <= sample['window_s'] <= span + 0.001:
        raise ValueError('continuous window falls outside its guarded pass intervals')


def inspect_group(summary_path):
    artifacts = Artifacts()
    summary_path = Path(summary_path).resolve()
    artifacts.check(str(summary_path), sha256(summary_path))
    summary = load_json(summary_path)
    if not isinstance(summary, dict) or summary.get('schema') != RESULT_SCHEMA:
        raise ValueError('not an F33 performance group result summary')
    if summary.get('status') != 'completed':
        raise ValueError('formal performance group did not complete every scheduled sample')
    group_id = summary.get('group_id')
    if not isinstance(group_id, str) or not group_id:
        raise ValueError('missing performance group ID')
    manifest_path = summary.get('group_manifest')
    manifest_hash = summary.get('group_manifest_sha256')
    manifest_path = artifacts.check(manifest_path, manifest_hash)
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get('schema') != GROUP_SCHEMA:
        raise ValueError('invalid frozen F33 performance group manifest')
    if manifest.get('group_id') != group_id:
        raise ValueError('group summary and frozen manifest IDs differ')
    manifest_body = dict(manifest)
    frozen_hash = manifest_body.pop('manifest_sha256', None)
    actual_hash = hashlib.sha256(json.dumps(
        manifest_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if frozen_hash != actual_hash:
        raise ValueError('frozen F33 group manifest hash mismatch')

    repeats = manifest.get('repeats_per_engine')
    schedule = manifest.get('schedule')
    if type(repeats) is not int or repeats < MINIMUM_PER_ENGINE:
        raise ValueError('F33 formal performance requires at least three samples per engine')
    if (not isinstance(schedule, list) or len(schedule) != repeats * 2 or
            schedule.count('grh') != repeats or schedule.count('gsim') != repeats or
            any(left == right for left, right in zip(schedule, schedule[1:]))):
        raise ValueError('frozen schedule must interleave equal GRH and GSIM sample counts')
    if manifest.get('measurement') != {
            'mode': 'no-trace', 'window_semantics': '2state', 'source': 'raw-firrtl',
            'exports': False, 'verification': False, 'profile': False, 'build_type': 'Release'}:
        raise ValueError('F33 performance measurement must be no-trace, no-export Release 2state')
    identity = manifest.get('identity')
    configuration = manifest.get('configuration')
    input_sha256 = manifest.get('input_sha256')
    if not isinstance(identity, dict) or not identity:
        raise ValueError('missing frozen paired implementation identity')
    if (not isinstance(configuration, dict) or not configuration or
            not isinstance(configuration.get('cpu_affinity'), list) or not configuration['cpu_affinity']):
        raise ValueError('missing frozen run configuration or CPU affinity')
    artifacts.check(manifest.get('input'), input_sha256)
    artifacts.check(manifest.get('source_manifest'), manifest.get('source_manifest_sha256'))
    if manifest.get('package_identity_sha256') is None or manifest.get('gsim_binary_sha256') is None:
        raise ValueError('group must pin one GRH package and GSIM binary')

    samples = summary.get('samples')
    if not isinstance(samples, list) or len(samples) != len(schedule):
        raise ValueError('result summary omits scheduled sample records')
    if [row.get('engine') for row in samples] != schedule:
        raise ValueError('sample rows differ from the frozen interleaved schedule')
    if [row.get('sequence') for row in samples] != list(range(1, len(schedule) + 1)):
        raise ValueError('sample rows lack consecutive sequence numbers')
    if type(summary.get('finished_at_ns')) is not int:
        raise ValueError('missing group finish timestamp')

    all_samples = []
    by_engine = {'grh': [], 'gsim': []}
    previous_finish = summary.get('started_at_ns', 0)
    if type(previous_finish) is not int or previous_finish <= 0:
        raise ValueError('missing group start timestamp')
    run_ids = set()
    for row in samples:
        if row.get('status') != 'passed':
            raise ValueError('failed, guarded, or incomplete scheduled sample cannot be omitted')
        started, finished = row.get('started_at_ns'), row.get('finished_at_ns')
        if type(started) is not int or type(finished) is not int or started >= finished or started < previous_finish:
            raise ValueError('sample timestamps overlap or differ from serial schedule')
        if finished > summary['finished_at_ns']:
            raise ValueError('sample timestamps escape the group interval')
        previous_finish = finished
        sample_path = artifacts.check(row.get('summary_file'), row.get('summary_sha256'))
        sample = load_json(sample_path)
        engine = row['engine']
        if (sample.get('schema') != SAMPLE_SCHEMA or sample.get('status') != 'passed' or
                sample.get('engine') != engine or sample.get('group_id') != group_id):
            raise ValueError('sample summary schema/status/engine/group mismatch')
        if sample.get('input_sha256') != input_sha256 or sample.get('identity') != identity:
            raise ValueError('sample input or frozen implementation identity differs from group')
        if sample.get('configuration') != configuration:
            raise ValueError('sample configuration differs from frozen group')
        run_id = sample.get('run_id')
        if not isinstance(run_id, str) or not run_id or run_id in run_ids:
            raise ValueError('sample run IDs must be nonempty and unique')
        run_ids.add(run_id)
        if sample.get('resource_interference') is not False:
            raise ValueError('resource-interfered sample cannot enter formal comparison')
        if row.get('run_id') != run_id or row.get('started_at_ns') != sample.get('started_at_ns') or \
                row.get('finished_at_ns') != sample.get('finished_at_ns'):
            raise ValueError('scheduler row and sample summary timing identity differs')
        guard_path = artifacts.check(row.get('guard_file'), row.get('guard_sha256'))
        guard = load_json(guard_path)
        if (guard.get('schema') != 'wolvrix.f33.guard.v1' or
                guard.get('status') != 'completed' or guard.get('resource_interference') is not False or
                guard.get('run_id') != run_id or guard.get('engine') != engine or
                guard.get('reference_identity') != identity or guard.get('returncode') != 0):
            raise ValueError('sample guard did not complete cleanly')
        metrics = verify_timing_files(sample, engine, artifacts)
        verify_events(sample, guard, artifacts)
        if sample.get('metrics') != metrics:
            raise ValueError('sample metrics differ from validated native timers')
        normalized = {'engine': engine, 'run_id': run_id, 'metrics': metrics,
                      'summary_file': str(sample_path), 'guard_file': str(guard_path)}
        all_samples.append(normalized)
        by_engine[engine].append(normalized)
    if any(len(by_engine[engine]) < MINIMUM_PER_ENGINE for engine in by_engine):
        raise ValueError('at least three completed samples per engine are required')
    artifacts.recheck()
    return {'schema': 'wolvrix.f33.performance-comparison.v1', 'status': 'incomplete',
            'complete': False, 'passed': False, 'performance_only': True,
            'semantic_acceptance': False, 'performance_acceptance': False,
            'group_id': group_id, 'group_manifest': str(manifest_path),
            'group_manifest_sha256': manifest_hash, 'input_sha256': input_sha256,
            'identity': identity, 'configuration': configuration,
            'schedule': schedule, 'sample_counts': {engine: len(by_engine[engine]) for engine in by_engine},
            'samples': all_samples, 'metrics': []}, by_engine, artifacts


def jitter(values, median):
    allowance = max(abs(median) * JITTER_RELATIVE, JITTER_ABSOLUTE_S)
    spread = max(abs(value - median) for value in values)
    return {'median_s': median, 'jitter_allowance_s': allowance,
            'max_abs_deviation_s': spread, 'stable': spread <= allowance}


def compare(path):
    report, by_engine, artifacts = inspect_group(path)
    results = []
    for metric in METRICS:
        grh = [sample['metrics'][metric] for sample in by_engine['grh']]
        gsim = [sample['metrics'][metric] for sample in by_engine['gsim']]
        grh_median, gsim_median = statistics.median(grh), statistics.median(gsim)
        allowance = max(gsim_median * JITTER_RELATIVE, JITTER_ABSOLUTE_S)
        limit = gsim_median + allowance
        grh_spread, gsim_spread = jitter(grh, grh_median), jitter(gsim, gsim_median)
        stable = grh_spread['stable'] and gsim_spread['stable']
        results.append({'metric': metric, 'grh_samples_s': grh, 'gsim_samples_s': gsim,
                        'grh': grh_spread, 'gsim': gsim_spread,
                        'allowed_delta_s': allowance, 'limit_s': limit,
                        'delta_s': grh_median - gsim_median,
                        'ratio': grh_median / gsim_median,
                        'within_gate': grh_median <= limit,
                        'stable': stable, 'passed': grh_median <= limit and stable})
    report.update(metrics=results, complete=True,
                  passed=all(row['passed'] for row in results),
                  status='passed' if all(row['passed'] for row in results) else 'regressed-or-unstable',
                  performance_acceptance=all(row['passed'] for row in results),
                  verified_artifacts=artifacts.records,
                  verified_artifact_count=len(artifacts.records))
    artifacts.recheck()
    return report


def write_report(report, output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('report output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    with (output / 'comparisons.tsv').open('w', encoding='utf-8', newline='') as stream:
        fields = ('metric', 'grh_median_s', 'gsim_median_s', 'delta_s', 'ratio', 'limit_s',
                  'within_gate', 'stable', 'passed')
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in report['metrics']:
            writer.writerow({'metric': row['metric'], 'grh_median_s': row['grh']['median_s'],
                'gsim_median_s': row['gsim']['median_s'], 'delta_s': row['delta_s'],
                'ratio': row['ratio'], 'limit_s': row['limit_s'], 'within_gate': row['within_gate'],
                'stable': row['stable'], 'passed': row['passed']})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare(args.benchmark)
        write_report(report, args.output)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in
                      ('status', 'complete', 'passed', 'sample_counts', 'metrics')}, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
