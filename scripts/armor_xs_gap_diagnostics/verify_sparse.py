"""Compare both sparse-prototype workload traces with the frozen PGO reference."""
from collections import Counter
import resource

from diagnostics import DEFAULT, IMAGES, NEMU, OUT, ROOT, WINDOW
from diagnostics import clean_environment, execute, expected, parse_run, pick_cpu, save, signature
from grhsim_difftrace import compare_traces, validate_trace_coverage


def verify_sparse(binary):
    for wl,image in IMAGES.items():
        folder=OUT/"verify"/"sparse"/wl
        folder.mkdir(exist_ok=True,parents=True)
        if (folder/"result.json").exists(): continue
        cpu,_=pick_cpu()
        cmd=["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",binary,"-i",image,
             "--diff",NEMU,"-b","0","-e","0","-s","0","-C",str(WINDOW),"--dump-difftrace","./trace"]
        if wl=="coremark":cmd+=["--force-dump-result"]
        execute(cmd,"run",folder,clean_environment(),folder)
        data=(folder/"run.log").read_text().splitlines()
        ref=DEFAULT/"verify/pgo"/wl
        counters=Counter(t for t in data if t.startswith("[PERF ]"))
        assert counters==Counter(t for t in (ref/"run.log").read_text().splitlines() if t.startswith("[PERF ]"))
        sig=signature(parse_run("\n".join(t for t in data if not t.startswith("[PERF ]")),WINDOW))
        assert sig==expected("gr_pgo",wl)
        cmp=compare_traces(ROOT/"build/armor-xs-pgo-v1/gsim/verify/comparator/compare",ref/"runtime/bin/trace_s0",
                           folder/"trace",folder/"trace.json")
        save(folder/"result.json",dict(signature=sig,coverage=validate_trace_coverage(cmp,sig),counter_lines=sum(counters.values())))


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    verify_sparse(OUT / "sparse/build/emu")
