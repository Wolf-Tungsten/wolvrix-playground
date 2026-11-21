import json
import resource
import subprocess
import sys
from diagnostics import *
from armor_xs_current_gap import BINS
from grhsim_difftrace import compare_traces, validate_trace_coverage

def run(label):
    for wl, image in IMAGES.items():
        d = OUT/"verify"/label/wl
        d.mkdir(parents=True,exist_ok=True)
        grh = label=="layout"
        ref = DEFAULT/"verify/pgo"/wl/"runtime/bin/trace_s0" if grh else ROOT/"build/armor-xs-pgo-threeway-v1/verify"/wl/"trace"
        comp = ROOT/"build/armor-xs-pgo-v1/gsim/verify/comparator/compare"
        cpu, _ = pick_cpu()
        command = ["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",BINS[label],
                   "-i",image,"--diff",NEMU,"-b","0","-e","0","-s","0","-C",str(WINDOW),"--dump-difftrace","./trace"]
        execute(command,"run",d,clean_environment(),d)
        sig = signature(parse_run((d/"run.log").read_text(), WINDOW))
        assert sig==expected(label,wl)
        cmp = compare_traces(comp,ref,d/"trace",d/"compare.json")
        save(d/"result.json",dict(signature=sig,coverage=validate_trace_coverage(cmp,sig)))
        if not grh:
            tool = ROOT/"build/armor-xs-pgo-v1/compare-commit-prefix"
            for mode in ("ordinary","pgo"):
                grtrace = DEFAULT/"verify"/mode/wl/"runtime/bin/trace_s0/0.bin"
                row = json.loads(subprocess.check_output([tool,grtrace,d/"trace/0.bin"],text=True))
                assert row["common_prefix_packets"]==min(row["grhsim_commit_packets"],row["gsim_commit_packets"])
                save(d/(mode+"-prefix.json"),row)
        print(label,wl,"ok",flush=True)
if __name__=="__main__":
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    run(sys.argv[1])
