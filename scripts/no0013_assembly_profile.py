#!/usr/bin/env python3
"""NO0013 Phase A: assembly-cone block profiler.

Single-pass census of the AM instruction graph (node records only):
  - per-block instruction count and wide-op (width >= 256 bits) opcode mix,
    wide-bit volume, and top gsim nodes by wide-bit volume;
  - joins per-block runtime cycles from an EMU_AM_BLOCK_EXECS dump;
  - per-gnode global aggregation of wide ops (assembly family attribution).

Usage:
  no0013_assembly_profile.py <instruction_graph.jsonl> <am_block_atom.jsonl> \
      <block_execs.txt> --out <prefix>

Writes <prefix>.json (full tables) and prints a human summary.
"""
import json
import re
import sys
from array import array
from collections import defaultdict

NODE_RE = re.compile(
    r'^\{"record":"node","id":(\d+),"op":\d+,"opcode":"([^"]+)",'
    r'"width":(\d+),"state_write":(?:true|false),"atom":(\d+),'
    r'.*?"gnode":(-?\d+)')
WIDE_BITS = 256          # >= 4 words: chain-slice territory
FULL_BITS = 4096         # >= 64 words: full-width rebuild territory


def main():
    graph_path, atom_path, execs_path = sys.argv[1:4]
    out_prefix = sys.argv[sys.argv.index('--out') + 1]

    # gsim_node -> block join key (graph jsonl atom ids are pre-scheduling;
    # am_block_atom.jsonl uses scheduled-program atom ids, so join via gnode)
    atom_block = array('i')
    block_role = {}
    gnode_block = {}
    gnode_dup = 0
    with open(atom_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            rec = json.loads(line)
            if 'block' in rec and 'atom' not in rec:
                block_role[rec['block']] = rec.get('role', '?')
            elif 'atom' in rec:
                atom = rec['atom']
                while len(atom_block) <= atom:
                    atom_block.append(-1)
                atom_block[atom] = rec['block']
                gn = rec.get('gsim_node', -1)
                if gn >= 0:
                    if gn in gnode_block and gnode_block[gn] != rec['block']:
                        gnode_dup += 1
                    else:
                        gnode_block[gn] = rec['block']

    # per-block aggregates
    blk_instr = defaultdict(int)
    blk_bits = defaultdict(int)
    blk_wide_instr = defaultdict(int)
    blk_wide_bits = defaultdict(int)
    blk_full_instr = defaultdict(int)
    blk_wide_opmix = defaultdict(lambda: defaultdict(int))
    blk_gnode_bits = defaultdict(lambda: defaultdict(int))
    # per-gnode global aggregates
    gn_wide_instr = defaultdict(int)
    gn_wide_bits = defaultdict(int)
    gn_blocks = defaultdict(set)
    totals = {'nodes': 0, 'wide_nodes': 0, 'wide_bits': 0,
              'unmapped_nodes': 0, 'gnode_dup': gnode_dup}

    with open(graph_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            m = NODE_RE.match(line)
            if not m:
                continue
            opcode = m.group(2)
            width = int(m.group(3))
            gnode = int(m.group(5))
            block = gnode_block.get(gnode, -1)
            if block < 0:
                totals['unmapped_nodes'] += 1
            totals['nodes'] += 1
            blk_instr[block] += 1
            blk_bits[block] += width
            if width >= WIDE_BITS:
                totals['wide_nodes'] += 1
                totals['wide_bits'] += width
                blk_wide_instr[block] += 1
                blk_wide_bits[block] += width
                blk_wide_opmix[block][opcode] += 1
                blk_gnode_bits[block][gnode] += width
                gn_wide_instr[gnode] += 1
                gn_wide_bits[gnode] += width
                if block >= 0:
                    gn_blocks[gnode].add(block)
                if width >= FULL_BITS:
                    blk_full_instr[block] += 1

    # execs/cycles
    blk_execs, blk_cycles = {}, {}
    with open(execs_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 4 and parts[0].lstrip('-').isdigit():
                b = int(parts[0])
                blk_execs[b] = int(parts[2])
                blk_cycles[b] = int(parts[3])

    top_blocks = sorted(blk_cycles, key=lambda b: -blk_cycles[b])
    block_table = []
    wide_block_cycles = 0
    wide_block_count = 0
    for b in top_blocks:
        if blk_cycles[b] <= 0:
            continue
        if blk_wide_instr[b] > 0:
            wide_block_cycles += blk_cycles[b]
            wide_block_count += 1
        gnodes = sorted(blk_gnode_bits[b].items(), key=lambda kv: -kv[1])[:3]
        block_table.append({
            'block': b, 'role': block_role.get(b, '?'),
            'cycles_G': round(blk_cycles[b] / 1e9, 2),
            'execs': blk_execs.get(b, 0),
            'per_fire_K': round(blk_cycles[b] / max(blk_execs.get(b, 1), 1) / 1e3, 1),
            'instrs': blk_instr[b],
            'Mbits': round(blk_bits[b] / 1e6, 1),
            'wide_instrs': blk_wide_instr[b],
            'full_instrs': blk_full_instr[b],
            'wide_Mbits': round(blk_wide_bits[b] / 1e6, 1),
            'wide_opmix': dict(sorted(blk_wide_opmix[b].items(),
                                      key=lambda kv: -kv[1])[:6]),
            'top_gnodes': gnodes,
        })

    top_gnodes = sorted(gn_wide_bits, key=lambda g: -gn_wide_bits[g])[:25]
    gnode_table = [{
        'gnode': g,
        'wide_instrs': gn_wide_instr[g],
        'wide_Mbits': round(gn_wide_bits[g] / 1e6, 1),
        'blocks': sorted(gn_blocks[g])[:12],
        'block_cycles_G': round(sum(blk_cycles.get(b, 0)
                                    for b in gn_blocks[g]) / 1e9, 2),
    } for g in top_gnodes]

    out = {'totals': totals,
           'wide_block_count': wide_block_count,
           'wide_block_cycles_G': round(wide_block_cycles / 1e9, 2),
           'top_blocks': block_table,
           'top_gnodes_by_wide_bits': gnode_table}
    with open(out_prefix + '.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1)

    print(f"nodes={totals['nodes']} wide(>= {WIDE_BITS}b) nodes={totals['wide_nodes']} "
          f"wide_bits={totals['wide_bits'] / 1e6:.0f}M "
          f"unmapped={totals['unmapped_nodes']} gnode_dup={totals['gnode_dup']}")
    print(f"wide-carrying blocks: {wide_block_count}, "
          f"their cycles: {wide_block_cycles / 1e9:.2f}G")
    print('\n== top blocks by cycles (with wide-op composition) ==')
    for row in block_table[:25]:
        print(f"b{row['block']} {row['role']:7s} {row['cycles_G']:8.2f}G "
              f"execs={row['execs']:7d} perfire={row['per_fire_K']:8.1f}K "
              f"instr={row['instrs']:6d} Mb={row['Mbits']:6.1f} "
              f"wide={row['wide_instrs']:6d} "
              f"full={row['full_instrs']:5d} wideMb={row['wide_Mbits']:7.1f} "
              f"{row['wide_opmix']} g={row['top_gnodes']}")
    print('\n== top gnodes by wide bits ==')
    for row in gnode_table[:15]:
        print(f"g{row['gnode']} wide={row['wide_instrs']:7d} "
              f"wideMb={row['wide_Mbits']:8.1f} cyc={row['block_cycles_G']:8.2f}G "
              f"blocks={row['blocks']}")


if __name__ == '__main__':
    main()
