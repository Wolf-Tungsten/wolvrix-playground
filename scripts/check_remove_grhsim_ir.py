"""Audit independent IR retirement in production sources, builds and models."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ("scripts/wolvrix_xs_grhsim.py", "scripts/wolvrix_hdlbits_grhsim.py",
           "scripts/reemit_grhsim.py", "scripts/grhsim_flow.py")
RETIRED_CALLS = frozenset(("lower_grh_to_grhsim", "lower_grhsim", "run_grhsim_pass",
                         "run_grhsim_pipeline", "emit_grhsim_cpu", "load_grhsim", "store_grhsim",
                         "list_grhsim_passes", "load_grhsim_json", "store_grhsim_json",
                         "read_grhsim_json_file", "session_lower_grhsim", "session_run_grhsim_pass",
                         "session_load_grhsim", "session_store_grhsim"))
RETIRED_CPP = re.compile(r"\b(?:GrhSimModel|CpuProgram|CpuMapping|lowerGrhToGrhSim|"
                         r"grhsimModels|sessionGrhSimModel|py_session_(?:lower_grhsim|run_grhsim_pass|"
                         r"load_grhsim|store_grhsim)|py_list_grhsim_passes)\b")
RETIRED_SYMBOL = "wolvrix::lib::grhsim::"
RETIRED_TREES = ("wolvrix/include/grhsim", "wolvrix/lib/grhsim")
PASS_ORDER = ("grh-to-grhsim", "grhsim-split-event-and-output", "grhsim-split-nonsink-and-sink",
              "grhsim-partition-nonsink", "grhsim-partition-sink")


def python_issues(source, name):
    issues = []
    for node in ast.walk(ast.parse(source, filename=name)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RETIRED_CALLS:
            issues.append(f"{name}:{node.lineno}: retired production definition {node.name}")
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
            if called in RETIRED_CALLS:
                issues.append(f"{name}:{node.lineno}: retired production call {called}")
    return issues


def cpp_issues(source, name):
    # Ignore comments, but inspect actual includes, identifiers and literals.
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    issues = [f"{name}: retired IR identifier {match.group()}" for match in RETIRED_CPP.finditer(source)]
    if re.search(r'#\s*include\s*[<"]grhsim/(?:ir|backend|dialect|convert|pass|io)/', source):
        issues.append(f"{name}: includes independent GrhSIM infrastructure")
    return issues


def audit(build, report, model_dir=None):
    issues, sources, symbol_checks = [], {}, []
    python_files = list(ENTRIES) + [str(path.relative_to(ROOT)) for path in
                                  sorted((ROOT / "wolvrix/app/pybind/wolvrix").rglob("*.py"))]
    for relative in python_files:
        source = (ROOT / relative).read_text()
        issues.extend(python_issues(source, relative))
        sources[relative] = hashlib.sha256(source.encode()).hexdigest()
    flow = ast.parse((ROOT / "scripts/grhsim_flow.py").read_text())
    passes = [node.value for node in ast.walk(flow) if isinstance(node, ast.Constant) and node.value in PASS_ORDER]
    # AST traversal includes branches in source order. Check all required pass
    # literals are present; execution ordering is exercised by test_grhsim_flow.
    if set(passes) != set(PASS_ORDER):
        issues.append("shared flow lacks a required conversion/partition pass")
    cpp_files = []
    for directory in ("wolvrix/lib", "wolvrix/include", "wolvrix/app/pybind/native"):
        cpp_files.extend(sorted((ROOT / directory).rglob("*.cpp")))
        cpp_files.extend(sorted((ROOT / directory).rglob("*.hpp")))
    for path in cpp_files:
        name = str(path.relative_to(ROOT))
        source = path.read_text()
        issues.extend(cpp_issues(source, name))
        sources[name] = hashlib.sha256(source.encode()).hexdigest()
    retired_files = [str(path.relative_to(ROOT)) for tree in RETIRED_TREES
                     for path in (ROOT / tree).rglob("*") if path.is_file()]
    retired_binding = ROOT / "wolvrix/app/pybind/native/actions/grhsim.cpp"
    if retired_binding.exists():
        retired_files.append(str(retired_binding.relative_to(ROOT)))
    issues.extend(f"retired implementation remains: {name}" for name in retired_files)
    cmake = (ROOT / "wolvrix/CMakeLists.txt").read_text()
    sources["wolvrix/CMakeLists.txt"] = hashlib.sha256(cmake.encode()).hexdigest()
    if re.search(r"(?:lib|include|tests)/grhsim/", cmake):
        issues.append("CMake still builds independent IR sources or fixtures")
    commands = build / "compile_commands.json"
    if not commands.is_file():
        issues.append("missing compile_commands.json; configure and build the current source first")
    else:
        for command in json.loads(commands.read_text()):
            if "/lib/grhsim/" in command["file"] or command["file"].endswith("/actions/grhsim.cpp"):
                issues.append(f"retired source in actual build graph: {command['file']}")
    objects = sorted(build.glob("CMakeFiles/*/lib/emit/grhsim/*.o"))
    objects += sorted(build.glob("CMakeFiles/*/lib/transform/grhsim/*.o"))
    if not objects:
        issues.append("no built new-route objects; run test_grhsim_cpu_st_cpp test_grhsim_sink_schedule first")
    for path in objects:
        symbols = subprocess.check_output(["nm", "-C", "-u", str(path)], text=True)
        bad = [line.strip() for line in symbols.splitlines() if RETIRED_SYMBOL in line]
        issues.extend(f"{path}: independent IR dependency: {line}" for line in bad)
        symbol_checks.append({"object": str(path.relative_to(ROOT)), "legacy_references": len(bad)})
    for path in (build / "libwolvrix-lib.so", build / "python/wolvrix/_wolvrix.so"):
        if not path.is_file():
            issues.append(f"missing current compiler/binding library: {path}")
            continue
        symbols = subprocess.check_output(["nm", "-C", str(path)], text=True)
        bad = [line.strip() for line in symbols.splitlines()
               if RETIRED_SYMBOL in line or RETIRED_CPP.search(line)]
        issues.extend(f"{path}: retired compiler/binding symbol: {line}" for line in bad)
        symbol_checks.append({"library": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "legacy_references": len(bad)})
    if model_dir is not None:
        manifest = json.loads((model_dir / "manifest.json").read_text())
        if manifest.get("emitter") != "grhsim-cpu-st-cpp":
            issues.append("model manifest is not from grhsim-cpu-st-cpp")
        for name in manifest.get("sources", []):
            path = model_dir / name
            issues.extend(cpp_issues(path.read_text(), str(path)))
        for path in model_dir.glob("*.hpp"):
            issues.extend(cpp_issues(path.read_text(), str(path)))
        libraries = list(model_dir.glob("libgrhsim_*.a"))
        if len(libraries) != 1:
            issues.append("expected one compiled generated model library")
        else:
            symbols = subprocess.check_output(["nm", "-C", "-u", str(libraries[0])], text=True)
            bad = [line.strip() for line in symbols.splitlines() if "wolvrix::lib::" in line]
            issues.extend(f"generated model depends on compiler library: {line}" for line in bad)
            symbol_checks.append({"generated_library": str(libraries[0]), "compiler_references": len(bad)})
    result = {"schema": "wolvrix.remove-grhsim-ir.production-audit.v2", "passed": not issues,
              "scope": "production sources, retired trees, actual CMake build graph, compiler/binding symbols and model dependencies",
              "entries": list(ENTRIES), "sources_sha256": sources, "symbol_checks": symbol_checks, "issues": issues}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": not issues, "sources": len(sources), "objects": len(symbol_checks), "issues": issues}), flush=True)
    return not issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    if not args.report.resolve().is_relative_to(ROOT / "ptmp/remove-grhsim-ir"):
        parser.error("report must be under ptmp/remove-grhsim-ir")
    return 0 if audit(args.build, args.report, args.model_dir) else 1


if __name__ == "__main__":
    raise SystemExit(main())
