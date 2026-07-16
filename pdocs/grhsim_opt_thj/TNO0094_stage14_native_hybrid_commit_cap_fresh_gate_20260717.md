# TNO0094 Stage 14 native-hybrid commit-cap fresh gate

记录日期：2026-07-17

状态：fresh 结构、canonical slot、O3 与 fixed-ASLR 100/10k/50k 功能门禁完成；严格性能待补。基于 [TNO0092](./TNO0092_stage14_native_hybrid_default_adoption_decision_20260717.md) 已采用的 C++ native hybrid default，重新生成 commit guard merge cap `4096/8192/16384/32768` 四档。高 cap 的 raw BAE、DAG 和 ELF size 都下降，typed value-slot mapping 完全稳定，但实际 emitted active OR sites 从 `790,475` 增至 `790,764/790,635/790,648`。因此 raw BAE 下降不能单独代表 emitter 动态工作减少；当前整机外部负载没有留下满足严格 whole-node gate 的窗口，本文不生成或引用受污染的性能数字，默认 cap 继续保持 `4096`。

## 1. Fresh 基线与唯一变量

本轮以 current native hybrid default 为共同 emitter 配置：

```text
direct_single_writer_state_reads = native true
pure_event_compute_word_bypass   = native true
pure_event profile / word pack   = off
```

四套 fresh 目录为：

```text
build/xs_activity_stage14_native_hybrid_default_20260717
build/xs_activity_stage14_native_hybrid_default_cap8192_20260717
build/xs_activity_stage14_native_hybrid_default_cap16384_20260717
build/xs_activity_stage14_native_hybrid_default_cap32768_20260717
```

第一套使用 native commit cap `4096`，其余只显式改变 `max_op_in_commit_supernode` 为 `8192/16384/32768`。activity-schedule 的 DP、fanin、clone、packing 等其它实验 policy 均关闭；Stage 13 canonical commit locality group/order 保持启用。因此该矩阵回答的是“当前 hybrid emitter 下 commit coarsening 的实际 source/O3/功能形状”，不混入旧 NO0300 emitter 或不同 post-stats provenance。

## 2. Fresh 结构结果

四档 production stats 如下；百分比均相对 cap4096：

| cap | total SN | commit SN / event-key runs | raw BAE | raw BAE delta | compute-to-commit pairs | DAG edges | DAG delta |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4096` | `63,726` | `485` | `1,983,923` | `0` | `262,225` | `528,622` | `0` |
| `8192` | `63,709` | `468` | `1,983,326` | `-597` (`-0.030092%`) | `261,628` | `527,990` | `-632` (`-0.119556%`) |
| `16384` | `63,700` | `459` | `1,981,862` | `-2,061` (`-0.103885%`) | `260,164` | `527,331` | `-1,291` (`-0.244220%`) |
| `32768` | `63,696` | `455` | `1,981,680` | `-2,243` (`-0.113059%`) | `259,982` | `526,921` | `-1,701` (`-0.321780%`) |

其余关键结构保持不变：

```text
compute supernodes             63,241
compute-to-compute value pairs 1,721,698
boundary values                1,000,463
topo edges                     10,150,909
commit event keys              450
```

compute-to-compute pairs 不变，因此 raw BAE 的全部下降都来自 compute-to-commit pairs；commit SN/runs 则随 cap 增大由 `485` 降至 `455`。结构层面 high cap 确实减少了 scheduler 统计的跨 supernode 边，但收益不随 cap 线性增长：从 `16384` 到 `32768` 只再减少 `182` 个 BAE。

## 3. Canonical typed-slot gate

从四套 generated source 抽取 typed value-slot mapping，结果完全一致：

| cap | raw rows | unique rows | vs cap4096 changed / missing / extra / type-changed |
| ---: | ---: | ---: | ---: |
| `4096` | `914,621` | `914,583` | control |
| `8192` | `914,621` | `914,583` | `0 / 0 / 0 / 0` |
| `16384` | `914,621` | `914,583` | `0 / 0 / 0 / 0` |
| `32768` | `914,621` | `914,583` | `0 / 0 / 0 / 0` |

四档 raw TSV 与 unique TSV 各自 byte-exact，SHA256 分别为：

```text
raw     cbc84814dcf7023d357a47a6db833f89582d8d06ec2821bd01d76e0d6c79073f
unique  4c603f837a8f0be86c32477f7b5830525374be23cd1d3fda3e25eebb95fdc281
```

这再次闭合了 Stage 13 的目标：high cap 不再引起 value-slot 全局改号。需要注意，slot identity 只排除了 value storage/layout 这一类混杂变量；它不保证 propagation statement 数或 active mask 组合方式相同。

## 4. Raw BAE 与 emitted active OR 的反向关系

对四档 production generated schedule source 使用同一 scanner 统计实际 emitted active OR sites，得到：

| cap | raw BAE | BAE delta | emitted active OR sites | OR-site delta |
| ---: | ---: | ---: | ---: | ---: |
| `4096` | `1,983,923` | `0` | `790,475` | `0` |
| `8192` | `1,983,326` | `-597` | `790,764` | `+289` (`+0.036560%`) |
| `16384` | `1,981,862` | `-2,061` | `790,635` | `+160` (`+0.020241%`) |
| `32768` | `1,981,680` | `-2,243` | `790,648` | `+173` (`+0.021886%`) |

三个 high-cap candidate 都出现同一方向：raw BAE 下降，但 emitted active OR site 比 cap4096 更多。原因边界是，raw BAE 按 source value 与 target supernode 的逻辑 pair 计数；emitter 还要按 active word、mask、changed-value lowering 和 source statement grouping 将逻辑边物化。合并 commit supernode 可以删除逻辑 pair，同时改变 mask sharing/grouping，使实际 OR statement 数增加。canonical typed-slot identity 不会自动固定这层 lowering。

因此后续 activity-schedule 候选不能只以 raw BAE/DAG 作为性能代理。至少应同时观察：

- emitted active OR/update sites；
- generated source/batch/function 数与 `.text`；
- 50k instructions、frontend/backend PMU 与 cycles。

本结果并不证明 high cap 一定回退；OR-site 增幅只有约 `0.02%..0.04%`，仍需严格 50k 裁决。但它解释了为什么“BAE 更少”不能直接晋升默认，也说明 cap8192/16384/32768 的 runtime 次序不应按 raw BAE 大小预判。

## 5. Generated source 与 fresh O3

commit coarsening 减少了 sched source file 数和总 source bytes：

| cap | C++/header files | source bytes |
| ---: | ---: | ---: |
| `4096` | `154` | `1,356,872,724` |
| `8192` | `134` | `1,356,643,748` |
| `16384` | `122` | `1,356,489,274` |
| `32768` | `116` | `1,356,410,734` |

四档均完成 fresh O3/link，三个 high-cap build log 的 exit status 均为 `0`：

| cap | emu bytes | delta | ELF `.text` | delta | `.eh_frame` |
| ---: | ---: | ---: | ---: | ---: | ---: |
| `4096` | `93,694,944` | `0` | `87,113,502` | `0` | `706,632` |
| `8192` | `93,671,816` | `-0.024684%` | `87,095,345` | `-0.020843%` | `706,144` |
| `16384` | `93,661,624` | `-0.035562%` | `87,097,093` | `-0.018836%` | `704,960` |
| `32768` | `93,656,296` | `-0.041249%` | `87,097,223` | `-0.018687%` | `704,704` |

ELF SHA256 为：

```text
cap4096   51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788
cap8192   28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7
cap16384  851f42e6f2f20fdb600aefa1cd232bc8f707e34b420d67b2332217b3fad3fe4a
cap32768  af336b2fcb38b4166c011ea61004e12f1a387e83f19c7592d001a52f1e442190
```

size 指标也不与 raw BAE 单调对应：cap8192 的 `.text` 最小，而 cap16384/32768 虽有更低 BAE，`.text` 反而略大于 cap8192。所有差异都很小，不能替代 runtime。

## 6. Fixed-ASLR 功能门禁

四档 fresh emu 均在 `setarch x86_64 -R` 下通过 100/10k/50k：

| limit | guest / cycle / instr | PC | cap4096 | cap8192 | cap16384 | cap32768 |
| ---: | --- | --- | --- | --- | --- | --- |
| `100` | `101 / 96 / 0` | `0x0` | PASS | PASS | PASS | PASS |
| `10000` | `10001 / 9996 / 458` | `0x800027c6` | PASS | PASS | PASS | PASS |
| `50000` | `50001 / 49996 / 73580` | `0x80001312` | PASS | PASS | PASS | PASS |

所有功能进程正常退出，mismatch/assert/error/fail/bad-trap 等负向扫描均为 `0`。功能日志中的 wall time 只证明可运行与终点一致，不属于性能样本。

## 7. Strict 性能窗口仍被外部负载阻断

正式性能必须继续遵循 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 和 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的 page-local/whole-node 协议。当前 watcher 在 `2026-07-17 02:04..03:05` 连续保留了 `120` 个 30 秒整机 survey；没有一个窗口产生 qualified marker。第 `1/60/120` 个代表性窗口的 30 秒 whole-machine average idle 分别为 `87.15%/91.34%/91.33%`，且持续可见个别 logical CPU 接近 `100%` busy，明显属于外部任务占用，不满足整 node mean idle `>=99%`、minimum idle `>=95%` 的入口要求。

因此本轮没有启动可用于 cap 对比的正式 ABBA/BAAB，也没有合格的 PMU/cycles 百分比。本文明确不做以下事情：

- 不引用功能 50k wall time作为性能；
- 不把旧 NFS/page-cache 或旧 NO0300-emitter 样本拼接到 current native-hybrid matrix；
- 不因 raw BAE、OR sites 或 `.text` 单项变化宣称正收益/回退；
- 不降低 whole-node gate 来换取受污染数字。

外部负载结束后，四档应复制到 N0/N1 各自 `/dev/shm` inode，使用镜像 physical core、`taskset + numactl --physcpubind/--membind`、fixed-ASLR、运行中 page placement、whole-node monitor、PMU/scheduler 与平衡 ABBA/BAAB 完整重测。任何污染样本整组作废，不与其它 quiet window 拼接。

## 8. 当前结论

fresh gate 已证明四档功能正确、canonical typed slots 完全稳定，高 cap 同时略减 source/ELF size。新的关键证据是：raw BAE 分别减少 `597/2,061/2,243`，实际 emitted active OR sites 却分别增加 `289/160/173`。这使 high cap 不再能仅凭 raw BAE 获得“更少动态工作”的推断。

在严格 50k 没有合格样本前，commit cap 继续保持 native `4096`。cap8192/16384/32768 都保留为显式 runtime candidates；后续最终裁决以 current native hybrid 的 page-local 50k cycles 为口径，同时用 instructions 与 frontend/backend PMU 解释方向。

## 9. 增量补充：active lowering 完整口径勘误

增量日期：2026-07-17

第 4 节将 `790,475/790,764/790,635/790,648` 称为“实际 emitted active OR sites”，这个名称不完整：该 scanner 数字只覆盖直接写一个 active byte 的 one-byte OR 子类，并没有覆盖 chunk OR、table loop、local accumulation 和 deferred lowering。one-byte OR 反向增加这一观察仍成立，但不能单独代表完整 active lowering；以下完整 stream-scanner 口径取代第 4 节对总量的解释。

四档分类计数为：

| cap | raw BAE | one-byte OR | chunk OR | table loop body | local OR | deferred final | deferred temp | `kActivationMasks` entries |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4096` | `1,983,923` | `790,475` | `28,750` | `613` | `34` | `19,044` | `4,730` | `92,384` |
| `8192` | `1,983,326` | `790,764` | `28,346` | `614` | `34` | `19,113` | `4,940` | `92,471` |
| `16384` | `1,981,862` | `790,635` | `28,448` | `615` | `35` | `19,082` | `4,912` | `92,476` |
| `32768` | `1,981,680` | `790,648` | `28,454` | `614` | `37` | `19,071` | `4,912` | `92,434` |

其中两个静态 source-site 口径为：

```text
staticFinalSites = oneByteOR + chunkOR + tableLoopBody + localOR + deferredFinal
staticWithDeferredTemp = staticFinalSites + deferredTemp
```

table loop 的 source body 只出现一次，但运行时会遍历对应 `kActivationMasks` entries。为接近 potential write 数，再定义不带动态权重的展开 proxy：

```text
runtimeWriteProxy = oneByteOR + chunkOR + kActivationMasksEntries
                    + localOR + deferredFinal
runtimeWriteProxyWithTemp = runtimeWriteProxy + deferredTemp
```

汇总结果如下，括号内为相对 cap4096 的 delta：

| cap | static final sites | + deferred temp | runtime-write proxy | runtime-write proxy + temp |
| ---: | ---: | ---: | ---: | ---: |
| `4096` | `838,916` (`0`) | `843,646` (`0`) | `930,687` (`0`) | `935,417` (`0`) |
| `8192` | `838,871` (`-45`, `-0.005364%`) | `843,811` (`+165`, `+0.019558%`) | `930,728` (`+41`, `+0.004405%`) | `935,668` (`+251`, `+0.026833%`) |
| `16384` | `838,815` (`-101`, `-0.012039%`) | `843,727` (`+81`, `+0.009601%`) | `930,676` (`-11`, `-0.001182%`) | `935,588` (`+171`, `+0.018281%`) |
| `32768` | `838,824` (`-92`, `-0.010967%`) | `843,736` (`+90`, `+0.010668%`) | `930,644` (`-43`, `-0.004620%`) | `935,556` (`+139`, `+0.014860%`) |

完整口径修正了“所有 high cap 的总 OR work 都增加”的过强表述：

- one-byte OR 在三档 high cap 都增加，但 chunk OR 同时减少；不含 deferred temp 的 static final sites 反而都略降。
- 加入 deferred temp 后，三档 static 总量都略增；把 table loop body 展开为 mask entries 后，不含 temp 的 runtime-write proxy 为 `+41/-11/-43`，方向混合。
- runtime-write proxy 再加入 deferred temp 后三档均高于 cap4096，为 `+251/+171/+139`，但幅度只有 `0.0149%..0.0268%`。
- raw BAE 下降 `597..2,243` 与任何完整 lowering 口径都不呈单调对应；同样，one-byte OR 子项也不能替代完整 lowering 或 runtime。

这些数字来自对 generated source 的统一 stream scanner，是静态 site/entry 展开 proxy，不按 enclosing branch 是否执行、value 是否 change、active target 是否 fire 或 50k 中的真实频率加权。它们适合解释 codegen 形状，不能宣称为动态 write 次数。最终仍需用严格 page-local 50k instructions/PMU/cycles 裁决；当前无合格 quiet window、默认 cap 保持 `4096` 的结论不变。
