#!/usr/bin/env python3
"""Choose a memory separator from measured structural cones, without name rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def choose(audit: dict, metrics: list[dict], max_copy_growth: float) -> dict:
    if not 0 <= max_copy_growth <= 1:
        raise ValueError('copy growth must be a fraction in [0, 1]')
    proposals = {item['candidate_id']: item for item in audit['refinement_candidates']}
    if len(proposals) != len(audit['refinement_candidates']):
        raise ValueError('duplicate candidate ids')
    considered = []
    seen = set()
    for row in metrics:
        name = row['name']
        if name not in proposals or name in seen:
            raise ValueError('unexpected or duplicate metric record')
        seen.add(name)
        before, largest, total = (row[k] for k in ('baseline_work', 'max_work', 'total_work'))
        if before <= 0 or largest <= 0 or total < before or largest > total:
            raise ValueError('invalid structural work ledger')
        eligible = largest < before and total <= before * (1 + max_copy_growth)
        considered.append(dict(row, eligible=eligible,
                               cut_memories=proposals[name]['cut_memories']))
    if seen != set(proposals):
        raise ValueError('incomplete candidate metrics')
    ranked = sorted((row for row in considered if row['eligible']),
                    key=lambda row: (row['max_work'], row['total_work'],
                                     len(row['cut_memories']), row['name']))
    winner = ranked[0] if ranked else None
    return dict(status='pass', method='minimum largest exact cone within replication budget',
                max_copy_growth=max_copy_growth, selected=winner,
                selected_memories=winner['cut_memories'] if winner else [],
                considered=considered, input_names_used_as_selection_rules=False,
                runtime_prediction=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--metrics', type=Path, required=True)
    parser.add_argument('--max-copy-growth', type=float, default=0.05)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = choose(json.loads(args.audit.read_text()), json.loads(args.metrics.read_text()),
                    args.max_copy_growth)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'selection.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.output / 'selected.txt').write_text(''.join(name + '\n' for name in result['selected_memories']))
    print(json.dumps({k: result[k] for k in ('status', 'selected', 'selected_memories')}))


if __name__ == '__main__':
    main()
