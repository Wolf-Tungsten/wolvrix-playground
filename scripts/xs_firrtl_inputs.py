#!/usr/bin/env python3
"""Describe Chisel FIRRTL and explicit SV resources for native mixed ingestion."""

import argparse
import json
from pathlib import Path


def validate_firrtl(firrtl):
    with firrtl.open(encoding="utf-8") as stream:
        if not stream.readline().startswith("FIRRTL version "):
            raise ValueError(f"not a versioned FIRRTL input: {firrtl}")
        circuit = stream.readline().split()
    if len(circuit) < 3 or circuit[0] != "circuit" or not circuit[2].startswith(":"):
        raise ValueError(f"invalid FIRRTL circuit header: {firrtl}")


def create_manifest(firrtl, *, top, sv_sources=(), include_dirs=(), defines=(),
                    resource_roots=(), annotation_files=(), init_policy="unknown",
                    invalid_policy="unknown", enabled_layers=(), node_annotations=True,
                    lower_threads=1):
    if isinstance(lower_threads, bool) or not isinstance(lower_threads, int) or lower_threads < 1:
        raise ValueError("lower_threads must be a positive integer")
    firrtl = Path(firrtl).resolve()
    validate_firrtl(firrtl)
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
                               "annotation_files": annotations, "enabled_layers": list(enabled_layers),
                               "lower_threads": lower_threads}}


def normalize_manifest(path, *, top, firrtl=None):
    """Preserve a prepared ingest request, resolving paths before publication."""
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"schema", "input_root", "tops", "sources", "slang_args",
               "firrtl_options", "external_bindings"}
    if not isinstance(manifest, dict) or set(manifest) - allowed:
        raise ValueError("invalid mixed sources manifest fields")
    if manifest.get("schema") != "wolvrix.xs.firrtl-inputs.v1":
        raise ValueError("unsupported mixed sources manifest schema")
    if manifest.setdefault("tops", [top]) != [top]:
        raise ValueError("mixed sources manifest top differs from selected top")
    root = Path(manifest.get("input_root", "."))
    root = (root if root.is_absolute() else path.parent / root).resolve()
    manifest["input_root"] = str(root)

    def resolve(name):
        if not isinstance(name, str):
            raise ValueError("mixed sources manifest paths must be strings")
        value = Path(name)
        return (value if value.is_absolute() else root / value).resolve()

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("mixed sources manifest requires a FIRRTL source")
    seen, firrtl_sources = set(), []
    for source in sources:
        if not isinstance(source, dict) or source.get("language") not in ("firrtl", "sv"):
            raise ValueError("invalid mixed source language")
        source_path = resolve(source.get("path"))
        if not source_path.is_file():
            raise ValueError(f"mixed input not found: {source_path}")
        if source_path in seen:
            raise ValueError(f"duplicate input: {source_path}")
        seen.add(source_path)
        source["path"] = str(source_path)
        if source["language"] == "firrtl":
            validate_firrtl(source_path)
            firrtl_sources.append(source_path)
    if len(firrtl_sources) != 1:
        raise ValueError("XiangShan workflow requires exactly one FIRRTL source")
    if firrtl is not None and firrtl_sources != [Path(firrtl).resolve()]:
        raise ValueError("mixed sources manifest FIRRTL source differs from selected input")

    options = manifest.setdefault("firrtl_options", {})
    if not isinstance(options, dict):
        raise ValueError("firrtl_options must be an object")
    for name in ("init_policy", "invalid_policy"):
        if options.get(name, "unknown") not in ("unknown", "zero"):
            raise ValueError(f"{name} must be unknown or zero")
    if "lower_threads" in options:
        threads = options["lower_threads"]
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise ValueError("lower_threads must be a positive integer")
    if "node_annotations" in options and not isinstance(options["node_annotations"], bool):
        raise ValueError("node_annotations must be a boolean")
    for name in ("resource_roots", "annotation_files"):
        if name not in options:
            continue
        if not isinstance(options[name], list):
            raise ValueError(f"{name} must be a list")
        options[name] = [str(resolve(item)) for item in options[name]]
        if name == "annotation_files":
            for item in options[name]:
                if not Path(item).is_file():
                    raise ValueError(f"annotation file not found: {item}")
    slang_args = manifest.get("slang_args", [])
    if not isinstance(slang_args, list) or not all(isinstance(arg, str) for arg in slang_args):
        raise ValueError("slang_args must be a list of strings")
    for index, arg in enumerate(slang_args):
        if arg == "-I":
            if index + 1 == len(slang_args):
                raise ValueError("-I requires an include directory")
            slang_args[index + 1] = str(resolve(slang_args[index + 1]))
        elif arg.startswith("-I"):
            slang_args[index] = "-I" + str(resolve(arg[2:]))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path)
    parser.add_argument("--sources-manifest", type=Path,
                        help="prepared ingest request; its options replace generated defaults")
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
    parser.add_argument("--lower-threads", type=int, default=1,
                        help="number of private FIRRTL lowerers (default: 1)")
    args = parser.parse_args()
    if args.sources_manifest:
        manifest = normalize_manifest(args.sources_manifest, top=args.top, firrtl=args.firrtl)
    elif args.firrtl:
        manifest = create_manifest(args.firrtl, top=args.top, sv_sources=args.sv_source,
            include_dirs=args.include_dir, defines=args.define, resource_roots=args.resource_root,
            annotation_files=args.annotation_file, init_policy=args.init_policy, invalid_policy=args.invalid_policy,
            enabled_layers=args.enabled_layer, node_annotations=args.node_annotations == "on",
            lower_threads=args.lower_threads)
    else:
        parser.error("--firrtl or --sources-manifest is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"FIRRTL mixed inputs: {args.output} ({len(manifest['sources'])} explicit sources)")


if __name__ == "__main__":
    main()
