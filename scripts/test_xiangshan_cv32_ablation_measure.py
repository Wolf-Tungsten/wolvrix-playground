from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from grhsim_single_baseline import save
from xiangshan_cv32_ablation_measure import (VARIANTS, measurement_lock, order_for_round,
                                            run_protocol, summaries)
from xiangshan_cv32_ablation_pmu import parse_counts


class AblationTests(unittest.TestCase):
    def test_pmu_event_completeness_multiplexing_and_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'perf.csv'
            valid='\n'.join(f'{value},,{event},1000000000,100.00,,' for event,value in
                [('cycles:u',1000),('instructions:u',2000),('branches:u',500),('branch-misses:u',5)])
            path.write_text(valid)
            result=parse_counts(path,100)
            self.assertEqual(result['per_guest_cycle']['instructions:u'],20)
            self.assertEqual(result['ipc'],2)
            self.assertEqual(result['branch_miss_fraction'],.01)
            for invalid in (valid.replace('100.00','98.99'),valid.replace('2000','<not supported>'),
                            valid+'\n'+valid.splitlines()[0],'\n'.join(valid.splitlines()[:3])):
                path.write_text(invalid)
                with self.assertRaises(ValueError):parse_counts(path,100)

    def test_same_round_direction_and_independent_metrics(self):
        rows=[]
        for index in range(8):
            base=1000+100*index
            rows.append(dict(full=dict(host_ms=base,external_wall_s=base/1000),
                no_shared=dict(host_ms=base*.9,external_wall_s=base*.8/1000),
                no_cones=dict(host_ms=base*1.1,external_wall_s=base*1.2/1000)))
        result=summaries(rows)
        for name,host,wall in [('no_shared',-10,-20),('no_cones',10,20)]:
            for metric,expected in [('host_ms',host),('external_wall_s',wall)]:
                row=result[name][metric]
                self.assertEqual(row['baseline'],'full')
                self.assertEqual(row['candidate'],name)
                self.assertAlmostEqual(row['delta_percent_mean'],expected)
                for endpoint in row['delta_percent_ci95']:self.assertAlmostEqual(endpoint,expected)
        with self.assertRaises(ValueError):summaries(rows[:7])
        rows[0]['no_shared']['host_ms']=float('nan')
        with self.assertRaises(ValueError):summaries(rows)

    def test_lock_rejects_overlapping_run_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            lock=Path(directory)/'cpu96.lock'
            with measurement_lock(lock):
                with self.assertRaisesRegex(RuntimeError,'held'):
                    with measurement_lock(lock):pass
            with measurement_lock(lock):pass

    def test_protocol_orders_all_runs_and_checks_full_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls=[]
            save(root/'manifest.json',dict(files=[]));save(root/'measurement-policy.json',{})
            class Runner:
                def __init__(self,name):self.name=name
                def run_sample(self,prepared,label,cycles,seed,extra):
                    calls.append((self.name,label,cycles,seed,extra))
                    return dict(pc='0x80000c1a',instr_count=250838,cycle_count=cycles-5,
                        guest_cycles=cycles+1,stop_reason='cycle-limit',workload_output='CoreMark',
                        runtime_difftest='on',host_ms=1000,external_wall_s=1.01)
            runners={name:Runner(name) for name in VARIANTS}
            prepared={name:dict(binary=root/name/'emu') for name in VARIANTS}
            def compare(tool,a,b,path):
                self.assertEqual(a.parent.name,'full')
                self.assertIn(b.parent.name,VARIANTS[1:])
                return dict(pass_=True,records=99999,first_cycle=0,last_cycle=99995)
            with patch('xiangshan_cv32_ablation_measure.compare_traces',side_effect=compare) as compared:
                result=run_protocol(root,runners,prepared,None,dict(files=[]))
            self.assertEqual(compared.call_count,4)
            self.assertEqual(len(calls),36)
            self.assertEqual([x[0] for x in calls[:3]],list(VARIANTS))
            self.assertTrue(all(x[2]==10000 for x in calls[:3]))
            self.assertTrue(all(x[4] for x in calls[3:9]))
            self.assertTrue(all(not x[4] for x in calls[9:]))
            expected=[name for index in range(8) for name in order_for_round(index)]
            self.assertEqual([x[0] for x in calls[12:]],expected)
            self.assertEqual(result['status'],'pass')
            self.assertEqual(len(result['rounds']),8)

    def test_functional_mismatch_stops_before_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls=[]
            class Runner:
                def __init__(self,name):self.name=name
                def run_sample(self,prepared,label,cycles,seed,extra):
                    calls.append(label)
                    return dict(pc=self.name,instr_count=1,cycle_count=cycles-5,
                        guest_cycles=cycles+1,stop_reason='cycle-limit',workload_output='CoreMark',
                        runtime_difftest='on',host_ms=1,external_wall_s=.001)
            with self.assertRaisesRegex(ValueError,'smoke signatures differ'):
                run_protocol(root,{n:Runner(n) for n in VARIANTS},{n:{} for n in VARIANTS},None,dict(files=[]))
            self.assertEqual(calls,['smoke']*3)


if __name__=='__main__':unittest.main()
