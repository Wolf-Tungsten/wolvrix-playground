"""Summarize the four XiangShan models using paired external wall times."""
import csv
import random
import statistics

from armor_acc_compare import OUT
from grhsim_single_compare import summarize
from xiangshan_cv32_ablation_measure import read, save, signature


def main():
    dest = OUT / 'measurement-commit-bank'
    rounds = read(dest / 'rounds.json')
    policy = read(dest / 'measurement-policy.json')
    summary = read(dest / 'summary.json')
    models = read(dest / 'manifest.json')['models']
    assert len(rounds) == 8 and [row['order'] for row in rounds] == policy['order']

    with (dest / 'samples.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['round', 'position', 'variant', 'wall_s', 'host_s', 'cpu288_idle_pct'])
        for i, row in enumerate(rounds, 1):
            for position, name in enumerate(row['order'], 1):
                sample = row[name]
                assert signature(sample) == summary['functional_signature']
                assert sample['binary_sha256'] == models[name]['binary']['sha256']
                assert sample['cpu'] == 96 and sample['numa_node'] == sample['max_threads'] == 1
                assert sample['locality_pass'] and not sample['diagnostic'] and sample['seed'] == 0
                writer.writerow([i, position, name, sample['external_wall_s'], sample['host_ms'] / 1000,
                                 sample['sibling_idle']['288']])

    contrasts = {}
    for base, candidate in [('full', 'group'), ('full', 'bank'), ('full', 'both'),
                            ('group', 'both'), ('bank', 'both')]:
        pairs = [{'A': {'host_ms': row[base]['external_wall_s'] * 1000},
                  'B': {'host_ms': row[candidate]['external_wall_s'] * 1000}} for row in rounds]
        stats = summarize(pairs)
        if base == 'full':
            assert stats['delta_percent_ci95'] == summary['comparisons'][candidate]['external_wall_s']['delta_percent_ci95']
        contrasts[f'{candidate}/{base}'] = stats

    # Extra seconds saved by commit grouping with the bank active vs. with it off.
    interaction = [(row['bank']['external_wall_s'] - row['both']['external_wall_s'])
                   - (row['full']['external_wall_s'] - row['group']['external_wall_s']) for row in rounds]
    rng = random.Random(20261102)
    boot = sorted(statistics.mean(rng.choices(interaction, k=len(interaction))) for _ in range(10000))
    save(dest / 'factorial.json', dict(metric='external_wall_s', comparisons=contrasts,
        additional_group_savings_with_bank_s=dict(mean=statistics.mean(interaction), ci95=[boot[249], boot[9749]],
                                                   per_round=interaction)))


if __name__ == '__main__':
    main()
