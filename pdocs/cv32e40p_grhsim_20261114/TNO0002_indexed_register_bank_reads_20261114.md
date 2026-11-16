# TNO0002：Wolvrix 寄存器堆动态读取，消除全量 concat

## 结果

在 TNO0001 冻结的 CV32E40P/CoreMark 上，Wolvrix 新增通用 `indexed_concat_slice` lowering，两个整数寄存器堆读端口不再每次装配整个 1024-bit concat。**8 对 AB/BA 全部更快，walltime 减少 11.9168%，95% paired bootstrap CI [11.8084%, 12.0187%]。**

| 指标 | 冻结旧 GrhSIM | 新 GrhSIM | 新 / 旧 |
| --- | ---: | ---: | ---: |
| 进程 walltime | 9.112463 s | 8.026557 s | 0.880832，CI [0.879813, 0.881916] |
| 仿真循环 | 9.078685 s | 7.991772 s | 0.880277，CI [0.879005, 0.881515] |
| 初始化及复位 | 0.007624 s | 0.007441 s | 0.976727 |
| 仿真吞吐 | 371,867 cycles/s | 422,443 cycles/s | 约 +13.60% |

同一组 node030 CPU96、NUMA1、ASLR disabled、单线程、Clang 23.1.2 O3/native。两侧各预热一次，8 对 AB/BA，各样本完整运行十迭代 CoreMark；无样本剔除、无重试、无 placement 拒绝，16 个样本的 CPU288 sibling 均记录为 100% idle。没有参数搜索或运行后挑选候选。

这修复的是寄存器堆读路径的全量拼装开销。逐 bit producer 更新、变化检测与活动传播仍在；没有恢复上游数组形态，也没有宣称 GrhSIM 已追平 Verilator。本轮没有重新运行 Verilator 性能对照，不能把跨轮数据合成为新的配对 CI。

## 实现与证明边界

实现位于 [grhsim_cpp.cpp](../../wolvrix/lib/emit/grhsim_cpp.cpp)，功能说明见 [indexed concat slices](../../wolvrix/docs/emit/grhsim-indexed-concat-slices.md)。`indexed_concat_slice` 默认为开启，可通过同名 emit attribute 或 `WOLVRIX_GRHSIM_INDEXED_CONCAT_SLICE=0` 关闭；与 scalar concat reduction 父规则独立。

匹配完全依据 IR：至少 256-bit 的局部 concat，各 operand 为 1–64-bit scalar，唯一完整用途是同 compute supernode 中稍后的 1–64-bit `kSliceDynamic`。不依赖模块名、寄存器名、profile、CV32 参数或运行结果。

生成一个本地 word-reader，运行时只执行被选择的 64-bit word 分支；跨 word 时最多执行两支，再移位和截断。CV32 的 32-bit 寄存器地址是 32 的倍数，因此每次只需一个 64-bit word，代替原来的全部 16 个 word。这个 word 最多包含两个相邻寄存器，未宣称已经恢复直接 `mem[index]`。

保持语义的限制：

- concat 不能是持久值、输出、event、需要 change tracking 的值或已有 packed-array 特殊表示。
- 完整 use 集只能有一个局部动态 slice；跨 supernode、多用户和其它消费方式走旧路径。
- concat 到 slice 之间不能有副作用、event 生产、不支持的操作或对捕获物理 value slot 的写入；检查包含 canonical alias 和实际 slot 复用。
- 局部 scalar 输入固定在原定义处形成快照；slice 结果也固定在原执行点，避免延迟到后续写入之后。direct state view 保守回退。
- 保留现有索引越界、宽索引高位检查和零填充；未对齐切片正确合并，避免 shift-by-64 UB。
- IR、activity schedule、commit 和 fixed-point loop 均未修改；execution planner 同步记录新 lowering 形态。

## 同源性及功能验证

基线是 TNO0001 的 Wolvrix `74d80cf` binary，SHA256：

```text
old 061650cf561b78846b11de0e81713518bb1fd0083f2ff90c901fe13523003ca0
new 4e817973c5b39392fa5ae5b4e943f2f6bc8fff0fedb7d61fcbd2d715de30d007
```

新模型直接从同一个 [graph.json](../../build/cv32e40p/run2/graph.json) 重放 activity schedule 和 emitter；没有重新运行 frontend、sv2v/Yosys、分区或编译 CoreMark。生成后的 `normalized.json` 与冻结版 SHA 相同。用新 emitter 显式关闭开关后，所有生成 `.cpp` 与旧版逐文件相同。开启后只有 `sched_5.cpp` 与 `sched_21.cpp` 改变，命中原先定位的 Value 41661/41662；各减少 106,876 bytes C++。这验证了实际差异仅在两个寄存器堆读取位置。

两侧均重新通过：

- smoke：253 cycles，`SMOKE PASS`，逐周期 trace SHA 完全相同。
- 完整 CoreMark：3,376,065 cycles、exit 0、UART 相同；seed/list/matrix/state/final CRC 为 e9f5/e714/1fd7/8e3a/fcaf。
- 完整 instruction/data bus trace 与旧 GrhSIM、原始/转换后 Verilator 的已归档 trace 相同：`ed2b490886767aa74524a6dd15e708e8f2b231bc3886814af0ba4d1919b3e098`。
- 每次正式样本继续检查 workload signature、CPU/线程/NUMA/ASLR。性能样本不写 trace。

## perf 归因

各侧额外各一次 `perf stat`、一次 cycles 采样，不计入上述 walltime 统计；PMU running fraction 均为 100%，采样 lost samples 均为 0。PMU 计数包含初始化和退出，表中除以 guest cycles 作归一化。

| 每模拟周期指标 | 旧版 | 新版 |
| --- | ---: | ---: |
| Host instructions | 24,925.47 | 22,344.76 |
| Host cycles | 8,412.42 | 7,419.11 |
| Branches | 855.62 | 838.51 |
| Branch misses | 1.599 | 2.110 |
| IPC | 2.963 | 3.012 |

指令量减少 **10.3537%**，与 11.97% 的仿真循环时间下降相符。新 switch 使 branch misses 小幅增加，但未抵消少做整组 pack 的收益。

batch 5 采样占比从 17.13% 降至 10.40%，其 outlined word-reader 另占 0.57%；batch 21 从 8.72% 降至 2.50%，word-reader 另占 0.88%。相关函数合计由 25.85% 降至 14.35%。这些是采样比例，并非该模式的精确独占耗时；没有把两个 batch 的全部开销归因于寄存器堆。

`.text` 从 207,991 到 208,871 bytes，`.rodata` 仍为 33,579,840 bytes。收益来自执行工作减少，并非 executable 体积缩小或 RAM 初始化变化。新模型 emit/compile/link 分别为 2.52/18.85/1.21 s；这些构建时间与性能样本分开记录，不与历史不同缓存条件下的构建时间作提速结论。

## 回归和复现

新增 focused emitter 回归：独立逐 bit oracle、1024 Boolean operands、混合 signed 字段及 padding、1/7/32/63/64-bit 输出、未对齐/partial/out-of-range、129-bit index、固定 index 改变数据、local snapshot、默认/显式/环境优先级和 split helper。负例覆盖全宽输出、多用户、跨 scope、副作用、宽字段和小 concat。

另含有时钟、写使能、选址写入、两个读口、x0、无新边沿重复 eval、重复 init 的八个条目的寄存器堆模型。开启/关闭/split 三种模型各在 Clang 23 O0/O3 下通过 ASan/UBSan。现有 `wide-concat-reduction` 与 `packed-array-late-index` 两项 CTest 通过；4 项 Python 回归验证原比较倍率、新旧倍率方向、CRC gate 与输出解析；`py_compile`、两仓 `git diff --check` 通过。

在已有冻结基线的工作区中复现，输出目录必须是新的目录：

```bash
# 在 node030，项目根目录
cmake --build build/cv32e40p/tools --target cv32e40p_emit emit-grhsim-cpp -j16
python3 scripts/cv32e40p_regfile_compare.py build --output build/cv32e40p/indexed-concat-reproduce
python3 scripts/cv32e40p_regfile_compare.py verify --output build/cv32e40p/indexed-concat-reproduce
python3 scripts/cv32e40p_regfile_compare.py measure --output build/cv32e40p/indexed-concat-reproduce
python3 scripts/cv32e40p_regfile_compare.py profile --output build/cv32e40p/indexed-concat-reproduce
python3 scripts/cv32e40p_regfile_compare.py report --output build/cv32e40p/indexed-concat-reproduce

PATH=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin:$PATH \
ctest --test-dir build/cv32e40p/tools/grhsim32/wolvrix --output-on-failure \
  -R '^emit-grhsim-cpp-indexed-concat-slice$'
```

记录中的生产 emitter diff 与实际构建时冻结的 patch 已核对一致；后续仅增加测试和文档，没有调整候选实现。当前改动位于 `thj/cv32e40p-grhsim-investigation-20261114` 工作树，尚未新增提交。

产物索引：

- [机器报告](../../build/cv32e40p/indexed-concat-v1/report.json)、[逐对 CSV](../../build/cv32e40p/indexed-concat-v1/pairs.csv)、[summary](../../build/cv32e40p/indexed-concat-v1/summary.json)、[measurement policy](../../build/cv32e40p/indexed-concat-v1/measurement-policy.json)
- [构建身份与命中](../../build/cv32e40p/indexed-concat-v1/build.json)、[功能与 trace](../../build/cv32e40p/indexed-concat-v1/functional.json)、[冻结 patch](../../build/cv32e40p/indexed-concat-v1/wolvrix.patch)
- [旧版 perf](../../build/cv32e40p/indexed-concat-v1/grhsim_baseline-perf.txt)、[新版 perf](../../build/cv32e40p/indexed-concat-v1/grhsim_indexed-perf.txt)、[旧版 PMU](../../build/cv32e40p/indexed-concat-v1/grhsim_baseline-stat.csv)、[新版 PMU](../../build/cv32e40p/indexed-concat-v1/grhsim_indexed-stat.csv)
- [focused/stateful 测试日志](../../build/cv32e40p/indexed-concat-v1/validation/indexed-concat-state-test.log)、[现有 CTest](../../build/cv32e40p/indexed-concat-v1/validation/indexed-concat-existing-tests.log)、[源版本核对](../../build/cv32e40p/indexed-concat-v1/validation/source-review.json)
- [复现实验脚本](../../scripts/cv32e40p_regfile_compare.py)、[回归测试](../../wolvrix/tests/emit/test_emit_grhsim_cpp.cpp)
