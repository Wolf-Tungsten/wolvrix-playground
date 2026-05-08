# NO0072 XS GrhSIM vs Reference GSim 结构与 CoreMark 50k Fresh 复测

> 归档编号：`NO0072`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

这份记录固定一次按最新代码重新执行的 XiangShan `grhsim` / `gsim` 对比复测，目标不是做方案设计，而是先把当前事实口径钉住：

- 两边是否已经在 supernode 数量上接近
- 两边的超节点 DAG 边数是否仍有明显差距
- `grhsim` 当前 host 二进制体量和静态指令数到底比 `gsim` 大多少
- 同样 `coremark` `50k cycle` 口径下，两边最新速度差距是多少
- 这些数据对后续 `grhsim_opt` 主线优化意味着什么

本次 `gsim` 明确使用 `reference/gsim` 中的插桩版本，不使用其他历史目录或未插桩构建。

## 2. 执行口径

### 2.1 版本

- `wolvrix` HEAD: `5b3f444`
- `reference/gsim` HEAD: `1a82e6b`

### 2.2 公共输入

为了保证 `grhsim` 和 `gsim` 比较的是同一份 XiangShan 仿真器输入，本次没有额外引入新的 RTL 生成变量，而是统一复用当前工作区里的同一份输入：

- FIR: `build/xs/rtl/rtl/SimTop.fir`
- filelist: `build/xs/wolf/wolf_emit/xs_wolf.f`
- workload: `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`
- difftest so: `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`

### 2.3 Fresh 复测约束

本轮不是读取旧 note 或历史 stats 直接汇总，而是重新执行并重新取数：

- `gsim` 重新生成并重新构建
- `grhsim` 重新 emit 并重新构建
- 两边重新跑 `coremark` `50k cycle`
- `grhsim` 禁止复用旧的 post-stats resume 结果
- 额外对 `gsim` 做一次 JSON dump，用来补齐 compact stats 不直接暴露的超节点出度分布

### 2.4 实验目录

所有本次复测产物都放在：

```text
tmp/xs_grhsim_gsim_struct_20260506_144707
```

## 3. 关键产物

### 3.1 `gsim`

- build log:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/gsim_build.log`
- `50k` 运行 log:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/gsim_coremark_50k.log`
- compact stats:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/gsim/gsim-compile/model/SimTop_0InstsGenerator_Stats.json`
- JSON dump stats:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/gsim_dump/SimTop_0InstsGenerator_Stats.json`
- JSON dump graph:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/gsim_dump/SimTop_0InstsGenerator.json`
- dump 后处理出的超节点出度统计:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/gsim_dump/gsim_supernode_out_degree_stats.json`

### 3.2 `grhsim`

- emit log:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_emit.log`
- build log:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_build.log`
- `50k` 运行 log:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_coremark_50k.log`
- supernode stats:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/grhsim/grhsim_emit/activity_schedule_supernode_stats.json`
- post-stats:
  - `tmp/xs_grhsim_gsim_struct_20260506_144707/grhsim/wolvrix_xs_post_stats.json`

## 4. 指标口径说明

这份对比里有一组能直接比的指标，也有一组只能近似参考的指标。

可直接比较：

- `supernode_count`
- `supernode_edge_count` / `dag_edges`
- 最终 `emu` 文件大小
- `.text` 大小
- 静态反汇编指令数
- `coremark` `50k` 的 host time / IPC / RSS

不能直接当作同义比较：

- `gsim supernodes_members`: 每个 supernode 包含的 `Node` 数
- `grhsim ops_per_supernode`: 每个 supernode 包含的调度 `op` 数

以及：

- `gsim supernodes_enodes`: 每个 supernode 挂接的唯一 `ENode` 数
- `grhsim out_degree_per_supernode`: 每个 supernode 指向其他 supernode 的出边数

因此本 note 的重点判断顺序是：

1. 先看 supernode 总量和边总量
2. 再看生成代码体量和静态指令数
3. 最后用运行时数据判断“结构差异是否真的传导成了速度差异”

## 5. 结构统计

### 5.1 主统计

| 指标 | `gsim` | `grhsim` |
| --- | ---: | ---: |
| supernode 数 | 84719 | 85056 |
| supernode 边数 | 645828 | 722809 |
| node 数 | 2708093 | - |
| node 边数 | 4902114 | - |
| dep 边数 | 5352058 | - |

直接结论：

- `grhsim` supernode 数仅比 `gsim` 多 `337`
- `grhsim` 超节点 DAG 边数比 `gsim` 多 `76981`
- 边数比约为 `1.119x`

这说明当前主要差距已经不是“supernode 数量没有靠近”，而是“跨 supernode 连接仍然更多”。

### 5.2 `gsim` supernode 负载分布

来自 `SimTop_0InstsGenerator_Stats.json`：

| 指标 | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| members / supernode | 31.9656 | 14 | 34 | 283 | 9913 |
| enodes / supernode | 163.043 | 62 | 157 | 1447 | 272726 |

### 5.3 `grhsim` supernode 负载分布

来自 `activity_schedule_supernode_stats.json`：

| 指标 | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| ops / supernode | 73.7095 | 32 | 120 | 676 | 45072 |
| out-degree / supernode | 8.4980 | 4 | 17 | 78 | 6364 |

### 5.4 `gsim` 超节点出度分布补采样

`gsim` compact stats 没有直接给出 out-degree 分布，因此本次额外对：

```text
tmp/xs_grhsim_gsim_struct_20260506_144707/gsim_dump/SimTop_0InstsGenerator.json
```

做了一次 node->super / edge->cross-super 聚合。

聚合结果：

| 指标 | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gsim` out-degree / supernode | 7.6231 | 2 | 16 | 76 | 13739 |

其他值：

- supernode 数：`84720`
- cross-super edge 数：`645829`
- 0 出度 supernode 数：`31561`

注意：

- 这组值来自单独的 instrumented dump run
- 与 build 产物中的 compact stats 相比，出现了 `+1 supernode / +1 edge` 的微小差异
  - build stats: `84719 / 645828`
  - dump stats: `84720 / 645829`
- 偏差量级极小，不影响宏观判断，但后续引用时应区分来源

### 5.5 结构侧结论

从当前数据看：

- `grhsim` 与 `gsim` 的 `p90/p99` 出度分布已经相当接近：
  - `grhsim`: `17 / 78`
  - `gsim`: `16 / 76`
- 但 `grhsim` 平均出度仍更高：`8.4980` vs `7.6231`
- `grhsim` 总边数也更高

这意味着 `grhsim` 的问题不是“所有尾部都更坏”，而是整体上还保留了更多跨 supernode 依赖。

## 6. 生成代码规模

### 6.1 生成 `.cpp` 数量

| 指标 | `gsim` | `grhsim` |
| --- | ---: | ---: |
| model / emit `.cpp` 数 | 331 | 1205 |
| 其中 sched `.cpp` 数 | - | 1178 |

`grhsim` 的代码拆分明显更碎，生成 `.cpp` 文件数约为 `gsim` 的 `3.64x`。

### 6.2 最终 `emu` 体量

| 指标 | `gsim` | `grhsim` | 比值 |
| --- | ---: | ---: | ---: |
| 文件大小 | 56016016 | 123556048 | `2.21x` |
| `.text` (`size`) | 55892506 | 123266233 | `2.21x` |
| `.data` | 9248 | 9360 | `1.01x` |
| `.bss` | 14688 | 14688 | `1.00x` |
| `.text` section size (`readelf`) | `0x2e863f7` | `0x707f47f` | `2.21x` |

## 7. 静态二进制指令数

统计方法：

- 对最终 `emu` 做 `llvm-objdump -d`
- 统计反汇编中形如 `^[0-9a-f]+:` 的指令行数

结果：

| 指标 | `gsim` | `grhsim` | 比值 |
| --- | ---: | ---: | ---: |
| 静态指令数 | 9840233 | 22337260 | `2.27x` |

这一组数据和 `.text` 大小趋势一致，说明当前 `grhsim` 的 host 代码问题首先是“总量更大”，而不是只在局部生成了更差的机器码。

## 8. CoreMark 50k 结果

运行日志：

- `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/gsim_coremark_50k.log`
- `tmp/xs_grhsim_gsim_struct_20260506_144707/logs/grhsim_coremark_50k.log`

两边都跑到约 `50000` host cycle / 仿真循环上限。这里需要先澄清一个最容易误判的点：

- `gsim` 的 `step()` 是一个完整周期
- `grhsim` 的 `eval()` 是半周期
- `emu.cpp` 对 `grhsim` 的一个 `single_cycle()` 会执行：
  - `clock=1; eval()`
  - `clock=0; eval()`
  - 然后 `cycles++`

也就是说：

- `gsim 50k` 不是“实际上跑了 100k”
- `grhsim` 也不是因为一次 `single_cycle()` 里做了两次 `eval()`，所以“实际周期翻倍”

本次进一步排查后，可以确认当前 XiangShan 配置下，`trap->instrCnt/cycleCnt` 不是“半周期口径搞错”的假差异，而是 DUT 真实上报的退休统计：

- `trap->instrCnt` 来自 ROB 内部累计退休计数器
- `trap->cycleCnt` 来自 ROB 的 `timer`
- `DiffTrapEvent` 在 ROB 中直接连到这两个量
- 当前 XiangShan 顶层使用 `Gateway.setConfig("U")`，不会经过会改变 `TrapEvent.needUpdate` 语义的 endpoint/validate 路径
- `DiffExtTrapEvent` 是 `posedge` DPI 调用，因此当前 `trap` 统计不是“很久没刷新”的陈旧值

所以，日志中的 `instrCnt/cycleCnt/IPC` 差异应视为：在同样约 `50k` 个完整周期后，`grhsim` 与 `gsim` 实际执行进度不同。

结果：

| 指标 | `gsim` | `grhsim` | 比值 |
| --- | ---: | ---: | ---: |
| instrCnt | 73584 | 22484 | `0.305x` |
| cycleCnt | 49998 | 49996 | - |
| IPC | 1.471739 | 0.449716 | `0.306x` |
| Host time | 32492 ms | 282707 ms | `8.70x` |
| cycles/s | 1538.8 | 176.8 | `0.115x` |
| Peak RSS | 59660 KB | 140792 KB | `2.36x` |

### 8.1 运行侧结论

这里最需要避免的误读，不再是“是不是把半周期算成了完整周期”，这一点已经排除。

当前能直接确认的，只有：

- 在当前 `50k` bounded run 口径下，`grhsim` 的 host time 明显更长
- `grhsim` 的峰值 RSS 更高
- `grhsim` 与 `gsim` 的 DUT 内部退休进度确实不同

但下面这组量：

- 同样约 `50k cycle` 窗口内，`grhsim` 只提交了 `22484` 条指令
- `gsim` 提交了 `73584` 条指令
- `grhsim IPC = 0.449716`
- `gsim IPC = 1.471739`

现在更合理的解释是：

1. 两边在 `50k` 完整周期时，程序已经跑到了不同的架构位置
2. `grhsim` 的退休进度明显落后
3. 这不是外层 cycle limit 把 `gsim` 多跑了一倍
4. 更像是 `grhsim` 的行为已经和 `gsim` 分叉，或在某段路径上长期低效 / 卡顿

一个很强的旁证是最终 PC 本身也不同：

- `gsim`: `pc = 0x8000131e`
- `grhsim`: `pc = 0x8000042c`

所以后续如果继续比较 `guest IPC`，可以继续用这组数，但必须把它理解为“当前 `grhsim` 的真实执行进度更差”，而不是“单纯统计口径没对齐”。

### 8.2 `10k` / `20k` commit trace 对齐复查

为了确认 `50k` 差异不是统计误读，本次又补跑了两组 commit trace：

- `tmp/xs_commit_trace_10k/gsim_10k_commit.log`
- `tmp/xs_commit_trace_10k/grhsim_10k_commit.log`
- `tmp/xs_commit_trace_20k/gsim_20k_commit.log`
- `tmp/xs_commit_trace_20k/grhsim_20k_commit.log`

结果分成两段：

1. `10k` 时，两边 commit trace 完全一致。
2. `20k` 时，`grhsim` 的全部 commit 序列仍然是 `gsim` 的前缀，但长度明显更短。

具体说：

- `10k`：
  - 两边解析出的 commit 条目数完全一致
  - `(pc, inst)` 公共前缀长度等于全长
  - 两边最终 `instrCnt` 都是 `458`
- `20k`：
  - `gsim` 解析出 `13949` 条 commit
  - `grhsim` 解析出 `6671` 条 commit
  - `(pc, inst)` 公共前缀长度为 `6671`
  - `grhsim` 没有先提交出“错误指令”，而是从某个时刻开始推进速度落后

这一步的意义很直接：

- 到 `10k` 为止，两边仍是同一条执行轨迹
- 到 `20k` 为止，`grhsim` 仍在 `gsim` 的同一条轨迹上，只是明显更慢
- 所以当前主要矛盾不是“很早就功能错了”，而是“`10k` 之后退休密度开始持续掉队”

### 8.3 `10k-20k` 逐周期提交密度对齐

为了把“掉队”量化，本次又用 `EMU_PROGRESS_EVERY_CYCLES=1` 逐周期采样：

- `tmp/xs_progress_20k_cyclewise/gsim_20k_progress.log`
- `tmp/xs_progress_20k_cyclewise/grhsim_20k_progress.log`

每条记录都包含：

- `host_cycles`
- `model_cycles`
- `instr`
- `commit_pc`
- `trap_pc`

#### 8.3.1 首次偏离点

在 `10k` 边界附近，两边直到 `10009` 周期仍完全一致：

- `instr = 458`
- `commit_pc = 0x80001cdc`
- `trap_pc = 0x800027c6`

真正的第一个退休计数偏离点出现在 `10010`：

- `gsim`: `instr = 459`, `trap_pc = 0x800027ca`
- `grhsim`: `instr = 458`, `trap_pc = 0x800027c6`

第一个 `commit_pc` 偏离点出现在 `10012`：

- `gsim`: `commit_pc = 0x80001ce2`
- `grhsim`: `commit_pc = 0x80001cdc`

这说明：

- `10k` 之后不是突然跳到另一条错误轨迹
- 而是从很小的退休节拍差开始，随后逐步累积成大 gap

#### 8.3.2 分段退休密度

把 `10001-20000` 按每 `1000` 周期切分，统计每段新增退休指令数：

| 周期窗口 | `gsim` 新增 instr | `grhsim` 新增 instr | gap | `gsim` instr/cycle | `grhsim` instr/cycle |
| --- | ---: | ---: | ---: | ---: | ---: |
| `10001-11000` | 398 | 398 | 0 | 0.398 | 0.398 |
| `11001-12000` | 225 | 220 | 5 | 0.225 | 0.220 |
| `12001-13000` | 1759 | 1613 | 146 | 1.759 | 1.613 |
| `13001-14000` | 1256 | 1051 | 205 | 1.256 | 1.051 |
| `14001-15000` | 1444 | 607 | 837 | 1.444 | 0.607 |
| `15001-16000` | 1356 | 520 | 836 | 1.356 | 0.520 |
| `16001-17000` | 1738 | 584 | 1154 | 1.738 | 0.584 |
| `17001-18000` | 1777 | 420 | 1357 | 1.777 | 0.420 |
| `18001-19000` | 3019 | 401 | 2618 | 3.019 | 0.401 |
| `19001-20000` | 694 | 443 | 251 | 0.694 | 0.443 |

整个 `10k-20k` 窗口的平均退休密度：

- `gsim`: `(14124 - 458) / 10000 = 1.3666 instr/cycle`
- `grhsim`: `(6715 - 458) / 10000 = 0.6257 instr/cycle`

也就是：

- `grhsim` 在这一段的退休密度约为 `gsim` 的 `45.8%`

#### 8.3.3 累计差距的增长

从逐周期累计值看，`gsim - grhsim` 的退休差距在下面这些点跨过阈值：

- `>= 10`：cycle `8256`
- `>= 50`：cycle `10749`
- `>= 100`：cycle `12132`
- `>= 500`：cycle `14353`
- `>= 1000`：cycle `14709`
- `>= 2000`：cycle `15978`
- `>= 5000`：cycle `18239`
- `>= 7000`：cycle `18905`

如果只看 `10k` 之后，增长速度最明显的阶段是：

- `14001-19000`

尤其 `18001-19000`：

- `gsim` 一段内退休 `3019`
- `grhsim` 同段只退休 `401`

#### 8.3.4 零提交占比与长停顿

在 `10000-20000` 这 `10001` 个逐周期样本里，单周期退休增量分布如下：

- `gsim`
  - `delta = 0` 的周期数：`6573`
  - `delta = 8` 的周期数：`744`
- `grhsim`
  - `delta = 0` 的周期数：`7865`
  - `delta = 8` 的周期数：`293`

最长连续零提交区间：

- `gsim`: `56` 周期，`15870-15925`
- `grhsim`: `58` 周期，`11314-11371`

更有代表性的是“`gsim` 还在前进，而 `grhsim` 完全不退休”的最长连续区间：

- `12120-12157`
- 连续 `38` 个周期
- 这段里 `gsim` 额外退休了 `307` 条指令，而 `grhsim` 为 `0`

这和 `20k` commit trace 的“同轨但更慢”结论是一致的：问题不是单点错误提交，而是 `grhsim` 更频繁地落入长停顿。

#### 8.3.5 按相同退休进度回看 `gsim` 时间滞后

如果把 `grhsim` 在某一周期达到的 `instrCnt`，映射回 `gsim` 是在第几周期达到同样进度，可以直接看出时间滞后：

| `grhsim` 周期 | `grhsim` instr | `gsim` 达到同 instr 的周期 | `grhsim` 相对滞后 |
| --- | ---: | ---: | ---: |
| `10000` | 458 | 9962 | 38 cycles |
| `11000` | 856 | 10958 | 42 cycles |
| `12000` | 1076 | 11930 | 70 cycles |
| `13000` | 2689 | 12947 | 53 cycles |
| `14000` | 3740 | 13673 | 327 cycles |
| `15000` | 4347 | 14194 | 806 cycles |
| `16000` | 4867 | 14519 | 1481 cycles |

到 `17000` 以后，`grhsim` 的累计退休数已经低到连 `20k` 周期内的 `gsim` 都找不到同值点：

- `17000`: `5451`
- `18000`: `5871`
- `19000`: `6272`
- `20000`: `6715`

说明到这时为止，`gsim` 在更早的时候就已经把这段进度远远甩开了。

### 8.4 运行侧补充结论

基于 `10k` / `20k` commit trace 和 `10k-20k` 逐周期进度日志，现在可以把运行侧结论收紧为：

1. `gsim 50k` 不是“实际跑了 100k”，这个口径问题已经排除。
2. `10k` 时两边执行轨迹仍一致。
3. `20k` 时 `grhsim` 的 commit 序列仍是 `gsim` 的前缀，说明它还在同一条轨迹上，但推进明显更慢。
4. 真正的异常形态是：`10k` 之后 `grhsim` 的退休密度持续低于 `gsim`，并且更频繁落入长零提交区间。
5. 因此 `50k` 时巨大的 `instrCnt` / `PC` 差异，应理解为“持续推进效率差导致的真实执行进度分叉”。

### 8.5 Verilator `20k` 锚点复核

为了排除“`gsim` 自己就偏离了标准 Verilator 行为”的可能，本次又补跑了一次 Verilator ref `20k coremark` commit trace：

- `tmp/xs_commit_trace_20k/verilator_20k_commit.log`

运行结果：

- `instrCnt = 14121`
- `cycleCnt = 19996`
- cycle limit 时 `pc = 0x80000440`
- commit trace 条目数：`13949`

把三方 commit 序列按 `(pc, inst)` 做公共前缀比较，结果如下：

| 对比项 | 公共前缀长度 | 说明 |
| --- | ---: | --- |
| `gsim` vs `verilator` | `13949` | 全长完全一致 |
| `grhsim` vs `verilator` | `6671` | `grhsim` 仍只是前缀 |
| `gsim` vs `grhsim` | `6671` | 与前面结论一致 |

也就是说：

- `verilator` 的 `20k` commit trace 与 `gsim` 完全一致
- `grhsim` 不是“跟 Verilator 一样，只是和 `gsim` 不一样”
- 当前偏慢、偏短的那一支就是 `grhsim`

这里 `verilator` 与 `gsim` 的 `instrCnt` 有 `14121` vs `14124` 的微小差异，但 commit trace 条目数和 `(pc, inst)` 序列完全一致，因此这更像是统计口径上的细节差异，而不是执行轨迹差异。本次要回答的核心问题不受影响：

- `20k` 执行轨迹上，`gsim` 与 `verilator` 站在同一边
- `grhsim` 明确不在这一边

### 8.6 访存返回路径排查：不是外部 RAM 慢，而是 helper 可见性时序不同

结合用户提出的“会不会是访存返回更慢”这一方向，本次又把内存后端和 RAM helper 时序单独拆开核查，结论需要分两层说。

#### 8.6.1 当前运行没有走外部 DRAMsim3

先看这次 `20k` / `50k` 运行日志，三边都只有：

- `Using simulated 8386560MB RAM`

没有出现 `DRAMSIM3 config:` / `DRAMSIM3 outdir:` 之类输出。因此当前跑的不是带外部 DRAM 模型的路径，而是本地 `mmap` RAM。

对应 C++ 后端代码也一致：

- `MmapMemory` 用 `mmap` 分配本地内存
- `difftest_ram_read()` 直接 `return simMemory->at(rIdx);`
- `difftest_ram_write()` 直接原地更新内存

所以这次 `grhsim` 掉队，不能解释成：

- host 侧 DRAMsim3 更慢
- 与外界交互更慢
- 外部 memory backend 响应更晚

当前排查里，“外部内存返回慢”这条路径可以先排除。

#### 8.6.2 `gsim` 的 RAM helper 读返回是当周期可见

`Mem.scala` 对 `Mem1R1WHelper` 明确分了两种实现：

- `GSIM` 下：
  - `assign r_0_async = 1'b1`
  - `always @(*)`
  - `r_0_data = difftest_ram_read(r_0_index);`
- 非 `GSIM` 下：
  - `assign r_0_async = 1'b0`
  - `always @(posedge clock)`
  - `r_0_data <= difftest_ram_read(r_0_index);`

生成出来的 `Mem1R1WHelper.v` 也保留了这个分支。

同时，`gsim` 生成 C++ 的局部实现能直接看到：

- `Mem1R1WHelper(...)` 在同一段逻辑里被调用
- `helper_0.r.async` 被置成 `1`
- 紧接着用
  - `helper_0.r.data`
  - 或旧寄存值 `r`
  进行 mux

也就是说，`gsim` 这条 `difftest_ram_read -> helper data -> read_0_data_*` 的路径，是按“本周期组合可见”来走的。

#### 8.6.3 `grhsim` 当前把同一条 helper 读路径物化成了 `posedge` 状态更新

在 `grhsim` 的 `wolvrix_xs_post_stats.json` 中，这条路径对应的关键 op 是：

- `_op_11102350`
  - `kind = kDpicCall`
  - `targetImportSymbol = difftest_ram_read`
  - `eventEdge = ["posedge"]`
- `_op_11102355`
  - `kind = kRegisterWritePort`
  - `regSymbol = cpu$memory$ram$rdata_mem$helper_0$r_0_data_1`
  - `eventEdge = ["posedge"]`
- `_op_11826046`
  - 从 `cpu$memory$ram$rdata_mem$helper_0$r_0_data` 再切片生成
    `cpu$memory$ram$rdata_mem$_helper_0_r_0_data`

对应生成调度代码里还能看到更具体的物化形态：

1. 在 `grhsim_SimTop_sched_551.cpp` 里：
   - 只有在 `event_edge_slots_[0] == posedge` 时，才调用 `difftest_ram_read(...)`
   - 返回值先写入 `value_u64_slots_[27818]`
2. 在 `grhsim_SimTop_sched_1018.cpp` 里：
   - 同样只在 `posedge` 下，把上面的返回值提交到
     `grhsim_state_slot_450776`
3. 在 `grhsim_SimTop_sched_4.cpp` 里：
   - 再从 `grhsim_state_slot_450776` 读出，
     形成 `cpu$memory$ram$rdata_mem$_helper_0_r_0_data`

这说明在 `grhsim` 当前实现里，同一条 helper read 路径已经被拆成：

`difftest_ram_read` DPI 调用
-> `posedge` 写入 helper 状态
-> 后续 supernode 再读取 helper 输出

它不再等价于 `gsim` 那种“同周期组合可见”的 helper 返回。

#### 8.6.4 这和当前 `20k` / `50k` 掉队现象是相符的

前面已经确认：

- `10k` 时 `gsim == grhsim`
- `20k` 时 `grhsim` 仍是 `gsim` 的 commit 前缀，只是更慢
- `verilator == gsim`

所以现在更合理的解释不是“功能错得很早”，而是：

1. `grhsim` 在 memory-related feedback 上，比 `gsim/verilator` 多了一拍或多了额外阶段
2. 这种差异不会直接触发 difftest，因为 difftest 不建模 commit 之间的时间间隔
3. 但它会在 load / store / polling / replay / wakeup 密集区，把退休密度持续拉低

因此，沿“访存返回更慢”这个方向，当前最收敛的判断是：

- 不是外部 memory backend 更慢
- 而是 `grhsim` 对 `Mem1R1WHelper` 这类 RAM helper 的内部时序建模，当前比 `gsim/verilator` 更偏向同步化/阶段化
- 这很可能就是 `10k` 之后逐步掉队的重要原因之一

## 9. 对 `grhsim_opt` 主线的直接约束

这次 fresh 复测会直接约束后面的优化方向。

### 9.1 不应再把 “supernode 数量对齐” 当成主 KPI

当前已经是：

- `gsim`: `84719`
- `grhsim`: `85056`

两边 supernode 数量已经足够接近。继续把主要精力放在“让 supernode 数量再更像一点”，从这组数据看，回报不会高。

### 9.2 应优先压缩跨 supernode 边数

当前更扎眼的是：

- `grhsim` 边数更高：`722809` vs `645828`
- 平均出度更高：`8.4980` vs `7.6231`

这比“数量差 337”更接近真实问题。

### 9.3 应优先压缩 host 代码总量

当前 `grhsim` 相对 `gsim`：

- `.text` 约 `2.21x`
- 静态指令数约 `2.27x`
- 生成 `.cpp` 文件数约 `3.64x`

这说明后续值得优先做的是：

- 收缩 supernode body
- 减少碎片化 `sched_*.cpp`
- 减少为了调度边界暴露出来的额外 host 代码

### 9.4 必须把“进度分叉”当成真实问题处理

这次排查已经能排除两条最容易误判的解释：

- 不是 `gsim 50k` 实际跑了 `100k`
- 也不是 `grhsim` 的 `eval()` 半周期导致外层 cycle limit 口径翻倍

因此后续要处理的不是“重新解释统计”，而是直接处理：

- 为什么 `grhsim` 在同样约 `50k` 完整周期后只退休了 `22484` 条指令
- 为什么 `grhsim` 在 `0x8000042c` 附近明显落后于 `gsim`

这类问题更接近功能/执行进度分叉，而不只是 host 侧性能问题。

## 10. 结论

这次按最新代码重新执行后，可以固定几个结论：

1. `grhsim` 的 supernode 数量已经和 `gsim` 很接近，主问题不再是 supernode 数量未对齐。
2. `grhsim` 的超节点 DAG 仍更稠密，边数约为 `gsim` 的 `1.12x`。
3. `grhsim` 生成出的 host 二进制仍显著更大：
   - `.text` 约 `2.21x`
   - 静态指令数约 `2.27x`
   - 生成 `.cpp` 文件数约 `3.64x`
4. `coremark 50k` 上，`grhsim` 最新 host time 仍约慢 `8.70x`。
5. `instrCnt/cycleCnt/IPC` 差异不是由 `gsim step` / `grhsim eval` 周期口径造成的；两边在 `50k` 完整周期时的执行进度确实不同。
6. 最终 PC 也不同，说明 `grhsim` 与 `gsim` 在该 workload 上已经出现真实进度分叉，而不是单纯统计显示差异。

因此，对 `grhsim_opt` 主线最直接的结论是：

- 不要再把“对齐 supernode 数量”当成主目标
- 应该把重点转向“减少跨 supernode 边数 + 收缩 host 代码总量”
- 同时把 `0x8000042c` 附近的执行进度分叉作为独立问题继续往下查
