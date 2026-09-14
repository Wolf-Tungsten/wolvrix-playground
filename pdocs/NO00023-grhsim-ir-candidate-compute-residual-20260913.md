# NO00023：归一化赋值并共享重复纯计算

- Node：`compute_residual_20260913_01`。
- 最终阶段：`ACCEPTED`。六次正式交替中新均值 **60.645667 s**、旧均值
  **63.169000 s**，降低 **3.994575%**；三次新结果全部快于三次旧结果，U=0、
  单侧精确 p=0.05。完整 SV 生成 **609.71 s**、fresh 编译 **240.37 s**，六次
  50k NEMU 校验及聚焦回归全部通过。接受依据与全部样本见文末。
- 根基线：`fa4344b`；子模块基线 `2f3b72f7496ee6e4a29f40a39faaf8873d883000`。
- 节点开始工作区干净，NO00022 已归档，无未完成实验。本报告保留节点内被否定的
  尝试；最终只保留 GrhSIM 侧赋值归一化与纯计算 CSE，节点收尾集中提交。

## IDEA 与证据计划

NO00022 最终相位 compute 41.914338 s（67.44%）、commit 18.606339 s（29.94%）、
publication 1.557333 s，仍为 100102 evals / 201258 rounds。先用当前构建刷新平坦
采样，结合生成代码及通用依赖/读写属性选择减少重复求值的机制；不重复通知分支、
局部目标汇聚或阈值微调。实施前记录具体新意、静态覆盖、收益范围与证伪标准。

## BASELINE 与预注册

- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`、SimTop、NEMU/DIFFTEST；
  冻结 RTL、GRH、GRH pass 与工作负载不变，禁止模块名触发。
- CoreMark SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；
  NEMU SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
- 复用 NO00022 完整生成/fresh 编译的对照，emu SHA-256
  `4e05a152cb8e6c97bc50c0960d04801ff40b634aba5154048aefc3f9f651f815`。
- 50,000 cycles、CPU 2、`XS_EMU_THREADS=1`、`XS_NUM_CORES=1`；waveform、commit/RAM
  trace 关闭；AMD Ryzen 9 7950X3D，16 核/32 逻辑 CPU、单 NUMA node，编译 32 jobs。
  clang 22.1.2，模型 `-std=c++20 -O3`，保持相同编译配置。
- 运行前选定 NO00022 正式均值 63.223 s，仿真预装 **94.835 s** 进程树 KILL
  （1.5 倍、毫秒取整）；生成/编译各自从 Make 启动计时，预装 1800 s KILL。
  超时否定该次尝试并隔离不完整 flow；恢复 flat checkpoint 仅供筛选。
- 正式六次顺序预注册为 `old1/new1/old2/new2/old3/new3`，同窗口串行。
  Host 为主指标，记录 emu 墙钟及全部退出/等价性；均值、样本标准差、效应量及
  秩次分析均须报告。仅 `max(new)<min(old)`（单侧精确 p=0.05）允许 ACCEPTED。
  无效样本记录后补跑，不删除有效慢样本；诊断不进入性能样本。
- 精确 50k 终点：73580 instructions、cycleCnt 49996、PC `0x80001312`、guest cycles
  50001。非零、断言、mismatch 或输入不符为 INVALID；运行确认失败即停止。
- 复用 gsim 20.640 s 归档，不重复仿真。
- 临时日志、命令与产物统一位于 `ptmp/no00023_compute_residual_20260913_01/`。
- NO00023 收尾须更新三节点搜索复盘；长期约 40 s 目标与本节点接受分别判定。

## IDEA：在定义位置转发标量结果

当前 NO00022 新鲜采样 `no00023_baseline_profile`：Host 64.084 s、12821 samples
（200 Hz），compute tasks 61.180875%、commit tasks 24.249279%、evaluator 2.971687%、
main-other 8.891662%、external 2.433508%；compute 分散在 2551 个 task。解码通过
终止符、mapping、ELF 布局、符号边界与样本总数检查。50k NEMU 终点通过，诊断不计入
性能基线（emu 墙钟 64.12 s）；首次解码因缺少 WOLF_ENV_SOURCED 被 Make 拒绝，
补齐环境后成功，未重跑仿真。

生成代码反复使用 `boundary[result]=expr; ... use(boundary[result])`。boundary 的
bool/uint8_t 与其他对象共用字节 arena，后续字节写入可能阻碍编译器跨操作保留值。
机制是在原定义位置声明规范化的标量局部结果，照常写回 boundary、累积原通知，
同一 computeGroup 内之后的消费者直接使用此局部结果。它消除重复读取及表达式
经存储转发的依赖，不增加跨 eval 缓存或条件分支，也不在入口预读外部操作数。
与历史未验证的 operand cache 不同，本方案只转发本块已执行的生产者结果。

资格：1–64 bit 两态逻辑、boundary 存储、非 state-read alias、常规单结果 compute/
input/state/memory read，并且本 computeGroup 后面有消费者。DPI 结果、宽值、string、
跨 helper chunk 与跨 unit 使用保留原存储路径。局部名在定义后才可见；helper 边界
重置转发表，定义顺序、boundary 快照、通知和 memory read address 记录保持原样。
只改 CPU emitter，不改 GRH/IR、分区、布局、调度或 runtime helper ABI。

预期总 Host 减少 3–12%，理论上限受 compute 约 61–67% 占比约束；静态覆盖在
生成后统计，不能当作动态收益。若编译器已能转发，或局部值增加寄存器压力导致
无收益，则证伪并继续本节点修正。聚焦回归、完整 SV/编译各 1800 s、50k 等价与
94.835 s 止损不变；正式六次使用前述旧/新顺序，筛选不计入正式样本。

## IMPLEMENTED：结果转发首版

emitter 在每个 computeGroup 中记录最后消费位置，在常规标量生产者之后才发布
局部转发名。结果规范化只计算一次，写回路径沿用原 changed-group；不合格结果
和 group 之外仍通过原 storage accessor 读取。IR verifier 要求每值恰有一个生产者，
canonical boundary layout 为各值分配独立存储；结合只向定义后转发，后续操作
不能改写被转发值的快照。首版既有 emitter suite 53.40 s
通过。新增独立 scoreboard 覆盖 unsigned bool、signed 5-bit、unsigned 64-bit、
加法溢出、位运算、多消费者、寄存器旧值快照、重复 eval 和四次 init，并分别生成
内联及逐操作 helper 两种模型。扩展 emitter suite **114.57 s** 通过（与筛选模型
编译并行，此测试耗时不作性能比较）；两种模型各验证 16384 eval / 4 init，内联
模型明确覆盖转发，逐操作 helper 模型明确没有跨 chunk 转发。schedule **0.04 s**、
IR/mapping 各 **0.02 s** 通过；原 sanitizer、Verilator、多时钟和宽值 suite 保留。

筛选恢复 frozen flat checkpoint：Make 墙钟 **107.61 s**（内部 96.678 s），exit 0，
已安装 1800 s 截止。静态转发 **189832** 个结果，覆盖 **3680** 个 compute task。
该恢复用时不代替完整 SV 门槛。fresh 32-job C++ 编译 **259.13 s**，exit 0，
预装 1800 s 截止；期间并行了聚焦测试，性能仿真等待两者全部退出后才启动。
最终 emu text 段 old/new 为 134244983 / 133617167 bytes，减少 627816 bytes
（约 0.47%）。局部 task 的代码规模有增有减，不能据此推断性能收益。

相邻筛选：old Host/emu 墙钟 **63.402/63.43 s**、new **62.109/62.14 s**，
均 Make/emu exit 0/0、精确 50k NEMU
终点通过。单对降低 1.293 s（2.0394%），仅用于进入正式验证，不构成统计接受证据。
代码冻结为 emitter SHA-256 `4e4c743b34e222dbecef36992033dec655797b95da0c7d23991912111cf17068`；
随后在独立目录完成完整 SV→C++、fresh 编译与预注册的六次旧/新交替，结果如下。

## VALIDATION 进展：完整生成

`no00023_forward_full_generate` 从 SV 入口完成：内部 602.473 s，Make 总墙钟
**611.93 s**，exit 0，1800 s 截止未触发。目标 C++/Makefile 在启动后约 593 s
已形成（20:12:24 启动记录、20:22:17.211589400 最后生成的 Makefile mtime）；
611.93 s 还包含后续 IR round-trip，为生成门槛的保守上界。各前端步骤顺序保持。
完整生成的 flat GRH 与 NO00022 **逐字节相同**，XiangShan 工作区干净。
正式与筛选模型的全部 `.cpp`、头文件及 Makefile **逐字节相同**；没有把筛选
二进制复制到正式目录。fresh 32-job 编译 **261.50 s**，Make exit 0，1800 s 截止
未触发；新旧 ELF .comment 中编译器均为 clang 22.1.2。
正式 emu SHA-256 `46a94d11d05a5dd0ed4c517141f6d86075667370d24515df2f74651a40f2a7ae`，
旧 emu 与 emitter 源码哈希保持冻结值。正式六次按预注册顺序执行；期间不构建或
并行运行其他仿真。

## 复现命令与边界

从根目录执行，复跑时替换为唯一节点目录和 RUN_ID，fresh flow 必须尚不存在。
以下命令对应最终 CSE 实现；旧构建使用上述 NO00022 基线及其已归档完整生成物，
需要重建时按 [NO00022 报告](NO00022-grhsim-ir-candidate-shared-port-edge-20260913.md)
在该基线版本执行完整生成与 fresh 编译。所有生成、构建、测试、仿真
均走既有 Makefile 目标；日志与临时文件位于 ptmp。实际 runner 同时记录完整
shell-quoted Make 命令、开始/结束时间、退出码与 VALID/INVALID 状态；超时 kill
进程树并隔离不完整 flow，非零或错误终点立即停止。

```bash
set -euo pipefail
root=$PWD
node=$root/ptmp/no00023_compute_residual_20260913_01
old=$root/ptmp/no00022_residual_eval_20260913_01/flow-taskedge-final
flow=$node/flow-cse-final
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
  PYTHON="$root/.venv/bin/python" > "$node/test-cse-final.log" 2>&1
timeout --signal=KILL 1800s make --no-print-directory test_grhsim_reg_to_mem_rtl \
  PYTHON="$root/.venv/bin/python" > "$node/test-cse-rtl-pipeline.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00023_cse_full_generate.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00023_cse_full_generate \
  > "$node/no00023_cse_full_generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/no00023_cse_full_build.make.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu "${common[@]}" \
  RUN_ID=no00023_cse_full_build > "$node/no00023_cse_full_build.log" 2>&1
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00023_cse_${version}${pair}"
    run_flow="$flow"
    if [[ "$version" == old ]]; then run_flow="$old"; fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 94.835s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1 || exit "$?"
    rg -q 'Difftest enabled' "$node/$run_id.log"
    rg -q 'instrCnt = 73,?580, cycleCnt = 49,?996' "$node/$run_id.log"
    rg -q 'LIMIT at pc = 0x80001312' "$node/$run_id.log"
    rg -q 'Guest cycle spent: 50,?001' "$node/$run_id.log"
    if rg -qi 'mismatch|Assertion.*failed|ABORT|BAD TRAP' "$node/$run_id.log"; then exit 1; fi
  done
done
```

最终筛选使用独立 `flow-cse-screen`，生成目标加
`XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1`
与 `XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON="$old/xiangshan_flat_grh.json"`，RUN_ID 分别为
`no00023_cse_screen_generate/build/old/new`。历史尝试分别使用本文说明的实现差异及
`forward`、`multiuse`、`identity` flow/RUN_ID，不能用最终源码复现为相同候选。
phase 诊断仅设置
`EMU_RUNTIME_PROFILE=1`；平坦采样在 emu prefix 后加
`env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0 CPUPROFILE=... CPUPROFILE_FREQUENCY=200`。
解码使用 `make analyze_grhsim_cpu_profile`，参数为
`PYTHON="$root/.venv/bin/python"`、
`GRHSIM_CPU_PROFILE="$node/no00023_baseline_profile.prof"`、
`GRHSIM_CPU_PROFILE_BINARY="$old/emu/emu"`、
`GRHSIM_CPU_PROFILE_MODEL="$old/model/grhsim_SimTop.cpp"` 与
`GRHSIM_CPU_PROFILE_SAMPLES=12821`。这些路径是复现参数，结果证据在本文正文归档。

### REJECTED：首版无条件块内标量转发

完整 fresh 编译为 261.50 s，六次正式交替全部有效且 NEMU PASS：

| RUN_ID 后缀 | 启动（UTC+08:00） | Host s | emu 墙钟 s | Make/emu 退出 | 状态 |
|---|---|---:|---:|---|---|
| old1 | 20:27:38 | 61.967 | 62.00 | 0/0 | VALID / PASS |
| new1 | 20:28:40 | 63.861 | 63.89 | 0/0 | VALID / PASS |
| old2 | 20:29:44 | 63.330 | 63.36 | 0/0 | VALID / PASS |
| new2 | 20:30:47 | 63.999 | 64.03 | 0/0 | VALID / PASS |
| old3 | 20:31:51 | 62.256 | 62.28 | 0/0 | VALID / PASS |
| new3 | 20:32:54 | 64.310 | 64.34 | 0/0 | VALID / PASS |

日期均为 2026-09-13，RUN_ID 前缀 `no00023_forward_`。old 均值 **62.517667 s**、
样本标准差 **0.718188 s**；new 均值 **64.056667 s**、样本标准差 **0.229988 s**。
new 比 old 慢 **2.461704%**，old−new 效应量 Cohen's d=−2.886133，
`min(new)=63.861 > max(old)=63.330`，U_new=9，改善方向单侧 p=1.0，
反向单侧精确 p=0.05，不能作为收益证据；六次均保留。精确终点均为
73580 instructions、cycleCnt 49996、PC `0x80001312`、guest cycles 50001，
无 INVALID、超时或补跑。筛选时的单对改善因此归为窗口噪声/负载差异，正式交替否定
首版。可能原因是 189832 个局部常量延长寄存器活跃范围，增加了 task 代码压力，
抵消 boundary 重读节省；没有硬件计数器，不能作更强归因。

### IMPLEMENTED：收紧为多次使用结果

修正版仅转发同一 computeGroup 内被至少两个后续 operand 使用的标量结果；一次使用
的结果继续原 boundary 路径。该条件仍要求 boundary 槽、两态 1–64 bit、无 alias、
同一 chunk，通知/写回顺序不变。目标是删除首版大量短生命周期局部量，保留可能有
重复读取收益的值；预期覆盖和收益在筛选生成后重新统计。首版六次已否定，修正版
须重新经过聚焦测试、完整生成/编译与六次交替，不能复用首版性能样本。

多次使用修正版 emitter suite **56.27 s** 通过。筛选恢复 Make **103.13 s**（内部
92.036 s）、fresh 编译 **261.21 s**，均 exit 0，预装 1800 s 截止。静态覆盖
**53225** 个结果/**3011** 个 task，为首版局部量的 28.04%；相邻筛选结果如下。

### REJECTED：多次使用结果转发

修正版相邻筛选仍然回退：old Host **63.232 s**、new **66.331 s**，emu 墙钟
**63.26/66.36 s**，均 exit 0、精确 50k NEMU PASS。new 慢 **4.9010%**，
因此未进行完整生成或正式六次；修正版不保留，继续改换机制。

## IDEA / IMPLEMENTED：一位逻辑直接布尔路径

取消结果转发资格，在 `normalize` 中对 unsigned two-state width=1 结果只发射
`static_cast<bool>`，在目标宽度同为 1 时 `expression` 的操作数转换直接传递原
bool 值。该路径不触及多位、有符号、宽值、状态 alias、边沿或提交逻辑；它只删除
恒等的 `grhsim_cast_u64(...,1,1,false)`/`grhsim_trunc_u64(...,1)` helper 包装。
该尝试通过首轮 emitter 编译后进入回归；计划中若新增整数提升或 helper 内联
没有带来净收益则否定该尝试，实际结果如下。

布尔路径初版在聚焦 history-scan derived 用例发生 edge/sample mismatch（24.55 s）：
`static_cast<bool>(~true)` 为 true，原位宽截断结果为 false，直接转换不等价，记
INVALID 并立即停止。改为 `(expr)&UINT64_C(1)` 后 emitter suite **55.69 s** 通过。
该修正已恢复原低位截断，预计编译器可折叠相同包装；没有进行 XiangShan 生成、
编译或性能实验，撤销两处 bool 改动。此前文字“恒等变换”只适用于已规范化输入，
不能用于取反/加法等未规范化表达式的结果，本次失败不作性能证据。

## IDEA / IMPLEMENTED：消除 GrhSIM 中同类型赋值

首轮生成示例包含 `sum→assign→assign→commit` 等链，单纯转发后仍保留全部
boundary 写回、变化比较、端口武装和调度结点。新机制在 GrhSIM 语义层删除相同
TypeId 的两态逻辑 `core.compute.assign`，将所有消费者改接链根，随后重新建立
CPU mapping。预期同时减少求值、持久值存储和变化传播，突破只改局部 C++ 表达式
的限制。作用点在已冻结 GRH 之后、reg-to-mem 之后；不修改 GRH、既有 GRH pass、
XiangShan 或负载，也不按模块名触发。

资格严格要求同完整类型（含位宽、signedness、domain）、单输入/单输出、无对象
引用和参数；宽度/符号转换、四态、string/real 均保留。按值链解析，支持非拓扑
operation 顺序和多级 chain；纯 assign 环及指向该环的初次解析路径保持，不能
虚构根值。保留生产者、状态/事件 history、初始化与有副作用操作的相对顺序。
所有 operand（包括 commit 快照及 event）统一重接，调用既有 compact 重建 ID，
由 SemanticTransform 清除 mapping 并重新验证。没有改 runtime helper ABI。

示例：`x:u8 → assign y:u8 → assign z:u8 → regWrite(enable,z,mask,clk)`
归约为 `regWrite(enable,x,mask,clk)`；`x:s5 → assign y:u8` 必须保留以执行符号
扩展和宽度转换。同理 state-read 的结果若最终被 commit 使用，CPU alias proof
仍看到这个消费者，保留 pre-commit boundary 快照，不把存储直接别名到可变状态。

预期总 Host 改善 **5–20%**；可证伪因素是 assign 占比太低，或分区重排抵消少算
收益。静态覆盖在筛选时测量，收益须重新完整生成/编译、50k 对拍和六次交替证明。
仿真止损仍为 94.835 s；本尝试独立 RUN_ID `no00023_identity_*`，正式顺序
`old1/new1/old2/new2/old3/new3`，不得混入前述失败样本。

基线 audit 确认 `core.compute.assign=235555`（另有 and=757209、not=98828、
state.read=184961）。筛选后 assign 为 **1739**，删除 **233816** 个操作/值，
覆盖原 assign 的 **99.2617%**；其余保留类型转换。新 operations=4296920、
values=4051866，状态、init 和副作用操作未删除。筛选恢复 Make **102.63 s**
（内部 88.668 s），新 pass 内部 **0.596 s**；均 exit 0，截止未触发。
emitter suite **56.05 s** 通过，两种模型各16384 eval / 4 init；新增 IR 测试覆盖
反拓扑链、signedness/位宽/四态转换保留、129-bit 同类型消除、纯 assign 环、
idempotence 和 JSON round-trip，IR/mapping/schedule 均 **0.01 s** 通过。
筛选模型使用独立 fresh 编译，没有使用前两次尝试的生成物。

### REJECTED：仅消除同类型赋值

fresh 编译 **262.48 s**，exit 0。相邻筛选 old Host/墙钟 **62.221/62.25 s**、
new **66.018/66.05 s**，均 Make/emu exit 0/0、精确 NEMU PASS，回退
**6.1024%**。task 从5595降到5309，
boundary 从2411392降到2349440 bytes，cpu_flags/next_arms 各从6056降到5760 bytes，
pflags 24303 bytes与对象25934336 bytes不变；text 从134244983到133086020 bytes。
这些静态删减没有换来动态收益，分区及依赖重排的成本可能超过消除 assign 的收益，
尚无更强因果归因。未进行该单独版本的完整 SV 或正式六次；继续同一节点。

## IDEA：对同类型赋值归一化后的纯计算做公共表达式消除

只消除复制值无法去掉独立重算；下一版把相同 `(op type, result TypeId,
canonical operands, 完整 parameters)` 的两态逻辑纯 compute 合为一个结果。
只按精确操作数顺序匹配，不做交换/结合变换，故不改变截断、符号、算术或异常
边界。不共享 input/state/memory read、DPI、system、output 或 commit 操作。
参数序列使用长度分隔的精确编码；带未知参数类型的 op 保守保留。对依赖按拓扑
次序处理，循环及依赖循环的节点不做 CSE。相同初始模型、纯函数和相同输入保证
结果等价；合并后所有消费者共用同一结果，重新调度确保依赖顺序。

预期更广地删除重复算术/逻辑与通知，局部目标 **5–20%**；静态覆盖待生成测量。
若没有充分重复或调度重排仍回退则证伪。时间、NEMU、单线程和六次交替门槛保持，
独立 RUN_ID `no00023_cse_*`，正式顺序 old/new 连续三对。

CSE 筛选模型 operations=**4095805**、values=**3850751**；在233816个 identity
之外再删除 **201115** 个重复纯 compute 及结果。状态508487、init records508487、
init steps624709、对象引用762914保持。恢复 Make **109.24 s**（内部97.759 s），
canonicalize pass **3.781 s**，exit0，预装1800 s截止。扩展 emitter suite
**60.59 s**通过，明确检查两条相同 add/xor 链只留一条，且每种映射仍通过独立
16384 eval/4 init scoreboard；IR suite **0.01 s**覆盖不同减法操作数顺序、不同
slice参数保留及重复slice合并，mapping **0.01 s**。筛选 fresh 编译结果如下。

CSE 筛选 fresh 编译 **236.80 s**。相邻 old Host/墙钟 **63.158/63.19 s**、new
**61.141/61.17 s**，均 Make/emu exit0/0、精确 NEMU PASS，改善 **3.1936%**；
只用于推进完整验证，不作接受依据。独立文件 `canonicalize_compute.cpp/.hpp`
承载最终 pass，注册器与 CMake 接入；抽取类不改变算法、遍历或输出。进一步把
既有 Verilator 标量、宽值、宽状态、多时钟 CDC/双口 RAM 差分测试也前置该 pass，
验证泛化范围，最终版本回归及完整生成结果如下。

独立文件抽取后 emitter/IR/mapping/schedule 回归通过；扩大的 Verilator 差分
suite **61.42 s**通过（与完整生成入口短时并行，测试耗时不作性能证据）。新增
算术链 fixture 两种 mapping 的独立 scoreboard 保留；既有标量、宽值、宽状态、
CDC/双口 RAM fixture 现在先运行 canonicalize-compute，再生成并与相同 SV 参考
对比。最终 pass 和流水线脚本随后冻结，完整 SV 路线验证同一源码版本。

根仓库现有 `make test_grhsim_reg_to_mem_rtl` 同样通过：使用更新后的完整
CPU_PIPELINE，SV→GRH→reg-to-mem→canonicalize→C++，对 Verilator **8192 samples**
一致（`scalar table RTL/GrhSIM PASS`）。通过该 Make 目标执行，参数为既有 `.venv`
Python、LLVM/Verilator PATH、节点 TMPDIR，预装1800 s截止；它不作为50k性能样本。

### CSE 完整 SV 门槛

`no00023_cse_full_generate` Make 总墙钟 **609.71 s**（内部598.257 s），exit0，
预装1800 s进程树截止未触发；从SV读取开始完成所有目标C++/Makefile及后续IR
round-trip，因此总墙钟是生成门槛的保守上界。flat GRH 与NO00022逐字节相同。
正式 C++、头文件、Makefile 与 CSE 筛选逐字节相同。独立 fresh 32-job 编译
`no00023_cse_full_build` **240.37 s**，Make exit 0，1800 s 截止未触发；
2026-09-13 22:40:09–22:44:09（UTC+08:00）。完整生成从 22:29:30 启动，
目标 Makefile mtime 为 22:39:23.245556182，后续 round-trip 于 22:39:40 完成；
正式 pass 本身 **3.514 s**。新旧编译器 ELF `.comment` 均为 clang 22.1.2。
新 emu SHA-256 `ac556d5f6c70eaff644e59c624d0f594a0bc5e7a7ead1e0ffb9b7241b71f8e2e`。
最终 pass SHA-256 `030b2b5d7fe159f191eab4930723159a29b16214b0a8d27f367b479ed512482f`，
流水线脚本 `f022fee0411ed2987553ba8b36ebe6f0ba636f522077e2398336dd27d44926d7`，
XiangShan工作区干净，CoreMark哈希与预注册一致。没有保留C++转发、bool包装或
单独identity版本；最终代码是identity归一化与纯计算CSE的组合。

## VALIDATED：最终六次正式交替

日期均为 2026-09-13，时区 UTC+08:00，RUN_ID 前缀 `no00023_cse_`。
严格按预注册 old1/new1/old2/new2/old3/new3 串行执行，期间无构建或其他仿真。

| RUN_ID 后缀 | 启动 | Host s | emu 墙钟 s | Make/emu 退出 | 状态 |
|---|---|---:|---:|---|---|
| old1 | 22:44:49 | 62.719 | 62.75 | 0/0 | VALID / NEMU PASS |
| new1 | 22:45:52 | 60.669 | 60.70 | 0/0 | VALID / NEMU PASS |
| old2 | 22:46:52 | 63.033 | 63.06 | 0/0 | VALID / NEMU PASS |
| new2 | 22:47:56 | 60.678 | 60.71 | 0/0 | VALID / NEMU PASS |
| old3 | 22:48:56 | 63.755 | 63.78 | 0/0 | VALID / NEMU PASS |
| new3 | 22:50:00 | 60.590 | 60.62 | 0/0 | VALID / NEMU PASS |

最后一次于 22:51:01 结束。每次日志均确认 `Difftest enabled`，精确终点均为
**73580 instructions / cycleCnt 49996 / PC 0x80001312 / guest cycles 50001**。
没有 INVALID、超时、补跑或排除的有效样本。输入身份、单核 harness、CPU 2 绑定、
单线程仿真、50k 上限和 trace/waveform 设置均一致；前述筛选与诊断不混入本表。

| Host 统计量 | NO00022 对照 | NO00023 候选 |
|---|---:|---:|
| 样本数 | 3 | 3 |
| 均值 s | 63.169000 | 60.645667 |
| 样本标准差 s（分母 n−1） | 0.531221 | 0.048418 |
| 最小值 s | 62.719 | 60.590 |
| 最大值 s | 63.755 | 60.678 |

均值降低 **2.523333 s / 3.994575%**，百分比以同窗口旧均值为分母。
emu 墙钟均值 old/new 为 **63.196667/60.676667 s**，降低 **3.987552%**，
与 Host 口径一致。以 old−new 定义改善方向，pooled-SD Cohen's d 为
**6.689870**，rank-biserial 改善效应量为 **1**。
`max(new)=60.678 < min(old)=62.719`，间隔 **2.041 s**；新样本占全部最低三秩，
Mann–Whitney **U_new=0**，单侧精确 **p=1/C(6,3)=0.05**（无并列）。
样本很少，d 不宜外推为长期稳定的固定收益；接受依据是预注册六次的完全秩分离。
观测改善低于最初 5–20% 局部预期，但最新规则没有收益幅度硬门禁，真实收益成立。

## 静态结果与最终相位

| 项目 | NO00022 | NO00023 | 变化 |
|---|---:|---:|---:|
| GrhSIM operations | 4530736 | 4095805 | −434931（−9.599566%） |
| GrhSIM values | 4285682 | 3850751 | −434931（−10.148466%） |
| `core.compute.assign` | 235555 | 1682 | −233873 |
| CPU tasks | 5595 | 5036 | −559 |
| boundary bytes | 2411392 | 2282776 | −128616 |
| cpu_flags bytes | 6056 | 5487 | −569 |
| next_arms bytes | 6056 | 5487 | −569 |
| commit pflags bytes | 24303 | 24303 | 0 |
| object bytes | 25934336 | 25934336 | 0 |
| emu text bytes | 134244983 | 129732600 | −4512383（−3.361305%） |

总删减由 **233816** 个同类型 identity assign 和 **201115** 个重复 compute
组成；后者包含 **57** 个精确相同的剩余 assign 转换。state **508487**、init records
**508487**、init steps **624709**、object refs **762914** 均保持，input/state/memory
read、DPI/system、输出与提交操作未删除。少算表达式同时缩减了持久值、通知和分区，
因此无法将总收益单独归于算术次数；仅 identity 版本回退也说明静态数量不能代替实测。

六次结束后运行独立 `no00023_cse_final_phase`（22:52:40–22:53:40），
`EMU_RUNTIME_PROFILE=1`，Host **59.157 s**、emu 墙钟 **59.19 s**，Make/emu exit
0/0，精确 NEMU PASS，94.835 s 截止未触发。evals **100102**、rounds **201258**，
与原模型一致；相位累计 eval **58.983056 s**：

| 相位 | 时间 s | 占 eval 时间 |
|---|---:|---:|
| compute | 38.935131 | 66.010705% |
| commit | 18.505281 | 31.373894% |
| publication | 1.468784 | 2.490180% |

其余约 0.073860 s 属相位之外的 evaluator 开销。该次插桩运行比正式候选均值还快，
说明机器状态仍可漂移，不能替换六次主样本。相较 NO00022 归档相位，compute
41.914338→38.935131 s、commit 18.606339→18.505281 s，方向与重复计算消除一致；
它们并非同期交替的相位对照，不能将这两个差值当作因果分解或额外性能接受证据。

## ACCEPTED 与三节点搜索复盘

本节点的最终机制为通用 GrhSIM SemanticTransform：同完整类型赋值归一化后，
按纯计算、精确有序 operand、结果类型及完整参数共享等价表达式，并重建 CPU mapping。
实现不依赖 XiangShan 模块名称，没有改 frozen GRH、既有 GRH pass、RTL 或负载，
没有修改 runtime helper ABI，也没有增加仿真线程。保留实现文件为
[canonicalize_compute.cpp](../wolvrix/lib/grhsim/pass/canonicalize_compute.cpp)、
[注册接口](../wolvrix/include/grhsim/pass/canonicalize_compute.hpp)、
[CPU 流程说明](../wolvrix/docs/grhsim_ir/flows/cpu-st.md) 及
[XiangShan 入口](../scripts/wolvrix_xs_grhsim_ir.py)，注册器/CMake 与测试同步归档。

门槛全部完成：聚焦 IR/mapping/schedule 回归、内联与 helper 各 16384 eval/4 init
的独立 scoreboard、ASan/UBSan、标量/宽值/宽状态/CDC/双口 RAM 的 Verilator 差分、
完整 RTL pipeline 的 8192 samples 对拍、SV→C++ **609.71<1800 s**、fresh 编译
**240.37<1800 s**、六次 50k 等价及预注册 U=0/p=0.05。最终判定 **ACCEPTED**。
首版转发的正式回退、多使用转发和仅 identity 的筛选回退、bool 初版的 INVALID
均保留于本文；失败源码全部撤销，未执行的完整/正式阶段没有冒充通过。

NO00021–NO00023 三节点分别减少混合 task history 重复采样、共享提交端口边沿、
共享 GrhSIM 纯计算。同窗口降幅依次为 **3.304271% / 3.308048% / 3.994575%**，
每个节点均以自己的六次交替判断，不能把跨窗口均值直接相减或相乘作为累计实测。
当前最佳正式均值 **60.645667 s**，距约 40 s 仍差 **20.645667 s**（还需降低
约 34.04%）。三节点收益较 NO00017–19 的大步改善收窄；NO00023 已从 helper/
通知微调转向语义层去重，仍未达到最初 5–20% 预期，不宜继续只靠边角包装推进。

已排除本节点的无条件/多使用块内标量转发、直接 bool 包装简化、仅 identity
删减，也维持 NO00021/22 已否定的 helper/cache 与通知分支/局部汇聚判断。
当前 compute 仍占约 **66%**，commit 约 **31%**，轮次结构没有变化；后续方向应
优先调查依赖驱动的更细粒度 compute 执行、稀疏 commit 端口执行或 staged memory
访问，先刷新相应热点并明确动态覆盖和可证伪上界。以上只是搜索建议，本次不启动
下一节点。长期约 40 s 目标仍未完成。

归档顺序为子模块实现提交，再根仓库入口、子模块指针、本报告、goal 与
[索引](grhsim-ir-xiangshan-coremark.index.md)；生成物、日志、profile 和二进制
均留在 ptmp，不提交。保留实现的最终子模块 commit：
`abefd39e11c0ce52eb34996336eec9112ae93f1d`（`feat(grhsim): canonicalize pure compute expressions`）。
该提交的 pass 源码与本文完整生成、回归和六次正式测量的冻结哈希一致；根仓库
归档提交同时固定此子模块指针和入口流水线改动。
