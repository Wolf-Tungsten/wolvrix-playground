# NO00036：动态覆盖证据与下一步机制选择

日期：2026-09-16。当前阶段：**ACCEPTED（尝试 C）**。

根基线：根仓库 `0ab5f08`（NO00035 归档提交），wolvrix `ff83ba2`
（`feat: lower boolean muxes to bitwise selection`）。节点开始时两个工作树
均干净。NO00035 已完成；本节点由新的用户 goal 启动。

机器为 AMD Ryzen 9 7950X3D，16核/32逻辑CPU。冻结的 wolvrix 基线
`1fb8feb40d9bb7bca272bb4f04a069276a86be94`，XiangShan
`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`。CoreMark 输入 SHA256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，
NEMU `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

## 目标与起点

当前最佳（NO00035 正式 new）100k Host 均值 **102.506000 s**，归档 gsim
**46.965 s**，剩余 **2.182604×**。NO00035 的诊断确认 compute 占 eval
**77.02%**、热点分散（前10 task 仅占样本 4.19%），并留下明确指示：
后续应以**动态覆盖证据**区分选择计算、值物化与活动传播三类成本，再决定
更大依赖锥或执行机制的变换。本节点首先取得该证据，再据此选定机制。

不修改冻结 GRH、GRH pass、XiangShan 或基准源码；不按模块名匹配。perf 在
本机被 perf_event_paranoid=4 禁用，动态证据改由生成代码插桩获得。

## 静态证据（确切 NO00035 模型，3945332 ops / 3783436 values）

新增通用工具 `scripts/grhsim_op_mix_stats.py`（Make 目标
`analyze_grhsim_op_mix`）测得：

- op 分布：`and` 23.92%、`or` 18.01%、`mux` 14.90%、`concat` 5.88%、
  `sliceStatic` 5.06%、`bitSelect` 5.06%、`eq` 4.38%、`not` 3.22%、
  `logicNot` 2.43%、`add` 2.66%。一位两态布尔 op（and/or/not/logicNot/eq/
  reduceOr/bitSelect 及 1-bit mux）合计超过一半。
- boundary 结果 **835511** 个（占 value 22.1%），按生产者：`and` 29.96%、
  `or` 13.10%、`mux` 11.89%、`sliceStatic` 9.63%、`state.read` 8.07%、
  `eq` 6.35%、`bitSelect` 4.81%。
- supernode（含 commit 叶）36137 个：op 数 p50=120、p90=128、max=4096、
  均值 109.18；每 supernode boundary 结果数 p50=11、p90=64、均值 23.12。

## gsim 结构对照（build/xs/gsim 生成代码与 reference/gsim 源码）

- gsim 的 `SSimTop::step()` 是 **327 个 subStep 的固定拓扑序直线调用，无
  fixed-point 循环、无独立 commit 阶段**；寄存器 `reg = reg$NEXT` 是普通
  supernode，由 `$NEXT` 变化驱动，活动位跨 step 保持。
- 活动跟踪：每 supernode 1 bit（84643 位 = `activeFlags[10584]`），激活写
  为代码生成期预计算的立即数打包掩码，运行时不遍历边表。
- 只有 ~431k/2.7M（16%）信号有存储并参与比较/激活；supernode 体内 82%
  的值是 C++ 局部变量。
- 宽值用 clang `_BitInt` 原生表示；我们走 uint64 数组 + 指针 helper。
- 代码体积：gsim text 55.5 MB / 总指令 ~10.85M；我们 text 103.8 MB /
  仅 compute 即 15.2M 指令。指令缓存压力差近 2 倍。

## 动态覆盖插桩（诊断专用，默认关闭）

为区分三类成本，给 `cpu.st.emit-cpp` 增加 `--dynamic-stats` 选项
（默认关闭；关闭时生成代码与既有路径逐字节一致，由 emitter 测试与
checkpoint 逐字段比较验证）。开启时生成以下计数器，在
`dump_runtime_profile()` 末尾以 `[grhsim-dyn]` 行输出（运行设
`EMU_RUNTIME_PROFILE=1` 时由既有 harness 调用）：

- 每个 compute supernode：激活次数 `act`、通过 quiescence 检查后的实际
  执行次数 `body`、computeGroup 调用次数 `grp`、至少一个组变化的次数
  `chg`。
- 每个 op 类型：boundary 标量/宽值写回站点的写入次数 `wr` 与真实变化次数
  `ch`，以及无 fanout 的 boundary 直写次数 `silent`。
- 组级 fanout 发布：`grp_pub`（评估的组数）与 `grp_fire`（至少一个结果
  变化的组数）。
- commit 侧：每个 commit task 的进入次数；端口武装评估 `port_eval` 与
  实际写体执行 `port_fire`；stable-history 整任务跳过与 inactive-edge
  仅采样路径次数。
- 输入扇出检查/变化次数；publish 调用、pending 条目总数与真实变化次数。

由 `act/body` 与静态 op 分布可推出每类 op 的动态执行次数（supernode 激活
即执行其全部 op）；由 `wr/ch` 得值物化的活动率；由 `grp_fire/grp_pub` 与
`chg/act` 得活动传播的产出率。这些量共同决定下一机制：

- 若产出率低（大量激活未产生任何变化），方向为更细粒度活动（分区/调度
  侧），而非继续在 compute 表达层面微调。
- 若 boundary 写入变化率高（大多数写都是真变化），方向为降低单次
  物化/比较成本或扩大融合减少边界值数量。
- 若 commit 端口评估远大于实际写，方向为提交侧再筛选；若 publish pending
  量大，方向为提交/发布合并。

插桩构建只用于诊断（计时偏大、不进入任何性能统计），其仿真以单独截止
运行并分类为 `VALID_DIAGNOSTIC`；性能结论只来自未插桩构建的正式交替测量。

## BASELINE 与预注册口径（先行固定）

- 正式对照 old：NO00035 完整 SV 路线最终构建
  `ptmp/no00035_compute_fusion_20260916/flow-b-final`（其身份与六次正式
  数据见 NO00035 报告）。预选止损比较值为 NO00035 正式 new 均值
  **102.506000 s**，每次 emu 截止 **153.759000 s**（1.5×）。
- 候选先经 checkpoint 重发射筛选（一对 old/new）；通过筛选后才走完整
  SV→C++ 生成（Make 启动计时，`<1800 s`）与 fresh 编译（`<1800 s`），
  再以 `benchmark_grhsim_ir` 按 old1/new1/old2/new2/old3/new3 执行正式
  六次；任一 `INVALID` 作废补跑。主指标 Host，辅指标 emu 墙钟；判定要求
  max(new)<min(old)（n=3+3 等价单侧精确 p≤0.05），并报告均值、样本 SD、
  Cliff delta、Cohen d。筛选/诊断样本不混入正式统计。
- 仿真固定 CPU2、`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、100000 cycles、
  CoreMark 两次迭代、NEMU 对拍，waveform/commit/RAM trace/profile 关闭。
  有效终点 instrCnt=240349、cycleCnt=99996、guest=100001、PC=0x80000c0c，
  exit 0 且无 mismatch。运行前后校验输入与两个 emu 的 SHA256。
- gsim 配置不变，复用归档 46.965 s，仅作剩余差距参照，不参与交替窗口。
- 生成/编译预装 `timeout --signal=KILL 1800s` 进程组截止；超时记
  `TIMEOUT_KILLED` 并隔离产物。正式性能窗口不并行重工作；模型编译
  32 jobs。工作产物均在 `ptmp/no00036_dynamic_coverage_20260916/`。
- 本节点发现并修复一个测量工具隐患：XiangShan difftest 框架在
  `common.cpp:78` 调用 `setlocale(LC_NUMERIC, "")`，在 `LANG=zh_CN.UTF-8`
  的 shell 下 emu 输出数字带千分位（如 `240,349`），benchmark/profile 脚本的
  终点正则无法解析。两个脚本现在对子进程固定 `LC_ALL=C`（只影响文本格式，
  不影响语义与计时），并有单元测试 `test_benchmark_grhsim_ir` 覆盖。本节点
  全部测量在该修复后进行。

（机制假设、实现与验证结果随阶段推进在本文更新。）

## 动态覆盖证据（插桩诊断，100k，VALID_DIAGNOSTIC）

插桩构建 `flow-dyn`（NO00035 checkpoint 原样重发射 + 计数器；默认路径已
经 `flow-plain` 对 NO00035 生成代码逐字节 diff 为空、checkpoint JSON 逐字节
相同而验证零影响）。诊断运行 Host 123.590 s（插桩开销约 +20.6%，不作为任何
性能证据），100k 预期终点、NEMU 对拍通过、emu 哈希前后一致。核心计数
（evals=200102、rounds=402258，2.0103 rounds/eval）：

- **supernode 激活 1,111,120,882 次**（5,552 次/eval），实际执行体
  1,051,889,174 次（quiescence 跳过 5.33%）。
- **产出率：grp_fire/grp_pub = 267,199,748/967,150,813 = 27.63%**；
  supernode 级 chg/act 均值 **29.26%**——约 71% 的激活没有产生任何
  boundary 变化（inert）。
- **boundary 写回 21,450,723,477 次（107,172 次/eval），真实变化仅
  6.04%**；按类型：and 写入 6.72B（变化率 1.52%）、mux 3.09B（13.82%）、
  or 3.00B（3.16%）、eq 2.74B（2.39%）、state.read 1.61B（14.44%）。
- 动态 compute op 执行 114,985,909,800 次（**574,637 次/eval**），
  and/mux/or 合计 60.1%；frame 均值 154.84 B/body。
- commit：进入 63.56M 次，端口评估 701.47M、实际写体 488.47M
  （fire/eval 69.63%）；publish 每次 311.88 条 pending，88% 真变化。

## 假设 A：活动粒度（细 supernode）

compute 占 eval 77% 的主要动态成本形态是"整体重算"：一次激活平均重算
109.18 个 op，而 71% 的激活无任何产出；失活浪费与体尺寸成正比。参照点
gsim 的 supernode 平均约 32 成员（同等工作量下每次激活重算量约 1/3.4），
单周期总开销相应更低。尝试 A 把 `cpu.st.merge-compute-supernodes` 的
`--max-op-in-compute-supernode` 从 128 降到 **16**（同 DP 目标函数下的粒度
移动，其余 mapping/调度/emission 规则不变）：失活激活的重算浪费按体尺寸
同比下降，激活更精确（只有真正受影响的小锥体重算）。

代价侧（同 evidence 一并预注册）：boundary 值增多（比较/写站点增多，但写入
执行次数 ≈ 激活体数×均 23 个 boundary 结果，估计基本持平）、激活字节与
调度检查增多（已有字打包预过滤）、frame/调用固定开销相对上升、helper 输入
缓存复用减少。这些可能抵消部分或全部收益，因此先做 checkpoint 重映射筛选。

局部目标 2–8% Host。可证伪标准：筛选 old/new Host 无正向（或变慢）、或
静态结构显示 boundary/dispatch 膨胀抵消、或正式六次不分离，则否定 A 并在
本节点内改换机制（备选：boundary 同组相邻字节批量比较，静态覆盖
17.3%/runs≥4；或 publish/端口侧批量化）。A 只改分区映射参数，不改 IR 语义、
不改冻结 GRH/GRH pass、不改 XiangShan 与基准源码；等价性由 100k 对拍与
终点一致性验证。

### 尝试 B：提交/发布热路径的调用开销消除

A 被否决后回到动态证据：compute 有效载荷无法通过粒度缩减，转而削减每次
激活的固定辅助开销。既有 200 Hz profile（NO00034 构建，21367 样本）按符号
拆分：compute task 69.52%、commit task 17.06%、**非 task 的 helper/libc
符号 9.10%**、evaluator 3.22%。其中最热的是 `cpu_write_cell<bool,1>`
（1.70%）、`cpu_replicate_words_changed<2,1>`（1.21%）、
`cpu_write_scalar<bool>`（0.96%）、libc（0.88%）、
`cpu_direct_state_changed`（0.62%）。热点 commit task 的反汇编显示每次
标量内存写都要执行 9 参数调用（3 个栈推入 + 6 次寄存器搬移 + call），
publish 循环对每条 pending（含 1 字节状态）都调用 libc memcmp+memcpy。
动态计数：publish 共 125,456,647 条 pending（88% 真变化）、commit 端口评估
701M/写体 488M。

B 的三处发射改动，语义逐位不变（同一 dirty/pending/shadow 记账与发布顺序）：

1. `writeCell` 在调用点内联标量内存写体（memWrite/memFill/memWriteSeq 的
   1–64 位 cell），消除 9 参数调用序列；begin/count/projection/元素宽度
   均为发射期常量。
2. `cpu_publish` 按 size∈{1,2,4,8} 分派内联比较+写回，仅更宽条目回退
   libc memcmp/memcpy；publish 的比较/复制语义与顺序不变。
3. `cpu_write_scalar` 加 `__attribute__((always_inline))`（history 采样与
   staged 标量写的每事件调用点）。

局部目标 1–3% Host。可证伪标准：筛选无正向或正式六次不分离则否定；
若筛选偏弱（<0.8%）则追加同族候选（小字宽 replicate 特化）再筛。

### 尝试 B 筛选：REJECTED

checkpoint 重发射 36.93 s、fresh 编译 243.19 s 均 exit 0；与默认路径的
文本 diff 确认仅有三处预期改动（publish 分派、`cpu_write_scalar` 内联属性、
311 个 commit task 的 writeCell 内联体）。筛选 old/new Host
**102.072 / 114.909 s**——候选慢 **12.58%**（n=1+1，p=1.0），100k 终点与
对拍通过。ELF text 103.83→108.09 MB（+4.1%）。内联在大 commit 函数内造成
寄存器/代码体积病理——与本仓库 AGENTS.md 的 helper 指引（保持既有
指针式 helper 路线为性能参照）一致：helper 调用开销不是可提取的成本，
其代码体积代价反向支配。B 的三处源码已全部撤回（保留插桩、脚本/目标与
测试断言设施）；两个方向（A 的固定成本、B 的代码体积）的失败共同指示：
只有缩减动态工作量或静态代码量的改动才可能获益。

### 尝试 C：1-bit replicate 广播特化

replicate 审计（确切 NO00035 模型）：13,398 个 replicate op 中 12,977 个为
1 位源（窄 1→1 word），418 个宽结果（1→2/3/4/5 words）。现状发射：窄路径
把 rep 次复制展开为 **rep 层嵌套的 `grhsim_concat_u64` 调用**（如 rep=32
约 90 条依赖链指令）；宽路径调用 `cpu_replicate_words_changed` 嵌套 word
循环（200 Hz profile 中 <2,1>/<5,1> 两个实例合计 1.79% Host，含调用开销与
循环开销）。而 `{rep{bit}}` 的语义只是按位广播：结果每个 live lane 都等于该
bit——`0 - (uint64)bit` 一次减法即得全 1/全 0 字。

C 的发射改动（纯 emission，不动 IR/分区/调度/语义）：

- 窄（≤64 位结果、1 位两态无符号源）：发射 `(0-static_cast<uint64_t>(b))`，
  由既有 `normalize()` 做结果位宽截断/符号扩展；替代 rep 层嵌套 concat 链。
- 宽（>64 位结果、1 位两态无符号源）：在 compute() 逐 word 内联
  `next = cpu_rword & liveMask(word)`（liveMask 为发射期常量；liveWidth 与
  padding 清零规则与 `cpu_replicate_words_changed` 逐位相同），保留逐 word
  变化比较与 changed/fanout 结构，替代嵌套循环 helper 调用。
- 其他源宽度（含 1 位 signed，其存储按符号扩展语义不保证 0/1 内容）维持原
  helper/concat 路径，由既有 fixture（8 位源 replicate 与宽值差分测试）覆盖。

局部目标 1–2% Host。可证伪标准：筛选无正向或六次正式不分离则否定。

### 尝试 A 筛选：REJECTED

重映射后 supernode 36137→**204916**（均值 109.18→19.25 ops），boundary
结果 835511→913885（+9.4%），frame 总量基本持平（5.43MB）。checkpoint
重映射+重发射 48.79 s、fresh 编译 209.64 s，均 exit 0。筛选 old/new Host
**102.426 / 133.856 s**——候选慢 **30.69%**，两组 Make/emu 均 exit 0、
100k 终点与 NEMU 对拍通过。n=1+1、单侧精确 p=1.0；方向明确为负，不进入
完整验证。结论：粒度细化带来的失活重算减少被每次激活的固定成本（活动位
检查、frame 清零、helper 调用、组标志与发布）彻底淹没——205k 个 supernode
的固定开销淹没了 109→19 ops 的重算节省。细粒度方向在本架构发射形态下
不成立；gsim 的细粒度成立依赖其近零的 per-supernode 固定成本（无 frame、
无 helper 调用、无组标志机制）。这与 NO00004–06 的调度侧失败一致。

## 插桩实现与小模型验证（已完成）

实现位于 wolvrix `lib/grhsim/backend/cpu_emit.cpp`：`cpu.st.emit-cpp` 新增
`--dynamic-stats <true|false>`（经 pybind kwargs 透传，reemit 目标以
`GRHSIM_REEMIT_DYNAMIC_STATS=1` 打开）。启用时 emitter 在模型头声明
`cpu_dyn_*` 计数器数组/标量并在上述各发射点插入计数语句；关闭时不发射任何
插桩，代码路径逐字节保持既有输出（dump 尾部拼接结构保持不变）。新成员名在
`validate()` 中按启用条件注册为保留名。

新增通用离线分析 `scripts/grhsim_dynamic_stats.py`（Make 目标
`analyze_grhsim_dynamic`）：解析 `[grhsim-dyn]` 行，与模型分区树 join 出按
op 类型的动态执行次数（body 加权）、boundary 写入活动率、supernode 产出率、
commit/publish 结构计数。

聚焦验证：`make test_grhsim_cpu_emit test_grhsim_cpu_mapping
test_grhsim_cpu_schedule` 全部通过（107.69 s，exit 0）。新增
`testDynamicStats`（wolvrix `tests/grhsim/test_cpu_emit.cpp`，fixture
`cpu_dynamic_stats.{mk,cpp}`）在 ASan/UBSan 下执行 2×1024 步（每步两次
eval）+ 2 次 init 的逐输出记分板，dump 校验 `ch<=wr`、必要计数行齐全；另
验证启用插桩时 `cpu_dyn_wr` 端口名被保留名拒绝。小模型实跑 dump 示例：
`and wr=1024 ch=255`、`totals grp_pub=7424 grp_fire=6260 port_eval=512
port_fire=256 pub_calls=3071 pub_pending=1023`，计数随语义合理。

## IMPLEMENTED：尝试 C 的保留实现

C 只修改 `wolvrix/lib/grhsim/backend/cpu_emit.cpp` 的 replicate 发射路径，
没有改变 GrhSIM-IR 模型、依赖、分区、布局或调度。对一位、unsigned、two-state
源，窄结果改用 `0 - bit` 广播，宽结果在已有结果槽中按 word 写入并逐 word
比较变化；padding 位按原 helper 规则清零。signed、四态或宽源继续使用原有
concat/helper 路径。新增 `cpu_replicate_broadcast` fixture 覆盖 1/3/32/64/66/
130 位结果、宽源回退和跨 eval 变化，避免把 signed/宽源语义误归入特化。

聚焦验证执行：

```text
make test_grhsim_cpu_emit test_grhsim_cpu_mapping test_grhsim_cpu_schedule
```

结果为 exit 0；emitter 测试包含 replicate 广播 fixture、动态插桩 fixture，
并通过 ASan/UBSan 运行。C 的 checkpoint 筛选使用 `flow-c-probe`，old/new
Host 为 102.740/99.715 s，终点和 NEMU 对拍通过，作为进入完整路线的筛选证据，
不计入正式六次统计。

## VALIDATED：完整路线与六次交替复测

完整 SV→C++ 生成使用全新 `flow-c-final`，不是 flat GRH 或筛选 checkpoint
恢复。`generation.time` 为 **705.37 s**、exit 0；GrhSIM store/load/store
round-trip 字节一致。fresh emu 编译 `compile.time` 为 **213.11 s**、exit 0，
两项均低于 1800 s 截止。正式构建 emu SHA256 为
`d96d774ac12deace188cdf14511a00b2be929f88fa670019695d8c6b4bbbaba2`；old
构建 SHA256 为 `4b7a5d4622197d44b8957ac7658548890bf60c8839e097bbbdaad17b58f07e35`。

正式窗口在 2026-09-16 按预注册 `old1/new1/old2/new2/old3/new3` 顺序运行，
CPU2、`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`、100000 cycles，关闭 waveform、
commit/RAM trace 和 profile。每次 Make/emu 均 exit 0；六次均为
`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、guest cycles 100001、
末端 PC `0x80000c0c`，Difftest 无 mismatch。

| 顺序 | Host (s) | emu wall (s) | Make / emu exit | 对拍及终点 |
|---|---:|---:|---|---|
| old1 | 102.711 | 102.74 | 0 / 0 | PASS |
| new1 | 99.801 | 99.83 | 0 / 0 | PASS |
| old2 | 102.641 | 102.67 | 0 / 0 | PASS |
| new2 | 101.291 | 101.32 | 0 / 0 | PASS |
| old3 | 102.237 | 102.27 | 0 / 0 | PASS |
| new3 | 99.869 | 99.90 | 0 / 0 | PASS |

old Host 均值 **102.529667 s**、样本 SD **0.255862 s**；new 均值
**100.320333 s**、样本 SD **0.841309 s**。均值差 −2.209333 s，按
`100*(1-new/old)` 降低 **2.154823%**。组内 CV 为 0.249560% / 0.838292%。
`max(new)=101.291 < min(old)=102.237`，分离间隔 0.946 s；Mann–Whitney
`U(new)=0`，3+3 全排列单侧精确 `p=0.05`，Cliff delta **−1.0**，Cohen d
（new−old）**−3.553134**。六次全部有效，无补跑、超时或剔除，因此满足节点
真实收益判据。

## ACCEPTED：结论、根因收敛与归档

动态证据把主要差距具体化为 compute 值物化成本：每次 eval 平均执行约
574,637 个 compute op，71% 的 supernode 激活没有 boundary 产出，21.45B 次
boundary 写回只有 6.04% 真变化；提交端口评估也达到 701.47M 次。细化
supernode 会把固定活动/调用开销放大 30.69%，提交侧内联会使 text 增长 4.1%
并变慢 12.58%，所以这两条路线被证伪。C 保留了原有活动与变化传播结构，只
消除高频一位广播的 concat 链和宽值 helper 循环，完整窗口仍取得 2.154823%
的真实提升。它证明了“按语义证明缩减动态值物化指令”是当前可组合的局部方向，
但不能把该局部收益外推为全部 2.18 倍差距；剩余主要成本仍是大规模 boolean
compute、boundary 比较/写回和活动传播。

本节点最终保留动态统计设施、复现脚本、C 发射特化、测试和本报告；A/B 的
失败数据保留在本报告，B 的源码全部撤回。正式证据来自已跟踪的报告、脚本、
测试和索引，生成代码、日志、profile、checkpoint 与二进制均只留在
`ptmp/no00036_dynamic_coverage_20260916/`，不进入归档。节点状态为
**ACCEPTED**；下一节点需由用户重新启动 `/goal`。

## 归档复现命令与提交

以下命令从根仓库执行；`flow-c-final`、`formal-c` 和日志均位于
`ptmp/no00036_dynamic_coverage_20260916/`。生成与编译使用 1800 s 进程组截止，
编译并行度 32；正式窗口的脚本自身写入预注册顺序、输入哈希和每次结果。

```bash
source env.sh
node_dir="$PWD/ptmp/no00036_dynamic_coverage_20260916"
flow="$node_dir/flow-c-final"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache" \
  CCACHE_DIR="$node_dir/ccache" CCACHE_DISABLE=1 \
  PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH" \
  WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD="$flow" XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00036_replicate_final_generate

timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_NUM_CORES=1 \
  XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00036_replicate_final_compile

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$PWD/ptmp/no00035_compute_fusion_20260916/flow-b-final" \
  GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-c" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=102.506
```

根仓库归档提交为本报告所在的最终 `feat: accept NO00036 replicate broadcast optimization` 提交，
其中的 wolvrix 子模块提交为 `cd79f03`
（`feat: specialize one-bit replicate emission`）。两个工作树在提交后均干净。
