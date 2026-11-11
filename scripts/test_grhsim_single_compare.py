import ctypes
from pathlib import Path
import tempfile
import unittest

from grhsim_difftrace import build_comparator, compare_traces, validate_trace_coverage
from grhsim_single_compare import (build_modes, compare_footprints, pair_order,
                                   revision_signature, run_signature, runtime_modes, summarize)


class PairTests(unittest.TestCase):
    def test_independent_runtime_modes_preserve_variant_labels(self):
        self.assertEqual(runtime_modes('on'),dict(A='on',B='on'))
        self.assertEqual(runtime_modes('off'),dict(A='off',B='off'))
        self.assertEqual(runtime_modes('on',baseline='off'),dict(A='off',B='on'))
        self.assertEqual(runtime_modes('off',candidate='on'),dict(A='off',B='on'))

    def test_model_and_compile_modes_are_independent_of_runtime(self):
        self.assertEqual(build_modes(dict(rtl_difftest='on'), 'off'),
                         dict(rtl='on',model='off',compile='off'))
        self.assertEqual(build_modes(dict(rtl_difftest='on',model_difftest='on',
                                          compile_difftest='on'), 'off'),
                         dict(rtl='on',model='on',compile='on'))
        self.assertEqual(build_modes(dict(rtl_difftest='on',model_difftest='on',
                                          compile_difftest='on'), 'on'),
                         dict(rtl='on',model='on',compile='on'))

    def test_order_and_paired_statistics(self):
        self.assertEqual(pair_order(4), [('A','B'),('B','A'),('A','B'),('B','A')])
        result = summarize([{'A':{'host_ms':1000+i*100},
                             'B':{'host_ms':(1000+i*100)*0.9}} for i in range(8)])
        self.assertAlmostEqual(result['delta_percent_mean'], -10)
        self.assertAlmostEqual(result['delta_percent_ci95'][0], -10)
        self.assertEqual(result['candidate_faster_pairs'], 8)


class FootprintTests(unittest.TestCase):
    def test_matched_nonempty_memory_and_uart_output(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/name for name in ('A','B')]
            for path in paths:path.write_bytes(bytes(range(16)))
            row=dict(guest_cycles=100001,workload_output='Running CoreMark\n')
            result=compare_footprints(paths,[row,row])
            self.assertEqual(result['status'],'pass')
            for payload in (b'',b'bad',bytes(16)):
                paths[1].write_bytes(payload)
                with self.assertRaises(ValueError):compare_footprints(paths,[row,row])
            paths[1].write_bytes(paths[0].read_bytes())
            for change in (dict(guest_cycles=100000),dict(workload_output=''),dict(workload_output='wrong')):
                with self.assertRaises(ValueError):compare_footprints(paths,[row,dict(row,**change)])

    def test_no_diff_signature_includes_workload_output(self):
        row=dict(pc=None,instr_count=None,cycle_count=None,guest_cycles=100001,
                 runtime_difftest='off',stop_reason='cycle-limit',workload_output='CoreMark\n')
        self.assertNotEqual(run_signature(row),run_signature(dict(row,workload_output='')))

    def test_mixed_modes_compare_shared_observations_without_fabricating_pc(self):
        off=dict(pc=None,instr_count=None,cycle_count=None,guest_cycles=100001,
                 runtime_difftest='off',stop_reason='cycle-limit',workload_output='CoreMark\n')
        on=dict(off,pc='0x80000c0c',instr_count=240349,cycle_count=99996,runtime_difftest='on')
        self.assertEqual(run_signature(off,True),run_signature(on,True))
        self.assertNotEqual(run_signature(off),run_signature(on))
        for change in (dict(guest_cycles=100000),dict(workload_output='wrong'),dict(stop_reason='other')):
            self.assertNotEqual(run_signature(off,True),run_signature(dict(on,**change),True))

    def test_cross_revision_signature_includes_uart_but_not_schema_specific_progress(self):
        a=dict(guest_cycles=100001,stop_reason='cycle-limit',workload_output='Running CoreMark\n',
               pc='0x80000000',instr_count=10,cycle_count=8)
        b=dict(a,pc='0x80001000',instr_count=12,cycle_count=9)
        self.assertEqual(revision_signature(a),revision_signature(b))
        for change in (dict(guest_cycles=100000),dict(stop_reason='trap'),
                       dict(workload_output='other\n')):
            self.assertNotEqual(revision_signature(a),revision_signature(dict(a,**change)))


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        header = cls.root/'state.h'
        header.write_text('''#include <stdint.h>
typedef struct {
uint8_t valid;
uint64_t pc;
} Commit;
typedef struct {
uint64_t data;
} Data;
typedef struct {
uint64_t cycleCnt;
} Trap;
typedef struct {
Commit commit[2];
Data commit_data[2];
Trap trap;
} DiffTestState;
''')
        cls.comparator = build_comparator(header, cls.root/'tool')
        class Commit(ctypes.Structure):
            _fields_ = [('valid',ctypes.c_uint8),('pc',ctypes.c_uint64)]
        class Data(ctypes.Structure):
            _fields_ = [('data',ctypes.c_uint64)]
        class Trap(ctypes.Structure):
            _fields_ = [('cycleCnt',ctypes.c_uint64)]
        class State(ctypes.Structure):
            _fields_ = [('commit',Commit*2),('commit_data',Data*2),('trap',Trap)]
        cls.State = State

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def record(self, cycle=10, valid=1, pc=123, data=456, padding=0):
        s = self.State()
        ctypes.memset(ctypes.addressof(s), padding, ctypes.sizeof(s))
        for i in range(2):
            s.commit[i].valid=valid; s.commit[i].pc=pc; s.commit_data[i].data=data
        s.trap.cycleCnt=cycle
        return bytes(s)

    def compare(self,a,b):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root=Path(tmp)
            for name,records in [('A',a),('B',b)]:
                (root/name).mkdir(); (root/name/'0.bin').write_bytes(b''.join(records))
            return compare_traces(self.comparator,root/'A',root/'B',root/'result.json')

    def test_padding_and_inactive_payloads_ignored(self):
        a=[self.record(padding=0),self.record(valid=0)]
        b=[self.record(padding=255),self.record(valid=0,pc=999,data=999,padding=255)]
        self.assertEqual(self.compare(a,b)['records'],2)

    def test_effective_fields_count_and_order_checked(self):
        base=[self.record(),self.record(cycle=11)]
        for bad in [[self.record(pc=9),base[1]], [self.record(data=9),base[1]],
                    [self.record(valid=0),base[1]], [self.record(cycle=9),base[1]],
                    base[:1], base[::-1], [base[0][:-1]], []]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.compare(base,bad)

    def test_sparse_trace_coverage_uses_terminal_cycle(self):
        trace=[self.record(cycle=500),self.record(cycle=99995)]
        check=self.compare(trace,trace)
        row=dict(runtime_difftest='on',stop_reason='cycle-limit',cycle_count=99995,guest_cycles=100001)
        self.assertTrue(validate_trace_coverage(check,row)['pass_'])
        for change in (dict(records=0),dict(pass_=False),dict(last_cycle=99994)):
            with self.assertRaises(ValueError):validate_trace_coverage(dict(check,**change),row)
        for change in (dict(runtime_difftest='off'),dict(stop_reason='other'),dict(cycle_count=None)):
            with self.assertRaises(ValueError):validate_trace_coverage(check,dict(row,**change))

    def test_self_comparison_rejects_cycle_regression(self):
        records=[self.record(cycle=11),self.record(cycle=10)]
        with self.assertRaisesRegex(ValueError,'regressed'):self.compare(records,records)
        repeated=[self.record(cycle=11),self.record(cycle=11)]
        self.assertEqual(self.compare(repeated,repeated)['records'],2)

    def test_cycle_regression_between_chunks_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root=Path(tmp)
            (root/'0.bin').write_bytes(self.record(cycle=11))
            (root/'1.bin').write_bytes(self.record(cycle=10))
            with self.assertRaisesRegex(ValueError,'across chunks'):
                compare_traces(self.comparator,root,root,root/'result.json')

if __name__=='__main__': unittest.main()
