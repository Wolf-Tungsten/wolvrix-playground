#!/usr/bin/env python3
from copy import deepcopy
import csv
import json
from pathlib import Path
import struct
import tempfile
import unittest

from grhsim_source_map import source_span, build_source_map, verify_package, identity, add_asc_map, add_communication
from grhsim_path_report import HEADER, RECORD, summarize_timeline, reference_labels, summarize_batches, assemble_report, write_html
from grhsim_path_instrument import instrument_wrapper
from grhsim_rtl_rewrite import compare_traces, materialize
from grhsim_critical_path import page_kind
from grhsim_chisel_map import build_chisel_index, resolve_module, normalized_module


class CriticalPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def trace(self,name='trace.bin',batch=False):
        events=[]
        for part in range(2):
            for step in range(1,5):
                clock=(step-1)%2
                for phase in range(3):
                    base=step*1000+phase*200
                    start,end=(base+10,base+60) if part==0 else (base+65,base+85)
                    events.append((step,start,end,part+100,part,0xffffffff,0,0xffffffff,0,phase,clock,0))
                    if batch and phase==1 and part==1:
                        events.append((step,start+1,end-1,part+100,part,0,1,0,1,3,clock,0))
        for step in range(1,5):
            for phase in range(3):
                base=step*1000+phase*200
                events.append((step,base,base+100,99,2,0xffffffff,0,0xffffffff,0,phase+5,(step-1)%2,0))
        path=self.root/name
        path.write_bytes(HEADER.pack(b'GRHCP001',1,64,2,1,2,1 if batch else 0,1 if batch else 0xffffffff,0,len(events))+
                         b''.join(RECORD.pack(*event) for event in events))
        return path

    def test_last_completion_is_not_longest_body(self):
        report=summarize_timeline(self.trace())
        self.assertEqual(len(report['steps']),12)
        for step in report['steps']:
            self.assertEqual(step['last_part'],1)
            self.assertEqual(step['longest_body_part'],0)
            self.assertEqual(step['exclusive_tail_ns'],25)
            self.assertEqual(step['host_completion_ns'],15)

    def test_truncated_extended_version_and_missing_samples(self):
        path=self.trace();original=path.read_bytes()
        for data in (original[:-1],original+b'x',original[:8]+struct.pack('<I',2)+original[12:]):
            path.write_bytes(data)
            with self.assertRaises(ValueError):summarize_timeline(path)
        data=bytearray(original)
        # Claim one fewer record and truncate it: shape valid, window incomplete.
        struct.pack_into('<Q',data,40,(len(data)-48)//64-1)
        path.write_bytes(data[:-64])
        with self.assertRaisesRegex(ValueError,'missing|incomplete'):summarize_timeline(path)

    def test_duplicate_ties_and_window_labels(self):
        a=summarize_timeline(self.trace())
        b=deepcopy(a);b['steps'][0]['last_part']=0
        labels=reference_labels([a,b])
        self.assertIsNone(labels[1,'input'])
        self.assertEqual(labels[1,'eval'],1)
        b['steps'][0]['clock']=1
        with self.assertRaisesRegex(ValueError,'window'):reference_labels([a,b])
        data=bytearray(self.trace().read_bytes());data[48+64:48+128]=data[48:48+64]
        p=self.root/'duplicate.bin';p.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'duplicate'):summarize_timeline(p)

    def test_batch_binding_and_round_accounting(self):
        reference=summarize_timeline(self.trace())
        mapping={'batches':{'1:compute:0':{}}}
        probe=summarize_batches(self.trace('batch.bin',True),mapping,reference_labels([reference,reference]))
        self.assertEqual(probe['sampled_steps'],4)
        self.assertEqual(sum(r['calls'] for r in probe['batches']),4)
        self.assertEqual(sum(r['sampled_steps'] for r in probe['sample_coverage']),4)
        self.assertEqual({r['clock'] for r in probe['sample_coverage']},{0,1})
        self.assertTrue(all(r['scope']=='stable_last' and r['wave']=='first' for r in probe['batches']))
        with self.assertRaisesRegex(ValueError,'unmapped'):
            summarize_batches(self.trace('badbatch.bin',True),{'batches':{}},reference_labels([reference,reference]))

    def test_ids_relocate_and_keep_unknown_ranges_unknown(self):
        a=self.root/'one/rtl';b=self.root/'two/rtl'
        row=dict(file=str(a/'unit.sv'),line='3',column='5',end_line='0',end_column='0')
        first=source_span(row,a)
        second=source_span(dict(row,file=str(b/'unit.sv'),origin='transform'),b)
        self.assertEqual(first['source_span_id'],second['source_span_id'])
        self.assertEqual(first['precision'],'point');self.assertIsNone(first['end_line'])
        self.assertIsNone(source_span(dict(row,file='')))
        with self.assertRaisesRegex(ValueError,'reversed'):
            source_span(dict(row,end_line='2',end_column='5'))

    def mapping(self):
        native=self.root/'native';native.mkdir();rtl=self.root/'rtl';rtl.mkdir()
        (rtl/'unit.sv').write_text('module unit;\nwire a;\nendmodule\n')
        fields='part,batch,phase,group,active_id,op_index,op_symbol,op_kind,work,activity_mask,group_mask,value_ids,value_symbols,file,line,column,end_line,end_column,origin,pass,note,location_kind,fanout,boundary,storage'.split(',')
        with (native/'inst_part_1.sources.csv').open('w',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
            for op,file,line,work in [(0,str(rtl/'unit.sv'),'2',7),(1,'','0',3)]:
                row={key:'' for key in fields}
                row.update(part='inst_part_1',batch='0',phase='compute',group='0',active_id='0',op_index=str(op),op_symbol=f'op{op}',op_kind='kAnd',work=str(work),activity_mask='3',group_mask='3',file=file,line=line,column='1',end_line='0',end_column='0',fanout='0',boundary='0',location_kind='operation')
                w.writerow(row)
        (native/'inst_part_1.paths.csv').write_text('part,clock,rank,work,unknown_operations,position,op_index\ninst_part_1,0,1,10,0,0,0\ninst_part_1,0,1,10,0,1,1\n')
        (native/'inst_part_1.batches.csv').write_text('part,batch,phase,estimated_lines,groups,active_words\ninst_part_1,0,compute,2,0,0\n')
        return build_source_map(native,self.root/'map',rtl),native

    def test_mapping_counts_unknown_and_batch_cost_not_split(self):
        mapping,_=self.mapping()
        self.assertEqual(mapping['summary']['operation_coverage'],.5)
        self.assertEqual(mapping['summary']['work_coverage'],.7)
        reference=summarize_timeline(self.trace())
        probe=summarize_batches(self.trace('deep.bin',True),mapping,reference_labels([reference,reference]))
        report=assemble_report(mapping,[reference,reference],[probe])
        self.assertEqual(len(report['source_associations']),1)
        source=report['source_associations'][0]
        self.assertNotIn('eval_score',source)
        self.assertEqual(source['associated_batch_ns'],report['batch_ranking'][0]['critical_sample_ns'])
        self.assertEqual(report['batch_ranking'][0]['unmapped_operations'],1)
        html=self.root/'report.html';write_html(report,mapping,html)
        self.assertIn('application/json',html.read_text())
        dynamic=json.loads((self.root/'dynamic_top1.json').read_text())
        row=next(r for r in dynamic['rows'] if r['clock']==0 and r['scope']=='stable_last')
        self.assertEqual(row['batch_key'],'1:compute:0')
        self.assertEqual(row['modules'][0]['name'],'unit')
        self.assertEqual(row['signals'][0]['signal'],'a')
        self.assertEqual(row['signals'][0]['line'],2)
        self.assertIn('动态关键路径第一名',(self.root/'dynamic_top1.md').read_text())

    def test_static_only_does_not_invent_dynamic_measurements(self):
        mapping,_=self.mapping();reference=summarize_timeline(self.trace())
        report=assemble_report(mapping,[reference,reference],[])
        self.assertEqual(report['source_associations'],[])
        self.assertFalse(report['batch_ranking'][0]['measured'])
        self.assertEqual(report['batch_ranking'][0]['classification'],'static-only')

    def test_package_membership_is_verified(self):
        _,native=self.mapping();package=self.root/'package';package.mkdir()
        cpp=package/'grhsim_Gpart_1_model_sched_0.cpp'
        cpp.write_text('void GrhSIM_Gpart_1_model::eval_compute_batch_0() {\n// Supernode 0:\n}\n')
        self.assertEqual(verify_package(native,package)['batches'],1)
        cpp.write_text(cpp.read_text().replace('Supernode 0','Supernode 1'))
        with self.assertRaisesRegex(ValueError,'differ'):verify_package(native,package)

    def test_instrumenter_refuses_unsupported_early_phases(self):
        with self.assertRaisesRegex(ValueError,'early'):
            instrument_wrapper('void step() {}','common')

    def test_exact_asc_join_does_not_guess_transformed_operations(self):
        mapping,_=self.mapping()
        path=self.root/'asc.csv'
        path.write_text('op_symbol,op_kind,raw_op_index,value_symbols,part,asc_ids\nop0,kAnd,99,,1,7;9\nop1,kNot,100,,1,8\n')
        record=add_asc_map(mapping,path,self.root/'map',[1])
        self.assertEqual(record['mapped_operations'],1)
        self.assertEqual(record['unmapped_operations'],1)
        self.assertEqual(mapping['batches']['1:compute:0']['asc_ids'],[7,9])

    def test_cross_partition_edges_use_actual_input_masks(self):
        mapping,native=self.mapping()
        (native/'inst_part_1.ports.csv').write_text('part,direction,name,value,symbol,width\ninst_part_1,input,repcut_port_0,7,a,64\ninst_part_1,input,repcut_port_1,8,b,1\n')
        (native/'input_masks.csv').write_text('part,value,target,word,mask\ninst_part_1,7,0,0,255\n')
        package=self.root/'package';package.mkdir()
        (package/'wolvi_repcut_grhsim_sim_update_0.cpp').write_text('copy_changed_wide_words_(unit_part_1_->in_0, unit_part_0_->out_2, 1);\ncopy_changed_scalar_(unit_part_1_->in_1, unit_part_0_->out_3);\n')
        edges=add_communication(mapping,native,package)
        self.assertEqual(edges[0]['active_ids'],[0]);self.assertIsNone(edges[1]['active_ids'])
        self.assertEqual(mapping['batches']['1:compute:0']['cross_partition_inputs'],[0])

    def test_effective_page_mode_is_audited(self):
        for huge,expected in ((0,'small'),(4096,'thp')):
            self.assertEqual(page_kind({'codepages':dict(mode='auto',bytes=4096,huge_bytes=huge)}),expected)
        with self.assertRaisesRegex(ValueError,'partial'):
            page_kind({'codepages':dict(mode='auto',bytes=4096,huge_bytes=1024)})

    def test_chisel_mapping_reports_unique_best_and_ambiguous_matches(self):
        root=self.root/'xiangshan';(root/'src/main/scala/a').mkdir(parents=True)
        (root/'src/main/scala/a/Rob.scala').write_text('package a\nclass Rob { val debug_exuData = 0 }\n')
        (root/'src/main/scala/a/One.scala').write_text('package a\nclass One { val foo = 0 }\n')
        (root/'src/main/scala/b/Two.scala').parent.mkdir(parents=True)
        (root/'src/main/scala/b/Two.scala').write_text('package b\nclass Rob { val other = 0 }\n')
        index=build_chisel_index(root)
        unique=resolve_module('Rob',['debug_exuData'],index)
        self.assertEqual(unique['status'],'best-signal-match')
        self.assertEqual(unique['selected']['qualified'],'a.Rob')
        ambiguous=resolve_module('Rob',['missing_signal'],index)
        self.assertEqual(ambiguous['status'],'ambiguous')
        self.assertEqual(normalized_module('MSHR_64'),'MSHR')


class DifferentialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def traces(self):
        inputs=[dict(cycle=i,inputs={'a':i}) for i in range(3)]
        stim=self.root/'stim.jsonl';stim.write_text(''.join(json.dumps(r)+'\n' for r in inputs))
        rows=[dict(schema_version=1,stimulus_sha256=identity(stim)['sha256'],observables=['outputs.y'])]
        rows += [dict(**r,outputs={'y':r['inputs']['a']},state={},commits=[]) for r in inputs]
        a=self.root/'a.jsonl';a.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        b=self.root/'b.jsonl';b.write_text(a.read_text())
        return a,b,stim,rows

    def test_cycle_inputs_and_observables(self):
        a,b,stim,rows=self.traces();self.assertEqual(compare_traces(a,b,stim,3)['cycles'],3)
        rows[2]['outputs']['y']=100;b.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'mismatch'):compare_traces(a,b,stim,3)

    def test_empty_truncated_reordered_and_extra_cannot_pass(self):
        a,b,stim,rows=self.traces()
        for variant in ([],rows[:-1],rows+[rows[-1]],rows[:1]+list(reversed(rows[1:]))):
            b.write_text(''.join(json.dumps(r)+'\n' for r in variant))
            with self.assertRaises(ValueError):compare_traces(a,b,stim,3)

    def test_declared_but_missing_observation_cannot_pass(self):
        a,b,stim,rows=self.traces();rows[0]['observables']=['state.missing']
        for path in (a,b):path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'absent'):compare_traces(a,b,stim,3)

    def test_candidate_preserves_original_and_checks_hash(self):
        source=self.root/'a.sv';source.write_text('assign y = a[7:0];\n')
        filelist=self.root/'input.f';filelist.write_text(str(source)+'\n')
        row=dict(file=str(source),begin=11,end=17,before='a[7:0]',after='a')
        before=source.read_bytes();manifest=materialize(row,'unsigned-full-width-static-slice',filelist,self.root/'cand',identity(source))
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(Path(manifest['rewritten']['path']).read_text(),'assign y = a;\n')
        old=identity(source);source.write_text('//changed\n'+source.read_text())
        with self.assertRaisesRegex(ValueError,'changed'):
            materialize(row,'rule',filelist,self.root/'wrong',old)


if __name__=='__main__':unittest.main()
