#!/usr/bin/env python3
"""Run frozen C++ stimuli on ordinary-GRH models through the project Make target."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from remove_grhsim_ir_observations import FIXTURES, digest, observations, task_records


ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    prepared = json.loads((args.frozen / "prepared.json").read_text())
    manifest = json.loads((args.frozen / "manifest.json").read_text())
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    metadata = {}
    for name, (stem, *_types) in FIXTURES.items():
        old = args.frozen / name
        expected = manifest["fixtures"][name]
        if digest(old / "observations.jsonl") != expected["sha256"]:
            raise RuntimeError("Frozen observations changed: " + name)
        if digest(old / "driver.cpp") != prepared["fixtures"][name]["instrumented_driver_sha256"]:
            raise RuntimeError("Frozen stimulus changed: " + name)
        target = args.output / name
        shutil.copytree(args.models / name, target)
        source = (old / "driver.cpp").read_text()
        source = source.replace(f'"grhsim_phase_{stem}.hpp"', '"grhsim_top.hpp"')
        source = source.replace("GrhSIM_phase_" + stem, "GrhSIM_top")
        (target / "driver.cpp").write_text(source)
        # Instrument copies only. This fixture has a single 32-bit random
        # function and no random initialization, so every RNG call is a sample.
        if name.startswith("random_function"):
            patched = 0
            for path in sorted((target / "model").glob("*.cpp")):
                text = path.read_text()
                pattern = r"(std::uint64_t GrhSIM_top::random_next\([^\n]*\)\n\{\n)(.*?)(^\})"
                def instrument(match):
                    nonlocal patched
                    body, count = re.subn(r"return ([^;]+);", r"const auto observed = \1;\n    grhsim_observe_random(32, static_cast<std::uint32_t>(observed));\n    return observed;", match[2])
                    patched += count
                    return "void grhsim_observe_random(std::size_t, std::uint64_t);\n" + match[1] + body + match[3]
                text = re.sub(pattern, instrument, text, flags=re.MULTILINE | re.DOTALL)
                path.write_text(text)
            if patched != 1:
                raise RuntimeError("Cannot instrument generated random helper: " + name)
        metadata[name] = {"driver_sha256": digest(target / "driver.cpp"),
                          "frozen_observations_sha256": expected["sha256"],
                          "graph_sha256": digest(target / "graph.json")}
    (args.output / "prepared.json").write_text(json.dumps(metadata, indent=2) + "\n")


def canonical(records):
    for record in records:
        for category in ("outputs", "states"):
            record[category] = {name: int(value, 16) for name, value in record[category].items()}
    return records


def approved_difference(name, difference, policy):
    """Classify only the two explicitly approved, fixture-bound differences."""
    if policy not in ("single-original-call", "single-original-call-source-order") or difference["category"] != "effects":
        return None
    old, new = difference["old"], difference["new"]
    if name == "dpi_bit_abi" and len(new) == 1 and old == new * 2 and new[0].get("kind") == "dpi" and new[0].get("function") == "cpu_test_bit_abi":
        return "2026-10-25 user decision: one original DPI call with held cross-region results; remove the old Output duplicate"
    if (policy == "single-original-call-source-order" and name in ("dpi_smoke", "dpi_smoke_tu") and
            len(old) == 2 and all(effect.get("kind") == "dpi" for effect in old) and
            [effect.get("function") for effect in old] == ["cpu_test_dbl", "cpu_test_inc"] and new == old[::-1]):
        return "2026-10-25 user decision: preserve original independent call order inc then dbl; record the old schedule's dbl then inc"
    return None


def collect(args):
    prepared = json.loads((args.frozen / "prepared.json").read_text())
    summary = {"schema": "wolvrix.remove-grhsim-ir.comparison.v2", "fixtures": {}, "equal": True,
               "effect_policy": args.effect_policy, "accepted": True}
    for name in FIXTURES:
        directory = args.output / name
        with (directory / "driver.stdout").open("w") as stdout, (directory / "driver.stderr").open("w") as stderr:
            subprocess.run([str(directory / "driver")], cwd=directory, stdout=stdout, stderr=stderr, check=True)
        task_file = directory / "task_output.txt"
        tasks = task_records((task_file if task_file.exists() else directory / "driver.stdout").read_text())
        raw = (directory / "observations.txt").read_text()
        raw = re.sub(r"^output/([^=]+)=", r"\1=", raw, flags=re.MULTILINE)
        raw = re.sub(r"^state/([^=]+)=", r"smallSinkStore.\1=", raw, flags=re.MULTILINE)
        current = canonical(observations(raw, prepared["fixtures"][name], tasks))
        old = canonical([json.loads(line) for line in (args.frozen / name / "observations.jsonl").read_text().splitlines()])
        (directory / "observations.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in current))
        differences = []
        for expected, actual in zip(old, current, strict=True):
            for category in ("inputs", "outputs", "states", "effects"):
                if expected[category] != actual[category]:
                    differences.append({"epoch": expected["epoch"], "step": expected["step"], "category": category,
                                        "old": expected[category], "new": actual[category]})
        approved, unapproved = [], []
        for difference in differences:
            reason = approved_difference(name, difference, args.effect_policy)
            (approved if reason else unapproved).append({**difference, "decision": reason} if reason else difference)
        summary["fixtures"][name] = {"records": len(current), "equal": not differences, "differences": differences,
                                     "approved_differences": approved, "unapproved_differences": unapproved,
                                     "accepted": not unapproved}
        summary["equal"] &= not differences
        summary["accepted"] &= not unapproved
    (args.output / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    for name, entry in summary["fixtures"].items():
        print(f"{name}: {entry['records']} records, {len(entry['differences'])} raw differences, "
              f"{len(entry['approved_differences'])} approved, {len(entry['unapproved_differences'])} unresolved", flush=True)
    if not summary["accepted"]:
        raise SystemExit("Frozen/new observations have unresolved differences; see " + str(args.output / "comparison.json"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "collect"))
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--effect-policy", choices=("strict", "single-original-call", "single-original-call-source-order"), default="strict")
    args = parser.parse_args()
    args.frozen, args.models, args.output = (path.resolve() for path in (args.frozen, args.models, args.output))
    if not args.output.is_relative_to(ROOT / "ptmp/remove-grhsim-ir") or args.output.is_relative_to(args.frozen):
        parser.error("output must be isolated under ptmp/remove-grhsim-ir")
    if args.mode == "prepare":
        prepare(args)
    else:
        collect(args)


if __name__ == "__main__":
    main()
