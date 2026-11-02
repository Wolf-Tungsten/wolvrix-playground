"""Validate diagnostic timelines and attribute batch costs without inventing line timings."""
from __future__ import annotations
from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import struct
from grhsim_source_map import batch_key, save
from grhsim_dynamic_top import rank_dynamic_batches

HEADER = struct.Struct('<8s8IQ')
RECORD = struct.Struct('<4Q8I')
PHASES = ('input', 'eval', 'update')


def trace_records(path):
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as raw:
        if len(raw) < HEADER.size:
            raise ValueError('truncated trace header')
        magic, version, size, parts, warmup, cycles, stride, selected, reserved, count = HEADER.unpack_from(raw)
        if (magic,version,size,reserved) != (b'GRHCP001',1,RECORD.size,0) or not parts or not cycles:
            raise ValueError('unsupported trace version/shape')
        if len(raw) != HEADER.size + count * size:
            raise ValueError('truncated or extended trace records')
        yield dict(parts=parts,warmup=warmup,cycles=cycles,stride=stride,selected_part=selected,records=count)
        for offset in range(HEADER.size,len(raw),size):
            row = RECORD.unpack_from(raw,offset)
            step,start,end,thread,part,batch,round_,word,mask,kind,clock,after = row
            if end < start or not thread or not step or clock > 1 or kind > 7 or part > parts or after > 1:
                raise ValueError('invalid trace event')
            if (kind >= 5) != (part == parts):
                raise ValueError('global event/partition mismatch')
            yield row


def summarize_timeline(path):
    records = trace_records(path)
    header = next(records)
    groups = {}
    lane_next = {}
    seen = set()
    batch_count = 0
    for step,start,end,thread,part,batch,round_,word,mask,kind,clock,after in records:
        if kind in (3,4):
            batch_count += 1
            continue
        phase = kind-5 if kind>=5 else kind
        key = step, phase
        group = groups.setdefault(key, dict(step=step,phase=PHASES[phase],clock=clock,
            lanes=0,first=-1,second=-1,winner=None,body_max=0,body_winner=None,total_body=0,min_start=None))
        if group['clock'] != clock or (step,kind,part) in seen:
            raise ValueError('duplicate event or inconsistent clock')
        seen.add((step,kind,part))
        if kind>=5:
            group['global_start'], group['global_end'] = start,end
            continue
        previous = lane_next.get((part,phase))
        if previous is not None and step != previous+1:
            raise ValueError('missing lane step')
        lane_next[part,phase] = step
        group['lanes'] += 1
        group['min_start'] = start if group['min_start'] is None else min(group['min_start'],start)
        duration = end-start
        group['total_body'] += duration
        if group['body_winner'] is None or duration > group['body_max'] or (duration==group['body_max'] and part < group['body_winner']):
            group['body_max'],group['body_winner'] = duration,part
        if end > group['first'] or (end==group['first'] and (group['winner'] is None or part < group['winner'])):
            group['second'],group['first'] = group['first'],end
            group['winner'],group['winner_start'],group['winner_thread'] = part,start,thread
        elif end > group['second']:
            group['second'] = end
    if len(groups) != header['cycles']*2*3:
        raise ValueError('incomplete sampling window')
    result = []
    stats = defaultdict(Counter)
    steps = sorted({step for step,phase in groups})
    if any(b!=a+1 for a,b in zip(steps,steps[1:])):
        raise ValueError('missing global steps')
    if any(groups[(a,0)]['clock']==groups[(b,0)]['clock'] for a,b in zip(steps,steps[1:])):
        raise ValueError('non-alternating clock in XiangShan window')
    for key,group in sorted(groups.items()):
        if group['lanes'] != header['parts'] or 'global_end' not in group or group['second'] < 0:
            raise ValueError('missing phase/lane samples')
        if group['first'] > group['global_end'] or group['min_start'] < group['global_start']:
            raise ValueError('lane event outside global phase')
        row = dict(step=group['step'],clock=group['clock'],phase=group['phase'],
            last_part=group['winner'],last_thread=group['winner_thread'],
            last_start_ns=group['winner_start'],last_end_ns=group['first'],
            exclusive_tail_ns=group['first']-group['second'],
            longest_body_part=group['body_winner'],longest_body_ns=group['body_max'],
            global_ns=group['global_end']-group['global_start'],
            host_completion_ns=group['global_end']-group['first'])
        result.append(row)
        totals = stats[group['phase'],group['clock'],group['winner']]
        totals['last_count'] += 1
        totals['exclusive_tail_ns'] += row['exclusive_tail_ns']
        totals['global_ns_on_last_steps'] += row['global_ns']
        totals['last_not_longest_count'] += group['winner'] != group['body_winner']
    ranking=[dict(phase=phase,clock=clock,part=part,**values) for (phase,clock,part),values in stats.items()]
    ranking.sort(key=lambda r:(-r['exclusive_tail_ns'],r['part']))
    return dict(header=header,steps=result,parts=ranking,batch_events=batch_count)


def reference_labels(reports):
    if len(reports)<2:
        raise ValueError('at least two discovery runs are required')
    first = {(r['step'],r['phase']):r for r in reports[0]['steps']}
    votes = {key:[value['last_part']] for key,value in first.items()}
    for report in reports[1:]:
        current={(r['step'],r['phase']):r for r in report['steps']}
        if first.keys()!=current.keys() or any(first[k]['clock']!=current[k]['clock'] for k in first):
            raise ValueError('discovery runs have different step/clock windows')
        for key in first:
            votes[key].append(current[key]['last_part'])
    return {key:values[0] if len(set(values))==1 else None for key,values in votes.items()}


def summarize_batches(path, mapping, labels):
    records = trace_records(path)
    header=next(records)
    selected=header['selected_part']
    if selected>=header['parts'] or not header['stride']:
        raise ValueError('batch trace has no selected lane or sample stride')
    samples=defaultdict(list)
    evals={}
    clock_by_step={}
    for record in records:
        step,start,end,thread,part,batch,round_,word,mask,kind,clock,after=record
        if step in clock_by_step and clock_by_step[step]!=clock:
            raise ValueError('inconsistent clock in batch trace')
        clock_by_step[step]=clock
        if part!=selected:
            if kind in (3,4): raise ValueError('batch events from an unselected partition')
            continue
        if kind==1:
            if step in evals: raise ValueError('duplicate eval in batch trace')
            evals[step]=(start,end)
        if kind not in (3,4): continue
        if not round_:
            raise ValueError('batch missing fixed-point round')
        phase='compute' if kind==3 else 'commit'
        key=batch_key(part,phase,batch)
        if key not in mapping['batches']:
            raise ValueError(f'unmapped dynamic batch {key}')
        if kind==3 and mask & ~255:
            raise ValueError('invalid entry activity mask')
        samples[step].append((key,record))
    if len(evals)!=header['cycles']*2:
        raise ValueError('incomplete batch-probe eval window')
    first_step=min(evals)
    if sorted(evals)!=list(range(first_step,first_step+header['cycles']*2)):
        raise ValueError('missing batch-probe step')
    expected={s for s in evals if ((s-first_step)//2)%header['stride']==0}
    if any((s,'eval') not in labels for s in evals):
        raise ValueError('batch probe and discovery have different step windows')
    coverage=defaultdict(Counter)
    for step in expected:
        scope='stable_last' if labels[(step,'eval')]==selected else 'other'
        coverage[clock_by_step[step],scope]['sampled_steps']+=1
        coverage[clock_by_step[step],scope]['steps_with_batches']+=bool(samples.get(step))
    counts=defaultdict(Counter)
    intervals=[]
    for step,entries in sorted(samples.items()):
        if step not in expected:
            raise ValueError('unexpected sampled step')
        previous=-1
        round_seen=0
        start_eval,end_eval=evals[step]
        for key,record in entries:
            _,start,end,thread,part,batch,round_,word,mask,kind,clock,after=record
            if start<start_eval or end>end_eval or start<previous or round_<round_seen:
                raise ValueError('overlapping/unordered batch intervals')
            previous,round_seen=end,round_
            scope='stable_last' if labels.get((step,'eval'))==part else 'other'
            counter=counts[key,clock,scope,'first' if round_==1 else 'after_commit' if after else 'later']
            counter['calls']+=1;counter['ns']+=end-start
            counter['max_call_ns']=max(counter['max_call_ns'],end-start)
            counter['entry_nonzero_calls']+= kind==3 and mask!=0
            counter['entry_zero_ns']+= (end-start) if kind==3 and mask==0 else 0
            intervals.append(dict(step=step,clock=clock,part=part,thread=thread,batch_key=key,
                                  round=round_,start_ns=start,end_ns=end,entry_word=word,entry_mask=mask,
                                  entry_mask_kind='not_applicable' if kind==4 else 'or_of_words' if word==0xffffffff else 'word',
                                  after_commit=bool(after),scope=scope))
    # A sampled eval can have no fixed-point work. Distinguish that from loss
    # through the complete eval records and the trace's exact record count.
    return dict(header=header,sampled_steps=len(expected),steps_with_batches=len(samples),
        sample_coverage=[dict(clock=clock,scope=scope,**c) for (clock,scope),c in sorted(coverage.items())],
        batches=[dict(batch_key=key,clock=clock,scope=scope,wave=wave,**c)
                 for (key,clock,scope,wave),c in sorted(counts.items())],intervals=intervals)


def assemble_report(mapping, discoveries, probes):
    labels=reference_labels(discoveries)
    reference=discoveries[0]['header']
    for probe in probes:
        if any(probe['header'][field]!=reference[field] for field in ('parts','warmup','cycles')):
            raise ValueError('batch probe/discovery configuration mismatch')
    ranking=defaultdict(Counter)
    for report in discoveries:
        for row in report['parts']:
            ranking[row['phase'],row['clock'],row['part']].update({k:v for k,v in row.items() if k not in ('phase','clock','part')})
    parts=[dict(phase=phase,clock=clock,part=part,**c) for (phase,clock,part),c in ranking.items()]
    parts.sort(key=lambda r:-r['exclusive_tail_ns'])
    costs=defaultdict(Counter)
    phase_costs=defaultdict(Counter)
    for probe in probes:
        for row in probe['batches']:
            phase_costs[row['batch_key'],row['clock'],row['scope'],row['wave']].update({k:v for k,v in row.items() if k in ('calls','ns','entry_nonzero_calls','entry_zero_ns')})
            if row['scope']=='stable_last':
                costs[row['batch_key']].update({k:v for k,v in row.items() if k in ('ns','calls','entry_zero_ns')})
    static_keys={node['batch'] for path in mapping['static_paths'] if path['rank']==1
                 for node in path['nodes'] if node.get('batch')}
    dynamic_keys=set(costs)
    rows=[]
    for key,batch in mapping['batches'].items():
        static=key in static_keys; dynamic=key in dynamic_keys
        unknown=batch['unmapped_operations']==batch['operations']
        label='unmapped' if unknown else 'static-and-dynamic' if static and dynamic else 'dynamic-only' if dynamic else 'static-only' if static else 'other'
        rows.append(dict(batch_key=key,**batch,classification=label,measured=key in costs,
                         critical_sample_ns=costs[key]['ns'],critical_sample_calls=costs[key]['calls'],
                         critical_entry_zero_ns=costs[key]['entry_zero_ns']))
    rows.sort(key=lambda r:(-r['critical_sample_ns'],-r['structural_work'],r['batch_key']))
    sources=defaultdict(set)
    for row in rows:
        if row['critical_sample_ns']:
            for sid in row['source_spans']: sources[sid].add(row['batch_key'])
    source_rows=[dict(**mapping['spans'][sid],associated_batches=sorted(keys),
                     associated_batch_ns=sum(costs[key]['ns'] for key in keys)) for sid,keys in sources.items()]
    source_rows.sort(key=lambda r:(-r['associated_batch_ns'],r['file'],r['line']))
    return dict(schema_version=1,status='pass',diagnostic_only=True,mapping=mapping['summary'],
        part_ranking=parts,batch_ranking=rows,source_associations=source_rows,static_paths=mapping['static_paths'],
        discovery_runs=len(discoveries),probe_runs=len(probes),stable_eval_steps=sum(v is not None for (s,p),v in labels.items() if p=='eval'),
        dynamic_top1=rank_dynamic_batches(mapping,probes),
        phase_costs=[dict(batch_key=k,clock=c,scope=s,wave=w,**v) for (k,c,s,w),v in sorted(phase_costs.items())],
        limits=['Static work is a structural estimate, not hardware timing or elapsed time.',
                'Last completion and longest body are reported separately; timestamps include instrumentation perturbation.',
                'Batch probes use critical-step labels frozen from independent wrapper-only discovery runs.',
                'RTL spans are associated with a measured batch. Associated costs overlap and are not additive line timings.',
                'Entry activity masks do not reveal later activation within a batch.',
                'Missing source/ASC provenance remains explicit; no match is inferred from nearby line numbers.',
                'Update denotes inter-partition publication; commit batches execute inside eval.',
                'Finite differential tests are evidence for their recorded stimuli, not an equivalence proof.'])


def write_html(report, mapping, path):
    from grhsim_rtl_path_view import build_view, write_view
    return write_view(build_view(report, mapping), path)
