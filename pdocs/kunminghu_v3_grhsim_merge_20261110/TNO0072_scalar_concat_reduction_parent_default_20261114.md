# TNO0072：标量 concat 归约父规则默认开启验收

日期：2026-11-14（America/Los_Angeles）。本篇测量直接调用 GrhSIM emitter 时，将父规则 `scalar_concat_reduction` 从原默认关闭改为默认开启的效果。A/B 使用相同的 after `DefaultConfig` frozen graph；A 不设置父选项，B 显式设置父选项为 `0`。其余 emitter、RTL、workload 和编译参数一致。

## 构建与覆盖范围

单核 GrhSIM 源、binary、配置分别位于：

- 默认开启 A：`../../build/xs/parent-default-single-20261114-v1/`
- 显式关闭 B：`../../build/xs/parent-default-single-20261114-off-v1/`

两边使用 after kunminghu-v3 的 `DefaultConfig`、硬件 simulation model、完整 DiffTest/NEMU、CoreMark 100k、Clang 23.1.2 `-O3 -march=native`。镜像 SHA256 为 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，NEMU SHA256 为 `9188e7dda30709962f0bfbc1dd87cea73d88a18c92c30892f93ed529c22def43`。

A 和 B 的 3.8 GiB pre-reg-to-mem snapshot 逐字节相同。A 未设置 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION`，使用 emitter 新默认；B 显式设置为 `0`。两边都从相同 snapshot 恢复，重新执行相同 activity schedule 并生成 C++。

父规则开启的 A 在 139 个 generated C++/header 文件中实际应用了共享掩码和宽 concat lowering；关闭的 B 回退到原 lowering。generated C++/header 总大小从 B 的 1,608,765,988 字节降至 A 的 1,563,678,292 字节（−2.80%）；binary 从 104,469,128 字节降至 99,860,520 字节（−4.41%）。该变化来自本图实际命中的 lowering，不是只有开关值不同。身份及逐文件差异索引见 [build comparison](../../build/artifacts/parent-concat-reduction-default-20261114/build-comparison.json)。

## 功能与 placement gate

两侧均通过 10k smoke 和两组 100k 完整 DiffTest trace。每组 trace 有 99,999 条记录，所有 DiffTest 字段及 cycle 逐字节一致；两组 trace 的 SHA256 均相同。最终 PC 为 `0x80000c1a`，instruction count 为 250,838，model cycle count 为 99,995，guest cycles 为 100,001，CoreMark 输出相同。DiffTest schema 未变。

正式计时在 node030 CPU96、单线程、NUMA node 1、关闭 ASLR 下进行。外部 CPU/sibling idle admission check 按先前约定跳过，但每次运行仍检查 affinity、线程数和 NUMA locality；A、B 的 smoke、warmup、8 个配对样本均通过 placement/locality gate。正式计时关闭 trace 和诊断计数。

## 8 对 AB/BA

A 为父规则默认开启，B 为显式关闭。原 paired runner 的 delta 定义为 `B/A - 1`，正值表示关闭版更慢：

| 指标 | 默认开启 A | 显式关闭 B | B 相对 A | B/A 的 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 128.792 s | 143.065 s | +11.083% | [+10.785%, +11.396%] |
| 外部 walltime | 128.855 s | 143.129 s | +11.078% | [+10.779%, +11.390%] |

换成默认开启相对关闭的口径，Host time 降低 **9.977%**，95% CI **[−10.230%, −9.735%]**；外部 walltime 降低 **9.972%**，95% CI **[−10.226%, −9.730%]**。默认开启版本 8/8 对更快。bootstrap 使用 seed `20261102`、10,000 次配对重采样。

## 决定与范围

父规则 `scalar_concat_reduction` 现默认开启。三个子规则 `scalar_concat_reduction_masks`、`short_concat_reduction_masks`、`wide_concat_reduction` 仍各自带适用范围与保守回退；显式关闭父选项仍保持旧 lowering。focused emitter test 同步检查默认与显式开启源码一致、显式关闭源码回退，并通过 Clang 23 O0/O3 ASan/UBSan。

该性能结论限定于这一份 after `DefaultConfig` 单核 GrhSIM 图和 CoreMark 100k，不外推为任意设计或 workload 均加速。标准 `config/grhsim32.json` 原本已显式开启父规则，本次默认值变化不改变该 preset。没有重分区、手动选择 assignment 或按运行结果调整候选。

## 归档

- [机器可读汇总及 8 对数据](../../build/xs/parent-default-single-20261114-paired-measure-v1/summary.json)、[pairs CSV](../../build/xs/parent-default-single-20261114-paired-measure-v1/pairs.csv)
- [paired runner manifest](../../build/xs/parent-default-single-20261114-paired-measure-v1/manifest.json)、[两组 100k trace 核验](../../build/xs/parent-default-single-20261114-paired-measure-v1/trace-s0.json)、[第二组 trace 核验](../../build/xs/parent-default-single-20261114-paired-measure-v1/trace-s1.json)
- [最终报告](../../build/artifacts/parent-concat-reduction-default-20261114/report.json)、[构建和生成差异](../../build/artifacts/parent-concat-reduction-default-20261114/build-comparison.json)
- [规则命中统计](../../build/artifacts/parent-concat-reduction-default-20261114/lowering-coverage.json)、[focused emitter test 日志](../../build/artifacts/parent-concat-reduction-default-20261114/focused-emitter-test.log)
- [A/B emitter 日志与命令](../../build/xs/parent-default-single-20261114-v1/logs/emit.log)、[A/B compile 日志](../../build/xs/parent-default-single-20261114-off-v1/logs/compile.log)
