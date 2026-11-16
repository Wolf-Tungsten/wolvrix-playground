# TNO0028：当前 GrhSIM 的 C++／ELF 结构差距

本轮把当前保留实验版、最新联合通知实验版和同归一化 RTL Verilator 的 C++、ELF、IR及既有执行计数重新对应。结论是：剩余问题主要在**区域之间的值保存／变化通知契约，以及区域内部的控制、宽值和生命周期组织**。继续减少几次通知 OR，不能消除这些结构要求的读、写、比较和临时存储。

本轮仅离线分析；没有重新运行模拟器、采集 profile、生成优化候选或修改生产默认值。既有计数用于解释冻结模型，不作为生成器输入，不按运行热度选择站点、常量化分支或调节阈值。暂不讨论 SV 转 V 的影响。

## 对照身份与结论范围

| 后端 | ELF SHA-256 | 上次同轮外部 walltime／Verilator |
| --- | --- | ---: |
| 当前保留实验版，精确键缓存 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` | 1.042380，95% CI [1.038991, 1.045816] |
| 最新联合通知实验版 | `0f5e03c9f84fb95318153b626dde0d8fef6b464744862298e213391db02f4dab` | 1.051397，95% CI [1.049943, 1.052613] |
| 同归一化 RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` | 1 |

这些是 [TNO0027](./TNO0027_joint_notification_factoring_20261115.md) 的既有测量，不能称为本轮新跑分，也不能把“保留实验版”称为所有新规则均已进入全局默认。三侧 CoreMark 均为 3,376,065 周期，trace SHA-256 为 `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。编译选项为 Clang 23.1.2、`-std=c++20 -O3 -march=native -DNDEBUG -gline-tables-only`；既有测量位于 node030 CPU96、NUMA1、ASLR 关闭。

分析首先核对 ELF SHA、既有计数的原模型 SHA、功能 trace、IR 与 source mapping，再使用 ELF 内嵌 DWARF MD5 核对实际被归因的 C++：两份 GrhSIM 各 7 个文件、Verilator 2 个文件全部匹配。没有把当前目录中同名但不同版本的源文件套到旧 ELF 上。[身份、统计及计数来源](../../build/cv32e40p/current-structure-v1/report.json)、[ELF 内嵌源码校验及路径证据](../../build/cv32e40p/current-structure-v1/path-evidence.json)。

## 1. 区域扩大了，但边界仍要求中间值具有持久身份

当前图有 35 个 compute group、4 个 commit group；compute 分为 4 个 batch，commit 为 1 个 batch。保留版与联合版的区域成员、scalar slots 和 checked values 相同。

| 保留版的变化检查 | 值数量 | 每模拟周期检查次数 | 每模拟周期结果变化次数 |
| --- | ---: | ---: | ---: |
| 全部 | 209 | 167.255326 | 30.917438 |
| 仅跨 compute 边界，无直接 commit／输出／event 用途 | 199 | 159.228601 | 25.026527 |
| 其中另按位宽统计：所有 1-bit checked values | 175 | 138.153393 | 15.127760 |

最后一行与第二行有交集，不是额外相加的类别。约 **95.2% 的变化检查服务于计算区域之间的边界**。联合通知版仅把全部检查降为 166.423519 次／周期，边界性质未改变。

具体例子是 `instr_rdata_id_o[14]`。在 [compute batch 1](../../build/cv32e40p/mux-input-cache-v1/grhsim_mux_input_cache/grhsim_Cv32Bench_sched_1.cpp) 第 414–428 行，GrhSIM 不仅从状态提取一位，还读取上次保存的该位，比较新旧值、合入区域通知，再写回中间槽位。ELF 中这些操作仍在：

```text
0x6773  bextrl ...                 # 提取指令位
0x677b  movzbl 0xbf(%rdi), %edx    # 读取中间值的旧副本
0x6782  movb %cl, 0xbf(%rdi)       # 保存新副本
0x679b  xorl %ecx, %edx            # 新旧差异
0x67b0  orl %edx, %r9d            # 与下一项差异合并
```

它每周期检查约 0.999956 次，变化约 0.293328 次。这里的 XOR 是变化检测，不是 CPU RTL 算法需要的 XOR。这样的接口迫使编译器保留上一次调用的值，无法像普通局部表达式一样直接合入消费者。

Verilator 对同一状态位可在消费者表达式中直接做 `core___11272_ >> 14`；例如 [NBA 主函数](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp) 第 2489 行。它由事件触发整块有序逻辑，不要求这个中间位单独携带“旧值与通知”协议。Verilator 也保存跨函数临时值和 next-state；差异不是“它完全没有存储”，而是没有对每个这种区域接口值附加同样的变化检测。

另一个独立接口是 compute→commit：有 285 个已物化 IR 值仅被 commit 直接消费，排除 12 个常量后为 **273 个**，其中 **235 个来自 group 28**。这里计数的是 IR 值，可能共享槽位，不能称为 273 个独立物理槽或每周期 273 次机器写入。当前 scalar slot 数为 bool 346、u8 55、u16 5、u32 91、u64 2。

例如 [commit batch](../../build/cv32e40p/mux-input-cache-v1/grhsim_mux_input_cache/grhsim_Cv32Bench_sched_4.cpp) 第 1133–1143 行对 `core$_11244_` 的提交，在 ELF 中仍是读取已物化的 enable／next-value、与旧状态比较、条件写状态、标记读者。对应地址为 `0x131ec–0x13201` 与跳转目标 `0x1440d/0x14413`。Verilator 的同状态更新在 NBA 主函数第 1925–1929 行保留写使能和赋值，没有该处逐状态判变／读者通知。它的 next-state 也可能跨函数保存，所以不能把这一例的全部中间存储都认定为 GrhSIM 独有成本。[两个 C++／机器码例子的逐指令记录](../../build/cv32e40p/current-structure-v1/path-evidence.json)。

为何不能简单重复“合并同一 commit 终点”的旧优化：剩余 143 个 checked values 的终点集合同时包含 `commit37`、`commit38`、`obs_iaddr_o`、`obs_ireq_o`，贡献 125.854786 次检查／周期。大头已经是**共享、多终点、含对外观察值的接口**。应研究静态事件关系、状态快照和真正需要保留的接口字段；不能因 CoreMark 中两区域经常一起执行，就删除通知或跨提交重排。

## 2. 大区域内部仍有宽值准备和控制依赖不组合的问题

group 28 有 4,810 个 scheduled IR op，几乎每周期执行一次，已经没有 scalar changed 检查。DWARF 对应到它的机器码仍有 7,264 条静态指令、1,501 条带栈内存操作数的指令。因此，继续优化通知并不能覆盖这块计算本身。

下面的函数表用于描述代码布局，函数职责并非逐项等价。栈帧指 `subq ..., %rsp` 分配量，不包含保存寄存器、调用栈或 red zone；静态指令和栈访问不是动态时间占比。

| 函数 | 字节 | 静态指令 | 栈帧分配 |
| --- | ---: | ---: | ---: |
| GrhSIM 保留版 compute batch 2 | 39,563 | 8,221 | 2,456 B |
| GrhSIM 联合版 compute batch 2 | 39,586 | 8,230 | 2,456 B |
| Verilator NBA sequent TOP 0 | 42,425 | 8,525 | 1,432 B |
| Verilator NBA comb TOP 0 | 16,926 | 3,857 | 240 B |

Verilator 也有大函数和栈存储；不能仅凭 GrhSIM 函数大就诊断为 I-cache 瓶颈，也不能把栈访问全部叫作 spill。需要看具体临时对象为何存在、何时构造、消费者在哪里。

一个已确认的例子是两份 **2048-bit CSR counter view**：

- `core$_13859_` 与 `core$_13860_` 都由同一组 32-bit 寄存器 `core$_11244_` 至 `core$_11249_` 和同样的常量填充构成。归一化后的表达式为 `{1792'b0, q11249, q11248, q11247, q11246, 64'b0, q11245, q11244}`。它们处于同一纯 compute 快照，寄存器符号、位宽、符号性和常量完全相同，仅 read／constant SSA ID 不同。
- GrhSIM 仍在 [compute batch 2](../../build/cv32e40p/mux-input-cache-v1/grhsim_mux_input_cache/grhsim_Cv32Bench_sched_2.cpp) 第 2119、2200 行分别建立两个 `std::array<uint64_t, 32>`。从它们抽取的 32-bit 结果只在第 2315 行、root 4333 的 true 分支使用。
- ELF 保留了两个不同的栈缓冲，数据基址分别在 `rsp+0x418`、`rsp+0x890`；每个缓冲的 4 条向量清零 store 都在 `0xbcab` 的 guard 分支之前。直接 CFG 验证这 8 条 store **支配 guard**：只要到达该 guard，准备工作就已经执行。`0xbc75` 还有 guard 前的动态索引读取。
- 现有完整计数中，这个 true 分支执行 0 次、false 分支执行 3,376,066 次。这说明本负载确实支付了分支外的准备成本；不意味着该分支对所有输入恒假。

根因有两层。首先，等价状态视图经不同 SSA read 出现后，没有在这里被统一成一个 view。其次，当前 [conditional mux planner](../../wolvrix/lib/emit/grhsim_cpp.cpp) 的 `privateProducer` 要求结果和全部操作数都是 scalar，且不能是 word lowering；因此含 2048-bit 输入的窄提取和它的宽准备被挡在条件锥外。Clang 成功下沉了部分 scalar 逻辑，但这两个数组的构造没有跟着消费者进入分支。

Verilator 在对应主函数仅有一个 `VlWide<64>` counter view，并复用它；这证明状态视图合并并非必须丢失。不过也要保留反例：它的单 view 在 ELF 中同样有 **8 条**归因到清零的向量 store，分别来自初始化和随后填充。所以“GrhSIM 两个数组、Verilator 一个数组”不能直接换算成“多 4 次 store”或确定的时间收益。这里已证实的是重复存储对象、等价视图未合并、需求不成立时仍做准备；净机器成本需未来单独验证。[视图等价、两侧 store 及 CFG 证据](../../build/cv32e40p/current-structure-v1/path-evidence.json)。

这也解释了此前单独优化 wide slice 为何容易收效很小：只缩短局部运算，并不自动取消它上游的对象构造，也不保证它跟随真正的需求条件执行。更完整的方向是**状态视图规范化＋按消费者需求发射宽操作＋缩短临时对象生命周期**，而不是只替换一个 wide helper。

## 3. 局部译码缓存仍有组合缺口，但不能把源码谓词数当作热指令数

当前 C++ 两个最大的 CSR 译码家族，各有 170 条独立的局部 `const bool ... == constant` 声明。此口径不包括嵌入表达式中的 Eq，不能与旧报告的 171 个持久谓词直接相减，也不能把它们与上一节的 changed-value 比较混算。

| 当前局部家族 | group | 声明数 | 源值检查／周期 | 源值变化／周期 | DWARF 归因到这些声明行的静态机器指令 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `_val_6162`，12 bit | 28 | 170 | 0.718136 | 0 | 174 |
| `_val_134`，12 bit | 31 | 170 | 0.999956 | 0.786282 | 51 |

区域局部化后，这些 Eq 结果没有独立持久 bool slot，现有 `buildSharedEqualityDecodes::entry` 要求结果具有唯一、canonical、已物化的 bool slot，因而不能覆盖它们。TNO0022 恢复的是 18 个仍满足存储契约的 opcode 谓词；不能将那次修复理解为所有局部译码已恢复增量维护。Verilator 两张 4096 项 one-hot 表通过清旧索引、置新索引复用译码结果，其消费者直接读表项；它也支付表访问成本。

ELF 纠正了仅看 C++ 的判断：这不是每周期额外执行 340 次比较。编译器对它们做了合并、向量化、内联和控制下沉。root 4333 的 true 边独占 259 条机器指令；第一组声明行对应的 174 条指令中，63 条只有经过该边才可达，而既有计数显示本负载该边未执行。其余指令也不能不经路径分析就全部算为热路径。

因此，**缓存与局部化之间的存储契约不组合**仍是设计缺口，但“重新缓存所有 CSR 谓词一定快”并不成立。之前局部 one-hot 的负结果不能靠源码比较数量推翻。需要把谓词表示、消费者逻辑、有效性维护及编译器生成的热路径一起设计；不得根据本次观察的零变化将地址或分支固定。

## 排除的解释与后续方向

既有精确计数中，GrhSIM 每周期约为低电平 1 轮、高电平 2 轮，但 group 28 和 group 31 的主体只在高电平第二轮执行约一次。低电平／高电平第一轮主要处理时钟与提交。Verilator 也有对应的多轮事件求稳，主要 NBA 主体约一次。不能把“3 轮”解释成重型计算做了 3 遍。

本轮选取的 ELF 函数集合中，保留版 GrhSIM 为 12,861 条静态指令，Verilator 为 13,625 条；它们不是完整程序或完全等价的函数集合，但已经说明不能用“生成文件／静态指令更多”替代执行路径分析。上次 PMU 的退休指令分别约 10,276.3 与 9,799.1 条／模拟周期，才是执行总量差异；同次主机周期约 3,034.7 与 2,936.1。PMU 为各一次独立计数，不能从这几个总数分摊时间原因。

按证据，后续应关注两条结构主线：

1. **区域接口与事件快照**：在静态语义证明下减少只供跨区域运输的值副本、逐值判变和 compute→commit 暂存；保留真实跨事件、状态更新及公共输出边界。当前多终点接口是重点，单纯继续聚合 OR 或按共同终点扩大区域已不够。
2. **区域内部按需求组织数据**：让纯宽值、窄读取和条件锥能够组合；按同一状态快照识别等价 view，避免先完整物化再消费少数字段。调度与存储决策需要共同考虑对象生命周期，不能把“减少 group 数”当成独立目标。

这两条机制均不依赖 CV32E40P 名称，对 XiangShan 的共享控制逻辑、CSR view 和跨区域接口也可能适用。这里只提出可迁移的语义条件，没有 XiangShan 性能外推或新候选选择。

当前两份 GrhSIM ELF 没有对应的最新事件采样 profile，只有总量 PMU、精确源码计数及本轮离线机器码证据。**可以指出确实存在的额外协议和未消除的准备工作，尚不能声称剩余 4.24% 中分别有多少时间来自它们。** 某个观察点是否值得实现，须先形成通用、可证明的静态规则；本报告不自动导出候选、阈值或默认值。

## 产物与验证

- [离线主分析脚本](../../scripts/cv32e40p_current_structure.py)、[CFG／视图／ELF 内嵌源码校验](../../scripts/cv32e40p_current_structure_paths.py)、[回归测试](../../scripts/test_cv32e40p_current_structure.py)。
- [总报告](../../build/cv32e40p/current-structure-v1/report.json)、[路径与具体接口证据](../../build/cv32e40p/current-structure-v1/path-evidence.json)、[分函数反汇编](../../build/cv32e40p/current-structure-v1/assembly/)。压缩逐指令记录保存地址、函数、助记符、操作数、inline leaf 与最近生成 C++ 行。
- [测试日志](../../build/cv32e40p/current-structure-tests.log)、[验证汇总](../../build/cv32e40p/current-structure-v1/validation.json)。14 项相关 Python 测试通过；覆盖 inline header 归因、栈内存识别、CFG 汇合后的非依赖、间接跳转拒绝证明、状态视图等价及内嵌源码 checksum 冲突。`py_compile`、输入 SHA／统计闭合检查、两仓 diff 检查及新增文档链接检查通过。

从仓库根用新的产物目录复现，命令只调用离线工具，不执行 ELF：

```bash
python3 scripts/cv32e40p_current_structure.py \
  --output build/cv32e40p/current-structure-reproduce
python3 scripts/cv32e40p_current_structure_paths.py \
  --source build/cv32e40p/current-structure-reproduce
PYTHONPATH=scripts python3 -m unittest \
  test_cv32e40p_current_structure test_cv32e40p_binary_shape test_cv32e40p_structure
python3 -m py_compile scripts/cv32e40p_current_structure.py \
  scripts/cv32e40p_current_structure_paths.py scripts/test_cv32e40p_current_structure.py
```

DWARF 行映射会反映移动或合并后的代码，不能视为一条 C++ 对应一条机器指令；源码变量的词法跨度不是编译器活跃区间；静态栈访问也不是动态 spill 计数。报告中的控制边结论额外使用直接 CFG 检查，遇到间接跳转会拒绝证明。
