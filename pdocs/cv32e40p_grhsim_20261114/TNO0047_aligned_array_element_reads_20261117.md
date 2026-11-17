# TNO0047：按静态元素对齐读取一个 word

承接 TNO0046，先落实一个独立的表示组合修复：宽 packed source 的 scalar `SliceArray` 已经携带元素宽度，因此即使 concat 的等宽 lane 表示被 simplify 合并，也可利用元素对齐证明避免通用跨 word 拼接。本轮以 TNO0044 的 connected-shared 候选为固定基线，XiangShan 与 CV32 使用同一新库。没有组合其他实验选项或修改调度规则。

**三对XS结果为walltime +0.6512%，95% CI [+0.0154%, +1.2907%]，3/3更慢。局部读取的机器码改善没有转化为本窗口的整机收益。CV32无命中、模型代码及关键ELF节完全相同，三对差异为+0.0201%且CI跨零。新规则保持默认关闭，原connected候选继续作为性能基线。**

## 固定实现

新增默认关闭的 `aligned_array_slice` / `WOLVRIX_GRHSIM_ALIGNED_ARRAY_SLICE`。当源宽度大于64、索引和结果为scalar、结果宽度等于`sliceWidth`且该宽度整除64时，读取一个有边界检查的源word，移位并mask。元素宽度1/2/4/8/16/32/64自然满足条件；这不是按模型、站点或执行次数设置的阈值。

例如4-bit元素的`start=index*4`必有`(start%64)+4<=64`，无需读取下一word。已有packed-lane和reg-to-mem专用lowering仍优先。本轮不重建byte-lane数组，不改变source构造、状态存储、生命周期、区域或通知；ROB的2KiB捕获对象问题留作独立工作。

索引乘法及转成`size_t`的表达式逐字保留，包括既有unsigned wrap行为；word边界与source padding沿用原helper。规则不会顺便改变索引语义。planner新增对应shape计数，不调整batch估计。生成决策没有运行结果输入。[功能说明](../../wolvrix/docs/emit/grhsim-aligned-array-slices.md)

## 回归与静态门

专项`emit-grhsim-aligned-array-slice`通过O0和O3 ASan/UBSan的独立按bit提取oracle，覆盖全部合法宽度、非整除宽度及wide-result回退、混合16×4+64 concat、跨组生产/消费、source尾部padding、signed结果、输入存储高位、大索引/既有wrap、反复eval及输入单独变化。default/off、环境变量与attribute优先级、模型布局一致性通过。

首次fixture漏提供空`state_read_supernodes` session槽，在任何生成模型执行前被拒绝；补齐fixture后通过，未修改生产规则。既有`emit-grhsim-execution-plan`、`emit-grhsim-cpp-packed-array-late-index`也通过，共3项CTest；24项测量/统计工具Python回归通过。

XiangShan关闭新选项时，140个生成文件精确复现TNO0044最新候选。开启后所有区域/操作、状态视图/缓存/条件锥标记、scalar变化检查及活动数组操作记录hash一致；模型header与`eval.cpp`逐字相同。仍有84,690个compute区域、346个commit区域、2551个状态视图。

| 替换元素宽度 | 4 bit | 8 bit | 32 bit | 64 bit | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| XS生成读取位置 | 5 | 1 | 74 | 48 | **128** |

位置数是源码出现次数，不是每周期执行次数。[结构门](../../build/xs/aligned-array-slice-20261117-v1/structure.json)、[源码位置](../../build/xs/aligned-array-slice-20261117-v1/sites.json)

CV32未命中；全部18个模型C++文件相同，ELF的`.text/.rodata/.data`逐节SHA相同。新增未使用的runtime模板不会进入这些节。两边使用的冻结native库SHA相同。CV32三后端smoke、完整CoreMark和总线trace通过；其后续计时属于同代码重复性对照，不能记为本规则收益。[代码身份](../../build/cv32e40p/aligned-array-slice-v1/code-identity.json)

## 冻结测量协议

延续探索阶段的三对：XS full/candidate各一次10k smoke、两个seed的100k DiffTest trace、各一次预热，然后三对AB/BA。CV32为基线、候选、同RTL Verilator三轮正反序，完整CoreMark。所有正式计时在构建和回归结束后，串行使用node030 CPU96、NUMA1、单线程、ASLR off和共同文件锁；保留全部样本，无按速度重试或追加。

XS仍是CoreMark镜像的前100k周期窗口，不称完整CoreMark完成。正式计时后预先声明每模型一次独立PMU计数，仅评价冻结模型，不调整规则或产生后续候选。

驱动：[aligned_array_slice_compare.py](../../scripts/aligned_array_slice_compare.py)；XS冻结规则：[policy](../../build/xs/aligned-array-slice-20261117-v1/policy.json)，[诊断规则](../../build/xs/aligned-array-slice-20261117-v1/diagnostic-policy.json)。

## 结果

两边整机编译完成。当前bitmapcache同一结果的提取核心从17条静态指令、2个条件跳转，降到8条连续指令、没有条件跳转：`mov index → bextr word-index → shr/and shift → shrx 单word读取 → and mask → store`，另含提取常数准备。新窗口为`0xe5e2b4..0xe5e2d8`；header与基线一致，array/index/result成员偏移沿用TNO0046独立编译所得`0x1f9c68`、`0x12f680`、`0xe192c`。旧17条包含两条分支路径，不是声称每次净减少9条退休指令。[核心证据](../../build/xs/aligned-array-slice-20261117-v1/bitmapcache-core-evidence.json)、[新汇编](../../build/xs/aligned-array-slice-20261117-v1/machine-evidence/bitmapcache-core.s)

| XS compute ELF静态指标 | connected基线 | 本轮候选 | 差额 |
| --- | ---: | ---: | ---: |
| 指令 | 13,755,365 | 13,754,892 | −473（−0.00344%） |
| 条件跳转 | 563,299 | 563,252 | −47 |
| 带内存操作数指令，不含lea/nop | 5,480,957 | 5,480,826 | −131 |
| RSP相对访存位置 | 1,129,226 | 1,129,100 | −126 |

commit/eval总量保持不变。128处源码替换不等于每处都节省相同机器工作；编译器原本已能消除部分对齐场景的通用逻辑。相对整机静态规模，本轮削减很小，不能从局部17→8推出明显walltime改善。[完整ELF统计](../../build/xs/aligned-array-slice-20261117-v1/machine-analysis.json)

CV32三轮外部walltime相对基线 **+0.0201%**，95% bootstrap CI **[−0.1440%, +0.2151%]**；两边均值2.649079/2.649606秒。同代码/关键ELF节身份已证明，这属于重复性波动，无本规则收益。9个正式样本和18个首尾放置/NUMA快照审计通过。[统计](../../build/cv32e40p/aligned-array-slice-v1/summary.json)、[独立审计](../../build/cv32e40p/aligned-array-slice-v1/independent-review.json)

XS两侧10k smoke及两个seed的100k DiffTest通过，各seed的99,999条记录一致。终点均为PC `0x80000c1a`、instrCnt 250838、cycleCnt 99995、guest cycles 100001，cycle-limit停止。

| XS指标 | connected基线均值 | 候选均值 | 配对平均变化 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | --- |
| 外部walltime | 111.626481 s | 112.351248 s | **+0.6512%** | **[+0.0154%, +1.2907%]** |
| Host time | 111.567000 s | 112.290000 s | +0.6500% | [+0.0160%, +1.2894%] |

| 对次 | 顺序 | 基线wall秒 | 候选wall秒 | 候选变化 |
| --- | --- | ---: | ---: | ---: |
| 0 | 基线→候选 | 112.531103 | 112.548457 | +0.0154% |
| 1 | 候选→基线 | 111.507949 | 112.947205 | +1.2907% |
| 2 | 基线→候选 | 110.840393 | 111.558082 | +0.6475% |

三对全保留，没有重试、删点或追加轮次。基线时间也有变化，不能把小样本的区间当作跨时间/负载保证；当前结果不足以采用这项优化。独立复核覆盖14次XS运行、2739个线程/CPU快照、281个原始NUMA快照；全部通过，正式CPU288空闲率99.9821%–100%。[正式统计](../../build/xs/aligned-array-slice-20261117-v1/report.json)、[原始轮次](../../build/xs/aligned-array-slice-20261117-v1/measurement/rounds.json)、[独立审计](../../build/xs/aligned-array-slice-20261117-v1/independent-review/review.json)

13个compute主函数的静态统计发生变化，总`.text`从88,889,586降为88,887,266 B，仅少2320 B。省掉的核心读取和边界逻辑已在ELF中确认，但本轮没有逐站点执行计数，不能假定128处都热，也不能把变慢直接归为cache miss、spill或某个分支。寄存器分配、地址布局及未分离的运行波动都可能影响如此小的代码改动，目前未完成其因果分摊。

## 独立PMU与判断边界

正式样本全部结束后，两模型各运行一次100k周期PMU，CPU96串行执行，功能签名一致。观测值如下：

| 每guest cycle | connected基线 | 候选 | 变化 |
| --- | ---: | ---: | ---: |
| instructions:u | 3,647,034.724 | 3,657,811.563 | +0.2955% |
| cycles:u | 4,072,960.452 | 4,096,169.140 | +0.5698% |
| branches:u | 363,969.457 | 364,909.363 | +0.2582% |
| branch-misses:u | 42,934.629 | 43,061.090 | +0.2945% |

PMU没有显示整机工作量下降，但不把这组数字当作精确因果归因：每侧只有一次、包含harness/NEMU，附着会漏掉短启动窗口；事件运行比例分别报告99%/100%，满足原99%门但有计数覆盖/缩放限制。没有当前逐站点或逐区域的动态成本分解，不能认定+0.30%必然全由该helper引起，更不能拿这一次计数重算三对时间CI。[PMU结果](../../build/xs/aligned-array-slice-20261117-v1/pmu/summary.json)

本轮完成了通用读取简化及双模型验证，结果支持“局部结构已修正”，不支持“整机性能改善”。新开关仍默认关闭，不替换原connected基线。未按结果调阈值、筛站点、改变128处选择、追加组合或重新跑一组更有利的样本。若继续推进，快照/捕获准备以及更大范围的数组消费表示应独立设计，不能从这128处中挑选本负载热点。

## 归档与复现

两个模型、正式时间、PMU及离线ELF分析已经完成。3项CTest、24项Python回归、两个模型功能/轨迹、三对测量与统计审计、生产源码/冻结库身份和文档链接核对通过。CV32和XS正式测量及XS PMU通过同一shell顺序协调，所有模拟器采样均持有共同CPU96文件锁。

代码位置：[emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp)、[语义回归](../../wolvrix/tests/emit/test_emit_grhsim_aligned_array_slice.cpp)、[源码/ELF分析](../../scripts/aligned_array_slice_analysis.py)、[XS逐样本审计](../../scripts/aligned_array_slice_review.py)、[诊断驱动](../../scripts/aligned_array_slice_diagnose.py)。生产生成规则和预算在运行后未修改。

最终检查见 [validation.json](../../build/xs/aligned-array-slice-20261117-v1/validation.json)。重放时使用新目录，build和measure在node030执行；先完成两边build与回归，再串行调用verify-cv、measure-cv、measure-xs、diagnose：

```sh
python3 scripts/aligned_array_slice_compare.py prepare-xs --output build/xs/aligned-array-reproduce
python3 scripts/aligned_array_slice_compare.py build-xs --output build/xs/aligned-array-reproduce
python3 scripts/aligned_array_slice_compare.py build-cv --output build/cv32e40p/aligned-array-reproduce
python3 scripts/aligned_array_slice_compare.py verify-cv --output build/cv32e40p/aligned-array-reproduce
python3 scripts/aligned_array_slice_compare.py measure-cv --output build/cv32e40p/aligned-array-reproduce
python3 scripts/aligned_array_slice_compare.py measure-xs --output build/xs/aligned-array-reproduce
python3 scripts/aligned_array_slice_diagnose.py --source build/xs/aligned-array-reproduce
```
