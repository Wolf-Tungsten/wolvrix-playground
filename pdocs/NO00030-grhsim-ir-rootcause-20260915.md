# NO00030：共享标量计算局部化与执行边界成本

日期：2026-09-15。当前阶段：`ACCEPTED`；候选 B 的共享标量可逆运算局部化
通过六次交替复测，Host 均值 124.085000→121.836667 s，降低 **1.811930%**，
U=0、单侧精确 p=0.05。100k 等价、完整生成与 fresh 编译门槛均通过。
候选 A 的统计失败完整保留在本报告中；最终代码和档案随节点统一提交。

## 假设、根因证据与边界

本节点验证一个 GrhSIM IR 机制：把廉价的共享纯计算复制到各 compute consumer，
使分区能将它吸收到 consumer 的依赖锥，消除共享中间值的 boundary 存储、
变化比较和通知。它有意在局部撤销 CSE，以重复一条廉价运算换取执行局部性。
不修改冻结 GRH、GRH pass、XiangShan 或基准测试源程序，不按模块名称触发优化。

确切 NO00029 基线的 100k 诊断把瓶颈限定在生成模型内：

- 一次 phase-timing 运行的 Host 为 123.899 s，model_step 为 123.406787 s，
  占 99.602730%；difftest 仅 0.343403 s。
- 另一次 runtime-profile 运行记录 evals=200102、rounds=402258，
  eval=123.344359302 s；compute=94.705334544 s（76.781245%），
  commit=26.689765648 s（21.638416%），publish=1.801296243 s（1.460380%）。
  两次均到达下文的正确 100k 终点；这些插桩时间不进入性能统计。
- ELF text：旧 IR 为 114,297,322 bytes，已归档 gsim 为 55,477,514 bytes。
  代码体积差提示布局和指令工作集值得进一步研究，不能直接换算为运行时间。

因此，NEMU 对拍不是当前主要成本。compute 占比大也不意味着所有 compute 时间
都是冗余调度。本节点只能量化一个具体机制的贡献，不能声称已经证明或解决全部
约 2.6 倍差距。原 goal 的 2.719578 倍与其列出的 122.018/46.965 s 不符，实际
为 2.598062 倍、相差 75.053 s；本次纠正这项历史算术错误，不把纠正算作优化收益。

局部目标预注册为 1–5% 的探索范围，不是接受硬阈值。可证伪标准是目标共享
boundary/通知应减少、100k 行为保持，并且六次交替结果能够排除噪声。
若静态结构未改善或性能不能区分，则不能以本机制完成节点。

## 同一段逻辑的结构对照

选取 `LoadUnit_2.loadTrigger` 作为诊断窗口；这个名字只用于读取生成产物，
不参与 pass 的选择规则。gsim 的三个 lane 是三个 `SUPER_VALID members=18`
块，每块核心代码约 39 行，使用 typed locals，末尾比较可观察结果并更新
packed active flags。IR 中相应区间为 93 个 operation：92 个在旧 task 1630，
共享的一位 `not`（op 2973584）在 task 174。

跨 task 本身不是 gsim 独有或 IR 独有。gsim 也将该 `!isPrefetch` 保存为
typed member，并唤醒多个块。两者差异在于 IR 将这个值单独建模为 boundary，
由 producer 执行旧值比较、写回和通知，再由 consumer 读取。

旧图：

```text
op 2973070: x = state.read(s1_in_r_isPrefetch) -> value 2853042
op 2973584: t = not(x)                       -> value 2855366
op 2973585 / 2973601 / 2973617 / 2973650: and(t, lane_condition)
op 2975411: and(t, s2_condition)

state.read / not -> task 174
四个 lane consumer -> task 1630
s2 consumer -> task 3319
```

旧 task 174 先将 state 读到 boundary 979992，再产生并比较 boundary 981594：

```cpp
const auto next = bool(~cpu_at<bool>(cpu_boundary.get(), 979992) & 1);
cpu_changed |= cpu_at<bool>(cpu_boundary.get(), 981594) != next;
cpu_at<bool>(cpu_boundary.get(), 981594) = next;
// fanout 到 consumer 的活动标记
```

根因链可以在已跟踪源码中逐层核对：

1. [buildNodes](../wolvrix/lib/grhsim/backend/cpu_partition.cpp) 逆拓扑吸收 producer，
   当多个 consumer 的 owner 不同就停止吸收；每个 op 仍只归一个 node。
2. [buildLayout](../wolvrix/lib/grhsim/backend/cpu_layout.cpp) 将跨 owner 使用的值
   分配为 Boundary，而不是 PartitionLocal。
3. [CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp) 根据 slot 生成 arena
   访问，并为有通知的结果生成旧值比较和激活。

目标模块有 528 个 state、1,054 个直接 state read/write；沿其 527 个写目标
回溯得到 39,231 个 producer operation，跨 282 个 task。全模型有 4,896 个 task，
不能拿它与仅包含该模块的 64 个 gsim subStep 相除。这个诊断窗口证明了分区
与物化的实际路径，不提供各模块的运行时占比。

## IR 变换及语义约束

实现为 [grhsim.clone-shared-compute](../wolvrix/lib/grhsim/pass/clone_shared_compute.cpp)，
在 `grhsim.canonicalize-compute` 之后、CPU mapping 之前执行。
[pass 文档](../wolvrix/docs/grhsim_ir/passes/clone-shared-compute.md) 给出完整规则：

- 候选 B 接受无 parameters/objectRefs、单结果的 two-state 标量可逆运算：
  同类型 1–64 bit `not`，输入/结果均为一位的 `logicNot`，以及恰有一个常量
  operand、全部同类型 1–64 bit 的 `xor/add/sub`。减法保留原操作数顺序。
  非常量源必须已有多个 distinct consumer，避免仅把 boundary 向上游搬移。
- 不复制读取本身。只按语义、位宽和 distinct consumer 数选择，fanout 默认 2–8；
  全模型最多新增 250,000 个 op，预算不足时整组跳过。
- 每个 compute consumer 一个副本，同一 consumer 的重复操作数复用同一个副本。
  非 compute consumer 保留原 producer；只删除本次重写后无用户的原 producer。
- 连续候选从下游向上游处理，每次立即重写并更新用户列表；上游向下游新副本
  克隆，不向已删除的原 producer 克隆。按当前存活 fanout 重新检查上限和预算，
  候选环保持不变。
- state、初始化、history、memory access、commit 和外部调用保持。
  例如 `regWrite(enable, t, mask, clock)` 的四个 operands 依次为使能、数据、
  位掩码和事件值；如果它读取原 `t`，该 producer 和提交前快照仍保留。
- 重写后统一 compact，重建密集 ID 和操作数池；SemanticTransform 使旧 mapping
  失效，再重新构建依赖、布局和调度。后续不能再运行 CSE 将副本合回去。

输入/输出例子：

```text
x = state.read(q)
t = not(x)
y = and(t, a); z = or(t, b)
raw = output(x)
=>
x = state.read(q)
ty = not(x); y = and(ty, a)
tz = not(x); z = or(tz, b)
raw = output(x)
```

每个副本仍依赖同一读取值，所有唤醒边由正常 mapping 生成，未绕过固定点或
提交机制。XiangShan 和共享的 HDLBits IR pipeline 默认启用；XiangShan 可用
`XS_WOLF_GRHSIM_IR_CLONE_SHARED_COMPUTE=0` 建立对照。

## 候选 A 静态证据

候选 A 仅支持直接 state/input read 后的 1–8 bit `not/logicNot`。
以下比较确切 NO00029 模型与候选 A 完整 SV 路线生成的模型。
由 [分析脚本](../scripts/grhsim_localization_stats.py) 通过 Make 读取 IR 与 C++；
C++ 词项次数是静态出现次数，不是运行时调用次数。

| 指标 | old | new | 差值 |
| --- | ---: | ---: | ---: |
| operation | 3,937,483 | 3,942,995 | +5,512 |
| value | 3,713,085 | 3,718,597 | +5,512 |
| state | 464,343 | 464,343 | 0 |
| node | 1,079,025 | 1,076,427 | −2,598 |
| supernode | 35,627 | 35,673 | +46 |
| active word | 4,391 | 4,396 | +5 |
| task / emit function | 4,896 | 4,901 | +5 |
| boundary value | 897,056 | 894,636 | −2,420 |
| object bytes | 25,862,312 | 25,862,312 | 0 |
| boundary bytes | 2,223,168 | 2,220,776 | −2,392 |
| runtime bytes | 5,349 | 5,354 | +5 |
| task C++ bytes | 1,109,025,895 | 1,108,937,232 | −88,663 |
| 全部 C++ bytes | 1,172,616,999 | 1,172,561,475 | −55,524 |
| task 中 boundary.get() | 5,162,350 | 5,149,901 | −12,449 |
| task 中 objects.get() | 918,062 | 923,351 | +5,289 |
| task 中 cpu_local | 5,993,796 | 6,009,488 | +15,692 |
| task 中 cpu_changed_ | 1,898,961 | 1,891,786 | −7,175 |
| task 中 cpu_flags[ | 520,441 | 517,701 | −2,740 |
| task 中 cpu_pflags[ | 237,723 | 237,719 | −4 |
| ELF text bytes | 114,297,322 | 114,205,174 | −92,148 |

实际克隆 3,163 个根的 8,668 个 consumer，删除 3,156 个无用户根，保留 7 个
仍被其他消费者使用的根。8,497 个副本成为 PartitionLocal；171 个仍因正常
分区容量等约束成为 Boundary。增加运算不等于增加调度成本，但任务数也没有下降；
结果不支持“只要 task 文件变少就会更快”的解释。

目标 `!isPrefetch` 的五个副本全部成为局部 slot：

| 原 consumer | 新 not op | 新 consumer op | task | 局部 offset |
| --- | ---: | ---: | ---: | ---: |
| 2973585 | 3938586 | 2971869 | 1634 | 189 |
| 2973601 | 3938587 | 2971885 | 1634 | 202 |
| 2973617 | 3938588 | 2971901 | 1634 | 203 |
| 2973650 | 3938589 | 2971934 | 1634 | 190 |
| 2975411 | 3938590 | 2973683 | 3324 | 61 |

state read 仍在 task 174，新的 value 2851325 对应 boundary 978536。
task 1634 已生成下面的形式，原 not 的持久 boundary 和 changed 比较消失：

```cpp
cpu_at<bool>(cpu_local, 202) =
    bool(grhsim_trunc_u64(~cpu_at<bool>(cpu_boundary.get(), 978536), 1));
// 紧接着由本 task 的 and 消费这个局部值
```

总代码只减少 0.004735%，ELF text 只减少约 0.081%；如果运行获益，不能归因为
大规模代码压缩。更直接的机制是减少选中共享值的物化、比较和传播，但仍有大量
其他 boundary 和 compute 成本未被覆盖。

## 节点内未接受的尝试与修正

| 尝试 | 证据与判定 |
| --- | --- |
| batch64 文件打包 | 恢复 flat GRH 生成约 178.072 s，task 4896→522，task C++ 1,109,025,895→1,080,109,637 bytes；已有编译只留下 149 个 object，无 emu、无可靠完整编译计时。INCOMPLETE，未运行仿真，不作为收益证据。 |
| scalar-anchor | 将共享标量锚定到第一个 consumer，环检测拒绝 306,403 次、接受 196,728 次；node=869,947。目标 not 仍在 task 165，consumer 在 1553/1554/2900，boundary 和变化通知仍在；全局 task 4879，但 boundary 词项反增 11,775、changed 词项反增 8,900。对目标机制静态证伪，REJECTED；未执行正式 emu 对比，代码已撤回。 |
| 早期 clone screen1–7 | 恢复生成内部耗时分别 320.384/171.406/172.708/174.407/169.022/168.074/167.740 s。其中多次混入 512 行打包配置；未留下足以归因每版实现的完整源码差异和六次交替记录，不追认其性能。 |
| 早期单次 smoke | 留存 127.403、124.020、120.949 s 三个 100k Host 终点，均到达目标 PC/instr/cycle，但不是同窗交替对照，且不足以归档各版退出状态。只保留过程事实，不计入性能统计。 |
| 固定 8192 行的 fair 初筛 | 同窗 old/new Host 124.133/122.471 s，emu wall 124.16/122.50 s，Make/emu exit 0/0，精确终点一致。1.338887% 仅为 n=1+1 筛选信号，p=0.5；使用的旧克隆实现并非最终版。 |
| 引用与池修复 | 审查修复向 IR 池追加时复用池内引用、重复 operand 多次克隆及预算中途截断；只删除本次变换的无用户根。 |
| 测试发现的 JSON 问题 | 根被 commit 保留时没有删除 op，却留下替换后的旧 operand 范围；round-trip 报 header 42 operands / payload 32。改为每次重写后统一 compact，测试和 A 的完整模型往返均通过。 |

fair 初筛候选 emu SHA-256 为
`bca39d2c3fe06edb95651e4bd3dcf576042f957b4e309f0112ad7a25a6373dd0`。
它比 A 定稿模型少 1,261 个 operation 和 98 个 object reference，包含此前更广的
窄操作死代码清理；A 定稿只删除本次克隆后无用户的根。因此不能把 fair 的
1.338887% 直接当成 A 的收益。它的计时没有混入 A 的正式六次。
上述 REJECTED/INCOMPLETE 都是节点内部过程；
本节点最终必须以经统计确认的收益收尾。

## 输入身份、环境与复现

- 根基线 `89bb68f`；wolvrix 基线
  `a318548b956ae83cc9d3201b4d6ba935cee4439f`（NO00029）。
- XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`；
  XiangShan 和 HDLBits 子模块工作树均干净。
- CoreMark SHA-256：
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- NEMU SHA-256：
  `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
- 新旧 flat GRH 均为
  `518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`，
  证明冻结输入与前置 GRH 路线一致。
- 候选 A IR 与 fresh-session round-trip 均为
  `a26b585465cf6195ae783879e39d4083f7a06e9b8c86eacfe21c9512c4622e75`。
- old emu：
  `339ce7e63fb2cb1c6f8d6a131be78caec9ad3367e0dfb93d8c8bcfcb7b6e5bbf`。
- 候选 A emu：
  `1303fbb4f4e1e876227934dfb2480bb68d4ae56a847e5d86c0b509584b1b9efb`。
- 主机 AMD Ryzen 9 7950X3D，16 核/32 逻辑 CPU，内存约 187 GiB；
  仿真固定 CPU 2、单线程，100000 cycles，所有 waveform/trace/progress/profile 关闭。
  精确终点为 instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c。
- 预选 NO00029 三次 Host 均值 122.697333 s，仿真止损 184.046 s（1.5 倍）。
  生成和编译分别安装 1800 s 进程组截止；失败立即停止，超时产物隔离。
- 正式顺序预注册 old1/new1/old2/new2/old3/new3，主指标 Host，另记 emu wall。
  要求 max(new)<min(old)，报告均值、样本 SD、效应量、单侧精确 U/p；
  不使用跨窗口历史数据替代本次 old 三次。

从根目录执行（换用不存在的新 flow/benchmark 目录可复现）：

```sh
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1
export CMAKE_BUILD_PARALLEL_LEVEL=32
node="$PWD/ptmp/no00030_localize_20260915"
flow="$node/flow-bijective-final"
export TMPDIR="$node/work-tmp" PIP_CACHE_DIR="$node/pip-cache"
mkdir -p "$flow" "$TMPDIR" "$PIP_CACHE_DIR"

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD="$flow" XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00030_bijective_final_generate > "$flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00030_bijective_final_compile > "$flow/compile.log" 2>&1

make --no-print-directory benchmark_grhsim_ir PYTHON=.venv/bin/python \
  GRHSIM_IR_BENCH_OLD=ptmp/no00029_literal_specialization_20260914_01/flow-canonical-final \
  GRHSIM_IR_BENCH_NEW=ptmp/no00030_localize_20260915/flow-bijective-final \
  GRHSIM_IR_BENCH_OUTPUT=ptmp/no00030_localize_20260915/formal-bijective \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=122.697333
```

实际执行先检查前一步 exit；失败不进入下一步。生成/编译边界都是 Make 启动
到完整目标结束。运行由 [benchmark 脚本](../scripts/benchmark_grhsim_ir.py)
预登记二进制与输入哈希，然后调用已有 emu Make 目标，显式设置单线程、
CPU/100k/trace 参数，以 timeout 包住 emu 进程组，监视运行日志中的失败。
emu wall 由只包住 emu 的 /usr/bin/time 记录，Make 等待时间另存，不代替仿真时间。
原始日志、JSON、生成代码、profile、二进制均留在 ptmp，不提交。

## 候选 A 验证与门槛

- `make test_grhsim_cpu_mapping`：IR 和 mapping 两项通过，覆盖重复操作数、
  类型/参数/fanout/预算保护、幂等性及 JSON 往返。
- `make test_grhsim_cpu_schedule`：通过，调度实现未修改。
- `make test_grhsim_cpu_emit`：最终全套 69.54 s 通过；新增两个布局各运行
  24,576 次 oracle 检查，包含输入变化、两级状态提交前快照、重复 eval/init、
  跨分区通知，启用 ASan/UBSan。新 fixture 的一处 auto 声明编译错误已修正。
- `make run_hdlbits_grhsim_ir DUT=086 SKIP_PY_INSTALL=1` 与 DUT=097：
  分别通过字节使能寄存器和下降沿事件锁存检查，使用最终已安装包。
- `make test_benchmark_grhsim_ir`：两项通过，检查失败/不完整终点拒绝及
  包含 ties 的统计门禁。
- 完整 SV→C++：Make wall **989.33 s**、exit 0；包含解析器依赖重建。
  IR 路线内部 **658.888 s**，其中 clone pass **0.577 s**；
  fresh-session JSON round-trip 逐字节一致。
- fresh C++ 编译：**236.86 s**、exit 0，32 路，未从筛选目录复制 object/library。
  两个 1800 s 截止均未触发。最终源文件哈希与启动时一致。

## 候选 A 正式六次结果：REJECTED

第一轮固定源码六次数据如下，均为 100k、CPU 2、单线程，Make/emu exit 均为
0/0，均达到精确 PC/instr/cycle/guest 终点，无 NEMU mismatch。

| 顺序 | Host s | emu wall s |
| --- | ---: | ---: |
| old1 | 123.271 | 123.30 |
| new1 | 123.088 | 123.11 |
| old2 | 123.962 | 123.99 |
| new2 | 121.319 | 121.35 |
| old3 | 124.238 | 124.27 |
| new3 | 123.274 | 123.30 |

old 均值 123.823667 s、样本 SD 0.498121 s；new 均值 122.560333 s、样本 SD
1.079041 s，表观改善 1.020268%。Cohen's d（new−old）=−1.503300，Cliff's
delta=−0.777778，new 的 U=1、单侧精确 p=0.10。max(new)=123.274 s 比
min(old)=123.271 s 慢 0.003 s；不能因只差 3 ms 就放宽预注册秩次门槛。
本轮判定 REJECTED（收益未排除噪声），不是节点最终判定。

## 候选 B：共享标量可逆运算

A 失败后先测算反向无用途链清理的覆盖面，只有 10,461 个 operation，约占
全模型 0.27%；未实现额外 DCE。A 的主要限制是覆盖太窄，不足以稳定排除约
1 s 的波动。B 扩展同一局部化机制，但要求被克隆运算是非常量输入上的双射：
`not`、一位 `logicNot`、常量 `xor` 及模 2^width 的常量 `add/sub`。
双射满足 `f(x_new) != f(x_old)` 当且仅当 `x_new != x_old`，因此被删除的
结果比较没有额外过滤能力；并要求 `x` 已共享。多位逻辑非及有宽度变化的
运算不满足该条件，明确排除。

在旧模型上的静态候选计数为 34,453 个根，按原 fanout 估算 91,446 个副本：

| 运算 | 根 | 原 fanout 的 compute 副本 |
| --- | ---: | ---: |
| not | 19,690 | 55,806 |
| logicNot | 11,272 | 28,569 |
| add | 3,210 | 6,466 |
| sub | 212 | 467 |
| xor | 69 | 138 |

这不是最终克隆量：连续候选的逆拓扑展开会改变上游 fanout，上限检查可能跳过
整组。预期收益仍为探索性的 1–5%，不能由 op 数直接换算；若 boundary/比较不
下降、等价性失败、截止触发或新的六次交替秩次仍不分离，则本次尝试不被接受。
下一轮使用全新目录和独立预登记的 old1/new1/old2/new2/old3/new3；A 的所有
有效样本完整保留，不混入 B 的统计。

B 已通过 `make test_grhsim_cpu_mapping test_grhsim_cpu_emit`，emit suite 为
69.56 s。直接 IR 回归增加相邻候选及逆序插入、展开后的 fanout/预算限制、
候选环与 JSON 往返；生成 C++ 的两个布局各有 24,576 次 oracle 检查，覆盖
64 位 not/xor/add/sub 与 reversed-sub、连续 not→add、整数回绕、重复 eval/init
及状态提交前快照，启用 ASan/UBSan。两项 HDLBits（086、097）也在安装 B 后
通过。测试启动曾因未设置 `WOLF_ENV_SOURCED` 被 Make 拒绝，补全环境后重跑
成功；该次未执行构建或测试，不计入上述耗时。

## 候选 B 完整路线与静态结果

完整 SV→C++ Make 墙钟 **660.65 s**、exit 0；内部流程 **648.949 s**，其中
局部化 pass **0.862 s**。生成从 SV 开始，resume=0；flat GRH 哈希与上文冻结
基线一致。独立会话的 IR JSON 往返逐字节一致，二者 SHA-256 均为
`9eb35c409cf003b3950c44aaba6dae5fe6c754c9c7cfd5a5ea2f92f579301cf0`。
生成前后冻结的 pass、注册、CMake、Makefile 和 Python 入口哈希均一致；其中
局部化源文件 SHA-256 为
`4cf91e35949b3f199a38a50405737655594a95418d7a34fa9c8edc86dce7e9b5`。
fresh C++ 编译 **227.48 s**、exit 0，32 路；从新目录构建，没有复制旧 object
或 library。两个 1800 s 截止均未触发。B emu 的 SHA-256 为
`9bed364b7c5339bcf64b1a549f2716722e69842d865297d4fcd684617062d605`。

实际对 34,447 个根新增 **91,408** 个副本，删除 **34,356** 个无用户根，
保留 91 个仍有非 compute 用户的根。89,339 个副本为 PartitionLocal，
2,069 个仍是 Boundary；相邻候选的当前 fanout 检查使最终数量不同于原图估算。

| 指标 | NO00029 old | B | 差值 |
| --- | ---: | ---: | ---: |
| operation | 3,937,483 | 3,994,535 | +57,052 |
| value | 3,713,085 | 3,770,137 | +57,052 |
| state | 464,343 | 464,343 | 0 |
| node | 1,079,025 | 1,050,544 | −28,481 |
| supernode | 35,627 | 36,240 | +613 |
| active word | 4,391 | 4,467 | +76 |
| task / emit function | 4,896 | 4,972 | +76 |
| boundary value | 897,056 | 875,735 | −21,321 |
| object bytes | 25,862,312 | 25,862,312 | 0 |
| boundary bytes | 2,223,168 | 2,204,184 | −18,984 |
| runtime bytes | 5,349 | 5,425 | +76 |
| task C++ bytes | 1,109,025,895 | 1,112,625,131 | +3,599,236 |
| 全部 C++ bytes | 1,172,616,999 | 1,176,286,107 | +3,669,108 |
| task 中 boundary.get() | 5,162,350 | 5,103,926 | −58,424 |
| task 中 objects.get() | 918,062 | 923,491 | +5,429 |
| task 中 cpu_local | 5,993,796 | 6,140,148 | +146,352 |
| task 中 cpu_changed_ | 1,898,961 | 1,870,938 | −28,023 |
| task 中 cpu_flags[ | 520,441 | 519,807 | −634 |
| task 中 cpu_pflags[ | 237,723 | 237,707 | −16 |
| ELF text bytes | 114,297,322 | 112,707,382 | −1,589,940 |

boundary 数下降 **2.376775%**，约为 A 减少量的 8.81 倍；但 task 增加
1.552288%，源码体积增加 0.312899%，不能从 boundary 的减少直接推出同幅度
运行收益。这是局部值/比较与重复运算、分区布局之间的交换，最后按未插桩实测
判定，不将 C++ 词项数当成动态调用数。
编译后 text 减少约 1.391056%，说明局部化给编译器留下了更小的最终代码，
即使 IR op 与源码数量增加；仍不能单独据此推导运行时间。

同一 `!isPrefetch` 窗口在 B 中仍有五个局部副本：op 3973605–3973608 与其
and consumer 同在 task 1679（local offsets 188/201/202/189），op 3973609
与 consumer 同在 task 3381（offset 62）。state read 为 op 2946004、task 173。
这证明目标中间值已进入消费锥；仍未证明该单一窗口占总仿真时间的比例。

## NO00028–30 方向复盘

这三个节点从通知实现（NO00028，已确认 2.447969%）转到 IR 代数归一化
（NO00029，已确认 2.896547%），再转到本节点的共享计算局部化。它们分别
减少通知调用、删除冗余运算、改变值的物化位置，不能把不同时间窗口的均值
直接连乘后当成一次同窗实验。本节点 B 的接受与当前最佳值以下文正式结果为准。

目前证据排除了几种归因或继续投入的依据：NEMU 不是主要耗时；生成文本中的
helper 出现次数不等于动态调用次数；仅减少 task 文件数没有完成的编译/仿真
证据；scalar-anchor 增加了目标 boundary/比较；窄克隆 A 的收益未排除噪声；
一般死锥清理只有 0.27% 的静态 op 覆盖，尚不能据此支持它是主要方向。
这些结论不等于证明所有相关方案永远无效，尤其未把静态 op 比例当成时间上界。

剩余差距仍主要位于生成模型执行中。B 后仍有 875,735 个 boundary、1,050,544
个 node 和 464,343 个 state；此前 compute 的 76.78% 相位占比只能用于定位
调查方向，不能全部称为冗余调度。后续更值得验证的是在 GrhSIM IR 中按共同
输入、可观测输出和依赖构造多个输出的计算锥，联合决定共享值的物化与局部
重算，测量实际执行次数及加载/比较成本。应先取得动态覆盖证据，再扩展机制；
不继续仅围绕 fanout 参数或单个 helper 的写法微调。

## 候选 B 正式六次结果与最终判定

2026-09-15 19:51–20:04（Asia/Shanghai）按预登记顺序执行；同一主机、CPU 2、
单线程、100k、profile/trace 关闭。六次 Make/emu 均 exit 0/0，均到达
instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c，NEMU 无 mismatch。
没有 INVALID、补跑、超时或被丢弃的有效样本；新旧二进制在测量后哈希未变。

| 顺序 | Host s | emu wall s | Make/emu exit | NEMU |
| --- | ---: | ---: | --- | --- |
| old1 | 123.995 | 124.03 | 0/0 | PASS |
| new1 | 121.856 | 121.88 | 0/0 | PASS |
| old2 | 123.915 | 123.94 | 0/0 | PASS |
| new2 | 121.557 | 121.59 | 0/0 | PASS |
| old3 | 124.345 | 124.37 | 0/0 | PASS |
| new3 | 122.097 | 122.12 | 0/0 | PASS |

old 均值 **124.085000 s**、样本 SD **0.228692 s**；new 均值 **121.836667 s**、
样本 SD **0.270519 s**，节省 **2.248333 s（1.811930%）**。
Cohen's d（new−old）=**−8.976104**，Cliff's delta=**−1.0**。
max(new)=**122.097 s** < min(old)=**123.915 s**，间隔 **1.818 s**；
Mann–Whitney U_new=**0**，枚举 20 种 3+3 分组的单侧精确 p=**0.05**，通过
预注册秩次门槛。emu wall 均值 old/new 为 124.113333/121.863333 s，与 Host
方向一致。结果支持这个机器/输入/100k 配置下的局部收益，不从 n=3 推断其他
设计和工作负载都能获得同样比例。

完整生成 **660.65 s**、fresh 编译 **227.48 s** 均低于 1800 s；聚焦测试和
六次正确性通过，184.046 s 仿真止损未触发。本节点最终判定 **ACCEPTED**，
保留 B 的通用 GrhSIM IR pass 及其 pipeline 接入。A 的 1.020268% 表观变化
仍是 REJECTED 过程记录，不与 B 合并，不作为已证明收益。

当前最佳正式 new 均值为 **121.836667 s**。与沿用的 gsim 46.965 s 相比为
**2.594201×**，仍差 **74.871667 s**；这是追赶目标的量级对照，gsim 未在本
窗口重测，不能把跨窗口差值当成新的因果速度比较。本节点确认了廉价共享计算
的边界物化/比较是可削减的一部分成本，并未证明它解释了全部约 2.6 倍差距。

## Git 归档

wolvrix 最终提交为 **`75be3ad8a2508f49a0be92e31ddba8d77f0e9044`**
（`feat(grhsim): localize shared scalar bijections`），包含 pass、注册、构建接入、
IR/生成 C++ 回归及 pass/flow 文档。根仓库以包含本报告的提交记录对应子模块
指针、默认 pipeline、测量/分析 Make 工具、goal 和索引；每个仓库一个节点最终
提交，无阶段提交。生成代码、二进制、原始日志和 profile 留在 ptmp，未纳入归档。
最终检查确认 XiangShan 与 HDLBits 子模块无源码改动，冻结 GRH 与既有 GRH pass
未修改。
