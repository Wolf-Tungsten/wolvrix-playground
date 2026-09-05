# TNO0275: XiangShan RepCut N=1 page-local AB/BA on node033

日期：2026-09-04

状态：`DIAGNOSTIC COMPLETE; PAGE CONFOUND REMOVED; STRICT PERFORMANCE N/A; N>1 PENDING; DEFAULT UNCHANGED`。

## 1. 结论

按 [TNO0274](./TNO0274_xiangshan_repcut_n1_page_local_runtime_protocol_fix_20260904.md)
的 `n1-page-local-v2` 协议，在 node033 同一 CPU64/NUMA0 完成 clean-v4
baseline/closure-aware 的 N=1 AB 与 BA。两个 order 使用 12 个互异 tmpfs inode；
四个 C=10000 accepted sample 的 model ELF 与 NEMU executable pages 均为
`remote_bytes=0`。

AB/BA pooled 结果为：

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| Host time mean | 61.687 s | 64.946 s | **+5.283%** |
| instructions | 270.408 B | 284.948 B | **+5.377%** |
| cycles | 220.203 B | 231.829 B | **+5.280%** |
| task-clock | 61.776 s | 65.034 s | **+5.274%** |
| aggregate IPC | 1.22799 | 1.22913 | +0.093% |
| average GHz | 3.56456 | 3.56475 | +0.005% |
| 32-part eval sum | 2564.716 us/step | 2715.714 us/step | **+5.887%** |
| eval max | 525.730 us/step | 357.448 us/step | **-32.009%** |
| eval population CV | 1.04962 | 0.62720 | **-40.245%** |
| attributed total sum | 3051.260 us/step | 3212.796 us/step | +5.294% |
| attributed total max | 584.731 us/step | 384.355 us/step | -34.268% |

修正后的含义很明确：closure-aware 确实以约 `5.4%..5.9%` 的串行总工作量
增加，换取最大 partition 约 `32%` 的下降和分布离散度约 `40%` 的下降。N=1
会顺序执行全部 32 个 model，只承担总量代价，无法兑现 max/makespan 收益；是否能在
N=8、N=32 得到净 walltime 收益仍须另测，本篇未执行 N>1。

这也闭合了用户提出的“instructions 只增加不多、walltime 为什么明显增加”：旧结果的
约 47% 增量是远端 executable page stall；page-local 后 instructions、cycles、
task-clock 和 Host 全部同幅增加约 5.3%，IPC/频率不再回退。剩余差值是实际生成模型
执行更多指令，不是降频或远端取指。

## 2. 与旧结果的勘误对照

| 指标 | TNO0272 原始页 | 本篇 page-local | 变化含义 |
| --- | ---: | ---: | --- |
| Host change | +47.367% | +5.283% | 原大部分回退消失 |
| cycles change | +47.331% | +5.280% | frontend latency confound 消失 |
| instructions change | +5.449% | +5.377% | 动态工作量判断基本不变 |
| eval sum change | +56.329% | +5.887% | per-part timing 不再被远端页放大 |
| eval max change | -0.671% | -32.009% | 削峰效果恢复 |
| eval CV change | -41.501% | -40.245% | 均衡方向始终稳定 |

因此 [TNO0272](./TNO0272_xiangshan_repcut_closure_weight_n1_node030_ccd80_runtime_diagnostic_20260904.md)
中的 Host/eval/cycles 数值只能作为 page-residency confound 的历史证据，不能评价算法。
本篇与 [TNO0273](./TNO0273_xiangshan_repcut_n1_frontend_numa_page_root_cause_20260904.md)
的本地页单序结果方向一致；TNO0273 的 eval sum/max 为 `+4.428%/-33.810%`，
本篇 opposite-order pooled 为 `+5.887%/-32.009%`。

## 3. 节点与运行口径

最初按要求在 node030 的 CPU `0-95` 扫描。node030 一度形成一个完整 page-local AB，
但随后 CI 启动约 379 个 `cc1plus`，所有 CCD 失去 admission；两个 opposite-order
尝试只形成 partial，不做拼接。随后在用户允许的 node029-node034、node036-node042
范围轮询，node033 CCD64 最近连续 8 个 3 s 窗口通过，故从头建立正式 diagnostic pair。

| 项目 | 值 |
| --- | --- |
| host / boot | node033 / `b8df54f6-fe34-4ed8-b965-326eaeab883e` |
| kernel | Linux 6.8.0-124-generic, x86_64 |
| K / N / C | 32 / 1 / 10000；C=100 为功能门 |
| target | CPU64 / NUMA0 |
| full CCD | `64-71,256-263` |
| monitor | CPU46，sibling 238，在目标 CCD 外 |
| AB | baseline -> closure-aware |
| BA | closure-aware -> baseline |
| model affinity | 仅 CPU64，`XS_EMU_THREADS=1` |
| ASLR / locale | `setarch x86_64 -R` / `LC_ALL=C` |
| policy | diagnostic；只豁免 `runtime_foreign_task_load` |
| pair ID | `node033_ccd64_cleanv4_pagelocalv2_n1_20260904_1630` |

两个 order 的 C=100 均首轮通过，冻结 endpoint/signature、302 steps、thread config
和 timing schema 闭合。C=10000 的 AB 两臂均首轮 accepted；BA candidate 首轮
accepted，baseline attempt01 因 `runtime_guard_min_idle` 被拒，attempt02 accepted。
被拒样本没有进入 `accepted.json` 或 pooled 结果。

## 4. AB/BA 顺序效应

| order | baseline Host | closure-aware Host | 相对变化 |
| --- | ---: | ---: | ---: |
| AB | 61.974 s | 65.848 s | +6.251% |
| BA | 61.400 s | 64.044 s | +4.306% |
| pooled mean | 61.687 s | 64.946 s | +5.283% |

arm 内 order spread 为 baseline `0.931%`、closure-aware `2.778%`；两序相对效果
相差 `1.945 pp`。因此 `+5.283%` 是当前 diagnostic 中心值，不写成亚百分点精度的
formal headline。另一方面，两序 instructions 增量分别为 `+5.385%/+5.369%`，
方向和幅度非常稳定；eval max 分别为 `-31.110%/-32.909%`，削峰结论也不依赖顺序。

node030 在 CI 风暴前完成的单序 AB 为 Host `60.537 -> 61.857 s`（`+2.180%`）、
eval sum `+2.266%`、eval max `-33.910%`，两侧同样 `remote=0`。它不进入本篇 pool，
但进一步说明跨机器/窗口会影响精确总量幅度，max 降低方向更稳定。

## 5. Phase 因果闭合

| phase (us/step) | baseline | closure-aware | 增量 | 变化 |
| --- | ---: | ---: | ---: | ---: |
| input_load | 4.8375 | 5.1330 | +0.2955 | +6.109% |
| part_eval | 2570.851 | 2722.276 | +151.425 | +5.890% |
| global_update | 488.840 | 499.2335 | +10.3935 | +2.126% |
| 三阶段总和 | 3064.5285 | 3226.6425 | +162.1140 | +5.290% |

`162.114 us/step * 20102 steps = 3.258816 s`，与 Host mean 的
`64.946 - 61.687 = 3.259 s` 几乎逐毫秒闭合。Host 增量分解为：

- part_eval `+3.043945 s`，占 `93.406%`；
- global_update `+0.208930 s`，占 `6.411%`；
- input_load `+0.005940 s`，占 `0.182%`。

所以剩余回退不是计时噪声或单一外层通信指标，而主要是 32 个 partition model 的
串行 eval 总量增加。

## 6. 最大项与其余 31 项

| 集合 | baseline eval | closure-aware eval | 增量 |
| --- | ---: | ---: | ---: |
| 最大项 | part_3 525.730 | part_8 357.448 | -168.282 us/step (-32.009%) |
| 去掉最大项后的 31 项 | 2038.986 | 2358.266 | +319.280 us/step (+15.659%) |
| 全 32 项 | 2564.716 | 2715.714 | +150.998 us/step (+5.887%) |

baseline part_3 的 AB/BA spread 只有 `0.048%`；candidate part_8 为 `2.694%`。
closure-aware 没有免费消除 work：它把 giant 降低约 168 us/step，但其余 31 项因
closure 复制/布局改变合计增加约 319 us/step，形成约 151 us/step 的净串行代价。
这与 static final graph ops `+4.480%`、exact closure sum `+3.012%` 同量级。

## 7. Page-local 与 identity gate

四个 C=10000 accepted samples 的最佳 executable snapshot 完全一致：

| arm/object | resident | coverage | local | remote | qualifying samples |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline ELF RX | 61,084 pages / 250,200,064 B | 98.912% | 250,200,064 B | 0 B | 24 / 24 |
| closure-aware ELF RX | 63,177 pages / 258,772,992 B | 98.824% | 258,772,992 B | 0 B | 26 / 25 |
| NEMU RX（四样本） | 71 pages / 290,816 B | 95.946% | 290,816 B | 0 B | 23..24 |

每个 sample 只观察到一个 `(PID,start_ticks)` model identity，page audit errors 为 0；
所有中间 qualifying sample 也通过 transient-local gate。两个 order 的 final staging
verification 均为 `6/6` records、0 mismatch，source/staged/final SHA 一致。
pooled validator 还确认 AB/BA 的 12 个 staged `(device,inode)` 全部互异。

持久输入 identity：

| 对象 | SHA-256 |
| --- | --- |
| baseline ELF | `355a2c7df9faec3e8f56591b53e5e214f7b0a3bf8453549bd3dc4cf55afadd77` |
| closure-aware ELF | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` |
| CoreMark image | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| v2 runner | `2019def21d67ef009041857c686136a686f58a156483bfa978fb5d3baa7f9f0a` |
| base runner | `3f50e79f1f47fbd81ed3f21d4fd71b27709d3ffd692f3853e0e88ee1fe2db9bd` |
| shared protocol | `3bd5681185f0b9d0c6acfd783b67001a86c8441644eef66307314360b8a33a70` |

## 8. Runtime quietness 与证据边界

| order/arm | guard mean/min idle | foreign ticks / strict limit | target unexplained / limit |
| --- | --- | --- | --- |
| AB baseline | 99.746% / 98.472% | 248 / 32 | 0.0077 / 0.3186 s |
| AB closure-aware | 99.791% / 98.621% | 212 / 34 | 0.0128 / 0.3377 s |
| BA closure-aware | 99.786% / 98.674% | 225 / 34 | 0.0200 / 0.3359 s |
| BA baseline | 99.747% / 98.733% | 236 / 32 | 0.0211 / 0.3156 s |

full-CCD guard、target unexplained-busy、affinity、page、PMU 与功能门均过；但轻量
foreign task ticks 为 strict limit 的约 `6.2x..7.8x`，所以 `runtime_audit.passed=false`
且本篇只能称 diagnostic。diagnostic 只豁免这一条，不能外推为 strict 性能 headline。

## 9. elapsed_wall_seconds 勘误

本轮 v2 的 `elapsed_wall_seconds` 为 `63.420 -> 67.353 s`（表面 `+6.201%`），
但该字段不能用于模型性能结论。runner 当前在 `process.wait()` 返回后执行
`audit.stop()`，完成 final `/proc` task/maps 扫描后才读取 elapsed；因此它包含
约 `1.53..2.97 s` 的审计收尾。BA candidate 的 audit 尾巴比其他样本多约 1.4 s，
人为放大该字段。

这不要求重跑当前 N=1：Host、task-clock、cycles 和 phase 四条独立证据均在
`+5.27%..5.38%` 闭合，page/quiet gate 也有充足裕量。进入 N=8/N=32 前必须派生
下一版 runner，在 `wait()` 返回瞬间记录 workload elapsed，并将 audit finalize
duration 单列；不得沿用 v2 `elapsed_wall_seconds` 比较并行 walltime。

## 10. 决策

1. `hyper_partition_weight` closure-aware 方案继续保留实验模式，不改 baseline 默认；
2. “该方法对并行速度无用”的旧判断继续撤销：本篇稳定确认 eval max `-32.009%`；
3. 同时承认串行代价：instructions `+5.377%`、eval sum `+5.887%`、Host `+5.283%`；
4. N=8/N=32 的裁决问题是 max/makespan 收益能否覆盖总 work、通信与调度开销，
   不能由 N=1 单独回答；
5. 按用户要求本阶段到 N=1 AB/BA 为止，不启动 N=8 或 N=32；
6. 下一步测 N>1 前先修正 workload/audit elapsed 分界，继续保留 page-local 硬门。

## 11. Artifact

Accepted runtime：

```text
build/repcut_closure_runtime_20260902/runs/
  node033_ccd64_cleanv4_pagelocalv2_diagnostic_ab_20260904_1630/
    accepted.json  SHA-256 a0116f9babafeda7f7f8bffeee390329ed83b8688378ee61957560b05a3c85e1
    attempts.jsonl SHA-256 aa1df8ed91e679069145f970495e3a4f297d0313cf7dc429e9264e455874f5f6
  node033_ccd64_cleanv4_pagelocalv2_diagnostic_ba_20260904_1630/
    accepted.json  SHA-256 c3bd022b34f46cdcdb9c00b3fd0aed1b9b7d5022972ad528d48ce45d0b7302df
    attempts.jsonl SHA-256 4e119a83c461240156a424fea8a6777e08ba928fc3b618c00fde3ae591c4a745
```

Summaries：

```text
build/repcut_closure_runtime_20260902/results/
  node033_ccd64_cleanv4_pagelocalv2_diagnostic_ab_20260904_1630/
    summary.json SHA-256 03e9cb137aaad06f04c7bc9bfecf8b86c0d2b107f9f7fefaf6d45366e0ab6d16
  node033_ccd64_cleanv4_pagelocalv2_diagnostic_ba_20260904_1630/
    summary.json SHA-256 7ebf6c25b31ae0db88ca1a3541f42a8829f08187ea145d203d9395517277cf02
  node033_ccd64_cleanv4_pagelocalv2_diagnostic_pooled_20260904_1630/
    summary.json SHA-256 519fb71ad038dbfb98c58835ae23d45df2fe82e7e014b78986a2f14c74a0a7d9
    per_partition_pooled.csv SHA-256 27bc14c60553104d5ce389a37908c222269c44dfecd3bb914775d230c9802d08
```

node030 未混池旁证：

```text
build/repcut_closure_runtime_20260902/runs/
  node030_ccd72_cleanv4_pagelocalv2_diagnostic_ab_20260904_1615/
  node030_ccd8_cleanv4_pagelocalv2_diagnostic_ab_20260904_1610/
  node030_ccd72_cleanv4_pagelocalv2_diagnostic_ba_20260904_1615/
```
