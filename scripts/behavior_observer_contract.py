#!/usr/bin/env python3
"""Reject functional feedback after an explicitly owned debug delay."""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/grhsim32-tools/python'))
import wolvrix
from wolvrix.behavior_state import lower_behavior_state, validate_observer_state_feedback


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, required=True)
    args = p.parse_args()
    root = args.fixture.resolve()
    raw = json.loads((root/'G/model/behavior_before.json').read_text())
    manifest = json.loads((root/'rtl/simulation_models.json').read_text())
    imported = lower_behavior_state(raw, manifest, root/'rtl')
    originals = [g for g in imported['graphs'] if g['symbol'].startswith('DelayReg')]
    clones = [g for g in imported['graphs'] if g['symbol'].startswith('WolvrixObserverDomain_v1_0_DelayReg')]
    assert originals and clones
    assert not any('behavior.observerDomain' in o.get('attrs', {}) for g in originals for o in g['ops'])
    assert any('behavior.observerDomain' in o.get('attrs', {}) for g in clones for o in g['ops'])
    altered = copy.deepcopy(manifest)
    clock = next(p for p in altered['observer_domains'][0]['ports'] if p['name'] == 'clock')
    clock['width'] = 2
    try:
        lower_behavior_state(raw, altered, root/'rtl')
    except ValueError as e:
        assert 'observer domain port mismatch' in str(e)
    else:
        raise AssertionError('incorrect domain port accepted')
    design = json.loads((root/'G/pre.json').read_text())
    validate_observer_state_feedback(design)
    graph = next(g for g in design['graphs'] if g['symbol'] == 'BehaviorDifftestStudy')
    ops = graph['ops']
    group = next(o for o in ops if o['kind'] == 'kBehaviorStateGroup')
    users = {}
    readers = {}
    writes = {'kRegisterWritePort': 'regSymbol', 'kMemoryWritePort': 'memSymbol', 'kMemoryFillPort': 'memSymbol'}
    for op in ops:
        for v in op['in']: users.setdefault(v, []).append(op)
        if op['kind'] in ('kRegisterReadPort', 'kMemoryReadPort'):
            symbol = op['attrs']['regSymbol' if op['kind'] == 'kRegisterReadPort' else 'memSymbol']['v']
            readers.setdefault(symbol, []).extend(op['out'])
    todo = list(readers[group['attrs']['memSymbol']['v']]);seen = set();data = None
    while todo and data is None:
        v = todo.pop()
        if v in seen: continue
        seen.add(v)
        for op in users.get(v, []):
            if op['kind'] in writes:
                reads = readers.get(op['attrs'][writes[op['kind']]]['v'], [])
                if reads: data = reads[0]; break
            todo.extend(op['out'])
    assert data is not None, 'fixture must contain a delay downstream of the group'
    width = next(v['w'] for v in graph['vals'] if v['sym'] == data)
    def attr(v): return dict(t='int' if isinstance(v, int) else 'string', v=v)
    graph['vals'].append(dict(sym='observer_leak_mask', w=width, sgn=False, type='logic',
                             **{'in': False, 'out': False, 'inout': False}))
    ops.extend([
        dict(sym='observer_leak_register', kind='kRegister', **{'in': [], 'out': []}, attrs={'width': attr(width)}),
        dict(sym='observer_leak_mask_op', kind='kConstant', **{'in': [], 'out': ['observer_leak_mask']},
             attrs={'constValue': attr(f"{width}'d{(1 << width)-1}")}),
        dict(sym='observer_leak_write', kind='kRegisterWritePort',
             **{'in': [group['in'][0], data, 'observer_leak_mask', group['in'][-1]], 'out': []},
             attrs={'regSymbol': attr('observer_leak_register'), 'eventEdge': dict(t='string[]', vs=['posedge'])}),
    ])
    try:
        validate_observer_state_feedback(design)
    except ValueError as e:
        assert 'observer group feeds unowned' in str(e)
    else:
        raise AssertionError('functional feedback through debug delay accepted')
    with wolvrix.Session() as session:
        session.load_json_text(json.dumps(design))
        session.diagnostics_raise_min_level = 'none'
        session.diagnostics_print_min_level = 'none'
        diags = session.emit_sv(design='design.main', output=str(root/'rejected-feedback.sv'), top=['BehaviorDifftestStudy'])
        assert not session.history()[-1]['success']
        assert any('observer group feeds unowned' in d.get('message', '') for d in diags)
    result = dict(pass_=True, cases=['typed-domain-port-rejection', 'shared-module-isolation',
        'valid-observer-delay', 'python-feedback-after-delay-rejection', 'native-feedback-after-delay-rejection'])
    (root/'observer-contract.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
