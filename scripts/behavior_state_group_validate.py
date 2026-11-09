#!/usr/bin/env python3
"""Binding failures, native contract rejection, SV fallback and instance isolation."""
import argparse,copy,json,os,sys
from pathlib import Path
from behavior_state_group_study import ROOT,CXX,command
from behavior_state_group_check import harness
sys.path.insert(0,str(ROOT/'build/grhsim32-tools/python'))

def pipeline(files,top,dest,manifest=None,grouped=False,perf=False):
 dest.mkdir(parents=True,exist_ok=True)
 (dest/'input.f').write_text('\n'.join(str(x) for x in files)+'\n');(dest/'read_args.txt').write_text('')
 env=dict(os.environ,PYTHONPATH=str(ROOT/'build/grhsim32-tools/python'),LD_LIBRARY_PATH=str(ROOT/'build/grhsim32-tools'),
   WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(dest/'pre.json'),WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON='0',WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='0')
 if manifest:env['WOLVRIX_SIMULATION_MODELS_MANIFEST']=str(manifest)
 else:env.pop('WOLVRIX_SIMULATION_MODELS_MANIFEST',None)
 command([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',dest/'input.f',top,dest/'model',dest/'graph.json',dest/'read_args.txt','info',
    '--waveform','off','--perf','eval' if perf else 'off','--behavior-state-lowering','grouped' if grouped else 'ordinary'],dest/'emit.log',env)
 command(['make','-C',dest/'model','-j8','CXX='+str(CXX),'CXXFLAGS=-std=c++20 -O3 -march=native'],dest/'compile.log')

def build_check(dest,code,top='BehaviorGroupFixture'):
 model=dest/'model';(model/'check.cpp').write_text(code)
 command([CXX,'-std=c++20','-O3','-march=native','-I'+str(model),model/'check.cpp',model/f'libgrhsim_{top}.a','-o',model/'check'],dest/'check-compile.log')
 command([model/'check'],dest/'check.log')

def main():
 import wolvrix
 from wolvrix.behavior_state import lower_behavior_state,validate_observer_state_feedback
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 fixture=a.fixture.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);records=[]
 raw=json.loads((fixture/'G/model/behavior_before.json').read_text());manifest=json.loads((fixture/'model/simulation_models.json').read_text())
 for label in ('version','missing-binding','port-width','update-order','initializer','source-hash','observer'):
  m=copy.deepcopy(manifest);b=m['models'][0]['binding']
  if label=='version':m['version']=99
  elif label=='missing-binding':m['models'][0]['binding']=None
  elif label=='port-width':b['ports'][2]['width']+=1
  elif label=='update-order':b['updates'][0]=1
  elif label=='initializer':b['arrays'][0]['initial'][0]='7'
  elif label=='source-hash':b['sv_sha256']='0'*64
  else:m['models'][0]['observer_only']=False
  try:lower_behavior_state(raw,m,fixture/'model')
  except (ValueError,KeyError) as e:records.append(dict(test=label,pass_=True,error=str(e)))
  else:raise AssertionError('negative binding accepted: '+label)
 good=json.loads((fixture/'G/pre_reg_to_mem.json').read_text())
 def attr(v):return dict(t='int' if isinstance(v,int) else 'string',v=v)
 for label in ('native-version','native-width','native-feedback','native-alias-writer'):
  design=copy.deepcopy(good);g=design['graphs'][0];group=next(o for o in g['ops'] if o['kind']=='kBehaviorStateGroup')
  if label=='native-version':group['attrs']['behavior.version']['v']=99
  elif label=='native-width':
   val=next(v for v in g['vals'] if v['sym']==group['in'][4]);val['w']+=1
  elif label=='native-alias-writer':
   g['ops'].append(dict(sym='illegal_owner',kind='kMemoryFillPort',**{'in':[group['in'][0],group['in'][4],group['in'][-1]],'out':[]},
    attrs=dict(memSymbol=group['attrs']['memSymbol'],eventEdge=dict(t='string[]',vs=['posedge']))))
  else:
   read=next(o for o in g['ops'] if o['kind']=='kMemoryReadPort');data=read['out'][0];width=next(v['w'] for v in g['vals'] if v['sym']==data)
   g['vals'].append(dict(sym='feedback_mask',w=width,sgn=False,type='logic',**{'in':False,'out':False,'inout':False}))
   g['ops'] += [dict(sym='feedback_reg',kind='kRegister',**{'in':[],'out':[]},attrs=dict(width=attr(width),isSigned=dict(t='bool',v=False))),
    dict(sym='feedback_constant',kind='kConstant',**{'in':[],'out':['feedback_mask']},attrs=dict(constValue=attr(f"{width}'d{(1<<width)-1}"))),
    dict(sym='feedback_write',kind='kRegisterWritePort',**{'in':[group['in'][0],data,'feedback_mask',group['in'][-1]],'out':[]},attrs=dict(regSymbol=attr('feedback_reg'),eventEdge=dict(t='string[]',vs=['posedge'])))]
   try:validate_observer_state_feedback(design)
   except ValueError:pass
   else:raise AssertionError('observer ownership check accepted ordinary feedback')
  with wolvrix.Session() as s:
   s.load_json_text(json.dumps(design));s.diagnostics_raise_min_level='none';s.diagnostics_print_min_level='none'
   diagnostics=s.emit_sv(design='design.main',output=str(out/(label+'.sv')),top=['BehaviorGroupFixture'])
   if s.history()[-1]['success']:raise AssertionError('native emitter accepted '+label)
   expected={'native-version':'invalid behavior group contract/version',
    'native-width':'behavior update port width mismatch',
    'native-feedback':'observer group feeds unowned state/effect',
    'native-alias-writer':'behavior backing store has an ordinary writer'}[label]
   if not any(expected in d.get('message','') for d in diagnostics):
    raise AssertionError(f'{label}: rejected for the wrong reason: {diagnostics}')
   records.append(dict(test=label,pass_=True,diagnostics=diagnostics))
 # Re-emit grouped GRH as ordinary SV and verify its runtime state trajectory.
 roundtrip=out/'roundtrip';roundtrip.mkdir(exist_ok=True)
 with wolvrix.Session() as s:
  s.load_json_text(json.dumps(good));s.emit_sv(design='design.main',output=str(roundtrip/'fallback.sv'),top=['BehaviorGroupFixture'])
 pipeline([roundtrip/'fallback.sv'],'BehaviorGroupFixture',roundtrip)
 build_check(roundtrip,harness(False));records.append(dict(test='SV-roundtrip',pass_=True,cycles=10000))
 # Two instances of the exact same RTL module/carrier, not merely two C++ objects.
 graph=next(g for g in raw['graphs'] if g['symbol']=='BehaviorGroupFixture');vals={v['sym']:v for v in graph['vals']}
 top='BehaviorGroupTwin';twin=out/'twins';twin.mkdir(exist_ok=True)
 ports=['input wire cross_enable'];instances=[]
 for side in ('left','right'):
  connections=[]
  for direction,key in [('input','in'),('output','out')]:
   for port in graph['ports'][key]:
    name=port['name'];width=vals[port['val']]['w'];ports.append(f'{direction} wire [{width-1}:0] {side}_{name}')
    other='right' if side=='left' else 'left'
    bound={'io_valid_1':'cross_enable','io_kind_1':"4'd1",'io_index_1':"6'd0",
     'io_data_1':other+'_io_snapshot_0_0'}.get(name,side+'_'+name)
    connections.append(f'.{name}({bound})')
  instances.append('BehaviorGroupFixture '+side+'('+','.join(connections)+');')
 (twin/'twin.sv').write_text('module '+top+'('+',\n'.join(ports)+');\n'+'\n'.join(instances)+'\nendmodule\n')
 pipeline([fixture/'model/BehaviorGroupFixture.sv',twin/'twin.sv'],top,twin,fixture/'model/simulation_models.json',grouped=True)
 code=f'#include "grhsim_{top}.hpp"\n#include <array>\n#include <cstdio>\nint main(){{GrhSIM_{top} m;m.init();std::array<unsigned long long,32> left{{}},right{{}};\nfor(unsigned c=0;c<1000;++c){{\n'
 for side in ('left','right'):
  code+=f'm.{side}_clock=false;m.{side}_reset=c<3;m.{side}_io_readIndex=0;m.{side}_io_valid_0=true;m.{side}_io_kind_0=1;m.{side}_io_index_0=c%32;m.{side}_io_data_0=c+{1 if side=="left" else 10000};\n'
 code+='m.eval();m.left_clock=true;m.eval();left[c%32]=c+1;if(c<3)left.fill(0);\n'
 for row in range(32):code+=f'if(m.left_io_snapshot_0_{row}!=left[{row}] || m.right_io_snapshot_0_{row}!=right[{row}])return 1;\n'
 code+='m.right_clock=true;m.eval();right[c%32]=c+10000;if(c<3)right.fill(0);\n'
 for row in range(32):code+=f'if(m.left_io_snapshot_0_{row}!=left[{row}] || m.right_io_snapshot_0_{row}!=right[{row}])return 2;\n'
 code+='}\nm.cross_enable=true;m.left_io_valid_0=false;m.right_io_valid_0=false;\n'
 code+='for(unsigned c=0;c<100;++c){m.left_clock=false;m.right_clock=false;m.eval();m.left_clock=true;m.right_clock=true;m.eval();std::swap(left[0],right[0]);\n'
 for row in range(32):code+=f'if(m.left_io_snapshot_0_{row}!=left[{row}] || m.right_io_snapshot_0_{row}!=right[{row}])return 3;\n'
 code+='}puts("PASS: two independent instances, 1000 staggered edges and 100 same-edge cross-group swaps");}\n'
 build_check(twin,code,top);records.append(dict(test='same-module-two-instances',pass_=True,cycles=1100,cross_group_old_state=True))
 (out/'summary.json').write_text(json.dumps(records,indent=2));print('PASS bindings, native contract, SV fallback and two-instance isolation')
if __name__=='__main__':main()
