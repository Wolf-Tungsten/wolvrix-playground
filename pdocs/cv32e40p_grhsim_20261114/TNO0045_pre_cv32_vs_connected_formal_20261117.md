# TNO0045：CV32 系列优化前与最新候选的正式八对直接比较

用户要求将当前 XiangShan GrhSIM 与引入 CV32 系列优化前的版本直接比较，并将本次作为正式八对测量。此前跨轮串接点估计约 −1.18%，尚不是直接比较；本次独立固定八对结果为 **外部 walltime −0.0692%，95% CI [−0.1485%, −0.0075%]，6/8 对更快**。实际差距很小，最新候选已回到优化前附近。这一直接结果替代此前跨轮估算。

## 版本与冻结范围

- A：Wolvrix `74d80cf`，CV32 优化系列前；复用 [TNO0033](./TNO0033_xiangshan_cv32_optimization_transfer_20261116.md) 的原始 before ELF。
- B：[TNO0044](./TNO0044_connected_shared_candidates_20261116.md) 的最新冻结 connected shared 候选，包含保留的 CV32 优化、共同正确性修复，以及计算连通/完整激活键候选和局部 SCC 细分。

| 模型 | ELF 字节数 | SHA256 |
| --- | ---: | --- |
| A，优化前 | 99,860,520 | `638c464fe763f24001e5950b885321f6fbd8fab42e1c7996dfe8d6e4f9b02b22` |
| B，最新候选 | 96,823,728 | `da1356413cb0b45a73a31f3c39bc0481912148b88a03e0c1a16cec1962a299eb` |

本轮不重新生成、编译或修改模型。对两端完整生成源码清单、ELF、schema、图输入、编译器、编译选项、镜像、NEMU 做冻结身份核对；两侧都是相同 DefaultConfig、guest 单核、native 单线程、普通硬件模型、完整 DiffTest，Clang 23.1.2，模型 `-std=c++20 -O3 -march=native`、harness O3。没有 waveform、PGO/BOLT、运行计数插桩或生成规则反馈。

候选包含的是 TNO0044 已测过的精确组合，未追加 packed layout、array scope、no-init、selected-read 或其他实验开关。原版本的 oversized splitting 配置仍保持历史值；TNO0033 已证实该图两侧实际拆分数量为零。

[模型身份](../../build/xs/pre-cv32-vs-connected-8pairs-v1/models.json)、[全部冻结输入](../../build/xs/pre-cv32-vs-connected-8pairs-v1/inputs.json)、[预先固定协议](../../build/xs/pre-cv32-vs-connected-8pairs-v1/policy.json)、[测量驱动](../../scripts/xiangshan_pre_cv32_final_compare.py)。

## 测量协议

node030 CPU96、NUMA1、ASLR off、单线程，全程持有共同 CPU96 测量锁。复用已有 NUMA 私有运行副本机制，持续核对线程、CPU、affinity、ASLR、binary/NEMU/共享库与页位置。

先分别执行 10k-cycle smoke，再重新采集两个 seed 的 100k-cycle DiffTest trace，直接比较 A/B 全部字段、顺序与覆盖范围。各自预热一次后，执行固定 8 对，顺序为 AB、BA 交替。正式样本不写 trace；每个样本都保留功能终点签名、UART、Host time 和外部进程 walltime。

主比较为每对 B/A 的外部 walltime 百分比变化，负数表示最新候选更快；另报告 Host time。使用既有 seed 20261102、10,000 次配对 bootstrap。没有重试、删点、追加样本或根据中间结果调整候选。沿用此前 XiangShan 的 skip-external-idle-admission，仍记录 CPU96/288 状态并强制 CPU/NUMA/单线程等放置门。

工作负载仍是 `coremark-2-iteration.bin` 的前 100k 周期，实际停止是 cycle limit，不宣称完整 CoreMark 结束。17 项既有测量/统计/锁协议回归通过；本轮没有生产代码变化，无需重新执行 emitter 回归。[工具回归日志](../../build/xs/pre-cv32-connected-8pairs-tests.log)。

## 结果与审计

两 seed 的新采集 DiffTest trace 各有 99,999 条记录，所有有效字段、顺序和覆盖检查通过。全部运行签名一致：PC `0x80000c1a`、instrCnt 250,838、cycleCnt 99,995、guest cycles 100,001，停止原因 cycle-limit。UART 均为 `Running CoreMark for 2 iterations`。

| 指标 | A：CV32 优化前 | B：最新候选 | B/A 配对平均变化 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | --- |
| 外部 walltime 均值 | 114.530630 s | 114.451320 s | **−0.069163%** | **[−0.148491%, −0.007549%]** |
| Host time 均值 | 114.470500 s | 114.390125 s | −0.070128% | [−0.150400%, −0.007531%] |

外部 walltime 的逐对变化中位数为 −0.049054%，6/8 对候选更快。均值相差约 79.3 ms/100k-cycle 窗口。平均变化按逐对比值计算，不用均值之比代替。

| 对次 | 顺序 | A 外部秒 | B 外部秒 | B/A 变化 |
| --- | --- | ---: | ---: | ---: |
| 1 | AB | 114.712746 | 114.535022 | −0.154930% |
| 2 | BA | 114.409553 | 114.425450 | +0.013895% |
| 3 | AB | 114.464611 | 114.454875 | −0.008506% |
| 4 | BA | 114.461324 | 114.404557 | −0.049595% |
| 5 | AB | 114.539445 | 114.476111 | −0.055295% |
| 6 | BA | 114.432493 | 114.484231 | +0.045213% |
| 7 | AB | 114.536684 | 114.481118 | −0.048514% |
| 8 | BA | 114.688184 | 114.349201 | −0.295569% |

AB 四对的平均变化为 −0.066811%，BA 四对为 −0.071514%，方向一致。最后一对降幅较大，按预定协议保留，不删除或追加样本。区间略低于零只描述本次固定窗口的小幅差异，不能推广为全负载或显著工程收益；也不把此前 −1.18% 的跨轮估算或三对 no_shared 结果混入统计。

独立审计复算 Host time 与 walltime 的全部统计、正反序分组，核对 24 次运行（16 个正式样本、2 次 smoke、4 次 trace、2 次预热）、5,055 次线程/CPU 快照、512 次原始 NUMA 快照，以及所有 staged runtime 文件身份。CPU96、NUMA1、单线程、ASLR off 检查通过；正式样本 CPU288 空闲率均为 100%。两端 ELF 与历史对应产物的身份完全相同，没有重新编译、重试、删点或新增轮次。

[原始八对](../../build/xs/pre-cv32-vs-connected-8pairs-v1/paired/pairs.json)、[CSV](../../build/xs/pre-cv32-vs-connected-8pairs-v1/paired/pairs.csv)、[统计汇总](../../build/xs/pre-cv32-vs-connected-8pairs-v1/report.json)、[独立审计](../../build/xs/pre-cv32-vs-connected-8pairs-v1/independent-review.json)、[二进制来源检查](../../build/xs/pre-cv32-vs-connected-8pairs-v1/provenance.json)、[审计脚本](../../scripts/xiangshan_pre_cv32_final_review.py)。

最终输入、生产源码未改、统计、链接及仓库格式检查见 [归档验证](../../build/xs/pre-cv32-vs-connected-8pairs-v1/validation.json)。本轮仅完成测量和分析记录，没有修改生产代码、生成规则或默认开关。
