# TNO0030：利用已有寄存器激活覆盖消除跨区域视图维护

两阶段均通过功能与计数门，并分别取得稳定收益：仅删除冗余比较／通知使 walltime 降低 **1.3430%**；进一步删除槽位／赋值后，相对原保留版降低 **3.1106%**，95% CI **[−3.2191%, −2.9985%]**。相对同归一化 RTL Verilator 的倍率从本轮基线 **1.04219** 降到 **1.00977**，仍慢约 **0.98%**。

本轮落实此前提出的两阶段规则：先删除已有寄存器通知完整覆盖的中间值比较／通知，再以相同证明删除槽位和生产者赋值，让消费者直接读取寄存器视图。两项开关均默认关闭，既有保留版不变。生成过程只使用静态图、用途、类型和调度信息；诊断计数只验证行为和解释成本，不反馈站点、阈值或候选选择。

## 静态证明与实际命中

源是单写者寄存器在本区域的直接读取，结果限于一个 scalar slice／按位取反／逻辑非／赋值。生产者及所有消费者必须已经位于该寄存器的独立激活集合中，且均为纯 compute 区域；读取、定义和使用顺序有效。外部用户集合必须与原 boundary fanout 完全一致。证明使用删除之前冻结的寄存器激活集合，不借助已删除的其他边。

公开端口、event、waveform、别名、commit 用户、缓存隐含用户及特殊执行模式保守回退。特别保护共享译码源／结果和条件输入缓存源／结果；只检查普通 IR def-use 不足以保护这些隐含用途。直接视图沿用现有 scalar renderer 的位宽、符号和 Boolean 规则，未实现另一套截断语义。[功能说明](../../wolvrix/docs/emit/grhsim-covered-state-views.md)。

整机命中 **21 个值：17 个静态位段、2 个按位取反、2 个逻辑非**，生产区域为 31／32／33。没有改变 Eq 家族、调度图、区域或通知目标。原 IR SHA、39 个区域、共享译码缓存、精确输入缓存及条件锥站点保持一致；关闭新选项时生成源码逐文件等于原保留版。

| 结构 | 保留版 | 仅去比较／通知 | 再去槽位／赋值 |
| --- | ---: | ---: | ---: |
| checked values | 209 | 188 | 188 |
| bool/u8/u16/u32/u64 槽位 | 346/55/5/91/2 | 346/55/5/91/2 | 336/46/4/90/2 |
| scheduler C++ 字节 | 1,024,938 | 1,022,635 | 1,040,219 |

删去的 21 个槽位合计只占 **25 B**。本规则针对的是中间值比较、归约、写回与再次读取的维护成本，不是模型容量。直接表达式会在多个使用位置展开，所以 C++ 文本反而变长；文本大小不能代替 ELF 或运行指令量。

例如 value 37838 是指令寄存器 `core$_11272_` 的 bit 14。原版在区域 31 抽取该位，读取旧 bool 槽位比较，归约进通知标志，再写回；区域 28 随后读取槽位。但寄存器自身的原通知已经覆盖 31 和 28。第一阶段保留位抽取与写回，第二阶段直接在原使用点读取寄存器 bit 14。ALU 操作数符号位 30221／30285 满足相同条件。生产者与消费者的相对顺序由 active ID 证明，不能由区域编号大小推断。

逐值证明见[structure.json](../../build/cv32e40p/covered-state-views-v1/structure.json)，运行前假设见[hypothesis.json](../../build/cv32e40p/covered-state-views-v1/hypothesis.json)。

## 身份与功能证据

| 后端 | binary SHA-256 |
| --- | --- |
| 原保留版 | `600e92ca3a1dd83660d1aaa4341f5de9038b6529a528fbfefe0746c7cd98d98d` |
| 仅去比较／通知 | `a1f6c21c6abaea2076c686c9bc616c3e051f75afc677688389e0b71e856fe0fd` |
| 再去槽位／赋值 | `32771c541f782bf6d1ed443be30479591f9cf2cdebd14e5ae00078ea0d103849` |
| 同归一化 RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

沿用 TNO0023 保留版作为固定基线，没有叠加 TNO0029 的两个独立实验。冻结图、CoreMark、harness、Clang 23.1.2、`-O3 -march=native` 相同，在 node030 编译。第一阶段发射／编译／链接为 2.189／19.439／1.275 秒，第二阶段为 1.791／16.936／1.326 秒；构建时间不计入运行时间，编译时存在其他测试任务，不据此宣称编译提速。[build.json](../../build/cv32e40p/covered-state-views-v1/build.json)。

四后端 smoke 与完整 CoreMark 的 UART、退出码、CRC、完成周期及逐周期总线 trace 一致。CoreMark 均为 **3,376,065 周期**，trace SHA 为 `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[功能门](../../build/cv32e40p/covered-state-views-v1/functional.json)。

两个独立计数版本也通过相同 trace。原保留版计数按 binary SHA 复用；与两个阶段比较，**467 项保留行为计数完全相同**，包括区域和函数执行、fixed-point 轮数、剩余逐值比较／变化、缓存与条件分支。两个阶段的全部计数也相同。

每周期 scalar 比较 **167.255326 → 147.383499**，恰好减少所选 21 个值原有的 **19.871827 次（11.8811%）**；相应 true-change 判定减少 7.037515 次／周期。各 phase 的总比较与变化数均能用删去值的原计数闭合。没有增加消费者执行、缓存访问或固定点迭代。旧归档缺少的新 deferred-OR 探针仍单独记录，缺失值不当作零。[计数门](../../build/cv32e40p/covered-state-views-v1/count-gate.json)、[通知阶段计数](../../build/cv32e40p/covered-view-notify-counts-v1/counts.json)、[直接读取阶段计数](../../build/cv32e40p/covered-view-inline-counts-v1/counts.json)。

## 固定测量与结果

node030 CPU96、NUMA1、单线程、ASLR 关闭；等自身构建／测试任务全部结束后计时。四后端各预热一次，每样本完整重启一次 CoreMark。一组 8 轮正反序，32 个正式样本全部通过功能及 placement/locality 门，attempt 均为 0，没有重试、删样本或追加选择。既有 runner 记录的 CPU288 sibling 空闲率均为 100%。[测量协议](../../build/cv32e40p/covered-state-views-v1/measurement-policy.json)、[逐对结果](../../build/cv32e40p/covered-state-views-v1/pairs.csv)。

| 后端 | 外部 walltime 均值 | 相对本轮原保留版的配对变化 | 95% CI |
| --- | ---: | ---: | --- |
| 原保留版 | 2.929226 s | — | — |
| 仅去比较／通知 | 2.889882 s | −1.3430% | [−1.4512%, −1.2414%] |
| 再去槽位／赋值 | 2.838107 s | −3.1106% | [−3.2191%, −2.9985%] |
| 同 RTL Verilator | 2.810657 s | — | — |

两个阶段各自对原保留版都是 **8/8 轮更快**。第二阶段相对第一阶段还降低 **1.7915%**，CI **[−1.9245%, −1.6553%]**，同样 8/8 更快。因此只消除比较／通知会留下可测量的槽位与表达式边界成本。

仿真循环相对基线分别降低 **1.3734%**（CI [−1.4783%, −1.2745%]）与 **3.1829%**（CI [−3.2987%, −3.0652%]）；两阶段的初始化比值 CI 都跨 1。收益主要出现在持续仿真，不能归因于启动快慢。

原保留版／Verilator 为 **1.042186**，CI [1.041040, 1.043208]；仅去通知为 **1.028188**，CI [1.027627, 1.028695]；直接读取为 **1.009767**，CI [1.008574, 1.011121]。直接读取的纯仿真循环比值是 **1.011137**，CI [1.010223, 1.012157]。这些都是同轮配对值，不能用它们声称已超过 Verilator，也不与原始 SV 版本混为一谈。[汇总](../../build/cv32e40p/covered-state-views-v1/summary.json)、[完整报告](../../build/cv32e40p/covered-state-views-v1/report.json)。

## C++、ELF 与实际执行量

每后端一次独立 PMU 计数，包含初始化；不以单次主机 cycles 代替配对 walltime：

| 每模拟周期 | 原保留版 | 仅去比较／通知 | 再去槽位／赋值 | Verilator |
| --- | ---: | ---: | ---: | ---: |
| retired instructions | 10276.327 | 10169.075 | 10131.255 | 9799.122 |
| branches | 465.027 | 464.892 | 465.788 | 568.442 |
| branch misses | 1.263 | 1.268 | 1.284 | 0.876 |

两阶段相对原版分别少 **107.252 条（1.0437%）**与 **145.072 条（1.4117%）**退休指令／模拟周期。第二阶段进一步少 **37.820 条／周期**。循环、区域和缓存的执行次数未变，说明不是少模拟了工作或改变调度活跃频率。

对应到 ELF，指令 bit14（37838）的旧定义块有旧槽位 load、`xor` 判变和 store；第一阶段留下位抽取与 store，旧值读取和判变消失。DWARF 归属该块的静态指令数为 9→5，ALU 符号位 30221／30285 为 7→4、6→3。第二阶段没有这些生产者定义或槽位引用，位操作移到原消费者表达式中。行号归属可能被编译器合并／移动，上述数目不当作逐值动态节省量。

| ELF 静态指令数 | 原保留版 | 仅去比较／通知 | 再去槽位／赋值 |
| --- | ---: | ---: | ---: |
| compute batch 0 | 450 | 418 | 409 |
| compute batch 1 | 2267 | 2190 | 2280 |
| compute batch 2 | 8221 | 8216 | 8100 |
| compute batch 3 | 178 | 178 | 179 |

直接读取并不保证每个函数都缩小：batch 1 指令数回升，而主要消费者 batch 2 明显下降。batch 1 的栈分配是 168→160→184 B，batch 2 是 2456→2456→2488 B；这里没有“减少栈帧”的证据。消费者表达式变化、槽位重排和寄存器分配同时发生，不能仅用删去 25 B 槽位或源代码行数解释全部时间收益，也不能从这次单样本 PMU 再分解各微架构因素的占比。

已核对 ELF 中的 generated-source MD5 与实际 C++ 文件，对 21 个旧定义块逐一归档源码和行号机器码，并核对直接读取版中原槽位引用全部消失。[源码／ELF 证据](../../build/cv32e40p/covered-state-views-v1/machine-evidence/report.json)、[行为／PMU／配对分析](../../build/cv32e40p/covered-state-views-v1/boundary-analysis.json)。本轮消除了被证明冗余的简单视图接口，剩余 188 个 checked values 未扩大处理；没有据测量结果改变规则或选择新的组合。

## 验证边界与复现入口

专项回归覆盖 default/off 一致性、环境变量与显式选项优先级、execution plan、原激活集合不变，以及 1／17／64 bit、signed state、双时钟、异步复位、掩码写、重复 eval 和重新初始化；Clang 23 O0/O3 与 ASan/UBSan 下独立 oracle 和区域执行次数均通过。负例覆盖缺少独立 reader、公开／effect／commit／event 用户、多写者及译码缓存键。

开发时专项测试曾错误地用不受支持的 `waveform=vcd` 请求波形，该字符串实际被解析为关闭；已改为正式的 `declared-symbols`。当前工具未构建 libfst，因此该用例验证的是波形请求在 lowering 前被明确拒绝，未宣称完成带波形运行测试。模型本身的波形模式采用整体回退。此测试修正不改变已冻结的模型代码。

最终 **5 项 emitter CTest、16 项相关 Python 测试**通过，`py_compile`、父仓／Wolvrix `git diff --check` 和新增文档链接检查通过。除新专项外，回归包含事件区域、精确输入缓存、已有直接 Boolean 状态视图和语义家族共享译码；两个既有 `emit-grhsim-cpp` 用例还使用其原来固定的系统 Clang 19，不能统称为全部 Clang 23 测试。验证日志与当前测试源身份见[validation.json](../../build/cv32e40p/covered-state-views-v1/validation.json)。

```sh
# 在 node030 的本仓目录执行；输出目录必须不存在。
python3 scripts/cv32e40p_covered_state_views_compare.py build --output build/cv32e40p/covered-state-views-v1
python3 scripts/cv32e40p_covered_state_views_compare.py verify --output build/cv32e40p/covered-state-views-v1
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/covered-state-views-v1 --backend grhsim_covered_view_notify --output build/cv32e40p/covered-view-notify-counts-v1 --detailed --jobs 6
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/covered-state-views-v1 --backend grhsim_covered_view_inline --output build/cv32e40p/covered-view-inline-counts-v1 --detailed --jobs 6
python3 scripts/cv32e40p_covered_state_views_analysis.py --source build/cv32e40p/covered-state-views-v1 --notify-counts build/cv32e40p/covered-view-notify-counts-v1 --inline-counts build/cv32e40p/covered-view-inline-counts-v1 --counts-only
python3 scripts/cv32e40p_covered_state_views_compare.py measure --output build/cv32e40p/covered-state-views-v1
python3 scripts/cv32e40p_covered_state_views_compare.py diagnose --output build/cv32e40p/covered-state-views-v1
python3 scripts/cv32e40p_covered_state_views_analysis.py --source build/cv32e40p/covered-state-views-v1 --notify-counts build/cv32e40p/covered-view-notify-counts-v1 --inline-counts build/cv32e40p/covered-view-inline-counts-v1
```

XiangShan 的未分图纯寄存器位段可以使用同类静态证明，但多分区传输和 reg-to-mem 后的存储不满足本规则的直接寄存器条件，不能直接套用。此次没有新建 XiangShan 模型或跑分，未宣称其命中率或收益。
