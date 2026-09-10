"""Compare emitted history storage addresses and task source; never execute models."""

import collections
import hashlib
from pathlib import Path
import re
import sys


def inspect(directory):
    directory = Path(directory)
    initializers = collections.Counter()
    tasks = {}
    total_bytes = 0
    scalar_calls = batches = snapshots = snapshot_uses = snapshot_tasks = 0
    for path in sorted(directory.glob("*.cpp")):
        data = path.read_bytes()
        total_bytes += len(data)
        if "_init_" in path.name:
            initializers.update(re.findall(rb"cpu_at<bool>\(cpu_objects.get\(\),(\d+)\)=", data))
        if "_task_" in path.name:
            tasks[path.name] = (hashlib.sha256(data).hexdigest(), len(data))
            scalar_calls += data.count(b"cpu_write_scalar<bool>(")
            batches += data.count(b"// cpu_history_batch states=")
            cached = re.findall(rb"const bool (cpu_edge_snapshot_\d+)=.*?; // cpu_edge_snapshot uses=(\d+)\n", data)
            if len(cached) != data.count(b"const bool cpu_edge_snapshot_"):
                raise ValueError(f"unrecognized edge snapshot declaration in {path}")
            for name, expected in cached:
                uses = len(re.findall(rb"if\(\(?" + re.escape(name) + rb"\)", data))
                if uses != int(expected) or uses < 2:
                    raise ValueError(f"edge snapshot use count differs in {path}: {name!r}")
                snapshot_uses += uses
            snapshots += len(cached)
            snapshot_tasks += bool(cached)
    if not tasks or not initializers:
        raise ValueError("missing generated tasks or bool initializers")
    return initializers, tasks, total_bytes, scalar_calls, batches, snapshots, snapshot_uses, snapshot_tasks


def main():
    before, after = map(inspect, sys.argv[1:])
    if before[1].keys() != after[1].keys():
        raise ValueError("task inventories differ")
    if sum(before[0].values()) != sum(after[0].values()):
        raise ValueError("bool initializer counts differ")
    for label, data in zip(("baseline", "candidate"), (before, after)):
        print(f"{label}: bool_initializers={sum(data[0].values())} "
              f"unique_bool_addresses={len(data[0])} cpp_bytes={data[2]} "
              f"bool_stage_sites={data[3]} history_batch_sites={data[4]} "
              f"edge_snapshots={data[5]} edge_snapshot_uses={data[6]} edge_snapshot_tasks={data[7]}")
    changed = [name for name in before[1] if before[1][name] != after[1][name]]
    print(f"tasks={len(before[1])} changed_tasks={len(changed)} "
          f"eliminated_unique_bool_addresses={len(before[0]) - len(after[0])}")
    print(f"changed_task_bytes_before={sum(before[1][n][1] for n in changed)} "
          f"changed_task_bytes_after={sum(after[1][n][1] for n in changed)}")
    print("Counts are static source observations, not runtime work or live allocation size.")


if __name__ == "__main__":
    main()
