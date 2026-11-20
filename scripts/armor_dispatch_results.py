"""Tables of TNO0016 recomputed from the raw records under build/armor-dispatch-v1.

usage: armor_dispatch_results.py counts <variant> ...     event counts per guest cycle (node029)
       armor_dispatch_results.py branches <sample dir> ... sampled mispredictions by statement category
       armor_dispatch_results.py timing <tag> [<csv>]      rounds of one timing session (node030 CPU96)

`branches` scales every row by counted over sampled operations of the same build, because the kernel
drops samples above its rate limit and the faster builds lost up to a fifth of them.
"""
import json
from pathlib import Path
import random
import statistics
import sys

from cv32e40p_compare import ROOT

OUT = ROOT / 'build/armor-dispatch-v1'
EVENTS = [('ex_ret_brn', 'branches'), ('ex_ret_brn_tkn', 'taken branches'), ('ex_ret_brn_misp', 'mispredicted'),
          ('bp_de_redirect', 'decode redirects'), ('ic_cache_fill_l2', 'L1I fills from L2'),
          ('ic_cache_fill_sys', 'L1I fills beyond L2'), ('bp_l1_tlb_miss_l2_tlb_miss.all', 'iTLB walks'),
          ('instructions', 'instructions')]
GROUPS = [('value expressions', ('compute|local expression', 'compute|next value expression')),
          ('supernode tests', ('compute|supernode test',)),
          ('word tests', ('compute|word test', 'commit|word test')),
          ('commit state compares', ('commit|state compare',)),
          ('commit write enable tests', ('commit|write enable test',)),
          ('compute change checks', ('compute|value compare',))]


def per_cycle(variant, event, window=0):
    run = json.loads((OUT / 'pmu' / variant / 'summary.json').read_text())['runs'][window]
    return run['counts'][event]['count'] / (run['cycles'] + 1)


def counts(variants):
    base = variants[0]
    print(f"{'per guest cycle':22s}" + ''.join(f'{v:>20s}' for v in variants))
    for event, title in EVENTS:
        row = f'{title:22s}'
        for v in variants:
            x = per_cycle(v, event)
            row += f'{x:11.0f}' + (f'{100 * (x / per_cycle(base, event) - 1):+8.1f}%' if v != base else ' ' * 9)
        print(row)


def branches(directories):
    for directory in directories:
        d = json.loads((Path(directory) / 'summary.json').read_text())
        run = json.loads((Path(directory) / 'run.json').read_text())
        variant = Path(run['binary']['path']).parents[2].name
        counted = {'lines': 'lines', 'cmovlines': 'cmov', 'eager4096lines': 'eager4096',
                   'eager4096cmovlines': 'eager4096cmov', 'pgolines': 'pgo'}[variant]
        scale = d['period'] / d['guest_cycles']
        sampled_ops = d['regions']['_all']['samples'] * scale
        k = per_cycle(counted, 'ex_ret_ops') / sampled_ops
        total = d['regions']['_all']
        print(f"== {Path(directory).name}: sampled operations are {100 / k:.1f}% of the counted ones; "
              f"mispredicted per guest cycle {total['mispredicted'] * scale * k:.0f} sampled, "
              f"{per_cycle(counted, 'ex_ret_brn_misp'):.0f} counted")
        print(f"{'':28s}{'branches':>10s}{'taken':>9s}{'mispred':>9s}{'share':>8s}")
        rest = dict(total)
        for title, names in GROUPS:
            v = {f: sum(d['categories'].get(n, {}).get(f, 0) for n in names) for f in ('branches', 'taken', 'mispredicted')}
            for f in v:
                rest[f] -= v[f]
            print(f"{title:28s}{v['branches'] * scale * k:10.0f}{v['taken'] * scale * k:9.0f}{v['mispredicted'] * scale * k:9.0f}"
                  f"{100 * v['mispredicted'] / total['mispredicted']:7.1f}%")
        print(f"{'everything else':28s}{rest['branches'] * scale * k:10.0f}{rest['taken'] * scale * k:9.0f}"
              f"{rest['mispredicted'] * scale * k:9.0f}{100 * rest['mispredicted'] / total['mispredicted']:7.1f}%")
        print(f"{'all':28s}{total['branches'] * scale * k:10.0f}{total['taken'] * scale * k:9.0f}"
              f"{total['mispredicted'] * scale * k:9.0f}")


def interval(deltas):
    rng = random.Random(20261102)
    boot = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000))
    return boot[249], boot[9749]


def timing(tag, csv=None):
    rows = json.loads((OUT / f'timing-{tag}' / 'rounds.json').read_text())
    names = json.loads((OUT / f'timing-{tag}' / 'policy.json').read_text())['variants']
    assert len(rows) == 8, f'{len(rows)} of 8 rounds recorded'
    for metric, title in (('external_wall_s', 'walltime'), ('host_ms', 'Host time')):
        unit = 1 if metric == 'external_wall_s' else 1000
        print(f'== {title}, seconds; change is the mean of eight same-round ratios, interval from a paired bootstrap')
        for name in names:
            values = [row[name][metric] / unit for row in rows]
            line = f'{name:20s} mean {statistics.mean(values):7.2f}  min {min(values):7.2f}  max {max(values):7.2f}'
            for reference in names[:names.index(name)]:
                deltas = [100 * (row[name][metric] / row[reference][metric] - 1) for row in rows]
                low, high = interval(deltas)
                line += (f'\n    vs {reference:18s} {statistics.mean(deltas):+7.2f}%  [{low:+.2f}%, {high:+.2f}%]  '
                         f'faster in {sum(x < 0 for x in deltas)}/8')
            print(line)
    if csv:
        with open(csv, 'w') as stream:
            stream.write('round,position,variant,walltime_s,host_s\n')
            for row in rows:
                for position, name in enumerate(row['order']):
                    stream.write(f"{row['round'] + 1},{position + 1},{name},{row[name]['external_wall_s']:.3f},"
                                 f"{row[name]['host_ms'] / 1000:.3f}\n")
        print('wrote', csv)


if __name__ == '__main__':
    stage = sys.argv[1]
    if stage == 'counts':
        counts(sys.argv[2:])
    elif stage == 'branches':
        branches(sys.argv[2:])
    else:
        timing(*sys.argv[2:4])
