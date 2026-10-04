# 20261004 P_mem 写口 enable 影子位图（memEnableBits）

## 元信息

- 日期：2026-10-04 / 作者：kimi
- wolvrix commit：`66000f6` + 未提交工作树（V3-M3 + A1 sink-enable-guard 机制
  （默认关闭）+ 本项改动；A1 机制见 `20261004-sink-enable-guard.md`）
- 根仓 commit：`1b94a8d` + 未提交工作树
- 上游基线记录：`20261004-v3-sixphase-baseline.md`（V3-M3，223.4s）
- 说明：benchmark 的 old/new 流目录均在 `ptmp/grhsim-ir-memenable-bitmap/`
  （old-flow = 本项前构建归档，new-flow = 本项构建）；采纳后已把 new-flow 的
  model/ 与 emu 同步回默认工作目录 `build/xs/grhsim-ir`（默认目标
  `run_xs_wolf_grhsim_ir_emu` 即为新构建，100k 复测 204.4s 端点一致，
  见 `ptmp/grhsim-ir-memenable-bitmap/smoke-default/`）。

## 基线性能

- 机器与负载：AMD Ryzen 9 7950X3D（32 线程），单核定核 `taskset -c 2`，
  无同期干扰任务。
- benchmark 命令与口径：标准口径 `make benchmark_grhsim_ir`（3+3 交替、
  页缓存逐出、定核）；old = 本项改动前的当前构建归档
  （`ptmp/grhsim-ir-memenable-bitmap/old-flow`，即 2026-10-04 16:52 构建、
  基线记录同代码状态的 emu），new = `build/xs/grhsim-ir`（本项改动）。
- 指标定义：宿主时间（emu 自报 Host time spent，100k CoreMark 周期）。
- 数据：old 均值 **223.4s**（基线记录值 222.8/223.9/223.6，sd 0.56）；
  本次 A/B 复测逐次原始值见 `ptmp/grhsim-ir-memenable-bitmap/bench/`。

### 占比证据（perf record 调用栈归因，2026-10-04 采样）

- 方法与数据：`ptmp/grhsim-ir-phase-perf-20261004/`（`perf record -F 999
  --call-graph dwarf` 全程采样 100k 周期运行，214,906 样本；
  归因脚本 `attribute_phases.py`，内联进 eval 的 pPublish/pOutput 按
  反汇编偏移区间归属）。
- 六阶段占比（占总宿主时间）：P_general 83.76%（其中超节点本体 76.6%、
  扫描派发 4.7%）、**P_mem 12.39%**、P_publish 2.55%、P_event 0.81%、
  P_output 0.02%、P_input ~0%；模型外（difftest/NEMU/内核）0.44%。
- P_mem 内部结构（对生成源码普查）：22,641 个写口每轮逐一判断——
  19,458 个（86%）enable 为 boundary 1-bit 字段（散布在 91 万字段的
  BoundaryValueStore 上，缓存不友好），3,180 个为恒 1（`__reg_to_mem`
  静态行变化检测写口，每轮必做 cell 比较），2 个 memStore 回读、
  1 个恒 0。

## 优化方案

- 动机：P_mem 12.39% 中约 86% 端口的每轮 enable 判断是 boundary 大结构上
  的散布读；A1 记录已证明散布守卫读是主要成本项（热分支本身近乎免费）。
- 假设：把 enable 收进稠密影子位图后，每轮的端口扫描从 ~1.95 万次散布读
  变为 ~227 个 u64 字的顺序读（外加需点火的端口），预计 P_mem 大头消除，
  总收益 5~10%。恒 1 端口（变化检测收敛）保持原路径，不在本项范围。
- 改动点：
  - `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`：
    emit 期为每个 boundary 承载的 1-bit 两态 enable 分配稠密位
    （`enableBits_`）；`publishBoundary`/`publishDpiResult` 的
    compare-store 在字段真变化时同步该位；`pInput` 对输入直读 enable
    做同样同步；`init()` 末尾按 boundary 字段一次性构建全部位；
    `emitMemWrite` 的 enable 条件改读位图；`memChunkFn` 对 enable 全部
    被影子化的极大连续 run 外包一层按字 OR 聚合跳过（端口顺序不变，
    未影子化端口仅结束 run）。
  - `wolvrix/include/grhsim/backend/cpu_phase_emit.hpp`：
    `emitSixPhaseCpuCpp` 增加 `memEnableBitmap` 参数（默认 true）。
  - 选项：`cpu.st.emit-cpp --mem-enable-bitmap <on|off>`（默认 on）；
    流程侧环境变量 `XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP=0` 可回退
    （`scripts/wolvrix_xs_grhsim_ir.py`，hdlbits/reemit 共用）。
  - 测试：`wolvrix/tests/grhsim/test_cpu_phase_emit.cpp` 新增
    `memEnableBitmapTest`（行为序列 + 结构断言 + off 模式对照）。
  - 文档：`wolvrix/docs/grhsim_ir/backends/cpu.md` P_mem 段补充位图说明。

### 实现细节：数据结构位置

位图**不在** `boundaryValueStore` 里。BoundaryValueStore 有 90 余万字段、
布局由 named-store layout pass 驱动，正是"散布读"问题的来源；位图刻意做成
独立的稠密副带（64 个 enable 压一个 u64 字，一个 chunk 的端口通常共享 1~2
条 cache line）。boundary 字段仍是权威值（compare-store 照写、其他读者照读），
位图只是镜像。

- 运行时（生成的模型 `grhsim_<Top>.hpp`，类成员区紧跟
  `eventActStore`/`timeslotTriggerFlag`）：
  `std::array<std::uint64_t, N> memEnableBits{};`（N = ceil(影子化 enable
  数/64)）。
- 发射期（wolvrix 侧，`SixPhaseEmitter` 成员，
  `lib/grhsim/backend/cpu_phase_emit.cpp`）：

  | 成员 | 作用 |
  |---|---|
  | `enableBits_` | `vector<const CpuStoreField*>`，bit → 被镜像的 boundary 字段（init() 构建用） |
  | `enableBitOfValue_` | value index → bit；`memEnableGuard()` 把端口 enable 改写成位测试 |
  | `fieldEnableBit_` | boundary 字段 → bit；`publishBoundary`/`publishDpiResult` 的同步 hook 用 |
  | `inputEnableBit_` | input 端口 → bit；`pInput` 直写 hook 用 |
  | `memEnableWords_` | 位图字数（决定 N） |

同步关系：`init()` 末尾按 boundary 字段一次性建位
（`memEnableBits[w]=(field?mask:0)|...`）；之后每次 compare-store 真变化时
hook 一句 `memEnableBits[w]=value?(w|mask):(w&~mask)`。字段只在变化时触碰
位图，维护成本近似为零。

### 生成代码差异（before/after）

以单测双口模型（`ptmp/cpu_phase_emit_tests/cpu_phase_emit/mem_enable_bitmap{,_off}/model/`）做 on/off 精确对照，共四处差异：

```diff
  // 1. 类声明（hpp）
+     std::array<std::uint64_t,1> memEnableBits{};

  // 2. init() 末尾：一次性建位（每字一行）
+     memEnableBits[0]=(boundaryValueStore.memA__w0__enable?UINT64_C(0x1):UINT64_C(0))
+                     |(boundaryValueStore.memB__w0__enable?UINT64_C(0x2):UINT64_C(0));

  // 3. 生产端 compare-store 内：字段真变化时同步镜像位
      if(boundaryValueStore.memB__w0__enable!=cpu_value){
          boundaryValueStore.memB__w0__enable=cpu_value;
+         memEnableBits[0]=(cpu_value)?(memEnableBits[0]|UINT64_C(0x2))
+                                     :(memEnableBits[0]&~UINT64_C(0x2));
          dataActiveFlagNext[...]|=...;   // 原有 fanout 激活不变
      }

  // 4. pMem_c* 端口守卫：散布字段读 → 位测试 + run 级聚合跳过
-     if(((eventActStore[0]>>0)&1)){
-         if(boundaryValueStore.memA__w0__enable&&static_cast<std::size_t>(...addr)<16){
+     if((memEnableBits[0])!=UINT64_C(0)){          // run 聚合：一字为零跳过整 run
+         if(((eventActStore[0]>>0)&1)){            // act 精判保留
+             if(((memEnableBits[0]>>0)&UINT64_C(1))&&static_cast<std::size_t>(...addr)<16){
                  ... writeCell 体完全不变 ...
```

写体、地址/数据/掩码的 boundary 读、act 事件守卫、端口优先级顺序全部原样。

XS 规模统计（新模型 `build/xs/grhsim-ir/model/`）：

| 项 | 数量 | 说明 |
|---|---|---|
| 位图成员 | 227 个 u64 字（≈1.8KB） | 覆盖 14,480 个去重后的 enable value |
| init 构建行 | 227 | 仅启动时执行一次 |
| pMem 位测试 | 19,458 处端口 | 替代原来的散布 boundary 读 |
| run 聚合包装 | 626 个 | 415 个 pMem chunk 内的极大连续 run |
| compare-store 同步 hook | 14,480 处 | 全部 publishBoundary 型；XS 无输入端口直读 enable（pInput hook 0 处，仅作正确性兜底） |
| 未进位图端口 | 3,183 个 | 3,180 恒 1 + 2 个 memStore 回读 + 1 个恒 0，路径不变 |

未触碰：P_event/P_general/P_publish/P_output 全部代码、扫描循环、超节点
本体——除 14,480 行 hook 散布在对应超节点 TU 里外，其余生成代码逐字节相同。
- 风险与回退：风险点是位图与 boundary 字段的一致性——boundary 字段的全部
  写路径已枚举（publishBoundary、publishDpiResult、pInput 直写、init 流），
  逐一挂同步钩或在 init 统一构建；常数 enable 折叠后不进位图（
  staticScalars_ 排除）。回退：`XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP=0`
  重新发射，或 git 还原。

## 结果性能

- 同口径数据（`make benchmark_grhsim_ir`，3+3 交替、页缓存逐出、定核 CPU 2，
  全部 6 次命中期望终点 240349/99996/100001/0x80000c0c；
  `ptmp/grhsim-ir-memenable-bitmap/bench/`）：

  | | old（本项前构建） | new（本项） |
  |---|---|---|
  | 逐次宿主时间 (s) | 224.379 / 223.666 / 224.240 | 204.556 / 204.024 / 203.761 |
  | 均值 ± sd (s) | 224.095 ± 0.378 | 204.114 ± 0.405 |

  **改进 8.92%**（rank gate 通过：max(new) < min(old)；cliff_delta=-1.0；
  one-sided exact p=0.05）。对 M0 差距：2.60×（223.4s）→ 2.38×（204.1s）。
- 编译时间影响：emit 阶段不变（仅生成文本微调；本次因机器并发不可比，
  未单列）；模型全量编译（clang -O3，1082 TU）重构前 14.5 min，本次
  与 smoke/benchmark 交错未独立计时，TU 数与生成代码体量不变
  （新增 227 字位图数组 + 每端口一处位测试，详见"生成代码差异"节）。
- 复测阶段占比（perf 复采样，`ptmp/grhsim-ir-phase-perf-20261004/perf-new.data`，
  196,045 样本，同一归因脚本，inline 偏移按新二进制反汇编重钉）：

  | 阶段 | 改动前占比 | 改动后占比 | 改动前绝对时间 | 改动后绝对时间 |
  |---|---|---|---|---|
  | P_general | 83.76% | 92.12% | 187.7s | 188.0s（不变 ✓） |
  | **P_mem** | **12.39%** | **3.57%** | 27.8s | 7.3s（-20.5s ✓） |
  | P_publish | 2.55% | 2.88% | 5.7s | 5.9s（不变 ✓） |
  | P_event | 0.81% | 0.88% | 1.8s | 1.8s（不变 ✓） |
  | P_output / P_input | 0.03% | 0.03% | ~0.1s | ~0.1s |
  | 模型外 | 0.44% | 0.50% | 1.0s | 1.0s（不变 ✓） |

  P_mem 的 -8.8pp 与 benchmark 的 -8.92% 总量改进吻合；其余阶段绝对时间不变，
  证实收益来源单一、无误伤。P_mem 残余 3.57%（7.3s）主要是 3,180 个恒 1
  enable 的 `__reg_to_mem` 静态行变化检测端口（每轮必做 cell 比较）——
  见"后续"。
- 结论：**采纳**（默认开启；`XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP=0` 可回退）。

## 正确性验证

- [x] `make test_wolvrix`：54/57，恰基线三项（transform-comb-lane-pack /
      transform-repcut / ingest-write-back-slice SEGFAULT），无新增失败；
      其中 `grhsim-cpu-phase-emit-tests` 含新增 `memEnableBitmapTest`
      （行为序列 + 结构断言 + off 模式对照）通过
- [x] `make run_all_hdlbits_grhsim_ir_tests` 162/162（exit 0）
- [x] `make run_xs_bugcase_grhsim` 25/25
- [x] `make check_sim_refactor_baseline` 161/161 逐 eval 一致
- [x] XS 完整 CoreMark + NEMU difftest：HIT GOOD TRAP、exit 0，
      逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291 一致
      （`ptmp/grhsim-ir-memenable-bitmap/full/`，Host 594.4s）
- 日志路径：`ptmp/grhsim-ir-memenable-bitmap/{bench,smoke,full}`、
  `ptmp/grhsim-ir-phase-perf-20261004/`（perf 采样与归因脚本）

## 后续

- P_mem 残余（改动后 3.57%）：3,180 个恒 1 enable 的 `__reg_to_mem` 静态行
  端口每轮做"boundary data 读 + cell 比较"。这些端口的 data 字段同样经
  compare-store 发布——可把"数据未变 ⇒ 写必无效果"做成 data 字段脏位门控
  （publishBoundary 已检测字段变化；位图机制现成可复用）。注意多端口同行
  优先级：静态行已知的 `__reg_to_mem` 端口间行不相交，可精确判定无级联。
- 每 eval 轮数（~2 轮量级）仍待 WOLVRIX_GRHSIM_PERF=1 复测确认；scan
  （4.7%）/pMem 守卫/publish（2.9%）等每轮成本对轮数敏感。
- P_general 92% 成为绝对主体：sink 簇（改动前口径 9.4%+2.0%）与 3.6 万
  小超节点长尾是下一个大头；backlog 的 en 静态化、ThinLTO/内联评估应基于
  本次的 perf 解剖数据。
