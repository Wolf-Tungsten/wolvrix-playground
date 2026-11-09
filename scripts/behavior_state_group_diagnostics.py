#!/usr/bin/env python3
"""Build separate instrumented local fixtures; never use them for timings."""
import argparse,json
from pathlib import Path
from behavior_state_group_validate import pipeline,build_check
from behavior_state_group_check import harness

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--rat',action='store_true');a=p.parse_args();r=a.fixture.resolve();records={}
 for v in 'HOG':
  source=r/('hardware' if v=='H' else 'model');out=r/(v+'-diagnostic')
  if not (out/'model/grhsim_BehaviorGroupFixture.hpp').exists():
   pipeline([source/'BehaviorGroupFixture.sv'],'BehaviorGroupFixture',out,source/'simulation_models.json',grouped=v=='G',perf=True)
  build_check(out,harness(a.rat));records[v]=(out/'check.log').read_text()
 (r/'diagnostic-summary.json').write_text(json.dumps(records,indent=2))
 print(json.dumps(records,indent=2))
if __name__=='__main__':main()
