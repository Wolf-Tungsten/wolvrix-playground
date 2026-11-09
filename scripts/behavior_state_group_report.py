#!/usr/bin/env python3
"""Audit completed local H/O/G experiments without building or running models."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'wolvrix/build/artifacts/behavior-state-group'


def read(path):
    return json.loads(path.read_text())


def identity(path):
    return dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def config(path):
    line = next(x for x in path.read_text().splitlines()
                if 'activity-schedule max_op_in_compute_supernode=' in x)
    return dict(re.findall(r'(\w+)=([^ ]+)', line))


def structure(model):
    stats = read(model / 'activity_schedule_supernode_stats.json')
    header = (model / 'grhsim_BehaviorGroupFixture.hpp').read_text()
    scalar = re.search(r'struct state_logic_storage_t \{(.*?)\n    \};', header, re.S)
    regs = re.findall(r'std::uint(\d+)_t\s+u\d+_slots_\d+;', scalar[1]) if scalar else []
    memories = re.findall(r'std::array<std::uint(\d+)_t, (\d+)> state_mem_', header)
    def constant(name):
        return int(re.search(r'\b' + name + r' = (\d+);', header)[1])
    files = list(model.glob('grhsim_*.cpp'))
    return dict(
        **{k: stats[k] for k in ('graph_ops', 'compute_supernodes', 'commit_sink_ops',
                                 'boundary_activation_edges', 'commit_event_keys')},
        register_slots=len(regs), register_payload_bytes=sum(int(w) // 8 for w in regs),
        memories=len(memories), memory_rows=sum(int(n) for _, n in memories),
        memory_payload_bytes=sum(int(w) // 8 * int(n) for w, n in memories),
        state_shadow_count=constant('kStateShadowCount'),
        event_edge_storage_bytes=constant('kEventEdgeStorageBytes'),
        cpp_files=len(files), cpp_bytes=sum(p.stat().st_size for p in files),
        binary=identity(model / 'check'),
        generated_sources=[identity(p) for p in sorted(files)],
    )


def main():
    report = dict(
        scope='local fixtures only; no new full XiangShan or A/A measurement',
        variants={'H': 'original indexed Reg/Vec writes, production optimization',
                  'O': 'semantic carrier fallback, ordinary GRH, production optimization',
                  'G': 'the same carrier, grouped GRH, production optimization'},
        guards=read(BASE / 'guards/summary.json'),
        contracts=read(BASE / 'contracts-v2/summary.json'),
        net_zero_log=(BASE / 'simple-v2/G-diagnostic/net-zero.log').read_text(),
        fixtures={},
    )
    old_config = config(ROOT / 'build/xs/behavior_commit_rat_20261105_v10/A/logs/emit.log')
    frozen_hashes = set()
    for name, timing, diagnostic in [('simple-final', 'timing-v2', 'simple-v2'),
                                      ('rat-final', 'timing-v1', 'rat-v1')]:
        root = BASE / name
        checks = read(root / 'check-summary.json')
        assert len(checks) == 9 and all(x['pass_'] for x in checks)
        assert read(root / timing / 'complete.json')['pass_']
        manifest = read(root / 'model/simulation_models.json')
        binding = manifest['models'][0]['binding']
        diagnostic_text = read(BASE / diagnostic / 'diagnostic-summary.json')
        fixtures = dict(
            checks=checks, binding=binding, timing=read(root / timing / 'summary.json'),
            runs=read(root / timing / 'runs.json'), runtime=read(root / timing / 'manifest.json'),
            artifacts=[identity(p) for p in sorted((root / timing).glob('*.csv'))],
            diagnostics={v: dict((k, int(n)) for k, n in re.findall(r'(\w+)=(\d+)', text))
                         for v, text in diagnostic_text.items()},
            diagnostic_note='10,000 cycles, four evals/cycle including repeated/same-edge checks; '
                            'timings use two evals/cycle. memory_reads counts scheduled memory-read '
                            'ports, not all host loads. H/O changed_rows includes intermediate writes.',
            structure={}, config_diff_from_full_xs={},
            inputs=[identity(root / mode / file) for mode in ('hardware', 'model')
                    for file in ('BehaviorGroupFixture.sv', 'simulation_models.json')],
        )
        for v in 'HOG':
            fixtures['structure'][v] = structure(root / v / 'model')
            local_config = config(root / v / 'emit.log')
            diff = {k: [old_config.get(k), local_config.get(k)]
                    for k in old_config.keys() | local_config.keys()
                    if old_config.get(k) != local_config.get(k)}
            assert set(diff) <= {'pre_reg_to_mem_json', 'post_stats_json'}
            fixtures['config_diff_from_full_xs'][v] = diff
            assert identity(root / v / 'model/check')['sha256'] == fixtures['runtime']['variants'][v]['original']['sha256']
        for x in read(root / 'tools-frozen/identity.json'):
            if x['path'].endswith('/_wolvrix.so'):
                frozen_hashes.add(x['sha256'])
                assert hashlib.sha256((root / 'tools-frozen' / x['path']).read_bytes()).hexdigest() == x['sha256']
        for scenario in fixtures['timing']:
            runs = [r for r in fixtures['runs'] if r['scenario'] == scenario]
            assert len(runs) == 27 and len({r['hash'] for r in runs}) == 1
            assert not read(root / timing / (scenario + '-during.json'))['busy']
        report['fixtures'][name] = fixtures
    assert len(frozen_hashes) == 1
    report['frozen_native_sha256'] = frozen_hashes.pop()
    report['local_gate'] = {
        name: all(s['G_vs_O']['delta_percent_ci95'][1] < -5 and
                  s['G_vs_H']['delta_percent_ci95'][1] < 0 for s in f['timing'].values())
        for name, f in report['fixtures'].items()
    }
    report['decision'] = ('RAT local gate passed; small arrays did not pass. Keep ordinary/hardware '
                          'defaults, grouped is experimental. Full S3 capability/trace/NEMU and '
                          'whole-system speed remain unverified for grouped lowering.')
    (BASE / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(local_gate=report['local_gate'], native=report['frozen_native_sha256'])))


if __name__ == '__main__':
    main()
