import ctypes
from pathlib import Path
import tempfile
import unittest

from grhsim_difftrace import build_comparator, compare_traces
from grhsim_single_compare import pair_order, summarize


class PairTests(unittest.TestCase):
    def test_order_and_paired_statistics(self):
        self.assertEqual(pair_order(4), [('A','B'),('B','A'),('A','B'),('B','A')])
        result = summarize([{'A':{'host_ms':1000+i*100},
                             'B':{'host_ms':(1000+i*100)*0.9}} for i in range(8)])
        self.assertAlmostEqual(result['delta_percent_mean'], -10)
        self.assertAlmostEqual(result['delta_percent_ci95'][0], -10)
        self.assertEqual(result['candidate_faster_pairs'], 8)


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

if __name__=='__main__': unittest.main()
