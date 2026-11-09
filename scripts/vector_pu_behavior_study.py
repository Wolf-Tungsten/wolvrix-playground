#!/usr/bin/env python3
"""Generate and lower the single-uop VIPU behavior carrier fixture."""
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XS = ROOT / "testcase/xiangshan"
FIRTOOL = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
CXX = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++")

def cp(name):
    return [x.split(":", 3)[3] for x in json.loads(
        (XS / "out/xiangshan" / f"{name}.json").read_text())["value"]]

def run(cmd, cwd, log, env=None):
    with open(log, "w") as f:
        r = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env,
                           stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise RuntimeError(Path(log).read_text()[-6000:])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", choices=["vec-int-pu-lane", "vec-int-pu-whole"], required=True)
    p.add_argument("--compute-lowering", choices=["ordinary", "grouped"], default="ordinary")
    a = p.parse_args(); out = a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    compiler, runtime = cp("scalaCompilerClasspath"), cp("test/runClasspath")
    plugin = next(x for x in cp("scalacPluginClasspath") if "chisel-plugin" in x)
    classes = out / "classes"; classes.mkdir(exist_ok=True)
    sources = [
        XS / "utility/src/main/scala/utility/BehaviorModels.scala",
        XS / "yunsuan/src/main/scala/yunsuan/vector/VectorALU/VAluBundles.scala",
        XS / "yunsuan/src/main/scala/yunsuan/vector/VectorALU/VAluDecode.scala",
        XS / "yunsuan/src/main/scala/yunsuan/vector/VectorALU/VIPUBehavior.scala",
        ROOT / "testcase/chisel-intrinsic/VectorPuBehaviorStudy.scala",
    ]
    run(["java", "-Xmx8g", "-cp", ":".join(compiler),
         "scala.tools.nsc.Main", "-classpath", ":".join(runtime),
         "-Xplugin:" + plugin, "-language:reflectiveCalls", "-d", classes,
         *sources], ROOT, out / "scala.log")
    grouped = a.compute_lowering == "grouped"
    dest = out / a.compute_lowering; dest.mkdir(exist_ok=True)
    run(["java", "-Xmx8g", "-cp", str(classes) + ":" + ":".join(runtime),
         "study.vectorpu.VectorPuBehaviorStudyMain", dest, FIRTOOL,
         a.model, a.compute_lowering], ROOT, dest / "elaborate.log")
    (dest / "input.f").write_text(str(dest / "VectorPuBehavior.sv") + "\n")
    (dest / "read_args.txt").write_text("")
    model = dest / "model"; graph = dest / "graph.json"; model.mkdir(exist_ok=True)
    env = dict(os.environ,
               WOLVRIX_SIMULATION_MODELS_MANIFEST=str(dest / "simulation_models.json"),
               WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(dest / "pre.json"),
               WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON="0",
               WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON="0",
               PYTHONPATH=str(ROOT / "build/grhsim32-tools/python"))
    run([sys.executable, ROOT / "scripts/wolvrix_xs_grhsim.py", dest / "input.f",
         "VectorPuBehaviorFixture", model, graph, dest / "read_args.txt", "info",
         "--waveform", "off", "--perf", "off", "--behavior-compute-lowering",
         a.compute_lowering], ROOT, dest / "emit.log", env)
    run(["make", "-C", model, "-j8", "CXX=" + str(CXX),
         "CXXFLAGS=-std=c++20 -O3 -march=native"], ROOT, dest / "compile.log", env)
    print(json.dumps({"model": a.model, "lowering": a.compute_lowering,
                      "output": str(dest)}))

if __name__ == "__main__":
    main()
