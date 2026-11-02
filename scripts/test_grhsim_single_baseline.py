import unittest

from grhsim_single_baseline import parse_run
from grhsim_numa import inspect_locality, locality_errors


class BaselineLogTests(unittest.TestCase):
    LOG = ('Difftest enabled.\n'
           '\x1b[33mEXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000000\n\x1b[0m'
           'Core-0 instrCnt = 240349, cycleCnt = 99996, IPC = 2.4\n'
           'Seed=0 Guest cycle spent: 100001 (this will be different from cycleCnt)\n'
           'Host time spent: 12,345ms\n')

    def test_exact_cycle_limit_and_unique_measurement(self):
        result = parse_run(self.LOG, 100000)
        self.assertEqual(result['host_ms'], 12345)
        self.assertEqual(result['pc'], '0x80000000')
        self.assertEqual(result['cycle_count'], 99996)
        with self.assertRaises(ValueError):
            parse_run(self.LOG, 100001)
        with self.assertRaises(ValueError):
            parse_run(self.LOG + 'Host time spent: 123ms\n', 100000)

    def test_failure_and_absent_difftest_are_rejected(self):
        for text in [self.LOG + 'mismatch\n', self.LOG.replace('Difftest enabled.', ''),
                     self.LOG.replace('12,345ms', '0ms')]:
            with self.subTest(log=text), self.assertRaises(ValueError):
                parse_run(text, 100000)


class NumaLocalityTests(unittest.TestCase):
    PLAN = dict(node=1, interpreter=dict(path='/system/ld.so'), files=[
        dict(destination='/run/emu', role='binary'),
        dict(destination='/run/nemu.so', role='reference'),
        dict(destination='/run/lib/libc.so', role='library')])
    MAPS = ('00001000-00002000 r-xp 00000000 00:00 1 /run/emu\n'
            '00002000-00003000 rw-p 00000000 00:00 0 [heap]\n'
            '00003000-00004000 r-xp 00000000 00:00 2 /system/ld.so\n'
            '00004000-00005000 r-xp 00000000 00:00 3 /run/nemu.so\n'
            '00005000-00006000 r-xp 00000000 00:00 4 /run/lib/libc.so\n')
    NUMA = ('1000 bind:1 file=/run/emu N1=20 kernelpagesize_kB=4\n'
            '2000 bind:1 heap anon=100 dirty=100 N1=100 kernelpagesize_kB=4\n'
            '3000 bind:1 file=/system/ld.so N0=2 kernelpagesize_kB=4\n'
            '4000 bind:1 file=/run/nemu.so N1=5 kernelpagesize_kB=4\n'
            '5000 bind:1 file=/run/lib/libc.so N1=8 kernelpagesize_kB=4\n')

    def test_local_runtime_and_anonymous_state_with_loader_reported_separately(self):
        record = inspect_locality(self.MAPS, self.NUMA, self.PLAN)
        self.assertEqual(locality_errors(record, 1), [])
        self.assertEqual(record['groups']['binary']['executable_pages'], {'1': 20})
        self.assertEqual(record['groups']['anonymous']['pages'], {'1': 100})
        self.assertEqual(record['external']['/system/ld.so']['pages'], {'0': 2})
        self.assertEqual(set(record['seen_files']), {e['destination'] for e in self.PLAN['files']})

    def test_bind_policy_does_not_hide_remote_file_cache_or_state(self):
        for before, after, kind, count in [('N1=20', 'N0=20', 'binary', 20),
                                           ('N1=100', 'N0=1 N1=99', 'anonymous', 1),
                                           ('N1=5', 'N0=5', 'reference', 5),
                                           ('N1=8', 'N0=8', 'library', 8)]:
            with self.subTest(kind=kind):
                record = inspect_locality(self.MAPS, self.NUMA.replace(before, after), self.PLAN)
                self.assertEqual(locality_errors(record, 1), [dict(kind=kind, remote_pages={'0': count})])

    def test_unstaged_executable_library_is_rejected_even_if_local(self):
        maps = self.MAPS.replace('/run/lib/libc.so', '/system/libc.so')
        record = inspect_locality(maps, self.NUMA, self.PLAN)
        self.assertEqual(locality_errors(record, 1), [dict(unmanaged_executable=['/system/libc.so'])])


if __name__ == '__main__':
    unittest.main()
