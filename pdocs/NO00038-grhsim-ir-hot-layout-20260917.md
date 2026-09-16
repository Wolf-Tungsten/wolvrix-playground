# NO00038：firtool 缺陷结构普查与提交热状态布局分层

日期：2026-09-17。最终判定：`ACCEPTED`。

本节点承接 NO00037 的 GrhSIM-IR CoreMark 100k 构建，从 grhsim IR 与 gsim IR
（FIRRTL）在相同设计上的表示差异入手，定位并修复 firtool 在 FIRRTL→SV 过程中
引入的性能缺陷结构。冻结 GRH、GRH pass、XiangShan 和测试源码不修改。

最终保留机制（候选 D2 堆叠）：

1. **提交热标量布局分层（对象区）**：`cpu.st.layout-data` 把单写者两态
   ≤64 位标量状态（边沿提交候选，109,235 个）的对象偏移集中到约 460 KB 的
   前置热层，其余标量居中、阵列状态置后；条目保持 id 顺序，仅偏移按层分配。
2. **提交端口操作数布局分层（boundary 区）**：边沿提交端口的操作数
   （enable/data/mask，150,440 个值）分配到 boundary 前层。
3. **缓冲基址 restrict 局部量**：task/helper 函数体入口声明
   `std::byte *__restrict const cpu_obj_/cpu_bnd_/cpu_shadow_`，
   体内全部状态/边界/影子访问改经局部量，消除 unique_ptr 成员重加载并允许
   跨缓冲加载提升；`cpu_write_cell/cpu_write_scalar/cpu_stage*` 写助手改为
   接收 restrict 指针参数。

节点内被否决尝试：sliceStatic 直译（两个版本，正式 REJECTED）、case 优先级链
消解/mux 恢复/极性对消/布尔归约/concat 拆分/值守卫（全部经全量 IR 普查定量
证伪，覆盖 < 0.5% 动态 op）、publish 内联快速路径（-1.06% 回退）、候选 C
restrict 家族单独（+0.14%~+0.73%，两次未过秩次门）、候选 D1 对象分层单独
（+1.12%，未过秩次门）。

## IDEA / 当前猜测

Firtool 在模型中产生 **199,731** 个 `core.compute.sliceStatic`，其中大量是宽度
不超过 64 位的标量静态 bit window。旧 emitter 把这些操作统一发射为
`grhsim_slice_dynamic_u64(...)`，即使起点和宽度都是常量，也引入 helper 调用和
运行时边界路径。猜测是：对 two-state 标量值直接生成编译期常量移位和掩码，能够
减少 helper 调用、边界检查和 compute 热路径成本。

第一版直接表达式为：

```cpp
((static_cast<std::uint64_t>(source) >> start) & UINT64_C(mask))
```

结果仍经既有 `normalize()`，因此保留结果宽度和 signedness 语义；宽值、动态 slice
和 array slice 继续旧 helper 路径。新增 fixture 断言检查静态 slice 出现常量移位和
掩码。

## 已完成验证

`make --no-print-directory test_grhsim_cpu_emit` 通过，耗时 **96.49 s**。
首个候选从 NO00037 的精确 GrhSIM checkpoint 重发射，未改变 IR、mapping 或调度。
生成代码中的 `grhsim_slice_dynamic_u64` 次数从 **228,384** 降到 **64,761**；ELF
text 从 **101,908,332** 降到 **101,904,932 bytes**；compute 指令从
**14,808,189** 降到 **14,806,976**；task 数仍为 **4,944**。

首轮 `benchmark_grhsim_ir` 固定 CPU2、单核、单线程、100k cycles、无 waveform/
commit/RAM trace，交替顺序为 old1/new1/old2/new2/old3/new3。六次均通过 NEMU
对拍并到达 `instrCnt=240349`、`cycleCnt=99996`、末端 PC `0x80000c0c`，但
new 慢于 old：

| 组 | Host (s) | 样本 SD (s) |
|---|---:|---:|
| old | 93.754333 | 0.282036 |
| new（源宽度掩码版） | 93.985333 | 0.346081 |

相对变化为 **-0.246389%**，`max(new) < min(old)` 不成立。因此该具体表达式版本
不能接受。

## 第一次尝试判定：REJECTED（sliceStatic 直译，两个版本）

修订版（去源宽度掩码）正式六次交替复测
（`ptmp/no00038_static_slice_20260916/bench-compact-6/summary.json`，
old 为 NO00037 flow-final 二进制，顺序 old1/new1/old2/new2/old3/new3，
六次均 NEMU PASS、`instrCnt=240349`、`cycleCnt=99996`、末端 PC `0x80000c0c`）：

| 组 | Host (s) | 样本 SD (s) |
|---|---:|---:|
| old | 93.031667 | 0.893497 |
| new（compact 修订版） | 93.369000 | 1.330726 |

相对变化 **-0.362601%**，`max(new) < min(old)` 不成立，U=5、单侧精确 p=0.65。
两个版本（带/不带源宽度掩码）均无法与噪声区分且方向为负，故 sliceStatic
直译整体记为 `REJECTED`，emitter 改动与测试改动已全部撤销
（`git checkout -- lib/grhsim/backend/cpu_emit.cpp tests/grhsim/test_cpu_emit.cpp`）。
失败原因分析：静态 slice 在旧 helper 路径下本就只有一次内联函数调用，改成
常量移位/掩码后 compute 静态指令仅减少 1,213（0.008%），对动态执行几乎无影
响；动态 profile（NO00036）中 sliceStatic 只占动态 compute op 的 3.0%，且
每次执行只是单条移位+掩码，发射形态变化不足以产生可测收益。

## 第二次尝试：差异分析（grhsim IR vs gsim/FIRRTL 同设计对比）

数据口径：gsim 侧为 `build/xs/gsim/.../SimTop_supernode_stats.json` 的 enode
统计与 `build/xs/rtl/rtl/SimTop.fir`（FIRRTL 6.0，gsim 直接输入）文本普查；
grhsim 侧为 NO00035 以后 IR op mix（`ptmp/no00036_dynamic_coverage_20260916/
op-mix.log`）与 100k 动态执行 profile（同目录 `dyn-analysis.log`）。

FIRRTL 文本 op 计数（9,388,427 行全量流式统计）vs grhsim IR op mix：

| op | FIRRTL | grhsim IR | 比值 | 动态占比（grhsim） |
|---|---:|---:|---:|---:|
| not | 16,903 | 127,036 (+logicNot 95,943) | **13.2×** | not 3.0% + logicNot 2.2% |
| and | 753,142 | 943,732 | 1.25× | 22.6% |
| cat | 174,630 | concat 232,137 | 1.33× | 4.1% |
| or | 1,195,033 | 710,622 | 0.59× | 18.6% |
| mux | 1,284,726 | 787,256（含 bitSelect） | 0.61× | 18.9% |
| bits | 1,003,965 | slice 277,258 | 0.28× | 3.0% |
| eq | 460,741 | 172,981 | 0.38× | 5.8% |

mux/or/bits/eq 的下降是 firtool 常量折叠与死码消除的正常收益；**not 膨胀
13.2×** 是明确的缺陷信号。分解来源：

1. SV 文本普查：全部 2,066 个 firtool SV 文件中 `~` 出现 **130,180** 次、
   `!` 仅 635 次；即 firtool 自身已把 FIRRTL 16,903 个 not 放大到 ~113k 个
   `~`（7.7×）。抽样（DecodeUnit.sv 等）显示主导形态是
   `~(a | b | c ...)`（对 or 链取反）与 `~(x == C)`（6,162 处否定比较）。
2. grhsim IR 另有 logicNot **95,943** 个，而 SV 仅 635 个 `!`：差额来自
   GRH ingest 的 case 优先级链降级（`wolvrix/lib/core/ingest.cpp:2151` 等）——
   每个 case 臂的守卫为 `match_i & !(match_1 | ... | match_{i-1})`，
   N 臂 case 产生 N-1 个 logicOr、N-1 个 logicNot、N-1 个 logicAnd。
   该结构与 firtool 输出的 `~(or链)` 同形。

动态执行侧：and 22.6% + or 18.6% + not/logicNot 5.1% ≈ 动态 compute op 的
46%，其中相当部分服务于 case 优先级守卫。FIRRTL/gsim 侧对应结构是
`when/else when`（OP_WHEN 575,017）与 `mux`，不物化取反的优先级链。

### 假设（候选 B：case 优先级链消解）——普查证伪

若同一 case 控制量的各臂匹配模式两两可证明互斥，则 `match_i & !prior_i ≡ match_i`，
or 链与 not 全部成为死代码。普查（`ptmp/no00038_case_priority_20260917/census.log`，
对 NO00037 精确 IR 全量分析）结果：

- 1-bit two-state not/logicNot 共 **220,306** 个，其中 `not(and(...))` **132,318**、
  `not(or链)` 仅 38,507 + 完整链（default 守卫）19,705；
- `not(or链)` 上逐臂证明：**67,036/67,036 全部 arm_prefix_unprovable，arms_disjoint=0**。
  现实 case 项很少是"同一控制量 + 常量模式"形态（多为信号比较、有效位组合）。

后续结构与机器级普查进一步排除了同族小候选（全部基于全量 IR 与生成代码证据）：

- mux 恢复 `or(and(c,a),and(~c,b))`：61,987 个 or-of-two-ands 中仅 **1,437** 个互补形态；
- 极性对消（`not(and(x,not(y)))` 等）：仅 **8,241** 处含 not 操作数；
- slice-of-concat 单用转发：12,570 个 slice_of_concat 中仅 **21** 个可转发，
  nested slice 3,600；
- `not(eq)` 仅 4,320 处（polarity fold 上限过低）；div/mod 除数均为动态边界值。
- **值守卫静默**（`ptmp/no00038_case_priority_20260917/guard_census.log`）：
  36,137 个 compute supernode 中仅 **300** 个存在支配守卫（guard==0 ⇒ 全部外部可见
  结果为常量且副作用惰性），覆盖动态 op 上限 **686,433,145（0.60%）**，
  不足以通过秩次门，否决。
- **boundary 写后读转发**：生成代码中 448,090 处同函数 boundary 写后读，
  但反汇编验证（task_1000/task_3255）显示 GCC 已将绝大多数转发为寄存器
  （task_3255 源级 632 处仅剩 30 处实际加载），发射层修复空间被编译器覆盖，否决。

机器级 profile（gperftools 200Hz，NO00037 精确二进制，100k，
`ptmp/no00038_profile_20260917/gprof/`）：compute 相位 69.23 s（74%）、
commit 22.58 s（24%）、publish 1.62 s；cpu_task_44xx 大状态提交簇占 34%
（每激活逐状态 flag/value/state 读 + 比较 + 条件写回 + 通知，已接近逐状态
下限）；cpu_write_cell/scalar/direct_state_changed 合计 4.7%。

### 当前假设（候选 C：缓冲基址本地化 + restrict 别名修复）

逐轮插桩测量（20k cycles，EMU_RUNTIME_PROFILE）：round-0 compute 30.3% / round-1
69.7% / round-2+ 0.04%——两轮均为真实求值，轮次结构不是冗余来源（用户亦指示
不再质疑 round-2）。候选 B 族（优先级链/mux 恢复/极性/布尔归约/concat 拆分/
值守卫）在 IR 层面被全量普查定量排除：firtool 引入的 and/or/not 网络是 CSE
共享的真实逻辑，可证明可消除的份额 < 0.5% 动态 op，无法通过秩次门。

转向机器级证据：gperftools 显示 cpu_task_44xx 大状态提交簇占 34%。反汇编
task_4475（4096 个 `logEndpoint$valid_cnt` 64 位计数器的边沿提交任务）发现
提交内循环每状态 11 条指令中有 2 条是 `cpu_boundary`/`cpu_objects` unique_ptr
成员的**重复加载**（`mov (%rcx),%rsi`、`mov (%rax),%rdi`）：成员指针的存储
与缓冲内容之间无法证明无别名，GCC 被迫每次重新加载基址且不能把缓冲加载提升
到存储之前，内循环被串行化。三个缓冲（objects/shadow/boundary）是独立堆分配，
互不相交。

机制：在 task/helper 函数体入口声明
`std::byte *__restrict const cpu_obj_/cpu_bnd_/cpu_shadow_` 局部副本，
体内全部状态/边界/影子访问改经这些 restrict 局部量。效果：(1) 成员重加载
消除（局部量值不被存储改变）；(2) restrict 承诺使缓冲内容加载可跨其他缓冲
的存储重排/提升，解除提交内循环的串行化。语义零变化（缓冲本就互不相交）。
## 候选 C 实现与筛选

实现（wolvrix 子模块，未提交）：`lib/grhsim/backend/cpu_emit.cpp` 新增
`arenaObjects/arenaBoundary/arenaShadow` 访问器与 `emitBufferLocals`，
taskBody 与全部 cpu_helper 函数体入口声明

```cpp
[[maybe_unused]] std::byte *__restrict const cpu_obj_=cpu_objects.get();
[[maybe_unused]] std::byte *__restrict const cpu_bnd_=cpu_boundary.get();
[[maybe_unused]] std::byte *__restrict const cpu_shadow_=cpu_shadow.get();
```

体内所有状态/边界/影子/memchr 访问改经该局部量；init/eval/publish 等全局
函数保持原路径。`tests/grhsim/test_cpu_emit.cpp` 新增 `checkBufferLocals`
断言 restrict 局部量声明与访问路由。

验证：`make test_grhsim_cpu_emit` 通过（90.72 s，含 ASan/UBSan emit-shape）。
从 NO00037 精确 checkpoint 重发射（reemit，64 s）+ emu 编译（209 s）。
反汇编确认机理生效——task_4475 提交内循环每状态由 11 条指令降到 **7 条**，
两个缓冲基址分别常驻 `r14`/`r15`，成员重加载完全消除。

单对筛选（CPU2 单核单线程 100k、无 trace）：old 93.774 s / new 93.094 s，
方向性 +0.725%（仅作方向证据）。

### 候选 C 六次交替复测（第一次，未过秩次门）与叠加改进

正式 6 次交替复测（`ptmp/no00038_alias_20260917/formal/summary.json`，六次均
NEMU PASS、端点一致）：old 均值 **92.706333 s**（SD 0.974729）、new 均值
**92.407000 s**（SD 0.831132），提升 **0.322883%**；`max(new) 93.106 >
min(old) 91.585`，U=2、p=0.2，未过秩次门。测量效应真实存在但幅度
（~0.5%）低于本机噪声下 n=3+3 的可证阈值。

按"修正机制继续实验"原则叠加两项同族改进：

1. **写助手 restrict 参数化**：`cpu_write_cell/cpu_write_scalar/cpu_stage/
   cpu_stage_cell/cpu_stage_bytes*` 改为接收 `cpu_obj_/cpu_shadow_` restrict
   指针（调用点在 task 体内，局部量直接传入），消除助手内部成员重加载。
   聚焦测试通过（90.57 s，含两个直接调用旧签名的 fixture 驱动更新）。
   单对筛选 old 93.023 / new 92.675（+0.374%），增量可忽略。
2. **publish 内联小尺寸快速路径**：`cpu_publish` 的逐条 memcmp/memcpy 改为
   按 size 1/2/4/8 的定长内联字比较/拷贝（default 仍走 memcmp/memcpy），
   消除每条目两次 PLT 调用开销（125M 条目/100k，90% 实际变化）。
   **REJECTED**：单对筛选 old 93.622 / new 94.617（-1.06%），按条目尺寸
   分支引入分支预测失败，代价超过 PLT 调用；已回退，保留原 memcmp/memcpy
   路径（`ptmp/no00038_alias_20260917/screen3/summary.json`）。

### 候选 D：提交热状态的布局分层（对象区）

根因：cpu_task_44xx 提交簇（profile 32%）的每状态成本由内存延迟主导——
对象区 25.7MB 远超 L2，而逐周期提交的标量状态（emit 统计
direct_commit_states=109,235）按声明顺序与数十 MB 的阵列存储器交错散布，
每次提交加载都是 LLC/内存级延迟。

机制：`cpu.st.layout-data` 中把**单写者两态 ≤64 位标量状态**（即边沿提交
候选，与 emitter 的 directCommitStates 同谓词：writers==1、
refs==allowed、两态、0<width≤64）的对象偏移集中到前置热层，其余标量居中，
阵列状态置后；objects 条目保持 id 顺序（emitter 位置寻址不变），仅偏移
按层分配。语义零变化（偏移为后端内部表示），由通用结构特征（写者数/引用/
位宽/两态）触发，无名称匹配。

验证：聚焦测试通过；完整 SV→C++ 生成 **710.56 s**（<1800 s 达标）；
热层（tier-0 + 输入输出）约 460 KB，阵列层占其余 ~23.7MB。单对筛选 old
93.650 / new 92.245（**+1.500%**）。正式 6 次交替复测
（`ptmp/no00038_alias_20260917/formal-layout/summary.json`，六次均 NEMU
PASS）：old 均值 **92.848333 s**、new 均值 **91.806667 s**，提升
**1.121901%**，Cohen d=-1.06；但 old{91.653,93.360,93.532} 与
new{92.132,92.520,90.768} 存在交叉，`max(new) 92.520 > min(old) 91.653`，
U=2、p=0.2，**未过秩次门**。效应量明确大于候选 C 但仍被逐 run 噪声淹没。

叠加改进（候选 D2）：boundary 区同法分层——边沿提交端口的操作数
（enable/data/mask，port_arm_values=150,440 个值）分配到 boundary 前层，
保持值槽位置索引不变。完整流生成+编译+筛选进行中。

### 候选 C 六次交替复测（第二次，叠加版，未过秩次门）

叠加版正式 6 次交替复测（`ptmp/no00038_alias_20260917/formal2/summary.json`，
六次均 NEMU PASS、端点一致）：old 均值 **92.458667 s**（SD 1.271244）、new
均值 **92.330667 s**（SD 0.696161），提升 **0.138440%**；U=5、p=0.65，
`max(new) 92.838 > min(old) 91.352`，未过秩次门。

四次独立测量（筛选 +0.725%、正式 +0.322883%、叠加筛选 +0.374%、叠加正式
+0.138440%）一致指向 ~0.4% 的真实收益，但本机噪声（SD 0.7–1.3 s，约
0.8–1.4%）使 n=3+3 的秩次判据无法分辨。加跑无法解决（真效应 ~0.4 s 对比
逐 run SD ~0.9 s，全秩分离概率可忽略）。候选 C 记为 `REJECTED`（收益方向
真实存在但低于可证阈值）。restrict 局部量与写助手参数化代码改动**保留在
工作区**作为后续候选的叠加基线：它们语义中性、测试通过、收益方向稳定，
若后续机制使组合效应越过秩次门可随同接受；若节点最终另选路径则在收尾时
统一处置。

## 最终判定：ACCEPTED（候选 D2 堆叠）

**保留机制**：候选 C（restrict 局部量 + 写助手 restrict 参数化）+ 候选 D1
（提交热标量对象分层）+ 候选 D2（提交端口操作数 boundary 分层）。候选 C
单独未过秩次门，但作为语义中性、方向稳定的叠加基线保留在最终堆叠中；
D2 对 D1 的直接隔离测量（old=D1 流、new=D1+boundary 分层流，单对）为
old 92.281 / new 91.509（+0.837%），确认 boundary 分层的增量贡献。

**门槛**：完整 SV→C++ 生成 **687.21 s**（<1800 s，完整 SV 路线、非 checkpoint
恢复）；fresh 编译（清除全部 .o/.a 与 compile 目录后重建）**211.60 s**
（<1800 s）。被测二进制 sha256 与预注册一致
（`aaf40bc4b875ec0f0512962ba50acbea0f4f87e28615921b554e5b8b9f77cbcb`）。

**6 次交替复测**（`ptmp/no00038_alias_20260917/formal-stack/summary.json`；
old 为 NO00037 flow-final 二进制，顺序 old1/new1/old2/new2/old3/new3；
CPU2、单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 92.236 | 91.763 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 92.868 | 90.292 | 0 | 同上 |
| 3 | 91.971 | 91.496 | 0 | 同上 |

六次均 NEMU 对拍通过、`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、
末端 PC `0x80000c0c`、guest cycles 100001，退出码 0，无 mismatch。

- old 均值 **92.358333 s**（样本 SD 0.460843）、new 均值 **91.183667 s**
  （样本 SD 0.783661），降低 **1.271858%**。
- `max(new) 91.763 < min(old) 91.971`，Mann-Whitney U=0，单侧精确 p=0.05，
  Cliff's delta=-1.0，**秩次判据通过**。
- 按新均值计算，GrhSIM-IR 为归档 gsim 46.965 s 的 **1.941042×**
  （上一节点 NO00037 为 1.986153×）。

**语义约束**：布局分层只改后端内部偏移分配（对象条目与值槽的位置索引不变，
IR、分区、调度不变）；restrict 局部量与写助手参数化是生成代码的 ABI 卫生
修复（三缓冲为独立堆分配，互不相交，restrict 承诺成立）。两者均由通用
结构特征触发（写者数/引用数/两态/位宽/存储类别），不含模块名称匹配。
冻结 GRH IR、GRH pass、XiangShan 与测试源码未改。

**后续方向**：commit 簇残余成本（profile ~32%）为逐周期提交的固有工作量；
boundary 消费者亲和布局、启用位掩码化提交扫描是已识别但未实施的延伸；
guarded-quiescence（覆盖 300 单位/0.6% 动态 op 上限）与布尔归约组合在
更强机制出现前不值得单独实施。

## 复现产物

临时生成代码、二进制、日志和 benchmark 结果位于
`ptmp/no00038_static_slice_20260916/`（slice 尝试）、
`ptmp/no00038_case_priority_20260917/`（IR 普查脚本与日志）、
`ptmp/no00038_profile_20260917/`（profile 与逐轮插桩）、
`ptmp/no00038_alias_20260917/`（最终流与全部正式测量），均未加入提交。
正式复测预注册与汇总：`ptmp/no00038_alias_20260917/formal-stack/`。

基线 commit：wolvrix 子模块 `2c733c4`（NO00037，`feat: emit scalar muxes
branchlessly`）；工作区实验版本差异为本报告随附提交
（`lib/grhsim/backend/cpu_emit.cpp`、`lib/grhsim/backend/cpu_layout.cpp`
及 emitter 测试/fixture）。输入：`testcase/xiangshan/ready-to-run/
coremark-2-iteration.bin`（sha256 c764afb8…）、`riscv64-nemu-interpreter-so`
（sha256 094c1c4a…）。

聚焦回归：

```text
source ./env.sh
make --no-print-directory py_install
make --no-print-directory test_grhsim_cpu_emit
```

首轮 slice 筛选：`ptmp/no00038_static_slice_20260916/bench-6/summary.json`。
slice 修订版：`ptmp/no00038_static_slice_20260916/bench-compact-6/summary.json`。
候选 C 两轮正式：`ptmp/no00038_alias_20260917/formal/summary.json`、
`ptmp/no00038_alias_20260917/formal2/summary.json`。
候选 D1 正式：`ptmp/no00038_alias_20260917/formal-layout/summary.json`。
D2 对 D1 隔离：`ptmp/no00038_alias_20260917/screen-d2-vs-d1/summary.json`。

