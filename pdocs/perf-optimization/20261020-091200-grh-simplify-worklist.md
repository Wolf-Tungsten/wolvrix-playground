# GRH simplify 工作队列与子 pass 调度（H2）

## 元信息

- 日期 / 作者：2026-10-20 / Codex
- 根仓 / wolvrix commit：`3c7c969` / `5142b2b`，工作树包含既有未提交修改。
- 对照：[编译时间分段测量](20261019-222537-compile-time-segmentation.md)。
- 范围：路线章程 W1/H2；常量池跨轮缓存（H3）与 GrhSIM IR simplify 不在本次实验中。

## 猜想与实验预登记

1. 观测：`ptmp/grhsim-compile-time-20261019/seg1_sv2cpp.log` 中 GRH simplify
   七轮分别为 210859、44646、36685、36512、37191、35999、36146 ms，
   整个 pass 438041 ms。常量折叠只按存储顺序扫描一次，后继在前时需外层重扫。
2. 机制：常量折叠以工作队列重访改变了输入的用户；外层分别记录各子 pass
   是否使其他子 pass 失效，避免仅有删除或无变化时无差别重跑三个子 pass。
3. 预期：GRH simplify 减少 40–50%（约 180–220 s）；不单独承诺 C3 回闸。
4. 证伪：GRH simplify 未减少至少 30%，或仍出现多轮约 36 s 的全图重扫。

对照产物固定为 `ptmp/grhsim-compile-time-20261019/grhsim-ir/`，输入固定为
`ptmp/xs/rtl/rtl/` 的 preserve-aggregate=all SV。候选生成与编译均写入
`ptmp/grh-simplify-h2-20261020/`，段2使用 `VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32`。
保留 checkpoint round-trip、相同优化参数与 NEMU difftest。
本次测编译时间，采用 H1 的单次两段计时口径，不作运行速度的统计结论。

## 实现与验证

实现涉及 `const_fold.cpp`、`redundant_elim.cpp`、`simplify.cpp` 及常量折叠的
`needsRevisit()` 接口。常量池和拓扑索引仍按原生命周期构建，不作 H3 的跨轮缓存。
常量池的所有使用结束后才删除死常量，以免比较简化复用已擦除的池条目。

定向用例包括：64 级逆序常量链、重复操作数、多图局部 ID、32 级逆序 CSE、
DCE 后单用户 NOT/XOR 重写、后置比较简化唤醒常量折叠；原有 X/Z、声明符号、
slice/concat 环路保护与 shape 回归继续执行。

- `make test_transform_simplify`：通过，最终日志 `unit-refined2.log`。
- `make test_wolvrix`：**64/64**，最终候选 CTest 66.95 s，`test_wolvrix.log` / `.time`。
- 其余三个标准 Makefile 回归及整机 trace 在最终测量后执行，结果待登记。

上述日志均在 `ptmp/grh-simplify-h2-20261020/`；正式基线数字保持不变。

### H2 内部分步检查：只改常量队列不足

第一版只加入常量折叠工作队列及子 pass dirty 调度，GRH simplify 实测
**357782 ms**（六轮：198385、39725、35181、35634、35705、13149 ms），
比 H1 的 438041 ms 减少 **18.3%**，未达到 H2 的 30% 门槛。
其中 DCE 前五轮分别为 24574、21921、21667、22560、23009 ms；
末轮已成功跳过 DCE，但中间轮次仍反复遍历全图。
~~仅常量折叠队列加子 pass dirty 标记足以达到预期收益~~。

原始日志和该版补丁保留在 `ptmp/grh-simplify-h2-20261020/exploratory1/`。
确认此结果后，用工具中断本次隔离子进程（exit 130）；未进行段2，不将其
不完整端到端耗时用作 C3 数据。后续定向测试构建发生在 simplify 计时完成后。

第二版实验前登记：仍只在 H2 的调度与工作队列范围内，将 CSE 改成用户驱动
队列，重访输入被别名替换的消费者；签名命中时核对代表操作当前签名，避免
过期条目。首轮 DCE 保留，中间轮次积累删除需求，重写稳定或到达外层上限时
才执行 DCE，再由 DCE 唤醒单用户优化。预期减少中间约 3–4 次、每次约 22 s
的 DCE 全图扫描，并减少 CSE 依赖操作存储顺序导致的外层轮次；门槛仍为
相对 H1 至少减少 30%。新增 32 级逆序 CSE 用例约束一轮内的别名传播。

第二版实测 **312571 ms**，减少 **28.6%**，仍低于门槛；六轮为 218076、
21473、13754、13806、38223、7237 ms。DCE 仅运行两次，分别 25560、
24194 ms；第 2–4 轮降到约 14–21 s。第一轮 RE 增至 52843 ms，队列新增
的签名有效性核对在每次哈希命中时重新构造代表操作签名。
数据、补丁及该版 64/64 CTest 结果保留在 `exploratory2/`；同样在取得
simplify 数据后中断后续流水线（exit 130），没有作为 C3 完整测量。

第三版实验前登记：将上述有效性核对改为当前 CSE 调用内的输入版本标记，
每次别名替换前递增受影响用户的版本；代表条目版本不符即失效。CSE 内只有
操作数替换和操作删除，不改 kind、属性、结果类型，所以版本覆盖签名变更。
目的是移除工作队列新增的重复签名构造成本，仍按 H1 的 30% 门槛判断；
不跨子 pass 调用缓存任何索引，不涉及 H3。

第三版收尾时将两个队列的 pending/completed 状态合并到图内按 OperationId
索引的字节数组，取消另一个哈希集合；常量折叠不再保留原先的 foldedOps
哈希集合，CSE 已删除操作也由同一数组标记。该修订发生在第三次启动尚处于
xmr-resolve 时，启动被中断并归档为 `startup-before-dense-state/`，不含
simplify 测量。最终计时从修订后重新开始，保持同一 H2 工作队列变量。

## 最终候选的测量

GRH simplify：**289401 ms**，对照 **438041 ms**，减少 **148640 ms（33.93%）**。
达到 H2 的至少 30% 门槛，低于原先 40–50% 的收益预估。没有连续约 36 s 的
全图重扫轮次；DCE 仅执行首轮和收敛清理两次，共 48.373 s。

| 外层轮次（从 0 开始） | 常量折叠 ms | 冗余消除 ms | DCE ms | 该轮 ms |
| --- | ---: | ---: | ---: | ---: |
| 0 | 130343 | 42321 | 23950 | 196615 |
| 1 | 9859 | 8506 | 跳过 | 18365 |
| 2 | 6360 | 7507 | 跳过 | 13867 |
| 3 | 6821 | 7467 | 跳过 | 14288 |
| 4 | 7005 | 7322 | 24423 | 38751 |
| 5 | 跳过 | 7513 | 跳过 | 7513 |

日志：`ptmp/grh-simplify-h2-20261020/seg1.log`。本项为单次墙钟测量，未声称
统计显著性；编译时间口径与 H1 相同。最终两段总时间、段2 TU 数和行为门禁
仍在本轮流程中测量，完成后登记；正式 C3 基线不自动更新。

## 行为回归排查与根因修复（2026-10-20 下午登记）

最终候选的标准回归发现两处行为级破坏，定位过程与结论如下。

### 现象

- `run_xs_bugcase_grhsim`：CASE_009 编译期失败——生成模型的 `priority2`
  端口类型变为 `std::array<std::uint8_t, 2>`，TB 无法编译。
- XS 整机 emu（`run_xs_wolf_grhsim_ir_emu`，coremark 100k + NEMU
  difftest）：cycle 10761 处 store 提交不匹配——DUT 先提交了 memset 循环的
  8 字节清零 `sd`（pc 0x80001d2c），而 REF 期望更老的一字节 store
  （pc 0x80001e56，data 0x32）。`exploratory1` 的 flat GRH 经
  `--resume-from-flat-grh` 重放（variant1）产生完全相同的 mismatch，
  证明错误在探索一版已存在于 GRH simplify 输出中。

### 二分结论（离线回放 + 变体 emu）

以 `--dump-pre-simplify-json` 保存 simplify 前全图（8.5 GB），用
`replay_simplify.py` 单独重放 simplify 并按 op kind / 命名结构 / 常量多重集
做归一化直方图对比（`normdiff/`）：

- HEAD simplify + shape 修复的回放与 10-19 基线结构一致（仅 +69k kAssign，
  即修复拦下的跨 shape 内联）；
- A（常量折叠工作队列）+ B（CSE 工作队列）的图级差量仅 +88 kAssign /
  −7 个常量；
- A+B+fix（无 simplify.cpp 调度）的 XS emu **通过 100k**；
- A+B+C+fix（完整候选 + 修复）回放图与 A+B+fix 结构一致，XS emu
  **通过 100k**（`variant-ab-shapefix/`、`variant-abc-fix/`）。

即工作队列与子 pass 调度本身行为正确；破坏来自既有规则在新调度下暴露。

### 根因

`redundant-elim` 的 kAssign 内联规则（输出端口分支与临时值分支）只校验宽度
与符号位，**不校验 shape**。聚合→扁平的 `kAssign` 是 pack 转换点而非纯改名；
内联它会让 `Graph::replaceResult`/`guardShapeAlias` 把聚合 shape 回填到按扁平
声明的值上。HEAD 调度下该规则恰好只打在类型无关紧要的位置（XS 不受影响，但
CASE_009 在 HEAD 上就已失败）；H2 的更深首轮定值让不同 assign 满足单用户条件，
回填落到行为敏感的内部值上，最终表现为 store 提交乱序。

### 修复

两个内联分支均要求源与目标 shape 严格一致（与 CSE 合并的既有 shape 检查同
口径），见 `wolvrix/lib/transform/redundant_elim.cpp` 与
`docs/transform/redundant-elim.md`。新增
`tests/transform/test_redundant_elim_pass.cpp` 两个回归场景（输出端口 pack
与临时值 pack 均不得内联）；该测试在不带修复的代码上失败，带修复通过。

### 修复后验证

- 单元：`test_transform_simplify`、`test_transform_shape_mapping`、
  `test_wolvrix` 64/64。
- 端到端：`run_xs_bugcase_grhsim` 27/27（CASE_009 恢复），
  `run_all_hdlbits_grhsim_ir_tests` 通过。
- 整机：A+B+C+修复 的 XS emu coremark 100k + NEMU difftest 通过。

### 干净口径耗时（A+B+C+修复，无并发负载）

- 完整 seg1（sv→cpp）：**1391 s**（候选 1380 s，基线 1500 s）；其中 GRH
  simplify **291.3 s**——与候选的 289.4 s 持平，修复不影响 H2 收益
  （相对基线 438.0 s 减少 33.5%）。
- 仿真 100k：基线 **257.3 s**（10-19 原始记录同为 257 s）；HEAD+仅修复
  **394.4 s**；A+B+C+修复 **383.8 s**。三者指令数与 IPC 完全一致
  （238,535 / 2.385）。变慢归因于修复：约 6.9 万个跨 shape kAssign 不再被
  内联，保活后进入求值热路径，每周期约慢 1.49×；H2 的工作队列与调度对
  仿真速度无影响（相对仅修复反而略快，属噪声范围）。该回归是正确性代价，
  后续可考虑把跨 shape 内联改为显式 pack 表达式下沉来回收。

注意：修复拦下的跨 shape 内联在 XS 上保留约 +69k kAssign（grhsim  lowering
/ emit 段因此多花约 6 min）。C3 计时若需采用本修复后的代码，应重新测量。

## kAssignAs 重构（2026-10-21，承接"shape 即类型"方向）

按"op 定义 result 类型；kAssign 不改变数据类型；kAssignAs 负责 bit 级内容不变
的类型转换"的方向落地，分两期：

- **P1（kAssignAs 落地）**：新增 `OperationKind::kAssignAs`（`grh.hpp`/`grh.cpp`
  名称表），`Graph::assignKindFor(src, dst)` 统一判定产生点；ingest 的写回物化/
  实例合并/通用物化三处与 hier_flatten/instance_inline/xmr_resolve/strip_debug/
  comb_loop_elim/const_fold 的 kAssign 产生点全部改判；const_fold 折叠支持；
  grh_to_grhsim `kAssignAs → core.compute.assign`；SV emit 按普通 assign 发射；
  verifier 增加 kAssign 全等与 kAssignAs 等宽规则；store round-trip / fold /
  view 点测试。门禁全绿（test_wolvrix 64/64、xs_bugcase 27/27、hdlbits、
  sim_refactor），XS emu 100k difftest 通过（384 s）。
- **P2（shape 不可变）**：`guardShapeAlias` 去掉回填、改为严格 throw；
  `eraseOp` 替换路径补 guard；`replaceResult` 的守卫移除（它不 mutation，
  契约由 verifier 兜底）；新增 `Graph::replaceAllUsesWithView`——类型不一致时
  自动插一个带 `from` 类型的 kAssignAs 视图再别名；各 pass 的 replaceUsers
  与 ingest 的两处别名点迁移。XS emu 100k 通过（396 s）。

### P3 的性能结论（未达标，已回退）

目标是把仿真 100k 拉回基线 ~257 s。在 convert 层做了"kAssignAs 溶解"
（result 别名到 operand、不产 op）：带符号/形状敏感性消费方排除、链式解析、
环检测。实测 XS 100k **454 s**（比不溶解的 396 s 更差）——溶解让 N 个消费方
各自重新从聚合源打包，超过一次共享拷贝的成本。该尝试已回退；剩余 ~148k
kAssignAs 仍以 `core.compute.assign` 形式存活。

**结论**：类型系统已收敛正确（行为全门禁绿），但 260 s 目标未达成。回收性能
需要在 emit/存储层让 kAssignAs 的 result 与 operand 共享存储（flat 视图直接
读 array 存储），而非 convert 层删 op——这是下一阶段的工作。

### P4：perf 定位与 emit memcpy 快速路径（2026-10-21）

对 P2 emu 做 perf record（30k 周期，FP 调用图）与基线对比：

- P2 头部热点 `sn_7329`/`sn_7330`（ROB 区）合计 ~15% 周期，基线对应逻辑仅
  ~2%。热代码是 kAssignAs 视图链跨 supernode 的 pack/unpack：
  `state(19200b flat) →view→ 300×64 数组(frame) →memcpy pack→ flat →view→
  300×64 数组 → …`。
- `unpackValue`（flat→行数组）**没有** packStoreRows 已有的 memcpy 快速
  路径：每行对 19200 位 `_BitInt` 做一次全宽移位，单视图 O(rows×words)。
  生成代码静态计数（P2 vs 基线）：行循环 196k vs 106k（+85%），
  `const auto cpu_packed=`（unpack）73.8k vs 23.3k（+217%）。

修复（emit 文本层，行为等价）：

- `unpackValue`：rows×elementWidth==width 且 elementWidth∈{8,16,32,64} 时，
  小端下 `memcpy(&cpu_array,&cpu_packed,width/8)`，保留逐行循环作为非小端
  回退（与 packStoreRows 的条件完全镜像）。
- `publishBoundary` 聚合路径（非常量、非 arrayValue）：同条件下发布改为
  `memcpy`，变化检测改为 `memcmp`+条件 `memcpy`（保留原逐行路径作回退）。

实测见后续小节。待办候选（按预期收益）：`core.compute.replicate` 的
O(n²) 移位广播改 word 填充（sn_7330 内 212×64→13568 实例）；
whole-array state write 的逐行 rowSliceText；emit 层视图消除
（kAssignAs result 的 read() 别名到 flat operand，仅 chunk 内、非
crossing/非 boundary，保守条件已论证）。

**P4 实测结果（variant-fixa，干净口径，无 commit trace）**：

- XS emu 100k：**241.3 s**（基线 257.3 s，P2 修复前约 384-396 s），instrCnt
  238,535 / IPC 2.385445 与基线完全一致，difftest 通过。**超过 260 s 目标，
  且快于原基线 6%**（基线自身的 2.3 万个 unpack 点同样受益）。
- 生成代码：11.5k 个 unpack 点转为 memcpy（含 ROB 链 300×64 热点）；剩余
  62k 个点仍走逐行循环，主要受限于 elementWidth∉{8,16,32,64}（如宽元素
  聚合）——可后续扩展 ew%64==0（容器无填充）情形，非达标必需。
- emit 视图消除（read() 别名）与 replicate word 填充已设计完毕但**未启用**
  ——目标已达，避免无谓风险；如后续需要更多余量再启用（设计要点：等宽两态
  单操作数 assign、result 不跨 chunk/无 boundary/static/masked 标记时
  read() 别名到 operand 根，链式解析在行时完成）。
- 钉核（taskset -c 2）复测：**243.1 s**，instrCnt/IPC 再次一致，两次独立运行
  稳定（241.3/243.1 s），达标结论可靠。
- 编译侧：seg2（生成模型 C++ 编译）9m32s vs P2 的 10m35s（memcpy 文本短于
  循环，编译也略快）；seg1 GRH pipeline 不受 emit 改动影响，H2 收益保持。
- 附带：`run_all_hdlbits_tests`（Verilator 流）中 5 个 testbench
  （tb_042/043/060/062/071/116/117/118）因 Verilator 5.x `VlWide<N>` API 漂移自 9-25 起
  就无法编译（与本工作无关的既有环境漂移）；已将读路径字访问 helper 模板化
  （`const uint32_t w[N]`/`const uint32_t *w` → `const W&`，写路径调用点均为裸
  指针保持原签名），新旧 Verilator 均可编译。

**最终门禁（2026-10-21，P4 树态）**：test_wolvrix 64/64；xs_bugcase 27/27；
sim_refactor 162/162；hdlbits Verilator 流 162/162（含 8 个 tb 兼容修复后）；
XS emu 100k difftest 通过、host 241.3/243.1 s。**260 s 目标达成，工作收尾。**

### P5：emit 视图消除（read() 别名，2026-10-21）

设计：等宽两态单操作数 `core.compute.assign`（kAssign/kAssignAs 共同的
lowering 形态），result 不跨 chunk（不在任何 supernode/event/output
frame）、无 boundary 字段、非 static/masked 时，op 不产任何代码，
`read()` 在行时沿 `viewRoot_` 链别名到 operand 根；根必须为 flat（扁平读
平凡）或与 result 完全同形（行存取可转发，masked-read 根排除防重复展开）。
构造时机放在构造器末尾，construction 期的 read()/expression() 快照保持
旧解析。安全性已逐路径论证（boundary 上下文、waveform、DPI、latchWrite
staged 文本、frame 并集）。

实测（XS emu 100k 钉核背靠背）：fixa 246.3 s vs elide 253.8 s（+3%）；但
perf 15k 干净周期 fixa 438.6G vs elide 433.0G（-1.3%）；同二进制两次钉核
自身漂移 ~1.5%。**结论：XS 上性能中性（噪声区间内）**——Fix A 之后被消除的
物化成本已是 memcpy 量级，消除只省下调度开销。附带收益：生成代码 -70 万行
（-3%），seg2 模型编译 9m15s vs 9m32s。行为验证：test_wolvrix 64/64、
xs_bugcase 27/27、XS 100k difftest 通过（instrCnt/IPC 一致）。

### P6：编译总时长压降（2026-10-21，方案 1+2+3）

背景：P5 收尾后 SV→CPP→emu 端到端编译 32m26s（seg1 1391s + seg2 555s），
用户要求压进 30min。执行方案 1（流程裁剪）+ 2（生成代码/规划）+ 3（simplify
深挖）。

**方案 1：checkpoint 往返校验 flag 化（-105s）**
`wolvrix_xs_grhsim_ir.py` 的 round-trip 稳定校验（load fresh 67.7s +
store 36.8s）原为无条件步骤。改为 `--roundtrip-verify`（BooleanOptionalAction，
**脚本默认 ON**——xs-bugcase/xs-components 等 20+ 个直接调用方行为不变）；
XS 生产流 Makefile 默认传 `--no-roundtrip-verify`，
`XS_WOLF_GRHSIM_IR_ROUNDTRIP_VERIFY=1` 可开（verify=1 的 resume 全流已实测
通过，字节级一致校验仍可用）。

**方案 2a/2b：replicate 字填充 + unpack memcpy 扩展**
- 宽位 replicate 旧实现是运行期循环 `cpu_rep|=(W)(elem)<<(i*ew)`，对
  212×64→13568 等实例每次调用 O(rep×words)（45k 字操作/次）。改为容器字
  直接填充：64%ew==0 时先构造 64 位 broadcast 模式再按字写（memcpy/字循环），
  ew%64==0 且宽元素时按元素 memcpy；小端守卫与 packStoreRows 相同，其余回退
  原循环。主要收益在仿真侧。
- unpackValue memcpy 快速路径从 ew∈{8,16,32,64} 扩展到 ew%64==0（容器无填充）。
  实测 elide 模型剩余通用 unpack 点仅 ~2.8k 且行数普遍 ≤8（早先估计的 62k
  是过期口径），本项收益边际。

**方案 2c：TU 规划器 fanout 估算修复（seg2 主杠杆）**
seg2 构成：1218 个模型 TU 编译跨度 529s（difftest make -j28 按 tu 序号顺序
编译）。发现两类失衡：
- tu1069/70/71 各 64-95 万行（估算 32.7k 行），占 300-340s/个——根因：
  `estimateSupernodeLines` 对 activity-flag 扇出几乎不计费，而 XS small-sink
  写每次变更广播数十个 flag 字（sn_45570 单函数 9994 行中 9462 行是
  flagAcc 声明/累积/写回），低估 20-29 倍。
- 尾部：tu1072（5.3 万行宽 _BitInt 代码，含 8192 位 op）最后完成，
  27 核空转 ~150s。
修复：估算器按 schedule 的 commitStateFanout/computeSupernodeFanout 对
每个写收 6+distinctFlagWords 行、每个 supernode 函数收 2×unionWords
（声明+写回）；另对 `core.system.task` 按 arg 数计费（每个 arg 是一次
grhsim_make_task_arg 调用，PERF 计数器 fwrite 单 arg ~14ms 前端耗时，
97 行 4.4MB 的 tu1471 单 TU ~460s）——实测 plan-TU pass 40.3s（+2.7s），
units 1218→1792，max_unit_estimated 仍封 32768 cap，最大实际 TU 从 95 万
行降到 7.6 万行。
**曾尝试**将 plan.units 按估算降序重排，已回退：chunk 流（init/scan 等）
要求跨 unit 按计划顺序密铺（emit 的 tiling 校验直接报错），且 general scan
调用顺序承载同轮激活语义，不可乱序。**正确做法**：plan 与 .cpp 内容保持
流序，只在生成 Makefile 的 SOURCES 列表按 estimatedLines 降序——编译顺序
与内容顺序解耦（difftest make -j28 按列表顺序编译，archive 成员顺序不影响
链接语义）。同一份 t2c2 模型实测：顺序编译跨度 629s → 前置后 **495.7s**
（-133s，-21%）。

**方案 3：simplify profile（perf record -F 999 --call-graph fp，resume seg1）**
- 扁平 profile：parseCpuConstLiteral 所在内联区 6.85%、StringInterner::text
  4.39%、verify 2.25%——通用 helper 死亡千刀，无单点。
- 分窗（simplify whole/phase）50-70% 样本落在一个 ~23 字节热循环。符号化
  反复踩坑（.so 被后续构建覆盖，就近符号漂移到 __make_heap）；ccache 重链
  同时代 .so 后定位为 **`simplifyStepUsedBits` 内部的 memset 型向量分配**。
  疑似主因：whole 8 轮 + phase 3 轮里每步每轮对 ~1M 项大向量的
  assign/resize 与 model.compact()（compact 在 canonicalize 窗口也占 4.86%，
  每步删除后全量重建 op/value 数组，~66 次/全流程）。定为后续工作
  （跨轮复用缓冲 / compact 阈值化），本轮未动。
- GRH 侧（干净流独有）：xmr-resolve 102.6s、hier-flatten 67.3s、
  comb-loop-elim 58.8s、GRH simplify 291.3s（iteration 0 占 200s，
  const-fold 132s 为单块最大）。H2 工作队列后 iteration 0 为一次全图
  筛查，剩余是 per-op 成本，无 XS 规模 pre-simplify 转储可深剖（replay
  用的 flat 转储 changed=0，已是简化后图）。

**实测总时长（方案 1+2c 后，干净全流）**：sv→cpp（seg1）1639 s，cpp→emu（seg2）
534 s，端到端编译 2173 s（36m13s）；XS emu 100k 246.3 s（钉核 taskset -c 2），
instrCnt 238,535 / IPC 2.385445 与基线一致，difftest 通过。日志：
`ptmp/grh-simplify-h2-20261020/variant-rerun1/`（2026-10-21 23:26 启动的重跑）。
