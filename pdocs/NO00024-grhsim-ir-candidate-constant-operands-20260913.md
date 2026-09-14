# NO00024：在使用点特化不可变标量操作数

- Node：`sparse_execution_20260913_01`。
- 最终阶段：`ACCEPTED`。六次交替中新均值 **58.417667 s**、旧均值 **60.347333 s**，
  降低 **3.197601%**；三次新结果全部快于三次旧结果，U=0、单侧精确 p=0.05。
  完整生成 **595.01 s**、fresh 编译 **229.70 s**，全部 50k NEMU 及聚焦回归通过。
- 根基线 `6e66aef`；子模块基线 `abefd39`（NO00023）。节点开始工作区干净。
- 保留实现的最终子模块 commit：`8b5675de1a1c3e21338cf2b73cbf3fbdbf166b3c`
  （`perf(grhsim): specialize immutable scalar operands`）。仅在全部验收完成后提交；
  根仓库本次归档提交同时保存该指针、本报告、goal 当前基线和报告索引。

## IDEA 与证据计划

NO00023 最新相位 compute 38.935131 s（66.01%）、commit 18.505281 s（31.37%），
publication 1.468784 s，evals/rounds 100102/201258。先刷新当前构建的平坦动态
热点，结合生成代码的依赖和活动粒度，选择减少被激活任务内实际求值次数的机制。
具体假设、覆盖、收益上界和证伪标准在实现前补齐。不重复已否定的结果转发、bool
包装、通知分支/汇聚或仅 identity 删减。

## BASELINE 与预注册

- 复用 NO00023 `flow-cse-final` 的完整生成/fresh 编译对照；emu SHA-256
  `ac556d5f6c70eaff644e59c624d0f594a0bc5e7a7ead1e0ffb9b7241b71f8e2e`。
- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`、SimTop、DIFFTEST/NEMU。
  CoreMark SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 50,000 cycles、CPU 2、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`，waveform、commit/RAM
  trace 关闭；编译使用 32 jobs。冻结 RTL、GRH、GRH pass 不变，不按模块名触发。
- 运行前固定 NO00023 正式均值 60.645667 s 为止损参考，仿真截止为 **90.969 s**
  （1.5 倍、毫秒取整）。完整生成与编译各预装 1800 s 进程树 KILL，计时从 Make
  启动开始；超时即否定该次尝试并隔离不完整 flow。恢复 flat IR 仅供筛选。
- 正式六次预注册顺序 `old1/new1/old2/new2/old3/new3`，同窗口串行，期间不构建。
  Host 为主指标，同时保留 emu 墙钟、退出和等价性；记录均值、样本标准差、
  效应量、Mann–Whitney U 与单侧精确 p。必须 `max(new)<min(old)` 才可接受；
  全部有效样本保留，INVALID 记录后补跑。诊断与筛选不进入正式统计。
- 精确 50k 终点要求 73580 instructions、cycleCnt 49996、PC `0x80001312`、guest
  cycles 50001；非零、断言、mismatch 或输入不符均 INVALID，确认失败即停止。
- gsim 配置不变，复用归档 20.640 s，不重跑。
- 临时命令、日志和产物均在 `ptmp/no00024_sparse_execution_20260913_01/`。
- 本节点须取得真实收益、通过完整门槛后集中提交；单次失败继续在本节点修正。

## IDEA：不可变操作数在使用点特化

当前对照刷新采样 `no00024_baseline_profile`：Host **59.797 s**，11963 samples
（200 Hz），compute tasks **60.469782%**、commit tasks **24.366798%**、evaluator
**3.076151%**、main-other **9.378918%**、external **2.516091%**，compute 热点分散
在 **2273** 个 task。终止符、mapping、ELF、符号边界、任务覆盖和采样总数检查通过；
50k 精确 NEMU 终点通过。采样仅作诊断，不进入正式性能统计。

生成代码把 numeric constant 放入 boundary/local arena，消费者仍动态读取。例如
`mux(enable, state, zero)` 的 zero 是 boundary load，写端口的 constant-1 enable
与全位 mask 也动态读取；纯计算 CSE 共享定义，但尚未把不可变性暴露给 C++ 编译器。
候选在 emitter 建立单结果 `core.compute.constant` 的标量 literal 表，使用点引用
按原语义类型规范化的 literal，不再发射常量写回与变化通知。编译器据此折叠常量
分支、掩码和相关求值。创新点是利用跨任务不可变语义减少实际执行，区别于此前被
否定的动态结果局部转发；不增加缓存、逐值比较或运行时分支。

首版覆盖两态 logic 1–64 bit，复用原 literal 的截断、符号扩展和 X/Z 投影规则；
wide、real 和动态值沿用现有路径，不改变 helper ABI。常量无副作用、恰有一个
定义；所有 compute unit、commit domain 和端口活动位在 init 时已激活，首轮使用
得到定义后的同一值，之后没有常量变化需要通知。保持 IR、分区、布局和任务顺序，
只移除不再需要的常量物化。测试须覆盖 signed 1/5/64 bit、无符号边界、跨任务及
helper、首次 eval/reinit、constant event、state masked write、DPI inout 初值。

预期 Host 降低 **5–20%**；保守总上界受 compute+commit 约 85% 平坦采样约束，
静态覆盖仅表示机会而非动态收益。若消费者本来已被编译器折叠、代码膨胀抵消
收益、等价失败或时间门槛失败，则否定该次尝试，在同一节点继续修正。

## IMPLEMENTED：标量常量使用点替换

实现仅改变 CPU emitter：收集规范化 scalar literal，`value()` 在使用点引用，
常量 producer 不再生成赋值或加入 changed-group；其余读写、活动通知、history
和 helper ABI 均沿用原路径。原 emitter suite **55.42 s** 通过；新增 scoreboard
后 emitter suite **62.52 s**，schedule **0.01 s**、IR/mapping 各 **0.01 s** 通过。
两种分区/helper 配置各验证 **32768 eval / 4 init**，覆盖 signed 1/5/64 bit、
unsigned 1/5/64 bit、X/Z 投影、类型截断、算术溢出、常量边沿仅首轮触发、掩码
写入、DPI inout 使用独立可写副本及重复 eval；ASan/UBSan 开启。既有 Verilator
差分、宽值、初始化、多时钟及共享 history 回归也通过。

筛选模型恢复冻结 flat GRH：Make 墙钟 **107.64 s**（内部 92.720 s），exit 0，
1800 s 截止未触发；恢复时间不代替完整 SV 门槛。独立 fresh C++ 编译 **234.19 s**，
exit 0，1800 s 截止未触发。旧/新 ELF text **129732600 / 120437197 bytes**，减少
9295403 bytes（约 7.17%）；源代码 literal 展开使部分 task 文本反而增大，text
减少仍不能代替动态性能证据。

从完整对照 GrhSIM JSON 按 op/type/operand 检查得到 **13814** 个两态 1–64 bit
常量、**1271104** 个常量操作数引用，涉及 **1123496** 个消费者。主要消费者：
366642 mux（382759 引用）、192079 regWrite（260339 引用）、176381 concat
（199751 引用）、137447 eq、77904 sliceDynamic、33750 memWrite（71278 引用）、
28893 add、28181 memRead。regWrite/latchWrite 的位置分布为 enable **67603**、
mask **192348**、data **800**。这解释了不可变语义的跨任务覆盖；不把引用次数
等同于执行次数。首次分析脚本误把 JSON domain `2-state` 写为 `two_state`，
其“零覆盖”被内置检查拒绝，修正拼写后重新分析；没有重复仿真。

相邻筛选 old Host/emu 墙钟 **60.822/60.85 s**、new **59.141/59.17 s**，降低
**2.763803%**，两次 Make/emu exit 均 0/0、精确 50k NEMU 终点均 PASS。
效果低于初始预期带，说明
大量静态引用未等量转化为动态节省；单对不作接受依据。冻结 emitter SHA-256
`4f45e735f5a526c2f389f9002db59b0933a14041520f51451f50b829801f454a`，启动独立
fresh flow 的完整 SV→C++ 生成、编译和预注册六次交替。

筛选源文件比较：5193 个 C++/header/Makefile 文件中只改变 **4639 个 task**，
主 evaluator、runtime/header、init 和 Makefile 均逐字节相同。C++ 总文本
1234524407→1238337396 bytes（+0.31%），但 boundary accessor 文本引用
6931955→5365802（−1566153）、local accessor 6157209→6144786，object accessor
1472896 不变。这些是源码引用（含读写及条件），不是动态 load 指令计数。
两个示例 native 符号大小：compute task 4507 为 92016→86392 bytes；commit
task 4576 为 383118→330876 bytes，显示编译期折叠减少了两相位的本体代码。
GrhSIM checkpoint 的 operation/value/type/init/mapping 数组相同；string 池中的
内部 event 命名有不同，不能声称整个 GrhSIM JSON 逐字节相同。完整流程另行
核验冻结 flat GRH 和正式/筛选生成代码，结果见下。

## VALIDATION：完整生成

`no00024_constants_full_generate` Make 总墙钟 **595.01 s**（内部 **589.419 s**），
exit 0，1800 s 截止未触发。启动 2026-09-14 00:14:25（UTC+08:00），完整模型
Makefile 最后生成于 00:24:03.857620462；595.01 s 还包含后续 GrhSIM checkpoint
round-trip，为目标 C++ 生成边界的保守上界。前端 simplify 274.405 s，与对照
277.448 s 接近。flat GRH 与冻结 NO00023 **逐字节相同**，XiangShan 工作区干净。
正式与筛选的 **5193** 个 C++、header 和 Makefile **全部逐字节相同**，正式目录
从零生成并独立启动 fresh 32-job 编译，没有复制筛选二进制。

`no00024_constants_full_build` fresh 32-job 编译墙钟 **229.70 s**，exit 0，1800 s
截止未触发；模型 C++ flags 仍为 `-std=c++20 -O3`，新旧 ELF 编译器均 clang
22.1.2。正式 emu SHA-256
`13a7006af3c842128770c08dc43fba624b6b48066a73faeba57c1d535bdd45f2`，text
120437197 bytes，与筛选构建一致。对照 SHA-256 与冻结值相同。
正式六次按预注册顺序启动，期间不构建或运行其他仿真。

## VALIDATED：正式六次交替

2026-09-14，UTC+08:00；RUN_ID 前缀 `no00024_constants_`，按旧/新连续三对。
六次连续完成，期间无构建和其他仿真；全部有效，未补跑、剔除或选择样本。

| 后缀 | 启动 | Host s | emu 墙钟 s | Make/emu 退出 | 等价性 |
|---|---|---:|---:|---|---|
| old1 | 00:29:03 | 60.902 | 60.93 | 0/0 | PASS |
| new1 | 00:30:04 | 58.700 | 58.73 | 0/0 | PASS |
| old2 | 00:31:02 | 60.687 | 60.72 | 0/0 | PASS |
| new2 | 00:32:03 | 58.782 | 58.81 | 0/0 | PASS |
| old3 | 00:33:02 | 59.453 | 59.48 | 0/0 | PASS |
| new3 | 00:34:01 | 57.771 | 57.80 | 0/0 | PASS |

窗口结束 00:34:59。全部六次均启用 DIFFTEST/NEMU，73580 instructions、cycleCnt
49996、末端 PC `0x80001312`、guest cycles 50001；没有 crash、assertion 或 mismatch，
没有触发 90.969 s 止损线。Host 是预注册主指标，emu 墙钟只覆盖 emu 进程区间。

| Host 统计量 | old | new |
|---|---:|---:|
| 均值 s | 60.347333 | 58.417667 |
| 样本标准差 s（n−1） | 0.781940 | 0.561529 |
| 最小值 s | 59.453 | 57.771 |
| 最大值 s | 60.902 | 58.782 |

平均节省 **1.929667 s**，`(old_mean-new_mean)/old_mean` 为 **3.197601%**。
合并样本标准差采用 `sqrt((sd_old²+sd_new²)/2)`，old−new Cohen's d 为
**2.834766**。`max(new)=58.782 < min(old)=59.453`，间隔 **0.671 s**；
Mann–Whitney U_new=0，枚举 6 选 3 的 20 种标签分配，改善方向单侧精确
**p=1/20=0.05**，满足预注册秩次判据。三对分别节省 2.202 / 1.905 / 1.682 s，
均为正。第三对新旧都更快，显示机器状态在窗口内变化，已完整保留；没有用
历史均值、诊断或筛选样本填补正式控制。n=3+3 的小样本结论限于规定的门槛，
不外推为任意主机/负载上的相同收益幅度。

实际收益低于初始 5–20% 预期带，幅度预测未获支持；核心机制的正收益由同期
全秩分离支持。代码变化只暴露常量不可变性，静态百万引用可能包括冷路径和
编译器本来已能折叠的 local 值；没有动态逐指令计数，不能把全部时间差进一步分摊到某类
运算。这不影响已通过的正确性、时间和统计门槛。

## 最终相位与范围

六次正式样本结束后，独立 `no00024_constants_final_phase` 于 00:35:24–00:36:22
运行，Host **57.928 s**、emu 墙钟 **57.96 s**、Make/emu exit 0/0，精确 50k
NEMU 终点 PASS。仅开启 `EMU_RUNTIME_PROFILE=1`，其余运行参数、CPU 2 和
90.969 s 截止保持一致；该诊断不进入上述六次统计。

| 相位 | s | eval 时间占比 |
|---|---:|---:|
| compute | 41.433633 | 71.734020% |
| commit | 14.684130 | 25.422624% |
| publication | 1.565766 | 2.710809% |
| eval 总计 | 57.760088 | 100% |

仍为 **100102 evals / 201258 rounds**，轮次结构未改变。残余热点已更偏向
compute；与 NO00023 旧相位来自不同窗口，不能直接相减作为分相位收益证据。
当前 phase 比正式均值快也再次表明机器状态变化，接受只依据同窗口正式对照。

本节点从 IDEA、BASELINE、IMPLEMENTED 到 VALIDATED 的所有必需阶段均完成，
核心机制首版即通过；没有 REJECTED 的实现版本，没有 INVALID 性能样本或止损
触发。前述静态分析脚本域名拼写修正不改变实现、输入或运行样本。保留实现为
[CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp) 的标量常量使用点替换，
以及[回归入口](../wolvrix/tests/grhsim/test_cpu_emit.cpp)、独立 scoreboard 和
[后端文档](../wolvrix/docs/grhsim_ir/backends/cpu.md)。不修改冻结 RTL、GRH 或
既有 GRH pass，不按模块名触发，不采用多线程仿真，不提交生成物。

本节点判定 **ACCEPTED**：聚焦正确性、完整生成/编译门槛、50k 等价和六次全秩
分离均有直接证据。当前最佳正式均值 58.417667 s，距离约 40 s 仍差
**18.417667 s**（约需再降低 **31.53%**），长期目标尚未完成。距 NO00023 的
三节点定期复盘仅一个节点，本次更新当前最佳和残余证据，不另开下一节点。
后续优先从依赖/条件驱动的 compute 子图执行或 staged memory 访问寻找更大的
收益；不要把静态常量引用数量当作动态上界，也不循环先前已否定的 helper、
结果转发和通知阈值微调。节点归档见[索引](grhsim-ir-xiangshan-coremark.index.md)。

## 复现方法与计时边界

主机 AMD Ryzen 9 7950X3D，16 核/32 逻辑 CPU，单 NUMA node；编译 clang 22.1.2，
生成模型 `-std=c++20 -O3`，新旧配置一致。NEMU SHA-256
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
以下从根目录执行，重跑应使用新的 node 路径、RUN_ID 和不存在的 fresh flow。
对照需要重建时在子模块 `abefd39` 按同样完整生成/编译参数执行；本次复用已
归档且 SHA-256 核验一致的 NO00023 完整构建。runner 在每步另外记录开始/结束、
shell-quoted 命令、退出和 VALID/INVALID 状态；生成/编译超时移动不完整 flow
隔离，仿真失败保留日志并停止当前尝试。

```bash
set -euo pipefail
root=$PWD
node=$root/ptmp/no00024_sparse_execution_20260913_01
old=$root/ptmp/no00023_compute_residual_20260913_01/flow-cse-final
flow=$node/flow-constants-final
mkdir -p "$node/tmp" "$node/logs"
export PATH="$root/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export TMPDIR="$node/tmp" PIP_CACHE_DIR="$node/pip-cache"
export CCACHE_DIR="$root/ptmp/cpu_emit_ccache" CMAKE_BUILD_PARALLEL_LEVEL=32
export LC_ALL=C EMU_RUNTIME_PROFILE=0
common=(PYTHON="$root/.venv/bin/python" XS_NUM_CORES=1 XS_EMU_THREADS=1
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
  XS_LOG_DIR="$node/logs" XS_GRHSIM_IR_BUILD="$flow"
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0)
timeout --signal=KILL 1800s make --no-print-directory \
  test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping \
  PYTHON="$root/.venv/bin/python" > "$node/test-constants-focused.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00024_constants_full_generate.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00024_constants_full_generate \
  > "$node/no00024_constants_full_generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00024_constants_full_build.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu "${common[@]}" \
  RUN_ID=no00024_constants_full_build > "$node/no00024_constants_full_build.log" 2>&1
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00024_constants_${version}${pair}"
    run_flow="$flow"
    if [[ "$version" == old ]]; then run_flow="$old"; fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 90.969s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1
    rg -q 'Difftest enabled' "$node/$run_id.log"
    rg -q 'instrCnt = 73,?580, cycleCnt = 49,?996' "$node/$run_id.log"
    rg -q 'LIMIT at pc = 0x80001312' "$node/$run_id.log"
    rg -q 'Guest cycle spent: 50,?001' "$node/$run_id.log"
    if rg -qi 'mismatch|Assertion.*failed|ABORT|BAD TRAP' "$node/$run_id.log"; then exit 1; fi
  done
done
```

筛选改用独立 `flow-constants-screen`，生成时设置
`XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1`、
`XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON="$old/xiangshan_flat_grh.json"`；RUN_ID 前缀
`no00024_constants_screen_`，步骤后缀 generate/build/old/new。
基线 profile 使用 old flow，emu prefix 在上述 `stdbuf` 后附加
`env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0 CPUPROFILE=$node/no00024_baseline_profile.prof CPUPROFILE_FREQUENCY=200`。
解码命令为 `make --no-print-directory analyze_grhsim_cpu_profile`
`PYTHON="$root/.venv/bin/python"`、
`GRHSIM_CPU_PROFILE="$node/no00024_baseline_profile.prof"`、
`GRHSIM_CPU_PROFILE_BINARY="$old/emu/emu"`、
`GRHSIM_CPU_PROFILE_MODEL="$old/model/grhsim_SimTop.cpp"`、`GRHSIM_CPU_PROFILE_SAMPLES=11963`。
这些临时路径仅为复现参数，结果证据在本文正文归档。
最终相位运行使用同样的 run 命令，将 `EMU_RUNTIME_PROFILE=1`，RUN_ID 设为
`no00024_constants_final_phase`；诊断和性能命令始终分开。
