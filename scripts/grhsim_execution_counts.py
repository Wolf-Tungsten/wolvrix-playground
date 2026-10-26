"""Bind native emitted operation visits to their exact GRH snapshot and sites.

Counts describe logical execution of emitted sites, not instructions or time.
Effect counts are separate from guarded operation visits. Writer sample/commit
counts are visits, not successful state changes. Initialization is included;
init resets the counters. No legacy mapping IDs or inferred cycles are used.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from grhsim_grh_reader import GraphReader, READ_KINDS, WRITE_KINDS, attribute


SCHEMA = "grhsim-execution-counts.v1"
MAX_COUNT = (1 << 64) - 1
CATEGORIES = {"operation", "effect", "writer-sample", "writer-commit", "history-write"}
NON_COMPUTE = READ_KINDS | WRITE_KINDS | {
    "kConstant", "kRegister", "kLatch", "kDpicImport", "grhsim.edge-detect",
    "grhsim.system-task", "grhsim.system-function", "grhsim.dpi-call", "grhsim.history-write"}


def binding(snapshot, sites, program_files=None):
    """Emitter's non-cryptographic graph/site tag; reports also retain SHA256."""
    value = 14695981039346656037
    program = [raw for name, contents in sorted((program_files or {}).items())
               for raw in (name.encode("utf-8"), contents)]
    for data in [snapshot] + [str(len(raw)).encode() + b":" + raw
                              for site in sites for raw in
                              (site[key].encode("utf-8") for key in ("operation", "category", "function"))] + [
                                  str(len(raw)).encode() + b":" + raw for raw in program]:
        for byte in data:
            value = ((value ^ byte) * 1099511628211) & MAX_COUNT
    return str(value)


def read_counts(path, tag, size):
    lines = Path(path).read_text().splitlines()
    if len(lines) != size + 4 or lines[0] != f"{SCHEMA}\t{tag}":
        raise ValueError("execution counter schema/binding/length mismatch")
    def number(text):
        if not re.fullmatch(r"0|[1-9][0-9]*", text) or int(text) > MAX_COUNT:
            raise ValueError("invalid execution counter integer")
        return int(text)
    if not lines[1].startswith("evals\t"):
        raise ValueError("missing execution eval count")
    evals = number(lines[1][6:])
    if not evals:
        raise ValueError("execution pricing requires at least one eval")
    counts = []
    for index, line in enumerate(lines[2:2 + size]):
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] != str(index):
            raise ValueError("missing, duplicate or reordered execution site")
        counts.append(number(fields[1]))
    total = sum(counts)
    if total > MAX_COUNT or lines[-2] != f"total\t{total}" or lines[-1] != f"end\t{size}":
        raise ValueError("execution counter total/end closure failed")
    return counts, evals


class NativeExecutionCounts:
    def __init__(self, reader, model_dir, first, second):
        self.reader = reader if isinstance(reader, GraphReader) else GraphReader(reader)
        self.directory = Path(model_dir)
        manifest_path = self.directory / "manifest.json"
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        metadata = manifest.get("execution_counters", {})
        if metadata.get("schema") != SCHEMA or metadata.get("graph_file") != "execution-counter-graph.json":
            raise ValueError("model lacks native execution counter metadata")
        snapshot_path = self.directory / metadata["graph_file"]
        snapshot = snapshot_path.read_bytes()
        if GraphReader(json.loads(snapshot)).graph != self.reader.graph:
            raise ValueError("execution counter snapshot differs from the selected GRH graph")
        self.sites = metadata.get("sites")
        if not isinstance(self.sites, list):
            raise ValueError("invalid native execution sites")
        primary, effects = set(), set()
        for site in self.sites:
            if set(site) != {"operation", "category", "function"} or any(
                    not isinstance(value, str) or not value for value in site.values()):
                raise ValueError("invalid native execution site record")
            name, category = site["operation"], site["category"]
            if name not in self.reader.ops or category not in CATEGORIES:
                raise ValueError("unknown native execution operation/category")
            kind = self.reader.ops[name]["kind"]
            if ((category.startswith("writer-") and kind not in WRITE_KINDS) or
                    (category == "history-write" and kind != "grhsim.history-write") or
                    (category == "effect" and kind not in
                     {"grhsim.system-task", "grhsim.system-function", "grhsim.dpi-call"})):
                raise ValueError("execution category disagrees with native operation")
            if category == "effect":
                effects.add(name)
            elif category != "writer-commit":
                primary.add(name)
        elided = metadata.get("elided_operations", [])
        if not isinstance(elided, list) or len(elided) != len(set(elided)) or any(
                name not in self.reader.ops or self.reader.ops[name]["kind"] != "kAssign" for name in elided):
            raise ValueError("invalid native view elisions")
        executable = {name for name, op in self.reader.ops.items() if attribute(op, "grhsim.partition")}
        if primary & set(elided) or primary | set(elided) != executable or effects - primary:
            raise ValueError("native executable operation coverage failed")
        tag = metadata.get("binding_fnv1a64")
        if not isinstance(tag, str) or not re.fullmatch(r"[0-9]+", tag):
            raise ValueError("invalid native execution binding")
        source_sites = Counter()
        sources = manifest.get("sources", [])
        if not sources or len(sources) != len(set(sources)):
            raise ValueError("missing/duplicate emitted counter source")
        source_hashes = {}
        files = metadata.get("binding_files", [])
        if not isinstance(files, list) or files != sorted(set(files)) or set(sources) - set(files) or len(files) != len(sources) + 1:
            raise ValueError("invalid execution binding file list")
        program, replacements = {}, 0
        marker = SCHEMA.encode() + b"\\t" + tag.encode() + b"\\n"
        placeholder = SCHEMA.encode() + b"\\t__GRHSIM_EXECUTION_BINDING__\\n"
        for source in files:
            if Path(source).name != source or not source.endswith((".cpp", ".hpp")):
                raise ValueError("invalid emitted counter source path")
            raw = (self.directory / source).read_bytes()
            source_hashes[source] = hashlib.sha256(raw).hexdigest()
            replacements += raw.count(marker)
            program[source] = raw.replace(marker, placeholder)
            if source in sources:
                source_sites.update(map(int, re.findall(rb"\+\+opExecCounts_\[(\d+)\];", raw)))
        if source_sites != Counter({index: 1 for index in range(len(self.sites))}):
            raise ValueError("emitted execution counter site closure failed")
        if replacements != 1 or tag != binding(snapshot, self.sites, program):
            raise ValueError("native execution metadata/source binding mismatch")
        if Path(first).resolve() == Path(second).resolve():
            raise ValueError("two independent execution reports are required")
        counts, self.evals = read_counts(first, tag, len(self.sites))
        if (counts, self.evals) != read_counts(second, tag, len(self.sites)):
            raise ValueError("independent native execution counts differ")
        self.counts = counts
        self.visits = {category: Counter() for category in CATEGORIES}
        for site, count in zip(self.sites, counts):
            self.visits[site["category"]][site["operation"]] += count
        self.identity = {"snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
                         "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                         "source_sha256": source_hashes,
                         "run_sha256": [hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                        for path in (first, second)]}
        self.elided = set(elided)

    def compute(self, names):
        names = set(names)
        if names - self.reader.ops.keys():
            raise ValueError("cannot price foreign native operation symbols")
        return {name for name in names if self.reader.ops[name]["kind"] not in NON_COMPUTE}

    def price(self, names):
        return sum(self.visits["operation"][name] for name in self.compute(names))

    def summary(self):
        owners, kinds = Counter(), Counter()
        for name, count in self.visits["operation"].items():
            op = self.reader.ops[name]
            owner = attribute(op, "grhsim.partition")
            owners["/".join(owner)] += count
            kinds[op["kind"]] += count
        return {"available": True, "schema": SCHEMA, "evals": self.evals,
                "sites": len(self.sites), "elided_operations": len(self.elided),
                "category_visits": {key: sum(value.values()) for key, value in sorted(self.visits.items())},
                "compute_operation_visits": self.price(self.reader.ops),
                "operation_visits_by_owner": dict(sorted(owners.items())),
                "operation_visits_by_kind": dict(sorted(kinds.items())),
                "independent_runs_equal": True, "source_site_closure": True,
                "executable_coverage": True, "identity": self.identity,
                "caliber": "Logical emitted site visits, including init, normalized by eval calls. "
                           "Effects are actual guarded calls; writer visits are not successful writes. "
                           "Not instruction counts, time, legacy mapping counters or inferred cycles."}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--run1", type=Path, required=True)
    parser.add_argument("--run2", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "ptmp"
    if not args.report.resolve().is_relative_to(root):
        parser.error("report must be under repository ptmp")
    path = args.graph or args.model_dir / "execution-counter-graph.json"
    counts = NativeExecutionCounts(json.loads(path.read_bytes()), args.model_dir, args.run1, args.run2)
    report = counts.summary()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("evals", "sites", "category_visits")}, sort_keys=True))


if __name__ == "__main__":
    main()
