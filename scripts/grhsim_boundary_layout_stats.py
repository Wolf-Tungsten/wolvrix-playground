"""Measure word-batching opportunity for boundary byte compare-and-write sites."""

import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    value_slots = payload[3][3]
    schedule = payload[4]
    cpu_types = {t[0]: t for t in payload[3][1]}

    fanout_key = {}
    for source, activates, arms in schedule[2]:
        fanout_key[source] = (tuple(activates), tuple(arms))
    port_words = Counter()  # values with port-arm targets are not knowable here; count separately

    runs = Counter()
    groupable = Counter()
    total_byte_boundary = 0
    per_supernode_covered = 0
    for pid, part in partitions.items():
        if part[2] != 3:
            continue
        members = []
        stack = [pid]
        while stack:
            node = partitions[stack.pop()]
            members.extend(node[5])
            stack.extend(node[4])
        sites = []
        for op_id in members:
            op = ops[op_id - 1]
            for value in op[5]:
                slot = value_slots[value - 1]
                if slot[1] != 2:
                    continue
                ctype = cpu_types[slot[0]]
                if ctype[5] != 1:  # size != 1 byte
                    continue
                sites.append((slot[3], value))
        if not sites:
            continue
        total_byte_boundary += len(sites)
        sites.sort()
        # Runs of byte-adjacent slots produced by this supernode.
        run = [sites[0]]
        for site in sites[1:]:
            if site[0] == run[-1][0] + 1:
                run.append(site)
            else:
                runs[len(run)] += 1
                run = [site]
        runs[len(run)] += 1
        # Stricter: adjacent AND identical fanout key.
        grouped_runs = []
        run = [sites[0]]
        for site in sites[1:]:
            if site[0] == run[-1][0] + 1 and fanout_key.get(site[1]) == fanout_key.get(run[-1][1]):
                run.append(site)
            else:
                grouped_runs.append(run)
                run = [site]
        grouped_runs.append(run)
        for run in grouped_runs:
            groupable[min(len(run), 8)] += 1
            if len(run) >= 4:
                per_supernode_covered += len(run)
    print(f"total 1-byte boundary results in supernodes={total_byte_boundary}")
    print("== plain adjacency run lengths ==")
    covered = 0
    for length in sorted(runs):
        print(f"len={length}: {runs[length]} runs, {runs[length] * length} values")
        if length >= 4:
            covered += runs[length] * length
    print(f"values in runs>=4: {covered} ({100.0 * covered / max(total_byte_boundary, 1):.2f}%)")
    print("== adjacent + same-fanout runs (capped at 8) ==")
    covered = 0
    for length in sorted(groupable):
        print(f"len={length}: {groupable[length]} runs, {groupable[length] * length} values")
        if length >= 4:
            covered += groupable[length] * length
    print(f"values in groupable runs>=4: {covered} ({100.0 * covered / max(total_byte_boundary, 1):.2f}%)")


if __name__ == "__main__":
    main()
