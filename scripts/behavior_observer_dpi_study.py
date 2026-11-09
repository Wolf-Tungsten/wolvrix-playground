#!/usr/bin/env python3
"""Verify a grouped array -> debug delay -> void DPI observation path."""
import argparse
import json
import sys
from pathlib import Path
from behavior_state_group_validate import ROOT, pipeline, build_check

sys.path.insert(0, str(ROOT/'build/grhsim32-tools/python'))
from wolvrix.behavior_state import carrier_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nested',action='store_true')
    args=parser.parse_args()
    name='observer-dpi-nested' if args.nested else 'observer-dpi'
    out = ROOT/'wolvrix/build/artifacts/behavior-state-group-s3'/name
    out.mkdir(parents=True, exist_ok=False)
    original = json.loads((ROOT/'wolvrix/build/artifacts/behavior-state-group/simple-final/model/simulation_models.json').read_text())
    binding = original['models'][0]['binding']
    source = carrier_source(binding)
    source += '''module ObserverSink(input clock, input reset, input [63:0] data);
reg [63:0] delayed;
always @(posedge clock) if (reset) delayed <= 0; else delayed <= data;
import "DPI-C" function void behavior_observe(input longint unsigned value);
always @(posedge clock) behavior_observe(delayed);
endmodule
module BehaviorObserverDpi(input clock, input reset, input [63:0] data, output [63:0] observed);
'''
    wires = []
    connections = []
    for port in binding['ports']:
        name, width = port['name'], port['width']
        if port['direction'] == 'output':
            wires.append(f'wire [{width-1}:0] {name};')
            value = name
        else:
            value = {'clock': 'clock', 'reset': 'reset', 'u0_valid': "1'b1", 'u0_data': 'data'}.get(name, f"{width}'d0")
        connections.append(f'.{name}({value})')
    source += '\n'.join(wires)+'\n'+binding['module']+' arrays('+','.join(connections)+');\n'
    owner='ObserverDomainRoot' if args.nested else 'ObserverSink'
    source += f'assign observed = r0_data;\n{owner} sink(clock, reset, r0_data);\nendmodule\n'
    if args.nested:
        source += 'module ObserverDomainRoot(input clock,input reset,input [63:0] data);\nObserverSink child(clock,reset,data);\nendmodule\n'
    (out/'fixture.sv').write_text(source)
    original['observer_domains'] = [dict(version=1, id='test.dpi-observer', module=owner, include_children=True,
        ports=[dict(name=n, width=w, direction='input') for n,w in [('clock',1),('reset',1),('data',64)]])]
    (out/'manifest.json').write_text(json.dumps(original))
    pipeline([out/'fixture.sv'], 'BehaviorObserverDpi', out, out/'manifest.json', grouped=True)
    code = '''#include "grhsim_BehaviorObserverDpi.hpp"
#include <cstdint>
#include <cstdio>
static uint64_t last=0, calls=0;
extern "C" void behavior_observe(uint64_t value){last=value;++calls;}
int main(){GrhSIM_BehaviorObserverDpi m;m.init();uint64_t state=0,delayed=0;
for(unsigned c=0;c<100;++c){m.clock=false;m.reset=c<3;m.data=c*7;m.eval();
m.clock=true;m.eval();
if(last!=delayed || calls!=c+1){fprintf(stderr,"cycle=%u last=%lu delayed=%lu calls=%lu\\n",c,last,delayed,calls);return 1;}
delayed=m.reset?0:state;state=m.reset?0:m.data;
if(m.observed!=state)return 2;
m.eval();if(calls!=c+1)return 3;
}puts("PASS grouped old state -> observer delay -> void DPI; 100 edges, repeated eval does not call twice");}
'''
    build_check(out, code, 'BehaviorObserverDpi')
    print((out/'check.log').read_text())


if __name__ == '__main__':
    main()
