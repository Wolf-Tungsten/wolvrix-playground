# NO00034：分区内稳定输入缓存

日期：2026-09-16。节点阶段：`ACCEPTED`。

最终保留尝试 C：在 GrhSIM CPU mapping 中显式记录稳定 helper 输入缓存，emitter
按计划复用读取。六次交替 100k 的 Host 均值 **108.014333 → 104.594333 s**，
降低 **3.166246%**，max(new) 105.727 < min(old) 107.175，U=0、单侧精确 p=0.05。
六次 NEMU 对拍及预期终点均通过；完整生成 **720.38 s**、fresh 编译 **214.26 s**。
尝试 A（精确表达式复用）未通过统计门槛、B（大范围局部变量提升）筛选变慢，均已
撤回，失败过程完整记录于下文。该节点证明一项局部收益，剩余与 gsim 的差距仍为
**2.227070 倍**；没有宣称一个机制解释了全部差距。

## IDEA 与基线

本节点从 NO00033 开始，根仓库基线 `4880df9`，wolvrix 子模块基线
`c652264bcca1c50a542120ea66de0aea1250d5a1`。此前 profile 表明 compute
仍占 eval 约 78.65%，最新 IR Host 均值 108.078 s，为归档 gsim 46.965 s 的
2.301246 倍。该差距分散于大量 compute task；需要减少分区和 lowering 后残留的
重复计算及其物化成本。

机器为 AMD Ryzen 9 7950X3D（16 核、32 逻辑 CPU）。仿真只用逻辑 CPU2；
模型编译使用 32 个并行作业，不把编译并行度带入仿真。

假设：全局 canonicalization 先于 clone 和 predicate lowering，后续变换会在
同一 compute helper 内产生重复的纯表达式。按 op、结果类型和有序输入共享计算，
可消除这些变换引入的冗余。初步 emitter 计数为 3,287,222 个候选、32,312 次
精确重复；这是覆盖面证据，不是运行时收益证据。局部目标为减少 compute 指令和
访存，预期收益较小；若编译器已消除这些表达式，或额外复制抵消收益，则该初始
实现被证伪，需在同一节点内改进机制。不得据单次筛选接受。

## BASELINE 与测量预注册

在任何有效 NO00034 性能运行之前固定以下口径：CPU2、单核、
`XS_EMU_THREADS=1`、100000 cycles、CoreMark 两次迭代、NEMU 对拍；关闭
waveform、commit/RAM trace 和 profile。对照为 NO00033 已接受二进制，SHA256
`229ce08989b587cfa7104cbc57d8c65b9317ae04fbcc9767245d6a7b850fcb28`。
预选对照时间 108.078 s，emu 进程树截止为 **162.117 s**。

输入 CoreMark SHA256 为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；
NEMU SHA256 为
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
有效终点必须为 `instrCnt=240349, cycleCnt=99996, guest=100001,
PC=0x80000c0c`，emu exit 0 且无 difftest mismatch。

初始筛选顺序为 old1/new1；正式顺序固定为
**old1/new1/old2/new2/old3/new3**。主指标为 Host time，补充每次 emu 墙钟；
报告均值、样本 SD、Cohen d(new−old)、Cliff delta 和精确单侧 Mann–Whitney U。
要求 `max(new) < min(old)`（3+3 时 p=0.05）。筛选样本不混入正式结果。

完整 SV→C++ 和 fresh C++ 编译分别在启动前设置
`timeout --signal=KILL 1800s`，任一步超时即终止并否定该次尝试。
后续所有日志、TMPDIR、pip/ccache 目录均位于本仓库 `ptmp/`。

## 尝试 A：emitter 内精确复用原型

工作区改动仅为 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`。候选限定于单结果、
无对象引用、无参数的 `core.compute.*`，结果为 1–64 位 two-state scalar；
不处理静态常量和 read alias。重复表达式暂通过首个结果的存储槽复制，保留
各自的 changed/fanout 通知。初始实现后的复核确认 layout 使用独立槽位，且 compute
期间读取提交前状态；最终将这一条件纳入下述可验证 mapping 计划。

已有 `make test_grhsim_cpu_emit` 两次通过（96.01 s、95.35 s）。初始 checkpoint
重发射和编译成功，但未预装截止机制且遗漏 TMPDIR；这些前期构建不作为最终
时间门槛证据。诊断位置调整后重复构建了相同生成代码，造成不必要的构建开销。
此前一次 20k 启动因候选二进制尚不存在而失败，未产生有效仿真测量。

初步 Python 分析曾误用 JSON 字符串表索引（正确为 `strings[id - 1]`），因此
不采纳其 op 标签与分类数字；上述 32,312 来自 C++ emitter 的实际诊断。

初始有效筛选 old/new Host 为 **107.846 / 106.673 s**，emu 墙钟为
**107.88 / 106.70 s**，两次 exit 0、对拍和预期终点通过；候选快 **1.087662%**。
n=1+1 的精确单侧 p=0.5，不作接受依据。第一次筛选命令漏设 `WOLF_ENV_SOURCED`
被 Makefile 启动检查拒绝，没有执行 emu；第二次成功，不与有效样本混淆。

修正后的结构统计与 C++ 诊断一致：32,312 次重复中，`not` 15,362、`logicNot`
13,898、`add` 2,483、`concat` 353、`sub` 122、`xor` 69、`and` 24、`or` 1；
其中 30,890 个结果为 partition-local、1,422 个为 boundary。这里的统计没有依据
模块名或源码名称筛选，全部来自类型、operand 和最终 helper 分块。

原生静态 compute 指令为 14,795,401 → 14,789,608（减少 5,793，约 0.039%），
条件跳转反而为 530,277 → 530,525（增加 248）；ELF text 为
102,912,740 → 102,893,636 bytes。commit 指令不变。大部分源码重复已被编译器
消除，不能把 32,312 次静态替换等同于运行时等量减少；筛选时间差还需正式测量验证。

覆盖面仅为候选标量计算的 **0.982958%**。若假设这些计算的执行频率和单位成本
完全相同，并理想消除重复计算本身，则对应 eval 时间的约 **0.773%**；该均匀成本
估计不是实际收益上界，因为执行频率、访存和代码布局并不均匀。它说明本方案预计
是百分之一量级的局部改进，无法单独解释或消除 2.3 倍差距。条件跳转数量增加也说明
不能仅凭静态汇总预言性能，接受与否仍由正式秩次门槛决定。

## 实现收敛：IR mapping 与 emitter 协同

把尝试 A 的发现过程移入 `cpu.st.layout-data`，新增可选
`CpuDataLayout::computeReuses`，在最终 helper 分块内按 opcode、完整结果 TypeId
和有序 operand IDs 建立 `{value, source}`。emitter 只执行经过 verifier 检查的计划，
不在发射时隐式重新决定等价关系。语义 graph、slot、分区和调度依赖保持原样，避免
重新进行全局 CSE 抵消 NO00030 clone localization。

JSON 增加末尾可选表；旧 checkpoint 缺表时继续使用普通计算，字节形态兼容。
verifier 重建计划，拒绝错误来源、逆序和缺失项。源与目标位于同一 helper，源先
执行；纯表达式 operand 的 SSA 值在调用中不变，且当前 layout 不复用存储槽。
目标仍保留自己的 changed 比较和 fanout/port-arm 通知。未增加 runtime helper
ABI，没有修改 GRH、GRH pass、XiangShan 或 benchmark 源码。

聚焦验证已通过：`test_grhsim_cpu_emit`（CTest 98.55 s；含编译墙钟 103.48 s）、
`test_grhsim_cpu_mapping`（IR 与 mapping 两项）、`test_grhsim_cpu_schedule`，以及
`run_hdlbits_grhsim_ir DUT=086`、`DUT=097`。新增 fixture 在普通 helper 和每 op
独立 helper 两种情况下各检查 24,576 次求值，覆盖重复局部结果、重复 boundary
结果、独立使能寄存器、符号/位宽归一化、减法输入顺序、带参数切片、重复 init 和
连续 eval；两种情况都使用 ASan/UBSan。还拒绝错误、逆序、缺项的计划，并验证
新旧 JSON 格式，全部通过。

## 尝试 A 的完整验证配置

下面命令均从根仓库运行。全新 `flow-final` 不复用前期生成文件和 emu object；
`CCACHE_DISABLE=1` 确保 fresh 编译。生成计时包含 Make 启动、包安装、SV ingest、
完整转换和 C++/Makefile 发射，不用恢复 checkpoint 的时间替代。生成期间完成上述
小型 schedule/HDLBits 回归；正式仿真期间不并行运行编译、profile 或大型分析。

```bash
node_dir="$PWD/ptmp/no00034_local_cse_probe"
flow="$node_dir/flow-final"
old="$PWD/ptmp/no00033_batch_probe/flow-cache-final"
mkdir -p "$flow" "$node_dir/work-tmp" "$node_dir/pip-cache" "$node_dir/ccache"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export CCACHE_DIR="$node_dir/ccache" CCACHE_DISABLE=1
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00034_reuse_final_generate > "$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00034_reuse_final_compile > "$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-reuse" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=108.078 \
  > "$node_dir/formal-reuse.log" 2>&1
```

筛选通过 `benchmark_grhsim_ir` 的同一参数执行，但 new 指向前期 `flow`，output
为 `screen-a`，`GRHSIM_IR_BENCH_PAIRS=1`。静态分析使用
`make analyze_grhsim_compute_storage GRHSIM_COMPUTE_STORAGE_MODEL=...` 与
`make analyze_grhsim_cpu_code GRHSIM_CPU_CODE_OLD=... GRHSIM_CPU_CODE_NEW=...
GRHSIM_CPU_CODE_PHASE_ONLY=1`，均显式传入 `PYTHON="$PWD/.venv/bin/python"`。
前者脚本随本节点归档，统计字符串 ID 从 1 开始，且以真实 helper ranges 为边界。
最终核对另传 `GRHSIM_COMPUTE_STORAGE_REFERENCE="$old/xiangshan_grhsim_ir.json"`。

完整生成实测 **700.43 s**，exit 0，低于 1800 s；新 checkpoint 往返字节一致。
独立 Python 重建确认最终 32,312 条计划与 C++ 生成的序列完全一致；与 NO00033
逐节比较，语义 sections、分区、存储和 schedule 全部相同，只有 layout 末尾新增
复用表。最终生成的 C++/header/Makefile 与尝试 A 筛选版逐文件相同；目录比较时
排除了编译过程的 `.o`、`.a`、`.tmp`，首次未排除这些文件导致的 diff 非零不表示
源码差异。fresh 编译实测 **218.48 s**，exit 0，低于 1800 s。正式六次测量已按
预注册顺序启动，使用该最终构建；期间无并行编译、profile 或大规模分析。

尝试 A 的最终六次结果如下，均退出 0、NEMU 无 mismatch，并满足同一预期终点。

| 运行 | Host (s) | emu 墙钟 (s) |
|---|---:|---:|
| old1 | 107.811 | 107.84 |
| new1 | 108.555 | 108.58 |
| old2 | 108.348 | 108.38 |
| new2 | 108.779 | 108.81 |
| old3 | 108.410 | 108.44 |
| new3 | 107.070 | 107.10 |

old 均值 **108.189667 s**、样本 SD **0.329397 s**；new 均值
**108.134667 s**、样本 SD **0.928806 s**。均值降低仅 **0.050837%**，
Cohen d(new−old) **−0.078927**，Cliff delta **+0.333333**，U_new **6**，
精确单侧 p **0.8**；max(new) 108.779 > min(old) 107.811，秩次门槛失败。
尝试 A 判定 **REJECTED**：源码冗余确实存在，但这一单独实现未证明真实收益。
不选择较快的 new3 或早期筛选替代完整统计。A 候选 emu SHA256 为
`88293470921a01939236455ae67b7ef3212983da78804ed448c09713a78e0747`。

## 尝试 B：由使用范围驱动的标量局部变量

尝试 A 的完整六次未证明收益，已经否定其单独使用的效果。
因此扩大机制覆盖面：不只共享约 1% 的重复表达式，还把仅在一个 helper 内使用的
中间标量保留为 C++ 局部变量，去掉把 SSA 中间值反复物化为 `cpu_local` 槽的要求。
这是同一节点内的计算表示优化，不开始新节点。

新假设：数百万标量中间值的 byte-arena 表达阻碍编译器跨别名优化；显式局部变量
能减少 load/store 和无用 frame 初始化。部分代码原本已被编译器标量化，因此收益
可能接近零；若新代码规模与运行时间均未改善，则否定此机制。局部目标是覆盖多数
仅在 helper 内流转的 two-state 标量，争取百分之一至数个百分点的收益；不声称解决
全部 2.3 倍差距。

`CpuDataLayout::scalarLocals` 记录符合以下条件的 ValueId：非 constant 的纯
`core.compute.*`，无对象引用，结果 1–64 位两态，原 slot 为 partition-local，
producer 和所有 consumer 在同一最终 helper。emitter 按原有表达式归一化规则生成
`const auto`，并让下游引用局部变量。跨 helper、跨分区、commit/event、宽值和
带副作用值均保留原来的存储策略；不新增 runtime helper 或宽值复制。canonical
slot 表保持原样，提升表可序列化并由 verifier 完整重建。

尝试 B 沿用已预选基线 108.078 s、截止 162.117 s、CPU2 单线程 100k 和全部输入。
先运行独立 old/new 筛选，若可行，再在新目录完成完整生成和 fresh 编译，正式顺序仍
为 old1/new1/old2/new2/old3/new3；尝试 A 样本不并入 B 的任何统计。

B 的聚焦回归通过：emitter CTest **85.28 s**，IR/mapping/schedule 均通过；
新增的局部变量完整性/错误 boundary 提升检查和 helper 拆分检查也通过。三项目标
合计含构建墙钟 **108.21 s**。使用新增 `GRHSIM_REEMIT_REMAP=1` 选项从 A 的
checkpoint 重新执行 CPU mapping，未再执行任何语义变换；筛选重发射 **60.03 s**。
实际生成计划含 **2,851,956** 个 scalar locals、**32,312** 条 compute reuses，
其余分区、状态和依赖不变，编译及运行结果如下。

独立重建检查通过，两张计划表均与序列化结果一致；和 NO00033 的语义 sections、
partition、canonical storage、schedule 逐节相同。B 筛选 fresh 编译 **214.10 s**，
exit 0，启动前设 1800 s 截止。筛选目录为 `flow-scalar-probe`，运行输出为
`screen-b`，旧构建仍为 NO00033。

B 筛选两次均 exit 0、预期终点/NEMU PASS。old Host/emu 墙钟为
**108.116 / 108.15 s**，new 为 **111.754 / 111.78 s**，候选慢 **3.364904%**。
n=1+1 不用于宣称统计显著退化，但结果不支持投入正式验收，记 **REJECTED**，
未执行 B 的完整 SV 重生成和正式六次。大范围 SSA 局部变量并不能保证原生代码更优；
后续依据原生指令结构调整表示，不把该筛选包装为成功。

B 的静态 compute 指令为 **14,908,808**，比基线多 **113,407**；条件跳转为
**543,012**，多 **12,735**；ELF text 为 **103,313,844 bytes**，多 **401,104**。
因此并非成功消除存储后被对拍成本掩盖，生成的原生计算结构本身就变大了。不能从
该汇总单独断言寄存器溢出或分支预测是唯一原因。A/B 实现均撤回，未进入最终代码。

## 尝试 C：稳定 helper 输入缓存

根据 B 的结果保留原有中间值表示，把共享范围改为重复 boundary 输入加载。
`cpu.st.layout-data` 为每个最终 helper 统计 operand 使用次数，移除由该 helper
生产的所有 value，只缓存次数大于 1、非 constant、boundary、1–64 位 two-state
logic 的输入。新表 `CpuDataLayout::helperReadCaches` 保存
`{firstOp, values}`：firstOp 标识 helper 开头的 operation，values 按 ValueId 排序。
emitter 在 helper 开始声明 `const auto cpu_cached_value_*`，下游引用缓存；每次
helper 调用重新加载，不跨调用缓存。原来的 state-read cache 仍负责状态读取。

源的 producer 在当前 helper 外，单线程 compute 调用中源值稳定；当前 helper 的
任何结果即使是 boundary 都不缓存，避免读到该 helper 更新前的旧值。所有写入、
fanout 和 port-arm 行为保留。宽值不缓存，不新增宽数组临时量。完整计划由 verifier
重建；JSON 新增可选尾表，旧格式缺表时走普通读路径。预期覆盖面由实测统计确定，
希望通过减少重复稳定输入读取取得百分之一至数个百分点收益；若原生代码或 100k
筛选仍无改善，则否定。截止、输入、CPU2 和统计门槛沿用原预注册。

C 聚焦回归全部通过：emitter CTest **97.71 s**，IR/mapping/schedule 通过，三组
目标含构建墙钟 **120.57 s**。checkpoint 重发射 **58.09 s**。独立统计确认
**29,192** 个 helper 中有 **408,161** 个缓存项，覆盖 **1,767,421** 次 operand
引用，源码层面减少 **1,359,260** 次重复读取；实际机器指令能消除多少仍需比较。
缓存表与独立重建逐项相同，语义 sections、partition、storage、schedule 与 NO00033
一致。筛选目录为 `flow-readcache-probe`，使用 NO00033 原 checkpoint 和
`GRHSIM_REEMIT_REMAP=1` 重建 CPU mapping；未加载 A/B 的临时扩展格式。

C 筛选 fresh 编译 **215.71 s**。old Host/emu 墙钟 **108.079 / 108.11 s**，
new **104.745 / 104.77 s**，降低 **3.084781%**。两次均 exit 0、预期终点与
NEMU PASS；该 n=1+1 结果只支持进入正式验证，不计入最终六次。

静态 compute 指令 **14,795,401 → 15,005,705**（增加 210,304），条件跳转
**530,277 → 410,666**（减少 119,611）；ELF text **102,912,740 → 103,230,628**
bytes（增加 317,888）。commit 与 eval 指令不变；`other` 含 helper 和其余支持函数，
合计静态指令 **1,358,855 → 1,315,388**，不能全部归因于 helper。这些是静态数，
不能代替动态分支错失或加载次数。
源码读取去重不意味着总指令数下降，但能让编译器看到 helper 输入在本次调用中的
不变性，改变其布尔与控制流表达；这一点与条件跳转显著减少、筛选变快方向一致。
尚不足以把整个 2.3 倍差距归于单一根因。

## C 完整验证预注册

最终路径为 `ptmp/no00034_local_cse_probe/flow-readcache-final`，生成和编译命令
与 A 完整验证一致，但分别用 `RUN_ID=no00034_readcache_final_generate` 和
`RUN_ID=no00034_readcache_final_compile`。此目录全新，禁用 ccache，恢复 flat GRH
关闭。正式 benchmark output 为 `formal-readcache`，顺序及 baseline seconds
仍为 `old1/new1/old2/new2/old3/new3`、108.078。完整 SV→C++ 生成 **720.38 s**，
exit 0，低于 1800 s，checkpoint 往返字节一致；fresh 编译 **214.26 s**，exit 0，
同样低于 1800 s。两步均在启动前安装截止机制，未触发超时。最终模型的生成源码
以及 `libgrhsim_SimTop.a` 与 C 筛选版逐字节一致，因此静态代码证据适用于正式模型。
最终 emu SHA256 为
`8d61acafd3250768f0fade709ffce65c3fafc8b9a75c9fc9b0a8c0aa2af7dd42`。
最终缓存表再次通过独立重建，语义图、分区、canonical storage 与 schedule 和
NO00033 一致。正式六次测量见下文，筛选样本未混入正式统计。

最终新增 fixture 使用普通 body 与每 op 一个 helper 两种分块，各进行 24,576 次
eval 检查，覆盖符号/位宽转换、切片、独立寄存器使能和重复 init。另把 producer
重新合并到 helper，确认其 boundary 结果退出缓存；这直接检查不得提前读取内部
结果的安全条件。最终 emitter CTest **104.37 s**（含构建 **109.69 s**），
HDLBits 086/097 **1.85 / 1.83 s**，全部通过。代码实现、JSON 和安全约束详见
[CPU backend 文档](../wolvrix/docs/grhsim_ir/backends/cpu.md)；分析脚本为
[grhsim_compute_storage_stats.py](../scripts/grhsim_compute_storage_stats.py)。

## VALIDATED / ACCEPTED

正式运行窗口为 2026-09-16 05:29–05:40（Asia/Shanghai），严格按预注册顺序执行；
六次均 emu/Make exit 0，NEMU 无 mismatch，同一终点为 `instrCnt=240349`、
`cycleCnt=99996`、IPC `2.403586`、guest cycles `100001`、PC `0x80000c0c`。
没有 INVALID 样本、补跑或截止触发，正式期间无并行编译、profile 或大型分析。

| 运行 | Host (s) | emu 墙钟 (s) | 退出 / 对拍 |
|---|---:|---:|---|
| old1 | 107.175 | 107.20 | 0 / PASS |
| new1 | 103.949 | 103.98 | 0 / PASS |
| old2 | 108.431 | 108.46 | 0 / PASS |
| new2 | 104.107 | 104.13 | 0 / PASS |
| old3 | 108.437 | 108.47 | 0 / PASS |
| new3 | 105.727 | 105.75 | 0 / PASS |

Host old 均值 **108.014333 s**、样本 SD **0.726890 s**；new 均值
**104.594333 s**、样本 SD **0.984094 s**，绝对减少 **3.420000 s**，相对降低
**3.166246%**。Cohen d(new−old) **−3.953281**，Cliff delta **−1.0**，
Mann–Whitney U_new **0**、精确单侧 p **0.05**；
**max(new)=105.727 < min(old)=107.175**，满足预注册的真实性能门槛。
emu 墙钟 old 均值 **108.043333 s**、样本 SD **0.730365 s**，new 均值
**104.620000 s**、样本 SD **0.981478 s**，降低 **3.168482%**，方向一致。
new3 明显较慢，仍保留并计入全部统计；没有选择性删除波动样本。

最终旧/新二进制哈希在运行后与预注册一致。完整生成、fresh 编译、所有聚焦回归、
100k 正确性与六次统计门槛均通过，节点唯一最终判定为 **ACCEPTED**。

最终完整复现命令如下；`flow-readcache-final` 必须为新目录。输出目录和所有临时
环境仍位于 `ptmp/`，生成与编译各自在启动前设置 1800 s 截止，benchmark 目标
为每次 emu 安装 162.117 s 截止并检查端点、对拍、输入和二进制身份。

```bash
node_dir="$PWD/ptmp/no00034_local_cse_probe"
flow="$node_dir/flow-readcache-final"
old="$PWD/ptmp/no00033_batch_probe/flow-cache-final"
mkdir -p "$flow" "$node_dir/work-tmp" "$node_dir/pip-cache" "$node_dir/ccache"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export CCACHE_DIR="$node_dir/ccache" CCACHE_DISABLE=1
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00034_readcache_final_generate > "$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00034_readcache_final_compile > "$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-readcache" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=108.078 \
  > "$node_dir/formal-readcache.log" 2>&1
```

## 根因结论与范围

已证实的链条是：最终 CPU helper 对稳定 boundary 输入存在大量重复引用；先前 IR
layout 只描述各 value 的存储，没有把 helper 调用期间的输入不变性明确传给 emitter；
新增可校验缓存计划后，编译器生成的 compute 条件跳转少 **22.556324%**，六次交替
证明 Host 快 **3.166246%**。源码层面去重是机制，静态分支变化是编译结果，两者
不能直接换算为动态分支错失或执行次数；本节点没有测硬件计数器。

A/B 的反例排除了“只要源码 CSE 或标量化，原生代码就会更快”的泛化判断。保留 C
是因为其正确性、覆盖面和交替统计共同支持，而非它源码更短。相比归档 gsim
**46.965 s**，当前 new 均值为 **2.227070×**，仍多 **57.629333 s（122.706980%）**；
gsim 不在本次窗口内，该比例只表示剩余目标差距，不是本节点统计对照。
主要差距仍在分散的 compute 求值与边界表达，后续应研究更高层的依赖锥/执行融合，
而不是重复微调同一缓存参数。本节点完成后停止，不自动开始 NO00035。

最终仅保留 C 的 model/layout/JSON/emitter 扩展及其测试、文档；A/B 代码未提交。
最终提交前对 JSON 可选尾表解析做了逗号处理修正；修正后的
`test_grhsim_cpu_emit`、`test_grhsim_cpu_mapping`、`test_grhsim_cpu_schedule` 均通过，
总墙钟 **101.26 s**（exit 0）。该修正只影响 checkpoint 读取，不改变已测量生成
源码或 emu 二进制。所有报告内关键证据已列出，不提交生成代码、日志、profile、波形或二进制。
子模块实现提交在最终集中归档时填入，随后根仓库提交子模块指针、报告、索引及 goal。
