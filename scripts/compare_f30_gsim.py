"""Compare F30 GRH common boundaries against the GSIM no-trace reference."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

from benchmark_f29_pass_trace import sha256
from benchmark_f30_gsim import SCHEMA as GSIM_SCHEMA, parse_timers
from benchmark_f30_pipeline import verify_source_provenance
from compare_f30_performance import (MAX_JITTER_ABSOLUTE_S, MAX_JITTER_RELATIVE,
    canonical, digest, inspect_sample, jitter_policy, number, rejected_sample, text)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.gsim-comparison.v1'
METRICS = ('prefix', 'comb-split.pass', 'prefix+transform.pass')
DIAGNOSTIC_METRICS = ('comb-split.total', 'ingest-through-split.total')
MACHINE_FIELDS = ('machine', 'cpu_model', 'thread_environment')


def inspect_gsim(path):
    path = Path(path).resolve()
    contents = path.read_bytes()
    value = json.loads(contents)
    if not isinstance(value, dict) or value.get('schema') != GSIM_SCHEMA:
        raise ValueError('not an F30 GSIM benchmark sample')
    if value.get('status') != 'passed':
        raise ValueError('GSIM failed or incomplete samples cannot be dropped')
    if (value.get('mode') != 'no-trace' or value.get('trace') is not False or
            value.get('stop_after_stage') != 'SplitArray' or value.get('returncode') != 0):
        raise ValueError('GSIM reference must complete raw FIRRTL through SplitArray without trace')
    config = value.get('configuration')
    if not isinstance(config, dict) or any(key not in config for key in MACHINE_FIELDS):
        raise ValueError('missing GSIM machine/CPU/thread configuration')
    if (not config['machine'] or not config['cpu_model'] or
            not isinstance(config['thread_environment'], dict)):
        raise ValueError('invalid GSIM machine/CPU/thread configuration')
    if config.get('instrumentation') != {'trace': False, 'dump': False, 'source': 'raw-firrtl'}:
        raise ValueError('GSIM reference contains additional instrumentation')
    for field in ('native_identity_verified', 'input_unchanged', 'binary_unchanged'):
        if value.get(field) is not True:
            raise ValueError('missing GSIM frozen provenance: ' + field)
    digest(value.get('input_sha256'), 'GSIM input SHA256')
    if sha256(Path(text(value.get('input'), 'GSIM input'))) != value['input_sha256']:
        raise ValueError('GSIM input hash mismatch')
    identity_path = Path(text(value.get('identity_file'), 'GSIM identity file'))
    digest(value.get('identity_sha256'), 'GSIM identity SHA256')
    if sha256(identity_path) != value['identity_sha256']:
        raise ValueError('GSIM frozen identity hash mismatch')
    native = value.get('native')
    if (not isinstance(native, dict) or native.get('schema') != 'wolvrix.f30.gsim-native.v1' or
            json.loads(identity_path.read_text()) != native):
        raise ValueError('GSIM sample differs from frozen native identity')
    if sha256(Path(native['binary'])) != native['sha256']:
        raise ValueError('GSIM frozen binary hash mismatch')
    verify_source_provenance(native)
    patch = native['source_patch']
    if sha256(Path(patch['path'])) != patch['sha256']:
        raise ValueError('GSIM frozen source patch hash mismatch')
    for library in native.get('libraries', []):
        if sha256(Path(library['path'])) != library['sha256']:
            raise ValueError('GSIM runtime dependency hash mismatch')
    command = value.get('command')
    if (not isinstance(command, list) or len(command) != 5 or command[0] != native['binary'] or
            command[1] != '--dir' or command[3:] != ['--stop-after-stage=SplitArray', value['input']]):
        raise ValueError('GSIM command does not describe the uninstrumented reference boundary')
    log_path = Path(text(value.get('log'), 'GSIM log'))
    if sha256(log_path) != value.get('log_sha256'):
        raise ValueError('GSIM timer log hash mismatch')
    timers = parse_timers(log_path.read_text(encoding='utf-8'))
    if timers != value.get('timers'):
        raise ValueError('GSIM sample timers differ from actual log')
    metrics = {'prefix': sum(timers[name] for name in ('readFile', 'parseFIR', 'Init')),
               'comb-split.total': timers['splitArray']}
    metrics['prefix+transform'] = sum(metrics.values())
    if value.get('metrics') != metrics:
        raise ValueError('GSIM common boundary metrics differ from native timers')
    if number(value.get('wall_s'), 'GSIM whole wall') < metrics['prefix+transform']:
        raise ValueError('GSIM stage timers exceed the whole process boundary')
    metrics['ingest-through-split.total'] = value['wall_s']
    metrics['comb-split.pass'] = timers['splitArray']
    metrics['prefix+transform.pass'] = metrics['prefix+transform']
    for field in ('started_at_ns', 'finished_at_ns'):
        if type(value.get(field)) is not int or not 0 < value[field] <= 2**63 - 1:
            raise ValueError('invalid GSIM execution timestamp: ' + field)
    if value['finished_at_ns'] <= value['started_at_ns']:
        raise ValueError('GSIM execution interval is not positive')
    affinity = value.get('cpu_affinity')
    if (not isinstance(affinity, list) or not affinity or
            any(type(cpu) is not int or cpu < 0 for cpu in affinity) or affinity != sorted(set(affinity))):
        raise ValueError('invalid GSIM CPU affinity')
    canonical(value)
    return {'path': str(path), 'summary_sha256': hashlib.sha256(contents).hexdigest(),
        'accepted': True, 'raw': value, 'metrics': metrics,
        'started_at_ns': value['started_at_ns'], 'finished_at_ns': value['finished_at_ns'],
        'configuration': config,
        'native_version': {key: native[key] for key in
            ('sha256', 'source_revision', 'build_configuration_files', 'libraries')}}


def reference_context(value):
    configuration = value.get('configuration')
    if not isinstance(configuration, dict) or any(key not in configuration for key in MACHINE_FIELDS):
        raise ValueError('missing reference input/machine/CPU/thread configuration')
    return {**{key: value.get(key) for key in ('input', 'input_sha256', 'cpu_affinity')},
            'machine': {key: configuration[key] for key in MACHINE_FIELDS}}


def timeout_reference_from_samples(samples, context=None, completed_before_ns=None):
    """Derive the watchdog only from already inspected, complete GSIM runs."""
    if len(samples) < 3 or len({sample['path'] for sample in samples}) != len(samples):
        raise ValueError('split timeout requires at least three distinct GSIM reference samples')
    before = time.time_ns() if completed_before_ns is None else completed_before_ns
    if type(before) is not int or not 0 < before <= 2**63 - 1:
        raise ValueError('invalid split timeout reference completion boundary')
    before = min(before, time.time_ns())
    first = samples[0]
    shared = reference_context(first['raw'])
    if context is not None and canonical(reference_context(context)) != canonical(shared):
        raise ValueError('split timeout reference has incompatible input/machine/CPU/thread configuration')
    for index, sample in enumerate(samples):
        if sha256(Path(sample['path'])) != sample['summary_sha256']:
            raise ValueError('split timeout GSIM summary changed during reference validation')
        if (canonical(sample['configuration']) != canonical(first['configuration']) or
                canonical(sample['native_version']) != canonical(first['native_version'])):
            raise ValueError('split timeout GSIM reference configuration or native version changed')
        if canonical(reference_context(sample['raw'])) != canonical(shared):
            raise ValueError('split timeout GSIM reference input or configuration changed')
        if sample['finished_at_ns'] > before:
            raise ValueError('split timeout GSIM references must finish before the GRH run')
        if index and sample['started_at_ns'] < samples[index - 1]['finished_at_ns']:
            raise ValueError('split timeout GSIM references must be chronological and nonoverlapping')
    elapsed = [number(sample['raw']['timers']['splitArray'], 'GSIM splitArray reference timer')
               for sample in samples]
    median = statistics.median(elapsed)
    if median <= 0:
        raise ValueError('split timeout GSIM reference median must be positive')
    return {'schema': 'wolvrix.f30.gsim-split-timeout.v1', 'reference': 'GSIM no-trace',
        'stage': 'SplitArray', 'metric': 'splitArray', 'multiplier': 2,
        'median_s': median, 'split_timeout_s': median * 2,
        'configuration': shared, 'native_version': first['native_version'],
        'samples': [{'path': sample['path'], 'sha256': sample['summary_sha256'],
                     'split_array_s': seconds, 'started_at_ns': sample['started_at_ns'],
                     'finished_at_ns': sample['finished_at_ns'],
                     'identity_sha256': sample['raw']['identity_sha256']}
                    for sample, seconds in zip(samples, elapsed)]}


def derive_split_timeout(paths, context=None, completed_before_ns=None):
    return timeout_reference_from_samples([inspect_gsim(path) for path in paths],
                                          context, completed_before_ns)


def compare(grh_paths, gsim_paths, jitter_relative=MAX_JITTER_RELATIVE,
            jitter_absolute_s=MAX_JITTER_ABSOLUTE_S):
    policy = jitter_policy(jitter_relative, jitter_absolute_s)
    report = {'schema': SCHEMA, 'status': 'incomplete', 'complete': False, 'passed': False,
        'reference': 'GSIM no-trace', 'hard_limit': 'incomplete', 'relative': 'incomplete',
        'jitter_policy': policy, 'minimum_samples_per_engine': 3,
        'samples': {'grh': [], 'gsim': []}, 'errors': [], 'comparisons': [], 'diagnostic_comparisons': [],
        'formal_metrics': list(METRICS),
        'diagnostic_metrics': list(DIAGNOSTIC_METRICS),
        'boundaries': {'prefix': 'GRH ingest+xmr-resolve+hier-flatten versus GSIM readFile+parseFIR+Init',
            'comb-split.pass': 'GRH comb.pass_s+split.pass_s, including runtime trace record/commit, versus GSIM uninstrumented splitArray timer; stage-boundary setup/export excluded on both sides',
            'prefix+transform.pass': 'prefix plus native comb/split pass execution; individual GRH passes have no separate GSIM denominator',
            'comb-split.total': 'diagnostic full boundary: GRH comb+split including trace setup/finish/export versus GSIM uninstrumented splitArray',
            'ingest-through-split.total': 'diagnostic full boundary: GRH production wall before Session teardown versus GSIM supervisor wall including start-summary/log setup and subprocess exit'},
        'limitations': ['All supplied samples are retained; the tool cannot discover omitted runs or establish equal external machine load.',
            'GSIM native timers have integer millisecond precision and use gettimeofday; whole process wall uses a monotonic clock.',
            'GSIM Init contains hierarchy expansion and graph construction; its post-split detectLoop is not GRH comb-loop-elim.',
            'GSIM reads FIRRTL only; GRH manifest SV helper cost remains on the GRH side.',
            'Trace TSV setup/finish/export has no GSIM no-trace counterpart; full-boundary diagnostic comparisons expose total cost and do not decide the native pass performance gate.']}
    all_paths = [str(Path(path).resolve()) for path in (*grh_paths, *gsim_paths)]
    if len(set(all_paths)) != len(all_paths):
        report['errors'].append('every sample must be a distinct recorded run')
    for engine, paths, reader in (('gsim', gsim_paths, inspect_gsim), ('grh', grh_paths, inspect_sample)):
        if len(paths) < 3:
            report['errors'].append(engine + ': at least three samples are required')
        for path in paths:
            expected_cap_s = None
            try:
                if engine == 'grh':
                    raw = json.loads(Path(path).read_text(encoding='utf-8'))
                    if not isinstance(raw, dict):
                        raise ValueError('not an F30 raw-ingest pipeline benchmark summary')
                    references = report['samples']['gsim']
                    if not all(sample['accepted'] for sample in references):
                        raise ValueError('split timeout GSIM references were not verified')
                    started = raw.get('started_at_ns')
                    if type(started) is not int or started <= 0:
                        raise ValueError('missing GRH start time for split timeout reference validation')
                    evidence = timeout_reference_from_samples(references, raw, started)
                    if canonical(raw.get('split_timeout_reference')) != canonical(evidence):
                        raise ValueError('split timeout reference differs from the supplied frozen GSIM samples')
                    expected_cap_s = evidence['split_timeout_s']
                    report['split_timeout_reference'] = evidence
                    sample = reader(path, expected_cap_s=expected_cap_s)
                else:
                    sample = reader(path)
                if engine == 'grh':
                    prefix = sum(sample['metrics'][stage] for stage in ('ingest', 'xmr-resolve', 'hier-flatten'))
                    transform = sum(sample['metrics'][name] for name in ('comb-loop-elim', 'split-static-array'))
                    sample['common_metrics'] = {'prefix': prefix, 'comb-split.pass': transform,
                        'prefix+transform.pass': prefix + transform,
                        'comb-split.total': sample['metrics']['comb-split.total'],
                        'ingest-through-split.total': sample['raw']['wall_s']}
                    if sample['raw']['verify']:
                        report['errors'].append('GRH verify=1 correctness sample cannot enter the formal GSIM performance gate: ' + str(path))
                    if sample['raw']['configuration']['instrumentation'].get('profile_flatten', False):
                        report['errors'].append('GRH profile-flatten diagnostic sample cannot enter the formal GSIM performance gate: ' + str(path))
                    if sample['raw']['configuration']['instrumentation'].get('profile_split', False):
                        report['errors'].append('GRH profile-split diagnostic sample cannot enter the formal GSIM performance gate: ' + str(path))
                report['samples'][engine].append(sample)
            except (OSError, ValueError, TypeError, KeyError) as error:
                report['samples'][engine].append(rejected_sample(path, error, expected_cap_s=expected_cap_s))
                report['errors'].append(f'{engine} {path}: {error}')
    statuses = [sample.get('hard_limit', {}).get('status') for sample in report['samples']['grh']]
    if 'failed' in statuses:
        report['hard_limit'] = 'failed'
    elif statuses and all(status == 'passed' for status in statuses):
        report['hard_limit'] = 'passed'
    accepted = {engine: [sample for sample in rows if sample['accepted']]
                for engine, rows in report['samples'].items()}
    for engine, samples in accepted.items():
        for sample in samples[1:]:
            first = samples[0]
            fields = ('config', 'native', 'source_revision', 'identity_sha256') if engine == 'grh' else ('configuration', 'native_version')
            if any(canonical(sample[field]) != canonical(first[field]) for field in fields):
                report['errors'].append(engine + ': configuration or native version changed within the supplied samples')
        if samples and [sample['started_at_ns'] for sample in samples] != sorted(sample['started_at_ns'] for sample in samples):
            report['errors'].append(engine + ': sample order is not chronological')
    samples = accepted['grh'] + accepted['gsim']
    if samples:
        first_raw = samples[0]['raw']
        shared = {key: first_raw.get(key) for key in ('input', 'input_sha256', 'cpu_affinity')}
        shared['machine'] = {key: first_raw['configuration'].get(key) for key in MACHINE_FIELDS}
        report['shared_configuration'] = shared
        for sample in samples[1:]:
            raw = sample['raw']
            current = {key: raw.get(key) for key in ('input', 'input_sha256', 'cpu_affinity')}
            current['machine'] = {key: raw['configuration'].get(key) for key in MACHINE_FIELDS}
            if canonical(current) != canonical(shared):
                report['errors'].append('incompatible input/machine/CPU/thread configuration: ' + sample['path'])
        ordered = sorted(samples, key=lambda sample: sample['started_at_ns'])
        for previous, current in zip(ordered, ordered[1:]):
            if current['started_at_ns'] < previous['finished_at_ns']:
                report['errors'].append('benchmark execution intervals overlap: ' + current['path'])
        report['execution_order'] = [sample['path'] for sample in ordered]
    if report['errors']:
        return report
    report['mode'] = accepted['grh'][0]['raw']['mode']
    for metric in (*METRICS, *DIAGNOSTIC_METRICS):
        grh = [sample['common_metrics'][metric] for sample in accepted['grh']]
        gsim = [sample['metrics'][metric] for sample in accepted['gsim']]
        candidate, reference = statistics.median(grh), statistics.median(gsim)
        allowance = max(reference * jitter_relative, jitter_absolute_s)
        threshold = reference + allowance
        classification = ('strict_pass' if candidate <= reference else
                          'within_jitter' if candidate <= threshold else 'regression')
        destination = 'comparisons' if metric in METRICS else 'diagnostic_comparisons'
        report[destination].append({'metric': metric, 'scope': 'formal' if metric in METRICS else 'full-boundary diagnostic',
            'grh_s': grh, 'gsim_s': gsim,
            'grh_median_s': candidate, 'gsim_median_s': reference, 'delta_s': candidate - reference,
            'ratio': candidate / reference if reference else 1.0 if candidate == 0 else None,
            'allowed_jitter_s': allowance, 'threshold_s': threshold,
            'classification': classification, 'passed': classification != 'regression'})
    report['diagnostics'] = {'grh': [{'path': sample['path'], 'individual_passes': sample['metrics'],
        'trace_export_verification': sample['components'], 'whole_wall_s': sample['raw']['wall_s']}
        for sample in accepted['grh']],
        'gsim': [{'path': sample['path'], 'timers': sample['raw']['timers'],
                  'whole_wall_s': sample['raw']['wall_s']} for sample in accepted['gsim']]}
    report.update(complete=True, passed=all(row['passed'] for row in report['comparisons']))
    report['status'] = 'passed' if report['passed'] else 'regressed'
    report['relative'] = report['status']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, nargs='+', required=True)
    parser.add_argument('--gsim', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jitter-relative', type=float, default=MAX_JITTER_RELATIVE)
    parser.add_argument('--jitter-absolute-s', type=float, default=MAX_JITTER_ABSOLUTE_S)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    try:
        report = compare(args.grh, args.gsim, args.jitter_relative, args.jitter_absolute_s)
    except ValueError as error:
        parser.error(str(error))
    output.mkdir(parents=True, exist_ok=True)
    write_json = json.dumps(report, indent=2, allow_nan=False) + '\n'
    (output / 'comparison.json').write_text(write_json, encoding='utf-8')
    fields = ('metric', 'grh_median_s', 'gsim_median_s', 'delta_s', 'ratio',
              'allowed_jitter_s', 'threshold_s', 'classification', 'passed')
    with (output / 'comparison.tsv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in report['comparisons']:
            writer.writerow({key: row[key] for key in fields})
    with (output / 'diagnostic-comparison.tsv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in report['diagnostic_comparisons']:
            writer.writerow({key: row[key] for key in fields})
    print(json.dumps({key: report[key] for key in ('status', 'hard_limit', 'relative', 'errors')}, indent=2))
    return 0 if report['passed'] else 1 if report['complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
