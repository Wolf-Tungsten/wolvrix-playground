#!/usr/bin/env python3
"""Focused manifest/carrier contract checks for kBehaviorComputeGroup."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys


def expect_failure(fn):
    try:
        fn()
    except (ValueError, KeyError, AssertionError):
        return True
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    study = args.study.resolve()
    module_path = Path(__file__).resolve().parents[1] / 'wolvrix/app/pybind/wolvrix/behavior_compute.py'
    spec = importlib.util.spec_from_file_location('behavior_compute_check_module', module_path)
    behavior_compute = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(behavior_compute)
    lower_behavior_compute = behavior_compute.lower_behavior_compute

    records = []
    for kind in ('int-mul', 'vec-int-mul', 'fp-mul', 'vec-fp-mul'):
        root = study / kind / 'B'
        manifest = json.loads((root / 'rtl/simulation_models.json').read_text())
        before = json.loads((root / 'model/behavior_before.json').read_text())
        imported = json.loads((root / 'model/behavior_imported.json').read_text())
        lowered = lower_behavior_compute(before, manifest, root / 'rtl')
        assert lowered == imported
        groups = [op for g in lowered['graphs'] for op in g.get('ops', [])
                  if op.get('kind') == 'kBehaviorComputeGroup']
        assert len(groups) == 1
        group = groups[0]
        model = manifest['models'][0]
        assert group['attrs']['behavior.model']['v'] == kind
        assert group['attrs']['behavior.observerOnly']['v'] is False
        assert group['attrs']['behavior.stateful']['v'] is False
        assert group['attrs']['behavior.inputWidths']['vs'] == [p['width'] for p in model['compute_ports'] if p['direction'] == 'input']
        assert group['attrs']['behavior.outputWidths']['vs'] == [p['width'] for p in model['compute_ports'] if p['direction'] == 'output']

        bad_hash = copy.deepcopy(manifest)
        bad_hash['models'][0]['compute_binding']['semantic_sha256'] = '0' * 64
        bad_ports = copy.deepcopy(manifest)
        bad_ports['models'][0]['compute_binding']['ports'][0]['width'] += 1
        bad_model = copy.deepcopy(manifest)
        bad_model['models'][0]['compute_binding']['model'] = 'unknown'
        records.append({
            'kind': kind,
            'group_symbol': group['sym'],
            'input_widths': group['attrs']['behavior.inputWidths']['vs'],
            'output_widths': group['attrs']['behavior.outputWidths']['vs'],
            'reject_bad_hash': expect_failure(lambda: lower_behavior_compute(before, bad_hash, root / 'rtl')),
            'reject_bad_ports': expect_failure(lambda: lower_behavior_compute(before, bad_ports, root / 'rtl')),
            'reject_unknown_model': expect_failure(lambda: lower_behavior_compute(before, bad_model, root / 'rtl')),
        })
        assert all(records[-1][key] for key in ('reject_bad_hash', 'reject_bad_ports', 'reject_unknown_model'))

    result = {'pass': True, 'models': records, 'scope': 'carrier version/ports/hash/model rejection and exact lowering'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
