# 当前 aggregate ROB 存取路径微观分析

2026-10-15；初始分析读取当前 `build/xs/rtl-aggr/rtl/Rob.sv`、`build/xs/grhsim-ir-aggr/xiangshan_flat_grh.json` 和同目录 `model/` 生成代码。末尾追加了 GRH pass 的实现与独立 ROB 探针结果；探针重新读取生成 SV 并输出 GRH，没有重建全系统 GrhSIM C++ 模型，也没有新的运行时间 A/B 数据。历史独立 ROB 模型的性能数字不能直接套用本次全系统产物。

## 结论

preserve aggregate 已使部分读写成为真实的下标访问，但没有实现 ROB 全路径的稀疏数组访问：

- 动态读成功：最终 C++ 直接读取一个数组元素，不必拼装整个 ROB。
- robEntries 写未恢复：52 个叶字段各保留 352 个常量地址写口和一个整数组复位口，共 18,304 个元素更新口。
- 简单的原始动态写也可能继续展开：debug_exuData 有 1,376 个常量地址写口。
- 成功对照：ROB 子模块 RenameBuffer 的 10 列各有 8 个动态地址写口，共 80 个，说明整条动态写后端可用。
- 访问指令之外仍有放大：一个 RenameBuffer 写入组执行 3 次元素 store，却设置 413 个不同读者超点的激活位；激活未按本次写入行筛选。

因此应分别检查地址访问、next-value 计算、跨超点物化和读者激活，不能以生成声明是 std::array 或最后一条 store 带下标作为完成标准。

## 可复查统计

分析脚本：`ptmp/analyze_rob_access.py`；机器可读结果：`ptmp/rob-access-census.json`。它只读取现有文件。GRH 统计按寄存器的 regSymbol 归组，以地址操作数是否由 kConstant 定义区分常量/动态；这些是静态操作/语句数量，不是每周期执行次数。

| 状态 | 常量地址读口 | 动态地址读口 | 常量地址写口 | 动态地址写口 | 整数组写口 |
| --- | ---: | ---: | ---: | ---: | ---: |
| robEntries.uopNum | 704 | 1 | 352 | 0 | 1 |
| robEntries.debug_pc | 352 | 10 | 352 | 0 | 1 |
| robEntries.perfDebugInfo.dispatchTime | 352 | 8 | 352 | 0 | 1 |
| debug_exuData | 352 | 8 | 1376 | 0 | 0 |
| robEntries 全部 52 列 | 19008 | 161 | 18304 | 0 | 52 |
| rab.renameBuffer 全部 10 列 | 3520 | 4160 | 0 | 80 | 0 |

“动态读口”不表示独立外部硬件端口数，也不意味着读总量已最小化；只表示当前图上地址不是直接常量。整数组复位循环中的 cpu_row 不计为稀疏动态写口。

## 案例一：动态读已落到直接访问

`grhsim_SimTop_tu373.cpp:6272–6274`，debug_pc 动态读取的等价简化：

```cpp
index = raw_index < 352 ? raw_index : 0;
value = largeSinkStore.robEntries_debug_pc[index] & mask50;
```

对应 SV 的 `{160{robEntries[0]}}` 与 352 项数组拼成 512 项视图，补齐区读取返回第 0 项；当前生成代码用范围判断表达该语义，没有在这个读点复制/拼装 512 项。`tu529.cpp:2087` 的 debug_exuData 读取也直接使用数组下标。

不过 ROB 的所有读都不是这种形式：`Rob.scala:208–235` 显式构造 8 个 bank，并用 Mux1H 选择当前行和下一行。每 bank 实际 44 项（源代码的“20 Entries”注释已过时）。这是 Chisel 本来就有的 AND/OR 选择网络。`tu80.cpp:707` 可见常量第 74 项 debug_pc 被读取、写边界槽、比较变化、通知下游，整列保留 352 个常量读口。

将这种 one-hot 网络恢复为一个索引读，需要证明 selector 的 one-hot/zero-hot 条件，并保留全零和多热时的 OR 语义；不能直接替换成任意 priority 编码。它是独立于普通 mux-tree 索引恢复的优化问题。

## 案例二：robEntries 写仍按 entry 全展开

Chisel `testcase/xiangshan/src/main/scala/xiangshan/backend/rob/Rob.scala`：

- 169：声明 Vec(352, RobEntryBundle)。
- 199–205：本身就对每个 entry 构造 enqOH 和 Mux1H 入队逻辑。
- 464 等：部分 perf/debug 字段则以动态 enqIndex 更新。
- 566 等：writeback 使用动态 wbIdx 更新调试状态。

因此展开既有 Chisel 显式逐项逻辑，也有后续动态字段写的译码展开；不能全部归咎于 firtool。

SV `Rob.sv:723247`：`robEntries[351] <= _GEN_77303`，随后 350、349……。struct 拆列后，每个叶字段继承同一份逐项 next-value 更新。

以 uopNum 为例：

1. flat GRH 9798807：复位是 kRegisterWritePort 整数组写。
2. 9798879 起：352 个 kRegisterWriteArrayPort，地址都是常量。
3. `tu316.cpp:4349–4364`：对 entry 351 计算入队地址比较、端口选择和 uopNum next-value，然后物化到 `largeSinkPayloadBoundaryStore...uopNum__w1__data`。
4. `tu1210.cpp:2644` 等：sink 阶段执行 `uopNum[175] = payload_w177`；其余 entry 各一份。

最后一条 store 虽然是数组访问，上游仍是按 352 项生成的计算、物化和调度结构。正常更新口的公共 enable 来自非复位分支，不等于“只有这个 entry 命中写地址才计算/写入”。具体执行覆盖取决于超点激活和 enable 位图，不能把 18,304 个静态写口直接当成每周期实际 store 次数。

uopNum 不能机械折成单点覆盖写：`Rob.sv:82535–82539` 有旧值减 writeback 数量，328170 附近尾部为 `valid ? old-minus-wb : old`。同一个 entry 可以受到多个写回源影响，恢复稀疏路径时必须保留汇总计算及入队、写回、flush 的优先级。

## 案例三：debug_exuData 的简单动态写仍失败

Chisel `Rob.scala:566–568` 是 `when(wb.valid) { debug_exuData(wbIdx) := wb.bits.data }`，理想的软件访问路径按写回端口数量增长。

但 SV `Rob.sv:773536–773584` 对 entry 351 分成前三个 if/else-if 直接赋值，以及剩余端口的 mux 链；每个 entry 重复。flat GRH 对同一常量地址产生多个写口，最终共 1,376 个，而不是一组按 writeback 端口索引的动态写。

`tu1178.cpp:87196` 等仍执行 `debug_exuData[351] = payload_w0`，并使用 enable 位图区分写口。这是比 uopNum 更适合作为动态写恢复试点的案例：数据本身不需要减计数，但需保留多个 writeback 同址时的 Chisel 连接优先级。

## 当前恢复 pass 的限制

`wolvrix/lib/transform/mux_tree_fold.cpp`：

- 825 起按寄存器收集全部写操作。
- 1017 左右只接受 kRegisterWriteArrayPort；一个整数组复位口就使整组放弃。当前 robEntries 52 列都含这种混合写口。
- 1080 起解析每个 entry 的 mux 链，条件只接受 `ptr == entry` 或其与一个 enable 的 AND。
- 1156 起要求每个 entry 有唯一链，尾部为同 entry 自读保持或统一常量；不接受 uopNum 的条件计算尾。
- debug_exuData 的同 entry 多写口和较复杂条件也超出这种单链形态。

这解释了为什么只“保留 shape”不够。需将整体复位、稀疏覆盖写、entry 本地计算分层处理，不能以一个寄存器整个写口组是否符合单一模板决定全部成功或失败。

## 案例四：RenameBuffer 地址写成功，激活仍放大

flat GRH 10106610 起，renameBuffer.info.pdest 只有 8 个动态地址写口。同一寄存器没有 352 个常量地址更新口。

`tu1178.cpp:87235–87661` 的一个写入组：

```cpp
if (write_enable) {
    if (address < 352) ldest[address] = data_ldest;
    if (address < 352) pdest[address] = data_pdest;
    if (address < 352) robIdx_value[address] = data_robIdx;
    // 413 条非条件读者激活语句
}
```

413 个不同激活位分布于 30 个 uint64_t 位图字。编译器可能合并同字 OR，因此不能把它们认定为 413 条机器指令；但生成代码确实保守激活了 413 个读者超点，且这里没有基于写入 address 的逐行筛选，也没有旧值相等判断。

`cpu_schedule.cpp:91–172` 已记录常量读者的 staticRow；`cpu_phase_emit.cpp:3550–3576` 的 burst collector 只在写地址为编译期常量时筛除不相交行，动态写时省略运行期行测试。注释明确称其为 conservative over-activation。当前产物符合这一模式。

这意味着即便成功变成 O(写端口数) 的元素写，也可能仍让大量常量读/组合超点重新计算。地址访问和调度必须分别评价。

## 优化优先级

1. 先以 debug_exuData、简单 debug/perf 字段为试点，恢复多静态写口/分支中的动态端口，避免 352 倍译码与 payload 物化；复位独立保留，严格维持同址优先级。
2. 对已成功的 RenameBuffer 检查按行读者激活：动态读者必要时全部通知，常量行读者只通知目标行；将已有 staticRow 元数据用到动态写路径。比较按行查表、合并位图与现有全量通知的成本。
3. 再处理 robEntries 的 enqOH/Mux1H 和 uopNum 等复杂读改写。显式逐项逻辑可能表达真实归约语义，需分别识别互斥覆盖写与多源汇总，不能简单合并为普通 last-write-wins。
4. 验证时同时统计实际写次数、被激活/执行的超点数、边界槽流量、instructions/cycle 和运行时间。当前静态证据说明存在结构性开销及优化机会，尚不能给出加速倍数。

## gsim 的读者与激活对照

以下对照来自当前 `reference/gsim` 源码与已有 `ptmp/xs-components-rob/gsim-model` 独立 ROB 产物，未重新构建成与当前全系统 aggregate 相同的输入/配置。用于解释机制，不作性能 A/B。

### 读者建模

`reference/gsim/src/Node.cpp:7–24` 的 updateConnect 遍历赋值 RHS 表达式树，并遍历 LHS 的下标表达式；引用到的 Node 成为当前消费者的 prev，当前消费者加入源 Node 的 next。因此 `x = arr[idx]` 同时依赖数组 Node 和 idx 的来源。读表达式可以内联到消费者中，不要求每个元素读取都物化为独立、跨超点的 read 节点。

`Node.cpp:212–241` 将 next 消费者映射到所属 super->cppId，写入 set<int> nextActiveId。相同超节点的多个消费者去重；本超节点内按序位于生产者之后的消费者不需另发激活。位于之前的消费者可能需要重新激活本超节点。

保留成一个 Node 的寄存器数组按数组依赖建模；上述通用路径没有读取时的运行期下标订阅，也没有逐行读者表。对可拆分的纯静态数组，splitArray 可以先拆成不同元素 Node，依赖粒度也随之改变。FIRRTL memory 则另有 NODE_READER/NODE_WRITER 等端口 Node；写端口的 updateActivate 会遍历 parent 的全部有效读端口并收集其超节点，同样不是动态按地址精确订阅。

### 激活与执行

- 输入 setter 在值变化时通知后继，见 `cppEmitter.cpp:615` 附近。
- 标量跨超节点结果通过旧值比较，仅变化时通知，见 activateNext（777 起）。
- 数组和 memory writer 走 activateUncondNext（827、949）：在赋值执行路径通知，不做整数组逐值比较。
- 激活目标集合转换成 activeFlags 位图，对相邻目标可用 16/32/64 位 OR 合并。每个目标超节点占一个位，不是每个读表达式占一个位。
- 生成的 subStep 按顺序检查位图；一组标志可先取到 oldFlag 并清零，然后执行激活的超节点。超节点内按普通代码顺序执行，不对内部每个节点重复调度。它并非每次写都动态遍历一个运行期 reader 对象列表。

### ROB 实例证明读者不一定在同一个超节点

debug_exuData 是集中实例：

```text
super 1710：各有效 writeback 动态写 debug_exuData$NEXT[wbIdx]
  → activeFlags[213] bit 5：super 1709
super 1709：循环提交全部 352 项 debug_exuData = debug_exuData$NEXT
  → activeFlags[663] bit 5：super 5309
super 5309：8 个 debug_exuData[deqPtr[i]] 读取及其后续 trap 数据计算
```

证据：`Rob6.cpp:121053、121060、121088–121095`，`Rob11.cpp:83517–83524`。这里 8 个直接读取确实集中在一个超节点；每个写回源也只通知同一个提交超节点，多个通知在位图中自然合并。提交仍复制全部 352 项，因此不能称 gsim 为完全稀疏提交或逐行精确激活。

反例是 robEntries.debug_pc：直接读取分布在 12 个超节点：57、3875、5263/5265/5267/5269/5271/5273/5275/5277、5309、5340。包含 storeDebug 输出、异常 PC、各路 difftest、trap 和 bank one-hot 读。`Rob0.cpp:70951–70959` 在提交后直接计算本超节点内的两个输出，并设置外部读者位；`Rob12.cpp:64989` 起的 bank one-hot 网络则集中在一个较大的超节点。不是所有读者自动合成一个超节点。

RenameBuffer.info.pdest 的直接读取集中在 super 371，不过这里先把 352 项复制进 renameBufferEntries.info.pdest；后续消费者可以分布到其他超节点。直接读者少，也不等于完整传递依赖只有一个超节点。

gsim 此处更紧凑的主要结构是：原生动态写、按消费者超节点去重、较完整的消费者计算链在超节点内部执行。它也存在整数组拷贝、粗粒度数组通知和 one-hot 展开；不应把性能差异解释为 gsim 已实现精确按行读者激活。

## 为什么 gsim 没有 debug_exuData 的 352 个常量旧值读

gsim 读取 FIRRTL，保留了 `when(valid) { array(index) := data }` 的条件赋值。生成代码中的 NEXT 数组是持久状态，未命中的位置不被赋值，自然保留上次内容；提交又令当前数组与 NEXT 一致，不需要每次在组合计算中读取旧元素来构造“保持”分支。整数组提交依然会搬运数据，不能把“没有旧值计算读者”理解为完全没有旧数据流量。

当前 SV 则已经有每 entry 的 mux：`array[e] <= hit ? data : array[e]`。ingest 忠实地产生真实 state read，旧值参与 payload 计算和调度。我们自己的 8 个动态功能读也集中在同一超节点 sn_20689__op_6362463；差异是额外 352 个常量旧值读，分布在 17 个超节点，而不是功能动态读被拆散。

避免它应在调度前的 GRH 优化中分两步做：

1. 在完整写优先级已知的前提下，把最终 next-value 中的纯保持路径提取为写使能，形如 `write(E, e, mux(H,D,read(e)))` 规范化为 `write(E && H,e,D)`。清理只服务于保持的 read/mux 及其依赖。这一步可以消掉旧值读，但仍有 352 项地址译码。
2. 将每 entry 的分支/多个写口按有效优先级规范化，识别 `valid[p] && index[p] == e`，再跨 entry 恢复成每源一个动态地址写口。支持复杂条件中的 OR、else 分支约束及同址优先级；复位保持独立。完成后 debug_exuData 的目标是按实际有效写源数量增长的动态写口，并只留下 8 个功能动态读。

不能无条件对任意独立写口消掉自读保持。例如同一事件内先 `q <= x`，再 `q <= b ? y : q`，第二条在 b=0 时用旧 q 覆盖了第一条；若改成 `if(b) q<=y`，第一条将生效，语义改变。应按完整有序写组分析，或者证明没有较低优先级的重叠写。debug_exuData 外层 if/else 互斥条件也必须保留。

测试应覆盖无命中保持、多写源同址优先级、零数据写入、复位与普通写竞争，以及上述显式自赋值覆盖的反例；同时核对旧值 read 数、写口数和读者超节点数，不能只看最终声明。

## GRH pass 实现与实测

已实现 `register-write-normalize -semantics=2state`，并扩展 `mux-tree-fold -guarded-writes=2state`。XiangShan 的模块级管线在 `xmr-resolve` 后先保留无参 `mux-tree-fold`，再执行规范化和扩展折叠，随后进入原来的 flatten/simplify/GrhSIM 流程。`XS_WOLF_MUX_TREE_FOLD=0` 仍可禁用这一整段。

normalizer 以完整有序写组证明保持路径安全，将更新剪成一个带有效使能的写口；例如 `A ? DA : B ? DB : old` 变为写使能 `A || B` 和 payload `A ? DA : DB`。它不增加写口数。扩展 matcher 仅在覆盖、事件、数据、有效条件和同址优先级都满足、且能减少写口时创建动态写口；失败时保留原组。另补充了 `~(|index)` 等零地址/全一地址比较的识别，以及不同 if/mux 分组下使能的统一排序。具体操作数和限制见 [pass 说明](../../wolvrix/docs/transform/register-write-normalize.md)。

实测输入为本次原始 `build/xs/rtl-aggr/rtl/Rob.sv` 及 12 个生成 SV 模块组成的依赖闭包，先通过 xmr-resolve 和无参 mux-tree-fold 保存基线，再运行新 pass。基线已经包含本次等价比较识别修复的收益；它是独立 Rob graph，不能直接与前文旧整机 flat GRH 的总操作数比较。

| 指标 | 基线 | 规范化/折叠后 |
| --- | ---: | ---: |
| debug_exuData 常量地址保持读 | 352 | 0 |
| debug_exuData 功能动态读 | 8 | 8 |
| debug_exuData 常量地址写 | 1376 | 0 |
| debug_exuData 动态地址写 | 0 | 24 |
| Rob graph 全部数组元素写口 | 30720 | 29360 |
| Rob graph 操作数 | 1833232 | 1816852 |

探针对每个 ROB 数组逐一检查元素写口数没有增加，前后 GRH 均通过 `grh.verify`。uopNum 等读改写路径仍保留：704 个常量读、352 个元素写和一个整数组复位写；没有将汇总算术误改成覆盖写。

可复查产物：`ptmp/rob-register-write/{rob.f,before.json,after.json,census.json}`；日志：`ptmp/register-write-rob-final.log`。复用基线的最终验证命令：

```bash
make probe_rob_register_write PYTHON=.venv/bin/python SKIP_PY_INSTALL=1 \
  ROB_REGISTER_WRITE_ARGS='--baseline ptmp/rob-register-write/before.json'
```

`make test_wolvrix` 的 62 项测试全部通过。新增测试独立比较规范化前、规范化后和折叠后的二态状态转移，覆盖多源同址、零数据、不同 if/mux 分组、共享功能旧值读、越界地址、非均匀整数组写的屏障顺序，以及覆盖不全、事件不一致、行间优先级冲突和显式自赋值覆盖反例。日志为 `ptmp/register-write-full-test.log`。

前面的探针只验证了 GRH 语义与访问路径结构；整机模型、超节点和 CoreMark 结果见下面的独立 A/B。

## XiangShan CoreMark 100k 整机 A/B

2026-10-16 对 preserve-aggregate=all 的同一份 XiangShan RTL 做了完整整机对照。baseline 保留原有无参 `mux-tree-fold`，设置 `XS_WOLF_REGISTER_WRITE_NORMALIZE=0`；enhanced 在其后启用 `register-write-normalize -semantics=2state` 和 `mux-tree-fold -guarded-writes=2state`。两边均为单核、单 emu 线程、关闭波形/commit trace/RAM trace，启用 difftest，并使用相同的 `-DWOLVRIX_GRHSIM_PERF=0` 编译宏。

| 指标 | baseline | enhanced | 变化 |
| --- | ---: | ---: | ---: |
| Host time spent | 400629 ms | 322434 ms | **-19.518%（1.2425x）** |
| instrCnt | 225471 | 225471 | 相同 |
| cycleCnt | 99996 | 99996 | 相同 |
| IPC | 2.254800 | 2.254800 | 相同 |
| `mem_writes` | 149290 | 141847 | -4.986% |
| `mem_readers` | 172535961 | 167960914 | -2.652% |
| general nodes | 1364884 | 1349883 | -1.099% |
| sink nodes | 218156 | 216145 | -0.922% |
| translation units | 1305 | 1288 | -1.303% |

两次运行都在 `-C 100000` 的周期上限退出（PC `0x800010e2`），退出码为 0，日志没有 difftest mismatch。这个 workload 是周期上限截断的 CoreMark 运行，不能据此宣称程序完成了完整两次迭代；但两组的指令数、周期数和停止位置一致，因此 Host time 可以直接比较。模型生成总耗时分别为 1526688 ms 和 1537085 ms，enhanced 的生成阶段约慢 0.68%；C++ emit 分别为 97149 ms 和 96794 ms。emu 编译使用相同宏，enhanced 生成 1288 个 TU，baseline 生成 1305 个 TU。

复查日志：

- enhanced 生成与 pass 计时：[xs_wolf_grhsim_ir_coremark100k-aggregate-enhanced-generate.log](../../ptmp/coremark100k/xs_wolf_grhsim_ir_coremark100k-aggregate-enhanced-generate.log)
- enhanced 运行：[xs_wolf_grhsim_coremark100k-aggregate-enhanced-final.log](../../ptmp/coremark100k/xs_wolf_grhsim_coremark100k-aggregate-enhanced-final.log)
- baseline 生成与 pass 计时：[xs_wolf_grhsim_ir_coremark100k-aggregate-baseline.log](../../ptmp/coremark100k/xs_wolf_grhsim_ir_coremark100k-aggregate-baseline.log)
- baseline 运行：[xs_wolf_grhsim_coremark100k-aggregate-baseline.log](../../ptmp/coremark100k/xs_wolf_grhsim_coremark100k-aggregate-baseline.log)
