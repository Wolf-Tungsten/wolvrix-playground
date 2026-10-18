# GrhSIM preserve-aggregate=all：XiangShan CoreMark 提交数差异排查

- 日期：2026-10-18
- 状态：本次 100k 周期回归通过；preserve-aggregate=all GrhSIM 与 plain Verilator 均为 instrCnt=238535、cycleCnt=99996，231,568 条提交记录含周期完全一致
- 对象：同一份 XiangShan 设计，GrhSIM IR（`--preserve-aggregate=all`）与 **plain/scalar RTL 的 Verilator**；plain Verilator 是唯一参考
- 负载：CoreMark，单核，NEMU difftest

**最终结果（16:44）**：已修复三类 ingest 问题：比较操作数的上下文定宽、折回
标量后的 struct 部分写入定宽、嵌套叶子读取的剩余宽度。重新从 aggregate SV
生成整机后，原 cycle 13647 的 WriteBuffer 断言和首次晚 6 拍的提交偏移均消失。
完整 100k 对照差异为 0，独立回放与 64 项 CTest 也全部通过。下文保留各阶段
证据和被撤回的早期判断，最新整机结果见文末。

## 现象

修复前的 100k 周期端点记录显示，aggregate 路径为 `instrCnt=225471`，历史
plain Verilator 参考端点为 `instrCnt=240349`。排查初期采用已有 30k
提交 trace 做确定性对齐：

| 项目 | plain Verilator | GrhSIM aggregate |
| --- | ---: | ---: |
| 提交数 | 27512 | 26350 |
| 首个提交序号（0-based） | 2888 | 2888 |
| 首个分歧提交 cycle | 13089 | 13095 |
| 首个分歧 PC | `0x80000124` | `0x80000124` |
| 指令 | `00051783` | `00051783` |

30k 对照的完整上下文在
[`20261017_verilator_vs_aggregate_trace30k_compare.txt`](../ptmp/xs/logs/20261017_verilator_vs_aggregate_trace30k_compare.txt)。
分歧前提交内容和写回数据仍相同，首先变化的是提交时刻，随后 aggregate 少提交。

## 已确认并修复的 ingest 位宽错误

### 时间映射修正与当前有效分歧

aggregate 的 raw FST 时间应映射为：

```text
cycle = floor((raw_time - 105) / 2)
```

旧记录采用 `-107`，会人为引入一周期偏移。此前 cycle 8245 的 ready/fire
相位判断不能继续用作调度错误的证据。修正映射后，
[`20261018_bpu_diff_offset105_8238_8262.txt`](../ptmp/xs/logs/20261018_bpu_diff_offset105_8238_8262.txt)
中可比较的 623 个信号没有分歧，但另外 5263 个信号为 silent，不能把这个结果
扩大为全部信号已证明相同。

当前关键分歧为（A=aggregate，B=Verilator）：

| cycle | 信号 | A | B |
| ---: | --- | --- | --- |
| 10286 | `abtb.t1_needCorrectTarget` | 1 | 0 |
| 10287 | `abtb.banks_0.writeValid` | 1 | 0 |
| 13070 | `inner_bpu.s3_override` | 1 | 0 |
| 13070 | `inner_bpu.s3_predictionSource` | `010` | `011` |
| 13071 | `inner_bpu.s2_valid` / `s3_valid` | 0 | 1 |
| 13085 | `inner_ftq.bpuEnqueue` / `ifuReqValid` | 0 | 1 |

证据：
[`20261018_10000_13100_diff_bpu_offset105.txt`](../ptmp/xs/logs/20261018_10000_13100_diff_bpu_offset105.txt)
和
[`20261018_10000_13100_diff_ftq_offset105.txt`](../ptmp/xs/logs/20261018_10000_13100_diff_ftq_offset105.txt)。
这是当前已定位路径的时间顺序，不代表已证明 10286 的错误是 13070 分歧的唯一原因。

### RTL、GRH 与生成代码（修复前工件）

[`AheadBtb.sv:590`](../ptmp/xs/rtl/rtl/AheadBtb.sv:590) 用 8 个条件表达式选择
22 位 `targetLowerBits`，按位 OR 后再与预测目标低 22 位比较：

```systemverilog
wire t1_needCorrectTarget = t1_hit & (&branchType)
  & (((sel[0] ? target0 : 22'h0) | ... | (sel[7] ? target7 : 22'h0))
     != target_addr[21:0]);
```

在修复前生成的
[`xiangshan_flat_grh.json`](../ptmp/xs/grhsim-ir/xiangshan_flat_grh.json:2168030)
中，Mux 输出保持 22 位，OR 链输出却成为 1 位：

| 节点 | 操作 / 含义 | 输入宽度 | 输出宽度 |
| --- | --- | --- | --- |
| `_op_504541` → `_val_461527` | 第 6 路 `kMux` | 条件 1、两个分支各 22 | 22 |
| `_op_504542` → `_val_461528` | OR 链中间结果 | 1、22 | **1** |
| `_op_504547` → `_val_461533` | 第 7 路 `kMux` | 条件 1、两个分支各 22 | 22 |
| `_op_504548` → `_val_461534` | 最后一个 `kOr` | 1、22 | **1** |
| `_op_504549` → `_val_461535` | `target_addr[21:0]` | 目标地址 | 22 |
| `_op_504550` | `kNe` 比较 | **1、22** | 1 |

`kMux` 的三个 operand 分别是条件、条件为真时的值、条件为假时的值；
`kOr` 是逐位 OR；`kNe` 的两个 operand 是待比较的值。比较结果为 1 位是正常的，
比较前的 OR 结果被截成 1 位才是错误。

历史
[`pre_flatten.grh.json`](../ptmp/xs-aggr-diag/pre_flatten.grh.json:3411244)
在 `AheadBtb` graph 内也有同样现象：`_val_81911`、`_val_81917` 为 22 位，
`_val_81918`、`_val_81925` 为 1 位。其
[`dump_pre_flatten.py`](../ptmp/xs-aggr-diag/dump_pre_flatten.py)
在 `hier-flatten` 前存储设计，说明这个旧工件中的损坏早于 flatten、simplify、
CPU mapping 和最终 C++ 输出。该文件生成于 10 月 10 日，不能单独替代当前版本的
ingest 验证；下节的小复现补上了这点。未 flatten 的 symbol 只在所属 graph 内唯一。

当前生成代码
[`grhsim_SimTop_tu273.cpp:9664`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu273.cpp:9664)
把各路 `targetLowerBits` 按 `& 1` 使用，OR 链用 `bool`，随后把这个 1 位值与
`_val_461535 & 0x3fffff` 比较。这是 GRH 中的错误已经变成实际计算的证据。

在 cycle 10286，reference 的 entry 4 `hit=1`，其 position 与最终预测均为
`11010`，其 target 和最终预测的低 22 位均为 `0000000001001110110101`
（`0x13b5`）。这些值见
[`entries_target_4`](../ptmp/xs/logs/20261018_get_ref_abtb_entries_target_4_10280_10290.txt)、
[`target`](../ptmp/xs/logs/20261018_get_ref_abtb_target_10280_10290.txt)、
[`entries_hit_4`](../ptmp/xs/logs/20261018_get_ref_abtb_entries_hit_4_10280_10290.txt)。
正确比较应为 `0x13b5 != 0x13b5`，结果 0；截断后变为
`1 != 0x13b5`，结果 1，与 `t1_needCorrectTarget` 的实际分歧吻合。

### 源码路径：外层赋值宽度穿过比较边界（修复前）

1. `StmtLowererState::handleNetInitializer`
   （[`ingest.cpp:2953`](../wolvrix/lib/core/ingest.cpp:2953)）用 net 的宽度建立
   `WidthContextScope`。对 `wire t1_needCorrectTarget`，上下文为 1。
2. `lowerExpression(BinaryExpression)`
   （[`ingest.cpp:11046`](../wolvrix/lib/core/ingest.cpp:11046)）直接递归降低左右
   operand。`!=` 没有隔离外层的 1 位上下文。
3. `ConditionalExpression`
   （[`ingest.cpp:11207`](../wolvrix/lib/core/ingest.cpp:11207)）创建 `kMux` 时没有
   设置 `widthHint`；`ExprNode` 默认值是 0，`addNode` 也不补宽度。
   `resizeValueToWidth` 遇到未知源宽度直接返回，因此这里的 Mux 仍保留 hint=0。
4. 父级按位 OR 看到两个 Mux 的 hint 都为 0，在
   [`ingest.cpp:11108`](../wolvrix/lib/core/ingest.cpp:11108)
   的 `else if (widthContext > 0)` 中令 `targetWidth=1`，随后写入 OR 的 hint。
5. 后续 `applyExprWidthHint` 只在 hint=0 时调用，因此没有调用
   `computeExprWidth` 来纠正 OR。当前证据不支持“Slang 把 22 位 OR 类型算成了 1 位”。
6. GRH 组装（[`ingest.cpp:25454`](../wolvrix/lib/core/ingest.cpp:25454)）会从分支
   恢复未知宽度 Mux 的 22 位输出，却信任 OR 已经写下的 1 位 hint，于是留下
   `Mux(22), Mux(22) → Or(1)`。

这说明修复必须处理比较操作数的宽度边界。**单独给 Mux 补上 22 位 hint 并不足够**：
原 conditional 路径末尾仍会按继承的 `widthContext=1` 调用 resize，那会直接
把 Mux 结果切成 1 位。应先按 SV 的比较操作数定宽规则阻断外层赋值宽度，再处理
Mux 的宽度信息，并检查类似的逻辑、归约、条件表达式边界。

### 修复前小复现：不需要完整设计或后端

工件：[`ptmp/xs-target-width-diag/`](../ptmp/xs-target-width-diag/Makefile)。
运行入口为 `make -f ptmp/xs-target-width-diag/Makefile run`，仅执行
`read_sv → store_json`，未执行任何 transform 或仿真。标量输入和 packed struct
输入分别保存为 `scalar.sv`、`aggregate.sv`，每份只有约 10 行。

| 写法 | scalar 的 OR 宽度 | aggregate 的 OR 宽度 | 预期宽度 |
| --- | ---: | ---: | ---: |
| `wire flag = ((c0 ? a : 22'h0) \| (c1 ? b : 22'h0)) != expected` | **1** | **1** | 22 |
| 上式结果 net 改为 `[7:0]`，表达式不变 | **8** | **8** | 22 |
| 先将选择结果存进 `wire [21:0] selected`，再比较 | 22 | 22 | 22 |
| 直接 `(a \| b) != expected`，不含条件 Mux | 22 | 22 | 22 |

单个 Mux 直接比较的对照也保留 22 位操作数。结果表明：这是 ingest 中的上下文
传播与缺失宽度信息组合触发的问题，packed aggregate 不是触发它的必要条件。
完整输出在
[`run-complete.log`](../ptmp/xs-target-width-diag/run-complete.log)，机器可读结果在
[`observations.json`](../ptmp/xs-target-width-diag/observations.json)。
本次成功运行耗时约 0.05 秒，峰值 RSS 54,352 KiB，退出码 0。

### 独立模块仿真复现（修复前）：CASE_026

新增
[`CASE_026/rtl/AheadBtbTargetCorrect.sv`](../testcase/xs-bugcase/CASE_026/rtl/AheadBtbTargetCorrect.sv)，
从原模块提取 position / attribute 命中检查、优先编码、8 路 22 位目标选择与 OR、
`t1_needCorrectTarget`，以及 bank 0 的 correction 写使能。保留这些逻辑读取的
packed struct / packed array 字段。它是提取出的组合锥，不包含完整 AheadBtb 的
SRAM、训练寄存器、replacer 或时钟行为。

[`tb.v`](../testcase/xs-bugcase/CASE_026/tb.v) 将 scalar 输入打包为 train 接口，
[`tb.cpp`](../testcase/xs-bugcase/CASE_026/tb.cpp) 在同一进程中驱动 Verilator 和
经现有 XiangShan GrhSIM IR CPU pipeline 生成的模型，并检查两边的输出。
第一组输入使用 cycle 10286 的关键值：命中 way 4、position 26、branchType 3、
rasAction 2、所选目标和比较目标低 22 位均为 `0x13b5`。未选择的 entry 统一使用
相同数据，目标高位使用合成常量；这不是完整原始 train 输入的逐位回放。

```sh
make -C testcase/xs-bugcase/CASE_026 reproduce
```

实际首组输出为：

```text
selected=0x10 target=0x0013b5 expected_low22=0x0013b5
needCorrectTarget ref=0 grhsim=1 writeBank0 ref=0 grhsim=1
[SUMMARY] vectors=72 mismatches=51 reference_or_control_errors=0 trace_10286=reproduced
```

覆盖所有 8 个 way，目标低位为 0、1、2、3、`0x13b5`、`0x3fffff`，以及仅高位
不同的目标和命中/位置/属性/训练使能/bank 屏蔽条件。Verilator 全部符合独立计算
的期望值，两边的 hit 和优先选择结果始终一致。修复前该错误既会在目标相等时多发
correction，也会在目标仅高位不同时漏发 correction。

修复前 `reproduce` 以“预期错误出现”为成功条件，退出 0；`run` 是严格等价检查，
比较程序返回 1、Make 返回 2。该复现仅依赖已安装的 Wolvrix binding 和
Verilator；生成代码、二进制、IR、日志和当前结果均位于
`ptmp/xs-bugcase/CASE_026/`；修复前结果另存为
[`case026-before.csv`](../ptmp/xs-target-width-fix/case026-before.csv)。修复前复核执行
`verify-extraction reproduce`，核心表达式与原 RTL 的逐字比较通过，构建加运行
约 3.61 秒，峰值 RSS 231,756 KiB
（约 226 MiB）。命令运行在独立子 session 中，设置 120 秒超时和 24 GiB
虚拟地址上限，未构建完整 XiangShan 或运行 CoreMark。

修复前验证日志：
[`reproduce.log`](../ptmp/xs-bugcase/CASE_026/reproduce.log)（提取一致性及错误复现，退出 0），
[`strict.log`](../ptmp/xs-bugcase/CASE_026/strict.log)（严格等价检查，Make 退出 2）。

该结果把“JSON 中宽度异常”的证据推进为 **独立模块实际输出错误**。它仍不能
单独证明 100k 提交数差额全部由这一处错误造成。

### 修复实现与最终验证（2026-10-18）

已修改 [`ingest.cpp`](../wolvrix/lib/core/ingest.cpp)：比较、逻辑运算、逻辑非、
归约运算的 operand，以及 `?:` 的判定表达式，使用 Slang 已定宽的表达式类型
建立局部宽度上下文，避免继承最终布尔结果的 1 位上下文。比较两侧的类型已包含
SV 的共同定宽规则。Mux 创建时补上表达式的 `widthHint`，让父节点和 resize
都能看到其真实宽度。

修复后的目标路径为 `Mux(22) → Or(22) → Ne(22,22) → 1`。`Ne` 的两个 operand
分别为选中的目标和预测目标低位；两者都保留 22 位，只有比较结果为 1 位。
局部上下文必须保留表达式类型宽度：例如 `(a * b) != expected` 中，22 位
乘法仍须按 22 位溢出，不能因清空上下文而走到 44 位乘法的回退路径。

新增 CTest
[`ingest-expression-width`](../wolvrix/tests/ingest/test_ingest_expression_width.cpp)
及其 [`SV fixture`](../wolvrix/tests/ingest/data/expression_width.sv)，覆盖全部 10 类
比较运算、1 位与 8 位结果 net、标量与 packed struct 目标、不同输入宽度、逻辑
与归约运算、宽条件判定，以及乘法溢出边界。验证了原错误会使回归失败，最终实现
通过。新增入口为 `make test_ingest_expression_width`。

通过 `make py_install` 重新构建并安装 binding 后，重新生成 CASE_026 的 GrhSIM
模型，与 Verilator 执行严格等价检查。case 每次都会重新生成 GrhSIM 模型，避免
复用修复前的二进制；也已加入 `run_xs_bugcase_grhsim` 的用例列表。

| 验证 | 最终结果 | 日志 |
| --- | --- | --- |
| `make test_ingest_expression_width` | 通过；新增边界回归 | [`unit-final.log`](../ptmp/xs-target-width-fix/unit-final.log) |
| `make test_wolvrix` | 64/64 通过，退出 0 | [`suite-final.log`](../ptmp/xs-target-width-fix/suite-final.log) |
| `make -C testcase/xs-bugcase/CASE_026 verify-extraction run` | 核心表达式与原 RTL 逐字一致；72/72 等价，退出 0 | [`case026-after.log`](../ptmp/xs-target-width-fix/case026-after.log) |

修复后独立模块结果：

```text
[SUMMARY] vectors=72 mismatches=0 reference_or_control_errors=0 trace_10286=matched
[PASS] isolated AheadBtb target correction matches Verilator
```

cycle 10286 的目标低位仍为 `0x13b5`；现在 `needCorrectTarget` 和 `writeBank0`
均为 `Verilator=0、GrhSIM=0`。72 组的差异从 51 组降至 0 组，详见
[`case026-after.csv`](../ptmp/xs-target-width-fix/case026-after.csv)。最终 case 构建
及运行约 3.64 秒，峰值 RSS 232,208 KiB（约 227 MiB）。完整测试过程仍在隔离
子 session 中执行，限制并发和虚拟地址空间，未重建或重跑完整 XiangShan。

### 多余写入之后的影响：仍在隔离

`AheadBtb.sv:604` 的 `_GEN_23 = t1_fire & t1_needCorrectTarget` 直接驱动 target
correction 写请求。现有波形在下一周期 10287 看到 bank 0 多出 `writeValid`。
该周期 train 的 bank mask 为 `0001`，set index 为 `11000`（24），与 bank 0
路径一致。

本轮对已有 FST 追加单进程、固定模块的查询：
[`wave-replacer.log`](../ptmp/xs-target-width-diag/wave-replacer.log)
显示 bank 0 的 `writeReplacerGen.io_nextState` 在 10287 分歧，A=`0101101`、
B=`1101011`。`fst_diff` 因发现分歧返回 1，Make 因此返回 2；这是工具的正常报告
语义，非超时或 OOM。峰值 RSS 221,560 KiB。

但是 nextState 在 reference 写无效时不必被采用，不能直接把这个组合输出差异
当作已写入的状态差异。对 replacer 的 `state_vec` / reference `state_vec_24`
查询 10284–10292，没有捕获到变化记录，见
[`state-aggregate.txt`](../ptmp/xs-target-width-diag/state-aggregate.txt)、
[`state-reference.txt`](../ptmp/xs-target-width-diag/state-reference.txt)。
这也不能用来推断窗口起点的值相同。10286 的语义错误已经确认，但它如何影响
13070 的最终预测仍需继续追踪。

另外，BPU core 的报告中 `sc.t1_writeThresVec_updated_scWrong` 在 cycle 12946
已有差异，`sc.s3_override` 在 13070 差异，见
[`bpu_core_offset105`](../ptmp/xs/logs/20261018_10000_13100_diff_bpu_core_offset105.txt)。
下一步应直接展开 `s3_override` 的组合依赖，区分 ABTB 多余训练的后果和 SC 路径
可能存在的其他 lowering 错误。

## 早期波形记录（时间映射已修正，保留排查历史）

波形对照的第一语义分歧位于前端 FTQ/BPU。`fullbase_0.txt` 和 `fullbase_1.txt`
是已保存的映射后差异报告（A=aggregate，B=Verilator）：

| 信号 | aggregate 首次相对 Verilator 的现象 | cycle |
| --- | --- | ---: |
| `frontend.inner_ftq.bpuEnqueue` | A=0，B=1 | 8245 |
| `frontend.inner_bpu.ubtb.s1_fire` | A=0，B=1 | 8245 |
| `frontend.inner_bpu.s2_valid` | A=0，B=1 | 8246 |
| `frontend.inner_bpu.s3_valid` | A=0，B=1 | 8247 |
| `frontend.inner_bpu.s3_startPc` / FTQ 起始 PC | 首次进入差异传播区；精确相位受波形空洞影响 | 约 8247–8250 |

按已有 `fullbase_*.txt` 的同周期映射，Verilator 在 cycle 8245 产生
`prediction.ready`、`bpuEnqueue` 以及 UBTB/ABTB 的 fire，而 aggregate 在该周期为
0。对短窗原始 FST 进一步取值后，使用其与报告一致的半周期映射
`cycle=floor((raw_time-107)/2)` 可以看到 aggregate 的这些脉冲整体提前约 1 个周期：

| 信号 | aggregate | Verilator |
| --- | --- | --- |
| FTQ ready（aggregate `_io_fromBpu_prediction_ready_T_20` / reference 接口） | 8244=1，8245=0，8246=1 | 8245=1，8246=0，8247=1 |
| `ubtb.s1_fire` | 8244=1，8245=0，8246=1 | 8245=1，8246=0，8247=1 |
| `s2_valid` | 8245=1，8246=0，8247=1 | 8246=1，8247=0，8248=1 |
| `s3_valid` | 8246=1，8247=0，8248=1 | 8247=1，8248=0，8249=1 |
| `bpuEnqueue` | 8244=1，8245=0，8246=1 | 8245=1，8246=0，8247=1 |

这说明当前证据更准确的表述是“握手脉冲相位提前约 1 cycle”，此前把它概括成
aggregate 延后约 3 cycle 过强。后续 `s1/s2/s3` valid、SRAM read/clock-gate、IFU
请求和 backend dispatch 差异都沿这条相位路径传播。可复核的报告包括：

- [`fullbase_0.txt`](../ptmp/xs/logs/fullbase_0.txt)：FTQ、ready、bpuEnqueue 和后续队列
- [`fullbase_1.txt`](../ptmp/xs/logs/fullbase_1.txt)：BPU valid、UBTB/ABTB 和 SRAM 相关信号
- [`fullbase_2.txt`](../ptmp/xs/logs/fullbase_2.txt)：缩小的 UBTB 对照
- [`20261018_b0_diff.txt`](../ptmp/xs/logs/20261018_b0_diff.txt)：B0/ABTB 读请求及门控
- [`20261018_b0_sram_diff.txt`](../ptmp/xs/logs/20261018_b0_sram_diff.txt)：B0 SRAM 传播差异

SRAM 门控在 cycle 8245 即出现差异，但 SRAM 数据和有效信号的差异跟随上游
fire/valid 变化；目前没有证据表明 SRAM wrapper 是独立根因。

### 继续向 IFU/ICache ready 路径收敛

对 `20261018_agg_8200_9000.fst` 和
`xs_ref_20261018_ref_8200_9000.fst` 查询了 ICache main pipe 的控制信号。
aggregate FST 的时间仍按 `cycle=floor((raw_time-107)/2)` 映射，reference FST
直接使用 cycle。现有记录中的相位关系如下：

| 信号 | aggregate | Verilator | 说明 |
| --- | --- | --- | --- |
| `inner_icache.mainPipe.s1_fire` | raw 16592/16594/16596 对应 cycle 8242/8243/8244 为 1/0/1 | cycle 8243/8244/8245 为 1/0/1 | aggregate 早 1 cycle |
| `inner_icache.mainPipe.s1_valid` | cycle 8243/8244/8245 为 0/1/0 | cycle 8244/8245/8246 为 0/1/0 | aggregate 早 1 cycle |
| `inner_icache.mainPipe.s0_canGo` | cycle 8243/8244/8245 为 1/0/1 | cycle 8244/8245/8246 为 1/0/1 | aggregate 早 1 cycle |
| `inner_ifu._io_fromFtq_req_ready_T` / `io_fromFtq.req.ready` | cycle 8243/8244/8245 为 1/0/1 | cycle 8244/8245/8246 为 1/0/1 | 与 ICache `s0_canGo` 同步 |

RTL 中 `ICacheImp` 直接把 `mainPipe.io.req.ready` 接到 IFU 的
`fetchReady`（[`ICacheImp.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheImp.scala:216)）。
`ICacheMainPipe` 的 ready 由
`s0_canGo = toData.ready && fromWayLookup.valid && s1_ready`
计算（[`ICacheMainPipe.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheMainPipe.scala:162)），
并由它驱动 `fromFtq.ready`（同文件
[`ICacheMainPipe.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheMainPipe.scala:166)）。
随后 `s0_fire` 更新 `s1_valid`（同文件
[`ICacheMainPipe.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheMainPipe.scala:176)），
`s1_fire` 生成送回 IFU 的响应（同文件
[`ICacheMainPipe.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/icache/ICacheMainPipe.scala:418)）。
因此这组波形说明偏移已在 ICache main pipe 的握手/流水状态上可见；它不是
`ifuPtr` 更新之后才产生的纯 FTQ 记录差异。

同一窗口中，aggregate 的 FTQ `ifuReqValid` 在 cycle 8257 变 0、8259 变 1，
Verilator 在 8258、8260 才发生对应翻转；`ifuPtr` 也分别在 aggregate cycle
8244、8246、8247、8248 推进，在 Verilator cycle 8245、8247、8248、8249
推进。这与 ICache ready/fire 提前一拍相互吻合，但尚不能说明
`toData.ready`、`fromWayLookup.valid` 或 IFU `s1_ready` 哪一个组合输入先偏移。
aggregate 波形在这段之前有 raw 1442 到 16596 的长空洞，故只能把 ICache
main pipe 标为当前最早可见模块，不能把它定为已证明的根因。

## RTL 与生成 C++ 对照

RTL 的 FTQ 逻辑位于
[`Ftq.scala`](../testcase/xiangshan/src/main/scala/xiangshan/frontend/ftq/Ftq.scala:153)。
核心关系是：

```scala
io.fromBpu.prediction.ready :=
  distanceBetween(bpuPtr(0), commitPtr(0)) < FtqSize.U &&
  distanceBetween(bpuPtr(0), ifuPtr(0)) < BpRunAheadDistance.U &&
  bpTrainStallCnt < BpTrainStallLimit.U

val bpuEnqueue = prediction.fire && !redirect.valid
when (prediction.bits.s3Override) {
  bpuPtr := io.fromBpu.s3FtqPtr + 1.U
}.elsewhen (bpuEnqueue) {
  bpuPtr := bpuPtr + 1.U
}
```

对应的 preserve-aggregate SV 组合逻辑在
[`Ftq.sv`](../ptmp/xs/rtl/rtl/Ftq.sv:226)：`_io_fromBpu_prediction_ready_T`、
`_T_5` 和 `_T_20` 分别计算 flag、距离和最终 stall guard，`bpuEnqueue` 再由
`_T_20 & prediction.valid & ~redirect.valid` 得到。短窗 aggregate 中，
`_T_12` 在 cycle 8244/8245 为 76/77，`_T_5` 为 73/74，`_T_20` 在
8244/8245 为 1/0；这与 `bpuPtr` 在 8245 增加、而 `ifuPtr` 尚未同步增加的边沿
相符，说明组合算术本身没有出现明显的随机值或位宽截断。

生成 C++ 保留了这些算术关系，但把它们拆到不同的阶段函数和边界存储：

- [`tu678.cpp`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu678.cpp:5666) 更新
  `prediction_ready_T`；同文件约 6130 行更新 `_T_5`/`_T_20`。
- [`tu804.cpp`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu804.cpp:7650) 将
  ready、prediction valid 和 redirect 合成为 `bpuEnqueue`。
- [`tu816.cpp`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu816.cpp:1753) 计算
  `bpuPtr` 下一值 payload；[`tu1042.cpp`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu1042.cpp:8693)
  把 payload 写回 `smallSinkStore` 的 `bpuPtr`。
- [`tu143.cpp`](../ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu143.cpp:24111) 的
  `_val_374433` 只是 `!reset` 门控；没有证据说明它错误地把 bpuPtr 永久清零。

因此目前最强的假设是 preserve-aggregate 后的事件边界/阶段调度使 FTQ/BPU
ready/valid 握手相对 Verilator 发生约 1 cycle 的相位偏移；这会让 `bpuPtr`、BPU
流水线和后续 FTQ 消费节奏在边沿处使用不同的状态。生成 C++ 中没有发现一处可以
单独证明为错误的常量、位宽截断或 reset 条件，结论仍是候选根因。

## 其他差异

`intBusyTable` 在映射后报告中出现宽度异常：aggregate 的 `allocMask`/`wbMask`
为 224 bit，Verilator 为 223 bit；`table_0` 已是 224 bit。记录见
[`fullbase_4.txt`](../ptmp/xs/logs/fullbase_4.txt:225)。这可能解释后端稍后的
dispatch/issue 差异，但它晚于前端首个分歧，当前不能作为首因。

## 波形工件注意事项

`20261018_agg_8200_9000.fst` 和对应 reference 文件名表示 8200–9000 窗口，
但 aggregate 的部分内部 BPU 信号在 raw FST 时间 1442 后直到约 16596 才再次出现
变化；用半周期映射后表现为 cycle 721 到 8298 的长空洞。短窗 aggregate 文件和已
保存的 `fullbase_*.txt` 则包含 8245 附近的差异。因此这些 FST 不能当作完整连续波形
来推断空洞期间的状态，也不能单凭缺失记录断言某个 SRAM 或指针保持不变。当前结论
以映射后的差异报告和 8245 附近可见的相位证据为准。

`fst-roi-discovery` 的 Python helper 已做依赖检查，但 workspace `.venv` 中没有
`pylibfst`（`ModuleNotFoundError`）；本轮没有绕过该失败去使用未声明的解析器，
而是使用已构建的 `build/fst_diff/fst_diff` 对固定信号和固定窗口做有界查询。

## 会话退出与内存事故

本轮再次退出的直接原因已经确认是 OOM。2026-10-18 08:23:36 的内核记录显示，
一条宽范围 `rg` 扫描 `ptmp/xs/grhsim-ir/model/grhsim_SimTop_tu*.cpp` 时，
`rg` RSS 达到约 160.7 GiB（anon RSS 约 168,497,412 KiB），同一管线中的 `tail`
约 23 GiB；OOM killer 杀死了 `rg`。这是排查命令造成的，不是 GrhSIM 仿真再次启动。
此前还记录过两次 `jq` OOM（约 117.8 GiB 和 96.3 GiB），均位于独立的
`tmux-spawn-*.scope`。

当前检查时总内存约 187 GiB，已用约 4 GiB，可用约 183 GiB；没有发现其他高 RSS
业务进程。后续只允许固定文件/固定行号读取和单进程 FST 查询，禁止对生成模型做
宽范围正则扫描或并行波形解析。

## 当前结论与下一步

已确认 `AheadBtb.t1_needCorrectTarget` 的目标 OR 链在 ingest 中从 22 位错误地
变成 1 位。修复前仅执行 `read_sv → store_json` 即可复现。在已有修复前波形中，
错误在 cycle 10286 生效，并在 10287 产生多余 bank 写入。先前基于 `-107`
映射的“一周期调度偏移”假设已撤回。

已修复比较及其他布尔操作数的宽度边界，并补全 Mux 的表达式位宽信息。
CASE_026 严格等价检查的 72 组输入全部通过，64 项 CTest 全部通过。
完整设计的 100k CoreMark 复跑已执行，但在 `cycleCnt=13647` 触发 WriteBuffer
断言中止，没有得到 aggregate GrhSIM 的有效 100k 端点。本次 plain Verilator
跑满 100k，`instrCnt=238535`，退出 0；其前 30k trace 与历史 plain 记录完全一致。
原提交时刻分歧仍存在，不能认为整机问题已修复。

## 修复后 aggregate GrhSIM 的 100k 复跑与 plain Verilator 对照

- 独立输出目录：`ptmp/xs/grhsim-ir-widthfix-20261018_135200/`。
- 输入仍为 `ptmp/xs/rtl/rtl/`，生成记录明确包含
  `--preserve-aggregate=all`、`--config TLConfig`、`--issue E.b`、单核和成功退出。
  原始记录副本为该目录的 `logs/rtl-generation-time.log`。
- 使用修复后的 ingest，从 SV 重新生成；显式指定
  `XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0`，不复用旧 flat GRH 或旧模型。
- 入口为 `make xs_wolf_grhsim_ir`，生成在独立 session 中执行，设置
  96 GiB 虚拟内存上限、2 路 binding 构建并发、2 小时阶段超时；不生成波形。
- 修复 diff 和输入 SHA-256 记录在 `logs/ingest-fix.diff`、`logs/input-sha256.txt`。
- 生成日志：`logs/generate.log`；阶段资源统计：`logs/generate.time`。
- 参考采用 `build/xs/ref/emu`：10 月 2 日构建的 plain Verilator。
  对应 XiangShan 源码提交 `4a6e3da8bf` 到当前 `2193b15d3` 的 `src/`、
  `build.sc` 没有差异，后续提交主要更新 difftest 和构建入口。
  按用户明确要求，aggregate Verilator 不再作为参考，不继续排查其断言。

2026-10-18 14:17，完整生成成功，`xs_wolf_grhsim_ir` 退出 0。包含 binding 安装
的入口耗时 25:59.86，最大 RSS 52,173,976 KiB（约 49.76 GiB）；生成 1,207 个
C++ 编译单元，IR 保存、重新加载和 round-trip 逐字节一致均通过。随即通过
`make xs_wolf_grhsim_ir_build_emu` 编译新模型。生成进程释放内存后可用内存约
175 GiB，C++ 编译改为 8 路、每进程 8 GiB 虚拟内存上限；
日志为 `logs/build.log`、`logs/build.time`。

### GrhSIM 整机复跑结果：提前中止

新模型编译成功：`logs/build.time` 记录退出 0，耗时 10:20.85，最大单进程
RSS 2,423,336 KiB（约 2.31 GiB）。随后通过
`make run_xs_wolf_grhsim_ir_emu` 运行：

```text
XS_PRESERVE_AGGREGATE=all
XS_SIM_MAX_CYCLE=100000
XS_COMMIT_TRACE=1
XS_PROGRESS_EVERY_CYCLES=10000
XS_LOG_BEGIN=0 XS_LOG_END=-1
XS_WAVEFORM=0 WOLVRIX_GRHSIM_WAVEFORM=0
```

运行保持默认 `8386560MB` 模拟 RAM（稀疏 `MAP_NORESERVE` 映射），因此运行阶段
没有沿用编译的 8 GiB 地址空间限制，而使用 64 TiB 虚拟地址上限、1 小时超时。
实际运行仅 34.95 秒，最大 RSS 185,192 KiB（约 181 MiB），没有 OOM。
父进程存活；运行因 RTL 断言以失败状态返回（emu 1，外层 make 2）。

```text
Assertion failed at ptmp/xs/rtl/rtl/WriteBuffer_54.sv:121.
[ERROR][time=13650]
SimTop.cpu.l_soc.core_with_l2.core.frontend.inner.bpu.sc.pathTable_1.writeBuffer_1:
WriteBuffer_scpathTable1_1 port0_hitMask should be no more than 1
Core 0: ABORT at pc = 0x8000035e
Core-0 instrCnt = 3672, cycleCnt = 13647
Seed=0 Guest cycle spent: 13651
```

这是 RTL 断言停止，不是已观察到的 NEMU 架构状态 mismatch。`WriteBuffer_54.sv`
第 96–99 行计算四个 `setIdxHitVec` 的计数，并用 `_GEN_0[2:1]` 判定多命中；
第 121 行为这个判定对应的 `xs_assert_v2`。命中值和状态是否已在更早时刻出错，
尚需与参考确认，不能只凭断言文本认定根因。

运行日志：`logs/run.log`；原始提交记录：
`logs/xs_wolf_grhsim_20261018_135200_widthfix_100k.log`；资源统计：`logs/run.time`。
共保存 3,624 条提交 trace 记录。计数与 `instrCnt` 的统计口径不同，不能互相替代。

按 cycle、PC、指令、写回使能及有效写回目标/数据与旧参考 30k trace 流式比较：

```text
first_diff_ordinal_0based=2888
reference: 13089 0000000080000124 00051783 1 15 0000000000005252
widthfix:  13095 0000000080000124 00051783 1 15 0000000000005252
```

前 2,888 条记录一致，但原来的第一处提交时刻分歧未消失。证据为
`logs/first-trace-diff.txt` 及两个 `*-normalized.trace` 文件。提取时处理了断言
打印与一条提交记录粘在同一行的情况；只忽略无写回时的无效 dst/data 字段。

为排除本次 binding 安装遗漏修复，再通过 CASE_026 的 Make 入口强制重新生成
小模型并验证，仍为 `vectors=72 mismatches=0 reference_or_control_errors=0`、
`trace_10286=matched`（`logs/case026-recheck.log`）。因此局部错误修复已生效，
但不能把这项独立测试的通过扩大为整机提交偏移已解决。

### plain Verilator 参考来源与本次 100k 运行

复用 `build/xs/ref/emu`，不重新生成或编译参考。程序对应 10 月 2 日的
`4a6e3da8bf, dirty: 0`。该提交的 Makefile 没有传 `--preserve-aggregate`，
使用 firtool 默认的 none。保留的 `VSimTop.h` 中接口也是 scalar 端口，
如 `difftest_uart_out_valid`、`difftest_logCtrl_begin`。

`build/xs/rtl/time.log` 已在 10 月 17 日被 aggregate RTL 的再生成覆盖，**不能**
用它描述 10 月 2 日参考程序的输入。参考原始 Makefile、Verilator 输入清单、
生成头文件与 binary/CoreMark/NEMU 的 SHA-256 已保存为：

```text
logs/plain-reference-original-Makefile
logs/plain-reference-verFiles.dat
logs/plain-reference-VSimTop.h
logs/plain-reference-build.time
logs/plain-reference-rtl-source.diff  # src/ 与 build.sc 的比较为空
logs/plain-reference-input-sha256.txt
```

根 Makefile 的 `run_xs_ref_emu` 改为直接运行指定的已构建参考，去掉与该 binary
无关的 aggregate RTL 生成检查；新增可执行文件检查与 `pipefail`，保留仿真失败状态。
GrhSIM 的 aggregate RTL 检查仍生效。本次通过该入口运行 plain 100k，
`XS_REF_BUILD=build/xs/ref`，启用 NEMU、完整 commit trace，关闭波形，
`XS_LOG_BEGIN=0 XS_LOG_END=-1`；2 线程模型绑定 CPU 2、3。
运行在独立 session 中，超时 1 小时、地址空间上限 64 TiB，不生成 core dump。
日志为 `logs/plain-reference-run.log`、`logs/plain-reference-run.time` 和
`logs/xs_ref_20261018_150900_plain_reference_100k.log`。

本次 plain 参考已跑满 100k，以达到周期上限正常结束，make 退出 0，没有 RTL
断言或 NEMU mismatch。耗时 2:52.18，最大 RSS 156,868 KiB（约 153 MiB）。

| 本次指标 | plain Verilator | 修复后 aggregate GrhSIM |
| --- | ---: | ---: |
| 设置的最大周期 | 100000 | 100000 |
| Guest cycle spent | 100001 | 13651 |
| cycleCnt | 99996 | 13647 |
| instrCnt | 238535 | 3672 |
| commit trace 记录数 | 231568 | 3624 |
| 停止原因 | 达到周期上限，退出 0 | WriteBuffer 多命中断言，emu 退出 1 |

plain 的结束 PC 为 `0x80000cde`。历史 `240349` 与本次 `238535` 不同，
历史 100k 记录的精确运行配置尚未重新核实，不能继续把 `240349` 当作本次参考端点。
但本次 plain trace 的前 27,512 条（到 cycle 29995）与历史 plain 30k trace
连同提交周期全部一致，见 `logs/plain-vs-historical-trace-compare.txt`。
因此本次运行能够直接复核原有的早期提交偏移。

与修复后的 aggregate trace 按提交序号比较，结果为：

```text
first_diff_ordinal_0based=2888
plain:    13089 0000000080000124 00051783 1 15 0000000000005252
widthfix: 13095 0000000080000124 00051783 1 15 0000000000005252
compared_records=3624
differing_records=736
differing_payloads_excluding_cycle=0
min_cycle_delay=0
max_cycle_delay=78
last_common_plain:    13623 0000000080000392 fe0493e3 0 -- --
last_common_widthfix: 13647 0000000080000392 fe0493e3 0 -- --
```

3,624 条共有记录的 PC、指令、写回使能及有效写回目标/数据全部一致；
736 条记录的提交周期不同，首次晚 6 个周期，最大晚 78 个周期，最后一条晚 24
个周期。plain 到 cycle 13647 已有 3,639 条 trace 记录，aggregate 为 3,624 条。
这些是提交 trace 字段的比较结果，不代表 WriteBuffer 内部状态已证明正确。

完整对照报告为 `logs/plain-vs-widthfix-trace-compare.txt`，规范化 trace 为
`logs/plain-reference-normalized.trace` 和 `logs/widthfix-normalized.trace`。
比较通过 `compare_normalized_trace.awk` 流式完成，不载入完整设计 JSON 或生成 C++。

### 已撤出的 aggregate Verilator 旁路尝试

此前误尝试构建同份 aggregate SV 的 Verilator，使用了 `--language 1800-2005`
兼容 `until` 字段名；该程序在 cycleCnt=10269 触发 AheadBtbReplacer 断言。
用户纠正后，此路径撤出主比较，不再追踪其断言，也不用它解释 GrhSIM 的失败。
相关 `logs/reference-*` 与 `logs/xs_ref_20261018_135200_aggregate_reference_100k.log`
仅保留为旁路尝试的历史证据。为该尝试新增的 Verilator 线程初始化源码改动已撤回。

### WriteBuffer 小探针的边界

临时探针保存在本次目录的 `writebuffer-probe/`，可通过该目录的 Makefile 运行。
它使用原始 `WriteBuffer_54.sv` 和同一生产 GrhSIM pipeline，以 reset、写入和
读回检查状态及数据。为单独观察逻辑，两侧均定义 `SYNTHESIS`，不执行原模块的
断言打印/DPI 回调；所以它没有复现整机的断言停止。

最初观察到首笔写入后 entryVec 数据在 GrhSIM 中为零。进一步给 wrapper 的
**输入 payload** 增加观测后，发现差异在写入之前已经存在：

```text
cycle=0 edge=0 reset=1 valid=0
payload=074062a6bf8906c3
wrapper entryVec input: Verilator=62a6bf8906c3 GrhSIM=000000000000
```

证据为 `logs/writebuffer-probe.log`。wrapper 已使用按字段、按常量下标逐项赋值，
但嵌套 packed struct 数组的连接仍有差异。这是另一处待隔离的连接问题；由于
两个 DUT 的输入 payload 尚不能证明相同，早先的读回差异**不能证明 WriteBuffer
内部状态更新错误**，更不能当作原整机断言的完整复现。没有将它加入正式通过测试集。

当前结论：plain Verilator 已完成本次 100k，局部位宽测试通过，aggregate GrhSIM
整机回归未通过；`3672` 是提前停止时的计数，不能当作 100k 端点。
后续以 plain Verilator 为唯一参考，
继续追踪整机提交时刻偏移及 WriteBuffer 多命中状态的来源；嵌套数组连接探针
尚未复现整机错误，需先保证输入一致后才能判断内部状态更新。

## 新整机波形与可靠 WriteBuffer 回放（15:30 起）

本轮使用独立目录 `ptmp/xs/grhsim-ir-widthfix-wave-20261018_153000/`。
从上一轮有效的映射 IR 通过 `make xs_wolf_grhsim_ir_reemit` 重发带波形模型，
没有重新 ingest。新旧映射 IR 经 `cmp -s` 逐字节一致。重发耗时 3:56.22，
峰值 RSS 19,460,132 KiB；8 路编译耗时 10:17.66，峰值单进程 RSS 2,430,896 KiB。
两侧均从 reset 开始采集完整 14k FST，plain 复用原有 scalar Verilator binary。

plain 正常到达 `cycleCnt=13996, instrCnt=4096, Guest=14001`；GrhSIM 再现
`cycleCnt=13647, instrCnt=3672` 的 WriteBuffer 断言。新波形版与旧无波形版的
3,624 条提交记录含周期完全一致。波形未改变该现象，运行没有 OOM。

两侧周期计数在 raw 106 同为 1，raw 108 同为 2，随后逐拍一致。
本次两份完整 FST 均采用 `floor((raw-105)/2)`；不能沿用旧 plain 窗口文件的
零偏移。计数证据为 `logs/{aggregate,plain}-cycle-raw.changes`。

### 修复后的实际分歧顺序

| cycle | 新波形观察 | aggregate / plain |
| ---: | --- | --- |
| 0–13650 | `abtb.t1_needCorrectTarget`，完整范围比较 | compared=1, divergent=0, silent=0 |
| 12727（raw 25560） | 有效 slot 1 的 setIdx | `0 / 0x2d` |
| 12727（raw 25560） | 有效 slot 1 的 wayMask | `0 / 0x10`；两侧 valids 均为 3 |
| 12758 | WriteBuffer `state_reg` | `4 / 5` |
| 12946 | SC `t1_writeThresVec_updated_scWrong` | `1 / 0` |
| 12959 | WriteBuffer `needWrite` | `1 / 0` |
| 13070 | BPU `s3_override` / `s3_predictionSource` | `1 / 0`；`010 / 011` |
| 13089 起 | 原首次提交时刻分歧 | plain 13089，GrhSIM 13095 |
| 13647 | WriteBuffer `valids` 与断言 | `0xf / 0x7`，GrhSIM 停止 |

证据：`logs/widthfix-abtb.diff`、`logs/widthfix-bpu-s3.diff`、
`logs/widthfix-writebuffer-compare.txt`、`logs/widthfix-sc-training.diff`。WriteBuffer 的 packed 字段按每 slot
7/8 位与 plain 的独立 scalar 字段对齐，只对两侧都有效的 slot 比较。
此时间链说明 WriteBuffer 的实际状态损坏早于 BPU/提交偏移；尚需修复后整机
运行证明该错误足以解释原提交时刻偏移。

### 使用 plain 输入的独立回放

新回放位于 `writebuffer-replay/`，通过其 `Makefile` 的 `run` 入口生成模型并运行。
直接使用原 `WriteBuffer_54.sv`，定义 `SYNTHESIS` 关闭打印/DPI 断言。
参考数据来自 **plain 整机 FST**，没有构建 aggregate Verilator。
wrapper 以整体 net initializer 连接 payload，重组完整 63 位输入并逐 tick
核对，避免旧逐字段连接探针的输入损坏。共享 FST handle 的别名从 metadata
恢复；不使用信号名猜测。回放先用前一低相位的输入执行上升沿，再注入波形中
该相位更新后的上游输入，避免将 post-edge 值提前一拍使用。

修复前首次失败为：

```text
raw_tick=25560 read_bits actual=0000000001000000 plain=2d10000001000000
valids=3 needWrite=2 state_reg=4  # 两侧一致
```

完整输入相等，slot 1 的 entryVec 数据保留，但 setIdx/wayMask 被清零。
这是新的输入已核对的 DUT 错误证据；前节旧探针的结果仍不作为内部错误证据。
日志为 `logs/writebuffer-plain-replay{,-state}.log`。

### 第二处 ingest 错误：折回标量后的部分写入定宽

仅 `read_sv → store_json` 即可在原始小模块重现，无需任何 transform。
原始 GRH 保存在 `writebuffer-replay/out/raw-ingest-before.json`（约 1 MiB），
报告为 `logs/raw-ingest.log`：

```text
setIdx slot0: concat(old_upper21, value28) -> 49 bits
wayMask slot0: concat(old_upper24, value32) -> 56 bits
```

`entries` 是 `[0:0][3:0]` 的 packed struct 数组。声明收集因前导 extent=1
清空 leaf shape，把四个 setIdx 合并成 28 位 scalar。`handleStructAssignment`
错误地按该 scalar 的 `info.width=28` 给单个 7 位写值补零。write-back 正确保留
旧 upper21，再拼入错误的 value28；最终截回 28 位时就丢掉了其他 slot。
wayMask 的 `8 → 32 → concat56 → 截32` 同理。

修复改为按 **当前已选中 LHS 的 SV 类型** 拆出叶子宽度，不再由存储 shape
倒推 addressed width。7 位字段的正确更新为
`concat(old[27:7], rhs[6:0]) → 28`。
新增 ingest fixture 覆盖静态索引、动态索引和嵌套 struct 成员赋值。
修复前单测明确失败于 49 位 concat，修复后通过；原表达式定宽回归也通过。

### 回放推进后暴露的嵌套读取问题（继续验证中）

上述写入修复使回放越过 raw 25560，但在 raw 25614 出现新的 entryVec 分歧：

```text
read_bits actual=0d02000000000000 plain=0d02000000000040
```

`applyReadSlices` 消费 packed 维后更新了维度列表，却未更新已折回 scalar
的 `width`。例如 192 位叶子依次消耗 `[1,4,8]` 时，应使用
`192 → 192 → 48 → 6`；旧实现最后仍从 192 除以 8，误用 24 位步长。
连接侧对应代码已经会缩小 width；本轮正在将相同规则用于语句读取侧。

新增 `CASE_027` 使用共享 ingest fixture 和独立 scalar C++ 数组作期望值，
不构建 Verilator。直接整 struct 读写的 512 周期/6,144 项检查已通过；新增
逐字段重组读取后，旧读路径在 cycle 1 即失败，证据为
`logs/case027-nested-read-before.log`。修复后的完整回放、扩展 CASE_027 和整机
100k 尚待执行，不提前宣称整机一致。

### 两处修复后的独立验证与新整机生成（16:04）

`applyReadSlices` 现在与连接侧保持一致：移除一维后，如果剩余 shape 为空，
同步将 scalar `width` 缩小为本次选择的 subWidth。

重新 `make py_install` 后，强制重新生成两个小模型，结果为：

```text
[PASS] plain_wave_replay rows=28102 write_edges=82
[PASS] cycles=512 lane_field_checks=10240 static/dynamic/nested writes
```

完整 plain 回放的输入 payload、valids、needWrite、state_reg、read_valid 和
有效 read_bits 均一致，原 raw 25560、25614 两处失败全部消失。
日志为 `logs/writebuffer-plain-replay-final.log` 和 `logs/case027-final.log`。
ingest-only 原模块 GRH 中的 49/56 位错误 concat 也已消失。

新整机输出目录为 `ptmp/xs/grhsim-ir-structfix-20261018_160400/`，入口仍为
`make xs_wolf_grhsim_ir`，显式 `XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0`，
重新读取原 preserve-aggregate=all SV，不复用旧 flat GRH。binding 已安装，
因此通过 `XS_WOLF_DEPS=` 跳过重复安装。开启模型波形能力以便后续必要时继续
定位，100k 运行将关闭波形。生成阶段地址空间上限 96 GiB、2 小时超时，
独立 session；日志位于新目录的 `logs/generate.log`、`logs/generate.time`。

最终 `make test_wolvrix`（包含两处新修复及扩展 fixture）64/64 通过，退出 0，
CTest 耗时 70.97 秒；日志为上一波形目录的 `logs/struct-suite-final.log`。
本轮没有改变用户的 `AGENTS.md` 和 `testcase/xiangshan/difftest/grhsim.mk`。

16:29，新整机生成退出 0：耗时 25:11.49，最大 RSS 56,590,744 KiB
（约 53.97 GiB）。映射 IR 的保存、在新 session 中加载，以及 round-trip
逐字节一致检查均通过。1,207 个普通 TU 与 18 个波形 TU 已完整输出。
代码输出完成后立即通过 `make xs_wolf_grhsim_ir_build_emu` 开始 8 路编译，
每个编译子进程虚拟地址上限 8 GiB，40 分钟超时，独立 session，日志为
`logs/build.log`、`logs/build.time`。未重新构建 plain Verilator。

## 最终 100k 周期验证：与 plain Verilator 完全一致（16:44）

新模型编译退出 0，耗时 10:17.67，最大单进程 RSS 2,431,260 KiB
（约 2.32 GiB）。通过原项目 Makefile 入口运行：

```sh
make run_xs_wolf_grhsim_ir_emu \
  XS_GRHSIM_IR_BUILD=ptmp/xs/grhsim-ir-structfix-20261018_160400 \
  XS_LOG_DIR=ptmp/xs/grhsim-ir-structfix-20261018_160400/logs \
  XS_SIM_MAX_CYCLE=100000 XS_COMMIT_TRACE=1 \
  XS_PROGRESS_EVERY_CYCLES=10000 XS_LOG_BEGIN=0 XS_LOG_END=-1 \
  XS_WAVEFORM=0 WOLVRIX_GRHSIM_WAVEFORM=1 XS_EMU_CPU=2 \
  RUN_ID=20261018_160400_structfix_100k
```

模型保留波形能力，本次运行关闭波形。运行在独立 session 中，30 分钟超时，
虚拟地址上限 64 TiB 以容纳原有稀疏模拟 RAM；禁止 core dump。最终 make
退出 0，运行耗时 5:53.58，峰值 RSS 192,740 KiB（约 188 MiB），没有 OOM，
没有 RTL 断言或 NEMU mismatch，按配置达到周期上限正常结束。

唯一参考仍为前述 plain Verilator 的本次 100k 运行；没有构建 aggregate
Verilator，也没有更改参考程序。模型输入、ingest 修复、RTL 生成记录和 binary/
CoreMark/NEMU 的 SHA-256 位于新目录的 `logs/{ingest-fix.diff,input-sha256.txt,
rtl-generation-time.log}`。

| 本次指标 | plain Verilator | 修复后 aggregate GrhSIM |
| --- | ---: | ---: |
| 最大 Guest 周期设置 | 100000 | 100000 |
| Guest cycle spent | 100001 | 100001 |
| cycleCnt | 99996 | 99996 |
| instrCnt | 238535 | 238535 |
| 结束 PC | `0x80000cde` | `0x80000cde` |
| commit trace 记录数 | 231568 | 231568 |
| 仿真入口退出状态 | 0 | 0 |

比较通过新目录 `Makefile` 的 `compare` target 流式完成：逐条比较 cycle、PC、
指令、写回使能及有效 dst/data，仅在 wen=0 时忽略无效 dst/data。没有加载
整机 JSON 或扫描巨型生成 C++。完整结果：

```text
plain_records=231568
grhsim_records=231568
compared_records=231568
differing_records=0
differing_payloads_excluding_cycle=0
min_cycle_delay=0
max_cycle_delay=0
```

原首次分歧记录（序号 2888）现为两侧同一内容：

```text
cycle=13089 pc=0x80000124 inst=00051783 wen=1 dst=15 data=0x5252
```

因此，**本次 100k 窗口内的提交数和提交时刻差异已解决**。可靠回放确认了
WriteBuffer 的字段写入/嵌套读取错误；修复后整机完整 trace 一致，将该局部
错误与原整机偏移联系起来。前面仅修复 AheadBtb 定宽仍然偏移的结果，也说明
不能把原问题归于单一的 AheadBtb 错误。此次联合修复没有分别单独禁用每项
修改重跑整机，故不进一步分摊三项修改各自对 100k 差额的贡献。

最终工件（相对 `ptmp/xs/grhsim-ir-structfix-20261018_160400/`）：

- [`logs/plain-vs-structfix-trace-compare.txt`](../ptmp/xs/grhsim-ir-structfix-20261018_160400/logs/plain-vs-structfix-trace-compare.txt)：完整提交对照，退出 0。
- [`logs/run.log`](../ptmp/xs/grhsim-ir-structfix-20261018_160400/logs/run.log)：完整运行日志；原始提交日志为 `logs/xs_wolf_grhsim_20261018_160400_structfix_100k.log`。
- `logs/{generate,build,run}.time`：各阶段资源统计。
- [`Makefile`](../ptmp/xs/grhsim-ir-structfix-20261018_160400/Makefile)：`compare` 可重新核对既有 100k 日志。
- 永久回归入口：`make test_ingest_struct_array_write`、
  `make -C testcase/xs-bugcase/CASE_027 run`；CASE_027 的 10,240 项检查与全部
  64 项 CTest 均已通过。
