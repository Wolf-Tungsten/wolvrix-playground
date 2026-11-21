"""Build a single-model XiangShan emu with Clang instrumentation PGO."""
import argparse
import fcntl
import os
from pathlib import Path
import resource
import shlex
import shutil
import subprocess
import tempfile


def run(argv, **kwargs):
    print(shlex.join(map(str, argv)), flush=True)
    subprocess.run(argv, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=100000)
    parser.add_argument("--emu-args", required=True)
    parser.add_argument("--profdata", default="llvm-profdata")
    parser.add_argument("--model-flags", default="-std=c++20 -O3")
    parser.add_argument("make_command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.make_command[1:] if args.make_command[:1] == ["--"] else args.make_command
    if not command or args.cycles <= 0:
        parser.error("supply a make command after -- and a positive training window")
    image = args.workload.resolve(strict=True)
    model = args.model.resolve(strict=True)
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    _, hard = resource.getrlimit(resource.RLIMIT_STACK)
    resource.setrlimit(resource.RLIMIT_STACK, (hard, hard))
    with tempfile.TemporaryDirectory(prefix="grhsim-pgo-", dir=build) as directory:
        work = Path(directory)
        sources = work / "model"
        sources.mkdir()
        for path in model.iterdir():
            if path.suffix in (".cpp", ".hpp", ".h") or path.name == "Makefile":
                shutil.copyfile(path, sources / path.name)
        profile = work / "merged.profdata"
        binary = work / "grhsim-compile/emu"

        def compile_model(flag, extra=""):
            cflags = (flag + " " + extra).rstrip()
            run([*command, "grhsim-build-emu", f"BUILD_DIR={work}", f"GRHSIM_MODEL_DIR={sources}",
                 "PGO_WORKLOAD=", f"PGO_CFLAGS={cflags}", f"PGO_LDFLAGS={flag}",
                 f"GRHSIM_MODEL_CXXFLAGS={args.model_flags} {cflags}"])

        # Clang 23's instrumented XS model needs SLP disabled during training (TNO0016).
        compile_model("-fprofile-generate", "-fno-slp-vectorize")
        run([binary, "-i", image, "-C", str(args.cycles), *shlex.split(args.emu_args)],
            env=dict(os.environ, LLVM_PROFILE_FILE=str(work / "train-%p.profraw")))
        run([args.profdata, "merge", *sorted(work.glob("train-*.profraw")), "-o", profile])
        # Preserve the paths of module-local functions between generate and use.
        for pattern in ("*.o", "*.pch", "*.a"):
            for product in sources.glob(pattern):
                product.unlink()
        shutil.rmtree(binary.parent)
        compile_model("-fprofile-use=" + str(profile))
        # Concurrent builds have private profiles and binaries. Publish each pair together.
        directory_fd = os.open(build, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            os.replace(profile, build / "grhsim.profdata")
            os.replace(binary, build / "emu")
        finally:
            os.close(directory_fd)


if __name__ == "__main__":
    main()
