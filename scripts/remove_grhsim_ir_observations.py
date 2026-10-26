#!/usr/bin/env python3
"""Instrument copies of frozen generated fixtures; invoke through Make targets."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "dpi_smoke": ("dpi_smoke", {"clk": 1, "a": 8, "d": 8}, {"o": 8, "o2": 8}, {"q": 8, "q2": 8}),
    "dpi_smoke_tu": ("dpi_smoke", {"clk": 1, "a": 8, "d": 8}, {"o": 8, "o2": 8}, {"q": 8, "q2": 8}),
    "dpi_bit_abi": ("dpi_bit_abi", {"input": 1}, {"returned": 1, "output": 1}, {}),
    "random_function": ("random_function", {"input": 1}, {"echo": 1, "o": 32, "samples": 128}, {}),
    "random_function_tu": ("random_function", {"input": 1}, {"echo": 1, "o": 32, "samples": 128}, {}),
    "monitor_free": ("monitor_free", {"a": 1, "b": 1}, {}, {}),
    "monitor_event": ("monitor_event", {"a": 1, "clk": 1}, {}, {}),
    "monitor_event_tu": ("monitor_event", {"a": 1, "clk": 1}, {}, {}),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrumentation(source, input_names):
    support = r'''
static std::FILE *observation_stream = nullptr;
void grhsim_observe_random(std::size_t width, std::uint64_t value) {
    std::fprintf(observation_stream, "RANDOM %zu %llu\n", width,
                 static_cast<unsigned long long>(value));
}
'''
    source = source.replace('template<class T> struct CpuTestArray', support + '\ntemplate<class T> struct CpuTestArray', 1)
    source = source.replace(
        'return static_cast<std::uint8_t>(x+1);',
        'const auto result=static_cast<std::uint8_t>(x+1);'
        'std::fprintf(observation_stream,"DPI cpu_test_inc %u %u\\n",unsigned(x),unsigned(result));return result;')
    source = source.replace(
        'return static_cast<std::uint8_t>(x*2);',
        'const auto result=static_cast<std::uint8_t>(x*2);'
        'std::fprintf(observation_stream,"DPI cpu_test_dbl %u %u\\n",unsigned(x),unsigned(result));return result;')
    source = source.replace(
        '*out = 2; return in ? 3 : 0;',
        '*out = 2; const std::uint8_t result=in ? 3 : 0;'
        'std::fprintf(observation_stream,"DPI cpu_test_bit_abi %u %u %u\\n",unsigned(in),unsigned(result),unsigned(*out));return result;')
    if source.count('sim.init();') != 1 or source.count('return 0;') != 1:
        raise RuntimeError("Unexpected frozen driver initialization/return shape")
    source = source.replace('sim.init();', r'''
observation_stream=std::fopen("observations.txt","w");
if(!observation_stream)return 2;
for(unsigned observation_epoch=0;observation_epoch<3;++observation_epoch){
std::fprintf(observation_stream,"BEGIN %u -1\n",observation_epoch);
sim.init();
sim.dumpState(observation_stream);
std::fprintf(observation_stream,"END\n");
''')
    source = source.replace('return 0;', '}\nstd::fclose(observation_stream);\nreturn 0;')
    counter = 0

    def evaluation(_):
        nonlocal counter
        step = counter
        counter += 1
        inputs = ''.join(
            f'std::fprintf(observation_stream,"INPUT {name} %llu\\n",static_cast<unsigned long long>(sim.{name}));\n'
            for name in input_names)
        return (
            f'std::fprintf(observation_stream,"BEGIN %u {step}\\n",observation_epoch);\n'
            f'std::printf("OBS_BEGIN %u {step}\\n",observation_epoch);\n' + inputs +
            'sim.eval();\nsim.dumpState(observation_stream);\n'
            'std::fprintf(observation_stream,"END\\n");\n'
            'std::printf("OBS_END\\n");\nstd::fflush(stdout);')

    source = re.sub(r'^sim\.eval\(\);$', evaluation, source, flags=re.MULTILINE)
    if not counter:
        raise RuntimeError("Frozen driver contains no eval calls")
    return source, counter


def prepare(baseline, output):
    if output.exists():
        raise RuntimeError("Observation destination already exists; preserve previous evidence")
    manifest = json.loads((baseline / 'old-fixtures.json').read_text())['files']
    output.mkdir(parents=True)
    records = {}
    for fixture, (stem, inputs, outputs, states) in FIXTURES.items():
        source = baseline / 'old-fixtures/cpu_phase_emit' / fixture
        target = output / fixture
        (target / 'model').mkdir(parents=True)
        originals = [source / 'driver.cpp'] + sorted(
            path for path in (source / 'model').iterdir()
            if path.suffix in ('.cpp', '.hpp') or path.name == 'Makefile')
        hashes = {}
        for path in originals:
            key = str(path.relative_to(baseline))
            actual = digest(path)
            if manifest[key]['sha256'] != actual:
                raise RuntimeError('Frozen fixture changed: ' + key)
            hashes[key] = actual
            if path.name != 'driver.cpp':
                shutil.copy2(path, target / 'model' / path.name)
        driver, steps = instrumentation((source / 'driver.cpp').read_text(), inputs)
        (target / 'driver.cpp').write_text(driver)
        runtime = target / 'model' / f'grhsim_phase_{stem}_runtime.hpp'
        text = runtime.read_text()
        old = '    return grhsim_trunc_u64(grhsim_splitmix64_next(state), width);'
        if text.count(old) != 1:
            raise RuntimeError('Unexpected frozen RNG helper: ' + fixture)
        text = text.replace('inline std::uint64_t grhsim_random_u64(',
                            'void grhsim_observe_random(std::size_t, std::uint64_t);\ninline std::uint64_t grhsim_random_u64(', 1)
        text = text.replace(old, '    const auto result = grhsim_trunc_u64(grhsim_splitmix64_next(state), width);\n'
                                 '    grhsim_observe_random(width, result);\n    return result;', 1)
        runtime.write_text(text)
        records[fixture] = {'stem': stem, 'inputs': inputs, 'outputs': outputs, 'states': states,
                            'steps': steps, 'source_sha256': hashes,
                            'instrumented_driver_sha256': digest(target / 'driver.cpp'),
                            'instrumented_runtime_sha256': digest(runtime)}
    (output / 'prepared.json').write_text(json.dumps({'baseline': str(baseline), 'fixtures': records}, indent=2) + '\n')


def task_records(text):
    tasks, current = {}, None
    for line in text.splitlines():
        if line.startswith('OBS_BEGIN '):
            _, epoch, step = line.split()
            current = (int(epoch), int(step))
            if current in tasks:
                raise RuntimeError('Repeated task record')
            tasks[current] = []
        elif line == 'OBS_END':
            if current is None:
                raise RuntimeError('Task record end without begin')
            current = None
        elif current is not None:
            tasks[current].append({'kind': 'task', 'text': line})
    if current is not None:
        raise RuntimeError('Incomplete task record')
    return tasks


def observations(text, fixture, tasks):
    records, current = [], None
    for line in text.splitlines():
        if line.startswith('BEGIN '):
            _, epoch, step = line.split()
            current = {'epoch': int(epoch), 'step': int(step), 'inputs': {}, 'outputs': {}, 'states': {}, 'effects': []}
        elif line == 'END':
            current['effects'].extend(tasks.get((current['epoch'], current['step']), []))
            records.append(current)
            current = None
        elif current is not None:
            fields = line.split()
            if line.startswith('INPUT '):
                current['inputs'][fields[1]] = int(fields[2])
            elif line.startswith('DPI '):
                current['effects'].append({'kind': 'dpi', 'function': fields[1], 'values': list(map(int, fields[2:]))})
            elif line.startswith('RANDOM '):
                current['effects'].append({'kind': 'random', 'width': int(fields[1]), 'value': int(fields[2])})
            elif '=' in line:
                key, value = line.split('=', 1)
                if key in fixture['outputs']:
                    current['outputs'][key] = value
                for prefix in ('smallSinkStore.', 'largeSinkStore.'):
                    if key.startswith(prefix) and key[len(prefix):] in fixture['states']:
                        current['states'][key[len(prefix):]] = value
    expected = 3 * (fixture['steps'] + 1)
    if current is not None or len(records) != expected:
        raise RuntimeError('Incomplete observations')
    if set(tasks) != {(epoch, step) for epoch in range(3) for step in range(fixture['steps'])}:
        raise RuntimeError('Missing task/output eval markers')
    for epoch in range(3):
        group = [record for record in records if record['epoch'] == epoch]
        if [record['step'] for record in group] != list(range(-1, fixture['steps'])):
            raise RuntimeError('Observation steps differ from the frozen stimulus')
        if epoch and [{k: v for k, v in item.items() if k != 'epoch'} for item in group] != [
                {k: v for k, v in item.items() if k != 'epoch'} for item in records[:fixture['steps'] + 1]]:
            raise RuntimeError('Reinitialization changed the observation sequence')
        for record in group:
            if set(record['outputs']) != set(fixture['outputs']) or set(record['states']) != set(fixture['states']):
                raise RuntimeError('Missing logical state/output projection')
            for category in ('outputs', 'states'):
                for key, value in record[category].items():
                    if int(value, 16) >= 1 << fixture[category][key]:
                        raise RuntimeError('Projection exceeds logical width')
    return records


def collect(output):
    if (output / 'manifest.json').exists():
        raise RuntimeError('Completed observation evidence must not be overwritten')
    prepared = json.loads((output / 'prepared.json').read_text())
    summary = {'schema': 'wolvrix.grhsim.observations.v1', 'baseline': prepared['baseline'],
               'prepared_sha256': digest(output / 'prepared.json'), 'fixtures': {}}
    for name, fixture in prepared['fixtures'].items():
        directory = output / name
        with (directory / 'driver.stdout').open('w') as stdout, (directory / 'driver.stderr').open('w') as stderr:
            subprocess.run([str(directory / 'driver')], cwd=directory, stdout=stdout, stderr=stderr, check=True)
        task_file = directory / 'task_output.txt'
        tasks = task_records((task_file if task_file.exists() else directory / 'driver.stdout').read_text())
        records = observations((directory / 'observations.txt').read_text(), fixture, tasks)
        path = directory / 'observations.jsonl'
        path.write_text(''.join(json.dumps(record, sort_keys=True) + '\n' for record in records))
        summary['fixtures'][name] = {'records': len(records), 'sha256': digest(path),
                                      'types': {category: {key: {'width': width, 'shape': [4] if key == 'samples' else [],
                                                                   'domain': '2state', 'signed': False}
                                                           for key, width in fixture[category].items()}
                                                for category in ('inputs', 'outputs', 'states')},
                                      'effects': {kind: sum(effect['kind'] == kind for record in records for effect in record['effects'])
                                                  for kind in ('dpi', 'task', 'random')}}
        counts = summary['fixtures'][name]['effects']
        kind = 'dpi' if name.startswith('dpi_') else 'task' if name.startswith('monitor_') else 'random'
        if not counts[kind]:
            raise RuntimeError('Expected effects were not instrumented: ' + name)
    for plain, split in (('dpi_smoke', 'dpi_smoke_tu'), ('random_function', 'random_function_tu'),
                         ('monitor_event', 'monitor_event_tu')):
        if summary['fixtures'][plain]['sha256'] != summary['fixtures'][split]['sha256']:
            raise RuntimeError('Single/TU observable execution differs: ' + plain)
    (output / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'collect'])
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    baseline, output = args.baseline.resolve(), args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp/remove-grhsim-ir') or output.is_relative_to(baseline):
        parser.error('output must be under ptmp/remove-grhsim-ir and outside the frozen baseline')
    if args.mode == 'prepare':
        prepare(baseline, output)
    else:
        collect(output)


if __name__ == '__main__':
    main()
