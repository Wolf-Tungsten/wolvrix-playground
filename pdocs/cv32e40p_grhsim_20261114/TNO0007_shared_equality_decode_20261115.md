# TNO0007：共享同源常量等值译码

本轮实现 TNO0006 优先建议的共享等值译码。**GrhSIM walltime 再降低 7.7577%，95% 配对 bootstrap CI [7.5613%, 7.9593%]，8/8 轮均更快。** 每模拟周期 Host 指令减少 8.3222%。新版本相对归一化 RTL Verilator 的 walltime 为 **1.4015 倍**，相对原始 RTL Verilator 为 **2.9932 倍**。

## 本轮同场结果

| 后端 | walltime 均值 | 仿真循环均值 |
| --- | ---: | ---: |
| 上一版 GrhSIM，含 concat-slice 合并 | 4.509798 s | 4.478246 s |
| 新 GrhSIM，增加共享等值译码 | 4.159931 s | 4.127837 s |
| 同一归一化 RTL Verilator | 2.968224 s | 2.932080 s |
| 原始 RTL Verilator | 1.389829 s | 1.352133 s |

| 配对倍率，分子 / 分母 | walltime | 95% CI |
| --- | ---: | ---: |
| 新 GrhSIM / 上一版 GrhSIM | 0.922423 | [0.920407, 0.924387] |
| 新 GrhSIM / 归一化 Verilator | 1.401488 | [1.399531, 1.403299] |
| 新 GrhSIM / 原始 Verilator | 2.993153 | [2.987101, 2.998057] |

仿真循环下降 7.8245%，CI [7.6239%, 8.0272%]。绝对时间与 TNO0005 不同，所有收益和倍率只使用本轮同一组配对数据，不用历史均值计算累计收益。

node030、CPU96、NUMA1、ASLR disabled、单线程；四侧各预热一次，八轮按“旧 GrhSIM、新 GrhSIM、归一化 Verilator、原始 Verilator”与反序交替。每个样本完整执行 CoreMark 十次迭代，重复数为 1；最短侧仍大于一秒。32 个正式样本全部通过功能和 placement，零重试、零剔除，CPU288 sibling 全部记录为 100% idle。所有构建和 sanitizer 测试在正式计时前结束；perf 在计时后单独执行。

## 实现

[emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp) 新增 `shared_equality_decode`，默认开启。emit attribute 优先于 `WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE`；置 `0` 可关闭。说明见 [功能文档](../../wolvrix/docs/emit/grhsim-shared-equality-decode.md)。

本次使用局部缓存和稀疏更新，保持现有 Boolean 结果槽位，不分配完整域的 one-hot 数组：

```text
首次执行：按原表达式计算所有谓词，比较实际旧值、写回并通知。
源地址相同：所有谓词都不变，跳过这组工作。
源地址改变：清除旧地址的命中项，设置新地址的命中项；未命中的地址不对应任何项。
             对每个实际更新项调用原有的 old/new 比较及 reader 激活代码。
记录这次源地址。
```

静态条件为：同一个 compute supernode 内连续 16–256 个纯 `kEq`，比较同一 SSA source 与不同常量；source 宽度 2–12，已物化或为模型输入。常量位宽相同、无 X/Z，支持两种 operand 顺序。结果必须是独立 canonical Boolean 存储；事件源/结果、存储复用/别名、side effect、不同源、重复常量、跨 scope 均回退。若启用局部重排、priority-mux chain、Boolean producer reduction 或 zero-group guard，也保守回退。

没有 consumer 或 effect 在连续区间内部，因此只更新旧、新项不会改变可观察的中间状态；source 与 Boolean 目标存储类型不同，不能被该区间写回覆盖。每组缓存独立，不能被另一 supernode 更新而破坏旧值推导。`init()` 清除 valid 状态；普通与 fullpass 变体维护同一缓存，fullpass 继续沿用原有的通知抑制策略。

仍调用已有的 scalar change/activation 发射器，所以 direct、deferred、shared、batch-trigger 等通知路径保留各个谓词的 reader 集合。结果参与时钟事件时不应用规则。输入取值方式与普通 equality 相同，包括非整字宽端口 C++ 存储中的高位；不引入额外截断或符号扩展。

阈值只依赖结构，不依赖信号名、CoreMark 行为或测量结果。首次计算和全部地址行为均保留，未将本 workload 中恒 false 的 CSR 谓词删除。多个独立消费组只在源/区间证明成立时各自采用规则，不共享跨 scope 的可变 one-hot 表。

执行 planner 使用同一选择器记录 `shared_equality_decode_groups` 和 `shared_equality_decode_predicates`。由于命中/未命中/重复地址的代价不同，成本标为 `unmodeledWork`，不把它作为每个 IR operation 固定成本供离线排序。fullpass/activation overlay 保留 planner 现有的显式边界。

## CV32 命中与生成代码

固定图中命中 **7 组、354 个谓词**：

| 源 | 各连续组的谓词数 | 合计 |
| --- | --- | ---: |
| `_val_176`，7-bit 字段 | 19 | 19 |
| `_val_134`，decode 阶段 CSR 地址字段 | 63、59、48 | 170 |
| `_val_6162`，execute 阶段 CSR 地址 | 61、64、40 | 165 |

剩余谓词保持普通路径，例如不满足连续长度、已经内联或被其他计算隔开的部分。没有为了扩大命中而重新分区或改变调度顺序。

Boolean 值槽位仍为 1,038，supernodes 仍为 69，compute/commit 文件仍为 10 个。增加七个 previous-address/valid 缓存。生成源码从 1,596,518 增到 1,877,201 bytes，`.text` 从 102,249 增到 117,049 bytes；首次全计算及两个稀疏 switch 分派使静态代码增大。这是换取动态工作量下降的实际代价，不能把它描述成代码体积优化。

关闭新开关后，全部 `.cpp` 与 TNO0005 的冻结模型逐文件 SHA 相同；开启后的 `normalized.json` 与基线逐字节相同。两侧使用相同冻结 `candidate.json`、相同 RTL、固件和 harness；新 emitter 只添加这一项 lowering。Clang 23.1.2、`-O3 -march=native`、波形关闭、正式样本无性能插桩。

新 binary SHA256：`9642e07f8a0add9eaf1b0962005f60aadc5e4d6ce8382622de99489cb8860037`。本次唯一正式测量目录为 `shared-equality-validated`；更早构建仅用于功能开发，没有配对性能数据，未据计时选择实现。

## PMU

两个 GrhSIM binary 各一次 `perf stat`、一次 `cycles:u` 采样；PMU running fraction 均 100%，199 Hz 采样 lost samples 均为 0。计数包含初始化/退出，按 3,376,065 guest cycles 归一化：

| 每模拟周期 | 上一版 | 共享等值译码 |
| --- | ---: | ---: |
| Host instructions | 14,294.09 | 13,104.52 |
| Host cycles | 4,476.35 | 4,110.86 |
| Branches | 567.80 | 599.61 |
| Branch misses | 1.4702 | 1.5579 |
| IPC | 3.1932 | 3.1878 |

Host 指令减少 8.3222%，分支及 branch misses 略增，IPC 基本不变。说明本轮收益主要来自省去多数谓词比较、旧值读取和变化累计，而不是分支预测或初始化改善。两侧初始化均约 6.9 ms。

新版 compute batch 0/1 采样约 12.36%/12.96%，仍有多个数据通路和长 Boolean OR 热点；不按采样比例直接推算下一项优化收益。本轮没有改长 OR 集合化简或 mask mux，它们继续作为独立后续工作。

候选 emit/compile/link 约 2.42/17.74/1.11 s，关闭版重发射校验约 2.46 s；构建时间与仿真计时分开。

## 验证

四侧 smoke 均为 253 cycles，完整 CoreMark 均为 3,376,065 cycles、exit 0，CRC、UART、完成周期和有效总线事务一致。各 workload 的完整 trace SHA256 相同：

- smoke：`84e48e4a17e723b73c167a256a44ded549bd8f82d36cc5be4070554f40763fc0`
- CoreMark：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`

`emit-grhsim-cpp-shared-equality-decode` 与 `emit-grhsim-execution-plan` CTest 通过。新增 focused 用例包含五组正例，以及组过小、域过大、源混合、effect/event、重复或未知常量、位宽不等、分离 scope 等负例。独立 oracle 检查命中、未命中、地址重复、signed/spare-bit 输入、同名端口、重复 eval、寄存器写后固定点、多个下游用户和三次 reinit。

普通开启/关闭、split、runtime profile、shared deferred activation、input fullpass 六种生成模型均通过 Clang 23 O0/O3 + ASan/UBSan。default/on 和环境覆盖有源码一致性检查；普通 planner 的五组命中与 emitter 一致，fullpass 按既有约定标为非普通路径。早期回归发现的局部名遮蔽和非整字宽高位处理已修正，并保留相应用例。

六项比较 runner Python 回归、`py_compile`、两仓 diff 检查及相对链接检查通过。当前 tracked source patch 与测量时冻结 patch 一致；最终报告脚本的新增 coverage 输出仅解析既有生成源。

## XiangShan 与下一步

实现没有 CV32 特例，可能用于 XiangShan 的窄 CSR/枚举等值译码。但它要求同一 SSA source、连续纯比较和独立结果存储；XiangShan 的实际调度和已有 intrinsic 路径可能改变命中。完整 32-bit 指令译码不满足域宽限制。本轮没有重建 XiangShan，也不外推这次 7.76% 收益。

剩余差距仍明显。按 TNO0006 的结构证据，下一步可单独处理同源等值集合的长 OR：例如 62 个地址谓词对应四段常量区间。共享译码仍保留这些消费者，所以集合化简是独立的增量方向；不应把本轮收益与其假设收益相加。

## 复现与产物

保留此前冻结目录，在 node030 本项目目录运行，输出必须为新目录：

```bash
cmake --build build/cv32e40p/tools --target cv32e40p_emit emit-grhsim-cpp emit-grhsim-execution-plan -j16
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
ctest --test-dir build/cv32e40p/tools/grhsim32/wolvrix --output-on-failure \
  -R '^(emit-grhsim-cpp-shared-equality-decode|emit-grhsim-execution-plan)$'
python3 scripts/cv32e40p_equality_compare.py build --output build/cv32e40p/equality-reproduce
python3 scripts/cv32e40p_equality_compare.py attach-verilator --output build/cv32e40p/equality-reproduce
python3 scripts/cv32e40p_equality_compare.py verify --output build/cv32e40p/equality-reproduce
python3 scripts/cv32e40p_equality_compare.py measure --output build/cv32e40p/equality-reproduce
python3 scripts/cv32e40p_equality_compare.py profile --output build/cv32e40p/equality-reproduce
python3 scripts/cv32e40p_equality_compare.py report --output build/cv32e40p/equality-reproduce
```

- [完整报告](../../build/cv32e40p/shared-equality-validated/report.json)、[逐轮 CSV](../../build/cv32e40p/shared-equality-validated/pairs.csv)、[测量策略](../../build/cv32e40p/shared-equality-validated/measurement-policy.json)
- [构建身份](../../build/cv32e40p/shared-equality-validated/build.json)、[冻结 patch](../../build/cv32e40p/shared-equality-validated/wolvrix.patch)、[结构报告](../../build/cv32e40p/shared-equality-validated/structure.json)、[命中清单](../../build/cv32e40p/shared-equality-validated/decode-coverage.json)
- [功能及 trace](../../build/cv32e40p/shared-equality-validated/functional.json)、[完整样本与 placement](../../build/cv32e40p/shared-equality-validated/runs/)
- [归一化 Verilator summary](../../build/cv32e40p/shared-equality-validated/verilator-summary.json)、[原始 Verilator summary](../../build/cv32e40p/shared-equality-validated/verilator-original-summary.json)
- [旧 PMU](../../build/cv32e40p/shared-equality-validated/grhsim_baseline-stat.csv)、[新 PMU](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality-stat.csv)、[新热点](../../build/cv32e40p/shared-equality-validated/grhsim_shared_equality-perf.txt)
- [CTest 日志](../../build/cv32e40p/shared-equality-validated/validation/ctest.log)、[验证清单](../../build/cv32e40p/shared-equality-validated/validation/checks.json)、[比较脚本](../../scripts/cv32e40p_equality_compare.py)

改动仍在 `thj/cv32e40p-grhsim-investigation-20261114` 工作树，尚未新增提交。
