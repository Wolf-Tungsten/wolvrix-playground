#!/usr/bin/env python3
"""Describe Chisel FIRRTL and explicit SV resources for native mixed ingestion."""

import argparse
import json
from pathlib import Path


def create_manifest(firrtl, *, top, sv_sources=(), include_dirs=(), defines=(),
                    resource_roots=(), annotation_files=(), init_policy="unknown",
                    invalid_policy="unknown", enabled_layers=(), node_annotations=True):
    firrtl = Path(firrtl).resolve()
    with firrtl.open(encoding="utf-8") as stream:
        if not stream.readline().startswith("FIRRTL version "):
            raise ValueError(f"not a versioned FIRRTL input: {firrtl}")
        circuit = stream.readline().split()
    if len(circuit) < 3 or circuit[0] != "circuit" or not circuit[2].startswith(":"):
        raise ValueError(f"invalid FIRRTL circuit header: {firrtl}")
    # A component test can select an internal module of the original circuit.
    # Native mixed ingestion validates that the requested top exists.
    sources = [{"language": "firrtl", "path": str(firrtl), "unit": "xiangshan"}]
    seen = {firrtl}
    for name in sv_sources:
        path = Path(name).resolve()
        if not path.is_file():
            raise ValueError(f"SV resource not found: {path}")
        if path in seen:
            raise ValueError(f"duplicate input: {path}")
        seen.add(path)
        sources.append({"language": "sv", "path": str(path), "unit": "helpers"})
    roots = [str(Path(root).resolve()) for root in resource_roots]
    annotations = [str(Path(name).resolve()) for name in annotation_files]
    for name in annotations:
        if not Path(name).is_file():
            raise ValueError(f"annotation file not found: {name}")
    return {"schema": "wolvrix.xs.firrtl-inputs.v1",
            "input_root": str(firrtl.parent), "tops": [top], "sources": sources,
            "slang_args": [arg for directory in include_dirs for arg in ("-I", str(Path(directory).resolve()))]
                          + [arg for define in defines for arg in ("-D", define)],
            "firrtl_options": {"node_annotations": node_annotations, "init_policy": init_policy,
                               "invalid_policy": invalid_policy, "resource_roots": roots,
                               "annotation_files": annotations, "enabled_layers": list(enabled_layers)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--top", default="SimTop")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sv-source", action="append", default=[])
    parser.add_argument("--include-dir", action="append", default=[])
    parser.add_argument("--define", action="append", default=[])
    parser.add_argument("--resource-root", action="append", default=[])
    parser.add_argument("--annotation-file", action="append", default=[])
    parser.add_argument("--enabled-layer", action="append", default=[])
    parser.add_argument("--init-policy", choices=["unknown", "zero"], default="unknown")
    parser.add_argument("--invalid-policy", choices=["unknown", "zero"], default="unknown")
    parser.add_argument("--node-annotations", choices=["on", "off"], default="on")
    args = parser.parse_args()
    manifest = create_manifest(args.firrtl, top=args.top, sv_sources=args.sv_source,
        include_dirs=args.include_dir, defines=args.define, resource_roots=args.resource_root,
        annotation_files=args.annotation_file, init_policy=args.init_policy, invalid_policy=args.invalid_policy,
        enabled_layers=args.enabled_layer, node_annotations=args.node_annotations == "on")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"FIRRTL mixed inputs: {args.output} ({len(manifest['sources'])} explicit sources)")


if __name__ == "__main__":
    main()
