"""Rank reg-to-mem groups by enabled write ports and actual state changes."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from source_categories import read_lcov

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grhsim_change_sites import MARKER, fingerprinted_sources

WRITE = re.compile(rb"// op (.+) \[kRegisterWritePort\] reg=(.+)")
SEQUENCE = struct.Struct("=4I")  # visits, changes, transitions, branch-predictor misses


def load_groups(path, graph):
    groups = []
    by_port = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        for line in stream:
            group = json.loads(line)
            if group["graph"] != graph:
                continue
            groups.append(group)
            for number, op, reg in group["writes"]:
                if (op, reg) in by_port and by_port[op, reg] != number:
                    raise ValueError(f"ambiguous input write identity {(op, reg)}")
                by_port[op, reg] = number
    if not groups:
        raise ValueError(f"no groups for graph {graph}")
    return groups, by_port


def model_sites(model):
    digest = hashlib.sha256()
    inventory = {}
    for path, data, entry in fingerprinted_sources(model):
        digest.update(entry)
        if path.suffix != ".cpp":
            continue
        sites = sorted({(k.decode(), int(n)) for k, n in MARKER.findall(data)})
        if not sites:
            continue
        # The emitter writes the operation and destination immediately above its scalar commit.
        commits = {}
        if any(kind == "EAGER" for kind, _ in sites):
            owner = None
            for line in data.splitlines():
                if b"// op " in line:
                    match = WRITE.fullmatch(line.strip())
                    owner = tuple(s.decode() for s in match.groups()) if match else None
                elif line.startswith(b"#ifdef GRHSIM_EAGER_"):
                    number = int(line.rsplit(b"_", 1)[1])
                    if owner is None or commits.setdefault(number, owner) != owner:
                        raise ValueError(f"ambiguous emitted write {path.name} {number}")
        inventory[path.name] = sites, commits
    return digest.hexdigest(), inventory


def site_counts(model, profile, sequence, by_port, check_training):
    digest, inventory = model_sites(model)
    counts = defaultdict(Counter)
    emitted_ids = {}
    with gzip.open(profile, "rt") as stream:
        version, expected, cycles = next(stream).split()
        if version != "grhsim-change-sites-v1" or digest != expected or int(cycles) <= 0:
            raise ValueError("site profile does not match the emitted sources")
        for name, (sites, commits) in inventory.items():
            if next(stream).split() != [name, str(len(sites))]:
                raise ValueError(f"wrong profile inventory for {name}")
            if sequence:
                raw = (sequence / (Path(name).stem + ".bin")).read_bytes()
                if len(raw) != SEQUENCE.size * len(sites):
                    raise ValueError(f"wrong sequence size for {name}")
                records = SEQUENCE.iter_unpack(raw)
            for kind, number in sites:
                tag, site, visits, changes = next(stream).split()
                n, c = int(visits), int(changes)
                if (tag, int(site)) != (kind, number) or not 0 <= c <= n:
                    raise ValueError(f"wrong profile row for {name} {kind} {number}")
                if sequence:
                    seq_n, seq_c, _, _ = next(records)
                    if seq_c > seq_n or (check_training and (n, c) != (seq_n, seq_c)):
                        raise ValueError(f"wrong sequence counts for {name} {kind} {number}")
                    n, c = seq_n, seq_c
                if kind == "EAGER" and commits[number] in by_port:
                    port = commits[number]
                    if emitted_ids.setdefault(port, number) != number:
                        raise ValueError(f"ambiguous scheduled write ID for {port}")
                    counts[port].update(visits=n, changes=c)
        if stream.readline():
            raise ValueError("extra site profile rows")
    return digest, int(cycles), counts, emitted_ids


def commit_lines(rows, start, shared_predicate):
    """Return LCOV's 1-based visit/change lines for a recognized write."""
    if shared_predicate is not None and rows[start + 1].strip().endswith(b" = next_value;"):
        return shared_predicate + 1, start + 2, "lockstep"
    for j in range(start + 1, len(rows) - 1):
        line = rows[j].strip()
        if line == b"}" or line.startswith(b"// op "):
            break
        if line.startswith(b"if ("):
            body = rows[j + 1].strip()
            if body.endswith(b" = next_value;"):
                dst = body.removesuffix(b" = next_value;")
                if dst + b" != next_value)" in line:
                    return j + 1, j + 2, "scalar"
            if (re.search(rb"\bgrhsim_assign_words(?:_(?:2|full)<\d+>)?\(", line) and line.endswith(b") {")
                    and body.endswith(b";") and not body.startswith(b"//")):
                return j + 1, j + 2, "wide"
    return None


def coverage_counts(lcov, by_port):
    counts = defaultdict(Counter)
    incomplete = set()
    for file, lines, _ in read_lcov(lcov):
        path = Path(file)
        if "_sched_" not in path.name:
            continue
        rows = path.read_bytes().splitlines()
        shared_predicate = None
        for i, row in enumerate(rows):
            if row.strip() == b"// Lockstep scalar register writes share one change predicate.":
                # The emitter places the shared if after the opening brace and next_value.
                guard = rows[i + 3].lstrip()
                if guard.startswith(b"if (") and b" != next_value)" in guard:
                    shared_predicate = i + 3
                continue
            if shared_predicate is not None and i > shared_predicate and row.strip() == b"}":
                shared_predicate = None
            if b"[kRegisterWritePort] reg=" not in row:
                continue
            match = WRITE.fullmatch(row.strip())
            if not match:
                continue
            port = tuple(s.decode() for s in match.groups())
            if port not in by_port:
                continue
            pair = commit_lines(rows, i, shared_predicate)
            if pair is None or pair[0] not in lines or pair[1] not in lines:
                incomplete.add(port)
                continue
            visit_line, change_line, shape = pair
            n, c = lines[visit_line], lines[change_line]
            if not 0 <= c <= n:
                raise ValueError(f"invalid compare/store counts at {file}:{visit_line}")
            counts[port].update(visits=n, changes=c)
            if shape == "lockstep":
                counts[port].update(shared_predicate_visits=n)
    for port in incomplete:
        counts.pop(port, None)
    return counts


def summarize(groups, eager, emitted_ids, coverage):
    group_counts = Counter()
    members = Counter()
    owners = defaultdict(set)
    for group in groups:
        reason = group["outcome"]
        if reason == "no_true_match" and group["consolidated_reject"]:
            reason = group["consolidated_reject"]
        group_counts[reason] += 1
        members[reason] += group["members"]
        for number, op, reg in group["writes"]:
            owners[op, reg].add((reason, number))

    totals = defaultdict(Counter)
    for port, classes in owners.items():
        # A shared port contributes once even if several read-anchor groups include it.
        reasons = sorted({reason for reason, _ in classes})
        reason = "+".join(reasons)
        row = totals[reason]
        row["ports"] += 1
        if port in eager:
            counts = eager[port]
            row["site_ports"] += 1
            row["site_visits"] += counts["visits"]
            row["site_changes"] += counts["changes"]
            row["renumbered_sites"] += int(emitted_ids[port] != next(iter(classes))[1])
            if port in coverage:
                if any(counts[k] != coverage[port][k] for k in ("visits", "changes")):
                    raise ValueError(f"line counts differ from site counts at {port}")
                row["crosschecked_ports"] += 1
        elif port in coverage:
            counts = coverage[port]
            row["coverage_only_ports"] += 1
        else:
            row["unmeasured_ports"] += 1
            continue
        row.update(counts)
    for reason in group_counts:
        totals[reason].update(groups=group_counts[reason], members=members[reason])
    return dict(sorted(totals.items(), key=lambda item: -item[1]["visits"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--sequence", type=Path, help="per-shard four-counter files in this profile's order")
    parser.add_argument("--check-training", action="store_true", help="verify all sequence rows against training")
    parser.add_argument("--lcov", type=Path, help="matching workload's scalar compare/store line coverage")
    args = parser.parse_args()
    if args.check_training and not args.sequence:
        parser.error("--check-training requires --sequence")
    groups, ports = load_groups(args.groups, args.graph)
    digest, cycles, eager, ids = site_counts(args.model, args.profile, args.sequence, ports, args.check_training)
    coverage = coverage_counts(args.lcov, ports) if args.lcov else {}
    print(json.dumps(dict(graph=args.graph, model_sha256=digest, training_cycles_requested=cycles,
                          classes=summarize(groups, eager, ids, coverage)), indent=2))


if __name__ == "__main__":
    main()
