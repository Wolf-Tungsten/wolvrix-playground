import copy
import unittest

from grhsim32_pair_compare import (bind_runtime_memory, select_runtime_cpus, signature,
                                   validate_builds, validate_runtime, validate_thread_placement)


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

    def test_runtime_cpu_override_does_not_depend_on_build_cpu_metadata(self):
        original = list(range(32))
        configs = {key: dict(runtime_cpus=original) for key in ('A', 'B')}
        self.assertEqual(select_runtime_cpus(configs, '96-127'), list(range(96, 128)))
        self.assertEqual(configs['A']['runtime_cpus'], original)
        self.assertEqual(select_runtime_cpus(configs), original)
        for invalid in ('96-126', '96-127,128'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                select_runtime_cpus(configs, invalid)

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
        # After joining workers, the wrapper restores the host's original
        # broad affinity. That teardown sample is outside the 32-lane run.
        teardown=dict(elapsed_s=3,tasks=[dict(tid=1000,cpus=self.cpus)])
        validate_thread_placement([good,teardown],self.cpus,32)

    def test_strict_memory_policy_preserves_other_runtime_arguments(self):
        command=['taskset','-c','0-31','numactl','--preferred=0','setarch','x86_64','-R','env','LD_PRELOAD=/private/lib.so','/private/emu']
        bound=bind_runtime_memory(command,0)
        self.assertEqual(bound,[arg if arg!='--preferred=0' else '--membind=0' for arg in command])
        self.assertEqual(bind_runtime_memory(bound,0),bound)
        for invalid in (command[:4]+command[5:],command+['--membind=0'],command):
            with self.assertRaises(ValueError):bind_runtime_memory(invalid,1 if invalid==command else 0)


if __name__ == '__main__':
    unittest.main()
