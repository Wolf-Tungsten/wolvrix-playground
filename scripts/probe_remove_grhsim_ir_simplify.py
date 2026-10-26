"""Report graph changes per GrhSIM simplify round on an isolated checkpoint."""

import argparse
import collections
import json
from pathlib import Path

import wolvrix

from grhsim_flow import checked, run_pass, store_checkpoint


def snapshot(session, path, top):
    store_checkpoint(session, path, design="design.main", top=top)
    graph = json.loads(path.read_bytes())["graphs"][0]
    return {op["sym"]: op for op in graph["ops"]}, {v["sym"]: v for v in graph["vals"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=4)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "ptmp/remove-grhsim-ir"
    if not args.output.resolve().is_relative_to(root) or args.rounds < 1:
        parser.error("output must be under ptmp/remove-grhsim-ir; rounds must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    report = []
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        checked(session.read_json_file(str(args.model.resolve()), out_design="design.main"), "load probe")
        metadata = session.graph_metadata(design="design.main")
        top = metadata["symbol"]
        if "grhsim.stage" not in metadata["metadata"]:
            run_pass(session, "grh-to-grhsim", design="design.main", top=top, logic_domain="2state")
        before, before_values = snapshot(session, args.output / "before.json", top)
        for index in range(args.rounds):
            run_pass(session, "grhsim-simplify", design="design.main", top=top, max_rounds=1)
            after, after_values = snapshot(session, args.output / f"round-{index}.json", top)
            counts = collections.Counter()
            examples = {}
            for symbol in before.keys() | after.keys():
                old, new = before.get(symbol), after.get(symbol)
                if old == new:
                    continue
                key = (old or {}).get("kind", "new") + " -> " + (new or {}).get("kind", "deleted")
                counts[key] += 1
                if len(examples.setdefault(key, [])) < 3:
                    examples[key].append({"before": old, "after": new})
            row = {"round": index, "changes": dict(counts), "examples": examples,
                   "value_changes": sum(before_values.get(s) != after_values.get(s)
                                        for s in before_values.keys() | after_values.keys())}
            report.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "examples"}), flush=True)
            before, before_values = after, after_values
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
