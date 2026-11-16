from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cv32e40p_event_region_counts import RegionProbes, instrument_region_source


class PhaseCounterTests(unittest.TestCase):
    def test_round_and_body_use_the_same_phase_including_three_plus(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            self.skipTest('a C++ compiler is required for the counter oracle')
        probes = RegionProbes()
        source = '''
struct GrhSIM_Cv32Bench { bool clk_i; unsigned limit; unsigned local_equality_previous_0_=99;
    bool conditional_mux_change_dirty_[1]={true};
    struct Cache { bool valid=false; unsigned previous=0; } cache;
    void eval(); };
void GrhSIM_Cv32Bench::eval()
{
    unsigned fixed_point_round_count = 0;
    bool pending_eval_round = true;
    while (pending_eval_round) {
        ++fixed_point_round_count;
        pending_eval_round = fixed_point_round_count < limit;
        // Supernode 7: run when active
        if (true) {
            const bool grhsim_changed_17 = fixed_point_round_count == 1;
            const unsigned grhsim_local_eq_address_0 = 7;
            if (grhsim_local_eq_address_0 != local_equality_previous_0_) {
                local_equality_previous_0_ = grhsim_local_eq_address_0;
            }
            // Shared equality decode: stable source, exact changed predicates.
            auto &grhsim_eq_cache_0 = cache;
            const unsigned grhsim_eq_address_0 = fixed_point_round_count <= 2 ? 7 : 9;
            if (!grhsim_eq_cache_0.valid) {
                grhsim_eq_cache_0.valid = true;
            } else if (grhsim_eq_address_0 != grhsim_eq_cache_0.previous) {
            }
            grhsim_eq_cache_0.previous = grhsim_eq_address_0;
            unsigned mux;
            // Conditional mux input cache: root=123 inputs=1
            const bool grhsim_mux_cache_miss_123 = fixed_point_round_count != 2;
            if (grhsim_mux_cache_miss_123) {
                // Conditional mux cone: root=123 true_ops=24 false_ops=24
                if (fixed_point_round_count == 1) {
                    mux = 1;
                } else {
                    mux = 2;
                }
            }
            unsigned mux2=0;
            // Conditional mux change-trigger cache: root=124 sources=5
            if (conditional_mux_change_dirty_[0u]) {
                conditional_mux_change_dirty_[0u]=false;
                // Conditional mux cone: root=124 true_ops=16 false_ops=16
                if (fixed_point_round_count == 1) {
                    mux2 = 1;
                } else {
                    mux2 = 2;
                }
            }
            bool grhsim_joint_notify_7_0 = false;
            bool grhsim_any_changed_7_0 = false;
            grhsim_joint_notify_7_0 = static_cast<bool>(grhsim_joint_notify_7_0 | (fixed_point_round_count == 4));
            grhsim_any_changed_7_0 = static_cast<bool>(grhsim_any_changed_7_0 | grhsim_joint_notify_7_0);
            bool grhsim_mux_notify_group_7_0 = false;
            grhsim_mux_notify_group_7_0 = static_cast<bool>(grhsim_mux_notify_group_7_0 | (grhsim_joint_notify_7_0));
            conditional_mux_change_dirty_[0u] = static_cast<bool>(conditional_mux_change_dirty_[0u] | (grhsim_mux_notify_group_7_0));
            if (fixed_point_round_count == 2) {
                conditional_mux_change_dirty_[0u] = true;
            }
        }
    }
}
'''
        code = instrument_region_source(probes, 'fixture_eval.cpp', source)
        round_id, group_id = probes.index['round'], probes.index['group:7']
        check_id = probes.index['local_decode_checks:0']
        update_id = probes.index['local_decode_updates:0']
        visit_id = probes.index['decode_visits:0']
        initial_id = probes.index['decode_initializations:0']
        address_id = probes.index['decode_address_changes:0']
        cmp_id, chg_id = probes.index['cmp:17'], probes.index['chg:17']
        root_id, true_id, false_id = (probes.index['mux_' + arm + ':123'] for arm in ('root', 'true', 'false'))
        cache_visit, cache_miss = (probes.index['mux_cache_' + k + ':123'] for k in ('visits', 'misses'))
        dirty_visit, dirty_miss = (probes.index['mux_cache_' + k + ':124'] for k in ('visits', 'misses'))
        notifier_visit = probes.index['mux_invalidate_visits:0']
        notifier_change = probes.index['mux_invalidations:0']
        local_visit = probes.index['mux_notify_accumulate_visits:7:0']
        local_change = probes.index['mux_notify_accumulate_changes:7:0']
        joint_id=probes.index['notify_reduction_joint:7:0']
        deferred_id=probes.index['notify_reduction_deferred:7:0']
        code += f'''
int main() {{
    GrhSIM_Cv32Bench m{{true,4}}; cv32_shape::phase=1; m.eval();
    m.clk_i=false; m.limit=1; cv32_shape::phase=0; m.eval();
    const unsigned expected[4]={{1,1,1,2}};
    const unsigned updates[4]={{0,1,0,0}}, changes[4]={{1,1,0,0}};
    const unsigned addresses[4]={{1,0,0,1}};
    const unsigned misses[4]={{1,1,0,2}};
    const unsigned dirty_misses[4]={{1,1,0,1}}, notifier_visits[4]={{1,1,2,2}}, notifications[4]={{0,0,1,1}};
    for(unsigned i=0;i<4;++i)
        if(cv32_shape::counts[{round_id}][i]!=expected[i] ||
           cv32_shape::counts[{group_id}][i]!=expected[i] ||
           cv32_shape::counts[{check_id}][i]!=expected[i] ||
           cv32_shape::counts[{visit_id}][i]!=expected[i] ||
           cv32_shape::counts[{initial_id}][i]!=updates[i] ||
           cv32_shape::counts[{address_id}][i]!=addresses[i] ||
           cv32_shape::counts[{cmp_id}][i]!=expected[i] ||
           cv32_shape::counts[{chg_id}][i]!=changes[i] ||
           cv32_shape::counts[{cache_visit}][i]!=expected[i] ||
           cv32_shape::counts[{cache_miss}][i]!=misses[i] ||
           cv32_shape::counts[{dirty_visit}][i]!=expected[i] ||
           cv32_shape::counts[{dirty_miss}][i]!=dirty_misses[i] ||
           cv32_shape::counts[{notifier_visit}][i]!=notifier_visits[i] ||
           cv32_shape::counts[{notifier_change}][i]!=notifications[i] ||
           cv32_shape::counts[{local_visit}][i]!=expected[i] ||
           cv32_shape::counts[{joint_id}][i]!=expected[i] ||
           cv32_shape::counts[{deferred_id}][i]!=expected[i] ||
           cv32_shape::counts[{local_change}][i]!=(i==3?1u:0u) ||
           cv32_shape::counts[{root_id}][i]!=misses[i] ||
           cv32_shape::counts[{true_id}][i]!=changes[i] ||
           cv32_shape::counts[{false_id}][i]!=misses[i]-changes[i] ||
           cv32_shape::counts[{update_id}][i]!=updates[i]) return 1;
}}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'shape_counters.hpp').write_text(
                f'namespace cv32_shape {{ inline unsigned phase=0; inline unsigned counts[{len(probes.entries)}][4]={{}}; }}\n')
            (root / 'model.cpp').write_text(code)
            subprocess.run([compiler, '-std=c++20', root / 'model.cpp', '-o', root / 'check'], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([root / 'check'], check=True)


if __name__ == '__main__':
    unittest.main()
