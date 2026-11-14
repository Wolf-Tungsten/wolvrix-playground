"""Apply F30's paired performance gate to complete raw-ingest benchmark runs.

Each invocation compares one mode, preserving every supplied sample and its pair
order. Exit 1 means regression; exit 2 means incomplete or incompatible evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.performance-comparison.v1'
INPUT_SCHEMA = 'wolvrix.f30.pipeline-benchmark.v1'
SPLIT_TIMEOUT_S = 49.046
MAX_JITTER_RELATIVE = 0.03
MAX_JITTER_ABSOLUTE_S = 0.010
PREFIX_STAGES = ('ingest', 'xmr-resolve', 'hier-flatten')
PASSES = ('comb-loop-elim', 'split-static-array')
CONFIG_FIELDS = ('input', 'input_sha256', 'manifest', 'manifest_sha256',
                 'cpu_affinity', 'mode', 'verify', 'split_timeout_s')
CONFIGURATION_FIELDS = ('machine', 'cpu_model', 'thread_environment', 'build',
                        'pass_parameters', 'instrumentation', 'python_version')
METRICS = (*PREFIX_STAGES, *PASSES, 'comb-loop-elim.total',
           'split-static-array.total', 'comb-split.total', 'ingest-through-split.total')
COMPONENTS = ('trace_setup_s', 'trace_finish_s', 'semantic_validation_s', 'grh_verification_s')


def number(value, field):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{field}: expected a finite nonnegative number')
    return value


def text(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field}: expected a nonempty string')
    return value


def digest(value, field):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(f'{field}: expected a SHA256 digest')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def jitter_policy(relative, absolute_s):
    for value, maximum, field in ((relative, MAX_JITTER_RELATIVE, 'jitter-relative'),
                                  (absolute_s, MAX_JITTER_ABSOLUTE_S, 'jitter-absolute-s')):
        if number(value, field) > maximum:
            raise ValueError(f'{field}: must be between 0 and {maximum}')
    return {'relative': relative, 'absolute_s': absolute_s,
            'formula': 'max(before_median_s * relative, absolute_s)',
            'strict': relative == 0 and absolute_s == 0}


def dependencies_provenance(value):
    recorded = value.get('dependencies_provenance')
    if recorded in ('frozen-source-bound', 'post-build-sidecar'):
        return {'kind': recorded, 'basis': 'recorded by benchmark producer'}
    # Older producers verified the same artifacts without naming this distinction.
    dependency = value.get('dependencies')
    content = dependency.get('content_sha256') if isinstance(dependency, dict) else None
    revision = value.get('source_revision')
    bound = (isinstance(content, str) and isinstance(revision, str) and
             revision.endswith('+dependencies-sha256:' + content))
    return {'kind': 'frozen-source-bound' if bound else 'post-build-sidecar',
            'basis': 'inferred from legacy source_revision; not a new acceptance requirement'}


def hard_limit_evidence(value, *, expected_cap_s=SPLIT_TIMEOUT_S):
    """A watchdog observation is never a pass completion measurement."""
    limit = None if expected_cap_s is None else number(expected_cap_s, 'expected split cap')
    evidence = {'status': 'incomplete', 'limit_s': limit, 'cap_verified': False,
                'observed_elapsed_s': None, 'completion_time_s': None}
    if not isinstance(value, dict):
        return evidence
    recorded = value.get('split_timeout_s')
    evidence['recorded_limit_s'] = recorded
    verified = (limit is not None and limit > 0 and type(recorded) in (int, float) and recorded == limit)
    evidence['cap_verified'] = verified
    if not verified:
        evidence['status'] = 'unverified'
    case = value.get('trace' if value.get('mode') == 'trace' else 'no_trace')
    if not isinstance(case, dict) or not isinstance(case.get('passes'), list):
        return evidence
    rows = [row for row in case['passes'] if isinstance(row, dict) and row.get('pass') == 'split-static-array']
    if len(rows) != 1:
        return evidence
    row = rows[0]
    if 'timeout_s' in row and (type(row['timeout_s']) not in (int, float) or row['timeout_s'] != limit):
        evidence.update(status='unverified', cap_verified=False)
        verified = False
    elapsed = row.get('pass_s')
    if type(elapsed) in (int, float):
        try:
            if math.isfinite(elapsed) and elapsed >= 0:
                evidence['observed_elapsed_s'] = elapsed
        except OverflowError:
            pass
    if not verified:
        return evidence
    if row.get('status') == 'timeout':
        evidence.update(status='failed', measurement='deadline-observation-not-completion')
    elif row.get('pass_returned') is True and evidence['observed_elapsed_s'] is not None:
        evidence['completion_time_s'] = elapsed
        evidence['status'] = 'failed' if elapsed > limit else 'passed'
        evidence['measurement'] = 'pass-returned'
    return evidence


def rejected_sample(path, error, *, expected_cap_s=SPLIT_TIMEOUT_S):
    result = {'path': str(Path(path).resolve()), 'accepted': False, 'error': str(error), 'raw': None}
    try:
        original = Path(path).read_text(encoding='utf-8')
        value = json.loads(original)
        try:
            canonical(value)
            result['raw'] = value
        except (TypeError, ValueError, OverflowError):
            result['raw_json'] = original
        if isinstance(value, dict):
            result['dependencies_provenance'] = dependencies_provenance(value)
        result['hard_limit'] = hard_limit_evidence(value, expected_cap_s=expected_cap_s)
    except (OSError, ValueError, UnicodeError):
        result['hard_limit'] = hard_limit_evidence(None, expected_cap_s=expected_cap_s)
    return result


def inspect_sample(path, *, expected_cap_s=SPLIT_TIMEOUT_S):
    path = Path(path).resolve()
    with path.open(encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or value.get('schema') != INPUT_SCHEMA:
        raise ValueError('not an F30 raw-ingest pipeline benchmark summary')
    if value.get('status') != 'passed':
        raise ValueError(f"sample status is {value.get('status')!r}; failed or incomplete samples cannot be dropped")
    for field in ('package_identity_verified', 'source_identity_verified', 'dependencies_verified'):
        if value.get(field) is not True:
            raise ValueError(f'{field}: frozen provenance was not verified before timing')
    digest(value.get('identity_sha256'), 'frozen package identity SHA256')
    for field in ('input', 'manifest'):
        text(value.get(field), field)
        digest(value.get(field + '_sha256'), field + '_sha256')
    if value.get('mode') not in ('no-trace', 'trace'):
        raise ValueError('mode must be no-trace or trace')
    if type(value.get('verify')) is not bool:
        raise ValueError('verify must record the actual boolean verification setting')
    affinity = value.get('cpu_affinity')
    if (not isinstance(affinity, list) or not affinity or
            any(type(cpu) is not int or cpu < 0 for cpu in affinity) or affinity != sorted(set(affinity))):
        raise ValueError('cpu_affinity must be a nonempty sorted unique CPU list')
    expected_cap_s = number(expected_cap_s, 'expected split cap')
    if expected_cap_s <= 0 or number(value.get('split_timeout_s'), 'split_timeout_s') != expected_cap_s:
        raise ValueError(f'split hard cap must remain the verified {expected_cap_s} s')
    native = value.get('native')
    if not isinstance(native, dict):
        raise ValueError('missing actual loaded native identity')
    text(native.get('package'), 'native.package')
    libraries = native.get('libraries')
    if not isinstance(libraries, list) or not libraries:
        raise ValueError('missing loaded native libraries')
    names = []
    for library in libraries:
        if not isinstance(library, dict):
            raise ValueError('invalid loaded native library')
        names.append(Path(text(library.get('path'), 'native library path')).name)
        digest(library.get('sha256'), 'native library SHA256')
    if len(set(names)) != len(names) or not {'_wolvrix.so', 'libwolvrix-lib.so'} <= set(names):
        raise ValueError('native identity must include unique extension and core library hashes')
    config = {field: value[field] for field in CONFIG_FIELDS}
    configuration = value.get('configuration')
    if not isinstance(configuration, dict) or any(field not in configuration for field in CONFIGURATION_FIELDS):
        raise ValueError('missing configuration evidence for machine/CPU/threads/build/pass parameters/instrumentation/Python')
    for field in ('machine', 'cpu_model', 'python_version'):
        if not isinstance(configuration[field], (str, dict, list)) or not configuration[field]:
            raise ValueError(f'configuration.{field} must record a machine/runtime identity')
        if isinstance(configuration[field], list) and any(not isinstance(item, str) or not item for item in configuration[field]):
            raise ValueError(f'configuration.{field} contains an invalid machine/runtime identity')
    for field in ('thread_environment', 'pass_parameters', 'instrumentation'):
        if not isinstance(configuration[field], dict):
            raise ValueError(f'configuration.{field} must be a configuration object')
    if not isinstance(configuration['build'], (str, dict)) or not configuration['build']:
        raise ValueError('configuration.build must record the actual build configuration')
    instrumentation = configuration['instrumentation']
    termination = value.get('termination')
    if (instrumentation.get('resource_guard', False) or value.get('resource_guard') or
            isinstance(termination, dict) and termination.get('kind') == 'resource-guard'):
        raise ValueError('resource-guard diagnostic sample cannot enter a formal performance gate')
    if (instrumentation.get('source') != 'raw-firrtl' or instrumentation.get('clone') is not False or
            instrumentation.get('trace') is not (value['mode'] == 'trace') or
            instrumentation.get('verify') is not value['verify'] or
            type(instrumentation.get('statistics')) is not bool):
        raise ValueError('instrumentation must record raw FIRRTL, no clone, matching trace/verify and statistics setting')
    if not {*PREFIX_STAGES, *PASSES} <= set(configuration['pass_parameters']):
        raise ValueError('pass_parameters must record all five production stages')
    sources = configuration.get('sources')
    if not isinstance(sources, list) or not sources or value.get('sources') != sources:
        raise ValueError('actual manifest source inventory is missing or inconsistent')
    main_source = False
    for source in sources:
        if not isinstance(source, dict) or source.get('language') not in ('firrtl', 'sv'):
            raise ValueError('invalid actual manifest source definition')
        text(source.get('path'), 'actual source path')
        digest(source.get('sha256'), 'actual source SHA256')
        if type(source.get('bytes')) is not int or source['bytes'] < 0:
            raise ValueError('invalid actual source byte count')
        main_source |= (source['language'] == 'firrtl' and source['path'] == value['input'] and
                        source['sha256'] == value['input_sha256'])
    if not main_source:
        raise ValueError('recorded FIRRTL input is not bound to the actual manifest source inventory')
    dependencies = configuration.get('dependencies')
    actual_dependencies = value.get('dependencies')
    if (not isinstance(dependencies, dict) or not isinstance(dependencies.get('repositories'), list) or
            not isinstance(actual_dependencies, dict) or
            any(dependencies.get(field) != actual_dependencies.get(field) for field in ('content_sha256', 'repositories'))):
        raise ValueError('frozen external dependency inventory is missing or inconsistent')
    digest(dependencies.get('content_sha256'), 'frozen external dependency content SHA256')
    config['configuration'] = configuration
    canonical(config)
    canonical(native)
    text(value.get('source_revision'), 'source_revision')
    for field in ('started_at_ns', 'finished_at_ns'):
        if type(value.get(field)) is not int or not 0 < value[field] <= 2**63 - 1:
            raise ValueError(f'{field}: missing absolute nanosecond timestamp for execution order')
    if value['finished_at_ns'] <= value['started_at_ns']:
        raise ValueError('execution timestamps must describe a positive nonoverlapping run interval')
    prefix = value.get('prefix')
    stages = prefix.get('stages') if isinstance(prefix, dict) else None
    if (not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages) or
            [stage.get('stage') for stage in stages] != list(PREFIX_STAGES)):
        raise ValueError('requires ingest, xmr-resolve, hier-flatten in normal raw-ingest order')
    metrics = {}
    for stage in stages:
        if 'status' in stage and stage['status'] != 'passed':
            raise ValueError('prefix stage did not pass')
        metrics[stage['stage']] = number(stage.get('wall_s'), stage['stage'] + '.wall_s')
    case = value.get('trace' if value['mode'] == 'trace' else 'no_trace')
    if (not isinstance(case, dict) or case.get('status') != 'passed' or case.get('skip_comb') is not False or
            type(case.get('trace')) is not bool or case['trace'] != (value['mode'] == 'trace')):
        raise ValueError('missing complete same-mode comb/split run')
    passes = case.get('passes')
    if (not isinstance(passes, list) or any(not isinstance(stage, dict) for stage in passes) or
            [stage.get('pass') for stage in passes] != list(PASSES)):
        raise ValueError('requires both comb-loop-elim and split-static-array in order')
    components = {}
    for stage in passes:
        name = stage['pass']
        if stage.get('status') != 'passed' or stage.get('pass_returned') is not True:
            raise ValueError(f'{name}: pass failed, timed out, or did not return')
        metrics[name] = number(stage.get('pass_s'), name + '.pass_s')
        metrics[name + '.total'] = number(stage.get('total_s'), name + '.total_s')
        if metrics[name + '.total'] < metrics[name]:
            raise ValueError(f'{name}: total boundary excludes pass execution')
        if name == 'split-static-array' and metrics[name] > expected_cap_s:
            raise ValueError(f'split-static-array exceeded the {expected_cap_s} s hard cap')
        for field in COMPONENTS:
            if field in stage:
                components[name + '.' + field] = number(stage[field], name + '.' + field)
        if value['mode'] == 'trace':
            for field in ('trace_setup_s', 'trace_finish_s'):
                if field not in stage:
                    raise ValueError(f'{name}: trace requires separate setup and finish timing')
            if stage.get('trace_validate_at_finish') is not value['verify']:
                raise ValueError(f'{name}: trace verification differs from configured setting')
        elif any(field in stage for field in ('trace_setup_s', 'trace_finish_s')):
            raise ValueError(f'{name}: trace work present in no-trace sample')
        if value['verify']:
            if ('semantic_validation_s' not in stage or
                    not isinstance(stage.get('semantic_validation'), dict) or
                    stage['semantic_validation'].get('valid') is not True):
                raise ValueError(f'{name}: required semantic validation was not completed')
            if name == 'split-static-array' and (stage.get('grh_verification') != 'passed' or
                                                 'grh_verification_s' not in stage):
                raise ValueError('split-static-array: required GRH verification was not completed')
        elif any(field in stage for field in ('semantic_validation_s', 'grh_verification_s')):
            raise ValueError(f'{name}: validation work present with verify disabled')
        accounted = metrics[name] + sum(components.get(name + '.' + field, 0) for field in COMPONENTS)
        if metrics[name + '.total'] < accounted:
            raise ValueError(f'{name}: total boundary excludes measured setup/finish/validation work')
    metrics['comb-split.total'] = number(case.get('wall_s'), 'comb/split wall_s')
    if metrics['comb-split.total'] < sum(metrics[name + '.total'] for name in PASSES):
        raise ValueError('comb/split total boundary excludes pass boundaries')
    metrics['ingest-through-split.total'] = number(value.get('wall_s'), 'whole wall_s')
    if metrics['ingest-through-split.total'] < sum(metrics[name] for name in PREFIX_STAGES) + metrics['comb-split.total']:
        raise ValueError('whole boundary excludes measured production stages')
    hard_limit = hard_limit_evidence(value, expected_cap_s=expected_cap_s)
    if hard_limit['status'] != 'passed':
        raise ValueError('successful split sample lacks verified hard-limit completion')
    canonical(value)
    # Preserve all raw counters and workloads; they explain performance but do
    # not normalize or replace the measured wall-time completion gates.
    return {'path': str(path), 'accepted': True, 'config': config, 'native': native,
            'source_revision': value['source_revision'],
            'identity_sha256': value['identity_sha256'],
            'started_at_ns': value['started_at_ns'], 'finished_at_ns': value['finished_at_ns'], 'metrics': metrics,
            'components': components, 'raw': value,
            'hard_limit': hard_limit,
            'dependencies_provenance': dependencies_provenance(value)}


def compare(before_paths, after_paths, jitter_relative=MAX_JITTER_RELATIVE,
            jitter_absolute_s=MAX_JITTER_ABSOLUTE_S):
    policy = jitter_policy(jitter_relative, jitter_absolute_s)
    report = {'schema': SCHEMA, 'status': 'incomplete', 'complete': False, 'passed': False,
              'hard_limit': 'incomplete', 'relative': 'incomplete',
              'jitter_policy': policy,
              'split_timeout_s': SPLIT_TIMEOUT_S, 'minimum_pairs': 3,
              'before_paths': [str(Path(path).resolve()) for path in before_paths],
              'after_paths': [str(Path(path).resolve()) for path in after_paths],
              'samples': {'before': [], 'after': []}, 'errors': [], 'comparisons': [],
              'limitations': ['Recorded identities and timestamps cannot establish equal external machine load. '
                  'The configured jitter band applies only to paired medians; the independent split deadline remains fixed.']}
    if len(before_paths) != len(after_paths) or len(before_paths) < 3:
        report['errors'].append('at least three ordered before/after pairs of equal length are required')
    all_paths = report['before_paths'] + report['after_paths']
    if len(set(all_paths)) != len(all_paths):
        report['errors'].append('every sample must be a distinct run; a summary path cannot be reused')
    for side, paths in (('before', before_paths), ('after', after_paths)):
        for index, path in enumerate(paths):
            try:
                report['samples'][side].append(inspect_sample(path))
            except (OSError, ValueError, TypeError) as error:
                report['samples'][side].append(rejected_sample(path, error))
                report['errors'].append(f'{side}[{index}] {path}: {error}')
        samples = [sample for sample in report['samples'][side] if sample['accepted']]
        if samples:
            for sample in samples[1:]:
                if canonical(sample['native']) != canonical(samples[0]['native']):
                    report['errors'].append(f'{side}: loaded native identity changed within one version')
                if sample['source_revision'] != samples[0]['source_revision']:
                    report['errors'].append(f'{side}: source revision changed within one version')
                if sample['identity_sha256'] != samples[0]['identity_sha256']:
                    report['errors'].append(f'{side}: frozen package identity changed within one version')
    all_samples = report['samples']['before'] + report['samples']['after']
    hard_limits = [sample['hard_limit']['status'] for sample in all_samples]
    if 'failed' in hard_limits:
        report['hard_limit'] = 'failed'
    elif hard_limits and all(status == 'passed' for status in hard_limits):
        report['hard_limit'] = 'passed'
    report['dependencies_provenance'] = {side: [
        {'path': sample['path'], **sample['dependencies_provenance']}
        for sample in report['samples'][side] if 'dependencies_provenance' in sample]
        for side in ('before', 'after')}
    if any(item['kind'] == 'post-build-sidecar'
           for rows in report['dependencies_provenance'].values() for item in rows):
        report['limitations'].append('A post-build dependency sidecar verifies its recorded contents, '
            'but does not retroactively establish the dependencies used to build that frozen package.')
    samples = [sample for sample in all_samples if sample['accepted']]
    if samples:
        config = samples[0]['config']
        report['configuration'] = config
        for sample in samples[1:]:
            if canonical(sample['config']) != canonical(config):
                report['errors'].append(f"incompatible source/manifest/affinity/mode/verification/configuration: {sample['path']}")
    if report['errors']:
        return report
    first = ('before', 'after') if report['samples']['before'][0]['started_at_ns'] < report['samples']['after'][0]['started_at_ns'] else ('after', 'before')
    ordered = [(side, index, report['samples'][side][index])
               for index in range(len(before_paths)) for side in first]
    report['execution_order'] = [f'{side}[{index}]' for side, index, _ in ordered]
    for (_, _, previous), (side, index, current) in zip(ordered, ordered[1:]):
        if current['started_at_ns'] < previous['finished_at_ns']:
            report['errors'].append(f'paired runs must strictly alternate without overlap in supplied pair order: {side}[{index}]')
    if report['errors']:
        return report
    report['pair_count'] = len(before_paths)
    report['mode'] = report['configuration']['mode']
    for metric in METRICS:
        before = [sample['metrics'][metric] for sample in report['samples']['before']]
        after = [sample['metrics'][metric] for sample in report['samples']['after']]
        baseline, candidate = statistics.median(before), statistics.median(after)
        allowed_jitter = max(baseline * jitter_relative, jitter_absolute_s)
        threshold = baseline + allowed_jitter
        classification = ('strict_pass' if candidate <= baseline else
                          'within_jitter' if candidate <= threshold else 'regression')
        report['comparisons'].append({'metric': metric, 'before_s': before, 'after_s': after,
            'before_median_s': baseline, 'after_median_s': candidate, 'delta_s': candidate - baseline,
            'ratio': candidate / baseline if baseline else 1.0 if candidate == 0 else None,
            'allowed_jitter_s': allowed_jitter, 'threshold_s': threshold,
            'classification': classification, 'passed': classification != 'regression'})
    report['components'] = {}
    for key in sorted(set().union(*(sample['components'] for sample in samples))):
        values = {side: [sample['components'].get(key) for sample in report['samples'][side]]
                  for side in ('before', 'after')}
        report['components'][key] = {**values, **{
            side + '_median_s': statistics.median(rows) if all(value is not None for value in rows) else None
            for side, rows in values.items()}}
    report.update(complete=True, passed=all(row['passed'] for row in report['comparisons']))
    report['status'] = 'passed' if report['passed'] else 'regressed'
    report['relative'] = report['status']
    return report


def write_report(report, output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('report output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'comparison.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    with (output / 'comparison.tsv').open('w', encoding='utf-8', newline='') as stream:
        fields = ('mode', 'metric', 'before_median_s', 'after_median_s', 'delta_s', 'ratio',
                  'allowed_jitter_s', 'threshold_s', 'classification', 'passed')
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in report['comparisons']:
            writer.writerow({key: report.get('mode') if key == 'mode' else row[key] for key in fields})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', nargs='+', type=Path, required=True)
    parser.add_argument('--after', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jitter-relative', type=float, default=MAX_JITTER_RELATIVE,
                        help='relative median jitter allowance, 0..0.03 (default: 0.03)')
    parser.add_argument('--jitter-absolute-s', type=float, default=MAX_JITTER_ABSOLUTE_S,
                        help='absolute median jitter allowance, 0..0.010 seconds (default: 0.010)')
    args = parser.parse_args(argv)
    try:
        report = compare(args.before, args.after, args.jitter_relative, args.jitter_absolute_s)
        write_report(report, args.output)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in
        ('status', 'complete', 'passed', 'hard_limit', 'relative', 'errors')}, indent=2))
    return 0 if report['passed'] else 1 if report['complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
