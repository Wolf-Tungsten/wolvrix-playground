#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
import unittest

from grhsim_dynamic_top import rank_dynamic_batches
from grhsim_path_instrument import instrument_eval


def mapping():
    return {'batches': {f'{part}:{phase}:{batch}': dict(part=part, phase=phase, batch=batch,
        structural_work=1000 if batch == 1 else 1)
        for part in (0, 1) for phase, batch in (('compute', 1), ('compute', 2), ('commit', 1))}}


def cost(key, ns, clock=0, scope='stable_last', wave='first', calls=1, zero=0):
    return dict(batch_key=key, clock=clock, scope=scope, wave=wave, ns=ns, calls=calls,
                entry_nonzero_calls=0 if zero else calls, entry_zero_ns=zero, max_call_ns=ns//calls)


def probe(rows, critical=3, other=2):
    return dict(header=dict(selected_part=0), batches=rows,
        sample_coverage=[dict(clock=clock, scope=scope, sampled_steps=n, steps_with_batches=n)
                        for clock in (0, 1) for scope, n in (('stable_last', critical), ('other', other))])


def row(result, clock=0, scope='stable_last', part=0):
    return next(r for r in result['rows'] if (r['part'],r['clock'],r['scope'])==(part,clock,scope))


class DynamicRankingTest(unittest.TestCase):
    def test_measured_sum_not_static_weight_or_mean_and_keep_clocks(self):
        result=rank_dynamic_batches(mapping(), [probe([
            cost('0:compute:1',80),cost('0:compute:2',120,calls=12),
            cost('0:commit:1',200,clock=1)])])
        first=row(result)
        self.assertEqual(first['batch_key'],'0:compute:2')
        self.assertEqual(first['mean_call_ns'],10)
        self.assertEqual(first['share'],.6)
        self.assertEqual(row(result,clock=1)['batch_key'],'0:commit:1')
        self.assertFalse(first['repeated_top'])

    def test_critical_scope_does_not_use_noncritical_or_static_fallback(self):
        result=rank_dynamic_batches(mapping(), [probe([
            cost('0:compute:1',2000,scope='other'),cost('0:compute:2',120)])])
        self.assertEqual(row(result)['batch_key'],'0:compute:2')
        self.assertEqual(row(result,scope='all_sampled')['batch_key'],'0:compute:1')
        self.assertEqual(row(result)['sampled_steps'],3)
        self.assertEqual(row(result,scope='all_sampled')['sampled_steps'],5)
        empty=rank_dynamic_batches(mapping(),[probe([cost('0:compute:1',99,scope='other')],critical=0)])
        self.assertEqual(row(empty)['status'],'no_critical_samples')
        self.assertIsNone(row(empty)['batch_key'])
        self.assertEqual(row(empty,part=1)['status'],'not_measured')
        self.assertIsNone(row(empty,part=1)['sampled_steps'])

    def test_repeats_keep_disagreement_visible(self):
        a=probe([cost('0:compute:1',110),cost('0:compute:2',100)])
        b=probe([cost('0:compute:1',80),cost('0:compute:2',100)])
        first=row(rank_dynamic_batches(mapping(),[a,b]))
        self.assertEqual(first['batch_key'],'0:compute:2')
        self.assertEqual(first['repeat_top_agreement'],1)
        self.assertFalse(first['repeated_top'])
        self.assertEqual(first['sampled_steps'],6)
        self.assertEqual([r['winner_ns'] for r in first['repeats']],[100,100])
        repeated=row(rank_dynamic_batches(mapping(),[a,a]))
        self.assertTrue(repeated['repeated_top'])

    def test_waves_zero_entry_and_maximum_are_not_summed_as_peaks(self):
        a=probe([cost('0:compute:1',30,calls=3,zero=30),
                 cost('0:compute:1',50,wave='after_commit',zero=50)])
        first=row(rank_dynamic_batches(mapping(),[a,a]))
        self.assertEqual(first['ns'],160)
        self.assertEqual(first['waves'],dict(first=60,after_commit=100))
        self.assertEqual(first['max_call_ns'],50)
        self.assertEqual(first['entry_zero_share'],1)
        self.assertEqual(first['entry_nonzero_calls'],0)

    def test_ties_are_explicit_and_not_repeated_unique_winners(self):
        a=probe([cost('0:compute:2',40),cost('0:compute:1',40)])
        first=row(rank_dynamic_batches(mapping(),[a,a]))
        self.assertEqual(first['tied_keys'],['0:compute:1','0:compute:2'])
        self.assertFalse(first['repeated_top'])
        self.assertEqual(first['repeat_top_agreement'],0)

    def test_zero_work_window_is_not_missing_trace(self):
        first=row(rank_dynamic_batches(mapping(),[probe([])]))
        self.assertEqual(first['status'],'no_batch_calls')
        self.assertEqual(first['sampled_steps'],3)
        self.assertIsNone(first['batch_key'])

    def test_reject_partition_mismatch_and_invalid_counters(self):
        for bad in (cost('1:compute:1',20),cost('0:compute:1',-1),cost('0:compute:1',2,zero=3)):
            with self.assertRaises(ValueError):rank_dynamic_batches(mapping(),[probe([bad])])


class MultiWordInstrumentationTest(unittest.TestCase):
    def test_multiword_entry_masks_and_exactly_one_call(self):
        artifacts=Path(__file__).resolve().parents[1]/'wolvrix/build/artifacts/grhsim-critical-path'
        artifacts.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='multiword-',dir=artifacts) as directory:
            root=Path(directory)
            (root/'grhsim_Gpart_0_model_sched_1.cpp').write_text('''
constexpr std::uint8_t dispatchMask = UINT8_C(1);
std::uint8_t activeWordFlags = static_cast<std::uint8_t>(supernode_active_curr_[0u] & dispatchMask);
constexpr std::uint8_t dispatchMask = UINT8_C(128);
std::uint8_t activeWordFlags = static_cast<std::uint8_t>(supernode_active_curr_[3u] & dispatchMask);
''')
            original='''#include <cstdint>
struct Model {
  std::uint8_t supernode_active_curr_[4] = {2,0,0,128};
  bool commit_activated_readers_ = false, pending_eval_round = false;
  unsigned fixed_point_round_count = 0, calls = 0;
  void eval_compute_batch_1() { ++calls; supernode_active_curr_[0] = 1; }
  void eval() {
        ++fixed_point_round_count;
        this->eval_compute_batch_1();
        pending_eval_round = commit_activated_readers_ || false;
  }
};
'''
            instrumented,sites=instrument_eval(original,root,0)
            self.assertEqual(sites[0]['entry_mask_kind'],'or_of_words')
            self.assertEqual(sites[0]['activity_words'],[dict(word=0,mask=1),dict(word=3,mask=128)])
            (root/'grhsim_path_trace.hpp').write_text('''#include <cstdint>
namespace grhsim_path_trace {
inline unsigned seen_word=0,seen_mask=0,hits=0;
inline bool enabled=true;
inline void round(unsigned) {} inline void committed(bool) {}
inline bool sample() { return enabled; }
template<class F> void batch(unsigned,unsigned,unsigned word,unsigned mask,F fn) {
  ++hits; seen_word=word; seen_mask=mask; fn();
}
}
''')
            (root/'test.cpp').write_text(instrumented+'''
#include <cassert>
int main() {
  Model a; a.eval();
  assert(a.calls==1 && a.supernode_active_curr_[0]==1);
  assert(grhsim_path_trace::seen_word==UINT32_MAX && grhsim_path_trace::seen_mask==128);
  a.supernode_active_curr_[0]=2; a.supernode_active_curr_[3]=1; a.eval();
  assert(a.calls==2 && grhsim_path_trace::seen_mask==0);
  grhsim_path_trace::enabled=false; a.eval();
  assert(a.calls==3 && grhsim_path_trace::hits==2);
}
''')
            subprocess.run(['c++','-std=c++20','-O3',str(root/'test.cpp'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)


if __name__=='__main__':unittest.main()
