#!/usr/bin/env python3
"""Fresh Chisel -> native single-model GrhSIM -> pinned emu baseline.

This uses wolvrix_xs_grhsim.py, never the Repcut pipeline. The source tree is
shared, while all generated artifacts and tool builds belong to --output.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import statistics
import subprocess
import sys
import threading
import time

from grhsim_numa import inspect_locality, locality_errors, runtime_plan

ROOT = Path(__file__).resolve().parents[1]
XS = ROOT / 'testcase/xiangshan'


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def identity(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def cpus(text):
    result = set()
    for item in text.strip().split(','):
        bounds = [int(x) for x in item.split('-')]
        result.update(range(bounds[0], bounds[-1] + 1))
    return result


def clean_environment():
    prefixes = ('WOLVRIX_', 'WOLVI_', 'XS_', 'EMU_', 'REPCUT_', 'PGO_', 'BOLT_', 'MILL_', 'CMAKE_', 'SKBUILD_')
    remove = {'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'MAKEFLAGS', 'MFLAGS', 'CXXFLAGS', 'CFLAGS', 'LDFLAGS',
              'CONFIG', 'NUM_CORES', 'NO_DIFF', 'DISABLE_DIFFTEST',
              'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'}
    return {k: v for k, v in os.environ.items() if not k.startswith(prefixes) and k not in remove}


def cpu_counters(selected):
    result={}
    for line in Path('/proc/stat').read_text().splitlines():
        fields=line.split()
        if fields and fields[0] in {f'cpu{c}' for c in selected}:
            values=list(map(int,fields[1:9]))
            result[int(fields[0][3:])]=dict(total=sum(values),idle=values[3]+values[4])
    return result


def idle_percent(before,after):
    return {cpu:100*(after[cpu]['idle']-value['idle'])/max(1,after[cpu]['total']-value['total'])
            for cpu,value in before.items()}


def validate_difftest_modes(rtl, runtime):
    if rtl not in ('on', 'off') or runtime not in ('on', 'off'):
        raise ValueError('DiffTest modes must be on or off')
    if rtl == 'off' and runtime == 'on':
        raise ValueError('runtime DiffTest requires generated DiffTest hardware')


def parse_run(log,cycles,runtime_difftest='on',compile_difftest=None):
    if compile_difftest is None:
        compile_difftest=runtime_difftest
    log=re.sub(r'\x1b\[[0-9;]*m','',log)
    if re.search(r'ABORT|HIT BAD TRAP|mismatch|Assertion.*failed',log,re.I):
        raise ValueError('functional failure in emu log')
    patterns=dict(host_ms=r'Host time spent:\s*([\d,]+)ms',guest_cycles=r'Guest cycle spent:\s*([\d,]+)')
    result=dict(pc=None,instr_count=None,cycle_count=None,runtime_difftest=runtime_difftest)
    if runtime_difftest == 'on' or compile_difftest == 'on':
        if (('Difftest enabled' not in log and '[DIFFTEST_INIT]' not in log)
                or 'EXCEEDING CYCLE/INSTR LIMIT' not in log):
            raise ValueError('Difftest or cycle-limit completion absent')
        if runtime_difftest == 'on' and '[DIFFTEST_MODE] disabled' in log:
            raise ValueError('runtime DiffTest mode differs from request')
        if runtime_difftest == 'off' and re.search(r'The reference model is',log):
            raise ValueError('runtime DiffTest reference checking unexpectedly enabled')
        patterns.update(instr_count=r'instrCnt = (\d+), cycleCnt = \d+',
                        cycle_count=r'instrCnt = \d+, cycleCnt = (\d+)',
                        pc=r'EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-fA-F]+)')
        result['stop_reason']='cycle-limit'
        # UART bytes share stdout with periodic harness messages, sometimes
        # without a newline between them. Preserve UART across those messages.
        output=re.findall(r'The image is [^\n]*\n(.*?)Core 0: ',log,re.S)
        if len(output)!=1:
            output=re.findall(r'The first instruction of core 0 has commited\.[^\n]*\n(.*?)Core 0: ',log,re.S)
        if len(output)==1:
            value=re.sub(r'^(?:\[DIFFTEST_INIT\][^\n]*|The reference model is [^\n]*|'
                         r'The first instruction of core 0 has commited\.[^\n]*|'
                         r'Difftest enabled\.[^\n]*)\n','',output[0],flags=re.M)
            result['workload_output']=re.sub(r'\[CYCLE_LIMIT\][^\n]*\n','',value)
    elif runtime_difftest == 'off' and compile_difftest == 'off':
        marker='[DIFFTEST_MODE] disabled (CONFIG_NO_DIFFTEST): collection=off checking=off'
        if log.count(marker)!=1 or re.search(r'Difftest enabled|\[DIFFTEST_INIT\]|The reference model is',log):
            raise ValueError('runtime DiffTest not completely disabled')
        completion=re.findall(r'\[EMU_COMPLETION\] reason=(\S+) cycles=(\d+)$',log,re.M)
        if completion != [('cycle-limit',str(cycles))]:
            raise ValueError('missing/incorrect no-DiffTest cycle-limit completion')
        # This interval includes UART output and any diagnostics after loading
        # the workload. Keep it verbatim for matched no-DiffTest runs.
        output=re.findall(r'^The image is [^\n]*\n(.*?)\[EMU_COMPLETION\]',log,re.M|re.S)
        if len(output)!=1:raise ValueError('missing/ambiguous workload output interval')
        result['workload_output']=output[0]
        result['stop_reason']='cycle-limit'
    else:
        raise ValueError('runtime DiffTest mode must be on or off')
    for key,pattern in patterns.items():
        values=re.findall(pattern,log)
        if len(values)!=1:raise ValueError('missing/ambiguous runtime field: '+key)
        result[key]=values[0] if key=='pc' else int(values[0].replace(',',''))
    if result['guest_cycles']!=cycles+1:raise ValueError('unexpected number of guest cycles')
    if result['host_ms']<=0:raise ValueError('invalid Host walltime')
    return result


class Baseline:
    def __init__(self, args):
        self.args = args
        self.rtl_difftest = getattr(args, 'rtl_difftest', 'on')
        self.sim_models = getattr(args, 'sim_models', 'hardware')
        self.runtime_difftest = getattr(args, 'runtime_difftest', 'on')
        self.model_difftest = getattr(args, 'model_difftest', self.runtime_difftest)
        self.compile_difftest = getattr(args, 'compile_difftest', self.model_difftest)
        self.difftest_relax_intermediate_wires = bool(
            getattr(args, 'difftest_relax_intermediate_wires', False)
        )
        self.difftest_config = getattr(args, 'difftest_config', None)
        self.difftest_packed_delay_regs = bool(
            getattr(args, 'difftest_packed_delay_regs', False)
        )
        # Decode-table mode has two independent backend pieces: the source-side
        # table intrinsic (including the CSR tables) and the backend proof that
        # a table has a constant result.  Keep the latter explicit so historical
        # ablations can disable it without changing the mode name.  New
        # decode-table builds enable it by default.
        requested_fold = getattr(args, 'constant_decode_fold', None)
        if requested_fold is None:
            requested_fold = self.args.sim_primitives == 'decode-table'
        self.constant_decode_fold = bool(requested_fold)
        validate_difftest_modes(self.rtl_difftest, self.runtime_difftest)
        if self.sim_models not in ('hardware', 'commit-rat'):
            raise ValueError('simulation model mode must be hardware or commit-rat')
        if self.model_difftest not in ('on', 'off'):
            raise ValueError('model DiffTest mode must be on or off')
        if self.model_difftest == 'on' and self.rtl_difftest == 'off':
            raise ValueError('model DiffTest requires generated DiffTest hardware')
        if self.compile_difftest not in ('on', 'off'):
            raise ValueError('compile DiffTest mode must be on or off')
        if self.compile_difftest == 'off' and self.model_difftest == 'on':
            raise ValueError('compile DiffTest support is required by the model')
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.env = clean_environment()
        self.env.update(LC_ALL='C', WOLF_ENV_SOURCED='1', NOOP_HOME=str(XS))
        # Preserve clang++ argv[0]; resolving its symlink to clang selects the C
        # linker driver and omits the C++ standard library at the final link.
        self.cxx = str(Path(args.compiler).absolute())
        self.cc = str(Path(self.cxx).with_name('clang'))
        self.ar = str(Path(self.cxx).with_name('llvm-ar'))
        self.model = self.out / 'model'
        self.generated = self.out / 'chisel-home/build/generated-src'
        self.tools = args.tools_dir.resolve() if args.tools_dir else self.out / 'tools'

    def stage(self, name):
        record = dict(stage=name, time=time.time(), host=platform.node(), pid=os.getpid())
        save(self.out / 'progress.json', record)
        with (self.out / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        print('[single-baseline]', name, flush=True)

    def run(self, command, name, env=None, cwd=ROOT):
        command = list(map(str, command))
        log = self.out / 'logs' / (name + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        save(log.with_suffix('.command.json'), dict(command=command, cwd=str(cwd)))
        start = time.monotonic()
        with log.open('w') as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env or self.env, stdout=stream, stderr=subprocess.STDOUT)
            save(log.with_suffix('.process.json'), dict(pid=process.pid, start=time.time()))
            code = process.wait()
        save(log.with_suffix('.result.json'), dict(returncode=code, elapsed_s=time.monotonic()-start))
        if code:
            raise RuntimeError(f'{name} failed ({code}); see {log}')

    def snapshot(self):
        self.stage('freeze source/configuration identity')
        names=[]
        for base in ['testcase/xiangshan','wolvrix/lib','wolvrix/include','wolvrix/app/pybind','scripts']:
            for folder,dirs,files in os.walk(ROOT/base):
                dirs[:]=[n for n in dirs if n not in ('out','build','target','.git','__pycache__')]
                names += [str((Path(folder)/n).relative_to(ROOT)) for n in files
                          if Path(n).suffix in ('.scala','.mill','.cpp','.hpp','.py')]
        names += ['Makefile', 'wolvrix/CMakeLists.txt', 'testcase/xiangshan/Makefile',
                  'testcase/xiangshan/difftest/Makefile', 'testcase/xiangshan/difftest/grhsim.mk',
                  'testcase/xiangshan/difftest/emu.mk']
        save(self.out / 'sources.json', [identity(ROOT / n) for n in sorted(set(names))])
        for name, path in [('root',ROOT),('wolvrix',ROOT/'wolvrix'),('xiangshan',XS),('difftest',XS/'difftest')]:
            folder=self.out/'source_identity'/name;folder.mkdir(parents=True,exist_ok=True)
            for file, command in [('head.txt',['rev-parse','HEAD']),('status.txt',['status','--short']),
                                  ('diff.patch',['diff','--binary','HEAD']),('submodules.txt',['submodule','status','--recursive'])]:
                (folder/file).write_bytes(subprocess.check_output(['git','-C',str(path),*command]))
        paths=['build.mill','mill-version','out/xiangshan/scalaCompilerClasspath.json',
               'out/xiangshan/scalacPluginClasspath.json','out/xiangshan/test/runClasspath.json']
        records=[]
        for name in paths:
            path=XS/name
            if path.is_file():records.append(identity(path))
        save(self.out/'scala_inputs.json',records)
        configuration=dict(flow='native-single-model',host=platform.node(),runtime_cpu=self.args.cpu,
            compile_cpus=sorted(os.sched_getaffinity(0)),jobs=self.args.jobs,cycles=self.args.cycles,
            repeats=self.args.repeats,config='TLConfig',guest_cores=1,sim_primitives=self.args.sim_primitives,compiler=identity(self.cxx),
            sim_models=self.sim_models,
            rtl_difftest=self.rtl_difftest,model_difftest=self.model_difftest,
            compile_difftest=self.compile_difftest,
            runtime_difftest=self.runtime_difftest,
            difftest_relax_intermediate_wires=self.difftest_relax_intermediate_wires,
            difftest_config=self.difftest_config,
            difftest_packed_delay_regs=self.difftest_packed_delay_regs,
            constant_decode_fold=self.constant_decode_fold,
            model_flags='-std=c++20 -O3 -march=native',harness_flags='-O3',pgo=False,bolt=False,
            diagnostic_instrumentation=False,source_driver=identity(__file__),python=sys.executable,
            image=identity(XS/'ready-to-run/coremark-2-iteration.bin'),
            nemu=identity(XS/'ready-to-run/riscv64-nemu-interpreter-so') if self.runtime_difftest=='on' else None)
        save(self.out/'configuration.json',configuration)

    def build_tools(self):
        if self.args.tools_dir:
            self.run(['cmake','--build',self.tools,'--target','wolvrix_python','-j',self.args.jobs], 'tools-build')
            return
        self.run(['cmake','-S',ROOT/'wolvrix','-B',self.tools,'-G','Unix Makefiles','-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=/usr/bin/gcc','-DCMAKE_CXX_COMPILER=/usr/bin/g++',
            '-DWOLVRIX_ENABLE_MT_KAHYPAR=OFF','-DSKBUILD_PLATLIB_DIR=.', '-DSKBUILD_PURELIB_DIR=.',
            f'-DPython_EXECUTABLE={sys.executable}'], 'tools-configure')
        self.run(['cmake','--build',self.tools,'--target','wolvrix_python','-j',self.args.jobs], 'tools-build')

    def rtl(self):
        env=dict(self.env,NOOP_HOME=str(self.out/'chisel-home'))
        sim_args = ['--wolvrix-sim-primitives', self.args.sim_primitives]
        sim_args.extend(['--wolvrix-sim-models', self.sim_models])
        if self.difftest_relax_intermediate_wires:
            sim_args.append('--difftest-relax-intermediate-wires')
        if self.difftest_config:
            sim_args.extend(['--difftest-config', self.difftest_config])
        if self.difftest_packed_delay_regs:
            sim_args.append('--difftest-packed-delay-regs')
        self.run(['make','-C',XS,'sim-verilog',f'BUILD_DIR={self.out / "rtl"}',
            'CONFIG=TLConfig','NUM_CORES=1','RTL_SUFFIX=sv','WITH_CHISELDB=0','WITH_CONSTANTIN=0',
            'DISABLE_DIFFTEST='+str(int(self.rtl_difftest=='off')),
            'SIM_ARGS='+' '.join(sim_args)], 'rtl',env)
        if not (self.generated/'DifftestMacros.svh').is_file():
            raise RuntimeError('fresh Difftest generated sources absent')
        model_manifest = self.out/'chisel-home/build/simulation_models.json'
        if not model_manifest.is_file():
            raise RuntimeError('fresh simulation model manifest absent')
        model_report = json.loads(model_manifest.read_text())
        if model_report.get('mode') != self.sim_models:
            raise RuntimeError('generated simulation model mode differs from requested mode')
        save(self.out/'simulation_models_manifest.json', identity(model_manifest))
        profile=json.loads((self.generated/'difftest_profile.json').read_text())
        if bool(profile['bundles']) != (self.rtl_difftest=='on'):
            raise RuntimeError('generated DiffTest interfaces differ from requested mode')
        files=sorted((self.out/'rtl/rtl').rglob('*.sv'))+sorted((self.out/'rtl/rtl').rglob('*.v'))
        save(self.out/'rtl_manifest.json',[identity(p) for p in files])
        save(self.out/'difftest_generated_manifest.json',[identity(p) for p in sorted(self.generated.rglob('*')) if p.is_file()])

    def emit(self):
        self.stage('native full-model frontend, transforms, activity schedule and C++ emission')
        rtl=self.out/'rtl/rtl';common=XS/'difftest/src/test/vsrc/common'
        files=sorted({p.resolve() for base in (rtl,common) for p in base.rglob('*') if p.suffix in ('.sv','.v')})
        (self.out/'input.f').write_text(''.join(str(p)+'\n' for p in files))
        save(self.out/'input_manifest.json',[identity(p) for p in files])
        defines='-D DIFFTEST\n' if self.model_difftest=='on' else ''
        (self.out/'read_args.txt').write_text(f'-I {rtl}\n-I {self.generated}\n-I {common}\n'+defines)
        env=dict(self.env,PYTHONPATH=str(self.tools/'python'),LD_LIBRARY_PATH=str(self.tools),
            WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON='0',WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='0',
            WOLVRIX_XS_GRHSIM_POST_STATS_JSON=str(self.out/'post_stats.json'),
            WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(self.out/'pre_reg_to_mem.json'),
            WOLVRIX_SIMULATION_MODELS_MANIFEST=str(self.out/'chisel-home/build/simulation_models.json'))
        # The C++ pass consumes this as a generation-time option.  Prefer the
        # explicit configuration, while accepting the old research variable
        # when a diagnostic driver deliberately set it on the runner.
        if 'WOLVRIX_FOLD_CONSTANT_DECODE' in self.env:
            fold_constant_decode = self.env['WOLVRIX_FOLD_CONSTANT_DECODE']
        elif 'WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE' in self.env:
            fold_constant_decode = self.env['WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE']
        else:
            fold_constant_decode = str(int(self.constant_decode_fold))
        env['WOLVRIX_FOLD_CONSTANT_DECODE'] = fold_constant_decode
        save(self.out/'generation_environment.json',{k:v for k,v in env.items() if k.startswith(('WOLVRIX','PYTHON','LD_LIBRARY'))})
        self.run([sys.executable,'-c','import wolvrix; print(wolvrix.__file__)'],'python-binding',env)
        self.run([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',self.out/'input.f','SimTop',self.model,
                  self.out/'graph.json',self.out/'read_args.txt','info','--waveform','off','--perf','off'],'emit',env)
        if list(self.model.glob('*repcut*')) or list(self.model.glob('*Gpart*')):
            raise RuntimeError('unexpected partitioned package in native flow')
        save(self.out/'model_manifest.json',[identity(p) for p in sorted(self.model.glob('*')) if p.is_file()])

    def compile(self):
        self.stage('compile native GrhSIM model and Difftest emu')
        self.run(['make','-C',XS/'difftest','emu','-j',self.args.jobs,f'BUILD_DIR={self.out/"emu"}',
            f'GEN_CSRC_DIR={self.generated}',f'GEN_VSRC_DIR={self.generated}',f'GRHSIM_MODEL_DIR={self.model}',
            'GRHSIM=1','NUM_CORES=1','EMU_THREADS=0','EMU_RANDOMIZE=0','WITH_CHISELDB=0','WITH_CONSTANTIN=0',
            'NO_DIFF='+str(int(self.compile_difftest=='off')),
            'WOLVRIX_GRHSIM_WAVEFORM=0','WOLVRIX_GRHSIM_PERF=0','EMU_OPTIMIZE=-O3','PGO_BOLT=0',
            f'GRHSIM_MODEL_BUILD_JOBS={self.args.jobs}',f'VM_BUILD_JOBS={self.args.jobs}',
            f'CXX={self.cxx}',f'CC={self.cc}',f'AR={self.ar}','GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native'], 'compile')
        binary=self.out/'emu/grhsim-compile/emu'
        self.run(['nm','-S','--size-sort','--demangle',binary],'symbols')
        self.run(['ldd',binary],'ldd')
        save(self.out/'binary.json',identity(binary))

    def build(self):
        if (self.out/'binary.json').exists():
            raise ValueError('output already built; use measure to reuse frozen binary')
        if not (self.out/'sources.json').exists():self.snapshot()
        self.stage('fresh Chisel elaboration and isolated native Python-binding build')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.rtl),pool.submit(self.build_tools)]
            for future in futures:future.result()
        self.emit()
        self.compile()
        self.stage('build complete')

    def prepare_measurement(self):
        self.stage('measure native single-thread emu on CPU '+str(self.args.cpu))
        if self.args.binary:
            binary=self.args.binary.resolve()
            frozen=identity(binary)
            settings=dict(image=identity(self.args.image),
                          nemu=identity(self.args.nemu) if self.runtime_difftest=='on' else None)
        else:
            binary=self.out/'emu/grhsim-compile/emu'
            frozen=json.loads((self.out/'binary.json').read_text())
            if identity(binary)!=frozen:raise ValueError('baseline binary changed')
            settings=json.loads((self.out/'configuration.json').read_text())
            if settings.get('runtime_difftest','on')!=self.runtime_difftest:
                raise ValueError('runtime DiffTest mode differs from frozen build')
        original_binary=frozen
        for key in ('image','nemu'):
            if settings[key] is None:continue
            if identity(settings[key]['path'])!=settings[key]:raise ValueError('baseline input changed: '+key)
        symbols=subprocess.check_output(['nm','--demangle',str(binary)],text=True)
        if 'GrhSIM_SimTop::eval()' not in symbols or 'GrhSIM_Gpart_' in symbols:
            raise ValueError('measurement requires the native single-model GrhSIM binary')
        if self.compile_difftest=='off' and re.search(r'\b(?:v_difftest_|difftest_init\(|difftest_nstep\()',symbols):
            raise ValueError('no-DiffTest binary still contains collection/checking code')
        cpu=self.args.cpu
        if cpu!=96:raise ValueError('user requested CPU96 for walltime')
        siblings=cpus(Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list').read_text())
        nodes=[int(p.parent.name[4:]) for p in Path('/sys/devices/system/node').glob('node[0-9]*/cpulist') if cpu in cpus(p.read_text())]
        if len(nodes)!=1:raise ValueError('cannot determine CPU96 NUMA node')
        monitor=next(c for c in sorted(os.sched_getaffinity(0)) if c not in siblings)
        os.sched_setaffinity(0,{monitor})
        runtime=dict(self.env,EMU_PHASE_TIMING='0',EMU_PROGRESS_EVERY_CYCLES='0')
        directory=self.out/'runs'
        directory.mkdir(exist_ok=False)
        reference=settings['nemu']['path'] if self.runtime_difftest=='on' else None
        plan=runtime_plan(binary,reference,settings['image']['path'],
                          directory/'runtime',cpu,nodes[0],runtime)
        save(directory/'runtime_plan.json',plan)
        self.run(['taskset','-c',str(cpu),'numactl',f'--membind={nodes[0]}',sys.executable,
                  ROOT/'scripts/grhsim_numa.py',directory/'runtime_plan.json'], 'runtime-prefault',runtime)
        plan=json.loads((directory/'runtime/manifest.json').read_text())
        binary=directory/'runtime/bin/emu'
        frozen=identity(binary)
        if frozen['sha256']!=original_binary['sha256']:raise ValueError('staged binary differs')
        runtime['LD_LIBRARY_PATH']=str(directory/'runtime/lib')
        save(directory/'input_identity.json',dict(binary=original_binary,image=settings['image'],nemu=settings['nemu']))
        save(directory/'environment.json',dict(host=platform.node(),cpu=cpu,monitor_cpu=monitor,
            siblings=sorted(siblings),numa_node=nodes[0],aslr='disabled',code_pages='native loader; no remapping/preload',
            transparent_hugepage=Path('/sys/kernel/mm/transparent_hugepage/enabled').read_text().strip(),
            binary=frozen,original_binary=original_binary,driver=identity(__file__),
            locality_helper=identity(ROOT/'scripts/grhsim_numa.py'),runtime_manifest=identity(directory/'runtime/manifest.json'),
            library_path=runtime['LD_LIBRARY_PATH'],
            locality_poll_seconds=5,system_loader=plan['interpreter'],
            cycles=self.args.cycles,repeats=self.args.repeats))
        diff_args=['--diff',str(directory/'runtime/ref/nemu.so')] if self.runtime_difftest=='on' else ['--no-diff']
        base=['taskset','-c',str(cpu),'numactl',f'--membind={nodes[0]}','setarch',platform.machine(),'-R',str(binary),
              '-i',str(directory/'runtime/image/workload.bin'),*diff_args,
              '-b','0','-e','0','-s','0']
        self.run(['taskset','-c',str(cpu),'numactl',f'--membind={nodes[0]}','setarch',platform.machine(),'-R','true'],'runtime-placement-check')
        return dict(directory=directory, binary=binary, frozen=frozen, original_binary=original_binary, cpu=cpu, nodes=nodes, siblings=siblings, plan=plan, runtime=runtime, base=base)

    def run_sample(self, prepared, name, cycles, seed=0, extra_args=(), process_observer=None):
        directory=prepared['directory']
        binary=prepared['binary']
        frozen=prepared['frozen']
        original_binary=prepared['original_binary']
        cpu=prepared['cpu']
        nodes=prepared['nodes']
        siblings=prepared['siblings']
        plan=prepared['plan']
        runtime=prepared['runtime']
        base=prepared['base']
        self.stage('CPU96 runtime '+name)
        attempts=[]
        for attempt in range(60):
            before=cpu_counters(siblings);time.sleep(3);after=cpu_counters(siblings)
            idle=idle_percent(before,after);attempts.append(dict(time=time.time(),idle=idle))
            if min(idle.values())>=98:break
        else:raise RuntimeError('CPU96 or SMT sibling remains busy; placement is fixed, no fallback CPU')
        save(directory/(name+'.preflight.json'),attempts)
        base=list(base);base[-1]=str(seed)
        command=base+['-C',str(cycles),*extra_args]
        save(directory/(name+'.command.json'),command)
        start_counters=cpu_counters(siblings)
        start=time.monotonic();records=[];placement_seen=False;placement_bad=[];max_threads=0
        numa_records=[];numa_bad=[];next_numa=0.0
        numa_directory=directory/(name+'.numa');numa_directory.mkdir()
        with (directory/(name+'.log')).open('w') as stream:
            process=subprocess.Popen(command,cwd=binary.parent,env=runtime,stdout=stream,stderr=subprocess.STDOUT)
            if process_observer is not None:
                process_observer.start(process.pid, start)
            exited=threading.Event();completion={}
            def wait_for_exit():
                completion['returncode']=process.wait()
                completion['wall_s']=time.monotonic()-start
                exited.set()
            watcher=threading.Thread(target=wait_for_exit);watcher.start()
            while not exited.is_set():
                try:
                    proc=Path('/proc')/str(process.pid)
                    if (proc/'exe').resolve()==binary.resolve():
                        tasks=list((proc/'task').iterdir());max_threads=max(max_threads,len(tasks))
                        sample=dict(time=time.monotonic()-start,threads=len(tasks),tasks=[])
                        for task in tasks:
                            status=dict(line.split(':',1) for line in (task/'status').read_text().splitlines() if ':' in line)
                            affinity=status['Cpus_allowed_list'].strip()
                            stat=(task/'stat').read_text().split(') ',1)[1].split()
                            sample['tasks'].append(dict(tid=int(task.name),affinity=affinity,processor=int(stat[36]),
                                user_ticks=int(stat[11]),system_ticks=int(stat[12]),
                                voluntary_switches=int(status['voluntary_ctxt_switches']),
                                involuntary_switches=int(status['nonvoluntary_ctxt_switches'])))
                            if affinity!=str(cpu) or int(stat[36])!=cpu:placement_bad.append(sample['tasks'][-1])
                        if not placement_seen:
                            for fname in ('status','maps','smaps','numa_maps','personality'):
                                (directory/(name+'.'+fname)).write_text((proc/fname).read_text())
                            placement_seen=True
                        if sample['time']>=next_numa:
                            maps=(proc/'maps').read_text();numa=(proc/'numa_maps').read_text()
                            if self.runtime_difftest=='off' and re.search(r'nemu[^\n]*\.so',maps,re.I):
                                numa_bad.append(dict(unexpected_reference_mapping=True))
                            record=inspect_locality(maps,numa,plan)
                            record.update(time=sample['time'])
                            prefix=numa_directory/f'{len(numa_records):04d}'
                            prefix.with_suffix('.maps').write_text(maps)
                            prefix.with_suffix('.numa_maps').write_text(numa)
                            numa_records.append(record)
                            numa_bad.extend(locality_errors(record,nodes[0]))
                            next_numa=sample['time']+5
                        records.append(sample)
                except (FileNotFoundError,ProcessLookupError):pass
                exited.wait(.5 if placement_seen else .05)
            watcher.join();code=completion['returncode']
            if process_observer is not None:
                process_observer.finish()
        wall=completion['wall_s']
        save(directory/(name+'.monitor.json'),records)
        save(directory/(name+'.locality.json'),numa_records)
        seen={path for row in numa_records for path in row['seen_files']}
        # The NEMU reference is dlopen'ed by Difftest and can be unmapped before
        # the final /proc snapshot (short smoke runs commonly do this). Its
        # copied bytes are still prefaulted and its use is checked by the
        # Difftest log/trace. The native emu and private loader libraries must
        # remain mapped and local throughout the measured process.
        required={entry['destination'] for entry in plan['files'] if entry['role'] in ('binary','library')}
        if not required.issubset(seen):numa_bad.append(dict(missing_runtime_mappings=sorted(required-seen)))
        if not any(row['groups'].get('anonymous',{}).get('pages',{}).get(str(nodes[0]),0) for row in numa_records):
            numa_bad.append(dict(missing_anonymous_memory=True))
        if numa_bad:
            save(directory/(name+'.rejected.json'),dict(reason='NUMA locality',errors=numa_bad))
            raise RuntimeError(f'{name}: NUMA locality failed; raw logs retained, sample excluded')
        if code:raise RuntimeError(f'{name} emu exit {code}')
        if not placement_seen or placement_bad or max_threads!=1:
            raise RuntimeError(f'{name}: not a verified single thread on CPU96')
        result=parse_run((directory/(name+'.log')).read_text(),cycles,
                         self.runtime_difftest,self.compile_difftest)
        result.update(name=name,seed=seed,diagnostic=bool(extra_args),external_wall_s=wall,cpu=cpu,max_threads=max_threads,
                      sibling_idle=idle_percent(start_counters,cpu_counters(siblings)),binary_sha256=frozen['sha256'],
                      locality_pass=True,locality_samples=len(numa_records),numa_node=nodes[0],
                      reference_mapped=any(entry['destination'] in seen for entry in plan['files']
                                           if entry['role']=='reference'))
        if any(result['sibling_idle'][c]<98 for c in siblings if c!=cpu):
            save(directory/(name+'.rejected.json'),dict(reason='SMT sibling busy',result=result))
            raise RuntimeError(f'{name}: SMT sibling busy; sample excluded')
        if identity(binary)!=frozen:raise ValueError('binary changed while measuring')
        for entry in plan['files']:
            if identity(entry['destination'])!=entry['copy']:raise ValueError('runtime file changed while measuring')
        save(directory/(name+'.json'),result)
        print(json.dumps(result),flush=True)
        return result

    def measure(self):
        prepared=self.prepare_measurement()
        directory=prepared['directory'];frozen=prepared['frozen'];original_binary=prepared['original_binary']
        samples=[]
        for name,cycles in [('smoke',10000),('warmup',self.args.cycles)]+[(f'run{i:02d}',self.args.cycles) for i in range(1,self.args.repeats+1)]:
            result=self.run_sample(prepared,name,cycles)
            if name.startswith('run'):
                signature={k:result[k] for k in ('pc','instr_count','cycle_count','guest_cycles')}
                if samples and signature!={k:samples[0][k] for k in signature}:
                    raise RuntimeError('functional signature differs between repetitions')
                samples.append(result)
        times=[s['host_ms'] for s in samples]
        summary=dict(samples=samples,host_ms=dict(mean=statistics.mean(times),median=statistics.median(times),
            minimum=min(times),maximum=max(times),stdev=statistics.stdev(times) if len(times)>1 else 0,
            cv_percent=100*statistics.stdev(times)/statistics.mean(times) if len(times)>1 else 0),
            scope='Host time includes harness work, not pure eval',binary=frozen,original_binary=original_binary,
            numa_policy='Owned executable/reference/library pages and anonymous state must be local; system ELF loader reported separately')
        save(directory/'summary.json',summary)
        with (directory/'samples.csv').open('w') as stream:
            fields=['name','host_ms','external_wall_s','cpu','max_threads','pc','instr_count','cycle_count','guest_cycles']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(samples)
        self.stage('complete: native single-model baseline and CPU96 walltime')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','tools','rtl','emit','compile','measure','all'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--compiler',default='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
    parser.add_argument('--jobs',type=int,default=64)
    parser.add_argument('--sim-primitives',choices=['none','priority-encode','popcount','popcount-ge4','gray-decode','decode-table'],default='none')
    parser.add_argument('--sim-models',choices=['hardware','commit-rat'],default='hardware')
    parser.add_argument('--rtl-difftest',choices=['on','off'],default='on')
    parser.add_argument('--runtime-difftest',choices=['on','off'],default='on')
    parser.add_argument('--difftest-relax-intermediate-wires',action='store_true')
    parser.add_argument('--difftest-config',help='explicit DiffTest Gateway config, e.g. U or H')
    parser.add_argument('--difftest-packed-delay-regs',action='store_true')
    parser.add_argument('--tools-dir',type=Path,help='shared tool build for matched A/B generation')
    parser.add_argument('--cpu',type=int,default=96)
    parser.add_argument('--cycles',type=int,default=100000)
    parser.add_argument('--repeats',type=int,default=8)
    parser.add_argument('--binary',type=Path,help='measure an existing frozen native binary in a new output directory')
    parser.add_argument('--image',type=Path,default=XS/'ready-to-run/coremark-2-iteration.bin')
    parser.add_argument('--nemu',type=Path,default=XS/'ready-to-run/riscv64-nemu-interpreter-so')
    args=parser.parse_args()
    if args.binary and args.command!='measure':parser.error('--binary is only supported by measure')
    if args.cycles<=0 or args.repeats<=0:parser.error('cycles and repeats must be positive')
    if not platform.node().startswith('node030'):
        raise RuntimeError('this baseline must run on node030')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    work=Baseline(args)
    try:
        if args.command in ('build','all'):work.build()
        if args.command=='tools':work.build_tools()
        if args.command=='rtl':work.rtl()
        if args.command=='emit':work.emit()
        if args.command=='compile':work.compile()
        if args.command in ('measure','all'):work.measure()
    except Exception as error:
        work.stage('failed: '+str(error))
        raise


if __name__=='__main__':main()
