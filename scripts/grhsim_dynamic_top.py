"""Rank measured batch intervals per partition/clock; never rank RTL line times."""
from collections import Counter, defaultdict


SCOPES = ('stable_last', 'all_sampled')
COUNTS = ('ns', 'calls', 'entry_nonzero_calls', 'entry_zero_ns')


def _order(key, mapping):
    batch = mapping['batches'][key]
    return batch['phase'], batch['batch']


def _winners(scores, mapping):
    if not scores:
        return []
    maximum = max(c['ns'] for c in scores.values())
    return sorted((key for key, c in scores.items() if c['ns'] == maximum),
                  key=lambda key: _order(key, mapping))


def rank_dynamic_batches(mapping, probes):
    """Keep independent repeats, critical-step labels and clock levels separate.

    ``stable_last`` uses labels frozen by wrapper-only discovery. Fine probes
    must not elect their own critical partition: instrumentation delays it.
    ``all_sampled`` is a local cost ranking, including noncritical steps.
    """
    parts = sorted({b['part'] for b in mapping['batches'].values()})
    by_part = defaultdict(list)
    for probe in probes:
        part = probe['header']['selected_part']
        if part not in parts:
            raise ValueError(f'probe partition absent from mapping: {part}')
        scores = defaultdict(lambda: defaultdict(Counter))
        waves = defaultdict(Counter)
        for row in probe['batches']:
            key = row['batch_key']
            if key not in mapping['batches'] or mapping['batches'][key]['part'] != part:
                raise ValueError('dynamic batch belongs to a different partition')
            if row['clock'] not in (0, 1) or row['scope'] not in ('stable_last', 'other'):
                raise ValueError('invalid dynamic clock/scope')
            if any(row.get(name, 0) < 0 for name in COUNTS):
                raise ValueError('negative dynamic counter')
            if row.get('entry_zero_ns', 0) > row['ns']:
                raise ValueError('entry-zero time exceeds batch time')
            scopes = SCOPES if row['scope'] == 'stable_last' else ('all_sampled',)
            for scope in scopes:
                c = scores[row['clock'], scope][key]
                c.update({name: row.get(name, 0) for name in COUNTS})
                c['max_call_ns'] = max(c['max_call_ns'], row.get('max_call_ns', 0))
                waves[row['clock'], scope, key][row['wave']] += row['ns']
        coverage = defaultdict(Counter)
        for row in probe.get('sample_coverage', []):
            scopes = SCOPES if row['scope'] == 'stable_last' else ('all_sampled',)
            for scope in scopes:
                coverage[row['clock'], scope].update(
                    {name: row[name] for name in ('sampled_steps', 'steps_with_batches')})
        by_part[part].append((scores, waves, coverage, 'sample_coverage' in probe))

    rows = []
    for part in parts:
        runs = by_part[part]
        for clock in (0, 1):
            for scope in SCOPES:
                totals = defaultdict(Counter)
                wave_totals = defaultdict(Counter)
                coverage = Counter()
                repeats = []
                for repeat, (scores, waves, cov, known) in enumerate(runs):
                    current = scores[clock, scope]
                    coverage.update(cov[clock, scope])
                    for key, c in current.items():
                        totals[key].update({name: c[name] for name in COUNTS})
                        totals[key]['max_call_ns'] = max(totals[key]['max_call_ns'], c['max_call_ns'])
                        wave_totals[key].update(waves[clock, scope, key])
                    winners = _winners(current, mapping)
                    repeats.append(dict(repeat=repeat, top_keys=winners,
                        top_ns=current[winners[0]]['ns'] if winners else None,
                        sampled_steps=cov[clock, scope]['sampled_steps'] if known else None))
                known = bool(runs) and all(run[3] for run in runs)
                winners = _winners(totals, mapping)
                row = dict(part=part, clock=clock, scope=scope, batch_key=None,
                    status='not_measured' if not runs else
                        'no_critical_samples' if known and not coverage['sampled_steps'] else 'no_batch_calls',
                    probe_runs=len(runs), repeats=repeats,
                    sampled_steps=coverage['sampled_steps'] if known else None,
                    steps_with_batches=coverage['steps_with_batches'] if known else None,
                    total_batch_ns=sum(c['ns'] for c in totals.values()), tied_keys=winners)
                if winners:
                    key = winners[0]
                    c = totals[key]
                    same = sum(r['top_keys'] == [key] for r in repeats)
                    row.update(status='measured', batch_key=key, phase=mapping['batches'][key]['phase'],
                        batch=mapping['batches'][key]['batch'], **c,
                        share=c['ns'] / row['total_batch_ns'] if row['total_batch_ns'] else 0,
                        mean_call_ns=c['ns'] / c['calls'] if c['calls'] else None,
                        entry_zero_share=c['entry_zero_ns'] / c['ns'] if c['ns'] else 0,
                        waves=dict(wave_totals[key]), repeat_top_agreement=same,
                        repeated_top=len(runs) >= 2 and same == len(runs))
                    for repeat, (scores, _, _, _) in zip(repeats, runs):
                        repeat['winner_ns'] = scores[clock, scope].get(key, {}).get('ns', 0)
                rows.append(row)
    return dict(schema_version=1, metric='sum of sampled batch interval nanoseconds',
        granularity='batch', parts=parts, measured_parts=sorted(by_part), rows=rows,
        critical_labels='same last eval partition in independent discovery runs',
        scope_labels={'stable_last': '全局稳定拖尾采样', 'all_sampled': '分区全部采样'},
        note='排名使用实测累计时间；不按静态工作量排序，不分摊到 RTL 信号。')
