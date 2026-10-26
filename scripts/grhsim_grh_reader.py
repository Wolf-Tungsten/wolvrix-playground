"""Read-only helpers for diagnostics over ordinary GRH JSON snapshots."""

from collections import Counter, defaultdict
import math


STATE_KINDS = {"kRegister", "kLatch"}
READ_KINDS = {"kRegisterReadPort", "kRegisterReadArrayPort", "kLatchReadPort"}
WRITE_KINDS = {"grhsim.write", "grhsim.writeMask", "grhsim.writeArray",
               "grhsim.writeArrayMask", "grhsim.fill", "grhsim.latchWrite"}


def graph_snapshot(model, top=None):
    """Select one graph; symbols remain scoped to this snapshot and graph."""
    if "graphs" not in model:
        if "ops" in model and "vals" in model and "symbol" in model:
            if top is not None and model["symbol"] != top:
                raise ValueError("selected GRH graph does not match top")
            return model
        raise ValueError("expected an ordinary GRH design or graph snapshot")
    if top is None:
        tops = model.get("tops", [])
        if len(tops) != 1:
            raise ValueError("ordinary GRH diagnostics require an explicit top or exactly one design top")
        top = tops[0]
    graphs = [graph for graph in model["graphs"] if graph.get("symbol") == top]
    if len(graphs) != 1:
        raise ValueError(f"expected exactly one GRH graph named {top!r}")
    return graphs[0]


def attribute(record, name, default=None):
    value = record.get("attrs", {}).get(name)
    return default if value is None else value.get("vs", value.get("v"))


def declared_symbols(model, top=None):
    graph = graph_snapshot(model, top)
    names = graph.get("declaredSymbols")
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("ordinary GRH graph lacks a textual declaredSymbols list")
    return set(names)


def logical_type(record, declaration=False):
    """Full type, with total bit width (not width multiplied by shape)."""
    if declaration:
        return (attribute(record, "valueType", "logic"), attribute(record, "width"),
                attribute(record, "isSigned", False), attribute(record, "domain", "4state"),
                tuple(attribute(record, "shape", [])))
    return (record.get("type", "logic"), record["w"], record.get("sgn", False),
            record.get("domain", "4state"), tuple(record.get("shape", [])))


class GraphReader:
    """Indexes of native snapshot records, scoped to one graph and snapshot.

    No IDs or operations are invented, rewritten, scheduled, or made executable.
    In particular, ports remain values and edge histories remain detector attrs.
    """

    def __init__(self, model, top=None):
        self.graph = graph_snapshot(model, top)
        self.declared = declared_symbols(self.graph)
        self.ops = self._index(self.graph["ops"], "operation")
        self.values = self._index(self.graph["vals"], "value")
        self.states = {name: op for name, op in self.ops.items() if op["kind"] in STATE_KINDS}
        self.inputs = {}
        for port in self.graph.get("ports", {}).get("in", []):
            if port["val"] not in self.values:
                raise ValueError(f"input port references missing value {port['val']!r}")
            self.inputs.setdefault(port["val"], []).append(port["name"])
        self.producer, self.writes = {}, defaultdict(list)
        for name, op in self.ops.items():
            for value in op["in"] + op["out"]:
                if value not in self.values:
                    raise ValueError(f"{name!r} references missing value {value!r}")
            for value in op["out"]:
                if value in self.producer or value in self.inputs:
                    raise ValueError(f"duplicate value producer for {value!r}")
                self.producer[value] = name
            if op["kind"] in READ_KINDS | WRITE_KINDS:
                target = self.target(op)
                if target not in self.states:
                    raise ValueError(f"{name!r} references missing state {target!r}")
                if op["kind"] in WRITE_KINDS:
                    self.writes[target].append(name)
        for value, record in self.values.items():
            if record.get("def") != self.producer.get(value):
                raise ValueError(f"inconsistent producer for {value!r}")
            # GRH may retain unreferenced value symbols after rewrites. Keep
            # these records; a missing producer is an error only if traversed.

    @staticmethod
    def _index(rows, label):
        result = {}
        for row in rows:
            name = row["sym"]
            if not isinstance(name, str) or not name or name in result:
                raise ValueError(f"duplicate or invalid {label} symbol {name!r}")
            result[name] = row
        return result

    @staticmethod
    def target(op):
        return attribute(op, "latchSymbol" if "Latch" in op["kind"] or
                         op["kind"] == "grhsim.latchWrite" else "regSymbol")

    def cone(self, roots):
        """Return native operation symbols, stopping at state reads and ports.

        An indexed read is an opaque boundary: its address is not a new state
        identity. Its address dependencies remain available in the raw record.
        """
        seen, pending = set(), list(roots)
        while pending:
            value = pending.pop()
            if value in self.inputs:
                continue
            if value not in self.values or value not in self.producer:
                raise ValueError(f"missing value producer for {value!r}")
            name = self.producer[value]
            if name in seen:
                continue
            seen.add(name)
            op = self.ops[name]
            if op["kind"] not in READ_KINDS:
                pending.extend(op["in"])
        return seen

    def state_census(self):
        registers, arrays = {}, {}
        for name, state in self.states.items():
            typ = logical_type(state, declaration=True)
            if typ[4]:
                if (typ[1] is None or any(not isinstance(size, int) or size <= 0 for size in typ[4])
                        or typ[1] % math.prod(typ[4])):
                    raise ValueError(f"invalid total width/shape for state {name!r}")
                arrays[name] = {"type": typ[0], "width": typ[1], "shape": list(typ[4]),
                                "element_width": typ[1] // math.prod(typ[4])}
            else:
                registers[name] = {"symbol": name, "width": typ[1], "type": typ[0],
                                   "declared": name in self.declared}
        summary = {"schema": "grh", "graph": self.graph["symbol"],
                   "ops": len(self.ops), "values": len(self.values),
                   "kinds": dict(Counter(op["kind"] for op in self.ops.values())),
                   "states": len(self.states), "register_states": len(registers),
                   "register_bits": sum(row["width"] for row in registers.values()),
                   "array_states": len(arrays), "array_storage_bits": sum(row["width"] for row in arrays.values()),
                   "event_states": 0,
                   "edge_detectors": sum(op["kind"] == "grhsim.edge-detect" for op in self.ops.values()),
                   "declared_registers": sum(row["declared"] for row in registers.values()),
                   "declared_register_bits": sum(row["width"] for row in registers.values() if row["declared"])}
        return summary, registers, arrays


def main():
    import argparse
    import hashlib
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--top")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "ptmp"
    if not args.report.resolve().is_relative_to(root):
        parser.error("report must be under repository ptmp")
    raw = args.model.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    model = json.loads(raw)
    del raw
    reader = GraphReader(model, args.top)
    census, _registers, arrays = reader.state_census()
    report = {"input_sha256": digest, "census": census, "arrays": arrays,
              "limitations": "Read-only static diagnostics; no executable IR or dynamic counter mapping."}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(census, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
