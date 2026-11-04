#!/usr/bin/env python3
"""Add exact counters to frozen native C++ in an isolated research package."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil

from grhsim_single_baseline import ROOT, identity, save


def instrument(source):
    counts=Counter();out=[];pending=None
    for line in source.splitlines(keepends=True):
        m=re.match(r'void GrhSIM_\w+::eval_(compute|commit)_batch_(\d+)\(\)',line)
        if m:
            pending=('batch',int(m[2]));counts['batch_functions']+=1
        m=re.search(r'// Supernode (\d+): run when its activity flag is set\.',line)
        if m:pending=('group',int(m[1]));counts['supernode_guards']+=1
        m=re.search(r'// Strict cohort follower payload for supernode (\d+);',line)
        if m:raise ValueError('cohort followers need explicit instrumentation support')
        # The comparison is evaluated once; instrumentation returns its exact result.
        m=re.match(r'(\s*const bool grhsim_changed_\d+ = )(.*);\s*$',line)
        if m:
            line=m[1]+'decode_counts::change('+m[2]+');\n';counts['scalar_changes']+=1
        elif re.match(r'\s*if \(',line) and line.rstrip().endswith(') {'):
            condition=line[line.index('if (')+4:line.rindex(') {')]
            if ('grhsim_assign_words' in condition or
                ('!=' in condition and ('next_value' in condition or 'dpi_out_' in condition))):
                line=line[:line.index('if (')]+'if (decode_counts::change('+condition+')) {\n'
                counts['conditional_changes']+=1
        m=re.match(r'(\s*)(supernode_active_curr_\[[^\]]+\]) \|= (.*);\s*$',line)
        if m:
            line=f'{m[1]}decode_counts::activate({m[2]}, {m[3]});\n';counts['byte_activation']+=1
        elif re.match(r'\s*grhsim_or_active_u(?:16|32|64)\(supernode_active_curr_\.data\(\),',line):
            line=re.sub(r'grhsim_or_active_u(16|32|64)', lambda m: 'decode_counts::activate_words<std::uint'+m[1]+'_t>',line)
            counts['word_activation']+=1
        out.append(line)
        if pending and '{' in line and not line.lstrip().startswith('//'):
            kind,index=pending;pending=None
            if kind=='batch':out.append(f'    decode_counts::Batch counted_batch({index});\n')
            else:out.append(f'        decode_counts::fire({index});\n')
        if re.match(r'\s*producer_dirty_words_\[.*\] \|=',line):
            if not line.rstrip().endswith(';'):raise ValueError('multiline dirty update')
            out.append('        decode_counts::dirty();\n');counts['dirty_updates']+=1
    if pending:raise ValueError('missing body for instrumentation')
    return '#include "decode_constant_counts.hpp"\n'+''.join(out),counts


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    # Keep original .o/PCH for untouched state initialization, but copy all files:
    # no writable hard links to the frozen package.
    shutil.copytree(a.source/'model',a.output/'model')
    for path in (a.output/'model').glob('*.pch'):path.unlink()
    shutil.copy2(ROOT/'scripts/decode_constant_counts.hpp',a.output/'model/decode_constant_counts.hpp')
    manifest=[]
    for path in sorted((a.output/'model').glob('*_sched_*.cpp')):
        before=identity(a.source/'model'/path.name);source=path.read_text();edited,counts=instrument(source)
        path.write_text(edited);path.with_suffix('.o').unlink(missing_ok=True)
        manifest.append(dict(file=path.name,original=before,instrumented=identity(path),sites=counts))
    path=a.output/'model/grhsim_SimTop_eval.cpp';source=path.read_text()
    old='void GrhSIM_SimTop::eval()\n{';new=old+'\n    decode_counts::eval(clock);'
    if source.count(old)!=1 or source.count('++fixed_point_round_count;')!=1:raise ValueError('unexpected eval structure')
    source=source.replace(old,new).replace('++fixed_point_round_count;','++fixed_point_round_count;\n        decode_counts::round();')
    source,eval_sites=instrument(source)
    source=source.replace("decode_counts::activate(", "decode_counts::counts.current=131071; decode_counts::activate(")
    path.write_text(source);path.with_suffix('.o').unlink(missing_ok=True)
    (a.output/'chisel-home').mkdir();(a.output/'chisel-home/build').symlink_to((a.source/'chisel-home/build').resolve(),target_is_directory=True)
    save(a.output/'instrumentation.json',dict(source=str(a.source.resolve()),sites=manifest,eval_sites=eval_sites,driver=identity(__file__),
        scope='Full process including reset; no timing conclusions. Changed-result counters cover generated scalar comparisons and wide assignment conditions. Activation counts record byte/word OR sites and newly set bits; dirty counts count OR statements.'))


if __name__=='__main__':main()
