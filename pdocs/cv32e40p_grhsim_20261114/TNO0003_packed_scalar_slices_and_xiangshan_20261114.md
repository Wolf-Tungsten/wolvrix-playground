# TNO0003：合并 scalar bit-slice 存储，并检查 XiangShan 适用性

## 性能结果与剩余差距

本轮 **GrhSIM walltime 再减少 6.7813%，95% 配对 bootstrap CI [6.4191%, 7.1380%]，8/8 轮均更快**。但性能仍明显落后于 Verilator。

| 指标 | 上一版 GrhSIM | 新 GrhSIM | 转换后 RTL Verilator | 原始 RTL Verilator |
| --- | ---: | ---: | ---: | ---: |
| 进程 walltime，均值 | 7.968544 s | 7.428087 s | 3.158048 s | 1.471477 s |
| 仿真循环，均值 | 7.935446 s | 7.395082 s | 3.121981 s | 1.433900 s |

| 配对倍率（分子 / 分母） | walltime | 95% CI |
| --- | ---: | ---: |
| 新 GrhSIM / 上一版 GrhSIM | 0.932187 | [0.928620, 0.935809] |
| 新 GrhSIM / 转换后 Verilator | **2.352143** | **[2.344439, 2.359743]** |
| 新 GrhSIM / 原始 RTL Verilator | **5.048128** | **[5.027531, 5.067301]** |

仅仿真循环的降幅为 6.8084%，CI [6.4482%, 7.1633%]。node030 CPU96、NUMA1、ASLR disabled、单线程；四侧各预热一次，正式做一组 8 轮，轮次顺序在“上一版、新版、转换后 Verilator、原始 Verilator”与反序间交替。每个样本完整执行十迭代，原始 Verilator 也超过一秒，重复数固定为 1。各倍率使用同轮数据和固定 seed 的 10,000 次 paired bootstrap。

32 个样本全部通过 workload signature 和 placement，零重试、零剔除；CPU288 sibling 均记录为 100% idle。正式计时开始前所有测试编译已结束，perf 另行执行。

原始 RTL Verilator 与 GrhSIM 不是同一份转换后 RTL，二者的 5.05 倍用于回答接近用户原始使用方式的差距；2.35 倍则隔离了共同 sv2v/Yosys 转换后的后端差异。四侧 trace 相同支持本 workload 一致性，不代表所有 CPU 配置和指令的形式等价。与 TNO0001 的历史均值不混合计算累计 CI。

## 动机与固定范围

接续 TNO0002 的 indexed-concat 版本，重新读取其 frozen perf 数据并定位源码行。剩余热点除了 CSR 拼装，还包括许多 `kSliceStatic`：从 8/16/32/64-bit 整数取一位，逐个加载旧 Boolean slot、比较、写回和通知。典型热点包含 batch 22 的 ALU operand 拆 bit、batch 13 的 min/max 结果拆 bit、batch 0 的 state read 拆 bit。这是多个函数共享的 IR 形态，不是单一信号的特殊处理。

本轮只实现一个通用 `packed_scalar_slices` lowering。比较基线是已包含 indexed-concat 优化的 binary；所有固件、RTL、IR、调度、harness、编译器和 placement 继续冻结。没有修改分区、采用 XiangShan preset、参数扫描或按性能结果选候选。实现过程中补全内联表达式的别名证明和 planner 上下文一致性；前期目录只有结构/功能验证，正式性能统计仅使用 `packed-slices-final`。

## 实现

[emitter](../../wolvrix/lib/emit/grhsim_cpp.cpp) 新增 `packed_scalar_slices`，默认开启，可用同名 emit attribute 或 `WOLVRIX_GRHSIM_PACKED_SCALAR_SLICES=0` 关闭。通用规则见 [功能文档](../../wolvrix/docs/emit/grhsim-packed-scalar-slices.md)。

连续八个纯 `kSliceStatic` 必须读取同一 resolved scalar 表达式，目标为八个连续、独立、canonical Boolean value slot。只支持 8–64-bit source；每个结果宽度为 1，sliceStart 等于 sliceEnd。读取位可任意排列，不要求连续。event、effect、混合 source、目标 alias、非连续 slot 和跨 supernode 均回退。

对源表达式沿 emitter 实际内联的叶子做别名检查，不能读取本组任一目标 slot；已有 named local 保留快照。组内没有 consumer、commit 或其它操作，源在写回前只求值一次。按当前平台的 Boolean 对象表示判定是否可使用八字节 `memcpy`：one-byte bool、0/1 表示、小端序和 eight-byte uint64 均需满足；否则走标量 fallback。

合并读取旧值、构造新值、写回并计算 XOR 后，每个 byte lane 对应原 bit 的精确变化。无变化时跳过通知块；有变化时仍调用原有的逐值 activation 发射，保留各自 reader set 和 deferred/shared/direct 语义，没有合并成更宽的 reader union。事件结果不进入该路径，不改变 event 分类。

最终 CV32 模型命中 **212 组 / 1,696 个 Boolean 结果**，覆盖 13 个 compute C++ 文件。源图、活动调度和 commit 均未变；execution planner 同样报告 212 组。关闭新开关后，全部生成 `.cpp` 与 TNO0002 frozen 模型逐文件一致。

## perf 证据与下一处结构机会

两侧各一次 `perf stat` 和一次 `cycles:u` 采样，独立于正式计时；PMU running fraction 均为 100%，lost samples 均为 0。计数包含初始化和退出，按 guest cycles 归一化：

| 每模拟周期指标 | 上一版 GrhSIM | 新 GrhSIM |
| --- | ---: | ---: |
| Host instructions | 22,344.76 | 20,846.64 |
| Host cycles | 7,435.41 | 6,912.10 |
| Branches | 838.51 | 848.23 |
| Branch misses | 2.1126 | 2.1158 |
| IPC | 3.0052 | 3.0160 |

Host 指令减少 **6.7045%**，与仿真循环下降约 6.81% 一致。新增“整组无变化”分支使 branch 数略增，branch misses 基本不变。`.text` 从 208,871 降到 192,295 bytes；`.rodata` 从 33,579,840 到 33,581,250 bytes。初始化均约 7.4 ms，收益主要在持续仿真计算。

新模型 compute 函数合计仍占采样的 93.59%，`eval()` 自身约 1.16%。batch 5/0/7 分别约 11.49%/10.27%/5.77%；优化后的整体执行时间下降会改变比例，不把比例升高直接解释为这些函数绝对耗时增加。

[源码行映射](../../build/cv32e40p/packed-slices-final/hot-source-lines.json) 仍能看到：batch 7 的宽 concat pack（line 173）、batch 4/5 的 scalar Boolean-to-word pack、batch 5 的逐值变化累计、batch 7 的 activity bitmap 通知，以及新 helper 的组写回。说明反复的 bit 拆分/重新拼接及活动传播仍然是后端成本，单纯减少 `eval()` 调用本身不是当前证据支持的主方向。

下一处明确的局部机会是 CSR bank 的三个 `concat + dynamic slice`：源宽为 2048/2048/1024 bits，最大 operand 分别达 1792/1792/912 bits，均有唯一 32-bit slice 用户且同 supernode；它们超出了 TNO0002“输入全为 scalar”的证明范围。后续可独立研究宽常量/宽字段的按需读取，保持各字段 snapshot。更大范围的方向是保留整数/数组表示、减少 bit-level 中间值；它也可能惠及 XiangShan，但需要新的别名与激活证明，不能仅扩大当前规则阈值。

没有在观察到本轮性能后继续生成候选。新模型 emit/compile/link 为 2.46/18.59/1.14 s；构建成本单独归档，没有与不同缓存条件的历史构建比较。

## XiangShan 的适用性

对既有 `parent-default-single-20261114-v1/model` 做只读扫描：

| 扫描口径 | CV32E40P | XiangShan 单核 |
| --- | ---: | ---: |
| 广义 scalar-to-bit 生成表达式 | 2,131 | 43,996 |
| 同一源在文件内出现至少 8 次的组，涉及 bit 数 | 2,058 | 28,236 |
| 连续 static slice + 连续 bool slot 的八项组 | 212 | 424 |
| 严格组涉及的 Boolean 结果 | 1,696 | 3,392 |

广义计数只描述形态，包含非纯 static slice；更严格扫描仅接受连续的 static slice store，不跨其它文本操作。它仍不是在新 emitter 上的完整 IR eligibility 证明，不等同于 424 组一定被采纳，更不能直接估算 walltime。

严格例子包括 `grhsim_SimTop_sched_0.cpp` 第 129899 行：从 `state_logic_storage_.u16_slots_3390` 的低八位读取到 `value_bool_slots_[382936..382943]`。这种字段拆 bit 形态与 CV32 完全同类；37 个相关生成文件的 hash 已归档。回归同时覆盖共享 deferred activation、Boolean eager logic、wordwise concat bool-pack 等与 XiangShan preset 相关的组合。

因此，这次优化有明确的跨设计适用线索，但本轮没有重建 XiangShan 整机，也没有改变其工作区、preset 或默认 assignment；尚无 XiangShan walltime 结论。上一项 indexed-concat 也对应 XiangShan Chisel Vec 动态读取的已知结构机会，但该设计已有 packed-array/reg-to-mem 等特化路径，实际命中需另查，不能直接套用 CV32 收益。

## 功能与回归

四侧均验证 smoke 和完整 CoreMark：上一版 GrhSIM、新版 GrhSIM、转换后 RTL Verilator、原始 RTL Verilator。Smoke 为 253 cycles；CoreMark 为 3,376,065 cycles、exit 0，CRC/UART 全部相同，完整总线 trace SHA256 均为 `ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。

三项 CTest 通过：

- `emit-grhsim-cpp-packed-scalar-slices`：default/on/off/环境优先级、非对齐地址、任意位顺序至 bit 63、内联源、named snapshot、时钟状态/写使能/重复 eval/reinit，以及 effect/event/混合源负例。普通、split、profile、共享通知模型均通过 Clang 23 O0/O3 + ASan/UBSan。独立 oracle 检验 fast/forced-portable helper 的值、每个 bit 的变化 mask 和两端 sentinel。Planner 与 emitter 命中数相同。
- `emit-grhsim-cpp-indexed-concat-slice`：上一项寄存器堆优化的语义回归通过。
- `emit-grhsim-execution-plan`：planner 独立回归通过。修正了 planner 之前未记录部分 scalar constant/read/inline expression 上下文的问题，使新 shape 计数与发射一致。

六项 Python 测试通过，覆盖功能门、不同后端的倍率方向、连续优化的基线身份及显式加入的 Verilator 参照。`py_compile`、两仓 `git diff --check` 和新增链接检查通过。

## 复现

沿用 [原始准备流程](./TNO0001_reproduction_and_compute_cost_20261114.md) 和 [TNO0002 基线](./TNO0002_indexed_register_bank_reads_20261114.md)，在 node030 的本项目目录执行，输出目录必须是新目录：

```bash
cmake --build build/cv32e40p/tools --target cv32e40p_emit emit-grhsim-cpp emit-grhsim-execution-plan -j16
python3 scripts/cv32e40p_regfile_compare.py build --output build/cv32e40p/slice-reproduce \
  --reference build/cv32e40p/indexed-concat-v1 --lowering packed_scalar_slices
python3 scripts/cv32e40p_regfile_compare.py attach-verilator --output build/cv32e40p/slice-reproduce
python3 scripts/cv32e40p_regfile_compare.py verify --output build/cv32e40p/slice-reproduce
python3 scripts/cv32e40p_regfile_compare.py measure --output build/cv32e40p/slice-reproduce
python3 scripts/cv32e40p_regfile_compare.py profile --output build/cv32e40p/slice-reproduce
python3 scripts/cv32e40p_regfile_compare.py report --output build/cv32e40p/slice-reproduce

PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
ctest --test-dir build/cv32e40p/tools/grhsim32/wolvrix --output-on-failure \
  -R '^(emit-grhsim-execution-plan|emit-grhsim-cpp-packed-scalar-slices|emit-grhsim-cpp-indexed-concat-slice)$'
```

实现及实验脚本仍在 `thj/cv32e40p-grhsim-investigation-20261114` 工作树，尚未新增提交。

## 产物索引

- [机器报告](../../build/cv32e40p/packed-slices-final/report.json)、[逐轮 CSV](../../build/cv32e40p/packed-slices-final/pairs.csv)、[优化 summary](../../build/cv32e40p/packed-slices-final/summary.json)
- [相同 RTL Verilator summary](../../build/cv32e40p/packed-slices-final/verilator-summary.json)、[原始 RTL Verilator summary](../../build/cv32e40p/packed-slices-final/verilator-original-summary.json)、[测量策略](../../build/cv32e40p/packed-slices-final/measurement-policy.json)
- [构建身份](../../build/cv32e40p/packed-slices-final/build.json)、[功能和 trace](../../build/cv32e40p/packed-slices-final/functional.json)、[冻结 patch](../../build/cv32e40p/packed-slices-final/wolvrix.patch)、[Verilator 身份](../../build/cv32e40p/packed-slices-final/verilator-reference.json)
- [上一版 perf](../../build/cv32e40p/packed-slices-final/grhsim_baseline-perf.txt)、[新版 perf](../../build/cv32e40p/packed-slices-final/grhsim_packed_slices-perf.txt)、[逐行采样](../../build/cv32e40p/packed-slices-final/perf-lines.txt)
- [CTest 日志](../../build/cv32e40p/packed-slices-final/validation/final-tests.log)、[planner 命中](../../build/cv32e40p/packed-slices-final/validation/plan-count.log)
- [XiangShan/CV32 严格源码形态](../../build/cv32e40p/packed-slices-final/validation/contiguous-shapes.json)、[XiangShan 源码身份](../../build/cv32e40p/packed-slices-final/validation/xiangshan-source-identity.json)、[扫描脚本](../../build/cv32e40p/slice-followup/scout_contiguous_slices.py)、[剩余宽读取形态](../../build/cv32e40p/packed-slices-final/validation/wide-read-shapes.json)
- [比较 runner](../../scripts/cv32e40p_regfile_compare.py)、[回归测试](../../wolvrix/tests/emit/test_emit_grhsim_cpp.cpp)
