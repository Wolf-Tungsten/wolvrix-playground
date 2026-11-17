"""Apply the F32 paired native-pass and whole-window performance gates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

from benchmark_f30_pipeline import (verified_dependencies, verify_loaded_native,
                                    verify_package_identity, verify_source_provenance)
from benchmark_xs_firrtl_ingest import request_from_manifest

ROOT = Path(__file__).resolve().parents[1]
GROUP_SCHEMA = 'wolvrix.f32.pass-benchmark-group.v1'
RESULT_SCHEMA = 'wolvrix.f32.pass-benchmark-results.v1'
SAMPLE_SCHEMA = 'wolvrix.f32.pass-benchmark.v1'
INPUT_SHA256 = 'b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b'
PASSES = ('expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
MINIMUM_PER_ENGINE = 3
JITTER_RELATIVE = 0.03
JITTER_ABSOLUTE_S = 0.010
GSIM_PREFIX = ('{strbuf = readFile(InputFileName, size, mapSize)}',
               '{globalRoot= parseFIR(strbuf)}', 'Init', 'SplitArray', 'DetectLoop',
               'TopoSort', 'InferAllWidth', 'RemoveDeadNodes')
OBSERVED_CONFIGURATION_KEYS = ('machine', 'cpu_model', 'thread_environment',
                               'loader_environment', 'profiling_environment', 'cpu_affinity')

EXPECTED = {
    'grh': {
        'expr-opt': ('expr-opt#0', 'expr-opt', 'expr-opt#0'),
        'used-bits': ('used-bits#0', 'used-bits', 'used-bits#0'),
        'split-nodes': ('split-nodes#0', 'split-nodes', 'split-nodes#0'),
        'dead-code-elim': ('dead-code-elim#1', 'dead-code-elim', 'dead-code-elim#0'),
    },
    'gsim': {
        'expr-opt': ('ExprOpt#0', 'ExprOpt', 'ExprOpt#0'),
        'used-bits': ('{g->usedBits()}#0', '{g->usedBits()}', '{g->usedBits()}#0'),
        'split-nodes': ('{g->splitNodes()}#0', '{g->splitNodes()}', '{g->splitNodes()}#0'),
        'dead-code-elim': ('RemoveDeadNodes1#0', 'RemoveDeadNodes1', 'RemoveDeadNodes1#0'),
    },
}


def digest(value, field):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError(f'{field}: expected SHA256')
    return value


def positive(value, field, *, allow_zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{field}: expected finite nonnegative seconds')
    if value == 0 and not allow_zero:
        raise ValueError(f'{field}: must be positive')
    return float(value)


def file_sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


class ArtifactSet:
    def __init__(self):
        self.records = {}
        self.identities = {}

    def check(self, path, expected):
        path = Path(path).resolve()
        expected = digest(expected, 'artifact digest')
        old = self.records.get(str(path))
        if old is not None:
            if old != expected or self.stat(path) != self.identities[str(path)]:
                raise ValueError(f'artifact changed during comparison: {path}')
            return path
        before = self.stat(path)
        actual = file_sha256(path)
        after = self.stat(path)
        if before != after:
            raise ValueError(f'artifact changed while hashing: {path}')
        if actual != expected:
            raise ValueError(f'artifact SHA256 mismatch: {path}')
        self.records[str(path)] = actual
        self.identities[str(path)] = after
        return path

    def watch_unpinned(self, path):
        path = Path(path).resolve()
        before = self.stat(path)
        actual = file_sha256(path)
        after = self.stat(path)
        if before != after:
            raise ValueError(f'artifact changed while hashing: {path}')
        old = self.records.get(str(path))
        if old is not None and old != actual:
            raise ValueError(f'artifact changed during comparison: {path}')
        self.records[str(path)] = actual
        self.identities[str(path)] = after
        return actual

    @staticmethod
    def stat(path):
        value = Path(path).stat()
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def recheck(self):
        for path, identity in self.identities.items():
            if self.stat(path) != identity:
                raise ValueError(f'artifact changed during comparison: {path}')


def load_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def verify_tool_identity(identity, artifacts):
    if (not isinstance(identity, dict) or identity.get('schema') != 'wolvrix.f32.benchmark-tools.v1' or
            not isinstance(identity.get('files'), list) or len(identity['files']) != 2):
        raise ValueError('invalid frozen runner/guard tool identity')
    paths = []
    for record in identity['files']:
        if not isinstance(record, dict) or not isinstance(record.get('path'), str):
            raise ValueError('invalid frozen tool path/hash record')
        path = Path(record['path'])
        if not path.is_absolute():
            raise ValueError('frozen tool path must be absolute')
        paths.append(artifacts.check(path, record.get('sha256')))
    if (len(set(paths)) != 2 or {path.name for path in paths} !=
            {'benchmark_f32_passes.py', 'f30_resource_guard.py'}):
        raise ValueError('frozen tool identity must pin distinct runner and guard files')


def frozen_group(path, artifacts):
    summary_path = Path(path).resolve()
    artifacts.watch_unpinned(summary_path)
    summary = load_json(summary_path)
    if not isinstance(summary, dict) or summary.get('schema') != RESULT_SCHEMA:
        raise ValueError('not an F32 benchmark group result summary')
    if summary.get('status') not in ('completed', 'completed-with-failures'):
        raise ValueError('benchmark group did not finish its planned schedule')
    group_id = summary.get('group_id')
    if not isinstance(group_id, str) or not group_id:
        raise ValueError('missing benchmark group ID')
    group_key = 'group_manifest' if isinstance(summary.get('group_manifest'), str) else 'manifest_file'
    if not isinstance(summary.get(group_key), str):
        raise ValueError('group summary lacks frozen manifest path')
    manifest_path = Path(summary[group_key]).resolve()
    manifest_hash = summary.get('manifest_sha256')
    if manifest_hash is None:
        manifest_hash = summary.get('group_manifest_sha256')
    artifacts.check(manifest_path, manifest_hash)
    manifest = load_json(manifest_path)
    if (not isinstance(manifest, dict) or manifest.get('schema') != GROUP_SCHEMA or
            manifest.get('group_id') != group_id):
        raise ValueError('frozen group manifest identity mismatch')
    manifest_body = dict(manifest)
    internal_hash = manifest_body.pop('manifest_sha256', None)
    actual_internal_hash = hashlib.sha256(json.dumps(
        manifest_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if internal_hash != actual_internal_hash:
        raise ValueError('frozen group canonical manifest hash mismatch')
    if 'tool_identity' in manifest:
        verify_tool_identity(manifest['tool_identity'], artifacts)
    created = manifest.get('created_at_ns')
    if type(created) is not int or created <= 0:
        raise ValueError('invalid group creation timestamp')
    if manifest.get('input_sha256') != INPUT_SHA256:
        raise ValueError('F32 performance group must use the frozen full SimTop FIRRTL input')
    actual_input = artifacts.check(manifest.get('input'), manifest.get('input_sha256'))
    source_manifest_path = manifest.get('source_manifest', manifest.get('manifest'))
    source_manifest_hash = manifest.get('source_manifest_sha256', manifest.get('manifest_sha256'))
    if actual_input.resolve() == Path(source_manifest_path).resolve():
        raise ValueError('FIRRTL input and source manifest paths must be distinct')
    artifacts.check(source_manifest_path, source_manifest_hash)
    request = request_from_manifest(Path(source_manifest_path))
    sources = manifest.get('sources')
    if not isinstance(sources, list) or len(sources) != len(request['sources']):
        raise ValueError('group source inventory differs from its original source manifest')
    for frozen, actual in zip(sources, request['sources']):
        if (not isinstance(frozen, dict) or frozen.get('path') != actual['path'] or
                frozen.get('language') != actual['language'] or frozen.get('unit') != actual.get('unit')):
            raise ValueError('group source inventory differs from its original source manifest')
        artifacts.check(frozen.get('path'), frozen.get('sha256'))
        if frozen.get('bytes') != Path(frozen['path']).stat().st_size:
            raise ValueError('group source size differs from frozen original input')
    if not any(source['path'] == str(actual_input) and source['language'] == 'firrtl' for source in sources):
        raise ValueError('full FIRRTL input is not in the original source manifest')
    repeats = manifest.get('repeats', manifest.get('measurement', {}).get('repeats_per_engine'))
    if type(repeats) is not int or repeats < MINIMUM_PER_ENGINE:
        raise ValueError('group has fewer than three planned samples per engine')
    schedule = manifest.get('schedule')
    expected_schedule = schedule
    if (not isinstance(schedule, list) or len(schedule) != repeats * 2 or
            any(engine not in ('grh', 'gsim') for engine in schedule) or
            schedule.count('grh') != repeats or schedule.count('gsim') != repeats):
        raise ValueError('frozen schedule must include the same number of GRH and GSIM samples')
    if any(left == right for left, right in zip(schedule, schedule[1:])):
        raise ValueError('frozen schedule must serially interleave GRH and GSIM samples')
    configuration = manifest.get('configuration')
    if not isinstance(configuration, dict):
        raise ValueError('missing frozen run configuration')
    if (not isinstance(configuration.get('machine'), list) or not configuration['machine'] or
            not isinstance(configuration.get('cpu_model'), str) or not configuration['cpu_model'] or
            not isinstance(configuration.get('loader_environment'), dict)):
        raise ValueError('frozen machine, CPU or loader configuration is missing')
    threads = configuration.get('thread_environment')
    if (not isinstance(threads, dict) or
            any(threads.get(key) != '1' for key in ('OMP_NUM_THREADS', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS'))):
        raise ValueError('frozen thread policy must match the single-worker production runner')
    if configuration.get('instrumentation') != {'trace': False, 'snapshot': False, 'export': False,
                                                'verify': False, 'profile': False, 'statistics': False}:
        raise ValueError('frozen configuration includes instrumentation or lacks explicit disabled settings')
    measurement = manifest.get('measurement', {})
    if (measurement.get('mode') != 'no-trace' or measurement.get('window_semantics') != '2state' or
            measurement.get('exports') is not False or measurement.get('verification') is not False or
            measurement.get('profile') is not False or measurement.get('build_type') != 'Release' or
            measurement.get('source') != 'raw-firrtl'):
        raise ValueError('group must freeze no-trace, no-export, no-verify, no-profile Release 2state measurement')
    profiling = configuration.get('profiling_environment')
    if not isinstance(profiling, dict) or any(value is not None for value in profiling.values()):
        raise ValueError('profiling/debug environment is enabled in a formal group')
    affinity = configuration.get('cpu_affinity')
    if (not isinstance(affinity, list) or not affinity or affinity != sorted(set(affinity)) or
            any(type(cpu) is not int or cpu < 0 for cpu in affinity)):
        raise ValueError('invalid frozen CPU affinity')
    if type(summary.get('started_at_ns')) is not int or type(summary.get('finished_at_ns')) is not int:
        raise ValueError('missing group execution timestamps')
    if summary['started_at_ns'] < created or summary['finished_at_ns'] < summary['started_at_ns']:
        raise ValueError('invalid group execution interval')
    rows = summary.get('samples')
    if not isinstance(rows, list) or len(rows) != len(expected_schedule):
        raise ValueError('group summary omits a scheduled sample')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('invalid scheduled sample row')
    if [row.get('engine') for row in rows] != expected_schedule:
        raise ValueError('result rows do not follow the frozen interleaved schedule')
    if [row.get('sequence') for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('sample schedule rows must have unique consecutive one-based sequence IDs')
    for field in ('directory', 'summary_file', 'guard_file'):
        paths = [str(Path(row[field]).resolve()) for row in rows]
        if len(set(paths)) != len(paths):
            raise ValueError('scheduled samples reuse an artifact path: ' + field)
    previous_finish = summary['started_at_ns']
    for row in rows:
        start, finish = row.get('started_at_ns'), row.get('finished_at_ns')
        if type(start) is not int or type(finish) is not int or start >= finish:
            raise ValueError('invalid scheduler execution interval')
        if start < previous_finish or finish > summary['finished_at_ns']:
            raise ValueError('scheduler intervals overlap or escape the group interval')
        previous_finish = finish
    artifacts.check(manifest.get('gsim_identity'), manifest.get('gsim_identity_sha256'))
    gsim_identity = load_json(manifest['gsim_identity'])
    if gsim_identity.get('sha256') != manifest.get('gsim_binary_sha256'):
        raise ValueError('frozen GSIM native identity does not match group manifest')
    artifacts.check(gsim_identity.get('binary'), gsim_identity.get('sha256'))
    verify_source_provenance(gsim_identity)
    artifacts.check(gsim_identity['source']['archive'], gsim_identity['source']['archive_sha256'])
    artifacts.check(gsim_identity['source_patch']['path'], gsim_identity['source_patch']['sha256'])
    for library in gsim_identity.get('libraries', []):
        artifacts.check(library['path'], library['sha256'])
    package = Path(manifest.get('package')).resolve()
    package_identity_path = package / 'identity.json'
    artifacts.check(package_identity_path, manifest.get('package_identity_sha256'))
    package_identity = verify_package_identity(package, package_identity_path)
    if package_identity.get('build', {}).get('CMAKE_BUILD_TYPE') != 'Release':
        raise ValueError('frozen GRH package is not a Release build')
    dependencies = verified_dependencies(package, package / 'dependencies.json', package_identity)
    if dependencies.get('content_sha256') != manifest.get('dependencies_content_sha256'):
        raise ValueError('frozen GRH dependency identity differs from the benchmark group')
    artifacts.check(package / 'dependencies.json', file_sha256(package / 'dependencies.json'))
    return summary_path, summary, manifest, configuration, rows


def timing_artifacts(sample, artifacts):
    files = sample.get('timing_files')
    if files is None:
        # GRH records a separate native file for each run_pass; GSIM writes one.
        window_passes = sample.get('window_passes')
        if not isinstance(window_passes, list) or len(window_passes) != len(PASSES):
            raise ValueError('missing logical pass timing artifacts')
        records = {}
        for item in [*sample.get('prefix', []), *window_passes]:
            record = {'path': item.get('timing_file') or sample.get('timing_file'),
                      'sha256': item.get('timing_sha256') or sample.get('timing_sha256')}
            if record['path'] is None:
                continue
            records[record['path']] = record
        if sample['engine'] == 'gsim' and sample.get('timing_file'):
            records[sample['timing_file']] = {'path': sample['timing_file'], 'sha256': sample.get('timing_sha256')}
        files = list(records.values())
    if not isinstance(files, list) or not files:
        raise ValueError('missing raw native timing files')
    rows = []
    paths = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('invalid timing file record')
        path = artifacts.check(item.get('path'), item.get('sha256'))
        if str(path) in paths:
            raise ValueError('duplicate native timing file')
        paths.add(str(path))
        parsed = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if item.get('rows') is not None and item.get('rows') != parsed:
            raise ValueError('timing summary differs from raw native timing file')
        for row in parsed:
            if (not isinstance(row, dict) or row.get('schema') != sample['engine'] + '-stage-timing.v1' or
                    row.get('clock') != 'steady_clock' or row.get('complete') is not True):
                raise ValueError('invalid/incomplete native timer row')
            positive(row.get('wall_s'), 'native timer', allow_zero=row.get('scope') == 'boundary')
            if row.get('scope') not in ('pass', 'window'):
                continue
            rows.append((str(path), row))
    return rows


def inspect_sample(row, engine, group_id, group_file_hash, manifest, configuration, artifacts):
    path = Path(row.get('summary_file')).resolve()
    artifacts.check(path, row.get('summary_sha256'))
    sample = load_json(path)
    if (not isinstance(sample, dict) or sample.get('schema') != SAMPLE_SCHEMA or
            sample.get('group_id') != group_id):
        raise ValueError('sample schema or group identity mismatch')
    if sample.get('engine') != engine or row.get('engine') != engine:
        raise ValueError('sample engine disagrees with schedule')
    if row.get('status') != 'passed' or sample.get('status') != 'passed':
        raise ValueError('failed, timed out or incomplete samples cannot be omitted')
    if sample.get('source') != 'raw-firrtl' or sample.get('input_sha256') != INPUT_SHA256:
        raise ValueError('sample is not from the full raw FIRRTL input')
    if sample.get('window_semantics') != '2state' or sample.get('stop_after_stage') != 'post-second-dead-code-elim':
        raise ValueError('sample semantics/stop boundary differs from F32 gate')
    if sample.get('configuration') != configuration:
        raise ValueError('sample configuration differs from frozen group')
    if sample.get('cpu_affinity') != configuration.get('cpu_affinity'):
        raise ValueError('sample CPU affinity differs from frozen group')
    observed_configuration_verified = 'tool_identity' in manifest
    if observed_configuration_verified:
        if sample.get('tool_identity') != manifest['tool_identity']:
            raise ValueError('sample runner/guard tool identity differs from frozen group')
        verify_tool_identity(sample['tool_identity'], artifacts)
        expected_observation = {key: configuration[key] for key in OBSERVED_CONFIGURATION_KEYS}
        for field in ('observed_configuration', 'observed_configuration_after'):
            if sample.get(field) != expected_observation:
                raise ValueError(field + ': actual child environment differs from frozen group')
        if sample['cpu_affinity'] != sample['observed_configuration']['cpu_affinity']:
            raise ValueError('sample CPU affinity differs from actual child observation')
    if Path(sample.get('group_manifest')).resolve() != Path(row['directory']).resolve().parents[1] / 'group.json':
        raise ValueError('sample does not belong to its group output directory')
    if engine == 'gsim':
        gsim_identity = load_json(manifest['gsim_identity'])
        if sample.get('native') != gsim_identity:
            raise ValueError('sample GSIM identity differs from frozen group binary/source identity')
        expected_command = [gsim_identity['binary'], '--dir', str(Path(row['directory']) / 'model'),
                            '--stop-after-stage=RemoveDeadNodes1',
                            '--timing-output=' + sample.get('timing_file', ''), manifest['input']]
        if sample.get('command') != expected_command:
            raise ValueError('GSIM command differs from the normal raw no-export P4 stop command')
    else:
        package = Path(manifest['package']).resolve()
        package_identity = verify_package_identity(package, package / 'identity.json')
        if sample.get('package_identity') != package_identity:
            raise ValueError('sample GRH package identity differs from frozen group')
        if sample.get('sources') != manifest.get('sources'):
            raise ValueError('GRH sample source inventory differs from frozen group')
        verify_loaded_native(package, package_identity, sample.get('native'))
    if sample.get('group_manifest_sha256') != group_file_hash:
        # Group hash in this schema is the bytes of group.json, distinct from
        # manifest_sha256 which is the canonical hash of its JSON body.
        raise ValueError('sample points to a different frozen run group')
    if sample.get('input') != manifest.get('input'):
        raise ValueError('sample input differs from frozen original FIRRTL')
    if sample.get('instrumentation') != {'trace': False, 'dump': False, 'verify': False,
                                         'profile': False, 'export': False}:
        raise ValueError('sample includes trace, dump/export, verification or profiling')
    for key in ('started_at_ns', 'finished_at_ns'):
        if type(sample.get(key)) is not int or sample[key] <= 0:
            raise ValueError('missing sample execution timestamps')
    if sample['finished_at_ns'] <= sample['started_at_ns']:
        raise ValueError('invalid sample execution interval')
    if sample['started_at_ns'] < manifest['created_at_ns']:
        raise ValueError('sample predates the frozen run group; prior samples are not eligible')
    if sample.get('returncode') != 0 or row.get('returncode') != 0:
        raise ValueError('sample or scheduler did not record a successful return code')
    if engine == 'gsim' and sample.get('native_returncode') != 0:
        raise ValueError('GSIM did not exit successfully')
    if sample.get('active_stage', {}).get('name') != 'complete' or sample.get('active_stage', {}).get('finished') is not True:
        raise ValueError('sample stopped before completing the P4 boundary')
    guard_path = Path(row.get('guard_file', '')).resolve()
    artifacts.check(guard_path, row.get('guard_sha256'))
    guard = load_json(guard_path)
    if (guard.get('schema') != 'wolvrix.f30.resource-guard.v1' or
            guard.get('status') != 'completed' or guard.get('returncode') != 0):
        raise ValueError('resource guard did not complete successfully')
    if guard.get('reason') != 'child_completed':
        raise ValueError('sample resource guard recorded a non-success termination reason')
    limits = manifest.get('limits', {})
    guard_limits = guard.get('limits', {})
    if (guard_limits.get('rss_bytes') != limits.get('rss_bytes') or
            guard_limits.get('psi_percent') != limits.get('psi_percent') or
            guard_limits.get('psi_seconds') != limits.get('psi_seconds') or
            guard_limits.get('interval_s') != limits.get('sample_interval_s')):
        raise ValueError('sample resource guard limits differ from frozen group')
    if guard.get('phase_timeouts_s', {}).get('split-nodes#0') != limits.get('split_nodes_timeout_s'):
        raise ValueError('sample SplitNodes timeout differs from frozen group')
    if row.get('started_at_ns', 0) > sample['started_at_ns']:
        raise ValueError('sample began before its scheduler launch')
    if row.get('finished_at_ns', 0) < sample['finished_at_ns']:
        raise ValueError('sample finished after the scheduler observed its exit')
    for field in ('system_before', 'system_after'):
        snapshot = row.get(field)
        load = snapshot.get('loadavg_1_5_15') if isinstance(snapshot, dict) else None
        if not isinstance(load, list) or len(load) != 3:
            raise ValueError('per-sample system load/memory snapshot is missing')
        for value in load:
            positive(value, 'system load', allow_zero=True)
        positive(snapshot.get('memory_bytes', {}).get('MemAvailable'), 'system available memory', allow_zero=True)
        if snapshot.get('cpu_affinity') != configuration.get('cpu_affinity'):
            raise ValueError('system snapshot CPU affinity differs from frozen group')
        captured = snapshot.get('captured_at_ns')
        if type(captured) is not int or captured < manifest['created_at_ns']:
            raise ValueError('system snapshot predates the frozen group')
        if field == 'system_before' and captured > sample['started_at_ns']:
            raise ValueError('before-load snapshot was taken after sample start')
        if field == 'system_after' and captured < sample['finished_at_ns']:
            raise ValueError('after-load snapshot was taken before sample end')
    artifacts.check(sample.get('input'), sample.get('input_sha256'))
    timing_rows = timing_artifacts(sample, artifacts)
    logical = sample.get('logical_window')
    if not isinstance(logical, list) or [item.get('logical_pass') for item in logical] != list(PASSES):
        raise ValueError('logical window must contain exactly four passes in F32 order')
    pass_records = sample.get('window_passes')
    if not isinstance(pass_records, list) or [item.get('pass') for item in pass_records] != list(PASSES):
        raise ValueError('per-pass runner records are missing or out of order')
    metrics = {}
    used_rows = set()
    for item, record, pass_name in zip(logical, pass_records, PASSES):
        logical_name, stage, instance = EXPECTED[engine][pass_name]
        if item.get('logical_occurrence') != PASSES.index(pass_name):
            raise ValueError(f'{engine} {pass_name}: logical pass identity mismatch')
        if record.get('logical_instance') != logical_name:
            raise ValueError(f'{engine} {pass_name}: logical/native occurrence mapping differs')
        timer = item.get('native_timer')
        if record.get('native_timer') != timer:
            raise ValueError(f'{pass_name}: logical timer differs from runner pass record')
        if not isinstance(timer, dict):
            raise ValueError(f'{pass_name}: missing native pass row')
        if (timer.get('scope') != 'pass' or timer.get('stage') != stage or
                timer.get('pass_instance') != instance or timer.get('complete') is not True):
            raise ValueError(f'{pass_name}: wrong native timer identity')
        matches = [(file, raw) for file, raw in timing_rows if raw.get('scope') == 'pass' and raw == timer]
        file_hint = record.get('timing_file') or sample.get('timing_file')
        if file_hint:
            matches = [(file, raw) for file, raw in matches if file == str(Path(file_hint).resolve())]
        if len(matches) != 1:
            raise ValueError(f'{pass_name}: timer is not uniquely bound to a raw native file row')
        row_key = matches[0][0], json.dumps(matches[0][1], sort_keys=True)
        if row_key in used_rows:
            raise ValueError('native timer row reused for more than one logical pass')
        used_rows.add(row_key)
        native_s = positive(timer.get('wall_s'), pass_name + ' native timer')
        metrics_summary = sample.get('metrics')
        measured_s = positive(metrics_summary.get(pass_name) if isinstance(metrics_summary, dict) else None,
                              pass_name + ' measured time')
        if abs(native_s - measured_s) > max(0.001, native_s * 0.0001):
            raise ValueError(f'{pass_name}: summary metric differs from native pass timer')
        metrics[pass_name] = measured_s
    window = sample.get('window')
    if not isinstance(window, dict):
        raise ValueError('missing defensible contiguous P0-to-P4 window timer')
    window_s = positive(window.get('wall_s'), 'whole window wall')
    if sample.get('metrics', {}).get('window') != window_s:
        raise ValueError('whole window summary metric differs from observed window wall')
    sample_s = positive(sample.get('wall_s'), 'whole sample wall')
    if sample_s < window_s:
        raise ValueError('P0-to-P4 window exceeds the entire raw-ingest sample')
    native_sum = sum(metrics.values())
    if abs(positive(window.get('native_pass_sum_s'), 'native pass sum') - native_sum) > max(0.001, native_sum * 0.0001):
        raise ValueError('window native pass sum does not match the four per-pass timers')
    overhead = positive(window.get('framework_overhead_s'), 'window framework overhead', allow_zero=True)
    if abs(window_s - native_sum - overhead) > max(0.010, window_s * 0.001):
        raise ValueError('window wall does not reconcile with native pass and framework overhead')
    if engine == 'gsim':
        native_window = [(file, timer) for file, timer in timing_rows
                         if timer.get('scope') == 'window' and timer.get('stage') == 'F32Window' and
                         timer.get('pass_instance') == 'F32Window#0']
        if len(native_window) != 1 or native_window[0][1].get('wall_s') != window_s:
            raise ValueError('GSIM whole window must match its native F32Window timer')
        if window.get('native_timer') != native_window[0][1]:
            raise ValueError('GSIM window summary differs from its raw native timer')
        if window.get('clock') != 'steady_clock':
            raise ValueError('GSIM window measurement must be native')
        prefix = sample.get('prefix')
        if (not isinstance(prefix, list) or [timer.get('stage') for timer in prefix] != list(GSIM_PREFIX) or
                any(timer.get('pass_instance') != stage + '#0' or timer.get('scope') != 'pass'
                    for timer, stage in zip(prefix, GSIM_PREFIX))):
            raise ValueError('GSIM sample lacks the exact normal raw prefix and first-DCE timer')
        expected_passes = prefix + [record['native_timer'] for record in pass_records]
    else:
        if window.get('clock') != 'steady_clock':
            raise ValueError('GRH window wall must be measured around the contiguous runner calls')
        prefix = sample.get('prefix')
        names = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array', 'dead-code-elim')
        if (not isinstance(prefix, list) or len(prefix) != 6 or prefix[0].get('stage') != 'ingest' or
                [item.get('pass') for item in prefix[1:]] != list(names)):
            raise ValueError('GRH sample lacks the normal raw-ingest prefix ending at first DCE')
        for item, name in zip(prefix[1:], names):
            timer = item.get('native_timer')
            if (not isinstance(timer, dict) or timer.get('stage') != name or
                    timer.get('pass_instance') != name + '#0' or item.get('logical_instance') != name + '#0' or
                    not any(raw == timer and file == str(Path(item['timing_file']).resolve()) for file, raw in timing_rows)):
                raise ValueError('GRH prefix is not bound to exact native first-DCE and predecessor timers')
        expected_passes = [item['native_timer'] for item in prefix[1:]] + [record['native_timer'] for record in pass_records]
        start, finish = sample.get('window_started_at_ns'), sample.get('window_finished_at_ns')
        if (type(start) is not int or type(finish) is not int or
                not sample['started_at_ns'] <= start < finish <= sample['finished_at_ns'] or
                window_s > (finish - start) / 1e9 + .010):
            raise ValueError('GRH window interval does not bracket its contiguous pass calls')
    if [raw for _, raw in timing_rows if raw.get('scope') == 'pass'] != expected_passes:
        raise ValueError('raw native pass sequence differs from normal prefix followed by exact P0-P4 window')
    for metric in (*PASSES, 'window'):
        value = window_s if metric == 'window' else metrics[metric]
        positive(value, metric)
    return {'path': str(path), 'sha256': row['summary_sha256'], 'engine': engine,
            'sequence': row.get('sequence'), 'started_at_ns': sample.get('started_at_ns'),
            'finished_at_ns': sample['finished_at_ns'], 'wall_s': positive(sample.get('wall_s'), 'sample wall'),
            'user_s': positive(sample.get('user_s'), 'sample user', allow_zero=True),
            'system_s': positive(sample.get('system_s'), 'sample system', allow_zero=True),
            'maxrss_kib': positive(sample.get('maxrss_kib'), 'sample RSS', allow_zero=True),
            'system_before': row.get('system_before'), 'system_after': row.get('system_after'),
            'guard_file': str(guard_path), 'guard_status': guard.get('status'),
            'prefix': prefix, 'window': window,
            'execution_evidence': {'tool_sources_verified': observed_configuration_verified,
                                   'child_observations_verified': observed_configuration_verified},
            **({key: sample[key] for key in ('tool_identity', 'observed_configuration',
                                             'observed_configuration_after')}
               if observed_configuration_verified else {}),
            'metrics': {**metrics, 'window': window_s}, 'sample': sample}


def jitter(values, median):
    spread = max(values) - min(values)
    allowance = max(abs(median) * JITTER_RELATIVE, JITTER_ABSOLUTE_S)
    return {'range_s': spread, 'minimum_s': min(values), 'maximum_s': max(values),
            'median_s': median, 'jitter_allowance_s': allowance,
            'unstable': spread > allowance}


def compare(group_path):
    artifacts = ArtifactSet()
    report = {'schema': 'wolvrix.f32.performance-comparison.v1', 'status': 'incomplete',
              'complete': False, 'passed': False, 'group_summary': str(Path(group_path).resolve()),
              'performance_only': True, 'semantic_acceptance': False,
              'minimum_samples_per_engine': MINIMUM_PER_ENGINE,
              'jitter_policy': {'relative': JITTER_RELATIVE, 'absolute_s': JITTER_ABSOLUTE_S,
                                'spread_over_allowance_is_unstable': True},
              'gate': 'median(GRH) <= median(GSIM) + max(0.03*median(GSIM),0.010s)',
              'sample_counts': {'grh': 0, 'gsim': 0},
              'samples': [], 'comparisons': [], 'errors': []}
    try:
        summary_path, summary, manifest, configuration, rows = frozen_group(group_path, artifacts)
        report.update(group_id=summary['group_id'], manifest=summary.get('group_manifest'),
                      manifest_sha256=manifest.get('manifest_sha256'), schedule=manifest.get('schedule'),
                      sample_counts={'grh': 0, 'gsim': 0})
        report['scheduler_results'] = summary
        report['execution_evidence'] = {
            'tool_identity_required': 'tool_identity' in manifest,
            'tool_identity': manifest.get('tool_identity'),
            'limitations': [] if 'tool_identity' in manifest else [
                'Historical group did not pin runner/guard tool sources or record actual child environment observations.']}
        group_samples = []
        if [row.get('sequence') for row in rows] != list(range(1, len(rows) + 1)):
            report['errors'].append('sample rows must retain every one-based schedule sequence')
        for row in rows:
            engine = row['engine']
            try:
                result = inspect_sample(row, engine, summary['group_id'],
                                        summary.get('group_manifest_sha256'), manifest, configuration, artifacts)
                group_samples.append(result)
                report['samples'].append({key: value for key, value in result.items() if key != 'sample'})
                report['sample_counts'][engine] += 1
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                report['errors'].append(f"sample sequence {row.get('sequence')}: {error}")
                rejected = {'engine': engine, 'sequence': row.get('sequence'),
                    'summary_file': row.get('summary_file'), 'accepted': False,
                    'status': row.get('status'), 'error': str(error), 'scheduler_row': row}
                for field, result_field in (('summary_file', 'raw_summary'), ('guard_file', 'raw_guard')):
                    try:
                        rejected[result_field] = load_json(row[field])
                    except (OSError, ValueError, TypeError, KeyError):
                        pass
                report['samples'].append(rejected)
        report['sample_counts'] = {engine: sum(s['engine'] == engine for s in group_samples)
                                   for engine in ('grh', 'gsim')}
        if any(count < MINIMUM_PER_ENGINE for count in report['sample_counts'].values()):
            report['errors'].append('fewer than three valid new samples for at least one engine')
        by_engine = {engine: [s for s in group_samples if s['engine'] == engine]
                     for engine in ('grh', 'gsim')}
        ordered = sorted(group_samples, key=lambda s: s['sequence'])
        if len({s['sequence'] for s in ordered}) != len(ordered):
            report['errors'].append('duplicate sample schedule sequence')
        for previous, current in zip(ordered, ordered[1:]):
            if current['started_at_ns'] < previous['finished_at_ns']:
                report['errors'].append('scheduled samples overlap')
            if current['started_at_ns'] <= previous['started_at_ns']:
                report['errors'].append('sample execution timestamps do not follow the frozen schedule')
        for sample in group_samples:
            if sample['started_at_ns'] < summary.get('started_at_ns', 0) or sample['finished_at_ns'] > summary.get('finished_at_ns', 2**63):
                report['errors'].append('sample timestamps escape the group execution interval')
        for engine, samples in by_engine.items():
            if any(sample['engine'] != engine for sample in samples):
                report['errors'].append('invalid engine grouping')
        group_manifest = load_json(report['manifest'])
        if group_manifest.get('input_sha256') != INPUT_SHA256:
            report['errors'].append('frozen input is not the full original SimTop FIRRTL')
        if group_samples:
            fixed = ('configuration', 'input_sha256', 'window_semantics')
            raw0 = group_samples[0]['sample']
            for sample in group_samples[1:]:
                raw = sample['sample']
                for key in fixed:
                    if raw.get(key) != raw0.get(key):
                        report['errors'].append(f'samples differ in frozen {key}; comparison group is incompatible')
                        break
            for engine, engine_samples in (('grh', by_engine['grh']), ('gsim', by_engine['gsim'])):
                if engine_samples:
                    first_engine = engine_samples[0]['sample']
                    for sample in engine_samples[1:]:
                        raw = sample['sample']
                        if any(raw.get(key) != first_engine.get(key)
                               for key in ('native', 'package_identity', 'identity_sha256')):
                            report['errors'].append(f'{engine} frozen native/package identity changed within sample group')
                        if any(raw.get(key) != first_engine.get(key)
                               for key in ('manifest_sha256', 'input_sha256', 'group_manifest_sha256')):
                            report['errors'].append(f'{engine} input/manifest identity changed within sample group')
        if not report['errors']:
            metrics = (*PASSES, 'window')
            all_rows = []
            for metric in metrics:
                grh = [sample['metrics'][metric] for sample in by_engine['grh']]
                gsim = [sample['metrics'][metric] for sample in by_engine['gsim']]
                grh_median, gsim_median = statistics.median(grh), statistics.median(gsim)
                allowance = max(gsim_median * JITTER_RELATIVE, JITTER_ABSOLUTE_S)
                limit = gsim_median + allowance
                grh_spread, gsim_spread = jitter(grh, grh_median), jitter(gsim, gsim_median)
                stable = not grh_spread['unstable'] and not gsim_spread['unstable']
                result = {'metric': metric, 'grh_samples_s': grh, 'gsim_samples_s': gsim,
                    'grh': grh_spread, 'gsim': gsim_spread, 'allowed_delta_s': allowance,
                    'limit_s': limit, 'delta_s': grh_median - gsim_median,
                    'ratio': grh_median / gsim_median, 'within_gate': grh_median <= limit,
                    'stable': stable, 'passed': grh_median <= limit and stable}
                all_rows.append(result)
            report['comparisons'] = all_rows
            report['complete'] = True
            report['passed'] = all(item['passed'] for item in all_rows)
            report['status'] = 'passed' if report['passed'] else 'regressed-or-unstable'
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        report['errors'].append(str(error))
    try:
        report['verified_artifacts'] = artifacts.records
        report['verified_artifact_count'] = len(artifacts.records)
        artifacts.recheck()
    except (OSError, ValueError) as error:
        report['errors'].append(str(error))
        report.update(complete=False, passed=False, status='incomplete')
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
        for row in report['comparisons']:
            writer.writerow({'metric': row['metric'], 'grh_median_s': row['grh']['median_s'],
                'gsim_median_s': row['gsim']['median_s'], 'delta_s': row['delta_s'],
                'ratio': row['ratio'], 'limit_s': row['limit_s'], 'within_gate': row['within_gate'],
                'stable': row['stable'], 'passed': row['passed']})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True,
                        help='completed group results.json from benchmark_f32_passes')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare(args.benchmark)
        write_report(report, args.output)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ('status', 'complete', 'passed', 'sample_counts', 'errors')},
                     indent=2), flush=True)
    return 0 if report['passed'] else 1 if report['complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
