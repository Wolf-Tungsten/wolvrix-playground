# Rob 独立仿真：待修清单（攒批，之后一并修改）

> 记录用户点名要修、但暂缓实施的事项。每条附现状证据、目标形态、改动点与验证门槛。
>
> **2026-09-29 状态：六项全部完成实施与验证**（checksum 硬门槛全过；各条结论见本节末尾"实施结论"）。
> 统一验证门槛（每条都适用）：
>
> ```bash
> source env.sh && make build && make py_install && make test_grhsim_cpu_emit
> rm -rf ptmp/xs-components-rob/grhsim-model && make -C testcase/xs-components -f rob.mk rob-grhsim-model
> make -C testcase/xs-components -f rob.mk rob-bench-trace ROB_BENCH_VERIFY=100000 ROB_BENCH_REPEAT=3
> # 硬门槛：verify 全过且两模型 checksum == 0xd27a5e546e6474cc
> ```

## TODO-1 边沿历史扫描的代码形态（"shitty" IIFE + memchr 1 字节）

> **实施结论（2026-09-29）**：已按四级形态落地（单组单字节纯比较 / 单组连续裸 `!memchr` / 非连续 offsets 表 IIFE 兜底 / 多组 `&&` 连接），`stableCommitHistories` 分级发射；Rob 上单组单字节命中，IIFE 消失。性能不变（符合"纯可读性"预期），checksum 过。

现状（生成代码，`ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_68.cpp:7-10`）：

```cpp
if(/* cpu_stable_history_scan histories=8192 groups=1 */ ([&](){
    if(std::memchr(cpu_obj_+14730,!bool(cpu_event_snapshot_0),1))return false;
    return true;
}()))return; // cpu_stable_history_skip task=68
```

根因（发射器 `stableCommitHistories`，`wolvrix/lib/grhsim/backend/cpu_emit.cpp:5891-5943`，调用点 `:6121-6127`）：

- 接口设计是"返回一个**表达式字符串**"拼进 `if(<expr>)return;`；表达式写不了语句，多组/查表的一般情形只好包 IIFE，Rob 的单组单字节退化情形跟着受连累；
- 通用路径按"同事件多个连续历史字节一次 memchr 扫一片"（`:5931-5933`），**没有 size==1 特判**；
- `!bool(x)` 是对任意宽度 eventValue 的防御性规整，对已是 bool 的快照变量纯冗余。

已实证运行时成本为零（objdump `GrhSIM_Rob::cpu_task_68` 开头：两条 `movzbl` + `xor` + `cmp $1` + `jne`，IIFE 内联、memchr(…,1) 折叠为字节比较，stable 路径被 cold-block 扔到远处）——**纯可读性问题，不是性能问题**。

目标形态（按退化程度分级发射，调用点不动）：

- 单组单字节 → 纯比较表达式，如 `if(cpu_at<bool>(cpu_obj_,14730)==cpu_event_snapshot_0)return;`；
- 单组连续 N 字节 → `if(!std::memchr(...))return;`（本身就是表达式，去 IIFE）；
- 多组 → 各组谓词用 `&&` 短路边连成一条表达式（提前退出语义天然保留）；
- 仅"非连续 offsets 表循环"的稀有路径保留 IIFE 兜底。

备注：`cpu_inactive_edge_sample` / `cpu_edge_snapshot` 两段（同文件 :6128-6141 发射）形态尚可，不在本条范围；若改完顺手发现同类退化可一并清理，但需在本条记录。

## TODO-2 生成代码分阶段注释（eval 顶层 / compute 分派 / commit 任务）

> **实施结论（2026-09-29）**：已落地。eval() 顶部总览、输入暂存（段首 + 逐口带口名/扇出规模）、沿分类、下降沿省略、round 循环头、compute/commit 分派段、publish、域臂回灌、静止出口；compute/commit 任务函数头（无数字，保 twin 折叠）；commit 任务内事件快照/两级快速出口/共享沿布尔/写 walk/武装 walk/历史回写，全部 `[phase]` 前缀。**形态教训**：发射器的 IndentBuffer 美化器把 `//` 行注释粘到前一行尾部（trailing 注释设计），连续独立注释会两两粘连；块注释 `/* [phase] ... */` 不触发粘连、每行独立，故采用块注释形态，grep 验收口径 `grep -c '\[phase\]'` 不变。注意坑：注释文本不得含 `cpu_edge_snapshot` 等被测试做缺席断言的 token（`test_cpu_emit.cpp:934`）。

动机：生成代码几十万行无注释，读代码全靠对照 tour 文档（`grhsim_cpp_model_tour.md` §3/§4）。
要求在生成代码里直接加**段首注释**（允许重复、啰嗦，宁可每段都写全，不要省略引用），
标明每段在干什么。注释用固定前缀便于 grep（如 `// [phase] ...`）。

需要注释的位置（发射点均在 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`）：

1. **eval() 顶层分段**（对应 tour §3.0-§3.5，生成在 `grhsim_Rob.cpp`）：
   - profile 序言（仅 profile 开启时生效）；
   - 输入暂存段：逐口 `if(this->io_X != 快照)` 的比较-更新-扇出块——每个口块首注释口名与扇出规模，段首注释整体职责（"把 host 驱动的新输入与上周期快照比较，变化才更新状态区并激活下游"）；
   - 边沿分类段（pos/neg/other 分桶）；
   - round 循环头（恒激活组置位）、compute 分派段（"每轮扫 778 字节标志位图，逐任务 if 分派"）、commit 分派段（"按域字节派提交任务，原理见 tour §4"）、publish 调用点（"shadow→objects 原子回拷 + 下游扇出"）、next_arms 回灌、静止出口（输出拷回）、不收敛兜底 throw。
2. **compute 任务函数头**（`cpu_task_1`..`cpu_task_67`）：注释该任务对应的分区/职责、读哪些区（obj/bnd）、写哪些区（bnd/shadow）。
3. **commit 任务函数头**（`cpu_task_68/69/70`，对应 tour §4）：
   - 事件快照 locals（"从 boundary 读当前时钟电平"）；
   - 两级快速出口各一段注释（stable scan = "任何事件都没变过电平则整体跳过"；inactive sample = "无效沿只更新 history，否则下个有效沿会丢"）；
   - 共享沿布尔 `cpu_edge_snapshot_*`；
   - `cpu_mem_guard_hoist` 块（"同守卫连续 memWrite 合并一次沿判定"）；
   - 末尾 history 回写行。
4. 注释内容写"这段在算法上做什么"，不写"下一行是什么指令"；每段注释自包含，不引用别段行号（生成代码行号不稳定）。

验收：重新生成后 `grep -c '\[phase\]' grhsim_Rob*.cpp` 覆盖上述全部段；tour 文档 §3 表格行号若因注释插入漂移，一并刷新。

## TODO-3 commit 写体的公共守卫提升（enable/行号嵌套块），并删除 `cpu_men_*` 预读

> **实施结论（2026-09-29）**：已落地。`memEnableCache_` 机制整体删除；commit walk 两级分组：`cpu_mem_guard_hoist`（同沿守卫 run≥4）内嵌 `cpu_mem_enable_hoist`（同 enable 连续段 ≥2）。Rob 实测：enable_hoist 785 块、guard_hoist 715 块、`cpu_men_` 归零。曾做第三级 bounds hoist，Rob 实测 0 命中（动态行仅占 3.6% 且无连续同行段），已删除。性能与 TODO-4 合并测量：噪声级（归一化 −2% 内），checksum 过。
>
> **勘误（2026-09-29，全量 xiangshan 暴露）**：守卫/enable 被双 strip 后写体失去自有 `if` 作用域，宽元素（>64 位，`auto &cpu_cell` 局部声明）在同一 stripped run 内相邻出现即重定义编译错误（task_3677 等）。Rob 无此形态故六项验证全过而未能发现。修复：宽元素写体自带花括号（`cpu_emit.cpp:5199-5208`）。已验：`make test_grhsim_cpu_emit` 过 + 全量 xiangshan dynamic-stats 构建编译通过 + 100k coremark difftest 干净、端点 `240349/99996` 与生产基线一致。

现状（生成代码，`ptmp/xs-components-rob/grhsim-model/grhsim_Rob_task_68.cpp:622` 起）：同一行的多个字段写体**相邻、共享同一 enable 与常量行号**，但每个写体各自重复完整守卫：

```cpp
if((cpu_edge_snapshot_0) && cpu_men_43171 && ...(0)<352){ cpu_write_cell<bool,1>(...,0,...); }
if((cpu_edge_snapshot_0) && cpu_men_43171 && ...(0)<352){ cpu_write_cell<std::uint64_t,50>(...,0,...); }
... 行 0 的每个字段一遍；行 1..351 同构 ...
```

根因：`cpu_mem_guard_hoist`（`wolvrix/lib/grhsim/backend/cpu_emit.cpp:6204-6232`）只合并沿守卫（≥4 个同沿 run），enable + 边界检查两层未合并；`cpu_men_*` 预读（`memEnableCache_`，`:6154-6180`）只是"守卫重复"形态下的补丁（共享 enable 一次 load 进寄存器，供 N 个写体测试），没有消除重复本身。

开销定性：边界检查 `trunc_u64(常量)<352` 恒真，clang 折叠，运行时零成本（纯源码膨胀）；**enable 测试是真分支**——21,401 个写体 ⇒ 每个上升沿 ~2.1 万次 enable 测试（使能为假也照测），且 37k 行重复守卫文本撑大 task_68 的 I-footprint。

目标形态（按（沿守卫， enable ValueId, 行号表达式）对连续 memWrite run 分组嵌套）：

```cpp
if(cpu_edge_snapshot_0){                    // 沿守卫（沿用现有 hoist）
    if(cpu_at<bool>(cpu_bnd_,1149)){        // 行使能：每行只测一次，直接读 boundary
        cpu_write_cell<bool,1>(...field A...);
        cpu_write_cell<std::uint64_t,50>(...field B...);
        ...
    }
}
```

语义安全性：守卫全是纯读（沿布尔 / boundary enable / 常量边界），写体顺序不变、pending 记录顺序不变 ⇒ checksum 不变。

连带动作：enable 每行只测一次后，预读与直读 boundary 指令数相同，且省掉任务头数百次 prologue load——**`memEnableCache_` 机制整体删除**（含 emitter `:6146-6180` 的注释与统计计数 `memEnableCacheSites_`）。

预期收益：上升沿 enable 分支测试 21,401 → 去重后 enable 数（量级几百）；task_68/69/70 源行数与 I-footprint 显著缩小。**需实测**（对照组：bench + 分相探针的 commit_ns_pos）。

改动点：emitter commit walk（`wolvrix/lib/grhsim/backend/cpu_emit.cpp:6191-6234` 一带，与 guard hoist 同层加 enable/行号 run 分组）+ 删除 `memEnableCache_`。

## TODO-4 emit 期常量折叠：memWrite 常量行号的边界检查与下标表达式

> **实施结论（2026-09-29）**：已落地。commit 的 memWrite/memWriteSeq 用 `scalarConstantValue()` 折叠常量行号：恒在界删边界检查 + 行号发字面量；恒越界发 `// cpu_mem_write_dead` 注释。Rob 实测边界检查 14,748 → 176（残余为真动态行）。运行时零成本（clang 本就折叠），纯源码净化，checksum 过。

现状（生成代码，每个 memWrite 写体都有）：

```cpp
if(... && static_cast<std::size_t>(static_cast<std::uint32_t>(grhsim_trunc_u64(UINT64_C(0),32)))<352){
    cpu_write_cell<...>(...,static_cast<std::uint32_t>(grhsim_trunc_u64(UINT64_C(0),32)),...);
}
```

行号是 IR 里的两态常量（Chisel 按表项展开，每行一份写逻辑），`trunc_u64(常量)` 是恒等、
`常量<352` 恒真——clang 编译期全部折叠，运行时零成本，但 21,401 个写体各带一份
冗余文本（源码膨胀 + 阅读噪音）。

目标：emit 期用现成的 `scalarConstantValue()`（`wolvrix/lib/grhsim/backend/cpu_emit.cpp:4773`，
议题二的 all-ones mask 判定已用它）识别常量下标：

- 常量且 `< array.count` 恒真 → **删掉边界检查**，下标直接发成字面量 `0`；
- 常量且越界恒真 → 写永不触发：保留最小守卫 `if(false)` 或直接跳过该写体并记 emitter 统计
  （真实硬件不应出现，出现即上游 bug，需在 emitter 日志里留痕）；
- 非常量下标（动态索引）→ 保持现有边界检查不变。

发射点：commit 的 memWrite（`wolvrix/lib/grhsim/backend/cpu_emit.cpp:5034-5039`）、
memWriteSeq（`:5079`）；顺带检查 `value()`/`normalize()` 对两态 ≤64 位常量的渲染
（`grhsim_trunc_u64(UINT64_C(x),w)` 恒等时可全局发成字面量——收益面更大，
但要注意四态/宽位常量不适用，分两档做，先把 commit 写体这条窄路径做掉）。

与 TODO-3 的关系：守卫嵌套后常量下标文本仍残留在每个 `cpu_write_cell` 实参里，
本条把它一并净化；两条一起做时建议先 TODO-3 分组、再 TODO-4 折叠，diff 更清晰。

## TODO-5 `cpu_write_cell` 按形态特化，废弃单一通用版本

> **实施结论（2026-09-29）**：已按路线 A 落地四形态——通用版（动态行+部分 mask）、`_f`（全 mask 去 mask 参）、`_c`（常量行预折）、`_cf`（两者）；全 mask 判定 = `scalarConstantValue` 覆盖元素全宽。Rob 上 memWrite 全部命中 `_cf`/`_f` 形态。与直写（TODO-6）叠加时曾测得 −6%，归因后确认亏损全部来自直写路径；特化本身归一化打平（0.4414 vs 基线 0.4402，噪声内）。checksum 过。

现状：所有内存写走同一个 10 参数模板（`ptmp/xs-components-rob/grhsim-model/grhsim_Rob.hpp:6046`），
议题二实测 `bool,1` 变体 78% 周期是调用约定开销（10 参数中 4 个压栈 + 重载）。

调用点普查（Rob 全模型 14,748 处，2026-09-29 grep 实测）：

| 维度 | 分布 | 结论 |
|---|---|---|
| (T,Width) | `bool,1` 4,928（33%）；`u8,8` 2,840；`u64,64` 2,472；`u8,7`/`u64,50`/`u64,48` 各 704；其余 8 种合计 ~1.7k | 14 种实例，保持模板化 |
| 行号 | **常量 14,212（96.4%）**；动态（boundary 读）536（3.6%） | 常量行可去掉 row 参数 |
| mask | **全部编译期常量**（typed 常量 14,604 + `UINT64_MAX` 144） | mask 参数可整体消灭 |
| begin/count/projection | 全部编译期常量 | 同上 |
| 每调用真正的运行时含量 | 仅 `data`（+3.6% 的 row） | 10 参数里 9 个可折掉 |

目标形态（两条路线，先做 A 度量，再定 B）：

- **A. 形状特化 helper**：按（常量行/动态行）×（全 mask/部分 mask）分版本，编译期常量全部折成函数内常量或模板参数。例：常量行+全 mask 的 5 位写 →
  `cpu_wcell_cf<std::uint8_t,5>(key, offset, begin, count, data)`（5 参数全寄存器传递，消灭栈参数）；动态行保留 row 参数的版本。等值早退、脏记账、pending 语义不变。
- **B. 描述符表**：每（内存 × 行类）一条 constexpr 描述符（key/offset/begin/count/projection），调用 `cpu_wd<Width>(desc, row, data)`（2-3 参数）。压缩更狠但多一层索引，需 A 的实测数据对照后再决定。

红线与教训：

- **按形状类特化，绝不按调用点生成函数**——议题三 always_inline 全域展开已实测 -13%（I-cache 崩溃）；版本数控制在 ~形状数（≤ 14 宽度 × 4 形态 ≈ 几十个函数）；
- 先做 TODO-3（守卫分组）与 TODO-4（常量折叠）再动本条——调用点形态净化后特化 diff 才干净；
- 验证门槛同顶部；性能对照用 bench + 分相探针 `commit_ns_pos`（议题二基线：`cpu_write_cell<bool,1>` 独占 3.84% 周期，可回收上限 ≈3% 墙钟）。

## TODO-6 借鉴 gsim：NBA 语义的静态化（沿检测降级 + commit 直写化）

> **实施结论（2026-09-29）：机制已实现，实测净亏损，默认关闭（opt-in 保留）**。
> 直写资格判定（`planDirectMemories`：数组仅被 memWrite/memRead 引用、元素 ≤64 位两态、commit 任务构成 round 分派后缀）+ `cpu_write_cell_direct[_f]` helper（变化检测内联 + 行过滤读者扇出，fanout 已改 noinline 外调——内联版 task_68 膨胀到 1.47 MB，外调后 0.55 MB）。
> Rob trace bench 全配置实测（gsim 归一化 grhsim/gsim）：直写关 0.4414（最优）、全直写 0.4151（−6%）、宽窄混合（≤8 读者直写）0.3874（−12%）。结论：shadow+publish 的批处理回拷（紧凑 shadow 顺序写 + publish 集中 memcmp/memcpy/单扫描）优于直写的交错散写 + 每写即扫；与内联形态无关。默认关闭，实验开关 `GRHSIM_DIRECT_MEM=1`（可选 `GRHSIM_DIRECT_MEM_MAX_READERS=N`）。checksum 全配置过。

背景（gsim 机制调研，2026-09-29；对照代码 `ptmp/xs-components-rob/gsim-model/`）：

- gsim 没有运行时"mem 写入"概念与沿检测。所有状态带 `$NEXT` 孪生，组合逻辑裸 store 进
  `$NEXT`（动态行写就一条数组赋值，`Rob5.cpp:69359`）；commit supernode 在拓扑序里排在
  producer **之前**（静态普查 7,436/7,478，bench 头注释 `ptmp/xs-components-rob/bench/rob_bench.cpp:4-9`），
  step() 开头执行 `x = x$NEXT` 应用的是**上一步用沿前状态算好的值**——NBA 由静态调度
  （rotated schedule）实现，不靠运行时机制。
- 单时钟设计时钟被编译期消灭：`step()` 一次 = 一个周期 = 一个上升沿，寄存器每 step 无条件
  前进（`rob_bench.cpp:23538-23541`）；`set_clock` 只做内联变化检测 + u64 打包扇出
  （`Rob0.cpp:36583`）。
- 内存 commit = 整数组 `$NEXT` → current 回拷（`Rob0.cpp:65230`），clang 塌缩成 `rep movsb`
  （议题二实测 gsim 最热单指令，仅 0.5%）——用内存带宽换零记账。
- 差距根源一句话：**gsim 把单时钟同步语义特化进了调度，grhsim 在付通用事件驱动语义的钱**。

行动方向：

- **commit 写路径直写化**：gsim 证明"写 $NEXT 镜像 + 统一回拷"足够；
  grhsim 对"下一 compute 阶段前无观察者"的单写者状态已有 direct-commit
  （`wolvrix/lib/grhsim/backend/cpu_emit.cpp:4930-4967`，history 已用），可把资格判定放宽/
  默认化，缩小 shadow+pending+publish 的覆盖面；内存行写已是"写 shadow + publish 回拷"，
  要害是砍掉每笔写的等值检测之外的记账（10 参数 helper，与 TODO-5 特化联动）。

  2026-09-29 实证（强化正当性）：Rob commit 相内 commit op 互读为零——task_68 的
  1,224 次 `cpu_obj_` 读 = 1,221 次 direct-commit 自 RMW + 3 次 history，数据/使能全走
  boundary；shadow 唯一防的残余风险是 commit 操作数直读状态（emitter 自述
  `wolvrix/lib/grhsim/backend/cpu_emit.cpp:512`，`readAliases_` :507-516 即为此设）。
  对照：compute 相的 boundary 写从来都是直写 + 内联扇出（`grhsim_Rob_task_33.cpp:53`），
  shadow 只套在状态写上。**现状是"默认 shadow、证明才直写"，应反转为"默认直写、
  证明有观察者才走 shadow"**；主要工作量在内存写（14,748 处 write_cell）的直写证明
  （无 commit 相内读者）+ 行过滤扇出内联化（替代 publish 的 `cpu_read_offsets` 查表，
  `grhsim_Rob.cpp:43686`）。

  （2026-09-29 用户裁定：沿检测/双 eval 降级路线**不做**，从清单删除。）

红线：checksum 硬门槛不变；形态变化限 commit 写路径。
验证：顶部统一门槛 + 分相探针 `commit_ns_pos` / `publish_ns_pos` 对照。

## TODO-7 三段式重构：compute（逻辑+寄存器写 shadow）/ commit（mem 直写）/ publish（回拷）

> **状态（2026-09-29 定稿）**：方向经四轮澄清确定；可行性 profile 已通过（判定：可以改，
> 见末节）；待实施。用户定性：可能有负面影响，但这是当前僵局的一个新突破口。

### 核心动作（2026-09-29 第四轮澄清后的准确表述）

round 保持三段，但职责重新划分：

1. **compute 段**：计算逻辑 +**普通寄存器写**融合——compute 与寄存器写不再在超节点层面
   分离，同一超节点内既有 compute op 又有寄存器写 op（锥的汇端）。目的是消掉寄存器写
   路径的 compute↔commit 边界开销（操作数 boundary 往返、独立 commit 分派段、域臂机制）。
   寄存器一律写 **shadow 状态区**。划分约束：融合节点须为**纯汇**（无 boundary 输出被
   其他超节点消费），否则入口沿门控不成立、只能退化到写 op 级守卫——见末节。
2. **commit 段**：只剩 **mem 写入**。mem 写调度在最后，round 内无观察者，故**直写 obj、
   不套 shadow、不回拷**（gsim 对 L3 bank 的先例：`array[w_setIdx]=x2` 裸写，见对照实证节）。
3. **publish 段**：把 shadow 写回 obj（reg 区）实现 NBA + 下轮激活位图写回真激活表。
   与 commit 段次序自由（reg 区与 mem 区不相交）；注意 mem 写的沿守卫读 obj 里的
   history 旧值，publish 置后（或 history 单独处理）更稳。

状态存储重构照旧：所有状态变量提取到独立结构体/存储区，reg 按位宽分桶（8/16/32/64/wide），
mem 每个独立形态。pending 队列删除（定案，数据流见下节）。

### 为什么放弃"删 shadow"（TODO-6 极端化路线）

直写化全量推开（删掉 shadow/pending/publish）的障碍不在 mask 多写——多写者本就按
程序序依次应用，直写 obj 与"dirty?shadow:obj"逐位等价。真正的耦合点是**边沿 history
在 commit 相内被活读**：

- commit 任务入口的稳定历史快速出口（`stableCommitHistories`，`wolvrix/lib/grhsim/backend/cpu_emit.cpp:6140-6199`）
  与共享沿布尔（`commitEdgeSnapshots`，`:6274-6312`）都**直读 obj 区 live history 字节**；
- 同 eval 同 round 内，前面的 commit 任务尾部采样写 history（`sampleHistoryBatch`，`:3024`），
  shadow 靠 round 末 publish 迟滞让这些写入对同 round 的其他任务不可见——NBA 沿语义的承重墙；
- 现有防护只靠"私有化资格"（`references==1` 的 op 独占 history，`:2921`；alias 代表元机制
  `:2140-2190`）把活读面收窄到"本任务独享的字节"，全量删 shadow 需要把沿判定整体提升为
  eval 级公共快照 + 采样统一挪到 eval 末尾，工作量与风险都高。

新路线下此死结自动消解：scan/沿守卫照旧读 obj（round 前状态），history 写只落 shadow、
publish 才可见，NBA 语义一行不动。

### pending 队列删除（定案）

pending 队列整体删除，无保留、无替代物讨论。删除后的数据流（与三段式一一对应）：

1. **寄存器写（compute 段内）→ shadow**：写前等值比较，变了才（a）置所在 reg 桶区域的
   脏位、（b）把静态预算的 (offset,mask) 序列 OR 进下轮激活位图。masked RMW 直接读
   shadow 即得程序序（不变量：publish 后 shadow≡obj，round 初无需再初始化）。
2. **mem 写（commit 段）→ 直写 obj**：不套 shadow、不入 pending；变化时同样（a）不需要
   脏位（mem 区不回拷）、（b）OR 激活位图。mem 读侧的同 round 旧值语义由调度保证
   （读值先捕获进寄存器/boundary，commit 段排在最后），与 gsim 大 bank 先例一致。
3. **publish 段**：（a）按 reg 桶脏位图对脏区域整体 memcpy shadow→obj（`rep movsb`）
   并清位图——neg eval 与未触及区域零回拷；（b）下轮激活位图按字扫描、全零字跳过、
   OR 回真激活表并清零。

（历史记录：此定案同时消掉 TODO-6 实测 −5~6% 亏损的根源——直写时仍按读者表运行时扫描
扇出；此处改为静态预算目标序列，无运行时扫描。）

### gsim 对照实证（直接读生成代码，2026-09-29）

`build/xs/gsim/gsim-compile/model/`（全量 xiangshan）的实际形态：

1. **寄存器/小状态：`$NEXT` 孪生 + 每 step 无条件整组回拷**。标量逐个 `x = x$NEXT`；
   数组是定界 elementwise 循环（`for(i0...){ a[i0]=a$NEXT[i0]; }`，编译器塌缩成 `rep movsb`）。
   每 step 约 2,396 个回拷循环、~10.6 万元素，零条件、零记账。
2. **大 mem 不套 shadow、直写**。160 个 L3 dataStorage bank（`uint64_t array[16384]`，
   单个 131 KB、合计 ~21 MB）**没有一个有 `$NEXT` 孪生**（0/160）；写路径就是裸
   `array[w_setIdx] = x2;`，读侧在写之前已把 `array[ADDR]` 捕获进 `raw_rdata` 寄存器——
   NBA 语义由静态调度顺序保证，完全无运行时机制。这正是"mem 有自己形态"的 gsim 先例。

**勘误（2026-09-29）**：本节此前有"shadow 全量拷贝不可行"一段，错误在于把当前
25.7 MB 的 obj 整体当成拷贝对象定价——其中 ~82%（~21 MB）是 L3 dataStorage bank，
而 gsim 证明这部分本来就不该进 shadow（直写即可）。撤回该段结论。正确结论：
**大 mem 直写不套 shadow；其余状态区（reg 分桶 + 小 mem + history）全量拷贝完全可行，
gsim 就是这么做的，且它比当前 grhsim 快（xiangshan coremark 27.4s vs 48.8s）**。
区域脏位图保留为我们相对 gsim 的增量改良（neg eval 整片跳过），不是承重墙。

逐点对应（TODO-7 三段 ↔ gsim 机制）：

| TODO-7 | gsim 对应物 |
|---|---|
| compute 段：逻辑 + reg 写 shadow | 组合逻辑裸 store 进 `$NEXT` 孪生 |
| publish 段：脏 reg 区 memcpy 回 obj | 每 step 无条件 `x = x$NEXT` 整组回拷（~2,396 循环，塌缩成 `rep movsb`） |
| commit 段：mem 直写 obj、调度在最后 | L3 bank `array[w_setIdx]=x2` 裸写，读值已先捕获进 `raw_rdata` 寄存器 |
| 下轮激活位图 OR 回真表 | gsim 无此物（每 step 全量执行；我们的增量改良） |

### 可行性门槛与 profile 结果（2026-09-29，完整 xiangshan coremark 100k，VALID）

门槛问题（用户裁定）：commit 挂着时钟信号，时钟每 eval 必翻转，融合后必然导致每 eval
大量 compute 被激活——若现状本来如此，则合并不亏。profile 必须在完整 xiangshan
coremark 上做，不用 Rob 独立模型外推。

运行 VALID：端点 `instrCnt=240349 cycleCnt=99996 IPC=2.403586` 与生产基线一致，difftest 零
mismatch。日志 `ptmp/xs_dyn_activation_20260929/logs/xs_wolf_grhsim_dyn_act_20260929.log`。

静态结构：compute 超节点 29,829 个（29,341 个全程至少激活一次）；任务 3,664 compute + 487 commit。

| 指标（每 eval 均值） | pos eval（100,051 次） | neg eval（100,051 次） |
|---|---|---|
| rounds | 2.01 | 2.00 |
| **compute 超节点激活（sn_act）** | **8,463（占静态 28.4%）** | **650（2.2%）** |
| commit 任务进入（cm_ent） | 157 | 157（几乎全为 inactive 采样，cm_inactive=15.49M） |
| 武装端口求值（port_eval） | 6,236 | 409 |
| 寄存器写口点火（port_fire） | 4,262 | 409 |
| memWrite 守卫测试（mw_gate） | 21,735 | **0** |
| memWrite 点火（mw_fire） | 6,635 | 0 |
| publish pending / changes | 291 / 186 | ~1 / ~1 |
| **墙钟占比（插桩口径）** | **98.25%（151.95s）** | 1.75%（2.70s） |
| 每 eval 墙钟 | ~1,519 µs | ~27 µs |

补充：round 直方图 99.5% eval 走最少轮数；`pub_pending rN=0`——所有状态 publish 都在
round 0 落地，round 1 纯为静止确认。

**判定：可以改。** pos eval 占墙钟 98.25%，其上"时钟→commit→compute"大面积激活本来就是
现状（8,463 次超节点激活、4,262 个写口点火每 eval）；融合不会让 pos eval 更糟。
neg eval 的便宜来自逐任务门控而非阶段分离（见下节），保留门控则融合不亏。

### 融合后必须保住的机制 + 融合特有的新风险

保住的机制（neg eval 不过度激活的保证，实施时逐条对应）：

1. **沿门控不撤，两处各保一处**：
   - **commit 段（只剩 mem 写）**：任务入口的稳定历史快速出口 / 无效沿快速出口 / 共享沿布尔
     原样保留——neg eval 上 `mw_gate=0` 照旧成立，mem 写一个守卫都不测；
   - **compute 段（reg 写融合处）**：沿门控上移为**超节点入口快速出口**——"本 eval 对内部
     所有寄存器写 op 均为无效沿 ⇒ 整个超节点跳过"。**该出口仅在"纯汇"划分下成立**
     （用户 2026-09-29 指出），否则计算错误：
     - **失败场景**：被门控的超节点若还有 boundary 输出被其他超节点消费，neg eval 上数据
       输入变化与时钟翻转置同一个激活位，入口按"无效沿"整体跳过 ⇒ 组合锥重算被一并跳过
       ⇒ 下游读到陈旧 boundary ⇒ 状态错误（激活位本身区分不了激活来源）。
     - **纯汇约束（对超节点划分算法的新要求）**：融合超节点内所有 op 的结果只许流向本节点
       内的寄存器写 op，不得有任何 boundary 输出被其他超节点消费。被多处共享的锥不能并入
       （或复制锥体后并入——代码膨胀换门控收益，需度量）。
     - **纯汇下为何不需要"仅时钟变化"检测**：纯汇 ⇒ 锥体重算的唯一消费者是节点内的寄存器
       写；无效沿时写本就不发生，跳过锥体无观察者。下一有效沿时超节点必然重新进入（时钟
       每 eval 翻转 ⇒ 域臂每 eval 重新激活）且进入后锥体无条件重算 ⇒ 写采样到的 D 恒为
       新鲜值。故入口门控只需"域 history 扫描 ⇒ 无有效沿"一条，不需要 per-超节点
       data-dirty 位。
     - **history 采样先于跳过**：无效沿跳过前必须完成本域 history 字节更新（对应今天
       commit 任务的 inactive 采样路径），否则下个有效沿的沿判定丢沿。
     - **多时钟域**：节点内含多个域的写时，门控 = 各域有效沿布尔的 OR（任一域有效沿即不得
       整体跳过）。
     - **退路（非纯汇节点）**：降级为写 op 级沿守卫（锥照跑、写加沿布尔，对应今天的
       `cpu_edge_snapshot_*` 形态），正确性不依赖划分，仅 neg-eval 收益缩水。
2. **下轮激活数组保持 bitmap+OR 形态（不是列表）**：重复激活幂等；publish 按字扫描 +
   OR 回真激活表，全零字跳过。neg eval 上该数组几乎全零 ⇒ quiescence round 一次扫描即退出。
3. **等值早退前置到写 shadow 之前**：状态没变就不置脏位、不激活。neg eval 上状态本来
   不变（除 history 字节与少量 negedge 寄存器），激活数组天然为空。

不可约固定税（合并不改变）：neg eval 上 negedge 键控的真实工作——650 次 compute 激活 +
409 个寄存器写口点火（改为写 shadow）+ 157 次 commit 任务进入做无效沿采样（mem 写守卫
全不点火，`mw_gate=0`）。

融合特有的新风险（用户已预知"可能有负面影响"，实施时必须量化）：

- **pos eval 锥体重跑（仅限 reg 写超节点）**：今天寄存器写走 commit 读 boundary 里
  "上次算好"的值，生产者锥不必每 eval 跑；融合后锥与寄存器写同超节点，时钟翻转激活
  超节点 ⇒ 锥体随行重算（产出同值、下游无感，但算力白花）。规模 = 寄存器写操作数生产者
  锥的重算量，现有 profile 未直接计量——**实施后第一个要对比的数就是 `sn_act_pos` 与
  `compute_ns_pos` 的涨幅**。mem 写不在此风险内：mem 写仍走独立 commit 段、操作数照旧读
  boundary（边界保留，量级 mw_fire 6,635 次/pos eval），其生产者锥重算量不变。
- **neg eval 激活粒度变粗 ⇒ 转化为划分约束**：时钟每 eval 翻转都会激活含时钟寄存器写的
  超节点；neg-eval 安静依赖入口快速出口，而出口的正确性依赖纯汇划分（见上）。划分算法
  若产出"非纯汇"融合节点又套用入口门控 ⇒ 直接是正确性 bug（陈旧 boundary），不是性能
  问题；对非纯汇节点必须退化到写 op 级守卫。实施时划分器需输出纯汇/非纯汇统计，
  验收时核对非纯汇节点全部走退化路径。

验收红线（实施后重跑本节 profile 逐项核对）：**正确性硬门槛先行**——非纯汇融合节点
零入口门控（全部退化到写 op 级守卫），划分器输出纯汇/非纯汇统计供核对；checksum /
difftest 不变。性能回归判据：neg 侧 `sn_act` ≈ 650/eval、`mw_gate` = 0、
`eval_ns_neg` 占比 ≈ 1.75%；pos 侧 `sn_act_pos`/`compute_ns_pos` 涨幅上限在实施前预注册。
若门控丢失，neg eval 将涨至 pos eval 量级（~1.5 ms vs 27 µs，总墙钟 ~2×）。

复现命令：

```bash
source env.sh
make reemit_grhsim_ir GRHSIM_REEMIT_MODEL=$PWD/ptmp/declsym_baseline_20260928/flow/xiangshan_grhsim_ir.json \
  GRHSIM_REEMIT_FLOW=$PWD/ptmp/xs_dyn_activation_20260929/dynamic \
  GRHSIM_REEMIT_DYNAMIC_STATS=1 GRHSIM_REEMIT_COMMIT_COMPACT_WALK=1 GRHSIM_REEMIT_COMMIT_MEM_WALK=1
make xs_wolf_grhsim_ir_build_emu XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=$PWD/ptmp/xs_dyn_activation_20260929/dynamic/model \
  XS_GRHSIM_IR_BUILD=$PWD/ptmp/xs_dyn_activation_20260929/dynamic
make run_xs_wolf_grhsim_ir_emu XS_GRHSIM_IR_BUILD=$PWD/ptmp/xs_dyn_activation_20260929/dynamic \
  XS_SIM_MAX_CYCLE=100000 XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_WAVEFORM=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 \
  XS_EMU_PREFIX="EMU_RUNTIME_PROFILE=1 taskset -c 2 stdbuf -oL -eL" \
  XS_LOG_DIR=$PWD/ptmp/xs_dyn_activation_20260929/logs RUN_ID=dyn_act_20260929
```
