#!/usr/bin/env python3
"""Freeze the dirty source tree and existing aggregate simulation evidence (Make only)."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import time


ROOT = Path(__file__).resolve().parents[1]


def command(args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def capture(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "root": str(ROOT), "repositories": {}, "artifacts": {},
                "policy": {"comb_pack": False, "pack_bit_registers": True,
                           "functional": "old-to-new all outputs, no exclusions; effects by ordered logs",
                           "runtime_regression_percent": 3, "generation_compile_rss_percent": 5,
                           "benchmark": "same host/toolchain/trace/seed; warmup then alternating 3+3"}}
    repos = [".", "wolvrix", "testcase/hdlbits", "testcase/xiangshan", "reference/gsim"]
    with tarfile.open(output / "source.tar.gz", "w:gz") as archive:
        for name in repos:
            repo = ROOT / name
            tag = name.replace("/", "_").replace(".", "root")
            status = command(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo)
            (output / (tag + ".status")).write_text(status)
            diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=repo)
            (output / (tag + ".patch")).write_bytes(diff)
            files = command(["git", "ls-files", "-c", "-o", "--exclude-standard"], repo).splitlines()
            hashed = {}
            for relative in sorted(set(files)):
                path = repo / relative
                if not path.is_file() or path.is_symlink():
                    continue
                # Dependencies remain identified by submodule revision, not copied as task output.
                if relative.startswith(("external/", "ready-to-run/")):
                    continue
                hashed[relative] = digest(path)
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
            manifest["repositories"][name] = {
                "revision": command(["git", "rev-parse", "HEAD"], repo).strip(),
                "submodules": command(["git", "submodule", "status", "--recursive"], repo),
                "files": hashed}
    paths = [
        "Makefile", "wolvrix/build/CMakeCache.txt", "wolvrix/build/bin",
        "ptmp/xs-components-rob-array-create/candidate/emit_flat_grh.json",
        "ptmp/xs-components-rob-array-create/candidate/emit_grhsim.json",
        "ptmp/xs-components-rob-array-create/candidate/grhsim-model",
        "ptmp/xs-components-rob-array-create/candidate/bench",
        "ptmp/xs-components-rob-array-create/candidate/dump_outputs",
        "ptmp/xs-components-rob-array-create/candidate/all_outputs.bin",
        "ptmp/xs-components-rob-array-create/candidate/rtl.f",
        "ptmp/xs-components-rob-array-create/candidate/read_args.txt",
        "ptmp/xs-components-rob-array-create/candidate/grhsim_model_gen.log",
        "ptmp/xs-components-rob-array-create/inputs.json",
        "ptmp/xs-components-rob-array-create/results.json",
        "ptmp/xs-components-rob/trace/rob_trace.bin",
        "ptmp/xs-components-rob/trace/layout.json",
        "ptmp/xs-components-rob/trace/fst_output_mask.bin",
        "testcase/xs-components/rob/rtl",
        "ptmp/xs/grhsim-ir/xiangshan_flat_grh.json",
        "ptmp/xs/grhsim-ir/xiangshan_grhsim_ir.json",
        "ptmp/xs/grhsim-ir/model",
        "ptmp/xs/grhsim-ir/emu/grhsim-compile/emu",
        "ptmp/xs/grhsim-ir/xs_wolf.f",
    ]
    for relative in paths:
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError(source)
        target = output / "frozen" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "--reflink=auto", "-a", str(source), str(target)], check=True)
        entries = sorted(target.rglob("*")) if target.is_dir() else [target]
        for path in entries:
            if path.is_file():
                manifest["artifacts"][str(path.relative_to(output))] = {
                    "size": path.stat().st_size, "sha256": digest(path)}
    manifest["toolchain"] = {tool: command([tool, "--version"]).splitlines()[0]
                             for tool in ["clang", "clang++", "make", "cmake"]}
    manifest["host"] = {"uname": os.uname()._asdict() if hasattr(os.uname(), "_asdict") else list(os.uname()),
                        "cpu_affinity": sorted(os.sched_getaffinity(0)), "cpu_count": os.cpu_count()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Frozen {len(manifest['artifacts'])} artifacts in {output}", flush=True)


def replay(output):
    manifest = json.loads((output / "manifest.json").read_text())
    frozen = output / "frozen"
    runner = frozen / "ptmp/xs-components-rob-array-create/candidate/dump_outputs"
    trace = frozen / "ptmp/xs-components-rob/trace/rob_trace.bin"
    golden = frozen / "ptmp/xs-components-rob-array-create/candidate/all_outputs.bin"
    for path in [runner, trace, golden]:
        recorded = manifest["artifacts"][str(path.relative_to(output))]["sha256"]
        if digest(path) != recorded:
            raise RuntimeError(f"Frozen artifact changed: {path}")
    actual = output / "replay-all-outputs.bin"
    start = time.monotonic()
    with (output / "replay.log").open("w") as log:
        subprocess.run([str(runner), str(trace), str(actual)], stdout=log, stderr=subprocess.STDOUT, check=True)
    expected, observed = digest(golden), digest(actual)
    result = {"elapsed_seconds": time.monotonic() - start, "golden_sha256": expected,
              "actual_sha256": observed, "equal": expected == observed,
              "exclusions": 0, "observed_bytes": actual.stat().st_size}
    (output / "replay.json").write_text(json.dumps(result, indent=2) + "\n")
    if not result["equal"]:
        raise RuntimeError("Frozen ROB replay differs from the full-output golden")
    print(json.dumps(result), flush=True)


def supplement(output):
    """Freeze original XS inputs/config alongside the already immutable snapshot."""
    frozen = output / "frozen"
    paths = {
        ROOT / "ptmp/xs/grhsim-ir/wolvrix_read_args.txt",
        ROOT / "ptmp/xs/logs/xs_grhsim_20261022_090516.log",
        ROOT / "ptmp/xs/logs/xs_wolf_grhsim_20261022_125159.log",
        ROOT / "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin",
        ROOT / "testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so",
    }
    filelist = frozen / "ptmp/xs/grhsim-ir/xs_wolf.f"
    paths.update(Path(line.strip()) for line in filelist.read_text().splitlines() if line.strip())
    args = (ROOT / "ptmp/xs/grhsim-ir/wolvrix_read_args.txt").read_text().splitlines()
    for index, arg in enumerate(args):
        if arg != "-I":
            continue
        include = Path(args[index + 1])
        paths.update(path for path in include.rglob("*")
                     if path.suffix in {".sv", ".v", ".svh", ".vh"})
    records = {}
    for source in sorted(paths):
        source = source.resolve(strict=True)
        relative = source.relative_to(ROOT)
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(target) != digest(source):
                raise RuntimeError(f"Already frozen input differs: {relative}")
        else:
            subprocess.run(["cp", "--reflink=auto", "-a", str(source), str(target)], check=True)
        records[str(relative)] = {"size": target.stat().st_size, "sha256": digest(target)}
    library = frozen / "wolvrix/build/libwolvrix-lib.so"
    if not library.exists():
        raise RuntimeError("Original shared library must be frozen before the first new link")
    records["wolvrix/build/libwolvrix-lib.so"] = {"size": library.stat().st_size,
                                                   "sha256": digest(library)}
    result = {"inputs": records, "seed": 0, "xs_workload": "coremark-2-iteration.bin",
              "xs_reference_cycles": 296754, "xs_observation": "historical good trap; not a new candidate run",
              "source_snapshot": "manifest.json and source.tar.gz remain the pre-R1 source authority"}
    (output / "inputs-supplement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Frozen {len(records)} supplementary input/library records", flush=True)


def fixtures(output):
    """Run the frozen test harness with its matching old shared library."""
    frozen = output / "frozen/wolvrix/build"
    environment = dict(os.environ)
    environment["LD_LIBRARY_PATH"] = str(frozen) + ":" + environment.get("LD_LIBRARY_PATH", "")
    environment["WOLVRIX_CPU_PHASE_EMIT_TEST_OUTPUT"] = str(output / "old-fixtures")
    environment["TMPDIR"] = str(output / "fixtures-tmp")
    Path(environment["TMPDIR"]).mkdir(exist_ok=True)
    start = time.monotonic()
    with (output / "old-fixtures.log").open("w") as log:
        subprocess.run([str(frozen / "bin/grhsim-cpu-phase-emit-tests")], cwd=ROOT,
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    records = {str(path.relative_to(output)): {"size": path.stat().st_size, "sha256": digest(path)}
               for path in sorted((output / "old-fixtures").rglob("*")) if path.is_file()}
    (output / "old-fixtures.json").write_text(json.dumps({"elapsed_seconds": time.monotonic() - start,
                                                          "files": records}, indent=2) + "\n")
    print(f"Verified and froze {len(records)} fixture artifacts", flush=True)


def prepare_xs_inputs(baseline, output):
    """Bind a new full-SV flow to immutable R0 file/include inputs."""
    if output.is_relative_to(baseline):
        raise ValueError("XS candidate inputs must not modify the frozen baseline")
    supplement = json.loads((baseline / "inputs-supplement.json").read_text())
    frozen = baseline / "frozen"
    records = supplement["inputs"]
    for relative, record in records.items():
        if digest(frozen / relative) != record["sha256"]:
            raise RuntimeError("Frozen XS input changed: " + relative)
    source = frozen / "ptmp/xs/grhsim-ir"
    manifest = json.loads((baseline / "manifest.json").read_text())
    filelist = source / "xs_wolf.f"
    key = str(filelist.relative_to(baseline))
    if digest(filelist) != manifest["artifacts"][key]["sha256"]:
        raise RuntimeError("Frozen XS filelist changed")
    files = []
    for line in filelist.read_text().splitlines():
        relative = str(Path(line).relative_to(ROOT))
        if relative not in records:
            raise RuntimeError("Unbound XS source: " + relative)
        files.append(str(frozen / relative))
    read_args = (source / "wolvrix_read_args.txt").read_text().splitlines()
    for index, arg in enumerate(read_args):
        if arg == "-I":
            relative = Path(read_args[index + 1]).relative_to(ROOT)
            read_args[index + 1] = str(frozen / relative)
    output.mkdir(parents=True, exist_ok=True)
    (output / "rtl.f").write_text("\n".join(files) + "\n")
    (output / "read_args.txt").write_text("\n".join(read_args) + "\n")
    (output / "inputs.json").write_text(json.dumps({
        "scope": "full original SV generation from frozen R0 inputs; no checkpoint resume",
        "baseline_manifest_sha256": digest(baseline / "manifest.json"),
        "supplement_sha256": digest(baseline / "inputs-supplement.json"),
        "filelist_sha256": digest(output / "rtl.f"),
        "read_args_sha256": digest(output / "read_args.txt"),
        "sources": len(files)}, indent=2) + "\n")
    print(f"Prepared {len(files)} frozen original XS sources", flush=True)


def prepare_binding(baseline, output, rebuild_compiler=False):
    if output.is_relative_to(baseline):
        raise ValueError("Frozen binding build must be outside the baseline")
    manifest = json.loads((baseline / "manifest.json").read_text())
    records = manifest["repositories"]["wolvrix"]["files"]
    selected = {}
    dependencies = None
    if rebuild_compiler:
        dependencies = command(["git", "submodule", "status", "--recursive"], ROOT / "wolvrix")
        if dependencies != manifest["repositories"]["wolvrix"]["submodules"]:
            raise RuntimeError("Frozen compiler dependency revisions changed")
    with tarfile.open(baseline / "source.tar.gz", "r:gz") as archive:
        for member in archive:
            name = member.name
            prefixes = ("wolvrix/include/", "wolvrix/app/pybind/") + (("wolvrix/lib/",) if rebuild_compiler else ())
            extras = ("scripts/wolvrix_xs_grhsim_ir.py", "wolvrix/CMakeLists.txt") if rebuild_compiler else ("scripts/wolvrix_xs_grhsim_ir.py",)
            if not name.startswith(prefixes) and name not in extras:
                continue
            if not member.isfile() or ".." in Path(name).parts:
                raise ValueError("Unsafe frozen binding source: " + name)
            raw = archive.extractfile(member).read()
            expected = records.get(name.removeprefix("wolvrix/")) if name.startswith("wolvrix/") else manifest["repositories"]["."]["files"].get(name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise RuntimeError("Frozen binding source changed: " + name)
            destination = output / "source" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or destination.read_bytes() != raw:
                destination.write_bytes(raw)
            selected[name] = expected
    package = output / "python/wolvrix"
    package.mkdir(parents=True, exist_ok=True)
    shutil.copytree(output / "source/wolvrix/app/pybind/wolvrix", package, dirs_exist_ok=True)
    if rebuild_compiler:
        cmake = (output / "source/wolvrix/CMakeLists.txt").read_text()
        match = re.search(r"set\(WOLVRIX_LIB_SOURCES\s+(.*?)\n\)", cmake, re.S)
        if not match:
            raise RuntimeError("Frozen compiler source list missing")
        sources = match[1].split()
        if any(not name.startswith("lib/") or ".." in Path(name).parts or
               "wolvrix/" + name not in selected for name in sources):
            raise RuntimeError("Unbound frozen compiler source")
        (output / "compiler-sources.mk").write_text("FROZEN_COMPILER_SOURCES := " + " ".join(sources) + "\n")
        (output / "source-identity.json").write_text(json.dumps({"source_sha256": selected,
            "baseline_manifest_sha256": digest(baseline / "manifest.json"),
            "dependencies": dependencies,
            "scope": "compiler and binding rebuilt from R0 archive; not the incompatible supplementary binary"}, indent=2) + "\n")
        print(f"Prepared {len(selected)} frozen compiler sources/headers", flush=True)
        return
    library = baseline / "frozen/wolvrix/build/libwolvrix-lib.so"
    record = json.loads((baseline / "inputs-supplement.json").read_text())["inputs"]["wolvrix/build/libwolvrix-lib.so"]
    if digest(library) != record["sha256"]:
        raise RuntimeError("Frozen shared library changed")
    destination = package / library.name
    if not destination.exists() or digest(destination) != record["sha256"]:
        shutil.copy2(library, destination)
    (output / "source-identity.json").write_text(json.dumps({"source_sha256": selected,
        "frozen_library_sha256": record["sha256"],
        "scope": "R0 binding source/public headers and frozen shared library; no current GRH ABI"}, indent=2) + "\n")
    print(f"Prepared {len(selected)} frozen binding sources/headers", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["capture", "replay", "supplement", "fixtures", "xs-inputs", "binding-inputs", "compiler-inputs"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp/remove-grhsim-ir"):
        parser.error("output must be under ptmp/remove-grhsim-ir")
    if args.mode in ("xs-inputs", "binding-inputs", "compiler-inputs"):
        if args.baseline is None:
            parser.error(args.mode + " requires --baseline")
        if args.mode == "compiler-inputs":
            prepare_binding(args.baseline.resolve(), output, rebuild_compiler=True)
        else:
            (prepare_xs_inputs if args.mode == "xs-inputs" else prepare_binding)(args.baseline.resolve(), output)
    else:
        {"capture": capture, "replay": replay, "supplement": supplement, "fixtures": fixtures}[args.mode](output)


if __name__ == "__main__":
    main()
