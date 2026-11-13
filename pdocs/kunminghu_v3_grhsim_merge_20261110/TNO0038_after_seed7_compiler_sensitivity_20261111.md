# TNO0038 after seed7 的 Clang 19/23 同窗口对照与编译器敏感度

## 问题与结论

用户指出：before seed2 换用 Clang 23 曾快约 30%，而原 after seed7 在两种编译器下似乎都在 17 秒附近。历史 after 的 Clang 19 均值为 17.451250 s，Clang 23 为 17.882875 s，但来自 [TNO0023](./TNO0023_repcut_cpu96_127_followup_20261111.md) 与 [TNO0030](./TNO0030_clang23_repcut_merge_comparison_20261111.md) 两个测量批次，不能直接作为编译器配对结论。

本轮直接复用两份 after seed7 binary，补做同窗口 8 对 AB/BA。结果确认 **after 没有复现 before 的大幅加速，Clang 23 在本轮反而小幅慢 1.8994%**，95% 区间为 `[+1.2247%, +2.4578%]`，8/8 对更慢。这里“小幅”描述效应大小，不表示区间跨零或性能严格相等。

## 固定内容与运行检查

本轮均使用原 after seed7、XiangShan `defb18e13` / DiffTest `b17a43a`、DefaultConfig。两份当前生成目录与原 manifest 逐文件检查：**9,435 个模型生成文件、6 个 generated DiffTest 文件的长度和 SHA256 全部一致**。生成 options 和 code-page 配置相同，没有重新分区、发射、编译或修改机器码，也没有采用新 seed1 的补丁版本。

两份模型与 harness 的代表对象 `.comment` 分别确认为 Ubuntu Clang 19.1.1 和 Clang 23.1.2，排除了取错同一编译器 binary 的情况。Clang 23 构建使用冻结源码重编译全部模型和对应 harness，因此本轮对比的范围是完整 emulator 的编译器变化。

| 版本 | binary bytes | SHA256 |
| --- | ---: | --- |
| A，after seed7 / Clang 19.1.1 | 118,894,296 | `23a2fe3de33bbc036e3400c7221fc4e4881e2d0a723c779ed799cdabaf7960de` |
| B，after seed7 / Clang 23.1.2 | 119,370,960 | `bd65a10ecc828cd6b0cf232cb0097cf57b103947248f9c1281e171e3de674281` |

两份构建均为 performance 模式。旧构建原有 CPU0–31 / NUMA0 元数据保留，本轮统一用 runtime override 在 **node030、CPU96–127、NUMA1 strict membind、ASLR disabled** 下执行。使用既有 preload/code-page、32 个 singleton affinity、thread pinning 和标准 phase timing，关闭 trace/额外 runtime profile，不做外部 CPU 空闲准入检查。

相同冻结 CoreMark/NEMU、100,000 周期上限、完整 DiffTest。每侧先执行 10k smoke、100k verification 和一次预热，随后 8 对 AB/BA，合计 **22 次全部通过、0 次拒绝**。除 emulator 外的运行依赖逐项相同；每次检查 actual affinity、NUMA 页、ASLR、code-page PASS 以及依赖和 binary 哈希。所有 100k 功能签名完全一致：PC=`0x80000c1a`、instrCnt=250,838、cycleCnt=99,995、Guest cycles=100,001，cycle-limit 终止，UART=`Running CoreMark for 2 iterations`。

## 同窗口性能结果

正数表示 Clang 23 更慢。固定 seed 20261102、10,000 次 paired bootstrap：

| 指标 | Clang 19 均值 / 中位数 | Clang 23 均值 / 中位数 | 配对均值 / 中位数 delta | 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 17.024125 / 16.930000 s | 17.346500 / 17.351500 s | **+1.8994% / +2.3074%** | **[+1.2247%, +2.4578%]** |
| 外部 walltime | 17.127806 / 17.028059 s | 17.449764 / 17.454047 s | **+1.8854% / +2.3006%** | **[+1.2124%, +2.4407%]** |

Host time 和外部 walltime 均为 Clang 23 更慢 8/8 对。新的绝对时间与历史批次不同，因此仍以本轮配对差异为准，不混合历史样本。

## 为什么与 before 不同

[TNO0028](./TNO0028_seed2_clang23_recompile_20261111.md) 的 before 同样是固定 seed2 和生成 C++、直接更换完整 emulator 编译器的 8 对实验，Host time 为 **16.369625 → 11.405125 s，−30.3242%**，95% CI `[−30.6979%, −29.8837%]`。以下从其原始 phase/part timing 与本轮 after 数据重新聚合；两行分别来自各自的编译器配对实验，不是一次四版本混合测量。

| 固定模型 | part_eval 中位数，Clang 19 → 23 | 观察 |
| --- | ---: | --- |
| before seed2 | 14.032171 → 9.077515 s | 分区阶段减少约 4.95 s |
| after seed7 | 14.883049 → 15.284184 s | 未减少，增加约 0.40 s |

进一步看各分区累计 eval 时间中位数，编译器收益集中在特定分区：

| 固定模型内的分区 | Clang 19 | Clang 23 | 变化 |
| --- | ---: | ---: | ---: |
| before part_6 | 8.622065 s | 3.383682 s | −60.76% |
| before part_20 | 7.464618 s | 2.852742 s | −61.78% |
| before part_8 | 7.175436 s | 2.474024 s | −65.52% |
| before part_26 | 7.021821 s | 6.714164 s | −4.38% |
| before part_11 | 6.681149 s | 6.607495 s | −1.10% |
| after part_8 | 11.141933 s | 11.667126 s | +4.71% |
| after part_18 | 10.714278 s | 10.751380 s | +0.35% |
| after part_19 | 7.874530 s | 7.838131 s | −0.46% |

before 的原来几个较慢分区大幅提速，较慢的分区随后变成 part_26 / part_11。after 的主要慢分区 part_8 / part_18 基本没有改善，其中 part_8 还略慢。after 各分区累计 eval 中位数之和变化约 +0.76%；before 对应和下降约 17.60%。这些累计并发时间只能表示工作量分布，不能当作 walltime 相加。

运行时在各个 eval 阶段分发任务并等待 worker 完成，然后进入更新阶段，因此总时间受每拍较慢分区和同步开销影响，不是平均分区收益。该机制与上述“before 的特定慢分区获得明显改善、after 的主要慢分区没有改善”相符，也解释了为何同一个 Clang 版本不会带来固定比例的整机加速。

目前可以确定的是：**两套生成代码对编译器版本的动态性能响应不同**。源码相等检查是同一 after 的两种编译器之间；before 与 after 本身包含上游结构、图和 assignment 的差异。不同模型的 `part_8` 不能当作同一个逻辑模块对应。

本轮尚未把收益归因到具体 LLVM pass、函数或指令。向量化、分支优化、寄存器分配和代码布局等只是待检验机制，不能仅由这些计时认定。若继续追根因，优先抽取 before part_6 / part_20 / part_8 中的动态热点，对照 Clang 19/23 机器码；再单独定位 after part_8 / part_18，而不是预设整个 after 都能复制 before 的 30% 收益。seed1 的掩码错误已有独立根因证据，本轮没有证据把 seed7 的性能差异归因于那个错误。

## 归档与检查

- [报告](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/report.json)、[验证结果](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/verification.json)、[执行入口](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/run.py)、[分析与核验脚本](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/analyze.py)。
- [源码逐文件一致性](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/source-equality.json)、[对象编译器注记](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/compiler-object-comments.json)、[运行依赖一致性](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/runtime-dependencies.json)。
- [原始配对摘要](../../build/xs/repcut-after-seed7-clang19-vs23-20261111/summary.json)、[逐对 CSV](../../build/xs/repcut-after-seed7-clang19-vs23-20261111/pairs.csv)、[逐对 JSON](../../build/xs/repcut-after-seed7-clang19-vs23-20261111/pairs.json)、[运行 manifest](../../build/xs/repcut-after-seed7-clang19-vs23-20261111/manifest.json)。
- [分区敏感度 JSON](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/compiler-sensitivity.json)、[after 分区 CSV](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/after-part-deltas.csv)、[before 分区 CSV](../../build/artifacts/repcut-after-seed7-clang19-vs23-20261111/before-part-deltas.csv)。

全部 22 次运行核验、统计重算、脚本 Python 编译、文档相对链接和 `git diff --check` 通过。本轮只增加实验产物与文档，未修改生产代码、默认编译选项或 retained 选择。
