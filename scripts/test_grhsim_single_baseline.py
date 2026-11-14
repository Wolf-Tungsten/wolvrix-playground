import unittest
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock

from grhsim_single_baseline import (Baseline, parse_run, validate_difftest_modes,
                                    validate_simulator_binary)
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

    def test_engine_binary_classification(self):
        grhsim = '0000000000000000 T GrhSIM_SimTop::eval()\n'
        gsim = '0000000000000000 T SSimTop::step()\n'
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'emu'
            binary.write_bytes(b'emu')
            validate_simulator_binary(binary, 'grhsim', grhsim)
            validate_simulator_binary(binary, 'gsim', gsim)
            with self.assertRaisesRegex(ValueError, 'GSIM'):
                validate_simulator_binary(binary, 'gsim', grhsim)
            with self.assertRaisesRegex(ValueError, 'GrhSIM'):
                validate_simulator_binary(binary, 'grhsim', gsim)
            with self.assertRaisesRegex(ValueError, 'SSimTop'):
                validate_simulator_binary(binary, 'gsim', 'T VSimTop::eval()')

    def test_gsim_cycle_limit_log_preserves_partial_uart(self):
        log = '''emu compiled at Nov 11 2026, 12:10:02
The image is workload.bin
[DIFFTEST_INIT] core=0 state=0x1 store_q_addr=0x2 store_qsize=0
The reference model is nemu.so
The first instruction of core 0 has commited. Difftest enabled.
Running CoreM[CYCLE_LIMIT] cycles=10000 max_cycles=10000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x800027c6
Core-0 instrCnt = 458, cycleCnt = 9998, IPC = 0.045809
Seed=0 Guest cycle spent: 10001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 4088ms
'''
        row=parse_run(log,10000)
        self.assertEqual(row['workload_output'],'Running CoreM')
        self.assertEqual((row['instr_count'],row['cycle_count'],row['guest_cycles']),
                         (458,9998,10001))
        self.assertEqual(row['stop_reason'],'cycle-limit')

    def test_upstream_grouped_architectural_counters(self):
        row=parse_run(self.LOG.replace('240349','240,349').replace('99996','99,996'),100000)
        self.assertEqual(row['instr_count'],240349)
        self.assertEqual(row['cycle_count'],99996)

    def test_unbuffered_uart_before_buffered_startup_banner(self):
        log=('[runtime-config] {"lanes":32}\n[codepage] PASS mode=auto\n'
             'Running CoreMark for 2 iterations\nemu compiled at Nov 10 2026\n'
             'The image is /run/workload.bin\nThe reference model is /run/nemu.so\n'
             'The first instruction of core 0 has commited. Difftest enabled. \n'
             'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
        self.assertEqual(parse_run(log,100000)['workload_output'],'Running CoreMark for 2 iterations\n')

    def test_enabled_uart_output_with_interleaved_cycle_messages(self):
        log=('The first instruction of core 0 has commited. Difftest enabled. \n'
             'Running CoreM[CYCLE_LIMIT] cycles=10000 max_cycles=100000\n'
             'ark for 2 iterations\n[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n'
             'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
        row=parse_run(log,100000)
        self.assertEqual(row['workload_output'],'Running CoreMark for 2 iterations\n')
        self.assertEqual(row['stop_reason'],'cycle-limit')
        self.assertEqual(row['instr_count'],240349)

    def test_codepage_retry_diagnostics_preserve_split_uart(self):
        retry='[codepage-retry] retained progress, retries=3 bytes=100663296\n'
        for prefix,body in [('', 'Running CoreMark for 2 iterations\n'),
                            ('Running CoreM', 'ark for 2 iterations\n')]:
            for before_banner,in_body in [(retry,''),('',retry),(retry,retry)]:
                with self.subTest(prefix=prefix,before_banner=before_banner,in_body=in_body):
                    log=(before_banner+prefix+'emu compiled at /tmp/emu\n'
                         'The image is /tmp/image\n'
                         'The reference model is /tmp/nemu.so\n'
                         'The first instruction of core 0 has commited. Difftest enabled.\n'
                         +in_body+body.replace('iterations','iter[CYCLE_LIMIT] cycles=10000 max_cycles=100000\nations')
                         +'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
                    parsed=parse_run(log,100000)
                    self.assertEqual(parsed['workload_output'],'Running CoreMark for 2 iterations\n')

    def test_image_loader_diagnostics_do_not_split_guest_uart(self):
        rows=[]
        for pid in (1001, 2002):
            log=(f'[src/monitor/image_loader.c:205,load_img] Loading flash image: /proc/{pid}/fd/3\n\n'
                 'emu compiled at /tmp/emu\n'
                 'The image is /run/image.bin\n'
                 'The reference model is /run/nemu.so\n'
                 'The first instruction of core 0 has commited. Difftest enabled.\n'
                 f'[src/monitor/image_loader.c:250,load_img] Read 24 bytes from file /proc/{pid}/fd/3 to 0xf0000000\n'
                 'Running C[CYCLE_LIMIT] cycles=10000 max_cycles=100000\n'
                 'oreMark for 2 iterations\n'
                 'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
            rows.append(parse_run(log,100000)['workload_output'])
        self.assertEqual(rows,['Running CoreMark for 2 iterations\n']*2)

    def test_collection_enabled_but_runtime_checking_disabled(self):
        log=('The first instruction of core 0 has commited. Difftest enabled. \n'
             'Running CoreM[CYCLE_LIMIT] cycles=10000 max_cycles=100000\n'
             'ark for 2 iterations\n[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n'
             'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
        row=parse_run(log,100000,'off','on')
        self.assertEqual(row['workload_output'],'Running CoreMark for 2 iterations\n')
        self.assertEqual(row['instr_count'],240349)

    def test_enabled_uart_ignores_reference_startup_diagnostics(self):
        log=('The image is /run/workload.bin\n'
             '[DIFFTEST_INIT] core=0 state=0x100 store_q_addr=0x120 store_qsize=0\n'
             'The reference model is /run/nemu.so\n'
             'The first instruction of core 0 has commited. Difftest enabled. \n'
             'Running CoreM[CYCLE_LIMIT] cycles=10000 max_cycles=100000\n'
             'ark for 2 iterations\n[CYCLE_LIMIT] cycles=100000 max_cycles=100000\n'
             'Core 0: '+self.LOG.removeprefix('Difftest enabled.\n'))
        row=parse_run(log,100000)
        self.assertEqual(row['workload_output'],'Running CoreMark for 2 iterations\n')


class NoDiffLogTests(unittest.TestCase):
    def test_optional_cli_difftest_modes_inherit_runtime_default(self):
        with tempfile.TemporaryDirectory() as directory:
            args=argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',runtime_difftest='on',
                model_difftest=None,compile_difftest=None)
            work=Baseline(args)
            self.assertEqual(work.model_difftest,'on')
            self.assertEqual(work.compile_difftest,'on')

    LOG = ('[DIFFTEST_MODE] disabled (CONFIG_NO_DIFFTEST): collection=off checking=off\n'
           'The image is /run/workload.bin\n'
           'Running CoreMark for 2 iterations\n'
           '[EMU_COMPLETION] reason=cycle-limit cycles=100000\n'
           'Seed=0 Guest cycle spent: 100001\n'
           'Host time spent: 12,345ms\n')

    def test_no_diff_completion_without_architectural_fields(self):
        row=parse_run(self.LOG,100000,'off')
        self.assertEqual(row['host_ms'],12345)
        self.assertEqual(row['workload_output'],'Running CoreMark for 2 iterations\n')
        for key in ('pc','instr_count','cycle_count'):
            self.assertIsNone(row[key])
        with self.assertRaises(ValueError):parse_run(self.LOG,100000)

    def test_completion_can_follow_unterminated_uart_output(self):
        log=self.LOG.replace('Running CoreMark for 2 iterations\n','Running CoreM')
        row=parse_run(log,100000,'off')
        self.assertEqual(row['workload_output'],'Running CoreM')

    def test_wrong_mode_failures_and_incomplete_work_are_rejected(self):
        for text in [self.LOG.replace('[DIFFTEST_MODE]','[OTHER]'),
                     self.LOG+'Difftest enabled.\n',self.LOG+'[DIFFTEST_INIT] core=0\n',
                     self.LOG+'The reference model is /ref/nemu.so\n',
                     self.LOG.replace('reason=cycle-limit','reason=other'),
                     self.LOG.replace('cycles=100000','cycles=99999'),
                     self.LOG.replace('spent: 100001','spent: 100000'),
                     self.LOG+'ABORT\n',self.LOG+'Host time spent: 12ms\n']:
            with self.subTest(log=text), self.assertRaises(ValueError):
                parse_run(text,100000,'off')


class DifftestBuildModeTests(unittest.TestCase):
    @staticmethod
    def model_manifest(work):
        (work.generated.parent/'simulation_models.json').write_text(json.dumps(
            dict(mode=work.sim_models,lowering=work.behavior_state_lowering,models=[])))

    def test_scalar_concat_reduction_override_reaches_emitter_only(self):
        for mode,expected in [('default',None),('off','0'),('on','1')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                work=Baseline(argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                    tools_dir=None,sim_primitives='none',rtl_difftest='on',runtime_difftest='on',
                    model_difftest='on',compile_difftest='on',scalar_concat_reduction=mode))
                work.run=Mock()
                work.generated.mkdir(parents=True)
                (work.generated/'DifftestMacros.svh').write_text('')
                (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
                self.model_manifest(work)
                work.emit()
                call=next(c for c in work.run.call_args_list if c.args[1]=='emit')
                env=call.args[2]
                self.assertEqual(env.get('WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION'),expected)

    def test_post_stats_reuse_skips_frontend_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            post_stats=root/'frozen-post-stats.json'
            post_stats.write_text('{"frozen":true}')
            work=Baseline(argparse.Namespace(output=root/'out',compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='on',runtime_difftest='on',
                model_difftest='on',compile_difftest='on',reuse_post_stats_from=post_stats))
            work.run=Mock()
            work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
            self.model_manifest(work)
            work.emit()
            call=next(c for c in work.run.call_args_list if c.args[1]=='emit')
            env=call.args[2]
            self.assertEqual(env['WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON'],'1')
            self.assertEqual((work.out/'post_stats.json').read_bytes(),post_stats.read_bytes())

    def test_pre_reg_to_mem_reuse_preserves_later_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            pre_reg=root/'frozen-pre-reg-to-mem.json'
            pre_reg.write_text('{"frozen":true}')
            work=Baseline(argparse.Namespace(output=root/'out',compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='on',runtime_difftest='on',
                model_difftest='on',compile_difftest='on',reuse_pre_reg_to_mem_from=pre_reg))
            work.run=Mock()
            work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
            self.model_manifest(work)
            work.emit()
            call=next(c for c in work.run.call_args_list if c.args[1]=='emit')
            env=call.args[2]
            self.assertEqual(env['WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON'],'1')
            self.assertEqual(env['WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON'],'0')
            self.assertEqual((work.out/'pre_reg_to_mem.json').read_bytes(),pre_reg.read_bytes())

    def test_explicit_gateway_config_reaches_chisel_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Baseline(argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='on',runtime_difftest='off',
                difftest_config='U',jobs=1))
            work.run=Mock()
            work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
            self.model_manifest(work)
            work.rtl()
            command=work.run.call_args.args[0]
            sim_args=next(str(arg) for arg in command if str(arg).startswith('SIM_ARGS='))
            self.assertIn('--difftest-config U',sim_args)

    def test_packed_delay_option_reaches_chisel_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Baseline(argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='on',runtime_difftest='off',
                difftest_packed_delay_regs=True,jobs=1))
            work.run=Mock()
            work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
            self.model_manifest(work)
            work.rtl()
            command=work.run.call_args.args[0]
            sim_args=next(str(arg) for arg in command if str(arg).startswith('SIM_ARGS='))
            self.assertIn('--difftest-packed-delay-regs',sim_args)


    def test_invalid_hardware_runtime_combination(self):
        for rtl,runtime in [('on','on'),('on','off'),('off','off')]:
            validate_difftest_modes(rtl,runtime)
        with self.assertRaises(ValueError):validate_difftest_modes('off','on')

    def test_model_collection_can_be_enabled_while_runtime_checking_is_off(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Baseline(argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='on',model_difftest='on',
                compile_difftest='on',runtime_difftest='off',jobs=1))
            work.run=Mock()
            work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[{}])))
            work.emit()
            self.assertIn('-D DIFFTEST',(work.out/'read_args.txt').read_text())
            binary=work.out/'emu/grhsim-compile/emu'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
            work.compile()
            command=next(c.args[0] for c in work.run.call_args_list if c.args[1]=='compile')
            self.assertIn('NO_DIFF=0',command)

    def test_modes_reach_generation_frontend_and_compilation(self):
        for rtl,runtime in [('on','on'),('on','off'),('off','off')]:
            with self.subTest(rtl=rtl,runtime=runtime), tempfile.TemporaryDirectory() as directory:
                work=Baseline(argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                    tools_dir=None,sim_primitives='none',rtl_difftest=rtl,runtime_difftest=runtime,jobs=1))
                work.run=Mock()
                work.generated.mkdir(parents=True)
                (work.generated/'DifftestMacros.svh').write_text('')
                (work.generated/'difftest_profile.json').write_text(json.dumps(
                    dict(bundles=[{}] if rtl=='on' else [])))
                self.model_manifest(work)
                work.rtl()
                self.assertIn('DISABLE_DIFFTEST='+str(int(rtl=='off')),work.run.call_args.args[0])
                work.emit()
                self.assertEqual('-D DIFFTEST' in (work.out/'read_args.txt').read_text(),runtime=='on')
                binary=work.out/'emu/grhsim-compile/emu'
                binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
                work.compile()
                command=next(c.args[0] for c in work.run.call_args_list if c.args[1]=='compile')
                self.assertIn('NO_DIFF='+str(int(runtime=='off')),command)
                (work.generated/'difftest_profile.json').write_text(json.dumps(
                    dict(bundles=[] if rtl=='on' else [{}])))
                with self.assertRaises(RuntimeError):work.rtl()

    def test_functional_models_are_independent_of_difftest_and_require_matching_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            args=argparse.Namespace(output=Path(directory),compiler='/usr/bin/clang++',
                tools_dir=None,sim_primitives='none',rtl_difftest='off',runtime_difftest='off',
                sim_models='int-mul,fp-mul,vec-int-mul,vec-fp-mul',jobs=1)
            work=Baseline(args);work.run=Mock();work.generated.mkdir(parents=True)
            (work.generated/'DifftestMacros.svh').write_text('')
            (work.generated/'difftest_profile.json').write_text(json.dumps(dict(bundles=[])))
            self.model_manifest(work);work.rtl()
            command=work.run.call_args.args[0]
            sim_args=next(str(arg) for arg in command if str(arg).startswith('SIM_ARGS='))
            self.assertIn('--wolvrix-sim-models '+args.sim_models,sim_args)
            (work.generated.parent/'simulation_models.json').write_text(json.dumps(dict(mode='hardware')))
            with self.assertRaisesRegex(RuntimeError,'mode differs'):work.rtl()
            args.behavior_state_lowering='grouped'
            with self.assertRaisesRegex(ValueError,'requires commit-rat'):Baseline(args)


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
