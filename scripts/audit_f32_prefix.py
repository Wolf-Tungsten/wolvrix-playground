"""Check fresh F32 P0 inventory rows against the frozen F31 first-DCE output.

Equal row fingerprints prove exact static identity/connection preservation.
Different fingerprints require investigation; they do not prove a behavior bug.
This audit intentionally does not interpret snapshot session/stage metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

from capture_f32_pipeline import table_artifact


ROOT = Path(__file__).resolve().parents[1]


def fingerprint(path):
    artifact = table_artifact(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for line in stream:
            if not line.startswith(b'#'):
                digest.update(line)
    return {**artifact, 'header_and_rows_sha256': digest.hexdigest()}


def row_samples(before, after, limit=8):
    with before.open() as old, after.open() as new:
        old_rows = (line.rstrip('\n') for line in old if not line.startswith('#'))
        new_rows = (line.rstrip('\n') for line in new if not line.startswith('#'))
        samples = []
        for index, (left, right) in enumerate(itertools.zip_longest(old_rows, new_rows)):
            if left != right:
                samples.append({'body_row': index, 'f31': left, 'f32': right})
                if len(samples) == limit:
                    break
        return samples


def audit(capture, baseline, output, *, allow_incomplete_run=False):
    summary = json.loads((capture / 'summary.json').read_text())
    if (summary.get('schema') != 'wolvrix.f32.pipeline-capture.v1' or
            summary.get('status') not in (('completed', 'failed') if allow_incomplete_run else ('completed',)) or
            summary.get('source') != 'raw-firrtl'):
        raise ValueError('requires completed raw-FIRRTL F32 capture')
    engine = summary['engine']
    result = {'schema': 'wolvrix.f32.prefix-audit.v1', 'engine': engine,
              'input_sha256': summary['input_sha256'], 'capture': str(capture),
              'baseline': str(baseline), 'trace_validation': False,
              'capture_status': summary['status'], 'capture_complete': summary['status'] == 'completed',
              'scope': 'exact static Node/connection rows; not functional equivalence', 'tables': {}}
    for name in ('nodes.tsv', 'connections.tsv'):
        old_path, new_path = baseline / name, capture / 'P0' / name
        before, after = fingerprint(old_path), fingerprint(new_path)
        for table in (before, after):
            if table['metadata'].get('engine') != engine:
                raise ValueError('wrong engine in prefix inventory')
        frozen = summary['snapshots']['P0'].get('artifacts', {}).get(name)
        if frozen is None and summary['status'] == 'completed':
            raise ValueError('completed capture lacks frozen P0 table identity')
        if frozen and (frozen['sha256'] != after['sha256'] or frozen['bytes'] != after['bytes']):
            raise ValueError('fresh P0 table changed since capture')
        same = before['header_and_rows_sha256'] == after['header_and_rows_sha256']
        result['tables'][name] = {'unchanged': same, 'f31': before, 'f32': after,
                                  'f32_hash_bound_by_final_capture_summary': frozen is not None,
                                  'first_row_differences': [] if same else row_samples(old_path, new_path)}
    result['static_rows_unchanged'] = all(row['unchanged'] for row in result['tables'].values())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'engine': engine, 'static_rows_unchanged': result['static_rows_unchanged'],
                      'output': str(output)}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete-run', action='store_true',
                        help='diagnose complete native P0 tables from a failed later boundary; never treats run as completed')
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / 'ptmp'):
        parser.error('audit output must be under repository ptmp/')
    audit(args.capture.resolve(), args.baseline.resolve(), args.output,
          allow_incomplete_run=args.allow_incomplete_run)


if __name__ == '__main__':
    main()
