# TNO0065：公共因子成本门的正式性能验收

日期：2026-11-13（America/Los_Angeles）。承接 [TNO0064](./TNO0064_short_predicate_factored_cost_implementation_20261112.md)，本篇记录公共因子成本门完成完整发射、功能门和 8 对 AB/BA 后的结果。此前 128 谓词门的结果保留在 [TNO0060](./TNO0060_short_predicates_strict_seed7_walltime_20261112.md) 和 [TNO0061](./TNO0061_short_predicates_strict_seed1_walltime_20261112.md)。

## 最终规则

短条件范围继续要求 4–15 个一位字段、稳定输入、同一活动范围、64 输入上限、完整 reduction-only use proof 和足够输入复用。不同谓词数为 `P`，稳定输入数为 `I`，估计公共因子复用后的二元布尔运算数为 `C`：

```text
P >= 128  或  (16 <= P < 128 且 C >= 2 * P + I)
```

`C` 在生成阶段按 AND/OR family 分开计算；每次确定性地选择出现最多的二元项并共享，剩余表达式按项数计数。这是筛选启发式，不是运行时重写，也不引入运行时计数器或条件分支。父规则关闭、显式属性/环境关闭和所有安全回退保持不变。

## 结构与功能

三个冻结图重新发射并通过逐范围源码审计。before 的 7,857 个 source/header 完全回退，重新链接 binary SHA256 仍为：

```text
27309399baffa03aeb1c8d538a7263bed934d0fd670f2269b54c1685ccd6c674
```

after seed7 保留 **196 个范围、20,969 个不同谓词**，改写 43 个 C++ 文件；after seed1 保留 **189 个范围、18,775 个不同谓词**，改写 54 个 C++ 文件。两图均保持 header/layout、graph、assignment 和 harness 不变。seed7 的 196 个范围与此前已验证的实际表达式检查覆盖交集：635,179 个向量、86,166,345 次比较，全部通过。

新增 focused fixture 在 Clang O0/O3、ASan/UBSan 下运行 12,000 组输入、每组重复 eval 两次，覆盖 127/128 谓词边界、32 谓词公共因子拒绝、复杂 AND/OR 接受、15 谓词下限、64/65 输入、字段宽度、写入、副作用、混合 family、属性优先级和父规则关闭。完整 emitter 回归、长字段掩码源码一致性、Python 17 项测试和 canonical Make dry-run 均通过。

## 正式对测

统一在 node030、CPU96–127、NUMA1 严格 bind、ASLR off、Clang 23、performance 模式、完整 DiffTest/NEMU、CoreMark 100k；关闭 trace 和诊断计数。每组双方依次 smoke、100k 验证、预热，再执行 8 对 AB/BA。三组共 66 次运行，全部通过功能签名、线程放置和 NUMA locality，无拒绝样本。bootstrap 使用固定 seed `20261102`、10,000 次重采样。

### after seed7：相对当前 128 谓词门

| 指标 | 当前 128 门 A | 公共因子门 B | 配对变化 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 13.257000 s | 12.830875 s | **−3.2129%** | **[−3.5945%, −2.8111%]** | 8/8 |
| 外部 walltime | 13.365525 s | 12.937725 s | **−3.1997%** | **[−3.5869%, −2.7983%]** | 8/8 |

### after seed7：相对未启用短条件的基线

| 指标 | 未启用短条件 A | 公共因子门 B | 配对变化 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 13.606500 s | 12.896500 s | **−5.2112%** | **[−6.1480%, −4.2658%]** | 8/8 |
| 外部 walltime | 13.714057 s | 13.002533 s | **−5.1813%** | **[−6.1115%, −4.2350%]** | 8/8 |

这两个口径不能相加：前者表示相对旧默认 128 门恢复的收益，后者表示相对没有短条件优化的总收益。此前宽松 16 谓词门为约 −6.93%；新门以少约一些覆盖换取 before 的完全回退和更稳健的选择。

### after seed1：相对当前 128 谓词门

| 指标 | 当前 128 门 A | 公共因子门 B | 配对变化 | 95% CI | B 更快 |
|---|---:|---:|---:|---:|---:|
| Host time | 14.148625 s | 13.852125 s | **−2.0953%** | **[−2.5716%, −1.6211%]** | 8/8 |
| 外部 walltime | 14.261140 s | 13.961194 s | **−2.1029%** | **[−2.5557%, −1.6534%]** | 8/8 |

两个 after 分区均有稳定额外收益；before 仍保持内容和 binary 完全不变。当前实现继续默认开启，并保留显式关闭选项。

## 产物

- [最终机器可读报告](../../build/artifacts/repcut-short-profitability-20261112/final-report.json)
- [seed7 对当前 128 门](../../build/artifacts/repcut-short-profitability-20261112/generated-strict-report.json)、[seed7 对未启用短条件](../../build/artifacts/repcut-short-profitability-20261112/generated-wide-report.json)、[seed1 对当前 128 门](../../build/artifacts/repcut-short-profitability-20261112/after1-strict-report.json)
- [逐对数据](../../build/xs/repcut-short-profitability-20261112/measure-generated-strict/pairs.csv)、[未启用短条件对照](../../build/xs/repcut-short-profitability-20261112/measure-generated-wide/pairs.csv)、[seed1 数据](../../build/xs/repcut-short-profitability-20261112/measure-after1-strict/pairs.csv)
- [before 内容一致性](../../build/artifacts/repcut-short-profitability-20261112/before-identity.json)、[kernel 覆盖](../../build/artifacts/repcut-short-profitability-20261112/kernel-coverage.json)、[最终源码与 patch](../../build/artifacts/repcut-short-profitability-20261112/)
