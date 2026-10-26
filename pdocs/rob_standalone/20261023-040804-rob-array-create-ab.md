# ROB arrayCreate 实施与同 trace A/B 验收

2026-10-23，stage-08 已实施，工作树未提交。真实 CoreMark 100050 周期回放中，GrhSIM 最小耗时由 **54.228 s 降至 45.683 s，降低 15.76%，加速 1.187×**；中位数降低 15.69%。新旧 GrhSIM 每周期全部 5491 个输出字逐字节一致，无排除。

同条件 gsim 为 10.906 s，新 GrhSIM 耗时仍是其 4.189×。本次消除了目标字段的数组构造经巨型整数打包后再拆分的问题，没有改变 exceptionVec 的端口存储，也不代表 S7 整机验收完成。[后续全量 C++ 审计](20261023-rob-array-roundtrip-audit.md) 仍发现内部 assign、整数组写入重新分组、切片和二维 replicate/concat 等路径有剩余数组往返。

## 实现与输入范围

计划位于 [stage-08-array-create.md](../grh-ir-array-support/stage-08-array-create.md)。实现增加 GRH `kArrayCreate` / `Graph::createArray` 与 GrhSIM `core.compute.arrayCreate` / `GrhSimModel::addArrayCreate`，并贯通 ingest、转换、优化、持久化、SV 发射和 CPU 消费路径。

每个操作数是完整同型 Logic 值，总宽 W、shape S；N 个元素产生总宽 N×W、shape `[N]+S`，`result[i]=operand[i]`。例如 `arrayCreate(8'h11,8'h22)` 的扁平位图是 `16'h2211`。多维构造添加外维，singleton 保留 `[1]`；verifier 独立核验几何、signedness、domain 与溢出。

CPU 向已有 local/frame/boundary/state/output 缓冲区逐项写入。兼容的数组来源直接按行读取，需要真实扁平运算的分支才打包。状态写先保存源快照，保留 enable、mask、变化检测、reader 激活和原有写优先级。没有大型按值返回 `std::array` helper。

此次 ROB 验收使用 [原始提取报告](rob-aggregate-coremark100k-20261022.md) 固定的输入：

- `testcase/xs-components/rob/rtl/` 的 `preserve-aggregate=all` SV，包含完整子模块闭包；候选重新 ingest，未 resume 旧 GRH/GrhSIM checkpoint。
- `ptmp/xs-components-rob/trace/rob_trace.bin`，共 100050 条记录、52 条 reset，来自 plain Verilator 整机真实 CoreMark 的 100k 周期窗口；不是程序运行到退出。每周期 5245 个输入字、5491 个输出字。
- 基线保存在 `ptmp/xs-components-rob/`；候选、比较结果和 perf 记录另存 `ptmp/xs-components-rob-array-create/`。

关键 SHA256：

```text
Rob.sv        f153cbdac23a1e673a5ac1e5ca9789a1ac3b70af08487a28db3426045fae5472
RenameBuffer  09b04a4e7d0d7b6bc9273e7adb1865707ea1877d9d087b79863479d575c9d888
manifest      2ed19164d258e40044024df082e9817aa1691a20a8a27aa3eb897974cd92d737
trace         cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1
old binary    70eebd9a99cff646a6335a777a6b123ce90f117e2e59a12d3e357741a58500c0
new binary    7bba7a8056764b758d368fac1b7be28e10a15a05caec3c26e0cc761acb7ba771
bench C++     109243a5acc7c1f921a714d89eabf641eb40f725a1448018f4965a49fd4cc29b
```

新旧 `rob_bench.cpp` 内容哈希相同。完整 RTL 清单、布局、参考掩码、候选 IR 和目标 C++ 的哈希见 [audit.json](../../ptmp/xs-components-rob-array-create/evidence/audit.json) 与 [inputs.json](../../ptmp/xs-components-rob-array-create/inputs.json)。A/B 结束时重新校验原始 binary 和 trace 的哈希。

## 正确性

两版 GrhSIM 各自重放完整 trace，每周期低相求值后、上升沿前采集所有输出，随后执行高相求值。两份 dump 各有 549374550 个 u64 数据字，包含原 gsim 严格比较排除的观测输出；全文件逐字节相同：

```text
cycles=100050 words_per_cycle=5491 exclusions=0 equal=true
SHA256=688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1
```

另外重跑原有 gsim / GrhSIM / trace 严格校验，覆盖全部 100050 周期：

```text
gsim_vs_grhsim_fail=0 gsim_vs_trace_fail=0 grhsim_vs_trace_fail=0
reference_words=4326 model_compared_words=5491
```

历史排除范围保持不变：17 个 bore 输出（69 字）、2 个 OOB debug pc、1336 个 diffCommits 观测叶。排除项的实际差异仍为 gsim-vs-GrhSIM 669 ports / 11711569 port-cycles，gsim-vs-trace 493 / 10817273，GrhSIM-vs-trace 0。因此不能把三方严格校验描述成“所有输出都与 gsim 相同”。新旧 GrhSIM 的全输出对照则没有这些排除。

日志与二进制 dump 位于实验目录的 `baseline/`、`candidate/`；[verify_trace.log](../../ptmp/xs-components-rob-array-create/candidate/verify_trace.log) 末尾额外的 vectors=1 用时不属于正式速度结果。

## IR、C++ 和机器码

最终 flat GRH 有 **813 个 kArrayCreate**。在原始 `RenameBuffer.sv:47099` 的字段组装处直接产生：

| 字段 | GRH op | 操作数数目 | 最终 GrhSIM value / op | 结果类型 |
| --- | --- | --- | --- | --- |
| pdest | `_op_2555929` | 520 | v672801 / op705901 | width=4160, shape=[520]，元素 8 bit |
| rfWen | `_op_2555931` | 520 | v672802 / op705902 | width=520, shape=[520]，元素 1 bit |
| fpWen | `_op_2555933` | 520 | v672803 / op705903 | width=520, shape=[520]，元素 1 bit |

最终 GrhSIM 共 **373 个 arrayCreate**，三个目标输出都直接消费 arrayCreate，没有 concat/flat assign 中间生产者。

实际接通还需要两项修复：canonicalize 沿无损 assign 链继续寻找最深的完整同型数组，只重接数组输出分支；used-bits 对 arrayCreate 和 assign 视图追踪存活，使失去消费者的数组包装和扁平生产者可删除。只改最后的输出 store 会把巨型 concat 留在上游，不满足验收。

生成 C++ 的实际字段 store 位于 `candidate/grhsim-model/grhsim_Rob_tu358.cpp:3102`、`:3637`、`:4172`，结构如下：

```cpp
std::array<std::uint8_t, 520> rows;
rows[0] = sampled0;
// ... 同一次采样值写入其余元素，实际名称为 cpu_v672801 等。
for (std::size_t j = 0; j < 520; ++j) output[j] = rows[j];
```

三个目标函数均无 `_BitInt` 表达式。旧布尔数组逻辑总宽是 520，但后端存储按字舍入，实际 C++ 使用 `_BitInt(576)`；不能仅搜索字面 `_BitInt(520)` 判断是否仍在打包。候选中其他真实宽位运算仍可使用 `_BitInt(576)`。

按字段定位新旧机器码，不依赖 helper 编号保持不变：

| 对应代码 | 静态代码字节 | 静态指令数 | 入口 `sub ..., %rsp` 字节 |
| --- | --- | --- | --- |
| 旧 pOutput_c64：三个字段 | 77537 | 10647 | 41624 |
| 新 pOutput_c64：pdest | 835 | 127 | 152 |
| 新 pOutput_c65：rfWen | 835 | 127 | 152 |
| 新 pOutput_c66：fpWen | 835 | 127 | 152 |

新三函数代码合计 2505 字节，较旧函数减少 96.77%。入口减栈量是反汇编可见的指令值，不含 push/red-zone，不能当作完整栈深度。它与 C++/IR 证据共同确认原有大打包临时值和拆分循环消失。

反汇编已归档在实验目录 `evidence/{baseline,candidate}/pOutput_c*.asm`；审计脚本同时检查符号确实存在且提取到非空指令。

## 正式速度 A/B

AMD Ryzen 9 7950X3D，CPU 0，Clang 22.1.2，`-O3`，无 PGO、无计时插桩。每侧一次完整预热、三次完整测量。正式计时没有并行编译或其他重负载。gsim 使用保留的旧 binary 的 gsim 分支。

计时规则与原基线相同：每轮新建模型，gsim 每周期 step 一次，GrhSIM 每周期低/高相各 eval 一次；包含同一驱动和 checksum，模型构造、mmap 打开在计时外。这是完整回放耗时。

| 模型 | 三轮耗时 ms | min ms | median ms |
| --- | --- | --- | --- |
| gsim | 10905.952 / 10920.645 / 10919.735 | 10905.952 | 10919.735 |
| GrhSIM 旧 | 54227.731 / 54230.259 / 54248.984 | 54227.731 | 54230.259 |
| GrhSIM 新 | 45727.162 / 45720.394 / 45683.073 | 45683.073 | 45720.394 |

九个测量轮的 checksum 全为 `0x048c94f0d417ffac`。最小耗时减少 8544.658 ms（15.76%），中位数减少 8509.865 ms（15.69%）；改善远大于轮间波动。同次复测的 GrhSIM/gsim 最小耗时比由 4.972× 降至 4.189×。不要把原报告不同批次的 4.814× 当成本次旧侧值。

原始结果见 [results.json](../../ptmp/xs-components-rob-array-create/results.json)，每轮记录见 `baseline/gsim.log`、`baseline/grhsim_old.log`、`candidate/grhsim_new.log`。

## perf 解释与测量边界

另用同 binary / trace、CPU 0、`cycles:u`、997 Hz，预热一轮并测一轮；采样覆盖两轮，与旧采样口径相同。新样本 90882 个、旧样本 109790 个，均报告 lost=0，按 period 权重计算独占占比：

| 区域 | 旧 | 新 |
| --- | --- | --- |
| 对应三个字段的完整输出函数 | 10.4072% | 合计 0.0187%（17 个样本） |
| 全部 pOutput 函数 | 17.8051% | 1.8384% |

新三个函数样本少，0.0187% 的精确值有较大相对不确定性；数量级下降与机器码结果相符。新最大单符号是 `pLargeSink_c0`，占 5.66%，其余成本仍主要分散在计算和调度中。采样轮用时只作诊断，不替换正式三轮计时。

本次净收益覆盖整条候选数组管线，不能全部归到一条 concat 或旧 pOutput_c64。比较的是固定旧 binary 和当前工作树重新生成的候选；当前工作树包含既有修改，没有做 commit 级单因素消融，也没有据此推断整机加速比。具体结构证据证明目标字段的数组往返已被消除。

## 回归、兼容性与复现

| Makefile 门禁 | 结果 / 日志（`ptmp/array-create-20261023/`） |
| --- | --- |
| `test_wolvrix` | 67/67，94.27 s，`full-final-tests2.log` |
| `run_xs_bugcase_grhsim` | 27/27，`xs-bugcases.log` |
| `test_array_create`、`test_ingest_struct_array_write` | 类型/负例/顺序/四态/roundtrip/原始 SV ingest 全过，`array-order-tests.log` |
| `test_array_create_cpu` | 四种小/大数组状态与 frame/boundary 模型执行、UBSan 全过，`array-final-targeted4.log` |
| `run_all_hdlbits_grhsim_ir_tests` | 162/162，`hdlbits-and-golden.log` |
| `check_sim_refactor_baseline` | 162/162 黄金 trace 相同，同上 |
| `rob-array-create-run` | 全输出零排除比较、三方既定严格校验、正式三轮 A/B 全过，`rob-ab.log` |
| `rob-array-create-profile`、`rob-array-create-audit` | perf / IR / C++ / 机器码证据通过，`rob-profile.log`、`rob-audit-final.log` |

测试还覆盖非对称 `11/22/33/44` 顺序、packed 升降序、unpacked/nested pattern、singleton、多索引/OOB、masked 与重叠状态写、flat/shaped 混合消费者、跨 helper/TU 及重复引用的随机值只采样一次。

GrhSIM JSON 容器保留 `wolvrix.grhsim.v3`，core 指纹升级为 `wolvrix.grhsim.core.v3`；旧 core.v2 checkpoint 明确拒绝，需重生。四态 arrayCreate 在 IR 中合法且折叠保留 X/Z，CPU 对四态 aggregate 继续明确报不支持。

从仓库根目录通过 Makefile 复现，编译器使用上述版本：

```sh
WOLF_ENV_SOURCED=1 make py_install PYTHON="$PWD/.venv/bin/python"
make -C testcase/xs-components rob-array-create-ab CXX=/home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin/clang++
make -C testcase/xs-components rob-array-create-profile
make -C testcase/xs-components rob-array-create-audit
```

`rob-array-create-build` 强制从 SV 重生候选；`rob-array-create-run` 可重放已有候选。原始基线与 trace 的硬编码哈希用于拒绝意外替换输入，换实验基线时应明确更新该约定。

本次实施前的工作树快照和原始哈希位于 `ptmp/array-create-20261023/{playground.before.patch,wolvrix.before.patch,wolvrix.before.status,baseline.sha256}`。起始 HEAD 分别是 playground `b8e0685f13366327d6f5a134e4d78e05bab9d6c8`、wolvrix `0627d04637123953af1bfd0dd8997364da341773`；改动尚未提交或合入。
