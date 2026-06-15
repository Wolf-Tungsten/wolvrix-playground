# NO0196 xs-components 2-eval 机制 vs XiangShan sink/succ —— 性能特征不一致诊断

记录日期：2026-06-14

关联：

- [`NO0189 §11`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md)：首次记录 XiangShan「单 eval 工作量两边≈0.96×、总工作量~1.93× 主因是 2 eval/cycle」，并把 model 2× vs 实测 8.4× 缺口归因于 sink/store-heavy + 事件派发。
- [`NO0194`](./NO0194_xs_real100_5s_profile_feature_delta_20260613.md)：xs-components real100 的 static / runtime-weighted `n_*` 差异。
- [`NO0195`](./NO0195_xiangshan_coremark50k_no_runtime_profile_speed_20260614.md)：XiangShan CoreMark 50k 裸跑 `7.93x`。
- 数据源 A（xs-components）：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/`。
- 数据源 B（XiangShan）：`tmp/no0190_xs_gsim_grhsim_runtime_profile_20260613_131543/`。
- 新增工具：`testcase/xs-components/tb/split_timing.cpp`（复用已编译 case 的 gsim model + grhsim lib，分别计时两次 eval）。

本文的结论是：**grhsim 相对 gsim 的慢，在 xs-components 与 full XiangShan 上是两种不同的瓶颈，不能用一套优化口径覆盖。**

---

## 1. xs-components real100 的机制：慢 = 每周期 2 次 eval 的 comp 体量

### 1.1 全部 gap 来自 comp 体量，per-op 反而更便宜

real100 4M、100 个 `XsReal*Large`，总账 gsim 958.0 s、grhsim 1288.0 s，**gap 1.344x**。comp-only 单变量模型对两边预测都落在 1% 内：

| | runtime-weighted `Σ f·n_comp` | 每 op 成本 | 预测 ms |
|---|---:|---:|---:|
| gsim | 16,511e8 | 586 ps/op | 968,199（实测 958,000）|
| grhsim | 27,501e8 | **468 ps/op** | 1,287,042（实测 1,288,029）|

即 `1.68（comp 体量）× 0.80（per-op）= 1.33x` ≈ 实测。**grhsim 的 codegen per-op 更便宜，gap 完全是 comp 体量被放大 1.68x。**

### 1.2 1.68x comp 的来源是「2 次 eval/cycle」，不是定点迭代、也不是稀疏性

- benchmark harness（`tb/xs_component_bench.hpp`）：gsim `drive → set_clock(1) → step()`（1 次/周期）；grhsim `drive → clock=0;eval() → 采样 → clock=1;eval()`（**2 次/周期**）。
- real100 全部 100 个 case：**单 supernode 最大 fire/cycle 恰好 = 2.00**，comp 加权均值 1.84，`0/100` 个 case 有内部定点多轮。→ 每次 `eval()` 一轮即收敛；1.84×/cycle 的节点重算 = 这两次 eval。
- real100 是满活动：gsim 100% 静态 comp 节点都落在 0.9–1.1 fire/cycle。**跨周期 activation 稀疏性收益 ≈ 0**（没有空闲 supernode 可跳）。

### 1.3 split_timing 实测：贵在 clock-low（compute），commit 便宜

对 20 个已编译 `Xs*Large`，分别计时两次 eval（1M vectors，ms 节选）：

| case | grh clk-low | grh clk-high | gsim step | ratio |
|---|--:|--:|--:|--:|
| XsLoadQueueRawLarge | 168 | 17 | 322 | **0.57**（grhsim 更快）|
| XsRobBankScanLarge | 413 | 17 | 352 | 1.22 |
| XsPlruLarge | 676 | 26 | 145 | 4.83 |
| XsIcacheReplRegsLarge | 681 | 90 | 47 | 16.4 |
| XsIssueBusyMaskLarge | 1214 | 1168 | 137 | 17.3 |

- clock-high eval（**含强制 commit 阶段**）在多数 case 是 ~17ms 地板 → **commit 分离不是瓶颈**。
- 贵的是 clock-low（输入驱动的组合 settle）。redundant 重算少时 grhsim 能反超 gsim（LoadQueueRaw 0.57x）。

### 1.4 「拆分有收益」的正确轴

两次 eval 之间输入不变，只有 `clock`(0→1) 与 commit 后的寄存器变。因此：纯输入组合锥在 clock-high 重算是浪费；纯寄存器锥在 clock-low 重算是浪费。粗 supernode 把两类锥混在一块 → 一类要算就拖着另一类。**正确的拆分轴 = 按「是否依赖 clock 沿 / 寄存器更新」分组，让第二次 eval 只激活后者**，而不是按「supernode 间互相无关」（满活动下后者 0 收益）。理论可回收上界 = `1 - 16511/27501 = 40%`（gsim 单 sweep 即地板），实际 < 40%（混合锥不可回收）。

---

## 2. XiangShan 对照：慢 = sink（状态写）+ a_succ（变动检测/事件派发）体量

数据源 B，XiangShan SimTop + coremark-2-iteration、50k cycle、difftest on。裸跑 gap = **7.93x**（NO0195）。统一口径 `Σ f·X`（已用原始 TSV 复核）：

| Σ f·X | gsim | grhsim | grh/gsim |
|---|---:|---:|---:|
| n_comp | 40,527,723,663 | 52,113,202,979 | 1.29x |
| n_src | 18,856,787,184 | 15,096,768,815 | 0.80x |
| n_sink | 1,843,388,719 | 39,688,582,279 | **21.53x** |
| n_const | 17,074,612,833 | 16,006,237,564 | 0.94x |
| a_succ | 3,762,489,186 | 54,847,516,421 | **14.58x** |

关键观察：

- grhsim 的 `a_succ`（54.8e9）是**所有项里最大的**，甚至超过 `n_comp`；`n_sink`（39.7e9）与 `n_comp`（52e9）同量级。而 gsim 这两项几乎可忽略（3.76e9 / 1.84e9）。
- 即 XiangShan 上 grhsim 的成本**集中在状态写（sink）和后继激活/变动检测（a_succ）**，不是 compute。`n_comp` 只有 1.29x。
- 这与 NO0189 §11 的「sink/store-heavy + 事件派发」一致，但现在是显式模型项而非残差：full core 的巨量状态（regfile/ROB/cache/TLB/LSQ）放大 sink，高扇出放大 a_succ 的 `old!=new` 比较点。

---

## 3. 结论：两套瓶颈，不能混用一套优化

| | xs-components real100 | XiangShan coremark 50k |
|---|---|---|
| gap | 1.34x | 7.93x |
| 主导项 | `n_comp` 1.68x（= 2 eval/cycle）| `n_sink` 21.5x + `a_succ` 14.6x |
| per-op codegen | grhsim 更便宜（0.80x）| sink/succ 路径昂贵 |
| commit/sink | clock-high ~17ms 地板，便宜 | sink 体量爆炸 |
| 该打的 lever | 削第二次 eval 的冗余 compute（按 clock/寄存器依赖分组）| 削 sink（状态写路径）+ a_succ（变动检测/激活派发）的体量与 per-op 成本 |

要点：

1. **性能特征确实不一致。** xs-components 是 compute-dominated、grhsim codegen 甚至更优、瓶颈是 2-eval；XiangShan 是 state/fanout-dominated、瓶颈是 sink + a_succ 机制开销。
2. **§1 的 2-eval 优化基本不能搬到 XiangShan。** 即便把 xs-components 的 comp 体量打掉，对 XiangShan 的 7.93x 只动到 `n_comp 1.29x` 那一小块；XiangShan 必须正面削 sink + a_succ（参考 NO0094 指出的 generic storage 间接、commit scalar table、batch 碎片化等实现成本，均可在不动 commit 分离语义的前提下优化）。
3. **方法论警告：xs-components real100 不能作为 full XiangShan 的代理基准。** 用它调参会把人引向 compute/2-eval 方向，而 XiangShan 真正的痛点（sink/succ）在 xs-components 上只有 3.0x / 3.5x，被严重低估。后续 XiangShan 优化的 profile 应以数据源 B 口径为准。

---

## 4. 后续可做的精确量化

- xs-components 侧：对 grhsim compute 节点做 input-only / register-only / mixed 可达性分类，按 clock-low / clock-high 各自 fire 加权，得到逐 supernode「可回收 comp」排名（指导按 clock/寄存器依赖的分组拆分）。
- XiangShan 侧：把 `Σ f·X` 表接 NO0190 的联合系数回归（`c_comp/c_src/c_sink/c_const/c_succ`），把 `n_sink`(21.5x)、`a_succ`(14.6x) 折算成实际墙钟占比，定位 sink 与 a_succ 各自贡献多少秒，再决定优先打哪条路径（状态写 codegen vs 变动检测/激活派发）。

---

## 勘误（增量更新 2026-06-14）：XiangShan 的 `n_sink 21.5x` / `a_succ 14.6x` 主要是计数口径假象，§2/§3 的「sink/succ 体量主导」结论作废

§2、§3 把 XiangShan 的 7.93x 归因到「grhsim 状态写体量 21.5x + 变动检测 14.6x」。进一步拆解后，这个归因**不成立**，原结论保留作为上下文，但以本节为准。

### 1. 两边 `n_sink` 计数口径不对齐

- gsim（`reference/gsim/src/cppEmitter.cpp:126`）：`n_sink` = **每个写节点计 1**（`NODE_REG_DST | NODE_WRITER | NODE_READWRITER`），与位宽/深度无关。
- grhsim（`wolvrix/lib/emit/grhsim_cpp.cpp:2755`）：`n_sink` = **每个 write-port op 计 1**（`kRegisterWritePort | kLatchWritePort | kMemoryWritePort | kMemoryFillPort`）。一个 memory / packed regfile 会被展开成成百上千个 write-port op。

### 2. 21.5x 的 99.7% 来自 79 个 banked memory / regfile

把 grhsim commit 行按 `n_sink` 宽度分桶：

| 宽度桶 | static n_sink | 加权 Σf·n_sink 占比 |
|---|---:|---:|
| wide（≥256 ops/行，banked memory）| 284,717（98.0%）| **99.7%** |
| mid（16–255）| 3,864 | 0.1% |
| small（<16）| 1,950 | 0.2% |

- 共 **79 个 wide commit 行**，最大的每行 `n_sink = 4096`（= memory 深度），firing ~3.0/cycle。
- 同一个 memory：grhsim 记 4096 个 sink，gsim 记 1 个 `NODE_WRITER`。再乘上 grhsim commit 行 entry 计数（n_sink 加权 2.73/cycle，commit 计数器在 supernode 入口自增、不是每次真实写）vs gsim event-driven 实际写 0.24/cycle，就凑出 21.5x。

### 3. `a_succ 14.6x` 是同一假象

grhsim `a_succ` 总量 54.85e9 里 **72.1%（39.56e9，与 wide-mem 的 Σf·n_sink 数值完全相同）落在同一批 79 个 memory 行**——grhsim 对每个 write-port op 各记一处变动检测。**剔除这些 memory 行后，`a_succ` 比值从 14.6x 降到 4.1x。**

### 4. 修正后的结论

- **gsim 的 `n_sink` 统计是对的**（每个写节点 1、event-driven fire ≈ 真实稀疏写），内部一致。grhsim 的 `n_sink` 量的是「展开了多少 write-port op × supernode 入口次数」，对 memory 会按深度爆炸，**两边口径不可比**。「grhsim 做了 21× 的状态写」是错读。
- 因此 **NO0190 README 的 headline（cost 集中在 n_sink 21.5x / a_succ 14.6x）与本文 §2/§3 的对应结论作废**：统一 `Σf·X` 在 full XiangShan 上被 memory/regfile 的计数粒度污染，不能用来归因 7.93x 墙钟。
- 剔除 memory 假象后，grhsim 相对 gsim 的 workload 其实接近（`n_comp 1.29x`、`n_src 0.80x`、`a_succ 4.1x`、非 memory `n_sink` 反而 < gsim）。**这说明 7.93x 主要是 per-op 墙钟成本（generic storage 间接、batch 碎片化、事件派发；见 NO0094 的 perf 归因 62% compute-batch / 34% commit-batch），不是 op 体量。**
- **未决问题**：这 79 个 banked memory 的 commit 在运行时究竟是「单条 indexed store」（则 4096 计数纯属 emit 假象、对墙钟≈0）还是「commit table 按 slot 迭代」（则是真开销、且就是头号瓶颈）。这要看 grhsim 对这些 memory/packed-regfile 的 commit codegen，或直接对二进制做 perf 归因，**不能从现有 TSV 判定**。
- 方法论：§3 表里「XiangShan 主导项 = n_sink/a_succ」一行按本勘误读作「被 memory 计数污染、需 perf 重测」；「xs-components 不能代表 full XiangShan」这一条仍然成立（但理由改为：real100 满活动掩盖了 XiangShan 的 per-op/低活动稀疏性差异，而非 sink 体量差异）。

---

## 二次更新（codegen 实证 2026-06-14）：那 79 个 memory 是 array-register 被展平，是 per-slot 真开销，不是 indexed store

直接读取生成代码 `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_100.cpp`（commit batch 100 = 仅 supernode 72145，4096-sink 之一）：

- 该 supernode body = **4090 条独立 `kRegisterWritePort` 语句**，每条形如：
  ```cpp
  if ((value_bool_slots_[12227]) != 0) {                       // per-field 写使能 guard
      const auto next_value = (grhsim_value_storage_ref<u8>(state_logic_storage_, 298696) & ~mask) | (data & mask);
      if (grhsim_value_storage_ref<u8>(..., 298696) != next_value) {  // 变动检测
          grhsim_value_storage_ref<u8>(..., 298696) = next_value;     // 实际写
          commit_activated_readers_ = true; supernode_active_curr_[...] |= ...;
      }
  }
  ```
- 全 batch **12,248 次 `grhsim_value_storage_ref` 间接访问**（每写 ~3 次：load old、compare、store）。
- 写使能不是单一外门，而是 ~10–15 个 per-field-group guard（`[214]` 管 844 条、`[12232]/.../[12223]` 各 ~307 条……），**没有把整组写折叠到一个 `if(write_enable)` 下**。
- 该 supernode firing 3.0/cycle（150,603 次 / 50k）。

对照 gsim：同一状态在 gsim `SimTop.h:133424` 声明为**真二维数组** `...providerUsefulCtr__DOT__value[64][8]`，用 **indexed store**（`value[idx][j]=…`）写，O(1)/实际写，记 1 个 `NODE_WRITER`，event-driven 0.24/cycle。

### 结论（对 §勘误 的再修正）

1. **不是 indexed store，是 per-slot 展平。** grhsim 的 aggregate/array-register lowering 把 gsim 的 `[64][8]` 寄存器数组**摊平成数千条 per-element scalar register-write**，commit 时逐条枚举。因此 `n_sink=4096` 对应**真实生成的代码**，不是纯 profile 假象。
2. **但「21× 写」仍是错读。** 两边写的是同一份架构状态；区别是 grhsim 每次 fire 付 **O(array_size) 的枚举 + per-field guard + generic storage 间接** 成本，而 gsim 是 O(1) indexed store。`Σf·n_sink` 既高估了「真正发生的写」（guard/变动检测会跳过多数），又恰好反映了「真实付出的枚举/间接工作量」——所以它不能当「写次数」用，但能指向真实热点。
3. **这 79 个展平数组是 7.93× 的真实大头候选。** 量级估算：79 × 4090 × 150k ≈ 48e9 次 op 执行，即便部分 guard 跳过，仍是数十秒级，占 327s gap 的可观比例。
4. **根因是 codegen，不碰 commit 分离。** 属 array-register 展平 / packed aggregate lowering（NO0185/NO0186/NO0188 preserve-aggregate、NO0047–063 merge_reg、NO0094 generic storage 同一主题）。修法 = 保留数组结构让 commit 退回 indexed store（或至少把 per-field guard 合并、消除 generic storage 间接），与 commit 分离语义正交。
5. **仍待 perf 终判：** 用 `build/xs/grhsim/emu` 对这批 `eval_commit_batch_*`（wide-memory supernode）做 perf 归因，确认它们占墙钟的确切比例，再决定优先级。codegen 已证「是 per-slot、真开销」，但「是否就是 7.93× 的头号项」需要 perf 数字坐实。
