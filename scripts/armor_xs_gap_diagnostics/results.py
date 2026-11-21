"""Read verified trial records and export paired summaries and unrounded raw data."""
import csv
import itertools
import math
import platform
from statistics import mean
import sys

from diagnostics import *
from armor_xs_current_gap import BINS, GROUPS, ORDERS
from xiangshan_cv32_ablation_measure import read

def paired(rows, a, b):
    ratios=[r[b]["external_wall_s"]/r[a]["external_wall_s"]-1 for r in rows]
    boot=sorted(map(mean,itertools.product(ratios,repeat=len(ratios))))
    return dict(pct=100*mean(ratios),faster=sum(v<0 for v in ratios),rounds=len(rows),
                min_pct=min(ratios)*100,max_pct=max(ratios)*100,
                ci95_pct=[100*boot[int((len(boot)-1)*q+.5)] for q in (.025,.975)])

def main():
    rounds=read(OUT/"measurement/rounds.json")
    assert set(rounds)==set(IMAGES) and all(len(rows)==4 for rows in rounds.values())
    names=[event for group in GROUPS for event in group]
    csvrows=[]; stats={}
    for wl,rows in rounds.items():
        st={}
        for ix,r in enumerate(rows):
            assert list(r["order"])==list(ORDERS[ix])
            for j,name in enumerate(r["order"]):
                s=r[name];c=s["counts"]
                assert s==read(OUT/s["path"]/"sample.json")
                assert signature(s)==expected(name,wl)
                assert s["binary"]==identity(BINS[name]) and set(c)=={"cycles","instructions",*GROUPS[ix]}
                assert min(s["counter_running_pct"].values())>=98 and s["sibling_idle"]["288"]>=98 and s["placements"]>0
                csvrows.append(dict(workload=wl,round=r["round"],position=j+1,variant=name,
                        external_wall_s=s["external_wall_s"],host_ms=s["host_ms"],guest_cycles=s["guest_cycles"],
                        guest_instr=s["instr_count"],host_cycles=c["cycles"],host_instructions=c["instructions"],
                        **{k:c.get(k,"") for k in names},sibling_idle_pct=s["sibling_idle"]["288"],
                        min_counter_running_pct=min(s["counter_running_pct"].values()),binary_sha256=s["binary"]["sha256"]))
        for name in BINS:
            samples=[r[name] for r in rows]
            metrics={ev:mean(s["counts"][ev]/s["guest_cycles"] for s in samples if ev in s["counts"])
                     for ev in ("cycles","instructions",*names)}
            metrics.update(wall=mean(s["external_wall_s"] for s in samples),
                wall_rounds=[s["external_wall_s"] for s in samples],CPI=metrics["cycles"]/metrics["instructions"],
                max_instructions_spread_pct=100*(max(s["counts"]["instructions"] for s in samples)/
                  min(s["counts"]["instructions"] for s in samples)-1))
            st[name]=metrics
        pairs=[("gs_off","gr_off"),("gs_pgo","gr_pgo"),("gs_off","gs_pgo"),("gr_off","gr_pgo"),
               ("gr_off","layout"),("layout","gr_pgo")]
        diffs={b+"_vs_"+a:paired(rows,a,b) for a,b in pairs}
        stats[wl]=dict(per_guest=st,paired=diffs)
    dest=ROOT/"pdocs/armor_grhsim/data/TNO0026_current_gap_samples.csv"
    with dest.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=csvrows[0],lineterminator="\n");w.writeheader();w.writerows(csvrows)
    save(OUT/"metrics.json",stats)
    save(OUT/"inputs.json",dict(binaries={k:identity(v) for k,v in BINS.items()},images={k:identity(v) for k,v in IMAGES.items()},
         nemu=identity(NEMU),gr_profile=identity(DEFAULT/"pgo/build/grhsim.profdata"),gs_profile=identity(MATCHED/"merged.profdata"),
         gsim_dpi_edits=read(MATCHED/"model/patched.json"),window=WINDOW,core=96,node=1,order=ORDERS))
    scaled={}
    for wl,s in stats.items():
        scaled[wl]={}
        for n in ("gs_off","gr_off","gs_pgo","gr_pgo"):
            a=read(OUT/"machine"/n/wl/"attribution.json")
            conv={"cycles":"cycles","instructions":"instructions","ibs-ops":"ex_ret_ops","ibs-misses":"branch-misses"}
            scaled[wl][n]={ev:{k:v/a["total"][ev]*s["per_guest"][n][counter] for k,v in a["buckets"][ev].items()}
                          for ev,counter in conv.items()}
    save(OUT/"per-guest-attribution.json",scaled)
    for wl,r in stats.items():print(wl,r["paired"],flush=True)

if __name__=="__main__":
    main()
