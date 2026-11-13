# TNO0061：128 谓词门下 after seed1 的独立对照

日期：2026-11-12（America/Los_Angeles）。使用与 [TNO0060](./TNO0060_short_predicates_strict_seed7_walltime_20261112.md) 相同的收紧规则，在独立 after seed1 分区上验证。before 的内容一致性见 [TNO0059](./TNO0059_short_predicates_before_identity_20261112.md)。

## 对齐与功能

冻结原 seed1 graph、assignment、Clang 23 编译选项、DiffTest harness、CoreMark/NEMU；A/B 均启用已有长字段掩码和宽归约。保留此前的 `grhsim_Gpart_2_model_sched_77.o` Clang 修正，源码与 archive 中的对象均未改变，SHA256 为：

```text
0c2189a66609399887e7d49eab1dd826378035bb1a93f2fec4f10e18ff70d484
```

重新发射的 9,306 个 source/header 文件集合一致，只改写 **30 个 C++ 文件**，header/layout 不变。共保留 **43 个范围、11,600 个不同谓词**：part_15 为 19 个范围、part_20 为 20 个、part_4 为 4 个。所有保留范围与初始规则生成源码逐字相同，未保留范围与基线源码逐字相同。

node030、CPU96–127、NUMA1 bind、ASLR off、performance 模式，相同 code-page/preload/thread pinning；不做外部 CPU 空闲准入检查。各侧 smoke 10k、100k DiffTest 验证、100k 预热，再进行 8 对交替计时。**22 次运行全部通过功能与放置门，无拒绝样本**；全部 100k 样本签名与 seed7 相同，PC `0x80000c1a`、instruction count `250838`、cycle count `99995`、Guest cycles `100001`、`cycle-limit`、相同 CoreMark 启动输出。

## 性能

| 指标 | A 均值 | B 均值 | 配对变化均值 | bootstrap 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 15.089875 s | 14.707000 s | **−2.5281%** | **[−3.0329%, −2.0491%]** | 8/8 |
| 外部 walltime | 15.191623 s | 14.808435 s | **−2.5133%** | **[−3.0141%, −2.0330%]** | 8/8 |

固定 seed `20261102`，10,000 次配对 bootstrap。收紧规则在两个 after 分区上均保持稳定收益。

累计阶段中位数中，part_eval 从 13,091.369 ms 降到 12,655.911 ms；最慢 part_15 eval 从 10,089.417 ms 降到 9,756.793 ms，仍慢于 part_16 的 9,250.574 ms。这里的编号属于 seed1，不与 seed7 的 part_18/19 混用，也不将并行分区时间相加。

候选 binary 为 114,428,144 bytes，SHA256：

```text
71a4f14f09669e0aff653e0ad04ad8e549876af93459eea7b5d9f16562a929a1
```

## 默认资格

before 源码和 binary 完全不变；seed7 和 seed1 的 Host 与外部 walltime 置信区间均低于零；两个 after 共 44 次运行通过完整 DiffTest 与 placement，focused sanitizer 和完整 emitter 回归通过。因此收紧版具备默认启用资格，最后还需核对默认/显式开启/显式关闭的生成一致性。该结论仅覆盖这些已验证的图与负载，不承诺任意电路均加速。

- [正式报告](../../build/artifacts/repcut-short-reduction-20261112/after1-strict-report.json)、[逐对 CSV](../../build/xs/repcut-short-reduction-20261112/measure-after1-strict/pairs.csv)、[原始运行](../../build/xs/repcut-short-reduction-20261112/measure-after1-strict/)
- [源码子集审计](../../build/xs/repcut-short-reduction-20261112/after1-strict/strict-source-audit.json)、[输入和修正对象身份](../../build/xs/repcut-short-reduction-20261112/after1-strict/inputs.json)、[配置](../../build/xs/repcut-short-reduction-20261112/after1-strict/configuration.json)
- [默认资格 gate](../../build/artifacts/repcut-short-reduction-20261112/strict-promotion-gate.json)、[构建日志](../../build/artifacts/repcut-short-reduction-20261112/after1-strict-build.log)
