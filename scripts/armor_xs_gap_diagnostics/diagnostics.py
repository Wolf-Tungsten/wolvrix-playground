"""Build from the timed model sources; coverage counts source executions, line builds locate instructions."""
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from armor_xs_current_gap import DEFAULT, IMAGES, LLVM, MATCHED, NEMU, OUT, WINDOW, expected
from armor_xs_pgo_build import XS, execute, header
from armor_dispatch_diag import pick_cpu
from grhsim_single_baseline import clean_environment, identity, parse_run, save
from xiangshan_cv32_ablation_measure import signature


def build(label, kind):
    grh = label.startswith("gr")
    base = DEFAULT / ("ordinary" if label == "gr_off" else "pgo") if grh else MATCHED
    source = base / "model"
    dest = OUT / kind / label
    work = dest / "work"
    engine = "grhsim" if grh else "gsim"
    model = work / ("model" if grh else "gsim-compile/model")
    model.mkdir(exist_ok=True, parents=True)
    for src in source.iterdir():
        if src.name == "Makefile" or src.suffix in (".hpp", ".cpp", ".h"):
            dst = model / src.name
            if not dst.exists():
                dst.symlink_to(src)
    binary = work / (engine + "-compile/emu")
    if (dest / "binary.json").exists():
        return model, binary
    optimize = ("-O3" if kind == "lines" else "-O1") + " -march=native"
    if kind == "coverage":
        flags, ld = "-fprofile-instr-generate -fcoverage-mapping", "-fprofile-instr-generate"
    elif kind in ("watch", "sitewatch"):
        flags, ld = "", ""
    else:
        ld = "-fprofile-use=" + str(base / ("build/grhsim.profdata" if grh else "merged.profdata")) if label.endswith("pgo") else ""
        flags = ("-gline-tables-only " + ld).strip()
    xs = ROOT / "testcase/xiangshan" if grh else XS
    gateway = ROOT / "build/armor-expression-default-v1/default/chisel-home/build/generated-src" if grh else header("gsim").parent
    command = ["make", "-j20", "-C", xs / "difftest", engine + "-build-emu", f"BUILD_DIR={work}",
               "NUM_CORES=1", "EMU_THREADS=0", "EMU_RANDOMIZE=0", "WITH_CHISELDB=0", "WITH_CONSTANTIN=0",
               "NO_DIFF=0", "EMU_TRACE=", "PGO_WORKLOAD=", "PGO_BOLT=0", f"EMU_OPTIMIZE={optimize}",
               f"PGO_CFLAGS={flags}", f"PGO_LDFLAGS={ld}", f"CXX={LLVM/'clang++'}",
               f"CC={LLVM/'clang'}", f"AR={LLVM/'llvm-ar'}", f"GEN_CSRC_DIR={gateway}", f"GEN_VSRC_DIR={gateway}"]
    if grh:
        command += ["GRHSIM=1", "WOLVRIX_GRHSIM_WAVEFORM=0", "WOLVRIX_GRHSIM_PERF=0",
                    f"GRHSIM_MODEL_DIR={model}", "GRHSIM_MODEL_BUILD_JOBS=20",
                    f"GRHSIM_MODEL_CXXFLAGS=-std=c++20 {optimize} {flags}"]
    else:
        command += ["GSIM=1", f"GSIM_CXX={LLVM/'clang++'}", "GSIM_BIN=/usr/bin/false", "-o", model / "SimTop0.cpp"]
    execute(command, "build", dest, dict(clean_environment(), LC_ALL="C", NOOP_HOME=str(xs)))
    save(dest / "binary.json", identity(binary))
    return model, binary


def cover(label, model, binary):
    for wl, image in IMAGES.items():
        dest = OUT / "coverage" / label / wl
        dest.mkdir(parents=True, exist_ok=True)
        if not (dest / "endpoint.json").exists():
            cpu, _ = pick_cpu()
            env = dict(clean_environment(), LC_ALL="C", EMU_PROGRESS_EVERY_CYCLES="0",
                       LLVM_PROFILE_FILE=str(dest / "trace.profraw"))
            command = ["taskset", "-c", str(cpu), "numactl", "--membind=1", "setarch", "x86_64", "-R",
                       binary, "-i", image, "--diff", NEMU, "-b", "0", "-e", "0", "-s", "0", "-C", str(WINDOW)]
            execute(command, "run", dest, env, dest)
            end = signature(parse_run((dest / "run.log").read_text(), WINDOW))
            assert end == expected(label, wl), end
            save(dest / "endpoint.json", end)
        lcov = dest / "model.lcov"
        if not lcov.exists():
            profile = dest / "merged.profdata"
            execute([LLVM / "llvm-profdata", "merge", dest / "trace.profraw", "-o", profile], "merge", dest)
            temp = dest / "export.tmp"
            with temp.open("w") as stream:
                subprocess.run([LLVM / "llvm-cov", "export", "-format=lcov", "-skip-branches", "-instr-profile="+str(profile),
                                binary, model], stdout=stream, check=True)
            if temp.stat().st_size < 100000:
                raise ValueError("empty model coverage")
            temp.replace(lcov)
        print(label, wl, lcov.stat().st_size, flush=True)


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    kind, label = sys.argv[1:]
    model, binary = build(label, kind)
    if kind == "coverage":
        cover(label, model, binary)
