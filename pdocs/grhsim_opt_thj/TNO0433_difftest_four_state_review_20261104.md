# TNO0433：DiffTest 四种配置的复核与仿真性能归因

日期：2026-11-04。

本记录把已经完成的实验统一成三个开关层次：Chisel/RTL 是否生成 DiffTest 硬件，Wolvrix
模型是否保留采集路径，以及运行时是否加载 NEMU 并执行 DiffTest 检查。这样可以区分
“生成出来的结构变大”“模型中保留采集支持”和“每次运行做参考模型检查”这三类成本。

## 四种状态

| 状态 | Chisel/RTL 生成 | Wolvrix 读入和编译 | 运行命令 | 参考模型 |
| --- | --- | --- | --- | --- |
| S0 | `DISABLE_DIFFTEST=1`，`--disable-difftest`；`EnableDifftest`/`AlwaysBasicDiff` 关闭，0 个接口 | 不定义 `DIFFTEST`；`NO_DIFF=1` | `--no-diff` | 无 |
| S1 | DiffTest 开启，106 个接口 | 不定义 `DIFFTEST`；`NO_DIFF=1` | `--no-diff` | 无 |
| S2 | 与 S1 相同 | 定义 `DIFFTEST`；`NO_DIFF=0`，保留采集能力 | `--no-diff` | 无 |
| S3 | 与 S1/S2 相同 | 与 S2 相同 | `--diff` | 加载 NEMU |

对应产物如下：

- S0 是 TNO0401 的生成关闭 B；RTL、模型和 harness 都没有 DiffTest 采集路径。
- S1 是 TNO0401 的生成开启 A，也是 TNO0432 的 A；RTL 中有接口，但 Wolvrix 读入和 harness
  都关闭采集支持。
- S2 是 TNO0432 的 A′；模型和 harness 保留采集路径，运行时不启用参考检查。
- S3 是 TNO0432 的 B；模型、harness 和运行时检查全部开启。

S0→S1 的直接配对结果来自 TNO0401；S1→S2 和 S2→S3 来自同一轮 TNO0432。绝对 Host
秒数来自不同测量批次，因此用于定位规模；归因优先使用每个相邻状态的配对百分比。

这里的优化目标不是选择 S0、S1 或 S2。交付目标是一个 **S3′**：保留 S3 的 106 个
DiffTest 接口、每周期可观测值、NEMU reference checking、异常检测和 trace/schema 语义，
但让这些观测路径尽量不扩大主 DUT 模型的状态、活动传播和调度。S0 只作为“没有验证功能
时能达到的性能下界”，不能作为最终配置。

## 性能结果

| 状态 | Host 平均 / s | Host 中位数 / s | 与前一状态的直接变化 |
| --- | ---: | ---: | ---: |
| S0 RTL 完全关闭 | 71.5495 | 71.3330 | 基准 |
| S1 RTL 生成但模型采集关闭 | 79.86425（TNO0401）；82.31675（TNO0432 复测） | 79.961（TNO0401）；81.3985（TNO0432） | S1 相对 S0：**+11.62%**（TNO0401 配对） |
| S2 采集能力开启、运行时关闭 | 97.7830 | 97.4400 | S2 相对 S1：**+19.0701%**，95% CI `[+16.7772%, +20.8480%]`，8/8 更慢 |
| S3 运行时 DiffTest 开启 | 98.0155 | 97.8750 | S3 相对 S2：**+0.2477%**，95% CI `[-0.5205%, +0.8077%]`，1/8 更快 |

S1 的两次绝对均值相差约 3.07%，说明 node030 的频率和系统状态会影响绝对秒数；这也是
本轮使用交替配对百分比而不是跨批次绝对时间作结论的原因。S0→S1 的 TNO0401 配对原始
口径是“生成关闭 B 相对生成开启 A 平均快 10.410040%”；换成 S1 相对 S0 即为慢 11.62%。

## 结构证据

### RTL 生成层：S0→S1

TNO0401 的结构核对显示，DiffTest 硬件生成本身已经改变了后续模型的输入规模：

| 指标 | S0 | S1 | S1 相对 S0 |
| --- | ---: | ---: | ---: |
| RTL DiffTest 接口 | 0 | 106 | — |
| RTL 文件数 | 2,025 | 2,097 | +3.56% |
| RTL 字节数 | 187,384,743 | 243,606,175 | +30.00% |
| reg-to-mem 前 GRH 操作数 | 4,502,885 | 4,662,310 | +3.54% |
| reg-to-mem 前寄存器位数 | 3,485,705 | 3,964,515 | +13.74% |
| 调度计算操作数 | 5,130,590 | 5,365,403 | +4.58% |
| compute supernode 数 | 57,527 | 60,225 | +4.69% |
| 生成 C++ 字节数 | 1,148,312,818 | 1,186,021,406 | +3.28% |
| ELF 字节数 | 71,286,016 | 73,454,048 | +3.04% |
| ELF `.text` 字节数 | 64,277,887 | 66,390,139 | +3.29% |

即使 S1 在 Wolvrix 读入时已经不定义 `DIFFTEST`，RTL 生成阶段留下的额外寄存器和组合结构
仍然进入 GRH 和调度。这个差异不能归因于运行时 DPI 或 NEMU。

### 模型采集层：S1→S2

TNO0432 的 S1/S2 模型统计显示，采集能力本身使图和调度规模明显变大：

| 指标 | S1 | S2 | S2 相对 S1 |
| --- | ---: | ---: | ---: |
| graph ops | 6,484,088 | 7,204,065 | +11.10% |
| graph values | 6,124,081 | 6,832,966 | +11.58% |
| compute nodes | 1,003,644 | 1,081,570 | +7.76% |
| compute supernodes | 60,225 | 63,273 | +5.06% |
| boundary values | 923,327 | 996,298 | +7.90% |
| boundary activation edges | 1,794,798 | 1,977,816 | +10.20% |
| C++/header 源字节数 | 1,193,528,652 | 1,272,538,177 | +6.62% |
| model 目录字节数 | 1,401,183,547 | 1,492,714,510 | +6.53% |
| native binary 字节数 | 73,454,048 | 79,101,024 | +7.69% |

S2/A′ 和 S3/B 的模型 C++ 内容相同，模型文件数和大小也相同；两者的 native binary 大小
同为 79,101,024 字节，差别来自 harness 的运行时配置。S1→S2 的 19.07% 回退因此更像
模型结构、调度和活动传播变化的综合成本，而不是一次 NEMU 调用的成本。

### 运行时检查层：S2→S3

S2 与 S3 的 8 对样本中，PC `0x80000c0c`、提交指令数 240349、DiffTest cycleCnt
99996、guest cycles 100001、UART 和首次访存指纹均一致。S3 额外加载了 NEMU，且每个样本
都通过 reference 映射检查；但配对均值只有 +0.2477%，区间跨零。对当前单核、100k 周期
CoreMark 负载，运行时检查不是可稳定测出的主要瓶颈。

## 对优化方向的启示

第一优先级应是**隔离和压缩 DiffTest 结构对主模型的影响，同时保留 S3 的全部观测语义**，
而不是先微优化 NEMU 检查函数。
当前数据支持以下方向：

1. 在 RTL ingest 或 GRH 早期把 DiffTest Gateway、采集寄存器和只服务于 DiffTest 的依赖
   标记为 observer side graph；在 `--diff` 时仍然计算并提交它们，但不让它们反向参与
   DUT 主图的状态规模、活动传播和 supernode 划分。这样优化的是 S3 的执行组织，而不是
   删除 S3 的采集功能。
2. 将“模型可采集”做成轻量的 commit-boundary ABI，只暴露必要的提交 PC、指令、异常和
   内存副作用；不要让完整 DiffTest bundle 的所有字段都进入 DUT 主模型状态。S1→S2 的
   graph values 和 activation edges 增长约 11%，说明现在的成本不只是几个回调符号。缩减
   ABI 时必须保留完整的外部 trace/schema，内部可以采用延迟打包或 commit snapshot。
3. 把运行时开关继续保持在模型外层。S2/S3 的结果说明同一个采集模型上切换 NEMU 检查
   已经足够便宜，值得保留这种可切换性；优化目标不是让 S2 成为最终模式，而是让 S3′
   在 `--diff` 下接近 S0，同时维持 S3 的每周期检查结果。
4. 重新审视 `EnableDifftest` 与 `debugEn` 的耦合。TNO0401 已记录该开关同时影响后端
   debug 字段和相关生成逻辑，所以 S0→S1 的收益不能全部归因于 DPI 回调。将“调试字段”、
   “DiffTest 采集结构”和“运行时检查”拆成独立配置，才能做出更干净的消融并避免为验证
   功能改变主数据路径。

一个合理的工程目标是：生成时保留完整的 commit trace 接口，在 GrhSIM 中将其变成与 DUT
主调度解耦的 observer side graph；`--diff` 时仍在 commit boundary 生成同样的状态快照并
挂接 NEMU。这样 S3 的功能和检查保持不变，同时有机会把主模型规模推回 S1，甚至接近 S0。
当前证据还不能保证能恢复全部 19% 或 11.62%，因为其中有 `debugEn` 和 RTL 结构改变的
混合因素；接下来必须用逐周期 DiffTest state/trace 等价来验收，而不能只看 CoreMark UART。

S3′ 的验收门应包括：生成的 DiffTest schema 与 S3 相同；相同输入下每个有效 bundle 的
字段、valid、cycle/commit 顺序和异常结果逐周期一致；NEMU 仍能检测故意注入的错误；最后
再用与 S3 相同的 8 对 CPU96 walltime 比较 S3′/S3，并以 S0 作为下界参照。

## 证据

- [TNO0401：生成阶段关闭 DiffTest](./TNO0401_difftest_generation_off_walltime_20261103.md)
- [TNO0432：模型采集路径与运行时检查的分层消融](./TNO0432_difftest_generation_and_runtime_ablation_20261104.md)
- [S0/S1 结构统计](../../build/xs/difftest_generation_20261103_v2/structure.json)
- [S1/S2 activity schedule 统计](../../build/xs/difftest_runtime_20261103_v1/B/model/activity_schedule_supernode_stats.json)
- [A/B summary](../../build/xs/difftest_runtime_20261104_v1/A-vs-B/summary.json)
- [A′/B summary](../../build/xs/difftest_runtime_20261104_v1/Aprime-vs-B/summary.json)

本记录是对已完成实验的综合 review，没有新增性能样本；所有正式样本和异常样本均保留在
原始目录中。
