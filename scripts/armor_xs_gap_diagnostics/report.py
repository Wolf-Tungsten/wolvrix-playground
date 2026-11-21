"""Render the TNO tables directly from the measured data and preserve the small diagnostic results."""
from collections import Counter
from statistics import mean
import json
import struct
from pathlib import Path

from results import OUT, ROOT, BINS, GROUPS, expected, identity, paired, read, save, signature

DOC=ROOT/"pdocs/armor_grhsim"
W="../../build/armor-xs-gap-current-v1"
NAMES={"gs_off":"GSIM 普通","gs_pgo":"GSIM PGO","gr_off":"GrhSIM 普通","gr_pgo":"GrhSIM PGO","layout":"GrhSIM 联合布局、无 PGO"}
LABELS=["gs_off","gr_off","gs_pgo","gr_pgo","layout"]
WLS={"coremark":"CoreMark","microbench":"MicroBench"}
BUCKETS={"value computation":"值计算及条件",
         "change detection and notification":"组合值的比较、写回和读者通知",
         "register update":"寄存器更新及提交",
         "dispatch tests":"激活字与计算组测试",
         "model, no statement line":"模型内无语句行号",
         "machine code differs":"对应指令字节有差异",
         "outside model":"harness、NEMU 及其他"}

def table(header,rows):
    return "\n".join("| "+" | ".join(map(str,row))+" |" for row in [header,["---"]*len(header),*rows])

def link(path,title):
    return f"[{title}]({W}/{path})"

def main():
    stats=read(OUT/"metrics.json");att=read(OUT/"per-guest-attribution.json");raw=read(OUT/"measurement/rounds.json")
    sizes={n:read(OUT/"machine"/n/"sizes.json") for n in BINS}
    watch={wl:{n:read(OUT/"watch"/n/wl/"result.json") for n in ["gs_pgo","gr_pgo","gr_off"]} for wl in WLS}
    source=read(OUT/"source-bytes.json")
    weighted=read(OUT/"audit/weighted.json");sel=read(OUT/"sparse/selection.json")
    sitewatch=OUT/"sitewatch/gr_pgo"
    train=list(struct.iter_unpack("<QQ",(sitewatch/"sites.bin").read_bytes()))
    keep=[i for i,(n,c) in enumerate(train) if n>=sel["min_visits"] and c*200<=n]
    hold=list(struct.iter_unpack("<QQ",(sitewatch/"micro.bin").read_bytes()))
    assert len(keep)==sel["selected"] and len(train)==len(hold)
    sel["holdout_visits"]=sum(hold[i][0] for i in keep)
    sel["holdout_changes"]=sum(hold[i][1] for i in keep)
    sel["holdout_over_half_percent"]=sum(hold[i][1]*200>hold[i][0] for i in keep)
    pair_path=OUT/"pair030/rounds.json"
    pair=read(pair_path) if pair_path.is_file() else {}
    complete=all(len(pair.get(wl,[]))==4 for wl in WLS)
    pair_stats={wl:paired(r,"gr_pgo","sparse") for wl,r in pair.items()} if complete else {}
    records={"gr_pgo":identity(BINS["gr_pgo"]),"sparse":identity(OUT/"sparse/build/emu")}
    for wl,rs in pair.items():
        for i,r in enumerate(rs,1):
            assert r["cpu"]==96 and r["round"]==i and r["group"]==1+(i%2==0)
            for n,record in records.items():
                sample=r[n]
                assert sample["binary"]==record and signature(sample)==expected("gr_pgo",wl)
                assert sample["sibling_idle"]["288"]>=98 and sample["cpu_fraction"]>=.97
                assert set(sample["counts"])=={"cycles","instructions",*GROUPS[r["group"]-1]}
                assert min(sample["counter_running_pct"].values())>=98 and sample["placements"]>0
                assert {k:v for k,v in sample.items() if k!="cpu_fraction"}==read(OUT/sample["path"]/"sample.json")
    a={wl:{n:read(OUT/"machine"/n/wl/"attribution.json") for n in LABELS if n!="layout"} for wl in WLS}
    code={wl:{n:read(OUT/"machine"/n/wl/"summary.json") for n in LABELS} for wl in WLS}
    cov={wl:{n:read(OUT/"coverage"/n/wl/"sites-mix.json")["per_guest"] for n in ("gs_pgo","gr_off","gr_pgo")} for wl in WLS}
    cache={wl:{n:read(OUT/"ibs-isolated"/n/wl/"cache/summary.json") for n in ("gs_pgo","gr_pgo")} for wl in WLS}
    small=DOC/"data/TNO0026_current_gap_diagnostics.json"
    examples=read(OUT/"machine/examples.json")
    for case in examples.values():
        case["assembly"]={k:(OUT/case[k]).read_text() for k in ("excerpt","off","pgo") if k in case}
    archive=dict(identities=read(OUT/"inputs.json"),summary=stats,source_bytes=source,
       elf={k:{"bytes":v["elf"],"text":v["sections"][".text"],"rodata":v["sections"].get(".rodata"),"object":v["model_object"],"cpp":v["cpp_files"],"functions":v["functions"],"function_bytes":v["function_bytes"]} for k,v in sizes.items()},
       machine_examples=examples,gs_pgo_line_binary_differences=read(OUT/"machine/gs_pgo/rip-differences.json"),
       phase_samples={w:{n:code[w][n]["phase"] for n in LABELS} for w in WLS},
       measured_change_sites=watch,coverage=cov,schedule=weighted,attribution=att,ibs_cache=cache,
       hot_pages={wl:{n:code[wl][n]["pages90"] for n in LABELS} for wl in WLS},
       candidate=dict(selection=sel,rounds={wl:[{n:{k:s[n][k] for k in ("external_wall_s","counts","cpu_fraction","binary")}
                      for n in ("gr_pgo","sparse")} for s in rows] for wl,rows in pair.items()},paired=pair_stats),
       source_attribution_samples={wl:{n:{"total":x["total"],"buckets":x["buckets"],"unverified":x["unverified"]} for n,x in y.items()} for wl,y in a.items()})
    save(small,archive)
    s=[]
    def para(t):s.append(t)
    def section(h):s.append("## "+h)
    para("# TNO0026　DPI 对齐后的 GSIM 与当前 GrhSIM")
    p=[stats[w]["paired"]["gr_pgo_vs_gs_pgo"]["pct"] for w in WLS]
    q=[stats[w]["paired"]["gr_off_vs_gs_off"]["pct"] for w in WLS]
    para(f"同轮配对的 GrhSIM / GSIM 耗时变化在普通构建为 CoreMark {q[0]:+.2f}%、MicroBench {q[1]:+.2f}%，开启各自的默认 PGO 后为 {p[0]:+.2f}%、{p[1]:+.2f}%。GSIM 两版都将两处组合统计 DPI 的输出置零。GrhSIM 用 TNO0025 发布的两个默认入口。另将 PGO 入口的同一份生成源码用普通编译器选项构建，以便分离生成布局与编译器 PGO 的收益。[四十次交错跑的原始数据](./data/TNO0026_current_gap_samples.csv) · [诊断与二进制身份](./data/TNO0026_current_gap_diagnostics.json)")
    section("相同周期窗口的运行成本")
    para("两种负载各运行四轮，每个版本每轮一次。下表的秒数是外部 walltime 算术平均，指令和周期是整进程用户态硬件事件除以每次报告的 100,001 个 guest cycles。CPI 取四轮平均宿主周期数除以四轮平均退休指令数。分支预测失败沿用第一轮专门计数的结果。")
    rows=[]
    for wl,title in WLS.items():
        for n in LABELS:
            v=stats[wl]["per_guest"][n]
            rows.append((title,NAMES[n],f"{v['wall']:.2f}",f"{v['instructions']:,.0f}",f"{v['cycles']:,.0f}",f"{v['CPI']:.3f}",f"{v['branch-misses']:,.0f}"))
    para(table(["负载","构建","耗时 / s","宿主退休指令 / 拍","宿主周期 / 拍","CPI","分支预测失败 / 拍"],rows))
    def ratio(w,metric,n,b):return stats[w]["per_guest"][n][metric]/stats[w]["per_guest"][b][metric]
    ins=[100*(ratio(w,"instructions","gr_pgo","gs_pgo")-1) for w in WLS]
    cpi=[100*(ratio(w,"CPI","gr_pgo","gs_pgo")-1) for w in WLS]
    para(f"开启 PGO 后，GrhSIM 的宿主退休指令比 GSIM 多 {ins[0]:.1f}% / {ins[1]:.1f}%（CoreMark / MicroBench），每条宿主指令的周期数相对 GSIM 为 {cpi[0]:+.1f}% / {cpi[1]:+.1f}%。宿主周期等于退休指令数乘 CPI。普通 GSIM 每拍执行的宿主指令更少，但每条指令耗时更多，两个因素在普通构建中相互抵消。")
    pairs=[("gs_off","gr_off","普通 GrhSIM / 普通 GSIM"),("gs_pgo","gr_pgo","PGO GrhSIM / PGO GSIM"),
           ("gs_off","gs_pgo","GSIM，同源码开 PGO"),("gr_off","gr_pgo","GrhSIM，切换两个默认入口"),
           ("gr_off","layout","GrhSIM，普通编译只换生成布局"),("layout","gr_pgo","GrhSIM，联合布局固定，只开编译器 PGO")]
    def pc(d):return f"{d['pct']:+.2f}% [{d['ci95_pct'][0]:+.2f}%, {d['ci95_pct'][1]:+.2f}%]"
    para(table(["同轮耗时变化","CoreMark","MicroBench"],[
        [label]+[pc(stats[w]["paired"][b+"_vs_"+a0]) for w in WLS] for a0,b,label in pairs]))
    para("区间从四个同轮比值的全部重采样组合计算。四轮刻画这台主机上两个固定窗口内的波动。同源码对照使用和普通版相同的模型及 harness 编译选项，联合布局包括 160 操作上限、宽块提交和三组规则。[当前构建配置](./TNO0025_xiangshan_grhsim_mode_defaults_20261121.md) · "+link("verify/layout","固定源码对照的两个完整轨迹"))
    para("复现第五种构建时，将 TNO0025 PGO 生成目录的 C++、头文件及 Makefile 复制到独立的 `control/model`。沿用相同的 Clang、DiffTest 网关和普通版参数，调用 `make -o xs_wolf_grhsim_emit xs_wolf_grhsim_emu PGO_WORKLOAD=`，用 `XS_WOLF_GRHSIM_EMIT_DIR` 指向复制的源码，用 `XS_GRHSIM_BUILD` 指向独立输出目录。"+link("control/build.log","固定源码的实际编译命令"))
    section("指令供给与分支")
    rows=[]
    for wl,title in WLS.items():
        for n in LABELS:
            v=stats[wl]["per_guest"][n]
            rows.append((title,NAMES[n],f"{v['branches']:,.0f}",f"{100*v['branch-misses']/v['branches']:.2f}%",
                f"{v['ic_cache_fill_l2']:,.0f}",f"{v['ic_cache_fill_sys']:,.0f}",f"{v['bp_l1_tlb_miss_l2_tlb_miss.all']:,.0f}",
                f"{v['de_no_dispatch_per_slot.no_ops_from_frontend']/1e6:.2f}",f"{v['de_no_dispatch_per_slot.backend_stalls']/1e6:.2f}"))
    para(table(["负载","构建","分支 / 拍","预测失败率","L2 供给 I-cache 行 / 拍","L2 以外供给行 / 拍","二级 iTLB miss / 拍","前端空派发槽 / 拍，百万","后端受阻槽 / 拍，百万"],rows))
    def fill_per_k(w,n):
        v=stats[w]["per_guest"][n]
        return 1000*v["ic_cache_fill_sys"]/v["instructions"]
    para(f"GrhSIM PGO 每拍需取回的指令行更多。但按每千条退休指令计算，从 L2 以外取得的行数分别为 CoreMark {fill_per_k('coremark','gr_pgo'):.1f} 对 {fill_per_k('coremark','gs_pgo'):.1f}、MicroBench {fill_per_k('microbench','gr_pgo'):.1f} 对 {fill_per_k('microbench','gs_pgo'):.1f}（GrhSIM 对 GSIM）。每拍总量与边界计算和提交工作的执行次数一起增长。仅调整 ELF 冷热排列无法消除这些值的生成、比较与传播。")
    para("同一次运行最多五个事件。前端空派发槽按槽计数，不能直接解释为 CPU 等待的周期百分比。L2 之外的指令行可以来自其他缓存或内存。原始表另含一级数据访问、miss、退休条件分支、退休宏操作与来自近端内存的数据填充。宿主退休指令的事件是 PMCx0C0。Zen 4 的 PMCx0C1 对应退休宏操作，两者分别保存在计数表中。[AMD 第四代 EPYC 计数器定义](https://docs.amd.com/r/en-US/57368-uProf-user-guide/Predefined-Core-PMC-Events)")
    rows=[]
    for w,title in WLS.items():
        for n in ("gs_off","gs_pgo","gr_off","gr_pgo"):
            at=a[w][n];m=stats[w]["per_guest"][n]["branch-misses"]
            scaled=lambda cat:m*at["buckets"]["ibs-misses"].get(cat,0)/at["total"]["ibs-misses"]
            rows.append([title,NAMES[n],*[f"{scaled(k):,.0f}" for k in list(BUCKETS)[:4]]])
    para(table(["IBS 定位的预测失败 / 拍","构建","值计算与条件","组合变化通知","寄存器更新","调度测试"],rows))
    para("GSIM 生成的许多控制流直接表示 FIRRTL 的条件赋值，PGO 可以改变分支方向、冷热块排列和执行未选中表达式的成本。前端 FTQ redirect 的同一行，在普通版中测试后用短距离 `je` 跳过一条路径，PGO 版本让另一臂顺序执行并以远距离 `jne` 跳出。具体站点只是代码形态示例，整类效果见 IBS 统计。"+link("machine/gs_off/examples/when1.asm","普通 GSIM 反汇编")+" · "+link("machine/gs_pgo/examples/when1.asm","PGO GSIM 反汇编"))
    section("生成源码、ELF 和热代码")
    rows=[]
    for n in LABELS:
        t=sizes[n]
        rows.append([NAMES[n],t["cpp_files"],f"{t['source_bytes']/1e9:.2f}",f"{t['elf']/2**20:.2f}",
            f"{t['sections']['.text']/2**20:.2f}",f"{t['sections']['.rodata']/2**20:.2f}",f"{t['model_object']/2**20:.2f}",
            *[f"{code[w][n]['pages90']['cycles']:,}" for w in WLS]])
    para(table(["构建","C++ 文件","C++ 与头文件 / GB","ELF / MiB",".text / MiB",".rodata / MiB","模型 sizeof / MiB","CoreMark 90% 采样热页","MicroBench 90% 采样热页"],rows))
    para("热页是计时 ELF 的生成模型中累计覆盖 90% 周期样本所需的 4 KiB 页数，受样本量与分布影响。它不等同于缓存容量或页驻留量。GSIM 两个版本共享 409 个 C++ 文件和头文件，其中约 1.30 GB 在默认关闭的 `ENABLE_LOG` 块里。GrhSIM PGO 有 0.385 GB 整行注释。模型对象为编译器实际 `sizeof`，堆上单独分配的内存不含在其中。在两个负载中，GrhSIM PGO 的模型对象较小，但热指令覆盖的代码页更多。"+link("source-bytes.json","源码分类")+" · "+link("machine","ELF 节表、函数及热页分布"))
    section("组件归因")
    para("以计时 ELF 的周期样本按生成语句分类，再乘本构建的总周期。表内为每拍千个宿主周期。变化通知包括组合值比较、槽位写回和读者活动位操作。GSIM 的下一状态辅助变化和寄存器写计入寄存器更新，普通值的表达式求值以及下一状态的表达式均计入值计算。GrhSIM 的提交函数整体计入提交，包括存储器、统计累加等工作。")
    for w,title in WLS.items():
        para(table([title,"普通 GSIM","普通 GrhSIM","PGO GSIM","PGO GrhSIM"],[
          [desc]+[f"{att[w][n]['cycles'].get(k,0)/1000:.0f}" for n in ("gs_off","gr_off","gs_pgo","gr_pgo")] for k,desc in BUCKETS.items()]))
    para("PGO 下没有语句行号的样本在 GSIM 较多。跨组簿记、提交和算式各自的归因有行表偏差，表中保留未归属项。三个版本加行号后的完整 `.text` 与计时 ELF 逐字节相同。GSIM PGO 的 407 个模型子函数地址及长度相同，行号映射仅接受该位置指令字节也一致的样本。IBS 另在 node029 上独立核心采集并从硬件原始记录识别预测失败，按计时机真实总数换算，属于估计。[AMD IBS 事件说明](https://docs.amd.com/r/en-US/57368-uProf-user-guide/IBS-Derived-Events) · "+link("per-guest-attribution.json","完整语句归因"))
    para("对上述字节有差异的 GSIM PGO 采样地址逐条反汇编。CoreMark 的 1,843 个不同地址和 MicroBench 的 1,680 个不同地址全部只有 RIP 相对位移不同，目标均在各自 ELF 的只读数据段，目标开始的 16 字节常量一致。它们分别包含 699 / 622 个周期样本，表中单列。"+link("machine/gs_pgo/rip-differences.json","两份 ELF 的热点指令对照"))
    rows=[]
    for w,title in WLS.items():
        for n in ("gs_pgo","gr_pgo"):
            c=cache[w][n];v=stats[w]["per_guest"][n];total=c["all"]["dc_miss"]
            share=lambda key:100*c["buckets"][key]["dc_miss"]/total
            rows.append([title,NAMES[n],f"{v['L1-dcache-load-misses']:,.0f}",f"{total:,}",
                 *[f"{share(k):.1f}%" for k in ("value computation","change detection and notification","register update")]])
    para(table(["负载","构建","L1D miss / 拍（PMC）","有 DC miss 的 IBS 样本","值计算占比","组合比较及通知占比","寄存器更新占比"],rows))
    para("从 IBS 原始的 Op Data 3 读取 load/store 和 DC miss 位。百分比分母是该构建中所有有效的 DC miss 访存样本，含未归属语句及非模型。两边在值计算行都出现可观的数据缓存流量；GrhSIM 在组合簿记上的 miss 样本占比尤其高。一个 miss 的开销受并行访存和下层缓存影响，此处不将事件数直接换算为等待周期。"+link("ibs-isolated","IBS 原始数据与各阶段分类"))
    para("GSIM 先做位宽、常量、别名和公共表达式优化。graphCoarsen 在初始分区前依次合并条件节点、单出、单入及兄弟节点，随后做有容量限制的连续分段、复制并构造语句树。GrhSIM 从 SystemVerilog 恢复进组的私有标量 mux 臂。可移入分支的中间值须在本组恰有一次操作数使用、没有跨组消费者，且组满足纯度等条件。已经跨组物化的值会同时影响通知和按条件跳过求值的机会。上述测量能定位执行差异，前端表示与各个优化 pass 的贡献仍需分离对照。[GSIM 生成流程](../../../wolvrix-playground-new-xiangshan/reference/gsim/src/main.cpp) · [GSIM 粗化与分区](../../../wolvrix-playground-new-xiangshan/reference/gsim/src/graphPartition.cpp) · [GrhSIM 条件 mux 的适用条件](../../wolvrix/docs/emit/grhsim-conditional-mux-cones.md)")
    section("计算组边界")
    rows=[]
    for w,title in WLS.items():
        for n in ("gs_pgo","gr_off","gr_pgo"):
            d=watch[w][n];z=d["signature"]["guest_cycles"];fires,checked,productive,_=d["groups"]
            tests,changes=d["comparisons"][0]
            rows.append([title,NAMES[n],f"{fires/z:,.0f}",f"{tests/z:,.0f}",f"{changes/z:,.0f}",
                         f"{100*changes/tests:.2f}%",f"{tests/fires:.2f}",f"{checked/z:,.0f}",f"{productive/z:,.0f}"])
    para(table(["负载","生成模型","组执行 / 拍","普通组合标量比较 / 拍","实际变化 / 拍","变化率","比较 / 组执行","有观测点的组执行 / 拍","至少一项观测到变化 / 拍"],rows))
    para("这是专用计数 ELF 每次实际执行、比较和变化的次数。对 GSIM，只将普通组合值纳入中间三列，寄存器及带 `$NEXT` 的比较另外计数。有观测点和有变化的组执行数覆盖该后端所有被插桩的类型。GrhSIM 插桩覆盖显式标量槽的 `grhsim_changed_ID` 比较，宽数组、特殊内联和提交阶段另计。组内还有存储器、副作用和未纳入观测的值；不能按变化率直接删掉整个组。两边观察到的有用变化数量接近，每次唤醒在 GrhSIM 中触发更多标量比较。"+link("watch","源级执行计数")+" · "+link("coverage","Clang 源行覆盖交叉核对"))
    para("同一段 ROB 逻辑可以直接核对。GSIM 在 SimTop332.cpp 第 36539 行开始声明八个局部量 `uopCanEnqSeq_{0..7}_67`，第 36583 行开始在同组计算并使用。当前 GrhSIM 把第 0 路发射为局部 `grhsim_v968274_0`，其余七路仍物化为跨组布尔槽。第 4 路的槽 386506 在 CoreMark 被比较 59,015 次、变化 504 次，MicroBench 被比较 42,358 次、变化 347 次，然后才与其他变化合并、通知读者。这比笼统要求提高超节点上限更能指明应该检查哪条生产者与消费者链。[GSIM 的八路局部变量](../../build/armor-gsim-gap-v1/pgo/gsim-nodpi/model/SimTop332.cpp) · [GrhSIM 的跨组比较](../../build/armor-xs-mode-defaults-v1/pgo/model/grhsim_SimTop_sched_21.cpp) · [GrhSIM 的局部第 0 路及读者](../../build/armor-xs-mode-defaults-v1/pgo/model/grhsim_SimTop_sched_30.cpp)")
    rows=[]
    for k,title in [("multiple external targets","多个外部读者"),("only commit target","唯一提交读者"),
                    ("only compute, capacity","唯一计算读者，超过 160 容量"),("only compute, order","唯一计算读者，容量可容纳、顺序受限"),
                    ("only compute, fits and order","唯一计算读者，容量与顺序均允许")]:
        rows.append([title,f"{weighted['static'][k]:,}"]+[f"{weighted['dynamic'][w][k].get('executions',0)/100001:,.0f}" for w in WLS])
    para(table(["现行 PGO 调度中的普通组合生产值","静态值数","CoreMark 比较 / 拍","MicroBench 比较 / 拍"],rows))
    para("生成器总计 1,039,932 个边界值。上表列其中由普通组合操作产生的值，静态统计包含提交读者。动态列只覆盖同时符合简单标量写回和读者通知形式的 581,807 个站点。提交读者单独一行的零表示这个计算侧模板没有相应通知，不表示提交免费。跨区域分解后的候选单位为同一粗化簇在同一最终组内的全部节点，比较当前组容量并检查其所有输出的读者顺序。这个上界还没有扣除候选争用、移动引入的新输入、事件域约束。旧 108 调度按同一程序重算后输出与旧审计逐字节相同。[现行审计](../../scripts/armor_single_reader_audit.cpp) · "+link("audit/weighted.json","逐类动态与静态权重"))
    para("在 CoreMark / MicroBench，两边界条件允许直接移入读者的比较仅覆盖约 5,151 / 4,670 次每拍。超过容量的唯一计算读者约 45,010 / 38,524 次，多外部读者约 59,951 / 50,357 次。把所有有唯一读者的静态值都当作可以消去的动态比较，会同时高估可移动数和可节省工作量。")
    section("提交与写回的机器码")
    para("CoreMark 已有同一生成模型的块计数。每拍访问约 10,529 个数据比较块，约 520 个进入逐项路径。每拍另测试约 5,298 个使能块，约 515 个展开。二者已跳过大量单寄存器扫描，提交仍须读这些块并处理被选中的项。另一处固定工作来自 32,454 个统计寄存器的累加循环，真实热点反汇编为 `vmovdqu64`、`vpaddq` 及向量存回。它在 CoreMark 的提交桶里是一个集中热点，不代表全部提交开销。[同一模型的块访问](../../build/armor-gap-followup-v1/block-visits-joint/counts/result.json) · "+link("machine/gr_pgo/examples/bank.asm","提交热点实际反汇编"))
    para("按计时 ELF 的函数级周期样本，整个提交阶段占 GrhSIM PGO 的 11.3% / 12.1%。在其他阶段耗时固定的理想假设下，全部消去提交也仅把 CoreMark 从 80.74 秒降到约 71.65 秒、MicroBench 从 71.95 秒降到约 63.24 秒，仍比对应的 GSIM PGO 多约 16% / 11%。若改变时序结构同时改变计算工作量，需用新的完整模型实测。")
    para("跨组写回可见另一种代码。生成器先将新值与槽里的旧值比较，再合并布尔变化、更新读者活动字并写回槽位。以 `grhsim_SimTop_sched_59.cpp:40458` 为例，未变化一臂仍把零掩码与活动字做 `orw`，之后 `movw` 写回。GSIM 也发射比较和通知，但每次组激活执行的此类操作较少。其寄存器下一值与更新由图中的有序节点表达，可随活动传播；GrhSIM 保留独立的提交阶段。[GrhSIM 生成器](../../wolvrix/lib/emit/grhsim_cpp.cpp) · "+link("machine/gr_pgo/examples/notify.asm","活动字写回的实际反汇编"))
    section("稀疏写回对照实验")
    para(f"只在 CoreMark 的专用计数构建上选点。581,807 个标量站点中，{sel['selected']:,} 个至少执行 25,000 次且变化率不高于 0.5%。合计每拍 {sel['visits']/100001:,.0f} 次比较、{sel['changes']/100001:,.1f} 次变化。原型在这些位置把本槽写回、布尔累积和掩码通知放进一个变化分支，其他表达式仍求值。原型用自己的 CoreMark profile 重新编译，两个负载各通过完整 DiffTest 轨迹，CoreMark 期末全部性能计数也与默认版一致。"+link("sparse/selection.json","训练选择")+" · "+link("verify/sparse","原型轨迹"))
    para(f"在未参与选点的 MicroBench 中，这些位置每拍执行 {sel['holdout_visits']/100001:,.0f} 次，实际改变 {sel['holdout_changes']/100001:,.1f} 次，总变化率 {100*sel['holdout_changes']/sel['holdout_visits']:.3f}%。其中 {sel['holdout_over_half_percent']:,} 个站点在 MicroBench 超过训练用的 0.5% 门槛。这类有条件写回保留真正变化后的处理路径。")
    rows=[]
    for w,title in WLS.items() if complete else ():
        rs=pair[w]; n="sparse"; b="gr_pgo"
        counter=lambda name,e:mean(r[name]["counts"][e]/r[name]["guest_cycles"] for r in rs if e in r[name]["counts"])
        rows.append([title,rs[0]["cpu"],f"{mean(r[b]['external_wall_s'] for r in rs):.2f}",f"{mean(r[n]['external_wall_s'] for r in rs):.2f}",
                    pc(pair_stats[w]),f"{counter(n,'instructions')-counter(b,'instructions'):+,.0f}",
                    f"{counter(n,'branches')-counter(b,'branches'):+,.0f}",f"{counter(n,'branch-misses')-counter(b,'branch-misses'):+,.0f}"])
    if rows:
        para(table(["node030 独立配对","CPU","默认 / s","原型 / s","同轮变化","Δ 指令 / 拍","Δ 分支 / 拍","Δ 预测失败 / 拍"],rows))
        core, micro=pair_stats["coremark"],pair_stats["microbench"]
        para(f"原型在 CoreMark 的同轮平均耗时变化为 {core['pct']:+.2f}%（{core['faster']}/4 轮更快），MicroBench 为 {micro['pct']:+.2f}%（{micro['faster']}/4 轮更快）。额外分支主要落在高度可预测的位置，减少的槽位写回与活动字操作在退休指令上可见。它对齐了一个具体机制，剩余的每拍求值、比较及多读者依赖仍需处理。")
        para("每组独立预热，四轮交换运行次序，校验本地 NUMA 页面与同核竞争。两轮计数分支，两轮计数取指，四轮均测周期和指令。最早在 node029 的预试因同核竞争被剔除，表中均为 node030 CPU 96 的正式记录。"+link("pair030/rounds.json","配对记录")+" · "+"[生成代码原型](../../scripts/armor_xs_gap_diagnostics/sparse.py)")
    else:
        para("原型的独立配对正在 node030 的 CPU 96 上运行。")
    rows=[]
    for w,title in WLS.items() if complete else ():
        for n in ("gr_pgo","sparse"):
            v=pair[w]
            event=lambda k:mean(r[n]["counts"][k]/r[n]["guest_cycles"] for r in v if k in r[n]["counts"])
            rows.append([title,"默认" if n=="gr_pgo" else "原型",f"{event('ic_cache_fill_l2'):,.0f}",
                         f"{event('ic_cache_fill_sys'):,.0f}",f"{event('de_no_dispatch_per_slot.no_ops_from_frontend')/1e6:.2f}"])
    if rows:para(table(["独立配对","构建","L2 供给 I-cache 行 / 拍","L2 以外供给行 / 拍","前端空槽 / 拍，百万"],rows))
    para("原型的 `.text` 为 89,809,586 字节，默认 PGO 为 88,606,818 字节。原型只将等值赋值和零掩码通知移出常见路径，仍须求新值并执行比较。通过 CoreMark 选点的模型还涉及一套手写离线选择过程，正式生成器需要保存可跨训练重现的标识并验证额外工作负载。")
    section("后续优化")
    if complete:
        para("优先把按站点的访问和变化计数接进编译训练，并用本文的独立源码对照核验所选站点。以未参与训练的负载、跨阶段或长窗口，以及保留的完整轨迹作为推广条件。把条件写回限制在可证明等价且有实际动态回报的位置；本轮原型仅用于诊断。")
    para("计算侧优先检验按真实消费者拆分激活和减少边界写回。以每拍执行的比较、真实变化、加权新增输入及读者激活次数为成本，分别测试高频多读者值和容量受限的单读者热点。静态可移入唯一读者的 25,802 个值中，能够实际省掉的工作还受组内旧读者和同时移动影响。直接放大所有计算组可能让热读者带上冷生产逻辑，应使用相同源起点和两个负载核验。")
    para("提交侧按阶段细分实际余量。连续值块已能跳过大部分逐项工作，可以按相同使能和时钟域继续组织分散的新旧值。对于主要流向提交的值，检验将新值产生与所属事件绑定、减少跨阶段物化的成本；这些改变需要验证同一时钟沿的读旧值、多写者次序和使能变化。另对统计累加循环检查分块增量活性，计入生产侧记录增量的开销。")
    section("测量边界")
    minimum=min(min(x[n]["counter_running_pct"].values()) for rs in raw.values() for x in rs for n in BINS)
    idle=min(x[n]["sibling_idle"]["288"] for rs in raw.values() for x in rs for n in BINS)
    para(f"node030 为 AMD EPYC 9684X。正式样本使用 CPU 96、本地 NUMA 1 的私有二进制及依赖、关闭 ASLR、单线程、seed 0、开启 DiffTest。所有主比较共 40 次正式计时，最低 SMT 兄弟空闲率 {idle:.2f}%，计数器最低实际运行比例 {minimum:.2f}%。PMU 的短时轮转按 perf 报告比例缩放，四轮都测 cycles 和 instructions，其余事件每种负载、每个版本各测一轮。预热的 perf record 样本只用于归因。两个窗口均为前 10 万个请求周期，PGO 用 CoreMark 训练，MicroBench 是留出负载。[交错计时驱动](../../scripts/armor_xs_current_gap.py) · "+link("inputs.json","ELF、profile 与固件身份"))
    para("同一后端开关 PGO 和固定源码实验均匹配各自的终点。两个引擎的停止位置相差两个架构周期。逐包比较共同前缀的 PC、指令和融合数，CoreMark 的 164,997 个和 MicroBench 的 109,222 个提交包全部一致，覆盖较短窗口的全部提交包。GSIM 在两个窗口分别多退休 7、9 条 guest 指令。文中的 CPU 指令数均指宿主，无插桩 ELF 的总量含初始化、harness 和 NEMU。两处统计 DPI 的置零只对齐本次指定的差异。"+link("verify/gs_off","两种负载的对照及提交前缀")+" · [默认 GrhSIM 轨迹](./TNO0025_xiangshan_grhsim_mode_defaults_20261121.md)")
    dest=DOC/"TNO0026_xiangshan_dpi_aligned_current_gap_20261121.md"
    dest.write_text("\n\n".join(s).replace("；","。")+"\n")
    print(dest,flush=True)

if __name__=="__main__":
    main()
