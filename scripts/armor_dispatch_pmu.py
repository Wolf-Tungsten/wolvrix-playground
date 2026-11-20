"""Per guest cycle PMU event counts of dispatch-diagnostic variants, side by side.

usage: armor_dispatch_pmu.py <variant> [<variant> ...]
The runs are on shared node029 cores, so only event counts are compared, not cycles or time.
"""
import json
import sys

from cv32e40p_compare import ROOT

OUT = ROOT / 'build/armor-dispatch-v1/pmu'
ROWS = [('instructions', 'instructions'), ('ex_ret_ops', 'operations'), ('ex_ret_brn', 'branches'),
        ('ex_ret_brn_tkn', 'taken branches'), ('ex_ret_brn_misp', 'mispredicted'),
        ('bp_de_redirect', 'decode redirects'),
        ('ic_tag_hit_miss.instruction_cache_miss', 'L1I misses'), ('ic_cache_fill_l2', 'L1I fills from L2'),
        ('ic_cache_fill_sys', 'L1I fills beyond L2'), ('bp_l1_tlb_miss_l2_tlb_miss.all', 'iTLB walks'),
        ('de_no_dispatch_per_slot.no_ops_from_frontend', 'slots without ops from front end'),
        ('L1-dcache-load-misses', 'L1D load misses'), ('cycles', 'cycles (not comparable)')]

variants = sys.argv[1:]
data = {v: json.loads((OUT / v / 'summary.json').read_text())['runs'] for v in variants}
for index, window in enumerate(('events-100k', 'events-10k')):
    print(f'== {window}')
    print(f"{'per guest cycle':34s}" + ''.join(f'{v:>14s}' for v in variants)
          + ''.join(f'{v + " vs " + variants[0]:>22s}' for v in variants[1:]))
    for event, title in ROWS:
        values = []
        for v in variants:
            run = data[v][index]
            c = run['counts'].get(event)
            values.append(c['count'] / (run['cycles'] + 1) if c else None)
        line = f'{title:34s}' + ''.join(f'{x:14.0f}' if x is not None else f"{'-':>14s}" for x in values)
        for x in values[1:]:
            line += f'{100 * (x / values[0] - 1):21.2f}%' if x is not None and values[0] else f"{'-':>22s}"
        print(line)
