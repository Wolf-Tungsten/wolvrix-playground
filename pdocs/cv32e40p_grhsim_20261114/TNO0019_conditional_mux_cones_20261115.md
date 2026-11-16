# TNO0019：分支专用组合锥的条件求值

新增默认关闭的 emitter 规则，把同一 compute 组内、只供一个 mux 分支使用的纯标量计算移入条件内部。最终直接 `if/else` 版在 node030 CPU96 的8轮配对中全部更快：walltime **−4.40%**，95% CI **[−4.70%, −4.16%]**。相对同归一化 RTL 的 Verilator，从同轮保留版的 **1.14356 倍降到1.09323倍**。

退休指令减少4.73%，每guest cycle少526.47条；活动调度、逐值变化检测等865项计数完全一致。这次收益来自减少实际执行的分支计算，未改图、分区、调度边界或生产默认值。保留该版本作为新的最佳实验组合：单终点event regions + 条件求值；此前predicate-set、slice-demand、local-equality及shared-region实验不叠加。

## 为什么需要这条规则

原生成器把候选值先求出，再调用 `grhsim_mux_u64(condition, a, b)`。参数求值已经发生；最终的mask或cmov只能选择结果，不能跳过前面的算术、bit-slice与concat。

当前保留版 `eval_compute_batch_3` 的反汇编，在生成源码3264行附近可见计算拼接结果之后的一串`cmpb/cmoveq/cmovneq`。证据见[带源码行的原机器码](../../build/cv32e40p/conditional-mux-analysis-v1/baseline-batch3.s)。本次直接把私有生产者放进函数内的`if/else`，而不是仅将mux helper改成三目表达式；后者仍不能撤销先前执行的生产者。

这修复的是GrhSIM直线化SSA lowering丢失条件求值边界的问题。它没有把整个硬件组合网络改成按指令分派，也没有证明Verilator在每个对应位置均已做相同变换。Verilator仍是同一冻结binary；本轮通过GrhSIM自身的受控改动解释可回收开销，不以变量名缺失或不同profile百分比代替跨后端因果证据。

## 实现和语义范围

开关：`conditional_mux_cones` / `WOLVRIX_GRHSIM_CONDITIONAL_MUX_CONES`，默认`false`。[功能文档](../../wolvrix/docs/emit/grhsim-conditional-mux-cones.md)、[实现](../../wolvrix/lib/emit/grhsim_cpp.cpp)、[回归](../../wolvrix/tests/emit/test_emit_grhsim_conditional_mux.cpp)。

- mux操作数是`(condition, true_value, false_value)`；根结果和两个分支必须同宽标量。可以仅延迟一侧。
- 每个移入分支的值只有一个有效的已调度操作数消费者，没有跨组消费者；共享计算保持原位置。无调度的死IR用户不算运行时使用。
- 不移动持久化、变化跟踪、端口、事件或storage alias值；也不移动其它packing/cache lowering预先使用的值。
- 全组必须是纯组合操作或寄存器读取；memory、latch、effect、behavior group及reg-to-mem intent回退。检查canonical storage唯一生产者和read-before-write，保持同组输入快照。工作始终留在compute，不移到commit。
- 静态预算为每分支16–256个私有操作。逆调度顺序先处理外层mux，避免重叠；不按信号名、热点或运行结果筛选。与priority-mux、bool-group lowering不组合。
- 分支内部复用现有标量生成逻辑，保留截断、有符号扩展及越界移位语义。execution-plan将分支标为条件相关工作，不能按每组执行次数把两臂都算成实际工作。

命中12个mux、16个非空分支，涉及601个原IR操作。关闭选项时所有生成C++/hpp与冻结保留版逐字节一致；候选`normalized.json`也与基线相同。32个compute组、4个commit组、413个checked value、704个scalar中间槽保持一致。[结构和位置](../../build/cv32e40p/conditional-mux-v4/structure.json)、[IR/RTL映射](../../build/cv32e40p/conditional-mux-v4/sources.csv)。

## 必须记录的实现回退：lambda被拆成函数

最初使用立即调用的捕获lambda表达条件求值。功能通过，但Clang23将多个lambda拆成了独立函数；主compute函数的调用点从1增到8。捕获原来的局部值需要构造闭包、写入指针、在新函数中加载，且调用边界增加了保存/恢复活跃值的成本。主函数从36,149增到41,939字节，还新增7个条件lambda函数；不是仅仅多了几个分支。

该版完整8轮全部保留：walltime **+22.9139%**，CI **[+22.1652%, +23.8692%]**，见[初版report](../../build/cv32e40p/conditional-mux-v3/report.json)、[lambda机器码形态](../../build/cv32e40p/conditional-mux-v3/lambda-shape.json)。

随后只做一次有明确机制的实现修正：使用函数内直接`if/else`，两臂赋给同一个标量临时值，再正常存储根结果。12个根、各臂操作数及全部选取规则保持一致。新增lambda符号消失，主函数调用点恢复为1；没有调整阈值、按profile删选区域或搜索多个策略。[一致性检查](../../build/cv32e40p/conditional-mux-v4/validation/evidence-checks.json)。v1/v2目录是发射阶段失败记录，未产出正式性能样本。

## 最终功能与测量

CoreMark沿用原冻结RV32IM镜像、2KB数据和10次迭代；三侧smoke为253周期，CoreMark为3,376,065周期。CRC、UART、退出码、完成周期和完整逐周期总线trace一致，CoreMark trace SHA为`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。[功能证据](../../build/cv32e40p/conditional-mux-v4/functional.json)。

| binary | SHA256 |
| --- | --- |
| 保留事件区域版 | `792ffa67830d766fd5418bd967e41615090141f8faa7c4ac58c0d3fa2438ee65` |
| 最终条件求值版 | `c7b8546489badb40431547248db1a6098b633f7592a94f9fba415eaed43dd5f3` |
| 同RTL Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |

固定node030、CPU96、单线程、NUMA1、ASLR关闭。Clang23.1.2，`-O3 -march=native -DNDEBUG -gline-tables-only`；无波形/正式性能插桩。三侧各预热一次，8轮ABC/CBA，每样本完整重启数1。24个正式样本一次通过功能和既有placement/locality门，无重试、无按快慢删样本；CPU288在所有样本区间均记录100% idle。外部loader映射按既有审计口径单独记录。

| 后端 | wall均值 | simulation loop均值 | init均值 |
| --- | ---: | ---: | ---: |
| 保留版 | 3.656567 s | 3.623848 s | 0.006941 s |
| 条件求值版 | 3.495543 s | 3.463123 s | 0.006998 s |
| Verilator | 3.197469 s | 3.161776 s | 0.010741 s |

- 候选/保留wall：**0.956005**，95% paired bootstrap CI **[0.952958, 0.958433]**。
- 候选/保留loop：0.955690，CI [0.952582, 0.958134]。
- 候选/Verilator wall：**1.093226**，CI **[1.091025, 1.095704]**。
- 同轮保留/Verilator wall：1.143561，CI [1.139485, 1.148864]。

比值为逐轮比值的均值；[report](../../build/cv32e40p/conditional-mux-v4/report.json)、[逐轮数据](../../build/cv32e40p/conditional-mux-v4/pairs.csv)、[策略](../../build/cv32e40p/conditional-mux-v4/measurement-policy.json)。构建独立记录：emit1.967s、并行model编译22.845s、harness链接1.371s，不计入仿真时间。

## 实际省下了什么

独立插桩模型只用于计数，不参与上述性能统计；它也通过smoke/CoreMark完整trace。候选与保留版的865项round、group、逐值比较/变化计数逐项相等。scalar比较仍为185.655056次/周期、变化37.115703次/周期，因此本次没有通过减少通知来提速。

按根执行次数和分支选择计数，601个静态私有操作对应每周期565.223个原IR操作；选择后执行404.748个，跳过 **160.475个/周期**。这里包括Clang原本可能已消去的slice/concat表达式，**不是**退休指令数。

| 根op | RTL位置/用途 | 真/假分支op数 | 真分支比例 | 跳过IR op/周期 |
| --- | --- | ---: | ---: | ---: |
| `_op_25983` | ff_one输入选择，RTL42585 | 33 / 0 | 0.00136% | 32.9996 |
| `_op_39561` | 控制组合选择`_07516_`，RTL43663 | 38 / 41 | 0% | 32.1097 |
| `_op_31931` | ff1结果选择，RTL42871 | 30 / 30 | 0.000385% | 30.0000 |
| `_op_36888` | controller next state，RTL43215 | 27 / 25 | 0% | 27.0000 |
| `_op_11383` | CSR读结果选择，RTL42209 | 19 / 30 | 0% | 19.0000 |
| `_op_39380` | 控制选择，RTL43619 | 30 / 0 | 46.7695% | 15.9692 |
| `_op_2126` | 组合选择，RTL41642 | 27 / 0 | 87.4203% | 3.3965 |
| `_op_25120` | CSR/ALU forwarding选择，RTL42535 | 0 / 167 | 0% | **0** |

其余4个根在该负载也没有跳过其私有臂。尤其最大的167-op分支始终被选择，不能把它的静态规模解释为收益。选取规则没有据此删改这些根；完整计数与根映射见[attribution](../../build/cv32e40p/conditional-mux-v4/attribution.json)、[counts](../../build/cv32e40p/conditional-mux-counts-v4/counts.json)。

一次独立PMU诊断：

| 每guest cycle | 保留版 | 条件求值版 | Verilator |
| --- | ---: | ---: | ---: |
| retired instructions | 11,130.083 | 10,603.610 | 9,799.121 |
| Host cycles | 3,357.972 | 3,196.737 | 2,924.852 |
| branches | 471.673 | 478.838 | 568.442 |
| branch misses | 1.1454 | 1.0911 | 0.8925 |
| IPC | 3.3145 | 3.3170 | 3.3503 |

新分支多7.165次/周期，退休指令少526.473条/周期，IPC近似不变。结合严格保持的调度计数和直接分支机器码，证据支持“跳过未选择的私有计算”是收益机制；不能将一次PMU的branch-miss变化解释为稳定的预测器收益，也没有把526条净差逐根分摊。

静态函数反而稍大：

| `eval_compute_batch_3` | 保留版 | 最终版 |
| --- | ---: | ---: |
| code bytes | 36,149 | 37,219 |
| 静态instructions | 7,596 | 7,757 |
| conditional branches | 99 | 106 |
| stack-operand instructions | 1,676 | 1,716 |
| 调用点 | 1 | 1 |
| stack frame | 2,488 B | 2,440 B |

静态访存数不能替代动态spill数；不同时间的profile百分比仅作各自binary内定位。最终版主compute函数约占自身采样60.06%，commit9.38%；仍有8.21%的退休指令差距和9.32%的wall差距。[PMU/静态指标](../../build/cv32e40p/conditional-mux-v4/diagnostics.json)、[反汇编目录](../../build/cv32e40p/conditional-mux-v4/assembly)、[profile](../../build/cv32e40p/conditional-mux-v4/candidate-perf.txt)。

## 后续边界与XiangShan

本轮证明条件求值有可回收收益，但单用户私有锥只是保守起点。共享生产者仍必须提前计算，最大ALU结果臂又几乎总被选择；简单扩大16–256预算或按本次CoreMark选择根，均不能解决这些结构限制。后续值得分析的是：多个消费者的条件需求是否可以静态合并，以及共享ALU/CSR网络能否在不复制工作、不破坏状态快照的前提下形成条件区域。本轮没有继续实施或搜索这些策略。

规则没有CV32E40P名称依赖，理论上也可用于XiangShan中同组的ALU结果、译码候选和next-state选择。实际机会受分区边界、共享扇出、宽值及状态别名限制；尤其不能把CV32E40P CoreMark的分支比例当作XiangShan成本模型。捕获lambda被outlined的教训对XiangShan大compute函数同样相关。尚未对XiangShan生成/测量此规则，所以保持全局默认关闭。

## 复现与验证入口

依赖本仓已有冻结baseline、graph和firmware；新输出目录必须不存在。以下构建、功能、性能和诊断命令在node030执行，runner自行固定CPU96/NUMA1/ASLR：

```bash
cmake -S testcase/cv32e40p-bench -B build/cv32e40p/tools
cmake --build build/cv32e40p/tools --target cv32e40p_emit cv32e40p_map emit-grhsim-conditional-mux -j12
python3 scripts/cv32e40p_conditional_mux_compare.py build --output build/cv32e40p/conditional-mux-repro
python3 scripts/cv32e40p_conditional_mux_compare.py verify --output build/cv32e40p/conditional-mux-repro
python3 scripts/cv32e40p_conditional_mux_compare.py measure --output build/cv32e40p/conditional-mux-repro
PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH python3 scripts/cv32e40p_conditional_mux_compare.py diagnose --output build/cv32e40p/conditional-mux-repro
python3 scripts/cv32e40p_event_region_counts.py --source build/cv32e40p/conditional-mux-repro --backend grhsim_conditional_mux --output build/cv32e40p/conditional-mux-repro-counts --detailed
python3 scripts/cv32e40p_conditional_mux_analysis.py --source build/cv32e40p/conditional-mux-repro --counts build/cv32e40p/conditional-mux-repro-counts
```

输入工具、graph、选项、source snapshot、patch、compiler、harness和binary身份均在[build.json](../../build/cv32e40p/conditional-mux-v4/build.json)中校验；每条命令与构建耗时在`logs/`归档。

新增CTest覆盖default/off源码一致、两分支、仅选择条件变化、clock held、寄存器旧值、17/32/64位signed算术与overshift，以及公开观察值、effects、跨组使用、死IR用户、小/超大预算回退；off/on均通过Clang O0与O3 ASan/UBSan。[CTest日志](../../build/cv32e40p/conditional-mux-v4/validation/conditional-mux-direct-ctest.log)。24项相关Python测试通过，覆盖分支计数分区恒等式及成本方向；`py_compile`、两个仓库`git diff --check`和链接检查通过。代码尚未提交，生产默认未修改。
