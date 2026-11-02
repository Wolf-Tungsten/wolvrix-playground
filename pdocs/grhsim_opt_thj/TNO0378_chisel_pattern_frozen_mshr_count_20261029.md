# TNO0378：真实 MSHRCtl 计数子锥——打包成本改变 PopCount 结论

日期：2026-10-29。关联：[扩展实验](./TNO0377_chisel_pattern_expanded_evidence_20261029.md)。

## 从真实香山取证

取自冻结生成包的 [p0 compute batch 116](../../build/xs/grhsim32_fresh_rtl_20261028/initial/package/grhsim_Gpart_0_model_sched_116.cpp:75)，
Supernode 928，包含 16 个 MSHR valid 和 2 个 pipe valid 的计数。3 个 uint8_t 声明原样
抽取，不重写算式；保留所有 value_bool_slots_ 的原索引。RTL 对应
[MSHRCtl.sv:2071](../../build/xs/grhsim32_fresh_rtl_20261028/rtl/rtl/MSHRCtl.sv:2071)。
GRH 原生 source CSV 把相应 kAdd/kConcat 放在 group 928；组内还包含其他逻辑，不能
把整组计时算作计数耗时。

Chisel 端有 [tl2tl MSHRCtl](../../testcase/xiangshan/coupledL2/src/main/scala/coupledL2/tl2tl/MSHRCtl.scala:101)
的 pipeReqCount/mshrCount 线索；该 Scala 定位按模块和接口关联，不能冒充唯一 elaboration
SourceInfo 映射。RTL→GRH→batch/group 的来源是精确的。

## 实验边界

对全部 262,144 个 18-bit 输入穷举，并检查两组各 100,000 随机输入。计时使用预先填好的
128 份状态布局，输入生成不计时；三种分布、三种候选各 8 对 AB/BA。

- 原算式：保留真实三个 C++ 表达式与分散 bool slot 读取。
- 直接求和：读取相同槽位，直接相加。
- gather + popcount：读取相同槽位，打包 18 位后计数。
- packed 下界：输入已经打包，忽略打包与维护成本；不是可直接替换的候选。

不计来源槽位的生产、不计两个 block 输出的比较/激活、不计外部传播；与整机 walltime 无直接换算关系。

| 分布 | 候选 | 原表达式 ns | 候选 ns | 配对变化 |
|---|---|---:|---:|---:|
| random | direct_sum | 4.326 | 4.556 | +5.5% |
| random | gather_popcount | 4.349 | 4.259 | -3.1% |
| random | packed_lower_bound | 4.404 | 2.209 | -49.9% |
| sparse | direct_sum | 4.218 | 4.551 | +7.6% |
| sparse | gather_popcount | 4.286 | 4.265 | -0.6% |
| sparse | packed_lower_bound | 4.431 | 2.223 | -49.9% |
| dense | direct_sum | 4.061 | 4.032 | -0.5% |
| dense | gather_popcount | 4.322 | 4.269 | -1.3% |
| dense | packed_lower_bound | 4.334 | 2.223 | -49.3% |

## 结论与接口含义

真实分散布局下，直接求和或 gather+popcount 与原算式接近。预先打包的版本明显较小，
但这是排除了打包成本的下界，不能据它宣称此处改写就能获得对应收益。

因此语义接口应表达“这些位的数量”，而不强制要求某种 C++ 指令。后端至少要区分：

1. 输入本来就是单个字或少量连续字：优先评估 popcount。
2. 输入是分散的 bool/state slot：比较 gather、求和或直接读取已有 packed view。
3. 若维护增量 packed view：必须计入每次位变化的更新、活动依赖和额外存储成本。

这也是 Chisel 层双实现值得研究的原因：它可以保留操作身份，同时把布局选择留给仿真
后端，而不是把硬件树展开后再从数百个标量操作中恢复意图。

复现工具：[chisel_pattern_frozen.py](../../scripts/chisel_pattern_frozen.py)。
[原始计时](../../wolvrix/build/artifacts/chisel-pattern-study/frozen-count/measurement.json)、
[抽取与输入身份](../../wolvrix/build/artifacts/chisel-pattern-study/frozen-count/manifest.json)、
[原样表达式及 harness](../../wolvrix/build/artifacts/chisel-pattern-study/frozen-count/frozen_count.cpp)。
