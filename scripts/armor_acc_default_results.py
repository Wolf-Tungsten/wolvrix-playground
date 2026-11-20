"""Recompute the paired walltime comparison and verify all timed samples."""
import csv
import statistics

from grhsim_single_baseline import ROOT, save
from grhsim_single_compare import summarize
from xiangshan_cv32_ablation_measure import read, signature, verify

OUT = ROOT / 'build/armor-acc-default-v1/perf-regression'
timing = OUT/'timing'
policy = read(OUT/'policy.json')
summary = read(timing/'summary.json')
pairs = read(timing/'pairs.json')
assert len(pairs) == 8 and [r['order'] for r in pairs] == policy['rounds']
assert summary['samples'] == pairs
stats = summarize([{side: {'host_ms': pair[side]['external_wall_s'] * 1000}
                    for side in ('A','B')} for pair in pairs])
assert stats == summary['external_wall']
expected = policy['signature']
checks = {}
for side in ('A','B'):
    inputs = policy['inputs'][side]
    for k in ('image','nemu','binary'):
        verify(inputs[k])
    verify(policy['verification'][side])
    env = read(timing/side/'runs/environment.json')
    assert env['host'].split('.')[0] == 'node030' and env['numa_node'] == 1 and env['cpu'] == 96
    assert env['aslr'] == 'disabled' and sorted(env['siblings']) == [96,288]
    assert read(timing/side/'runs/input_identity.json') == inputs
    for i,row in enumerate(pairs):
        sample = row[side]
        assert row['pair'] == i and sample == read(timing/side/'runs'/f'pair{i:02d}.json')
        assert sample['cpu'] == 96 and sample['numa_node'] == sample['max_threads'] == 1
        assert sample['seed'] == 0 and sample['locality_pass'] and not sample['diagnostic']
        assert sample['binary_sha256'] == inputs['binary']['sha256']
        assert signature(sample) == expected
        args = read(timing/side/'runs'/f'pair{i:02d}.command.json')
        assert '--dump-difftrace' not in args and '--force-dump-result' not in args and args[-2:] == ['-C','100000']
    checks[side] = dict(cpu288_idle_min_percent=min(r[side]['sibling_idle']['288'] for r in pairs),
                        wall_s_min=min(r[side]['external_wall_s'] for r in pairs),
                        wall_s_max=max(r[side]['external_wall_s'] for r in pairs))
for trace in summary['trace_checks']:
    assert trace['pass_'] and trace['records'] == 99999 and all(v['pass_'] for v in trace['coverage'])
assert len(summary['trace_checks']) == 2
anchors = {}
if policy['previous_default']:
    old = policy['previous_default']['binary']
    verify(old)
    for sample in summary['historical']:
        assert sample['binary_sha256'] == old['sha256'] and signature(sample) == expected
        assert sample['cpu'] == 96 and sample['numa_node'] == sample['max_threads'] == 1 and sample['locality_pass']
        anchors[sample['name']] = sample['external_wall_s']
    assert list(anchors) == policy['previous_default']['samples']
by_order = {}
for order in (['A','B'],['B','A']):
    deltas = [100 * (p['B']['external_wall_s'] / p['A']['external_wall_s'] - 1) for p in pairs if p['order'] == order]
    by_order[''.join(order)] = statistics.mean(deltas)
with (OUT/'paired-walltime.csv').open('w', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['round','order','off_wall_s','default_wall_s','saved_s','wall_delta_percent',
                     'off_host_s','default_host_s','off_cpu288_idle_percent','default_cpu288_idle_percent'])
    for pair in pairs:
        off, default = pair['A'], pair['B']
        a, b = off['external_wall_s'], default['external_wall_s']
        order = ['off' if name == 'A' else 'default' for name in pair['order']]
        writer.writerow([pair['pair']+1,'>'.join(order),a,b,a-b,100*(b/a-1),
                         off['host_ms']/1000,default['host_ms']/1000,
                         off['sibling_idle']['288'],default['sibling_idle']['288']])
save(OUT/'verified-stats.json', dict(status='pass', wall=stats,
    host_percent=summary['delta_percent_mean'], host_ci95=summary['delta_percent_ci95'],
    mean_saved_s=stats['baseline_s_mean'] - stats['candidate_s_mean'],
    wall_delta_percent_by_order=by_order, timed_samples=16, placement=checks, signature=expected,
    previous_default_s=anchors))
