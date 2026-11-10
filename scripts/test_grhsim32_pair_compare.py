import copy
import unittest

from grhsim32_pair_compare import signature, validate_builds, validate_runtime, validate_thread_placement


class PairGateTests(unittest.TestCase):
    def setUp(self):
        self.cpus = list(range(96, 128))
        self.configs = {key: dict(performance=True, runtime_cpus=self.cpus, codepages='auto') for key in ('A', 'B')}
        self.results = {key: dict(performance=True, status='pass', aslr_disabled=True,
                                  numa_node=1, runtime_cpus=self.cpus) for key in ('A', 'B')}

    def test_only_matching_completed_performance_builds(self):
        validate_builds(self.configs, self.results)
        for change in (dict(performance=False), dict(status='fail'), dict(aslr_disabled=False),
                       dict(numa_node=None), dict(numa_node=0), dict(runtime_cpus=list(range(32)))):
            result = copy.deepcopy(self.results)
            result['B'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_builds(self.configs, result)
        for change in (dict(performance=False), dict(codepages='small'), dict(runtime_cpus=list(range(31)))):
            config = copy.deepcopy(self.configs)
            config['B'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_builds(config, self.results)

    def test_runtime_pinning_and_exact_cpu_set_required(self):
        config = dict(lanes=32, thread_pinning='enabled', worker_cpus=self.cpus, part_cpus=self.cpus)
        validate_runtime(config, self.cpus)
        for change in (dict(lanes=31), dict(thread_pinning='disabled'), dict(worker_cpus=[]),
                       dict(part_cpus=list(reversed(self.cpus)))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_runtime(dict(config, **change), self.cpus)

    def test_each_revision_signature_includes_uart_and_progress(self):
        row = dict(pc='0x80001234', instr_count=2000, cycle_count=9996, guest_cycles=10001,
                   stop_reason='cycle-limit', workload_output='CoreMark\n', host_ms=100)
        self.assertEqual(signature(row), signature(dict(row, host_ms=200)))
        for key in ('pc','instr_count','cycle_count','guest_cycles','stop_reason','workload_output'):
            self.assertNotEqual(signature(row), signature(dict(row, **{key:None})))

    def test_proc_affinity_gate_does_not_depend_on_buffered_banner(self):
        good = dict(elapsed_s=2, tasks=[dict(tid=cpu+1000,cpus=[cpu]) for cpu in self.cpus])
        validate_thread_placement([good],self.cpus,32)
        for masks in ([self.cpus]*32,[[96]]*32,[[cpu] for cpu in range(32)]):
            bad=dict(elapsed_s=2,tasks=[dict(tid=i+1000,cpus=mask) for i,mask in enumerate(masks)])
            with self.assertRaises(ValueError):validate_thread_placement([bad],self.cpus,32)
        with self.assertRaises(ValueError):validate_thread_placement([],self.cpus,32)
        # A final post-join snapshot may contain only the host thread.
        validate_thread_placement([good,dict(elapsed_s=3,tasks=good['tasks'][:1])],self.cpus,32)


if __name__ == '__main__':
    unittest.main()
