# ROB 聚合 RTL 提取与 CoreMark 100k 真实激励基准

独立 `Rob` 的 `preserve-aggregate=all` SV 已提取；从保留 NEMU difftest 和断言的 plain Verilator 参考仿真获得 100k 周期 CoreMark 窗口。相同的 100,050 条记录在两个独立模型上全程回放，既定排除项外输出一致。CPU 0 固定单核、各预热一轮、测三轮取最小值：**gsim 11.247 s，GrhSIM 54.148 s，GrhSIM 耗时为 gsim 的 4.814×**。

## 提取结果

目标实例为 `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rob`，顶层 `Rob`，包含全部传递子模块。

| 项目 | 结果 |
|---|---|
| 提取源 | `build/xs/rtl/rtl/` |
| 聚合选项 | `--preserve-aggregate=all`，`build/xs/rtl/time.log` 中生成命令和 exit 0 已检查 |
| FIRRTL 闭包 | 10 模块，`testcase/xs-components/rob/Rob.fir` 266,344,354 字节 |
| SV 闭包 | 12 模块，合计 78,552,054 字节，另附原始 `assert.v` DPI 声明 |
| `Rob.sv` | 70,831,392 字节；正文和宏按原始内容复制 |
| 来源清单 | `testcase/xs-components/rob/manifest.json` |

`Rob.fir` 仅改电路名、去全设计 annotation；供 gsim 使用的 `ptmp/xs-components-rob/Rob_resolved.fir` 另把顶层抽象 Reset 解析为 `UInt<1>`，与 SV 同步复位对应。

关键 SHA256：

```text
source SimTop.fir b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b
extracted Rob.fir 134615d23c864a8c52b3cf9094a50e28101d897628cf00b7550686bb5dbe1a33
aggregate Rob.sv  f153cbdac23a1e673a5ac1e5ca9789a1ac3b70af08487a28db3426045fae5472
```

## 真实激励来源及采样时序

使用已有、通过 NEMU 校验的 plain 参考程序 `build/xs/ref/emu`，本次重新运行 `coremark-2-iteration.bin`，启用完整 FST、commit trace、NEMU difftest 和 RTL 断言。日志正常达到 `cycles=100000 max_cycles=100000`，以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，make 退出 0。共 231,568 条 commit 记录，`instrCnt=238535`，末尾 `cycleCnt=99996`，guest cycle 100,001，host time 300,677 ms。100k 指运行周期窗口，程序未运行到最终 CoreMark 退出。

聚合版整机 Verilator 的独立采集尝试在 `cycleCnt=10269` 触发 `AheadBtbReplacer.sv:124` 的替换路断言，只有 10,322 条记录。最小长度检查拒绝该采集，失败前缀保存在 `trace/rob_trace_aggregate_failed_10322.bin`，未被用于正式回放。相关整机问题已见 `pdocs/grhsim-ir-preserve-aggregate-xiangshan-coremark-investigation-20261018.md`。本次以 plain 参考为激励来源，独立 GrhSIM 仍使用上述聚合 SV，gsim 使用对应 FIRRTL。

FST 中 ROB 路径为：

```text
TOP.SimTop.cpu.l_soc.core_with_l2.core.backend.inner_ctrlBlock.rob.
```

Verilator 在 eval 后 dump，`pack_rob_fst.cpp` 按时间戳分组处理变化：检测到 clock 0→1 时，先输出上一低相稳定状态，再应用同一时间戳的所有变化。因此记录包含时钟沿前的输入和输出，回放无一周期偏移。首个上升沿 raw time 2，最后 raw time 200100，共 **100,050 条记录、52 条 reset**。测试覆盖时钟/数据同时间戳的顺序、跨 u64 的 packed 切片和短 trace 拒绝。

二进制格式为 little endian：

```text
header = magic[8]="RobTrc01", u64 cycles, u32 in_words, u32 out_words
record = u64 flags(bit0=reset), u64 inputs[5245], u64 outputs[5491]
```

每条记录 85,896 字节，总文件 8,593,894,824 字节。输入/输出各叶对应 `layout.json` 中的 `offset`（记录内 u64 索引）、`width`、`words`；`sv_port` / `sv_offset` 表示原聚合 SV 端口和叶最低有效位。例如 `struct {logic [3:0] tag; logic [1:0][4:0] lanes;}` 中，`lanes[0]` 对应 `[4:0]`，`lanes[1]` 对应 `[9:5]`，`tag` 对应 `[13:10]`。

### 输入完整性与参考输出覆盖范围

模型配对 **5,213 个输入叶、5,439 个输出叶**，GrhSIM 未配对输入/输出为 0。FIRRTL 的布尔数组与 GrhSIM packed 整数逐位映射；gsim 优化后收窄的 14 个输入仍在记录和 GrhSIM 中保留完整 SV 位宽，gsim setter 仅保留其实际使用位。

plain RTL 会裁掉不参与计算的聚合字段，也会传播整机常量。输入处理逐项记在 `trace/fst_mapping.json`：

| 输入分类 | 叶数 | 处理及依据 |
|---|---:|---|
| FST 观测 | 1,505 | 从 ROB 实际端口直接读取；包括静态零 `io_hartId` |
| 未使用 | 3,532 | 扫描生成 gsim 的 `step/subStep`，去掉初始化、访问器和禁用日志后，无该字段计算读取；两侧统一驱动零 |
| 整机零常量 | 176 | 下表来源证明；两侧统一驱动零 |
| 未分类活跃输入 | 0 | 任一未分类项或位段越界会使映射失败 |

| 零常量类别 | 叶数 | 来源证据 |
|---|---:|---|
| 入队 `replayInst` | 8 | `Bundles.scala` 的 `EnqRobUop.connectEnqRobUop` 赋 `false.B` |
| 非内存执行单元 debug 字段 | 68 | `ExeUnit.scala` 初始化 debug 为零；无 CSR 来源的 `isPerfCnt` 为 false |
| 未实现写回 data | 8 | plain 参考生成 C++ 的 `debug_exuData` 对应写回分支写常量零 |
| 不支持的 exception 位 | 92 | `fromExuOutput` 对缺少 exception 的执行单元补零；其他有效位从 FST 读取 |

全部 176 个常量还逐条与独立聚合 tap 的 10,322 周期前缀对照，均为零。该前缀仅作为额外证据，不是成功的 100k 采集。

plain FST 保留 **4,274 个输出叶（4,326 个 u64 字）**；另外 1,165 叶在 plain 顶层未保留。`fst_output_mask.bin` 只屏蔽这些叶与参考的比较，模型之间仍按既有规则比较全部输出。扣除下面 1,355 个历史排除叶后，模型间严格比较 **4,084 叶**，其中 **3,289 叶**也逐周期对照真实参考，余下 795 叶只有两个独立模型之间的校验。未将未观测输出填零后当作真实参考。

沿用历史排除范围，单独统计实际失配：

- 17 个 `*_bore` 输出（69 字）：计数器/包装时序约定不同的 difftest 观测口。
- 2 个 `io_storeDebugInfo_*_pc`：9 位动态索引可以超过 352 项数组边界。
- 1,336 个 `io_diffCommits_info` 行 ≥353 的观测叶：gsim 的二次环绕行为与参考不同。

全程校验日志：

```text
[VERIFY] top=Rob mode=trace vectors=100050 status=pass
gsim_vs_grhsim_fail=0 gsim_vs_trace_fail=0 grhsim_vs_trace_fail=0
first_fail=-1,-1,-1
[VERIFY_EXCLUDED] pairing=gsim_vs_grhsim mismatch_ports=669 port_cycles=11711569
[VERIFY_EXCLUDED] pairing=gsim_vs_trace mismatch_ports=493 port_cycles=10817273
[VERIFY_EXCLUDED] pairing=grhsim_vs_trace mismatch_ports=0 port_cycles=0
```

因此严格比较项全过；既定排除项中存在真实的 gsim 失配，不宣称所有输出完全等价。

## 同激励速度比较

AMD Ryzen 9 7950X3D，`taskset -c 0`，clang++ 22.1.2，均 `-O3`、未使用 PGO。gsim 为 `--supernode-max-size=15 --cpp-max-size-KB=8192`，GrhSIM 使用当前 CPU 管线及聚合 SV，未加载旧 scalar checkpoint。正式计时无整机编译等重负载并行运行。

每轮新建模型，从相同复位 trace 重建状态；gsim 内存清零后 placement new，GrhSIM `init()`。gsim 每周期一次 `step()`；GrhSIM 低/高相各一次 `eval()`，在低相后、上升沿前读输出。计时包含输入驱动、模型求值、相同严格输出的 checksum；模型构造和 mmap 打开在计时外。每模型独立 warmup 一轮，测三轮，取最小值，同时保留中位数。

| 模型 | 三轮耗时 ms | min ms | median ms | cycles/s | µs/cycle |
|---|---|---:|---:|---:|---:|
| gsim | 11251.723 / 11246.826 / 11246.878 | 11246.826 | 11246.878 | 8895.84 | 112.412 |
| GrhSIM | 54147.767 / 54174.131 / 54186.861 | 54147.767 | 54174.131 | 1847.72 | 541.207 |

**min 耗时比 4.814×，median 耗时比 4.817×**。全部六轮 checksum 均为 `0x048c94f0d417ffac`，`xs_assert_v2_stub_count=0`。

两侧独立模型剥离断言上报路径，保留条件计算，避免非功能 I/O 主导测量；整机参考的 RTL 断言与 NEMU 保持启用。测量包含两侧各自输入驱动成本，不代表剔除驱动后的纯 eval 比值，也不能直接与整机/旧标量 ROB 的历史速度比混用。

## 复现与文件

```bash
make -C testcase/xs-components rob-extract
make -C testcase/xs-components rob-bench-build rob-trace-layout-check
make -C testcase/xs-components rob-test-scripts
# 需要已有验证通过的 plain 参考 emu，默认 build/xs/ref/emu
make -C testcase/xs-components rob-trace-plain-wave ROB_TRACE_CYCLES=100000
make -C testcase/xs-components rob-trace-plain-pack ROB_TRACE_CYCLES=100000
make -C testcase/xs-components rob-bench-trace \
  ROB_BENCH_VERIFY=100050 ROB_BENCH_REPEAT=3 \
  ROB_BENCH_PREFIX='taskset -c 0 stdbuf -oL -eL'
```

所有日志与临时产物位于 `ptmp/xs-components-rob/`：

- `trace/xs_ref_rob_coremark100k.{fst,log}`：本次真实参考。
- `trace/rob_trace.bin`、`trace/capture_summary.json`：全程驱动和期望输出。
- `trace/fst_mapping.json`、`trace/fst_plan.tsv`、`trace/fst_output_mask.bin`：逐项输入审计、位段计划、参考输出覆盖掩码。
- `trace/plain_reference_sources.sha256`、`trace/fst_sources.sha256`、`trace/replay.sha256`：参考程序/镜像/NEMU、采集/映射来源、回放布局/二进制/掩码的哈希。
- `trace/bench_trace_sources.sha256`：实际测量可执行文件、两侧生成代码、GrhSIM 库、gsim 生成器、FIRRTL/SV 和结果日志的哈希。
- `trace/replay_full_20261022.log`、`bench_trace.log`：100,050 周期校验和六轮计时原始记录。
- `trace/constant_check_20261022.log`、`trace/final_checks_20261022.log`：常量前缀审计、脚本测试和打包检查。

```text
reference emu 9369d7e4f95d913e68801b32b964e43e8817d8e1ea358efaba5f545931a2cfb0
CoreMark image c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e
NEMU 094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e
FST 8a4c231401fb8bc26549d0d0e02e42beab87a395bab28e177d5564934cc1ed02
replay cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1
```

版本：playground `b8e0685`，XiangShan `2193b15d3`，gsim `a3ecb26`，Wolvrix `0627d04` 加工作区原有修改。生成模型和编译库来自本次聚合提取；本任务修复端口映射、采样/打包和基准流程，没有改 Wolvrix 仿真器实现。

最终检查：11 个脚本/打包回归测试通过，聚合 tap 布局检查通过；严格化来源检查后重新打包的 replay SHA256 与正式测量输入相同，复位与周期统计相同；`git diff --check` 通过。
