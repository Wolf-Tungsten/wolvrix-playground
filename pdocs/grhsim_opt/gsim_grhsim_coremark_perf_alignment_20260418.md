# GSim vs GrhSIM CoreMark 性能特征对齐（2026-04-18）

本文把 [gsim_default_xiangshan_coremark_baseline_20260418.md](/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/gsim_default_xiangshan_coremark_baseline_20260418.md) 和 [grhsim_default_xiangshan_coremark_baseline_20260418.md](/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/grhsim_default_xiangshan_coremark_baseline_20260418.md) 放到同一口径下做对齐，目标不是重复列数字，而是回答：

- 两者真正的差异主要落在哪一层
- 后续 `grhsim` 优化应该优先追什么指标

## 对齐原则

- workload 对齐：都使用 `tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- CPU 绑定对齐：都使用 `taskset 0x1`
- host 环境对齐：同一台机器、同一编译器、同一系统
- `perf` 事件组对齐：都使用
  - `instructions`
  - `cycles`
  - `branches`
  - `branch-misses`
  - `cache-references`
  - `cache-misses`
  - `L1-dcache-loads`
  - `L1-dcache-load-misses`
- 两边 `perf stat` 都有约 `62.5%` multiplex，因此 miss rate 只看量级，不看很细的绝对值

## 不能机械对齐的地方

- `gsim` 能完整跑完 `1900000` simulated cycles
- 当前 `grhsim` full-run 预计约 `8.1` 小时，无法在同样成本下拿完整 workload
- 因此：
  - `gsim` 运行吞吐使用 full-run 结果
  - `grhsim` 运行吞吐和 `perf` 使用 `30000` cycle 采样窗口
- 这意味着：
  - “总 wall time”不能直接一一对比
  - “每 simulated cycle 的 host 成本”仍然可以直接对比，而且这是更可靠的归一化口径

## 核心对照

| 指标 | `gsim` | `grhsim` | `grhsim / gsim` |
| --- | ---: | ---: | ---: |
| emit wall time | `9:07.36` | `16:54.81` | `1.85x` |
| emit peak RSS | `68 GiB` | `67.67 GiB` | `~1.00x` |
| emitted `*.cpp` 数 | `167` | `9500` | `56.89x` |
| emitted source-only 大小 | `1.67 GiB` | `2.41 GiB` | `1.55x` |
| emitted source-only LOC | `10623627` | `1386914` | `0.13x` |
| 最终可执行文件 | `33 MiB` | `222 MiB` | `6.70x` |
| host 仿真速度 | `3843.82 cycles/s` | `65.11 cycles/s` | `0.0169x` |
| host IPC | `0.58` | `0.15` | `0.257x` |
| branch miss rate | `22.62%` | `17.86%` | `0.79x` |
| cache ref miss rate | `59.67%` | `52.01%` | `0.87x` |
| L1D load miss rate | `2.11%` | `3.82%` | `1.81x` |
| host cycles / sim cycle | `1475947` | `82692641` | `56.03x` |
| host instructions / sim cycle | `855218` | `12312731` | `14.40x` |
| branches / sim cycle | `54338` | `2038313` | `37.51x` |
| cache refs / sim cycle | `191282` | `2552621` | `13.34x` |

## 对齐后的结论

### 1. 主矛盾不是“miss rate 比 `gsim` 高很多”

如果只看 miss rate：

- `grhsim` branch miss rate 反而低于 `gsim`
- `grhsim` cache reference miss rate 也低于 `gsim`
- 只有 `L1D miss rate` 明显更高，但也还没高到能单独解释 `59x` 的速度差

因此，当前 `grhsim` 慢的主因不是：

- “分支预测比 `gsim` 差很多”
- “缓存 miss 比 `gsim` 差很多”

更准确的说法是：

- `grhsim` 每个 simulated cycle 让 host 执行了远多于 `gsim` 的动态工作
- 在这堆额外工作上，host 还跑出了更低的 IPC

### 2. 真正拉开差距的是“每个模拟周期的动态动作量”

归一化到每个 simulated cycle 后，`grhsim` 相比 `gsim`：

- host cycles 多 `56.0x`
- host instructions 多 `14.4x`
- branches 多 `37.5x`
- cache references 多 `13.3x`

这说明 `grhsim` 当前的热路径问题更像：

- 调度粒度过碎
- 控制流过多
- 激活传播和批次切换开销过大
- 每次进入有效工作前，要先走很多“调度自身的工作”

而不是单纯某一个 load/store 打到了慢内存。

### 3. `IPC` 是最值得盯住的运行时总指标

- `gsim`：`0.58`
- `grhsim`：`0.15`

这意味着即使 `grhsim` 做了大量额外工作，CPU 也没有高效地把这些工作吞下去。把前两条合在一起看，当前 `grhsim` 更像是：

- 动态指令数已经太多
- 这些指令的前端 / 分支 / 访存组织还不够友好

所以后续优化不能只盯：

- “减少 cache miss”
- “减少某个 helper 调用”

更应该盯：

- 能不能显著减少每 simulated cycle 的 host 指令数
- 能不能把低效控制流收缩掉，让 IPC 回升

### 4. 生成形态已经和 `gsim` 完全不在一个区间

两边 emitted source-only 大小只差 `1.55x`，但文件数差了 `56.9x`：

- `gsim`：少量大文件
- `grhsim`：海量碎文件，且 `9364` 个是 `sched_*.cpp`

这说明 `grhsim` 现在的问题不是“总代码量离谱到不可接受”，而是：

- file packing 过细
- 调度代码过碎
- 编译器很难把热路径收敛成 `gsim` 那种紧凑形态

从这个角度看，`grhsim` 的 emitted 结构本身就已经在向运行时性能施压。

### 5. `grhsim_emit` 目录大小不能直接拿来和 `gsim model/` 比

`grhsim_emit/` 里有一个：

- `grhsim_SimTop_declared_value_index.txt = 22.37 GiB`

所以后续继续做体量对比时，建议固定拆成三层：

- source-only emitted code
- auxiliary index / debug files
- compile outputs / final binary

否则“目录大小”这个指标会被辅助文件污染。

## 对 `grhsim` 优化最值得追的对齐指标

如果后面要做每轮优化复测，我建议固定追这 8 项：

1. `host instructions / simulated cycle`
2. `host cycles / simulated cycle`
3. `IPC`
4. `branches / simulated cycle`
5. `cache references / simulated cycle`
6. emitted `sched_*.cpp` 文件数
7. emitted source-only 总大小
8. 最终 `emu` 大小

其中优先级最高的是前 4 项，因为它们最直接反映：

- 调度框架本身有多重
- 每个 supernode 被激活后，host 到底在做多少额外控制流工作

## 当前最合理的优化方向

基于这次对齐，后续 `grhsim` 更值得优先做的是：

- 收缩 emitted 调度碎片度，减少 `sched_*.cpp` 数量
- 降低 active/batch/supernode 切换带来的控制流密度
- 减少每 simulated cycle 的分支数和 cache reference 数
- 让编译器更容易把热路径收敛成更连续、更少跳转的代码

不建议把主要精力先放在：

- 单独追 `branch miss rate`
- 单独追 `cache miss rate`

因为这两个指标虽然能改善，但它们目前还不像“动态工作量过大 + IPC 太低”那样解释力强。

## 一句话总结

`grhsim` 当前相对 `gsim` 的核心差异，不是“单次访存更差”，而是“每个 simulated cycle 做了太多碎而低效的调度/控制工作”，最终表现为：

- `56x` 的 host cycles / sim cycle
- `14x` 的 host instructions / sim cycle
- `37x` 的 branches / sim cycle
- 只有 `0.15` 的 IPC
