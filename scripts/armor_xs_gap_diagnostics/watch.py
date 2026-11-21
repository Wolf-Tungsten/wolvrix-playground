"""Count actual scalar change decisions and firings with watched outputs, without instrumenting timing ELF."""
import json
import re
import resource
import sys
from pathlib import Path

from diagnostics import DEFAULT, IMAGES, MATCHED, NEMU, OUT, WINDOW, build, clean_environment, execute, expected
from diagnostics import parse_run, pick_cpu, save, signature

HEADER = r'''#pragma once
#include <cstdio>
#include <cstdlib>
namespace xs_watch {
struct Totals {
    unsigned long long fires=0, checked=0, productive=0, outside=0;
    unsigned long long tests[3]{}, changes[3]{};
    ~Totals() {
        if (auto *f = std::fopen(std::getenv("XS_WATCH_OUT"), "w")) {
            std::fprintf(f, "%llu %llu %llu %llu\n", fires, checked, productive, outside);
            for (int i=0; i<3; ++i) std::fprintf(f, "%llu %llu\n", tests[i], changes[i]);
            std::fclose(f);
        }
    }
};
inline Totals totals;
struct Scope;
inline Scope *active=nullptr;
struct Scope {
    Scope *previous=active;
    bool checked=false, changed=false;
    Scope() { active=this; }
    ~Scope() {
        ++totals.fires; totals.checked+=checked; totals.productive+=changed; active=previous;
    }
};
inline bool test(bool changed, unsigned kind) {
    ++totals.tests[kind]; totals.changes[kind]+=changed;
    if (active) { active->checked=true; active->changed|=changed; }
    else ++totals.outside;
    return changed;
}
}
'''
GS_UPDATE = re.compile(rb'\s*([\w$]+)(?:\[[^\]]*\])* = \1\$NEXT(?:\[[^\]]*\])*;')
GS_COND = re.compile(rb'^(\s*)bool (cond_[\w$]+) = ([^;]+);\s*$')
GS_IF = re.compile(rb'^(\s*)if \(([\w$]+) != ([\w$]+\$old\$\d+)\) \{\s*$')
GR = re.compile(rb'^(\s*)const bool (grhsim_changed_\d+) = (\(value_[\w]+_slots_\[\d+\] != next_value\));\s*$')


def rewrite(label):
    gs = label == "gs_pgo"
    sources = (MATCHED if gs else DEFAULT / ("pgo" if label == "gr_pgo" else "ordinary")) / "model"
    work = OUT / "watch" / label / "work" / ("gsim-compile/model" if gs else "model")
    work.mkdir(parents=True, exist_ok=True)
    (work / "xs_watch.hpp").write_text(HEADER)
    files = sorted(sources.glob("*.cpp" if gs else "*_sched_*.cpp"))
    state = set()
    if gs:
        for f in files:
            for line in f.open("rb"):
                if b"$NEXT" in line and b" = " in line:
                    m = GS_UPDATE.match(line)
                    if m:
                        state.add(m[1])
    if gs:
        (OUT / "gs-registers.txt").write_bytes(b"\n".join(sorted(state)) + b"\n")
        print("ordinary register names",len(state),flush=True)
    counts = [0, 0, 0, 0]
    def kind(name):
        return 1 if name.endswith(b"$NEXT") else 2 if name in state else 0
    for f in files:
        group = False
        compute = gs
        with f.open("rb") as before, (work / f.name).open("wb") as after:
            after.write(b'#include "xs_watch.hpp"\n')
            for line in before:
                if not gs and b"void GrhSIM_SimTop::eval_" in line:
                    compute = b"::eval_compute_batch_" in line
                if not compute:
                    after.write(line)
                    continue
                if gs:
                    if b") { // id=" in line:
                        after.write(line + b"      xs_watch::Scope xs_watch_scope;\n")
                        counts[0] += 1
                        continue
                    if b"bool cond_" in line:
                        m = GS_COND.match(line)
                        if m and b"$old$" in m[3]:
                            k = kind(m[2][5:])
                            after.write(line + m[1] + b"xs_watch::test(" + m[2] + b", %d);\n" % k)
                            counts[1+k] += 1
                            continue
                    if b"$old$" in line and b"if (" in line:
                        m = GS_IF.match(line)
                        if m:
                            k = kind(m[2])
                            after.write(m[1] + b"if (xs_watch::test(" + m[2] + b" != " + m[3] + b", %d)) {\n" % k)
                            counts[1+k] += 1
                            continue
                else:
                    if b"// Supernode " in line:
                        group = True
                    elif group and b"if (" in line and line.rstrip().endswith(b"{"):
                        after.write(line + b"            xs_watch::Scope xs_watch_scope;\n")
                        counts[0] += 1
                        group = False
                        continue
                    if b"const bool grhsim_changed_" in line:
                        m = GR.match(line)
                        if m:
                            after.write(line + m[1] + b"xs_watch::test(" + m[2] + b", 0);\n")
                            counts[1] += 1
                            continue
                after.write(line)
    assert counts[0] > 10000 and counts[1] > 100000, counts
    save(OUT / "watch" / label / "sites.json", counts)


def run(label):
    dest = OUT / "watch" / label
    if not (dest / "sites.json").exists():
        rewrite(label)
    _, binary = build(label, "watch")
    for wl, image in IMAGES.items():
        directory = dest / wl
        directory.mkdir(exist_ok=True)
        if (directory / "result.json").exists():
            continue
        rec = directory / "watch.txt"
        cpu, _ = pick_cpu()
        command = ["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",binary,
                   "-i",image,"--diff",NEMU,"-b","0","-e","0","-s","0","-C",str(WINDOW)]
        execute(command,"run",directory,dict(clean_environment(),XS_WATCH_OUT=str(rec)),directory)
        sig = signature(parse_run((directory / "run.log").read_text(),WINDOW))
        assert sig == expected(label,wl)
        counts = [list(map(int,r.split())) for r in rec.read_text().splitlines()]
        save(directory / "result.json", {"signature":sig,"groups":counts[0],"comparisons":counts[1:]})
        print(label, wl, counts, flush=True)


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    run(sys.argv[1])
