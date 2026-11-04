#!/usr/bin/env python3
"""Export valid committed instructions from generated DiffTest binary records.

The stream is a committed-instruction distribution, not an IFU/decode activity
trace. XiangShan's debug_instr carries the expanded backend instruction.
"""
import argparse
import json
from pathlib import Path
import subprocess

from grhsim_single_baseline import identity, save
from decode_table_study import CXX, parse, write_vectors


def export(header, trace, output):
    header, trace, output = map(lambda p: Path(p).resolve(), (header, trace, output))
    output.mkdir(parents=True, exist_ok=False)
    chunks = sorted(trace.glob('*.bin'), key=lambda p: int(p.stem))
    if not chunks or [int(p.stem) for p in chunks] != list(range(len(chunks))):
        raise ValueError('trace must contain a contiguous sequence starting at 0.bin')
    source = output / 'export.cpp'
    source.write_text('#include ' + json.dumps(str(header)) + '\n' + r'''
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
int main(int argc, char** argv) {
    if (argc < 3) return 2;
    std::ofstream out(argv[1]);
    out << "record,cycle,slot,pc,instruction,n_fused,is_rvc,skip\n";
    std::uint64_t records = 0, commits = 0, last = 0, fused = 0;
    for (int arg = 2; arg < argc; ++arg) {
        std::ifstream input(argv[arg], std::ios::binary);
        if (!input) return 3;
        DiffTestState state{};
        while (input.read(reinterpret_cast<char*>(&state), sizeof(state))) {
            const auto cycle = state.trap.cycleCnt;
            if (records && cycle < last) return 4;
            last = cycle;
            for (std::size_t slot = 0; slot < std::size(state.commit); ++slot) {
                const auto& c = state.commit[slot];
                if (!c.valid) continue;
                out << records << ',' << cycle << ',' << slot << ',' << c.pc << ',' << c.instr
                    << ',' << unsigned(c.nFused) << ',' << unsigned(c.isRVC) << ',' << unsigned(c.skip) << '\n';
                ++commits;
                fused += c.nFused;
            }
            ++records;
        }
        if (input.gcount() || !input.eof()) return 5;
    }
    if (!records || !commits || !out) return 6;
    std::cout << "{\"records\":" << records << ",\"commits\":" << commits
              << ",\"fused_extra_instructions\":" << fused
              << ",\"record_bytes\":" << sizeof(DiffTestState) << "}\n";
}
''')
    command = [CXX, '-std=c++20', '-O2', str(source), '-o', str(output/'export')]
    subprocess.run(command, check=True)
    result = json.loads(subprocess.check_output(
        [output/'export', output/'instructions.csv', *chunks], text=True))
    save(output/'manifest.json', dict(**result, header=identity(header), chunks=[identity(p) for p in chunks],
        command=command, source=identity(source), csv=identity(output/'instructions.csv'),
        scope='Valid commit-slot expanded instructions in record/slot order; fused extra instructions not reconstructed; not speculative decode inputs'))
    return output/'instructions.csv'


def instruction_vectors(table_file, instructions, destination):
    import csv
    table = parse(Path(table_file).read_text())
    if table['n'] != 32:
        raise ValueError('committed instructions require a 32-bit instruction table')
    with Path(instructions).open() as stream:
        count = write_vectors(Path(destination), table, (int(r['instruction']) for r in csv.DictReader(stream)))
    save(str(destination)+'.json', dict(table=identity(table_file), trace=identity(instructions),
        vectors=count, output=identity(destination), scope='Committed instruction distribution'))
    return count


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--header', type=Path, required=True)
    p.add_argument('--trace', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--table', type=Path)
    args = p.parse_args()
    instructions = export(args.header, args.trace, args.output)
    if args.table:
        instruction_vectors(args.table, instructions, args.output/'committed.bin')
