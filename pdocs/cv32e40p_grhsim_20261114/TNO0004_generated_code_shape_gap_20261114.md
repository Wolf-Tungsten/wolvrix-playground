# TNO0004：GrhSIM 与 Verilator 生成代码形态及剩余差距

本轮定位到的主要方向是 **减少 bit 中间值的物化、拆分后重新拼接，以及附带的变化检测和活动通知**。同一份归一化 RTL 上，GrhSIM 每模拟周期执行的 Host 指令是 Verilator 的 **2.1274 倍**；另有约 **1.1115 倍**的 IPC 差异。两者乘积为本次 PMU 的 Host cycle 倍率 2.3646，与上一轮正式 walltime 倍率 2.3521 接近。

最具体的缺口出现在调度前：两个寄存器堆 concat 各有 993 个输入，其中 992 个是一位 slice；每连续 32 位都来自同一个 32 位 SSA 值。用通用 `concat(slice(x), …)` 合并规则，可以把每个 concat 的输入数降到 32。当前按需拼装和八项 slice 写回优化仍保留这些中间 bit，因而只消除了部分成本。

本轮仅新增分析脚本、独立诊断模型及记录；沿用已冻结的生产 binary，没有修改生产 emitter、默认配置或 RTL。没有开展候选搜索，也没有新增正式配对计时。下文区分已测量的开销、观察到的代码形态和待实现验证的优化方向。

## 比较口径与身份

正式性能结论继续引用 [TNO0003](./TNO0003_packed_scalar_slices_and_xiangshan_20261114.md) 的同一组八轮数据：

| 后端 | 进程 walltime 均值 | GrhSIM / 该后端 | 95% paired bootstrap CI |
| --- | ---: | ---: | ---: |
| 当前 GrhSIM | 7.428087 s | 1 | — |
| 归一化 RTL Verilator | 3.158048 s | 2.352143 | [2.344439, 2.359743] |
| 原始 RTL Verilator | 1.471477 s | 5.048128 | [5.027531, 5.067301] |

GrhSIM 与第一种 Verilator 读取相同的 sv2v/Yosys 归一化 RTL；第二种 Verilator 直接读取原始 RTL，保留更多数组和整数结构。后者反映整体使用路径的差距，不能全部归因于后端。三侧运行同一 CoreMark，3,376,065 guest cycles、十次迭代、相同 UART/CRC/exit。保留真实时钟门控、相同 RTL RAM 和 harness。编译器为 Clang 23.1.2，`-O3 -march=native`；单线程、无波形。

本轮三侧分别一次 `perf stat`、一次 `cycles:u` 采样、一次 cache PMU；另各生成一个独立计数版本，运行 smoke 和完整 CoreMark。均在 node030、CPU96、NUMA1、ASLR disabled 执行；CPU288 sibling 最低记录为 99.4505% idle，不干预其他进程。15 次诊断样本全部通过功能和 placement 检查，计数版本的六份完整总线 trace 也与原始基准一致。

生产 binary SHA256：

| 后端 | SHA256 |
| --- | --- |
| GrhSIM | `6f3157a53b14b8f65bbd8c1fc9a254fd90e242c3630599959c26d70fc1ca7603` |
| 归一化 Verilator | `5396106991546a7aa0da975a44e9b92c21988bf6a4d60d4755bdafa370be7614` |
| 原始 Verilator | `6b90343c3a7ff6fe9da056cb56decf995ea9757e22b4bf3b3846e3c8f53c1661` |

源码、header、IR、binary 身份见 [static.json](../../build/cv32e40p/code-shapes-v1/static.json)；汇总阶段重新校验这些生成源和 binary 的 hash。插桩版本只用于执行次数，其耗时不进入性能比较。PMU 统计包含进程初始化/退出，除以完整 guest cycles；软件计数器则在装载镜像及复位完成后清零，两种统计边界不同。

## Host 指令量解释了大部分差距

| 指标 | GrhSIM | 归一化 Verilator | 原始 Verilator |
| --- | ---: | ---: | ---: |
| Host instructions / guest cycle | 20,846.64 | 9,799.12 | 5,355.19 |
| Host cycles / guest cycle | 6,949.86 | 2,939.16 | 1,354.17 |
| Branches / guest cycle | 848.23 | 568.44 | 674.09 |
| Branch misses / guest cycle | 2.1103 | 0.9007 | 0.9474 |
| IPC | 2.9996 | 3.3340 | 3.9546 |

PMU running fraction 均为 100%，采样频率 499 Hz、lost samples 均为 0。`cycles = instructions / IPC`，因此：

- 相对归一化 Verilator：`2.127399 × 1.111488 = 2.364577`。
- 相对原始 Verilator：`3.892795 × 1.318377 = 5.132173`。

这是计数恒等式分解，不能把各类 C++ 写法的耗时直接相加，也没有据此更新正式 walltime CI。它表明优先压缩生成模型的工作量有依据。初始化仅毫秒级；本次 G/V-normal/V-original 的 PMU 样本初始化分别约 7.46/11.15/11.06 ms，解释不了秒级差距。

GrhSIM 的主要采样函数仍是 compute：batch 5/0/6/7/4 分别占 12.38%/9.83%/5.71%/5.31%/4.72%；`eval()` 自身 2.10%。归一化 Verilator 的 `nba_sequent__TOP__0` 与 `nba_comb__TOP__0` 分别占 57.83% 与 24.49%，工作集中在较大的顺序代码区。不同后端函数边界不同，不能直接对比某个函数的占比作为绝对耗时。

## 寄存器堆：word 拆成 bit，再重新拼成 word

以下是简化后的数据路径示意，准确表达式以链接中的生成源码为准：

```text
GrhSIM:
  uint32 register state
    -> 32 Boolean value slots
    -> old/new 比较、写回、reader 通知
    -> 根据读地址选中一至两个 64-bit 区间，读取 Boolean slots 并拼接
    -> 32-bit read data

归一化 RTL Verilator:
  uint32 register state -> 共享的 32-word packed array -> 动态读取表达式

原始 RTL Verilator:
  packed register bank -> mem[read_address]
```

GrhSIM 的寄存器**状态本身已经是 uint32**，例如 x1 对应 `state_logic_storage_.u32_slots_53`；问题是从状态流向组合读取时物化的 bit 中间值。它不是把所有寄存器状态存成独立 bool，也不是每周期复制整个 4 MiB RAM。

具体对照：

| 位置 | 观察 |
| --- | --- |
| [GrhSIM sched_3](../../build/cv32e40p/packed-slices-final/grhsim_packed_slices/grhsim_Cv32Bench_sched_3.cpp)，785 行起 | 同一个 uint32 状态通过四组 `grhsim_store_scalar_slices` 写入 32 个 bool slot，并累计各 bit 的变化通知。上一轮优化已经把每八项写回合并，但目标仍是 bool slots。 |
| [GrhSIM sched_5](../../build/cv32e40p/packed-slices-final/grhsim_packed_slices/grhsim_Cv32Bench_sched_5.cpp)，1626、1718 行 | `grhsim_concat_word_41661` 用 switch 按需选择区间，再从 bool slots 移位、OR，交给 `grhsim_indexed_concat_slice<1024,32>`。已避免完整 1024-bit 拼装，但选中区间仍需 bit-to-word 转换。 |
| [GrhSIM commit](../../build/cv32e40p/packed-slices-final/grhsim_packed_slices/grhsim_Cv32Bench_sched_23.cpp)，1677 行起 | x1 写入仍是 uint32 比较/赋值，进一步确认状态存储与 bit 中间值是两件事。 |
| [归一化 Verilator root_0](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp)，3601 行起 | `_13862_[0]=0`，随后用 uint32/uint64 表达式填充寄存器 bank 的 word。两个读口共用 `_13862_`，没有单独保留第二份 `_13863_` 数组。 |
| [归一化 Verilator root_1](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__1.cpp)，3166 行起 | 归一化后的动态读取仍有重复的索引/bit 提取表达式；不能把它描述成原始 RTL 版本那样的一次简单数组读取。 |
| [原始 Verilator root_0](../../build/cv32e40p/run2/verilator-original/VCv32Bench___024root__0.cpp)，5766 行起 | `regfile_data_ra_id = mem[(instr_rdata_id >> 15) & 31]`，bank 是 `VlWide<32>`，底层按 32-bit word 直接索引。 |

因此上一轮的 indexed read 和 packed slice 都有作用，但尚未恢复 Verilator 的 word 数据流。仅继续打磨末端 pack helper，仍会保留之前的拆分、持久化和变化跟踪。

## 调度前已经存在可简化的结构

扫描 [调度前 graph.json](../../build/cv32e40p/run2/graph.json)，只接受相邻 operand 为同一 SSA 源的合法 `kSliceStatic`，并且位区间按 concat 顺序连续。`kConcat` 的 operand 从高位到低位；`sliceStart`/`sliceEnd` 是含两端的低/高位。例如：

```text
concat(slice(x,31:24), slice(x,23:16), slice(x,15:8), slice(x,7:0)) -> x
concat(prefix, slice(x,23:16), slice(x,15:8), suffix)
  -> concat(prefix, slice(x,23:8), suffix)
```

第一条要求 x 宽度恰为 32；两条都要求 slice 同源、有效、连续、位序正确，保留 concat 位宽和位模式。本轮扫描只统计形态，尚未执行 rewrite 或推算性能。

| IR operation / 输出 | 当前 operand 数 | 合并相邻同源 slice 后 | 可合并组数 |
| --- | ---: | ---: | ---: |
| `_op_44694` / `core$_13862_`，寄存器堆 | 993 | 32 | 31 |
| `_op_44800` / `core$_13863_`，寄存器堆 | 993 | 32 | 31 |
| `_op_24479` / `core$_13859_`，CSR | 194 | 8 | 6 |
| `_op_24584` / `core$_13860_`，CSR | 194 | 8 | 6 |
| `_op_24689` / `core$_13861_`，CSR | 18 | 3 | 1 |

整个图中有 **775 个 concat、976 组连续片段、14,178 个可减少的 operand 引用**。引用减少量不是可删除 operation 的数量；被其他用户或可观测名称引用的 slice 仍可能保留。完整逐组证据见 [concat-slice-shapes.json](../../build/cv32e40p/code-shapes-v1/concat-slice-shapes.json)。

前端已经运行 [SimplifyPass](../../tools/grhsim32/frontend.cpp)，不存在“忘记跑 simplify”的问题。当前 [redundant_elim.cpp](../../wolvrix/lib/transform/redundant_elim.cpp) 574 行起主要处理嵌套 concat 展平，693 行起处理全宽/嵌套 slice 和 `slice(concat)`；上述 `concat(slice(x), …)` 连续片段没有在当前流程中被重新合并。

调度前图有 44,615 个 operations、14,978 个 static slices。调度后为 49,804 个 operations，static slices 仍为 14,978。153 个不同寄存器的 read operation 从 153 增至 3,021，源于调度时 clone；生成器会内联其中许多 read，因此 **不能把 3,021 个 IR read 当作每轮 3,021 次实际内存加载**。这也说明应优先在调度前恢复 word 结构，之后再检查 slice 的存活、调度 clone 和通知是否同步减少。

CSR 同样值得关注：[GrhSIM sched_7](../../build/cv32e40p/packed-slices-final/grhsim_packed_slices/grhsim_Cv32Bench_sched_7.cpp) 115 行起仍构造宽数组并从 bit slots 拼装；大常量使它不满足当前 indexed-concat 的全部 scalar operand 条件。[归一化 Verilator](../../build/cv32e40p/run2/verilator/VCv32Bench___024root__0.cpp) 2903、3695 行起同样保留宽 CSR 临时数组，但以 word 填充，并共享一份 `_13859_` 给两组读取。这里的区别包括拆分/拼装与共享程度，不能概括成“Verilator 完全不构造宽 CSR”。

## 动态执行：三轮调度不等于整机重算三遍

计数模型保持原计算和分支，只追加 uint64 计数器，按外部 clock 低/高相位分别记录。计数器在装载镜像和复位后清零；全部六份 trace 与原模型一致。详细 probe 清单在各诊断目录的 `probes.json`，结果在 [counts.json](../../build/cv32e40p/code-shapes-v1/counts.json)。

| GrhSIM，每 guest cycle | 低相位 | 高相位 | 合计 |
| --- | ---: | ---: | ---: |
| `eval()` 调用 | 1 | 1 | 2 |
| fixed-point 调度轮数 | 1.0000003 | 2 | 3.0000003 |
| 真正进入的 compute groups | 1.000014 | 110.598342 | 111.598356 |
| 真正进入的 commit groups | 1.0000003 | 4.9999997 | 6 |
| scalar old/new 比较 | 5.000078 | 908.159161 | 913.159239 |
| scalar 值发生变化 | 1.000002 | 148.712010 | 149.712012 |
| 八项 packed slice 比较 | 0.000005 | 73.505569 | 73.505574 |
| packed slice 中变化的 bit | 0 | 56.264782 | 56.264782 |
| 直接 activity flag OR 语句执行 | 6.000051 | 485.461625 | 491.461676 |

23 个 compute batch 每轮都会被调用，但内部 activity 条件会跳过不活跃 group。低相位几乎只有时钟门控相关计算；高相位只有 compute group 96 平均执行超过一次（1.202095 次），其余 compute group 均不超过一次。当前数据不支持把性能差距归结为“每周期完整计算三遍”。

归一化 Verilator 的 `eval_act`/`eval_nba` 低相位各进入一次、高相位各两次，但真正 `eval_body__nba` 只在高相位进入一次。六个顺序/组合 NBA 代码区各约一次。原始 RTL Verilator 的高相位 `eval_act`/`eval_nba` 反而平均进入 3.7400/2.3700 次，NBA body 进入 1.3700 次，仍然最快。这些函数首先检查 trigger，不能把函数入口数直接当作数据通路重算次数。

scalar 比较中仅 **16.395%** 检测到变化；packed 八项组有 **21.908%** 检测到任一变化，按 bit 计变化比例为 **9.568%**。细粒度跟踪确实跳过了部分计算，也确实引入比较、旧值读取、写回与通知成本；这些计数尚不能证明关闭 activity schedule 会更快。

计数覆盖边界：scalar 只统计生成的 `grhsim_changed_*` 语句，包含整数和 bool，不包含所有 commit 比较；packed 统计当前平台使用的八项 helper；direct OR 仅统计源码显式 `supernode_active_curr_[…] |= …`，不涵盖 helper 内部写入，并且执行时 mask 可能为零。491.46 是该类语句的执行次数，不是 491.46 次非零激活。

## 代码体积、表与 cache

| 静态形态 | GrhSIM | 归一化 Verilator | 原始 Verilator |
| --- | ---: | ---: | ---: |
| 常规计算 C++ 源码 bytes | 4,206,342 | 1,472,585 | 852,288 |
| 本次所选模型计算函数机器码 bytes | 178,724 | 65,387 | 44,932 |
| 持久一位字段，见口径说明 | 3,142 value bool slots | 273 root 一位 CData | 158 root 一位 CData |
| table 数 / lookup 源码位置 | — | 219 / 839 | 7 / 20 |

GrhSIM 的 bool slots 不含另外 61 个 Boolean state 字段；Verilator 的 root 字段包含状态及中间量，且各后端内联边界不同，因此字段数只比较物化程度，不能视为一一对应的逻辑数量。[TNO0006](./TNO0006_remaining_decode_and_scheduling_gap_20261114.md) 进一步确认，273 个一位 CData 标量字段不含两张 one-hot 表的 8,192 个元素；不能据此认定 Verilator 的全部 Boolean 存储更少。机器码统计选择 compute/commit/eval 或 NBA/ACT/ICO 模型函数，完整符号清单见 [compiled-hot-functions.json](../../build/cv32e40p/code-shapes-v1/compiled-hot-functions.json)。整个 ELF `.text` 反而是 GrhSIM 192,295、V-normal 349,392、V-original 281,936 bytes，Verilator 还包含通用 runtime；不能用整个 `.text` 大小反推热代码大小。

GrhSIM 源码有 1,494 个 scalar 比较位置、212 个 packed 比较位置、896 个显式 activity OR 位置。许多 bit slot 是跨 group/函数存活的模型成员，C++ 编译器不能像优化一个局部纯表达式那样直接消除它们。恢复 IR word 数据流可同时影响算术表达式、持久值数量和活动通知，范围比局部 pack 指令优化更大。

归一化 Verilator 的 219 张表并非全部为复杂 Boolean 逻辑：其中 17 张只是取某一位、13 张取某一位的反值、4 张常量；对应 lookup 位置分别 95/37/51，其余 185 张表对应 656 个位置。详见 [table-shapes.json](../../build/cv32e40p/code-shapes-v1/table-shapes.json)。因此不能仅凭 Verilator 有更多 table，就推断给 GrhSIM 增加 LUT lowering 一定获益。原始 RTL 版本只有七张表却最快。

同机补充 cache PMU，每模拟周期：

| perf 事件 | GrhSIM | 归一化 Verilator | 原始 Verilator |
| --- | ---: | ---: | ---: |
| L1-icache-loads | 3,051.82 | 1,039.19 | 325.67 |
| L1-icache-load-misses | 43.163 | 29.591 | 1.661 |
| L1-dcache-loads | 7,794.94 | 4,024.36 | 1,664.83 |
| L1-dcache-load-misses | 3.409 | 10.307 | 0.054 |

事件均以 user 模式请求、running fraction 100%。这些是 node030 上 perf 提供的计数，不把 miss 数直接换算为停顿秒数。GrhSIM 的指令获取与数据访问量更大；但归一化 Verilator 的 D-cache miss 更多，仍明显更快，故不能把本次主要差距概括为 GrhSIM 数据 cache miss。剩余 IPC 差距包含指令获取、依赖链和控制流等因素，尚未逐一隔离。

## 下一步优先级与 XiangShan

1. **先在调度前合并同源连续 slice 的 concat。** 从上述明确的纯位模式恒等式入手，保持符号可观测性、位序/宽度/符号扩展和不同用户的语义；查看 DCE 后是否实际减少 bool slot、clone 和 activation。寄存器堆 993→32、CSR 194→8 提供了具体检查点。实现后才用同一冻结负载验证功能和性能，不预先宣称收益。
2. **再评估更粗的值存储和活动传播。** 当前大量中间 bit 持久化、每周期近千次值比较，支持研究内部纯组合值留在局部、边界按 word/group 通知的方向。必须保留时钟门控、effect/event 和 fixed-point 正确性；不能直接删除收敛轮次或把所有 reader set 合并。
3. **原始 RTL ingest/数组保留是另一个独立差距来源。** 原始 Verilator 比归一化 Verilator 指令数少约 45%，且 register bank 直接索引。恢复前端对原始结构的支持可能同时改善两侧间的总差距，但不应与上述后端优化混在一次 A/B 中。

这些方向都按通用 IR 形态定义，不按 CV32 信号名、一次 profile 或运行后的快慢选择候选。第一项适用于任何出现 `concat(slice(x), …)` 的设计；第二项也可能惠及 XiangShan 的 Chisel Vec、译码和字段逻辑。TNO0003 已有 XiangShan 拆 bit 形态证据，但本轮没有重建/测量 XiangShan，也没有扫描其完整 IR 的 concat 合并命中；已有 packed-array/reg-to-mem 路径还可能消除部分机会，不能外推收益比例。

## 复现与验证

先保留 TNO0001–0003 的冻结输入和生成产物。在 node030 本项目目录执行以下命令，输出目录必须是新目录；analysis 脚本读取固定的 `run2` 和 `packed-slices-final`，不会重新生成生产模型：

```bash
python3 scripts/cv32e40p_code_shapes.py static --output build/cv32e40p/code-shapes-reproduce
python3 scripts/cv32e40p_code_shapes.py extras --output build/cv32e40p/code-shapes-reproduce
python3 scripts/cv32e40p_code_shapes.py build-counts --output build/cv32e40p/code-shapes-reproduce --jobs 16
python3 scripts/cv32e40p_code_shapes.py count --output build/cv32e40p/code-shapes-reproduce
python3 scripts/cv32e40p_code_shapes.py pmu --output build/cv32e40p/code-shapes-reproduce
python3 scripts/cv32e40p_code_shapes.py cache-pmu --output build/cv32e40p/code-shapes-reproduce
python3 scripts/cv32e40p_code_shapes.py report --output build/cv32e40p/code-shapes-reproduce
PYTHONPATH=scripts python3 -m unittest test_cv32e40p_code_shapes
```

三个新回归通过，覆盖计数注入保留原计算/条件、Verilator 函数声明不误计为定义、共享 probe ID。`py_compile`、两仓 `git diff --check` 和相对链接检查通过；Wolvrix 当前 tracked diff 与 TNO0003 的冻结 patch 完全一致。计数版本 smoke 为 253 cycles、CoreMark 为 3,376,065 cycles，三侧每个 workload 的完整总线 trace hash 一致：

- smoke：`84e48e4a17e723b73c167a256a44ded549bd8f82d36cc5be4070554f40763fc0`
- CoreMark：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`

本轮代码和文档仍位于 `thj/cv32e40p-grhsim-investigation-20261114`，未新增提交。生产功能验证继续使用先前已通过的 CTest；本轮不重复整机优化实验。

## 产物

- [分析脚本](../../scripts/cv32e40p_code_shapes.py)、[计数回归](../../scripts/test_cv32e40p_code_shapes.py)、[完整机器报告](../../build/cv32e40p/code-shapes-v1/report.json)
- [静态源码/IR 身份](../../build/cv32e40p/code-shapes-v1/static.json)、[计数 binary 身份](../../build/cv32e40p/code-shapes-v1/count-builds.json)、[逐项动态计数](../../build/cv32e40p/code-shapes-v1/counts.json)
- [GrhSIM perf](../../build/cv32e40p/code-shapes-v1/grhsim-perf.txt)、[归一化 Verilator perf](../../build/cv32e40p/code-shapes-v1/verilator-perf.txt)、[原始 Verilator perf](../../build/cv32e40p/code-shapes-v1/verilator-original-perf.txt)
- [GrhSIM PMU](../../build/cv32e40p/code-shapes-v1/grhsim-stat.csv)、[归一化 Verilator PMU](../../build/cv32e40p/code-shapes-v1/verilator-stat.csv)、[原始 Verilator PMU](../../build/cv32e40p/code-shapes-v1/verilator-original-stat.csv)
- [GrhSIM cache PMU](../../build/cv32e40p/code-shapes-v1/grhsim-cache.csv)、[归一化 Verilator cache PMU](../../build/cv32e40p/code-shapes-v1/verilator-cache.csv)、[原始 Verilator cache PMU](../../build/cv32e40p/code-shapes-v1/verilator-original-cache.csv)
- [样本、trace 与 placement](../../build/cv32e40p/code-shapes-v1/runs/)、[本轮验证](../../build/cv32e40p/code-shapes-v1/validation.json)
