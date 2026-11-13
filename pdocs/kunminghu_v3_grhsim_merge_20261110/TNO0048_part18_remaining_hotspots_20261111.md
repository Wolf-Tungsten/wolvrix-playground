# TNO0048：向量掩码优化后的 part_18 剩余瓶颈

日期：2026-11-11（America/Los_Angeles）。承接 [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md) 与 [TNO0047](./TNO0047_reduction_masks_default_enabled_20261111.md)。本轮调查冻结 after seed7 已启用向量译码掩码规则的 binary，没有重新分区。

## 结论

`part_18` 的主要计算成本仍是分散的组合逻辑，其中存在上一轮未覆盖的向量译码形式。最具体的入口是 **宽 concat 的结果只被 OR 归约使用**：生成代码先把大量 Boolean 谓词打包，再归约为一个 bit。另有反复展开的短字段 AND 条件。当前证据不足以把整个分区成本归为译码，也没有发现新的功能错误。

空 batch 确实很多，但只增加调用前活动检查的独立 8 对对照没有稳定收益，见 [TNO0049](./TNO0049_part18_dispatch_guard_control_20261111.md)。因此下一轮应优先研究宽 concat/归约融合及跨谓词复用，不能直接根据空调用比例推断收益。

## 对象与测量口径

使用 TNO0043 正式生成的 Clang 23.1.2 binary：

```text
build/xs/repcut-vector-decode-20261111/generated/initial/harness/grhsim-compile/emu
sha256 e27e6fd69c65dc0412bb893afab3f6841222533ec64058c3656a5e13479a2aac
```

node030、CPU96–127、NUMA1 严格绑定、ASLR disabled；保留 performance 模式的 code-page、preload、thread pinning，完整 DiffTest/NEMU，CoreMark 100,000 周期。runtime 映射为 worker/part 顺序对应，`part_18` 在 CPU114；host 在 CPU105。没有外部 CPU 空闲准入检查。

两次进程范围的 `perf record -e cycles:u -F 997 --sample-cpu` 均通过功能签名、实际线程 affinity、NUMA locality 和 code-page 门。使用 ELF header 映射基址、冻结 binary 的符号与采样 IP 解析匿名重映射代码页；不是把匿名页面全部丢弃。采样和下述计数版本只用于归因，不把其 walltime 用作正式收益。

功能签名为 PC `0x80000c1a`、指令数 250,838、model cycle count 99,995、guest cycles 100,001、cycle-limit，workload 输出 `Running CoreMark for 2 iterations`。原 TNO0043 的 8 对正式计时中，`part_18` eval 中位数 8.7362 s，`part_19` 7.3479 s。它们是累计分区耗时，不能直接相加为整机 walltime。

## CPU114 动态归因

按两次采样的 period 加权合计，分母为 CPU114 上这个进程的全部用户态采样周期，包含等待：

| 类别 | 占比 |
|---|---:|
| compute batch | 57.012% |
| worker loop | 31.131% |
| `eval_with_input_changes` 调度主体 | 3.239% |
| commit batch | 3.073% |
| part_18 update | 2.319% |
| 其他已解析函数 | 2.102% |
| 未解析 | 1.125% |

worker loop 中，仅 `0x369d4/0x369da/0x369de` 三个 IP 就占 CPU114 全部采样的 30.419%。反汇编确认它们处于 `pause` 附近的 stop/work atomic 轮询。这个等待比例不能解释为译码成本，也不等于可消除的整机 walltime；即使平均最慢的分区，在不同 phase 和不同周期仍会等待。

最热 compute batch 为 160，占 CPU114 全部采样 1.885%，约占 compute 样本 3.31%；其次 242 为 0.881%、161 为 0.870%、90 为 0.804%。最热 10/20/40/80 个 compute batch 分别只覆盖 compute 样本的 **14.54% / 23.55% / 36.81% / 54.97%**。成本并不集中在单一大函数。

## 从采样 IP 到具体译码形态

对 batch 160、161、125、337 用相同 Clang 23/O3/native 参数额外编译 `-gline-tables-only` 对象。逐对象验证 `.text` 字节及目标函数大小与冻结 archive 一致后，才用 DWARF 将旧 binary 的采样偏移映射到源码；内联 runtime helper 保留 frame 链并归属生成代码调用位置。带调试信息的对象没有用于性能运行。

### 宽 concat 后只需要一个 OR 结果

`batch_160` 机器码 144,287 B，其中 supernode 1420–1423 合计占该函数采样的 **82.67%**。四个节点重复同一类译码形态：

```cpp
// 下面是形态示意；条件为纯 Boolean 表达式。
auto packed = concat_to_words<2>(array<uint64_t, 86>{p0, p1, /* ... */ p85});
bool result = reduce_or_words(packed, 86);
```

源码真实调用为 `grhsim_concat_uniform_scalars_words<2>`，输入 86 个 1-bit 谓词；还存在 wordwise 构造的 110/111 位 concat 随后 `grhsim_reduce_or_words`。四处 86 位 concat 表达式及其内联 helper 占 **batch_160 采样的 40.37%**，这是实际执行证据，不只是源码大小推断。该比例包含输入谓词计算与数组打包，不能全部计为数组开销。

具体见 [batch_160 源码](../../build/xs/repcut-vector-decode-20261111/generated/initial/package/grhsim_Gpart_18_model_sched_160.cpp)：319/843/1367/1891 行是四个 86 位 concat，548/1072/1596/2120 行为对应 OR 归约。单条 concat 源码约 68 KB，输入中又内联许多短字段 AND 条件。

现有 [scalarConcatReductionExpr](../../wolvrix/lib/emit/grhsim_cpp.cpp) 明确拒绝 `resultWidth > 64`，因此上一轮共享输入掩码规则不会覆盖这些宽结果；不是默认开关失效。源码扫描在 part_18 找到 **60 处、18 个 batch** 的宽局部 concat→OR 候选：12 处 uniform helper、48 处 wordwise，包含 86/100/110/111/604/638 等位宽。这是后续 IR 审核的候选集合，尚未证明每处都能安全替换。

合理方向是在保持原计算时点、所有用户语义与变化传播的前提下，让只服务 OR/NOR 的局部 concat 直接形成谓词，避免构造 Words。不能仅把现有阈值从 16 调低；这里首先有 64 位宽度边界。

### 短字段条件重复展开

batch 125/160/161 中大量 6–10 位条件以 shift/OR concat 再 reduce-AND 的形式内联。batch_125 有 460 个 `kReduceAnd` 源码操作标记，采样分散在多个条件求值和变化传播处。batch_161 包含 uop/channel 选择相关输出；batch_160 输出中可见 `uopBufferCtrlDecoder` 和 `illegalChannelOut` 层级。

相关 Chisel 为 [UopBufferCtrlDecoder.scala](../../testcase/xiangshan/src/main/scala/xiangshan/backend/vector/Decoder/UopBufferCtrlDecoder.scala) 与 [ChannelUopSelect.scala](../../testcase/xiangshan/src/main/scala/xiangshan/backend/vector/Decoder/Select/ChannelUopSelect.scala)。它们根据多个 channel 的 uop 数量构造译码表。优先在通用 emitter 中复用稳定输入和相同条件，需继续保留上一轮收益门与安全边界；不应为单个 XiangShan 路径硬编码 helper。

### commit 不是本轮主要归因

`commit_batch_337` 占 CPU114 样本约 2.45%，机器码 215,372 B，包含 4,144 个 register write 与 55 个 memory write 操作标记。它是混合状态提交，不能仅凭大函数或状态读写就称为 DiffTest observer 热点。本次没有足够层级映射证据把其全部成本归到 DiffTest。

## 活动计数与检查

只在 part_18 的 `eval_with_input_changes` 与 compute 调用入口加计数，模型 header/layout 不变，原 compute/commit 对象不变。全程无逐调用时钟读取。100k 完整 DiffTest 与 placement 门通过：

| 指标 | 数值 |
|---|---:|
| eval 入口 | 200,102 |
| compute round | 300,152 |
| compute batch 数 | 335 |
| compute batch 调用 | 100,550,920 |
| 入口有活动 bit | 40,964,552 |
| 入口无活动 bit | 59,586,368（59.2599%） |

这是调用入口 active-byte mask 的状态，不是 supernode 总执行次数；一个 eval 可有多个 fixed-point round。batch_160 仅 18.05% 调用入口非空，但其源码映射样本主要落在计算体，不在空入口。计数不能直接推算空路径耗时，所以另做 TNO0049 对照。

第一次计数运行功能通过，但计数 JSON 使用了 runner 自身结果文件名，被后者覆盖，报告收集失败；改为 `activation-counts.json` 后复用同一 binary 重跑并成功收集。失败收集日志保留，不用于计数结论。

## 归档与后续优先级

1. 审核宽局部 concat→OR/NOR 的真实 use-list、快照与副作用条件，优先去掉无必要的宽结果打包。
2. 再评估短字段 AND/OR 条件跨表达式复用；收益要覆盖多个 batch，单个函数的占比有限。
3. 保留调度与 commit 数据，但当前 part_18 的调用前检查没有通过性能门，不据此更改默认配置。

本轮没有改动生产 emitter 或默认配置。只增加诊断产物和追加式记录。没有获得“整个 part_18 都是向量译码”或“60 处全部可优化”的结论。

- [综合索引](../../build/artifacts/repcut-part18-20261111/report.json)、[机器可读归因](../../build/artifacts/repcut-part18-20261111/attribution.json)
- [采样驱动](../../build/artifacts/repcut-part18-20261111/profile.py)、[ELF 解析](../../build/artifacts/repcut-part18-20261111/analyze_samples.py)、[原始两次采样](../../build/xs/repcut-part18-20261111/)
- [源码/机器码等价与行映射](../../build/xs/repcut-part18-20261111/source-lines/report-inlined.json)、[宽 OR 候选](../../build/xs/repcut-part18-20261111/wide-or-candidates.json)
- [活动计数](../../build/xs/repcut-part18-20261111/counts/complete.json)、[计数驱动](../../build/artifacts/repcut-part18-20261111/probe.py)
