#!/usr/bin/env python3
"""Verify identical cache behavior while accounting for grouped notifications."""
import argparse
import json
from pathlib import Path

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check
from cv32e40p_grouped_notify_compare import BASE_BACKEND, CANDIDATE, RETAINED, notify_groups
from cv32e40p_repair_analysis import analyze as repair_analysis, counter_rates


def compare_notifications(old, new):
    if old['cycles'] != new['cycles'] or old['trace']['sha256'] != new['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    counter_rates(old); counter_rates(new)
    a,b,n = old['counts'],new['counts'],old['cycles']
    invariant_keys = {key for key in a.keys() | b.keys()
                      if not key.startswith(('mux_invalidate_visits:', 'mux_invalidations:', 'mux_notify_accumulate'))}
    for key in invariant_keys:
        if a.get(key) != b.get(key): raise ValueError('consumer or scheduling work changed: ' + key)
    aggregate = lambda counts,prefix:sum(sum(values) for key,values in counts.items() if key.startswith(prefix))/n
    return dict(invariants=len(invariant_keys),
        persistent_dirty_updates_per_cycle={name:aggregate(c,'mux_invalidate_visits:') for name,c in (('before',a),('after',b))},
        changed_dirty_updates_per_cycle={name:aggregate(c,'mux_invalidations:') for name,c in (('before',a),('after',b))},
        local_accumulations_per_cycle=aggregate(b,'mux_notify_accumulate_visits:'),
        local_changed_sources_per_cycle=aggregate(b,'mux_notify_accumulate_changes:'),
        cache_executions_per_cycle={key:sum(values)/n for key,values in b.items() if key.startswith(('mux_cache_visits:','mux_cache_misses:'))})


def analyze(out, counts):
    check(out)
    directories={RETAINED:ROOT/'build/cv32e40p/mux-input-cache-counts-v1',
                 BASE_BACKEND:ROOT/'build/cv32e40p/change-trigger-cache-counts-v1',CANDIDATE:counts}
    read=lambda directory:json.loads((directory/'counts.json').read_text())['coremark']
    result=compare_notifications(read(directories[BASE_BACKEND]),read(counts))
    result['groups']=notify_groups(out/CANDIDATE)
    result['limits']='Persistent dirty update counts exclude local accumulation; both are reported. IR counts are not retired instructions. Existing consumer executions, misses, source changes and scheduler counts must remain identical.'
    result['inputs']=[identity(path) for path in (out/'build.json',out/'structure.json',
        *(directory/'counts.json' for directory in directories.values()),Path(__file__).resolve())]
    repair_analysis(out,directories,retained_backend=RETAINED)
    save(out/'notify-attribution.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--counts',type=Path,required=True)
    args=parser.parse_args();analyze(args.source.resolve(),args.counts.resolve())
