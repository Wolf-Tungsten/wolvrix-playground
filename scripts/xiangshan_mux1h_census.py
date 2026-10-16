"""Count Scala Mux1H call sites and their source-attributed FIRRTL expansions.

This reads existing artifacts; it does not elaborate or run a simulator. A FIRRTL
tree is one scalar/ground field, while an aggregate Mux1H can have many trees.
"""

import argparse
import bisect
from collections import Counter, defaultdict
import csv
from functools import lru_cache
import json
from pathlib import Path
import re


# Production source roots declared by testcase/xiangshan/build.mill. In
# particular, nested copies of Rocket Chip under openLLC are not moduleDeps.
MAIN_ROOTS = {
    "xiangshan": "src/main/scala",
    **{name: f"{name}/src/main/scala" for name in (
        "utility", "yunsuan", "huancun", "coupledL2", "openLLC", "difftest",
        "ChiselAIA", "ChiselIOPMP", "macros", "rocket-chip")},
    "openNCB": "openLLC/openNCB/src/main/scala",
    "rocket-hardfloat": "rocket-chip/hardfloat/hardfloat/src/main/scala",
    "rocket-cde": "rocket-chip/cde/cde/src/main/scala",
    "rocket-macros": "rocket-chip/macros/src/main/scala",
}


def code_only(source):
    """Mask comments and literal text without changing line/column offsets."""
    result = list(source)
    i = 0
    while i < len(source):
        start = i
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            depth = 1
            i += 2
            while i < len(source) and depth:
                if source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
        elif source.startswith('"""', i):
            end = source.find('"""', i + 3)
            i = len(source) if end < 0 else end + 3
        elif source[i] == '"':
            i += 1
            while i < len(source):
                ch = source[i]
                i += 1
                if ch == "\\":
                    i += 1
                elif ch == '"':
                    break
        elif source[i] == "'" and re.match(r"'(?:\\.|[^'\n\\])'", source[i: i + 8]):
            match = re.match(r"'(?:\\.|[^'\n\\])'", source[i: i + 8])
            i += len(match[0])
        else:
            i += 1
            continue
        for j in range(start, min(i, len(source))):
            if source[j] != "\n":
                result[j] = " "
    return "".join(result)


def matching_end(text, start, opening="(", closing=")"):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError(f"unclosed {opening} at {start}")


def find_calls(source, relative, component):
    code = code_only(source)
    newlines = [-1] + [m.start() for m in re.finditer("\n", code)]
    records = []
    for match in re.finditer(r"\bMux1H\b", code):
        offset = match.end()
        apply = re.match(r"\s*\.\s*apply\b", code[offset:])
        if apply:
            offset += apply.end()
        while offset < len(code) and code[offset].isspace():
            offset += 1
        if offset < len(code) and code[offset] == "[":
            offset = matching_end(code, offset, "[", "]")
            while offset < len(code) and code[offset].isspace():
                offset += 1
        if offset >= len(code) or code[offset] != "(":
            continue
        # Exclude a local definition named Mux1H, if one exists.
        if re.search(r"\b(?:def|class|object)\s*$", code[max(0, match.start() - 30):match.start()]):
            continue
        end = matching_end(code, offset)
        line = bisect.bisect_left(newlines, match.start())
        end_line = bisect.bisect_left(newlines, end - 1)
        col = match.start() - newlines[line - 1]
        end_col = end - newlines[end_line - 1]
        records.append({
            "id": f"{relative}:{line}:{col}", "file": relative,
            "component": component, "line": line, "column": col,
            "end_line": end_line, "end_column": end_col,
            "source": " ".join(source[match.start():end].split())[:600],
        })
    return records


def source_census(root):
    records = []
    main_files = {}
    for component, directory in MAIN_ROOTS.items():
        for path in sorted((root / directory).rglob("*.scala")):
            main_files[path.relative_to(root).as_posix()] = component
    # Include other checked-in/vendor/test source trees as a separate scope.
    # rg follows the repository's ignore rules, avoiding generated out/ sources.
    import subprocess
    files = subprocess.check_output(
        ["rg", "--files", "--hidden", "-g", "*.scala", "-g", "!**/.git/**", str(root)],
        text=True).splitlines()
    files = sorted(set(files) | {str(root / name) for name in main_files})
    for filename in files:
        path = Path(filename)
        relative = path.relative_to(root).as_posix()
        component = main_files.get(relative, "other/" + relative.split("/")[0])
        records.extend(find_calls(path.read_text(), relative, component))
    return records, {"scala_files": len(files), "main_scala_files": len(main_files)}


def split_args(expr):
    depth = 0
    start = 0
    args = []
    for i, ch in enumerate(expr):
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(expr[start:i].strip())
            start = i + 1
    args.append(expr[start:].strip())
    return args


@lru_cache(maxsize=4096)
def source_path(path, root):
    marker = str(root.resolve()).lstrip("/") + "/"
    pos = path.find(marker)
    return path[pos + len(marker):] if pos >= 0 else path


def fir_census(path, calls, root):
    by_line = defaultdict(list)
    for call in calls:
        for line in range(call["line"], call["end_line"] + 1):
            by_line[(call["file"], line)].append(call)
    module_re = re.compile(r"^  (?:public )?(?:extmodule|module|intmodule) ([^ :]+)")
    instance_re = re.compile(r"^\s+inst (\S+) of (\S+)")
    loc_re = re.compile(r"([^\s\[\]]+\.scala) (\d+):(\d+)")
    node_re = re.compile(r"^\s+node (\S+) = (\w+)\((.*)\)$")
    connect_re = re.compile(r"^\s+connect (\S+), (\S+)$")
    wire_re = re.compile(r"^\s+wire (\S+) : (.*)$")
    zero_re = re.compile(r"^[US]Int(?:<\d+>)?\(0[hbod]0+\)$")
    modules = {}
    trees = []
    seen_calls = set()
    exact_calls = set()
    attributed_lines = Counter()
    module = None
    candidates = {}
    consumed = set()
    aggregate_wires = {}
    connections = defaultdict(list)
    aliases = {}

    def resolve(name):
        visited = set()
        while name in aliases and name not in visited:
            visited.add(name)
            name = aliases[name]
        return name

    def flush():
        if module is None:
            return
        for name, record in candidates.items():
            if name in consumed:
                continue
            # Each aggregate call has a fresh result wire; all field trees
            # connected to it belong to that same call expansion.
            groups = [dest.split(".")[0].split("[")[0]
                      for dest in connections.get(name, ())]
            group = next((dest for dest in groups
                          if aggregate_wires.get(dest) == record["call"]), name)
            visited = set()
            while group in aggregate_wires and group not in visited:
                visited.add(group)
                parents = [dest.split(".")[0].split("[")[0]
                           for dest in connections.get(group, ())]
                parent = next((dest for dest in parents if dest != group
                               and aggregate_wires.get(dest) == record["call"]), None)
                if parent is None:
                    break
                group = parent
            trees.append({"module": module, "root": name, "group": group, **record})

    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            match = module_re.match(line)
            if match:
                flush()
                module = match[1]
                modules[module] = {"instances": [], "line": number}
                candidates = {}
                consumed = set()
                aggregate_wires = {}
                connections = defaultdict(list)
                aliases = {}
                continue
            if module is None:
                continue
            inst = instance_re.match(line)
            if inst:
                modules[module]["instances"].append([inst[1], inst[2]])
            code, sep, info = line.partition(" @[")
            if not sep:
                continue
            locations = []
            for loc in loc_re.finditer(info):
                filename = source_path(loc[1], root)
                line_num, column = int(loc[2]), int(loc[3])
                for call in by_line.get((filename, line_num), ()):
                    if line_num == call["line"] and column < call["column"]:
                        continue
                    if line_num == call["end_line"] and column >= call["end_column"]:
                        continue
                    locations.append((call, line_num, column))
            if not locations:
                continue
            # Nested Mux1H calls have overlapping source spans.
            call, source_line, column = min(locations, key=lambda item: (
                item[0]["end_line"] - item[0]["line"],
                item[0]["end_column"] - item[0]["column"]))
            call_id = call["id"]
            seen_calls.add(call_id)
            attributed_lines[call_id] += 1
            # Chisel's source macro identifies the last character of Mux1H.
            # Argument expressions have their own columns within the call's
            # span; counting their zero-else muxes would inflate the inventory.
            if source_line != call["line"] or column != call["column"] + 5:
                continue
            exact_calls.add(call_id)
            code = code.rstrip()
            wire = wire_re.match(code)
            if wire and ("{" in wire[2] or "[" in wire[2]):
                aggregate_wires[wire[1]] = call_id
            connect = connect_re.match(code)
            if connect:
                connections[resolve(connect[2])].append(connect[1])
            node = node_re.match(code)
            if not node:
                continue
            name, kind, body = node.groups()
            if kind in ("bits", "asUInt", "asSInt", "pad", "head", "tail"):
                args = split_args(body)
                aliases[name] = resolve(args[0])
                continue
            if kind not in ("mux", "or"):
                continue
            args = split_args(body)
            if kind == "mux" and len(args) == 3 and zero_re.match(args[2]):
                candidates[name] = {"call": call_id, "terms": 1,
                                    "mask_example": args[0], "data_example": args[1],
                                    "fir_line": number}
            elif kind == "or" and len(args) == 2 and all(
                    resolve(arg) in candidates and candidates[resolve(arg)]["call"] == call_id for arg in args):
                refs = [resolve(arg) for arg in args]
                left, right = (candidates[arg] for arg in refs)
                candidates[name] = {**left, "terms": left["terms"] + right["terms"],
                                    "fir_line": number}
                consumed.update(refs)
    flush()
    # Weight module definitions by their actual instance count below SimTop.
    multiplicities = Counter()
    pending = [("SimTop", 1)]
    while pending:
        name, count = pending.pop()
        multiplicities[name] += count
        for _, child in modules.get(name, {}).get("instances", ()):
            pending.append((child, count))
    for tree in trees:
        tree["instances"] = multiplicities[tree["module"]]
    expansions = {}
    for tree in trees:
        key = (tree["module"], tree["call"], tree["group"])
        if key not in expansions:
            expansions[key] = {k: tree[k] for k in ("module", "call", "group", "terms", "instances")}
            expansions[key]["fields"] = 0
        expansions[key]["fields"] += 1
        if expansions[key]["terms"] != tree["terms"]:
            expansions[key]["mixed_terms"] = True
    return trees, list(expansions.values()), {
        "modules": len(modules), "reachable_module_definitions": len(multiplicities),
        "source_calls_with_fir_annotations": len(seen_calls),
        "source_calls_with_exact_fir_annotations": len(exact_calls),
        "source_calls_with_masked_trees": len({t["call"] for t in trees}),
        "attributed_lines": sum(attributed_lines.values()),
        "scalar_trees": len(trees), "scalar_trees_instance_weighted": sum(t["instances"] for t in trees),
        "grouped_expansions": len(expansions),
        "grouped_expansions_instance_weighted": sum(e["instances"] for e in expansions.values()),
        "terms_scalar_trees": dict(sorted(Counter(t["terms"] for t in trees).items())),
        "terms_expansions": dict(sorted(Counter(e["terms"] for e in expansions.values()).items())),
        "module_multiplicities": dict(multiplicities),
        "seen_calls": sorted(seen_calls),
        "exact_calls_without_trees": sorted(exact_calls - {t["call"] for t in trees}),
    }


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("testcase/xiangshan"))
    parser.add_argument("--fir", type=Path, default=Path("build/xs/rtl-aggr/rtl/SimTop.fir"))
    parser.add_argument("--output", type=Path, default=Path("ptmp/mux1h-census"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    calls, stats = source_census(args.root)
    write_csv(args.output / "source-calls.csv", calls)
    stats["calls_by_component"] = dict(sorted(Counter(c["component"] for c in calls).items()))
    stats["calls_all_sources"] = len(calls)
    stats["calls_build_main_sources"] = sum(c["component"] in MAIN_ROOTS for c in calls)
    print(json.dumps({"source": stats}), flush=True)
    trees, expansions, fir_stats = fir_census(args.fir, calls, args.root)
    write_csv(args.output / "fir-trees.csv", trees)
    write_csv(args.output / "fir-expansions.csv", expansions)
    summary = {"source": stats, "fir": fir_stats}
    by_id = {call["id"]: call for call in calls}
    fir_stats["annotated_calls_by_component"] = dict(Counter(
        by_id[call]["component"] for call in fir_stats["seen_calls"]))
    fir_stats["calls_by_component"] = dict(Counter(
        by_id[call]["component"] for call in {t["call"] for t in trees}))
    fir_stats["calls_with_long_trees"] = len({t["call"] for t in trees if t["terms"] >= 16})
    fir_stats["calls_with_16_64_trees"] = len({t["call"] for t in trees if 16 <= t["terms"] <= 64})
    fir_stats["calls_with_long_trees_list"] = sorted({t["call"] for t in trees if t["terms"] >= 16})
    fir_stats["top_source_expansions"] = Counter(e["call"] for e in expansions).most_common(20)
    call_rows = []
    for call in calls:
        selected = [e for e in expansions if e["call"] == call["id"]]
        call_rows.append({
            **call, "fir_expansions": len(selected),
            "fir_fields": sum(e["fields"] for e in selected),
            "fir_terms": " ".join(str(n) for n in sorted({e["terms"] for e in selected})),
            "fir_expansions_ge16": sum(e["terms"] >= 16 for e in selected),
        })
    write_csv(args.output / "call-coverage.csv", call_rows)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"fir": {k: v for k, v in fir_stats.items()
                             if k not in ("seen_calls", "module_multiplicities")}}), flush=True)


if __name__ == "__main__":
    main()
