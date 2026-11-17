#!/usr/bin/env python3
"""Audit a frozen zero-hit experiment without launching or timing a simulator."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from grhsim_elf_section_identity import sections
from grhsim_single_baseline import identity, save
import xiangshan_cross_region_views_compare as experiment
from xiangshan_shared_cost_guard_compare import verify_reuse_settings


def audit(out):
    experiment.check(out)
    experiment.check_harness_source()
    baseline = experiment.FULL
    candidate = out / 'candidate'
    read = experiment.read
    before_sources = read(baseline / 'model-sources.json')
    after_sources = read(candidate / 'model-sources.json')
    if experiment.source_shape(before_sources) != experiment.source_shape(after_sources):
        raise ValueError('generated sources differ')
    structure = read(out / 'structure.json')
    if structure['guard']['cross_region_sites'] != 0:
        raise ValueError('cross-region proof sites were added')
    verify_reuse_settings(baseline, candidate,
                          read(candidate / 'logs/compile.command.json')['argv'])
    binaries = {name: read(folder / 'binary.json')
                for name, folder in (('baseline', baseline), ('candidate', candidate))}
    data = {name: Path(record['path']).read_bytes() for name, record in binaries.items()}
    if len(data['baseline']) != len(data['candidate']):
        raise ValueError('ELF sizes differ')
    # The harness prints __TIME__ in its startup banner. Allow only this exact
    # string to differ; every other byte of both complete ELF files must match.
    pattern = rb'compiled at %s, %s\n\0[A-Z][a-z]{2} [ 0-9][0-9] [0-9]{4}\0(\d{2}:\d{2}:\d{2})\0'
    matches = {name: list(re.finditer(pattern, content)) for name, content in data.items()}
    if any(len(value) != 1 for value in matches.values()):
        raise ValueError('expected exactly one harness build-time banner per ELF')
    spans = {name: value[0].span(1) for name, value in matches.items()}
    if spans['baseline'] != spans['candidate']:
        raise ValueError('build-time strings moved')
    lo, hi = spans['baseline']
    normalized = {name: value[:lo] + b'00:00:00' + value[hi:]
                  for name, value in data.items()}
    if normalized['baseline'] != normalized['candidate']:
        raise ValueError('ELFs differ outside the harness build-time banner')
    different_bytes = [i for i, (a, b) in enumerate(zip(data['baseline'], data['candidate']))
                       if a != b]
    result = dict(
        status='no_codegen_effect', new_performance_pairs=0,
        reason='No proof sites; generated model unchanged; complete ELF unchanged except startup build-time text.',
        generated_file_count=len(after_sources), cross_region_sites=0,
        normalized_compile_settings_equal=True, generated_harness_inputs_equal=True,
        binaries=binaries,
        sections={name: sections(record['path']) for name, record in binaries.items()},
        only_elf_difference=dict(
            meaning='DiffTest common.cpp __TIME__ startup banner',
            allowed_span=[lo, hi], changed_offsets=different_bytes,
            strings={name: value[lo:hi].decode() for name, value in data.items()},
            normalized_sha256=hashlib.sha256(normalized['baseline']).hexdigest()),
        inputs=[identity(out / 'build.json'), identity(out / 'structure.json'),
                identity(baseline / 'model-sources.json'),
                identity(candidate / 'model-sources.json'),
                identity(experiment.XS / 'difftest/src/test/csrc/common/common.cpp'),
                identity(Path(__file__).resolve())],
        validation_scope='This is an offline identity audit, not a new DiffTest or timing run. '
                         'Existing baseline validation remains historical evidence.')
    save(out / 'no-codegen-effect-audit.json', result)
    print(json.dumps({key: result[key] for key in
                     ('status', 'generated_file_count', 'cross_region_sites',
                      'new_performance_pairs', 'only_elf_difference')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    audit(args.source.resolve())
