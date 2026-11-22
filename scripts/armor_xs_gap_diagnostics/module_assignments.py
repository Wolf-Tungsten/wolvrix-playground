"""Count dynamic assignments with an identifiable RTL result for three high-weight module types."""
from collections import Counter
from pathlib import Path
import sys
from value_modules import DEST, GR_LOCAL, GR_VALUE, GS_NAME, OUT, WORKLOADS, fir_hierarchy, signal_owner, save
from source_categories import GsimClassifier, read_lcov, bucket
from attribute import gs_kind

MODULES = {"Rob", "Ftq", "VectorDecodeChannel"}


def gr_values():
    values = {}
    with (OUT/"audit/stages/after-clone.ops.tsv").open() as stream:
        next(stream)
        for row in stream:
            if not any("/"+mod+'.sv"' in row for mod in MODULES):
                continue
            fields = row.rstrip("\n").split("\t")
            mod = Path(fields[4].strip('"')).stem
            if mod in MODULES:
                values.update((int(v),mod) for v in fields[8].split(",") if v)
    return values


def main(label):
    gs = label == "gs_pgo"
    result = {}
    if gs:
        tree = fir_hierarchy()
        regs = set((OUT/"gs-registers.txt").read_text().splitlines())
    else:
        values = gr_values()
    for wl in WORKLOADS:
        counts = {mod:Counter() for mod in MODULES}
        for file, lines, _ in read_lcov(OUT/"coverage"/label/wl/"model.lcov"):
            path = Path(file)
            if gs and not path.name.startswith("SimTop") or not gs and "_sched_" not in path.name:
                continue
            ph = False
            if gs: classifier = GsimClassifier(regs)
            current = None
            with path.open() as stream:
                for ln,raw in enumerate(stream,1):
                    if raw.startswith("void "):
                        ph = "::subStep" in raw if gs else "::eval_compute_batch_" in raw
                        current = None
                    if not ph:continue
                    t = raw.strip()
                    if not gs:
                        if "// value " in t:
                            m = GR_VALUE.search(t)
                            current = values.get(int(m[1])) if m else None
                        elif t.startswith("// op ") or t == "}":current = None
                    elif ("$old$" in t and " = " in t or "bool cond_" in t):
                        classifier.subject(t)
                    n = lines.get(ln,0)
                    if not n or " = " not in t or t.startswith("//"):continue
                    if not gs:
                        if m := GR_LOCAL.match(t):mod = values.get(int(m[1]))
                        elif "next_value = " in t or "next_words = " in t:mod = current
                        else:continue
                    else:
                        lhs = t.split(" = ",1)[0]
                        if "__DOT__" not in lhs:continue
                        if bucket("gsim",gs_kind(t,classifier)) != "value computation":continue
                        signal = GS_NAME.search(lhs)
                        if not signal:continue
                        mod = signal_owner(signal[0], tree)
                    if mod in MODULES:
                        counts[mod].update(sites=1,visits=n)
        result[wl] = counts
    save(DEST/label/"assignments.json",result)


if __name__ == "__main__":
    main(sys.argv[1])
