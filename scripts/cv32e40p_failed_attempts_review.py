#!/usr/bin/env python3
"""Offline audit of frozen unsuccessful experiments; never runs an emulator or perf."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, CXX, identity, save
from cv32e40p_binary_shape import function_symbols

ARTIFACTS = ROOT / 'build/cv32e40p'
EXPERIMENTS = ('indexed-padding-final', 'shared-deferred-activation-v1', 'local-decode-v2',
               'shared-regions-v3', 'predicate-set-v1', 'slice-demand-v1',
               'event-regions-v2', 'event-regions-v3', 'conditional-mux-v3', 'conditional-mux-v4')


def read(path):
    return json.loads(path.read_text())


def frozen_experiments():
    records = {}
    for name in EXPERIMENTS:
        root = ARTIFACTS / name
        manifest = read(root / 'build.json')
        binaries = manifest.get('binaries')
        if binaries is None:
            binaries = {key: manifest[key] for key in ('baseline_binary', 'candidate_binary')}
        shapes = {}
        for backend, binary in binaries.items():
            if identity(binary['path']) != binary:
                raise ValueError('frozen binary changed: ' + binary['path'])
            if 'verilator' in backend: continue
            symbols = function_symbols(Path(binary['path']))
            helpers = [x for x in symbols if x['symbol'].startswith('GrhSIM_Cv32Bench::eval')
                       and 'operator()' in x['symbol']]
            shapes[backend] = dict(binary=binary, lambda_symbols=helpers,
                                   lambda_bytes=sum(x['bytes'] for x in helpers))
        summary = read(root / 'summary.json')
        if 'wall_s' not in summary: summary = summary[manifest['backend_pair'][0]]
        records[name] = dict(build=identity(root / 'build.json'), summary=identity(root / 'summary.json'),
            ratio_definition=summary['ratio_definition'], wall=summary['wall_s'], binary_shapes=shapes)
    return records


def aligned_slice_proof(out):
    path = ARTIFACTS / 'slice-demand-v1/control.json'
    graph = read(path)['graphs'][0]
    values = {x['sym']: x for x in graph['vals']}
    definitions = {v: op for op in graph['ops'] for v in op['out']}
    def expect(value, kind, args):
        op = definitions[value]
        if op['kind'] != kind or op['in'] != args:
            raise ValueError('aligned-shift proof shape changed: ' + value)
    expect('_val_8718', 'kConcat', ['_val_8716', '_val_15', '_val_5203'])
    expect('_val_8719', 'kAssign', ['_val_8718'])
    expect('_val_8720', 'kSub', ['_val_8715', '_val_8719'])
    expect('_val_12829', 'kConcat', ['_val_8720'])
    expect('_val_12830', 'kAssign', ['_val_12829'])
    expect('_val_12836', 'kSub', ['_val_12834', '_val_12829'])
    expect('_val_12832', 'kLt', ['_val_12830', '_val_8715'])
    expect('_val_5746', 'kAnd', ['_val_451', '_val_8'])
    expect('_val_5804', 'kOr', ['_val_5746', '_val_11'])
    assert values['_val_15']['w'] == 5 and not values['_val_15']['sgn']
    assert values['_val_8405']['w'] == 32 and not values['_val_8405']['sgn']
    assert all(values[x]['w'] == 33 for x in ('_val_8718', '_val_8719', '_val_8720', '_val_12829', '_val_12830', '_val_12836'))
    assert values['_val_12830']['sgn'] and values['_val_8715']['sgn']

    def literal(text):
        if "'" not in text: return int(text)
        match = re.fullmatch(r"\d+'([bhd])([0-9a-fA-F_]+)", text)
        if not match: raise ValueError(text)
        return int(match[2].replace('_', ''), {'b': 2, 'h': 16, 'd': 10}[match[1]])

    def evaluate(root, index, data):
        cache = {'_val_15': index, '_val_8405': data}
        def signed(value, bits):
            info = values[value]
            return bits - (1 << info['w']) if info['sgn'] and bits >> (info['w'] - 1) else bits
        def visit(value):
            if value in cache: return cache[value]
            info, op = values[value], definitions[value]
            width = info['w']; args = op['in']; attrs = {k: v['v'] for k, v in op.get('attrs', {}).items()}
            kind = op['kind']
            if kind == 'kConstant': result = literal(attrs['constValue'])
            elif kind == 'kAssign': result = signed(args[0], visit(args[0]))
            elif kind == 'kConcat':
                result = 0
                for arg in args: result = (result << values[arg]['w']) | visit(arg)
            elif kind == 'kSub': result = signed(args[0], visit(args[0])) - signed(args[1], visit(args[1]))
            elif kind == 'kLt': result = int(signed(args[0], visit(args[0])) < signed(args[1], visit(args[1])))
            elif kind == 'kMux': result = visit(args[1] if visit(args[0]) else args[2])
            elif kind in ('kShl', 'kLShr'):
                amount = visit(args[1]); payload = visit(args[0])
                result = 0 if amount >= width else payload << amount if kind == 'kShl' else payload >> amount
            elif kind == 'kNot': result = ~visit(args[0])
            elif kind == 'kSliceStatic': result = visit(args[0]) >> attrs['sliceStart']
            else: raise ValueError('unexpected operation in proof: ' + kind)
            cache[value] = result & ((1 << width) - 1)
            return cache[value]
        return visit(root)

    for zero in ('_val_8716', '_val_5203', '_val_8715', '_val_12834'):
        assert evaluate(zero, 0, 0) == 0
    assert values['_val_8716']['w'] == 23 and values['_val_5203']['w'] == 5
    rows = []
    payloads = [0, 0xffffffff, 0xaaaaaaaa, 0x55555555, *[1 << bit for bit in range(32)]]
    for index in range(32):
        for data in payloads:
            mask16 = evaluate('_val_8', index, data)
            data16 = evaluate('_val_11', index, data)
            assert mask16 == (0 if index == 3 else 0xffff)
            assert data16 == (data & 0xffff if index == 3 else 0)
            # Check the downstream masked update at zero/ones/basis old words.
            for old in (0, 0xffff, *[1 << bit for bit in range(16)]):
                assert ((old & mask16) | data16) == (data & 0xffff if index == 3 else old)
        rows.append(dict(index=index, payload_cases=len(payloads), mask16=evaluate('_val_8', index, 0)))
    result = dict(graph=identity(path), index='_val_15: unsigned 5 bits', payload='_val_8405: unsigned 32 bits',
        original='bit[111:96] of a signed-direction shift of zero-extended payload/mask; displacement = 32 * index',
        exact_two_state_identity=dict(mask16='index == 3 ? 0 : 0xffff', data16='index == 3 ? low16(payload) : 0',
                                      update='_val_5804 = index == 3 ? low16(payload) : old16 (_val_451)'),
        proof='All 32 legal indices, zero/ones/alternating/32 basis payloads, and 18 old-state vectors checked against the original IR. For fixed index the data root is a logical shift/slice, hence bit-linear.',
        cases=rows, exclusions='Does not apply to arbitrary bit displacements, unknown bits, or unproved index alignment. No transformed model or performance run.')
    save(out / 'aligned-slice-proof.json', result)
    return result


def byte_boolean_probe(out):
    # Two identical consumption patterns; only the stored 0/1 contract differs.
    src = out / 'byte-bool-probe.cpp'
    indices = [1968, 1954, 1953, 800, 1971, 1970, 832, 773]
    code = '#include <cstdint>\n#include <cstdlib>\n'
    for kind, typ in (('byte', 'std::uint8_t'), ('boolean', 'bool')):
        code += f'extern "C" __attribute__((noinline)) unsigned {kind}_read(const {typ} *p) {{ return p[1968] != 0; }}\n'
        terms = [f'(unsigned(p[{index}] != 0) << {bit})' for bit, index in enumerate(indices)]
        code += f'extern "C" __attribute__((noinline)) unsigned {kind}_pack(const {typ} *p) {{ return ' + ' | '.join(terms) + '; }\n'
    code += 'int main() { std::uint8_t bytes[4096]{}; bool booleans[4096]{};\n'
    code += 'for (unsigned pattern=0;pattern<256;++pattern) {\n'
    for bit, index in enumerate(indices): code += f'bytes[{index}]=booleans[{index}]=bool((pattern >> {bit}) & 1);\n'
    code += ('if (byte_pack(bytes)!=pattern || boolean_pack(booleans)!=pattern || '
             'byte_read(bytes)!=boolean_read(booleans)) return 1; } }\n')
    src.write_text(code)
    commands = []
    for flags, destination in ((['-S', '-masm=att'], out / 'byte-bool-probe.s'),
                               (['-S', '-emit-llvm'], out / 'byte-bool-probe.ll'), ([], out / 'byte-bool-probe')):
        cmd = [str(CXX), '-std=c++20', '-O3', '-march=x86-64', *flags, str(src), '-o', str(destination)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        commands.append(cmd)
    subprocess.run([str(out / 'byte-bool-probe')], check=True)
    asm = (out / 'byte-bool-probe.s').read_text()
    functions = {}
    for name in ('byte_read', 'boolean_read', 'byte_pack', 'boolean_pack'):
        body = re.search(r'^' + name + r':.*?(?=^\.Lfunc_end)', asm, re.M | re.S)[0]
        insns = [line.strip() for line in body.splitlines() if re.match(r'^\t[a-z][a-z0-9]+(?:\s|$)', line)]
        functions[name] = dict(instructions=insns, count=len(insns), normalize=sum(x.startswith(('cmp', 'setne', 'test')) for x in insns))
    result = dict(source=identity(src), compiler=identity(CXX), commands=commands, functions=functions,
        oracle_patterns=256, scope='Static x86-64 contract probe only; not a model benchmark or prediction of the full-model gain.')
    save(out / 'byte-bool-probe.json', result)
    return result


def local_table_machine_code(out):
    model = ARTIFACTS / 'local-decode-v2/grhsim_local_decode'
    source = model / 'grhsim_Cv32Bench_sched_3.cpp'
    selected = [i for i, line in enumerate(source.read_text().splitlines(), 1)
                if re.search(r'const bool grhsim_v\w+ = local_equality_table_1_', line)][:4]
    symbol = next(s for s in function_symbols(model / 'emu')
                  if s['symbol'] == 'GrhSIM_Cv32Bench::eval_compute_batch_3()')
    cmd = [str(CXX.parent / 'llvm-objdump'), '-d', '--demangle', '--line-numbers', '--no-show-raw-insn',
           '--start-address=' + str(symbol['address']), '--stop-address=' + str(symbol['address'] + symbol['bytes']),
           str(model / 'emu')]
    asm = subprocess.check_output(cmd, text=True)
    (out / 'local-decode-batch3-lines.s').write_text(asm)
    excerpts = []; lines = asm.splitlines()
    for i, line in enumerate(lines):
        match = re.search(r'grhsim_Cv32Bench_sched_3.cpp:(\d+)\b', line)
        if match and int(match[1]) in selected: excerpts.append('\n'.join(lines[i:i + 8]))
    text = '\n\n'.join(excerpts) + '\n'
    assert 'testb' in text and 'setne' in text and 'movzbl' in text
    (out / 'local-table-load-examples.txt').write_text(text)
    return dict(binary=identity(model / 'emu'), source=identity(source), source_lines=selected, command=cmd,
                assembly=identity(out / 'local-decode-batch3-lines.s'), excerpts=identity(out / 'local-table-load-examples.txt'))


def shared_region_order():
    path = ARTIFACTS / 'shared-regions-v3/logs/emit.log'
    line = next(x for x in path.read_text().splitlines() if ' shared event-regions:' in x)
    before = int(re.search(r'local_value_live_steps_before=(\d+)', line)[1])
    after = int(re.search(r'local_value_live_steps_after=(\d+)', line)[1])
    assert after > before
    return dict(log=identity(path), before=before, after=after, increase_percent=100 * (after / before - 1),
        meaning='These compare topo order vs first-use order inside the same newly merged regions, not baseline vs candidate models.',
        adoption='orderEventRegionByUse records both metrics then unconditionally assigns ordered = std::move(byUse).',
        limitation='IR live-step sum is not a physical register-pressure or dynamic spill measurement.')


def review(out):
    out.mkdir(parents=True, exist_ok=True)
    experiments = frozen_experiments()
    local = ARTIFACTS / 'local-decode-v2/grhsim_local_decode'
    source = '\n'.join(x.read_text() for x in local.glob('*_sched_*.cpp'))
    table_reads = Counter(re.findall(r'local_equality_table_(\d+)_\[\d+u\] != UINT8_C\(0\)', source))
    slices = aligned_slice_proof(out)
    probe = byte_boolean_probe(out)
    result = dict(scope='Read-only frozen-model review plus isolated semantic/static-code probes. No emulator, model compilation, perf, or parameter search.',
        driver=identity(Path(__file__).resolve()), experiments=experiments,
        local_decode=dict(byte_table_normalization_sites=dict(table_reads),
            header=identity(local / 'grhsim_Cv32Bench.hpp'), probe=identity(out / 'byte-bool-probe.json'),
            actual_machine_code=local_table_machine_code(out)),
        shared_order=shared_region_order(),
        aligned_slice=identity(out / 'aligned-slice-proof.json'),
        evidence={name: identity(ARTIFACTS / name) for name in (
            'local-decode-v2/diagnostics.json', 'shared-regions-v3/work-decomposition.json',
            'predicate-set-v1/cache-interaction.json', 'predicate-set-v1/attribution.json',
            'slice-demand-v1/schedule-interaction.json', 'slice-demand-v1/attribution.json')},
        current_sources=[identity(ROOT / p) for p in ('wolvrix/lib/emit/grhsim_cpp.cpp',
            'wolvrix/lib/transform/activity_schedule.cpp', 'wolvrix/lib/transform/predicate_set.cpp',
            'wolvrix/lib/transform/slice_demand.cpp')])
    save(out / 'review.json', result)
    print(json.dumps(dict(experiments={k: dict(ratio=v['wall']['ratio_mean'], ci=v['wall']['ratio_ci95'],
        helpers={b:len(s['lambda_symbols']) for b,s in v['binary_shapes'].items()}) for k,v in experiments.items()},
        normalization_sites=dict(table_reads), probe={k:dict(count=v['count'], normalize=v['normalize']) for k,v in probe['functions'].items()},
        aligned_slice=slices['exact_two_state_identity']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    review(args.output.resolve())
