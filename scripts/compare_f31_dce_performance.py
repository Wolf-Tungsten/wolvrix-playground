"""Validate raw first-DCE samples and apply F31's production-path performance gate.

GRH no-trace must match GSIM across three samples. Trace is diagnostic-only and
must complete within the existing 2x-GSIM watchdog bound.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import time

from benchmark_f29_pass_trace import sha256, write_json_atomic
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
    verify_loaded_native, verify_package_identity, verify_source_provenance)
from compare_f30_performance import canonical, digest, number, text

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f31.dce-performance-comparison.v1'
INPUT_SCHEMA = 'wolvrix.f31.dce-benchmark.v1'
EXPECTED_INPUT_SHA256 = 'b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b'
JITTER_RELATIVE = 0.03
JITTER_ABSOLUTE_S = 0.010
GROUPS = ('gsim', 'grh_no_trace', 'grh_trace')
MINIMUM_SAMPLES = {'gsim': 3, 'grh_no_trace': 3, 'grh_trace': 1}


class Artifacts:
    """Hash shared immutable inputs once; reject mutation before publication."""
    def __init__(self):
        self.files = {}

    @staticmethod
    def stat(path):
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def watch(self, path, expected=None):
        path = Path(text(str(path), 'artifact path')).resolve()
        key, identity = str(path), self.stat(path)
        previous = self.files.get(key)
        if previous is None:
            actual = sha256(path)
            if self.stat(path) != identity:
                raise ValueError('artifact changed while hashing: ' + key)
            previous = self.files[key] = {'sha256': actual, 'identity': identity}
        elif identity != previous['identity']:
            raise ValueError('artifact changed during comparison: ' + key)
        if expected is not None and digest(expected, 'artifact SHA256') != previous['sha256']:
            raise ValueError('artifact hash mismatch: ' + key)
        return previous['sha256']

    def check(self):
        for path, item in self.files.items():
            if self.stat(Path(path)) != item['identity']:
                raise ValueError('artifact changed during comparison: ' + path)


def timing_rows(value, engine, artifacts):
    path = Path(text(value.get('timing_file'), 'native timing file'))
    artifacts.watch(path, digest(value.get('timing_sha256'), 'native timing SHA256'))
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        raise ValueError('empty native timing evidence')
    parsed = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get('schema') != engine + '-stage-timing.v1' or
                row.get('clock') != 'steady_clock' or row.get('complete') is not True):
            raise ValueError('incomplete or invalid native timing row')
        number(row.get('wall_s'), 'native stage wall_s')
        if row.get('scope') not in ('pass', 'boundary'):
            raise ValueError('unknown native timing scope')
        if row['scope'] != 'pass':
            continue
        key = text(row.get('pass_instance'), 'native pass instance')
        if key in parsed:
            raise ValueError('duplicate native pass instance')
        parsed[key] = row
    if (rows if engine == 'grh' else parsed) != value.get('native_timers'):
        raise ValueError('summary native timers differ from raw timing evidence')
    instance, stage = (('dead-code-elim#0', 'dead-code-elim') if engine == 'grh'
                       else ('RemoveDeadNodes#0', 'RemoveDeadNodes'))
    if instance not in parsed or parsed[instance]['stage'] != stage:
        raise ValueError('missing first native DCE timer or wrong DCE instance')
    if engine == 'grh' and len(rows) != 1:
        raise ValueError('GRH native timer must cover precisely the first independent DCE')
    return parsed


def machine_context(value):
    config = value.get('configuration')
    if not isinstance(config, dict):
        raise ValueError('missing machine configuration')
    if not isinstance(config.get('machine'), list) or not config['machine']:
        raise ValueError('invalid machine identity')
    text(config.get('cpu_model'), 'CPU model')
    if not isinstance(config.get('thread_environment'), dict):
        raise ValueError('missing thread environment')
    affinity = config.get('cpu_affinity')
    if (not isinstance(affinity, list) or not affinity or
            any(type(cpu) is not int or cpu < 0 for cpu in affinity) or affinity != sorted(set(affinity))):
        raise ValueError('invalid CPU affinity')
    instrumentation = config.get('instrumentation', {})
    if not isinstance(instrumentation, dict):
        raise ValueError('invalid instrumentation configuration')
    for key, enabled in instrumentation.items():
        if key in ('verify', 'statistics', 'profile', 'profile_flatten', 'profile_split') and enabled is not False:
            raise ValueError('diagnostic instrumentation cannot enter the formal performance gate')
    profiling = config.get('profiling_environment', {})
    if not isinstance(profiling, dict) or any(value is not None for value in profiling.values()):
        raise ValueError('profiling/debug environment cannot enter the formal performance gate')
    return {**{key: config[key] for key in ('machine', 'cpu_model', 'thread_environment', 'cpu_affinity')},
            'loader_environment': config.get('loader_environment', {})}


def source_artifacts(identity, artifacts):
    verify_source_provenance(identity)
    source = identity['source']
    artifacts.watch(source['archive'], source['archive_sha256'])
    if source.get('mode') == 'archived-baseline':
        artifacts.watch(source['patch'], source['patch_sha256'])
        artifacts.watch(source['head_file'])
    if 'dependencies' in source:
        artifacts.watch(source['dependencies']['path'], source['dependencies']['sha256'])


def inspect_gsim(value, artifacts):
    if type(value.get('returncode')) is not int or value['returncode'] != 0:
        raise ValueError('GSIM did not exit successfully')
    native = value.get('native')
    if not isinstance(native, dict) or native.get('schema') != 'wolvrix.f30.gsim-native.v1':
        raise ValueError('missing GSIM frozen native identity')
    identity_path = Path(text(value.get('identity_file'), 'GSIM identity file'))
    artifacts.watch(identity_path, digest(value.get('identity_sha256'), 'GSIM identity SHA256'))
    if json.loads(identity_path.read_text(encoding='utf-8')) != native:
        raise ValueError('GSIM native identity differs from frozen identity file')
    artifacts.watch(native['binary'], native['sha256'])
    source_artifacts(native, artifacts)
    artifacts.watch(native['source_patch']['path'], native['source_patch']['sha256'])
    for library in native.get('libraries', []):
        artifacts.watch(library['path'], library['sha256'])
    command = value.get('command')
    if (not isinstance(command, list) or len(command) != 6 or
            command[:2] != [native['binary'], '--dir'] or
            command[3:] != ['--stop-after-stage=RemoveDeadNodes0',
                '--timing-output=' + value['timing_file'], value['input']]):
        raise ValueError('GSIM reference command is not untraced raw first-DCE execution')
    return {key: native[key] for key in ('sha256', 'source_revision', 'build_configuration_files', 'libraries')}


def inspect_grh(value, artifacts):
    recorded = value.get('package_identity')
    if not isinstance(recorded, dict):
        raise ValueError('missing GRH frozen package identity')
    package = Path(text(recorded.get('package'), 'GRH frozen package')).resolve()
    identity_path = package / 'identity.json'
    if Path(text(value.get('identity_file'), 'GRH identity file')).resolve() != identity_path:
        raise ValueError('GRH recorded identity file is not the actual frozen package identity')
    artifacts.watch(identity_path, digest(value.get('identity_sha256'), 'GRH identity SHA256'))
    identity = verify_package_identity(package, identity_path)
    if recorded != identity:
        raise ValueError('GRH package identity differs from actual frozen package')
    verify_loaded_native(package, identity, value.get('native'))
    source_artifacts(identity, artifacts)
    artifacts.watch(identity['build_cache']['path'], identity['build_cache']['sha256'])
    for library in identity['libraries']:
        artifacts.watch(package / library['path'], library['sha256'])
    dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
    if value.get('dependencies') != dependencies:
        raise ValueError('GRH dependency provenance differs from frozen sidecar')
    artifacts.watch(package / 'dependencies.json', dependencies['sha256'])
    sidecar = json.loads((package / 'dependencies.json').read_text(encoding='utf-8'))
    artifacts.watch(sidecar['archive'], sidecar['archive_sha256'])
    manifest = Path(text(value.get('manifest'), 'actual ingest manifest'))
    artifacts.watch(manifest, digest(value.get('manifest_sha256'), 'ingest manifest SHA256'))
    _, sources = verified_input_request(Path(value['input']), manifest)
    if value.get('sources') != sources:
        raise ValueError('GRH actual source request differs from recorded source identities')
    for entry in sources:
        artifacts.watch(entry['path'], entry['sha256'])
    prefix = value.get('prefix', {})
    if not isinstance(prefix, dict):
        raise ValueError('invalid raw-ingest prefix evidence')
    if [row.get('stage') for row in prefix.get('stages', [])] != ['ingest', 'xmr-resolve', 'hier-flatten']:
        raise ValueError('GRH did not record the normal raw-ingest prefix')
    for row in prefix['stages']:
        number(row.get('wall_s'), 'raw-ingest prefix stage wall_s')
    comb_split = prefix.get('comb_split', {})
    if (not isinstance(comb_split, dict) or comb_split.get('status') != 'passed' or comb_split.get('trace') is not False or
            comb_split.get('skip_comb') is not False or
            [row.get('pass') for row in comb_split.get('passes', [])] != ['comb-loop-elim', 'split-static-array']):
        raise ValueError('GRH did not complete the untraced normal comb/split prefix')
    for row in comb_split['passes']:
        if row.get('status') != 'passed' or row.get('pass_returned') is not True:
            raise ValueError('GRH prefix pass failed or did not return')
    return {'package': str(package), 'identity_sha256': artifacts.watch(identity_path),
            'build': identity['build'], 'source_revision': identity['source_revision'],
            'dependencies': dependencies['content_sha256'], 'sources': sources,
            'manifest_sha256': value['manifest_sha256']}


def inspect_sample(path, engine, mode, artifacts):
    path = Path(path).resolve()
    summary_digest = artifacts.watch(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    canonical(value)
    if not isinstance(value, dict) or value.get('schema') != INPUT_SCHEMA:
        raise ValueError('not an F31 raw first-DCE sample')
    if value.get('status') != 'passed':
        raise ValueError('failed or incomplete samples cannot be dropped')
    if value.get('engine') != engine or value.get('mode') != mode:
        raise ValueError('wrong engine or mode in sample group')
    if value.get('verify') is not False or value.get('source') != 'raw-firrtl':
        raise ValueError('formal samples require raw FIRRTL and disabled correctness verification')
    if value.get('input_sha256') != EXPECTED_INPUT_SHA256:
        raise ValueError('formal samples require the complete F30/F31 SimTop FIRRTL input')
    artifacts.watch(text(value.get('input'), 'raw FIRRTL input'), value['input_sha256'])
    context = machine_context(value)
    timers = timing_rows(value, engine, artifacts)
    native_version = inspect_gsim(value, artifacts) if engine == 'gsim' else inspect_grh(value, artifacts)
    for key in ('started_at_ns', 'finished_at_ns'):
        if type(value.get(key)) is not int or not 0 < value[key] <= 2**63 - 1:
            raise ValueError('invalid sample execution timestamp: ' + key)
    if not value['started_at_ns'] < value['finished_at_ns'] < time.time_ns():
        raise ValueError('invalid or unfinished sample execution interval')
    for key in ('wall_s', 'user_s', 'system_s', 'maxrss_kib'):
        number(value.get(key), 'whole sample ' + key)
    row = value.get('dce', {})
    if not isinstance(row, dict):
        raise ValueError('invalid DCE measurement')
    seconds = number(row.get('pass_s'), 'DCE pass_s')
    instance = 'RemoveDeadNodes#0' if engine == 'gsim' else 'dead-code-elim#0'
    native_seconds = timers[instance]['wall_s']
    if seconds <= 0 or seconds > value['wall_s']:
        raise ValueError('DCE time must be positive and within the whole sample boundary')
    if engine == 'gsim':
        if seconds != native_seconds:
            raise ValueError('GSIM DCE denominator differs from native first-DCE timer')
        if sum(timer['wall_s'] for timer in timers.values()) > value['wall_s']:
            raise ValueError('GSIM native pass timers exceed the whole sample boundary')
        boundary = seconds
    else:
        if row.get('native_pass_s') != native_seconds or seconds < native_seconds:
            raise ValueError('GRH DCE pass_s excludes native pass work')
        for key in ('user_s', 'system_s', 'maxrss_kib'):
            number(row.get(key), 'DCE ' + key)
        snapshot = sum(number(row.get(key, 0), 'DCE ' + key)
                       for key in ('snapshot_setup_s', 'snapshot_export_s'))
        boundary = number(row.get('boundary_s'), 'complete DCE boundary_s')
        if boundary + 1e-9 < seconds + snapshot or boundary > value['wall_s']:
            raise ValueError('complete DCE boundary omits pass or snapshot/export cost')
        if mode == 'trace' and not all(key in row for key in ('snapshot_setup_s', 'snapshot_export_s')):
            raise ValueError('trace sample lacks separate static snapshot/export timing')
        if mode == 'no-trace' and snapshot:
            raise ValueError('no-trace sample contains static exchange overhead')
    return {'path': str(path), 'summary_sha256': summary_digest, 'accepted': True, 'raw': value,
            'context': context, 'native_version': native_version, 'dce_s': seconds,
            'native_dce_s': native_seconds, 'dce_boundary_s': boundary,
            'started_at_ns': value['started_at_ns'], 'finished_at_ns': value['finished_at_ns']}


def rejected_sample(path, error):
    result = {'path': str(Path(path).resolve()), 'accepted': False, 'error': str(error), 'raw': None}
    try:
        original = Path(path).read_text(encoding='utf-8')
        value = json.loads(original)
        canonical(value)
        result['raw'] = value
    except (OSError, ValueError, TypeError, OverflowError):
        if 'original' in locals():
            result['raw_json'] = original
    return result


def classification(reference, value):
    limit = reference + max(reference * JITTER_RELATIVE, JITTER_ABSOLUTE_S)
    return 'pass' if value <= reference else 'within_jitter' if value <= limit else 'regression'


def compare(gsim_paths, grh_no_trace_paths, grh_trace_paths):
    report = {'schema': SCHEMA, 'status': 'incomplete', 'complete': False, 'passed': False,
        'reference': 'GSIM no-trace RemoveDeadNodes#0 is the production-path gate; trace is diagnostic-only',
        'jitter_policy': {'relative': JITTER_RELATIVE, 'absolute_s': JITTER_ABSOLUTE_S},
        'minimum_samples': dict(MINIMUM_SAMPLES), 'samples': {group: [] for group in GROUPS},
        'errors': [], 'comparisons': [], 'diagnostics': [], 'hard_limit': 'incomplete',
        'limitations': ['All supplied samples are retained; omitted runs and external machine load cannot be inferred.',
            'Frozen source and binary identities do not retrospectively prove that the binary was built from those sources.',
            'GRH formal pass time conservatively includes the native run_pass boundary and timing-output overhead.',
            'Static snapshots/export and correctness analysis are excluded from native pass gates and reported separately.',
            'Trace performance is not compared to the production jitter gate; one successful run must remain within 2x GSIM.']}
    artifacts = Artifacts()
    groups = {'gsim': gsim_paths, 'grh_no_trace': grh_no_trace_paths, 'grh_trace': grh_trace_paths}
    paths = [str(Path(path).resolve()) for values in groups.values() for path in values]
    if len(set(paths)) != len(paths):
        report['errors'].append('every supplied sample must be a distinct run')
    for group, paths in groups.items():
        if len(paths) < MINIMUM_SAMPLES[group]:
            report['errors'].append(group + ': at least ' + str(MINIMUM_SAMPLES[group]) + ' complete sample(s) required')
        engine, mode = ('gsim', 'no-trace') if group == 'gsim' else ('grh', 'trace' if group == 'grh_trace' else 'no-trace')
        for path in paths:
            try:
                sample = inspect_sample(path, engine, mode, artifacts)
            except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
                sample = rejected_sample(path, error)
                report['errors'].append(group + ' ' + str(path) + ': ' + str(error))
            report['samples'][group].append(sample)
    valid = {group: [sample for sample in samples if sample['accepted']]
             for group, samples in report['samples'].items()}
    all_valid = [sample for samples in valid.values() for sample in samples]
    if all_valid:
        first = all_valid[0]
        for sample in all_valid[1:]:
            if (sample['context'] != first['context'] or
                    sample['raw']['input'] != first['raw']['input']):
                report['errors'].append('incompatible input/machine/CPU/thread/affinity: ' + sample['path'])
        ordered = sorted(all_valid, key=lambda sample: sample['started_at_ns'])
        for previous, current in zip(ordered, ordered[1:]):
            if current['started_at_ns'] < previous['finished_at_ns']:
                report['errors'].append('sample executions overlap: ' + current['path'])
        for group, samples in valid.items():
            if samples != sorted(samples, key=lambda sample: sample['started_at_ns']):
                report['errors'].append(group + ': supplied sample order is not chronological')
    for samples in (valid['gsim'], valid['grh_no_trace'] + valid['grh_trace']):
        if samples and any(sample['native_version'] != samples[0]['native_version'] for sample in samples[1:]):
            report['errors'].append('native source/build/dependency/request identity changed within an engine')
    if len(valid['gsim']) >= 3 and len(valid['gsim']) == len(gsim_paths):
        baseline = statistics.median(sample['dce_s'] for sample in valid['gsim'])
        split_times = []
        for sample in valid['gsim']:
            split_rows = [row for row in sample['raw']['native_timers'].values() if row['stage'] == 'SplitArray']
            if len(split_rows) != 1:
                report['errors'].append('GSIM reference lacks a unique native SplitArray timer')
            else:
                split_times.append(split_rows[0]['wall_s'])
        frozen = {'median_s': baseline, 'limit_s': baseline + max(baseline * JITTER_RELATIVE, JITTER_ABSOLUTE_S),
            'dce_timeout_s': 2 * baseline,
            'split_timeout_s': 2 * statistics.median(split_times) if len(split_times) == len(valid['gsim']) else None,
            'samples': [{'path': sample['path'], 'sha256': sample['summary_sha256']} for sample in valid['gsim']]}
        if frozen['split_timeout_s'] is not None and frozen['split_timeout_s'] <= 0:
            report['errors'].append('native GSIM split median must be positive')
        report['reference_evidence'] = frozen
        hard = []
        for group in ('grh_no_trace', 'grh_trace'):
            for sample in report['samples'][group]:
                raw = sample['raw'] if isinstance(sample.get('raw'), dict) else {}
                if raw.get('reference') != frozen:
                    report['errors'].append('GRH watchdog reference differs from the same supplied GSIM denominator: ' + sample['path'])
                    sample['hard_limit'] = {'status': 'unverified', 'limit_s': frozen['dce_timeout_s']}
                    hard.append('unverified')
                    continue
                if (type(raw.get('started_at_ns')) is not int or
                        any(reference['finished_at_ns'] > raw['started_at_ns'] for reference in valid['gsim'])):
                    report['errors'].append('watchdog reference was not frozen before the GRH run: ' + sample['path'])
                failed = raw.get('status') != 'passed'
                observed = raw['dce'].get('pass_s') if isinstance(raw.get('dce'), dict) else None
                outcome = 'failed' if failed else ('passed' if sample['accepted'] and observed <= 2 * baseline else
                    'failed' if sample['accepted'] else 'unverified')
                sample['hard_limit'] = {'status': outcome, 'limit_s': 2 * baseline,
                    'completion_time_s': observed if sample['accepted'] else None}
                hard.append(outcome)
            if (group == 'grh_no_trace' and len(valid[group]) >= MINIMUM_SAMPLES[group]
                    and len(valid[group]) == len(groups[group])):
                values = [sample['dce_s'] for sample in valid[group]]
                median = statistics.median(values)
                status = classification(baseline, median)
                report['comparisons'].append({'mode': 'trace' if group == 'grh_trace' else 'no-trace',
                    'reference_s': [sample['dce_s'] for sample in valid['gsim']], 'grh_s': values,
                    'gsim_median_s': baseline, 'grh_median_s': median, 'limit_s': frozen['limit_s'],
                    'delta_s': median - baseline, 'ratio': median / baseline,
                    'classification': status, 'passed': status != 'regression'})
                report['diagnostics'].append({'mode': group, 'boundary_median_s': statistics.median(
                    sample['dce_boundary_s'] for sample in valid[group]),
                    'ingest_through_dce_median_s': statistics.median(sample['raw']['wall_s'] for sample in valid[group]),
                    'native_dce_median_s': statistics.median(sample['native_dce_s'] for sample in valid[group]),
                    'snapshot_setup_s': [sample['raw']['dce'].get('snapshot_setup_s', 0) for sample in valid[group]],
                    'snapshot_export_s': [sample['raw']['dce'].get('snapshot_export_s', 0) for sample in valid[group]]})
        if valid['grh_trace'] and len(valid['grh_trace']) == len(groups['grh_trace']):
            values = [sample['dce_s'] for sample in valid['grh_trace']]
            trace_limit = 2 * baseline
            report['trace_sanity'] = {'samples_s': values, 'gsim_median_s': baseline,
                'limit_s': trace_limit, 'max_ratio': max(values) / baseline,
                'classification': 'acceptable' if all(value <= trace_limit for value in values) else 'too_slow',
                'passed': all(value <= trace_limit for value in values),
                'policy': 'diagnostic-only; no 3% jitter requirement'}
            report['diagnostics'].append({'mode': 'grh_trace', 'boundary_median_s': statistics.median(
                sample['dce_boundary_s'] for sample in valid['grh_trace']),
                'ingest_through_dce_median_s': statistics.median(sample['raw']['wall_s'] for sample in valid['grh_trace']),
                'native_dce_median_s': statistics.median(sample['native_dce_s'] for sample in valid['grh_trace']),
                'snapshot_setup_s': [sample['raw']['dce'].get('snapshot_setup_s', 0) for sample in valid['grh_trace']],
                'snapshot_export_s': [sample['raw']['dce'].get('snapshot_export_s', 0) for sample in valid['grh_trace']]})
        report['hard_limit'] = 'failed' if 'failed' in hard else 'passed' if hard and all(item == 'passed' for item in hard) else 'incomplete'
    try:
        artifacts.check()
    except (OSError, ValueError) as error:
        report['errors'].append(str(error))
    if not report['errors'] and len(report['comparisons']) == 1 and 'trace_sanity' in report:
        report['complete'] = True
        report['passed'] = (report['hard_limit'] == 'passed' and
                            all(row['passed'] for row in report['comparisons']) and
                            report['trace_sanity']['passed'])
        report['status'] = 'passed' if report['passed'] else 'regressed'
    report['artifacts'] = artifacts.files
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gsim', type=Path, nargs='+', required=True)
    parser.add_argument('--grh-no-trace', type=Path, nargs='+', required=True)
    parser.add_argument('--grh-trace', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'summary.json').exists():
        parser.error('refusing to overwrite a comparison report')
    report = compare(args.gsim, args.grh_no_trace, args.grh_trace)
    write_json_atomic(output / 'summary.json', report)
    with (output / 'comparisons.tsv').open('w', encoding='utf-8', newline='') as stream:
        fields = ('mode', 'gsim_median_s', 'grh_median_s', 'limit_s', 'delta_s', 'ratio', 'classification', 'passed')
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(report['comparisons'])
    print(json.dumps({'status': report['status'], 'passed': report['passed'], 'errors': report['errors']}), flush=True)
    raise SystemExit(0 if report['passed'] else 1 if report['complete'] else 2)


if __name__ == '__main__':
    main()
