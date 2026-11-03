# TNO0398：仅替换四位及以上 PopCount 的单线程实测

日期：2026-11-03。本文是 [TNO0397](./TNO0397_popcount_intrinsic_packed_layout_walltime_20261103.md) 的宽度消融：保留紧凑输入策略，只让宽度大于等于 4 的 packed `PopCount` 使用 intrinsic，宽度 1、2、3 的 packed 调用继续使用 Chisel 硬件实现。

## 模式和覆盖

新增显式模式：

```text
--wolvrix-sim-primitives popcount-ge4
```

原来的 `popcount` 全宽模式保留，便于和 TNO0397 对照。`popcount-ge4` 的布局规则是：

| 输入 | 宽度 | 处理 |
| --- | ---: | --- |
| packed `UInt/Bits` | 1–3 | 保留硬件 `chisel3.util.PopCount` |
| packed `UInt/Bits` | ≥4 | `wolvrix_popcount_v1_w<N>` → `kCountOnes` |
| `Vec[Bool]` / `Seq[Bool]` | 任意 | 保留硬件实现 |

香山的 primitive manifest 显示：packed `PopCount.Bits` 1,095 次；其中 405 次（宽度≥4）进入 intrinsic；packed 宽度 1、2、3 共 690 次，全部记录为 `packed-below-width-threshold`；分布式 `Vec/Seq` 共 7,140 次，全部保留硬件。因此本轮没有替换三个位宽，也没有重新引入 `asBools`/`Seq` gather。

## 生成和后端形态

B 从当前 Chisel 源码重新生成 RTL、GRH 和 native emu。A 复用了上一轮同配置的关闭原语 binary：utility 的 `none` 分支和本轮新增阈值逻辑生成相同硬件；候选 B 的 source snapshot 单独保存在生成目录中。这样避免重复生成没有语义变化的 A，同时保留 A binary 的 SHA256 和完整运行身份。

| 指标 | A（关闭原语） | B（宽度≥4） |
| --- | ---: | ---: |
| binary | 79,092,832 B | 78,941,184 B |
| model C++ 文件 | 132 | 129 |
| model C++ 源码 | 1,264,602,979 B | 1,257,542,569 B |
| compute supernodes | 63,273 | 62,500 |
| common-expression compute nodes | 582,659 | 581,540 |
| `kCountOnes` activation edge | 0 | 3 |

B 的生成 C++ 使用 `grhsim_popcount_u64`/`grhsim_popcount_words`，没有保留 PopCount DPI 调用作为 native 外部依赖。

## 功能和测量

仍使用 Wolvrix 专用单模型单线程流程，测量固定 node030 CPU96，C100000，8 对交替 AB/BA。smoke、两组 100,000 周期 Difftest trace、warmup、正式运行均通过 CPU 亲和和 NUMA locality 检查。

功能签名：

```text
pc=0x80000c0c
instr_count=240349
cycle_count=99996
guest_cycles=100001
```

两组 trace 各 100,000 条记录，A/B SHA256 完全一致。

正式 walltime：

| 指标 | 结果 |
| --- | ---: |
| A 平均 Host time | 97.46175 s |
| B 平均 Host time | 98.559625 s |
| B 相对 A 的配对均值 | **+1.136902%** |
| 配对中位数 | +0.522131% |
| 固定种子 paired bootstrap 95% CI | **[-0.129721%, +2.772443%]** |
| B 更快的配对数 | 3 / 8 |

逐对结果：

```text
pair 0: A 97.066  B 98.832  (+1.8194%)
pair 1: A 97.152  B 97.048  (-0.1070%)
pair 2: A 97.121  B 97.809  (+0.7084%)
pair 3: A 97.117  B 103.073 (+6.1328%)
pair 4: A 96.303  B 97.994  (+1.7559%)
pair 5: A 97.360  B 97.687  (+0.3359%)
pair 6: A 99.458  B 97.968  (-1.4981%)
pair 7: A 98.117  B 98.066  (-0.0520%)
```

pair 3 是一次保留的异常慢样本。它的 CPU、亲和性和页面 locality 检查均通过，因此没有被删除；这也使区间跨零，不能把本轮结果判为稳定回退。与此同时，均值方向仍为回退，3/8 的胜率也不足以证明收益。

## 结论

去掉 1–3 位后，B 相比 TNO0397 的全宽替换减少了 690 个小宽度 intrinsic，但没有得到稳定加速。当前结论是：

1. 小宽度调用很可能是回退来源之一，但本轮仍有 405 个宽度≥4 调用的后端形态变化，不能把残余回退全部归因于某个位宽；
2. 宽度阈值 4 不是当前可直接启用的成本策略，仍需按模块或调用频度做消融；
3. 1–3 位硬件保留规则应继续保留，因为它避免了最小宽度原语的无效展开，但还需要对 OldestArbiter、IssueQueue、IntRFBankReadArbiter 等高频模块分别测量；
4. 当前不启用任何 PopCount intrinsic 默认模式。

## 复现产物

- [B 生成目录](../../build/xs/popcount_ge4_20261103_v1/B/)
- [单线程 comparison summary](../../build/xs/popcount_ge4_20261103_v1/comparison-v1/summary.json)
- [8 对配对 CSV](../../build/xs/popcount_ge4_20261103_v1/comparison-v1/pairs.csv)
- [B primitive manifest](../../build/xs/popcount_ge4_20261103_v1/B/chisel-home/build/simulation_primitives.json)
- [机器可读汇总](../../wolvrix/build/artifacts/priority-intrinsic/priority-intrinsic-popcount-ge4-report.json)

复现命令：

```bash
python3 wolvrix/build/artifacts/priority-intrinsic/xs_generate_popcount_ge4_v1.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_finish_popcount_ge4_v1.py
python3 wolvrix/build/artifacts/priority-intrinsic/xs_compare_popcount_ge4_v1_wait.py
```
