import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from cv32e40p_code_shapes import Probes
from cv32e40p_compare import CXX
from cv32e40p_decode_counts import DecodeProbes
from cv32e40p_remaining_gap import DetailedProbes


class GeneratedCounterTests(unittest.TestCase):
    def test_grhsim_counters_preserve_computation_and_branch(self):
        source = '''void GrhSIM_Cv32Bench::eval() {
while (pending_eval_round) {
// Supernode 7: run when its activity flag is set.
if (unlikely(activeWordFlags & UINT8_C(1))) {
const bool grhsim_changed_12 = (old_value != next_value);
value = next_value;
supernode_active_curr_[1u] |= mask;
}}}
'''
        probes = Probes()
        output = probes.instrument('grhsim', source)
        for fragment in ('while (pending_eval_round) {', 'if (unlikely(activeWordFlags & UINT8_C(1))) {',
                         'const bool grhsim_changed_12 = (old_value != next_value);',
                         'value = next_value;', 'supernode_active_curr_[1u] |= mask;'):
            self.assertEqual(output.count(fragment), 1)
        self.assertEqual(set(probes.entries), {'function:eval', 'round', 'group:7',
            'scalar_comparisons', 'scalar_changes', 'direct_active_or_executions'})
        self.assertLess(output.index('old_value != next_value'), output.index('+= (grhsim_changed_12)'))
        self.assertLess(output.index('+= (grhsim_changed_12)'), output.index('value = next_value;'))

    def test_verilator_prototypes_are_not_function_hits(self):
        source = '''void VCv32Bench___024root___nba(VCv32Bench___024root* vlSelf);
void VCv32Bench___024root___nba(VCv32Bench___024root* vlSelf) {
if (trigger) {
// Inlined CFunc: _nba_comb__TOP__0
result = input;
}}
'''
        probes = Probes()
        output = probes.instrument('verilator', source)
        self.assertEqual(probes.entries, ['function:VCv32Bench___024root___nba', 'inline:_nba_comb__TOP__0'])
        self.assertEqual(output.count('+= (1);'), 2)
        self.assertLess(output.index('if (trigger)'), output.index('cv32_shape::counts[1]'))
        self.assertIn('result = input;', output)

    def test_aggregate_probe_ids_are_reused(self):
        probes = Probes()
        first = probes.hit('changes', 'changed')
        second = probes.hit('changes', 'other_changed')
        self.assertEqual(len(probes.entries), 1)
        self.assertIn('counts[0]', first)
        self.assertIn('counts[0]', second)
        self.assertIn('v={0,0}', probes.header())

    def test_per_value_probe_observes_result_before_store(self):
        source = '''const bool next_value = (input == 23);
const bool grhsim_changed_12 = (old_value != next_value);
old_value = next_value;
'''
        probes = DetailedProbes({'12': {'width': 1}})
        output = probes.instrument('grhsim', source)
        self.assertTrue({'cmp:12', 'chg:12', 'true:12'} <= set(probes.entries))
        self.assertEqual(output.count('input == 23'), 1)
        self.assertLess(output.index('+= (next_value)'), output.index('old_value = next_value;'))
        probes = DetailedProbes({'12': {'width': 32}})
        probes.instrument('grhsim', source)
        self.assertNotIn('true:12', probes.entries)

    def test_shared_decoder_counts_cold_repeat_hit_and_miss(self):
        # The same value has three source sites, but each dynamic update counts once.
        source = '''
struct Cache { unsigned previous = 0; bool valid = false; };
struct GrhSIM_Cv32Bench {
  Cache shared_equality_cache_[1];
  unsigned address = 0;
  bool grhsim_value_12_0_slot = false;
  void eval();
};
void GrhSIM_Cv32Bench::eval() {
  auto &grhsim_eq_cache_0 = shared_equality_cache_[0u];
  const unsigned grhsim_eq_address_0 = address;
  if (!grhsim_eq_cache_0.valid) {
    const bool grhsim_changed_12 = (grhsim_value_12_0_slot != (grhsim_eq_address_0 == 3u));
    grhsim_value_12_0_slot = (grhsim_eq_address_0 == 3u);
    grhsim_eq_cache_0.valid = true;
  } else if (grhsim_eq_address_0 != grhsim_eq_cache_0.previous) {
    switch (grhsim_eq_cache_0.previous) {
      case 3u: {
        const bool grhsim_changed_12 = (grhsim_value_12_0_slot != false);
        grhsim_value_12_0_slot = false;
      } break;
      default: break;
    }
    switch (grhsim_eq_address_0) {
      case 3u: {
        const bool grhsim_changed_12 = (grhsim_value_12_0_slot != true);
        grhsim_value_12_0_slot = true;
      } break;
      default: break;
    }
  }
  grhsim_eq_cache_0.previous = grhsim_eq_address_0;
}
int main() {
  GrhSIM_Cv32Bench m;
  for (auto a : {3u, 3u, 7u, 7u, 3u, 9u}) {
    m.address = a; m.eval();
    if (m.grhsim_value_12_0_slot != (a == 3u)) return 1;
  }
  cv32_shape::dump();
}
'''
        groups = [{'cache': 0, 'value_ids': ['12']}]
        probes = DecodeProbes({'12': {'width': 1}}, groups)
        output = probes.instrument('grhsim', source)
        probes.validate(groups)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'shape_counters.hpp').write_text(probes.header())
            (root / 'probe.cpp').write_text(output)
            subprocess.run([str(CXX), '-std=c++20', '-O2', str(root / 'probe.cpp'), '-o', str(root / 'probe')],
                           check=True, capture_output=True, text=True)
            text = subprocess.check_output([str(root / 'probe')], text=True)
        counts = dict(zip(probes.entries, json.loads(text.removeprefix('CV32_SHAPE '))['counts']))
        expected = {'function:eval': 6, 'round': 0, 'scalar_comparisons': 4, 'scalar_changes': 4,
                    'cmp:12': 4, 'chg:12': 4, 'decode:0:visits': 6,
                    'decode:0:initializations': 1, 'decode:0:initial_predicate': 1,
                    'decode:0:address_changes': 3, 'decode:0:clear': 2, 'decode:0:set': 1}
        self.assertEqual({k: v[0] for k, v in counts.items()}, expected)
        self.assertTrue(all(v[1] == 0 for v in counts.values()))


if __name__ == '__main__': unittest.main()
