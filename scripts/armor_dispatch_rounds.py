"""Per-round activity of the default XiangShan model, from the observer counts and traces.

usage: armor_dispatch_rounds.py counts|trace

`counts` uses the whole 100k window: how many fixed-point rounds each kind of
eval takes, where dispatch tests are visited and taken, and how well a fixed
guess per test site would do. `trace` uses the sampled windows of consecutive
guest cycles, which keep the joint activity of all supernodes in each round.
"""
import collections
import json
from pathlib import Path
import struct
import sys

from cv32e40p_compare import ROOT
from grhsim_single_baseline import save

OUT = ROOT / 'build/armor-dispatch-v1/obs'
CYCLES = 100001
PHASES = ('posedge', 'negedge', 'other')
KINDS = [f'{p} r{r}' + ('+' if r == 4 else '') for p in PHASES for r in (1, 2, 3, 4)]


def load_counts():
    evals = rounds = None
    groups, words, sites = {}, {}, {}
    for line in (OUT / 'counts.tsv').open():
        f = line.split('\t')
        if f[0] == 'E':
            evals = list(map(int, f[1:]))
        elif f[0] == 'R':
            rounds = list(map(int, f[1:]))
        elif f[0] in 'GW':
            v = list(map(int, f[2:]))
            (groups if f[0] == 'G' else words)[int(f[1])] = (v[0::2], v[1::2])
        else:
            sites[int(f[1])] = (int(f[2]), int(f[3]))
    return evals, rounds, groups, words, sites


def static_misses(table, per_kind):
    """Wrong guesses of the best fixed guess per site, or per site and round kind."""
    total = 0
    for seen, hit in table.values():
        if per_kind:
            total += sum(min(h, s - h) for s, h in zip(seen, hit))
        else:
            total += min(sum(hit), sum(seen) - sum(hit))
    return total


def counts():
    evals, rounds, groups, words, sites = load_counts()
    info = {int(k): v for k, v in json.loads((OUT / 'groups.json').read_text()).items()}
    word_info = json.loads((OUT / 'words.json').read_text())
    result = dict(evals=dict(zip(PHASES, evals)), rounds=dict(zip(KINDS, rounds)))
    print('evals', result['evals'])
    print(f"{'round kind':14s}{'rounds':>9s}{'word tests':>12s}{'non-empty':>11s}{'node tests':>12s}{'fired':>9s}   per guest cycle")
    table = []
    for k, name in enumerate(KINDS):
        if not rounds[k]:
            continue
        row = dict(kind=name, rounds=rounds[k],
                   word_tests=sum(v[0][k] for v in words.values()), word_hits=sum(v[1][k] for v in words.values()),
                   node_tests=sum(v[0][k] for v in groups.values()), node_fired=sum(v[1][k] for v in groups.values()))
        for phase in ('compute', 'commit'):
            row[f'{phase}_fired'] = sum(v[1][k] for g, v in groups.items() if info[g]['phase'] == phase)
            row[f'{phase}_word_hits'] = sum(v[1][k] for w, v in words.items() if word_info[w]['phase'] == phase)
        table.append(row)
        print(f"{name:14s}{rounds[k] / CYCLES:9.3f}{row['word_tests'] / CYCLES:12.0f}{row['word_hits'] / CYCLES:11.0f}"
              f"{row['node_tests'] / CYCLES:12.0f}{row['node_fired'] / CYCLES:9.0f}"
              f"   compute fired {row['compute_fired'] / CYCLES:.0f}, commit fired {row['commit_fired'] / CYCLES:.0f}")
    result['by_kind'] = table
    total_fired = sum(sum(v[1]) for v in groups.values())
    print(f"all rounds: word tests {sum(sum(v[0]) for v in words.values()) / CYCLES:.0f}, non-empty "
          f"{sum(sum(v[1]) for v in words.values()) / CYCLES:.0f}, node tests {sum(sum(v[0]) for v in groups.values()) / CYCLES:.0f}, "
          f"fired {total_fired / CYCLES:.0f}")

    # The round right after the rising-edge commit is where almost all compute work happens.
    main = max(range(len(KINDS)), key=lambda k: sum(v[1][k] for g, v in groups.items() if info[g]['phase'] == 'compute'))
    print('main round kind:', KINDS[main])
    buckets = [('>= 0.999', 0.999), ('0.9 - 0.999', 0.9), ('0.5 - 0.9', 0.5), ('0.1 - 0.5', 0.1), ('0.01 - 0.1', 0.01), ('< 0.01', 0.0)]
    stat = collections.defaultdict(collections.Counter)
    for g, (seen, hit) in groups.items():
        if info[g]['phase'] != 'compute':
            continue
        rate = hit[main] / rounds[main]
        name = next(n for n, low in buckets if rate >= low) if hit[main] else 'never'
        s = stat[name]
        s['supernodes'] += 1; s['main_fired'] += hit[main]; s['other_fired'] += sum(hit) - hit[main]
        s['likely_hint'] += bool(info[g]['likely'])
    never = sum(1 for g in info if info[g]['phase'] == 'compute' and g not in groups)
    print(f"{'fires per main round':22s}{'supernodes':>11s}{'hinted likely':>14s}{'main fires/cyc':>15s}{'share':>7s}{'other rounds/cyc':>17s}")
    classes = []
    for name in [n for n, _ in buckets] + ['never']:
        s = stat[name]
        if name == 'never':
            s['supernodes'] += never
        classes.append(dict(bucket=name, **s))
        print(f"{name:22s}{s['supernodes']:11d}{s['likely_hint']:14d}{s['main_fired'] / CYCLES:15.0f}"
              f"{100 * s['main_fired'] / total_fired:6.1f}%{s['other_fired'] / CYCLES:17.0f}")
    result['main_kind'] = KINDS[main]; result['classes'] = classes

    model = {}
    for name, table_ in (('word test', words), ('supernode test', groups)):
        model[name] = dict(one_guess_per_site=static_misses(table_, False) / CYCLES,
                           one_guess_per_site_and_round_kind=static_misses(table_, True) / CYCLES,
                           taken=sum(sum(v[1]) for v in table_.values()) / CYCLES)
        print(f"{name}: taken {model[name]['taken']:.0f}/cyc; wrong with one fixed guess per site "
              f"{model[name]['one_guess_per_site']:.0f}/cyc, per site and round kind "
              f"{model[name]['one_guess_per_site_and_round_kind']:.0f}/cyc")
    result['fixed_guess_model'] = model

    kinds = collections.defaultdict(collections.Counter)
    for line in (OUT / 'sites.tsv').open():
        f = line.rstrip('\n').split('\t')
        seen, hit = sites.get(int(f[0]), (0, 0))
        c = kinds[f[2], f[1]]
        c['sites'] += 1; c['seen'] += seen; c['hit'] += hit; c['wrong_fixed_guess'] += min(hit, seen - hit)
        c['never_hit'] += hit == 0
        c['writes'] += int(f[6])
    print(f"{'phase / site':26s}{'sites':>9s}{'never true':>11s}{'tests/cyc':>11s}{'true/cyc':>10s}{'true share':>11s}{'wrong fixed guess/cyc':>22s}")
    result['sites'] = {}
    for (phase, kind), c in sorted(kinds.items()):
        result['sites'][f'{phase} {kind}'] = dict(c)
        print(f"{phase + ' ' + kind:26s}{c['sites']:9d}{c['never_hit']:11d}{c['seen'] / CYCLES:11.0f}{c['hit'] / CYCLES:10.0f}"
              f"{100 * c['hit'] / max(1, c['seen']):10.2f}%{c['wrong_fixed_guess'] / CYCLES:22.0f}")
    save(OUT / 'rounds.json', result)


def records():
    groups = json.loads((OUT / 'groups.json').read_text())
    words = json.loads((OUT / 'words.json').read_text())
    group_bytes, word_bytes = (max(map(int, groups)) + 8) // 8, (len(words) + 7) // 8
    with (OUT / 'trace.bin').open('rb') as stream:
        while head := stream.read(12):
            cycle, phase, rnd = struct.unpack('<III', head)
            yield (cycle, phase, rnd, int.from_bytes(stream.read(group_bytes), 'little'),
                   int.from_bytes(stream.read(word_bytes), 'little'))


def bits(value):
    out = []
    while value:
        low = value & -value
        out.append(low.bit_length() - 1)
        value ^= low
    return out


def trace():
    words = json.loads((OUT / 'words.json').read_text())
    info = {int(k): v for k, v in json.loads((OUT / 'groups.json').read_text()).items()}
    compute_words = [i for i, w in enumerate(words) if w['phase'] == 'compute']
    # Word tests in execution order: compute batches run in numeric file order.
    batch_of = {}
    for i in compute_words:
        batch_of[i] = int(words[i]['file'].split('_')[-1].split('.')[0])
    order = sorted(compute_words, key=lambda i: (batch_of[i], i))
    position = {w: n for n, w in enumerate(order)}
    batches = sorted(set(batch_of.values()))
    batch_mask = {b: sum(1 << w for w in compute_words if batch_of[w] == b) for b in batches}
    compute_mask = sum(1 << g for g, v in info.items() if v['phase'] == 'compute')
    by_kind = collections.defaultdict(list)
    for cycle, phase, rnd, gbits, wbits in records():
        by_kind[phase, min(rnd, 4)].append((cycle, gbits & compute_mask, wbits))
    result = {}
    print(f"{'round kind':14s}{'rounds':>7s}{'active words':>13s}{'active nodes':>13s}{'non-empty batches':>18s}"
          + ''.join(f"{'chunk' + str(n):>9s}" for n in (8, 16, 64)) + '   word tests left if empty chunks are skipped')
    for (phase, rnd), rows in sorted(by_kind.items()):
        name = f'{PHASES[phase]} r{rnd}' + ('+' if rnd == 4 else '')
        n = len(rows)
        active_words = sum(bin(w & sum(batch_mask.values())).count('1') for _, _, w in rows) / n
        active_nodes = sum(bin(g).count('1') for _, g, _ in rows) / n
        nonempty = sum(sum(1 for b in batches if w & batch_mask[b]) for _, _, w in rows) / n
        left = {}
        for size in (8, 16, 64):
            total = 0
            for _, _, w in rows:
                chunks = {position[i] // size for i in bits(w) if i in position}
                total += len(chunks) * size
            left[size] = total / n
        result[name] = dict(rounds=n, active_words=active_words, active_nodes=active_nodes, nonempty_batches=nonempty,
                            word_tests_left=left, word_tests_now=len(order), batches=len(batches))
        print(f"{name:14s}{n:7d}{active_words:13.1f}{active_nodes:13.1f}{nonempty:13.1f}/{len(batches):<4d}"
              + ''.join(f'{left[s]:9.0f}' for s in (8, 16, 64)))

    # Main round: how regular is each supernode from one guest cycle to the next?
    main = max(by_kind, key=lambda key: sum(bin(g).count('1') for _, g, _ in by_kind[key]))
    rows = sorted(by_kind[main])
    column = collections.defaultdict(int)
    for index, (_, g, _) in enumerate(rows):
        for bit in bits(g):
            column[bit] |= 1 << index
    full = (1 << len(rows)) - 1
    always = [g for g, c in column.items() if c == full]
    consecutive = [i for i in range(1, len(rows)) if rows[i][0] == rows[i - 1][0] + 1]
    pair_mask = sum(1 << i for i in consecutive)
    flips = sum(bin((c ^ (c << 1)) & pair_mask).count('1') for c in column.values()) / max(1, len(consecutive))
    fires = sum(bin(c).count('1') for c in column.values()) / len(rows)
    patterns = collections.Counter(column.values())
    shared = sum(n for p, n in patterns.items() if n > 1 and p != full)
    print(f"main round {PHASES[main[0]]} r{main[1]}: {len(rows)} sampled rounds, {fires:.0f} compute supernodes fire per round")
    print(f"  fire in every sampled main round: {len(always)} supernodes ({100 * len(always) / fires:.1f}% of fires)")
    print(f"  ever fire: {len(column)}; change state between consecutive cycles: {flips:.0f} per cycle")
    print(f"  distinct activity patterns among those that are not always on: {len(patterns) - (full in patterns)}; "
          f"supernodes sharing a pattern with another: {shared}")
    top = [(bin(p).count('1'), n) for p, n in patterns.most_common(12) if p != full]
    print('  largest groups with one common pattern (rounds active, supernodes):', top)
    result['main'] = dict(kind=f'{PHASES[main[0]]} r{main[1]}', rounds=len(rows), fires=fires, always=len(always),
                          ever=len(column), flips_per_cycle=flips, patterns=len(patterns), sharing=shared)
    save(OUT / 'trace.json', result)
    save(OUT / 'always.json', sorted(always))


if __name__ == '__main__':
    {'counts': counts, 'trace': trace}[sys.argv[1]]()
