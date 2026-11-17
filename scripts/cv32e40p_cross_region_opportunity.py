#!/usr/bin/env python3
"""Static explanation of lost view proofs; no simulator or timing input."""
from functools import cache
from collections import defaultdict,Counter
from pathlib import Path
import csv,json,sys
from cv32e40p_compare import ROOT,identity,save
from cv32e40p_covered_state_views_compare import sites
from cv32e40p_post_view_structure import ALLOWED
out=ROOT/'build/cv32e40p/cross-region-views-v1'
model=out/'grhsim_unshared'
graph=json.loads((model/'normalized.json').read_text())['graphs'][0]
vals={v['sym']:v for v in graph['vals']};ops={o['sym']:o for o in graph['ops']}
rows=list(csv.DictReader((out/'unshared-sources.csv').open()));mapping={r['op_symbol']:r for r in rows}
byid={int(i):v for r in rows for i,v in zip(r['value_ids'].split(';'),r['value_symbols'].split(';')) if i}
readers=defaultdict(set)
for r in rows:
 o=ops[r['op_symbol']]
 if o['kind']=='kRegisterReadPort':readers[o['attrs']['regSymbol']['v']].add(int(r['group']))
@cache
def closure(symbol,depth=0):
 if depth>32:return None
 v=vals[symbol];d=v.get('def')
 if not d or v['w']>64:return None
 o=ops[d];k=o['kind'];row=mapping.get(d)
 if k=='kConstant':return frozenset(),frozenset(),frozenset()
 if row is None or row['phase']!='compute':return None
 if k=='kRegisterReadPort' and not o['in']:
  return frozenset([o['attrs']['regSymbol']['v']]),frozenset(),frozenset([int(row['group'])])
 if k not in ALLOWED:return None
 children=[closure(i,depth+1) for i in o['in']]
 if any(c is None for c in children):return None
 return (frozenset().union(*(c[0] for c in children)),frozenset([d]).union(*(c[1] for c in children)),frozenset([int(row['group'])]).union(*(c[2] for c in children)))
old=sites(ROOT/'build/cv32e40p/state-expressions-v1/grhsim_state_expression_inline')
current={s['value'] for s in sites(model)};results=[]
for site in old:
 i=site['value']
 if i in current:continue
 sym=byid[i];v=vals[sym];c=closure(sym)
 record=dict(value=i,symbol=sym,closure=bool(c))
 if c and len(c[0])==1:
  state=next(iter(c[0]));producer=int(mapping[v['def']]['group']);users={int(mapping[u['op']]['group']) for u in v['users'] if u['op'] in mapping}
  record.update(state=state,ops=len(c[1]),groups=sorted(c[2]),cross_region=len(c[2])>1,producer=producer,consumers=sorted(users-{producer}),
    producer_reads_state=producer in readers[state],missing_consumers=sorted((users-{producer})-readers[state]),direct_read_groups=sorted(readers[state]))
 results.append(record)
save(out/'cross-region-opportunity.json',dict(lost=len(results),rows=results,summary=dict(
 single_state=sum('state' in r for r in results),cross_region=sum(r.get('cross_region',False) for r in results),
 missing_producer=sum(not r.get('producer_reads_state',True) for r in results),missing_consumers=sum(bool(r.get('missing_consumers')) for r in results)),
 inputs=[identity(p) for p in (model/'normalized.json',out/'unshared-sources.csv',Path(__file__).resolve())],
 limits='IR direct-reader sets are a structural screen, not the emitter final activation frontier or full legality proof. Missing readers explain rejection without guessing runtime coactivity.'))
print(json.dumps(json.loads((out/'cross-region-opportunity.json').read_text())['summary'],indent=2))
