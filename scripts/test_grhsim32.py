"""Tests of the portable build orchestration, without a large RTL model."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import grhsim32 as flow


def arguments(output):
    return argparse.Namespace(config=flow.ROOT / 'config/grhsim32.json', output=output,
        jobs=8, runtime_cpus=','.join(map(str, range(32))), generated=output / 'generated',
        rtl=output / 'rtl', filelist=None, read_args=None, image=output / 'image',
        nemu=output / 'nemu.so', codepages='auto', performance=False, clean=False)


class CleanFlowTests(unittest.TestCase):
    def test_cpu_ranges(self):
        self.assertEqual(flow.cpu_list('2-4,9,11-12'), [2, 3, 4, 9, 11, 12])

    def test_topology_uses_actual_machine_instead_of_node030(self):
        cpus = list(range(32, 80))
        selected = flow.runtime_cpus(cpus)
        self.assertEqual(len(selected), 32)
        self.assertEqual(len(set(selected)), 32)
        self.assertTrue(set(selected) <= set(cpus))

    def test_default_recipe_does_not_contain_old_build_inputs(self):
        config = flow.read(flow.ROOT / 'config/grhsim32.json')
        self.assertEqual(config['solver_runs'], 8)
        self.assertEqual(config['partitions'], 32)
        self.assertEqual(config['options']['WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION'], '1')
        self.assertEqual(config['options']['WOLVRIX_GRHSIM_INPUT_DIRTY_TRACKING'], '1')
        text = json.dumps(config)
        self.assertNotIn('/nfs/', text)
        self.assertNotIn('build/', text)
        self.assertNotIn('assignment', config)

    def test_native_project_uses_current_sources(self):
        text = (flow.NATIVE / 'CMakeLists.txt').read_text()
        self.assertIn('add_subdirectory', text)
        self.assertIn('../../wolvrix', text)
        self.assertNotIn('replay-current', text)
        self.assertNotIn('202610', text)

    def test_default_input_regenerates_rtl_even_when_old_simtop_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'output'
            args = arguments(output)
            args.rtl = None
            pipeline = flow.Pipeline(args)
            stale = root / 'build/xs/rtl/rtl/SimTop.sv'
            stale.parent.mkdir(parents=True)
            stale.write_text('stale RTL')
            calls = []

            def command(cmd, log, **kwargs):
                calls.append(list(map(str, cmd)))
                if cmd[0] == 'make':
                    fresh = output / 'rtl/rtl/SimTop.sv'
                    fresh.parent.mkdir(parents=True)
                    fresh.write_text('fresh RTL')

            with patch.object(flow, 'ROOT', root), \
                    patch.object(pipeline, 'run_command', side_effect=command):
                pipeline.inputs()
            self.assertEqual(calls[0][0], 'make')
            self.assertIn(f'BUILD_DIR={output / "rtl"}', calls[0])
            self.assertEqual((output / 'input.f').read_text(), str(output / 'rtl/rtl/SimTop.sv') + '\n')
            self.assertEqual(stale.read_text(), 'stale RTL')

    def test_explicit_rtl_input_is_used_without_running_rtl_generator(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = arguments(output)
            args.rtl.mkdir()
            top = args.rtl / 'SimTop.sv'
            top.write_text('explicit RTL')
            pipeline = flow.Pipeline(args)
            calls = []
            with patch.object(pipeline, 'run_command',
                              side_effect=lambda cmd, *a, **kw: calls.append(list(map(str, cmd)))):
                pipeline.inputs()
            self.assertFalse(any(cmd[0] == 'make' for cmd in calls))
            self.assertIn(str(top), (output / 'input.f').read_text().splitlines())

    def test_clean_solve_runs_all_eight_seeds_and_selects_computed_minimum(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = arguments(output)
            args.performance = True
            pipeline = flow.Pipeline(args)
            pipeline.solver = Path('/solver')
            pipeline.solver_config = Path('/solver.ini')
            pipeline.cpus = list(range(32))
            calls = []

            def command(cmd, log, **kwargs):
                calls.append(list(map(str, cmd)))
                if Path(cmd[0]).name == 'grhsim32_initial_graph':
                    folder = Path(cmd[2]); folder.mkdir()
                    (folder / 'initial.hgr').write_text('0 64 11 6\n' + '1 1 1 1 1 1\n' * 64)
                elif str(cmd[0]) == 'taskset':
                    folder = Path(cmd[cmd.index('--partition-output-folder') + 1])
                    (folder / 'result.KaHyPar').write_text(''.join(f'{i % 32}\n' for i in range(64)))

            costs = '\n'.join(f'{i} {10 if i == 5 else 100 + i} 1' for i in range(8))
            with patch.object(pipeline, 'run_command', side_effect=command), \
                    patch.object(flow.subprocess, 'check_output', return_value=costs):
                selected = pipeline.solve()
            record = flow.read(output / 'selection.json')
            self.assertEqual(record['selected']['seed'], 5)
            self.assertEqual(selected.parent.name, 'seed5')
            solves = [cmd for cmd in calls if cmd[0] == 'taskset']
            self.assertEqual(sorted(int(cmd[cmd.index('--seed') + 1]) for cmd in solves), list(range(8)))
            self.assertTrue(all(str(output) in cmd[cmd.index('-h') + 1] for cmd in solves))

    def test_compile_keeps_generated_archive_order_and_enables_slp(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); pipeline = flow.Pipeline(arguments(out))
            package = out / 'initial/package'; package.mkdir(parents=True)
            (package / 'Makefile').write_text('SRCS := z.cpp a.cpp\n')
            (package / 'z.cpp').write_text(''); (package / 'a.cpp').write_text('')
            calls = []
            with patch.object(pipeline, 'run_command', side_effect=lambda cmd, *a, **kw: calls.append(list(map(str, cmd)))), \
                    patch.object(flow, 'align_object'), patch.object(pipeline, 'harness'):
                pipeline.compile(package.parent)
            commands = [cmd for cmd in calls if '-c' in cmd]
            self.assertEqual(len(commands), 2)
            self.assertTrue(all('-O3' in cmd and '-march=native' in cmd for cmd in commands))
            self.assertTrue(all('-fno-slp-vectorize' not in cmd for cmd in commands))
            members = (package.parent / 'objects.rsp').read_text().splitlines()
            self.assertTrue(members[0].endswith('/z.o"'))
            self.assertTrue(members[1].endswith('/a.o"'))

    def test_clean_cannot_delete_repository_or_build_root(self):
        for output in (flow.ROOT, flow.ROOT / 'build'):
            args = arguments(output); args.clean = True
            pipeline = flow.Pipeline(args)
            with patch.object(flow.fcntl, 'flock'), patch.object(flow.shutil, 'rmtree') as remove:
                with self.assertRaisesRegex(ValueError, 'clean output'):
                    pipeline.run()
                remove.assert_not_called()
            pipeline.lock.close()

    def test_preload_starts_at_emu_after_affinity_and_aslr_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = arguments(output)
            args.performance = True
            pipeline = flow.Pipeline(args)
            pipeline.aslr_off, pipeline.numa = True, None
            calls = []

            def command(cmd, log, env=None):
                calls.append((cmd, env))
                log.write_text('Difftest enabled\nEXCEEDING CYCLE/INSTR LIMIT\n'
                               'Host time spent: 1234ms\n[runtime-config] {"lanes":32}\n')
                log.with_suffix('.timing.jsonl').write_text('{}\n')

            with patch.object(pipeline, 'run_command', side_effect=command):
                result = pipeline.simulate(output / 'initial', output / 'runs', 'test')
            cmd, env = calls[0]
            self.assertNotIn('LD_PRELOAD', env)
            self.assertLess(cmd.index('setarch'), cmd.index('env'))
            self.assertTrue(cmd[cmd.index('env') + 1].startswith('LD_PRELOAD='))
            self.assertEqual(env['WOLVI_REPCUT_PIN_THREADS'], '1')
            self.assertEqual(result['host_s'], 1.234)

    def test_default_runtime_inherits_placement_and_skips_measurement_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            pipeline = flow.Pipeline(arguments(output))
            calls = []

            def command(cmd, log, env=None):
                calls.append((list(map(str, cmd)), env))
                log.write_text('Difftest enabled\nEXCEEDING CYCLE/INSTR LIMIT\n'
                               'Host time spent: 1234ms\n[runtime-config] {"lanes":32}\n')

            with patch.object(pipeline, 'run_command', side_effect=command):
                result = pipeline.simulate(output / 'initial', output / 'runs', 'test', cycles=100)
            cmd, env = calls[0]
            self.assertEqual(cmd[0], str(output / 'initial/harness/grhsim-compile/emu'))
            self.assertFalse(any(helper in cmd for helper in ('taskset', 'numactl', 'setarch')))
            self.assertNotIn('LD_PRELOAD', env)
            self.assertNotIn('REPCUT_CODEPAGE_MODE', env)
            self.assertNotIn('XS_REPCUT_STEP_TIMING', env)
            self.assertEqual(env['WOLVI_REPCUT_PIN_THREADS'], '0')
            self.assertEqual(result['parts'], [])

    def test_failed_automatic_candidate_keeps_functional_initial_emu(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = arguments(output)
            args.performance = True
            pipeline = flow.Pipeline(args)
            initial = output / 'initial'
            selected = {'name': 'automatic_move', 'source': 0, 'destination': 1}

            def command(cmd, log, **kwargs):
                if Path(cmd[1]).name == 'repcut_grhsim_piece_candidates.py':
                    folder = output / 'migration/proposals'
                    folder.mkdir()
                    flow.save(folder / 'selection.json', {'candidates': [selected]})
                elif Path(cmd[1]).name == 'repcut_grhsim_local_search_rank.py':
                    flow.save(output / 'migration/ranking.json', {})

            measured = [{'parts': [{'record_type': 'part_timing', 'part_name': 'part_0',
                                     'eval_avg_us': 1, 'update_push_avg_us': 1}]}]
            with patch.object(pipeline, 'trace', return_value=[output / 'new.trace']), \
                    patch.object(pipeline, 'run_command', side_effect=command), \
                    patch.object(pipeline, 'emit', side_effect=RuntimeError('candidate functional failure')), \
                    patch('repcut_grhsim_local_search_rank.select_migration', return_value=selected):
                retained = pipeline.search(initial, measured)
            self.assertEqual(retained, initial)
            result = flow.read(output / 'migration/result.json')
            self.assertFalse(result['accepted'])
            self.assertIn('candidate functional failure', result['error'])

    def test_publishing_launcher_does_not_overwrite_an_emu_symlink_target(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = arguments(output)
            args.performance = True
            pipeline = flow.Pipeline(args)
            pipeline.aslr_off, pipeline.numa = False, None
            initial = output / 'initial'
            binary = initial / 'harness/grhsim-compile/emu'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'original compiled ELF')
            (initial / 'package').mkdir()
            flow.save(initial / 'runs/summary.json', {'runs': [], 'walltime_median_s': 1})
            flow.save(output / 'selection.json', {'selected': {'seed': 3}})
            flow.save(output / 'migration/result.json', {'accepted': False})
            (output / 'emu').symlink_to(binary)
            pipeline.publish(initial)
            pipeline.publish(initial)
            self.assertEqual(binary.read_bytes(), b'original compiled ELF')
            self.assertFalse((output / 'emu').is_symlink())
            self.assertTrue((output / 'emu.bin').is_symlink())
            self.assertIn("env LD_PRELOAD=", (output / 'emu').read_text())

    @unittest.skipUnless((flow.ROOT / 'build/grhsim32-tools/libgrhsim32_codepage.so').exists(),
                         'code-page startup library has not been built')
    def test_codepage_survives_exec_helpers_and_runs_once_across_dlmopen(self):
        artifacts = flow.ROOT / 'wolvrix/build/artifacts'
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='grhsim32-codepage-', dir=artifacts) as temp:
            output = Path(temp)
            source = output / 'main.cpp'
            source.write_text('#define _GNU_SOURCE\n#include <link.h>\n#include <dlfcn.h>\n'
                '#include <cstdio>\n'
                'asm(".pushsection .text\\n.rept 6000000\\n.byte 0x90\\n.endr\\n.popsection");\n'
                'int main(int argc,char**argv){if(!dlmopen(LM_ID_NEWLM,argv[1],RTLD_NOW)){'
                'std::fputs(dlerror(),stderr);return 1;}std::puts("startup ok");}\n')
            subprocess.run([flow.compiler(), source, '-ldl', '-o', output / 'main'],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pipeline = flow.Pipeline(arguments(output))
            library = pipeline.build / 'libgrhsim32_codepage.so'
            env = dict(pipeline.env, LD_PRELOAD=str(library), REPCUT_CODEPAGE_MODE='auto')
            result = subprocess.run(['taskset', '-c', str(min(os.sched_getaffinity(0))), output / 'main', library],
                                    env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertIn('startup ok', result.stdout)
            self.assertEqual(result.stderr.count('[codepage] PASS'), 1)
            self.assertNotIn('bytes=0 ', result.stderr)

    def test_make_entry_needs_no_environment_script_or_manual_flags(self):
        completed = subprocess.run(['make', '--no-print-directory', '-n', 'xs_wolf_grhsim_repcut_emu',
                                    'WOLF_ENV_SOURCED=', 'ENV_FILE=/absent'], cwd=flow.ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('grhsim32.py', completed.stdout)
        self.assertIn('--clean', completed.stdout)
        self.assertNotIn('XS_REPCUT_INITIAL_ASSIGNMENT=', completed.stdout)

    def test_make_entry_exposes_the_same_pipeline_in_explicit_performance_mode(self):
        completed = subprocess.run(['make', '--no-print-directory', '-n', 'xs_wolf_grhsim_repcut_perf_emu',
                                    'WOLF_ENV_SOURCED=', 'ENV_FILE=/absent'], cwd=flow.ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('grhsim32.py', completed.stdout)
        self.assertIn('--clean --performance', completed.stdout)
        self.assertIn('grhsim32-perf', completed.stdout)

    @unittest.skipUnless((flow.ROOT / 'build/grhsim32-tools/bin/grhsim32_frontend').exists()
                         and (flow.ROOT / 'build/grhsim32-deps/solver-build-host/mt-kahypar/application/MtKaHyPar').exists(),
                         'native tools and solver have not been built')
    def test_verilog_to_eight_feasible_assignments_with_zero_weight_dimensions(self):
        artifacts = flow.ROOT / 'wolvrix/build/artifacts'
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='grhsim32-', dir=artifacts) as temp:
            output = Path(temp)
            rtl = output / 'top.sv'
            ports = ['input bit clock, reset', 'input bit [7:0] data']
            ports += [f'output bit [7:0] q{i}' for i in range(64)]
            logic = [f'always_ff @(posedge clock) if (reset) q{i} <= 0; else q{i} <= q{i} + data + 8\'d{i};'
                     for i in range(64)]
            rtl.write_text('module SimTop(' + ', '.join(ports) + ');\n' + '\n'.join(logic) + '\nendmodule\n')
            subprocess.run([flow.ROOT / 'build/grhsim32-tools/bin/grhsim32_frontend',
                            output / 'memory.json', 'SimTop', rtl], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pipeline = flow.Pipeline(arguments(output))
            pipeline.cpus = sorted(os.sched_getaffinity(0))[:8]
            pipeline.solver = flow.ROOT / 'build/grhsim32-deps/solver-build-host/mt-kahypar/application/MtKaHyPar'
            pipeline.solver_config = flow.ROOT / 'build/grhsim32-deps/mt-kahypar/config/default_preset.ini'
            selected = pipeline.solve()
            result = flow.read(output / 'selection.json')
            self.assertEqual(len(result['attempts']), 8)
            self.assertTrue(all(item['status'] == 'pass' and item['capacity_feasible']
                                for item in result['attempts']))
            self.assertEqual(result['selected']['km1'], min(item['km1'] for item in result['attempts']))
            self.assertEqual(len(selected.read_text().split()), 128)


if __name__ == '__main__':
    unittest.main()
