# Stage 07 — preserve-aggregate 端到端与 reg-to-mem 退役

- 日期：2026-10-08（2026-10-08 修订：comb-lane-pack 移除由评估项改为既定项）
- 状态：进行中（2026-10-10 开工；7a/7b 已落地，7c/7d 进行中）
- 依赖：stage-04（ingest 聚合保留）、stage-05（comb-loop-elim）、stage-06（grhsim 承接）
- 对应总目标：#10 终极目标

## 实施记录（2026-10-10，开工即写，验收后收口）

### 7a/7b 落地事实

- `testcase/xiangshan/Makefile`：`PRESERVE_AGGREGATE` 变量化（空=firtool 默认 none，
  aggregate 链路传 all），追加 `--firtool-opt "--preserve-aggregate=$(PRESERVE_AGGREGATE)"`。
- 根 Makefile：`$(XS_SIM_TOP_V)` 与 `xs_gsim_rtl` 的 mill 调用补 `XS_MILL_ENV`
  （`XS_JAVA_HOME ?= /usr/lib/jvm/java-17-openjdk-amd64` 存在检测 + 仓库根 mill launcher
  进 PATH）——原规则依赖操作员手工环境，新机器上 JDK25 必炸（mill 0.12.15 需 JDK17）。
- 新目标族：`xs_rtl_aggregate`（独立目录 `build/xs/rtl-aggr`）、
  `xs_wolf_grhsim_ir_aggregate(+_build_emu/_emu)`、`run_xs_wolf_grhsim_ir_aggregate_emu`
  （全部委托既有目标 + 变量覆盖：XS_RTL_BUILD/XS_GRHSIM_IR_BUILD/XS_WOLF_FILELIST/
  emit dir/XS_PRESERVE_AGGREGATE）。`xs_rtl_aggregate` 实测 375s 产出 2148 个 split
  文件，与探针产物一致。
- `scripts/wolvrix_xs_grhsim_ir.py`：`CPU_SEMANTIC_PIPELINE` 移除 `grhsim.reg-to-mem`，
  4 个 reg-to-mem CLI 参数删除；新增 `--dump-pre-simplify-json` 诊断旋钮；
  GRH_PIPELINE 在 comb-loop-elim 后与 simplify 后各加一步 `grh.verify`
  （加固：几何违例不再一路漏到 const-fold/grhsim 才炸）。
- 探针待补项关闭：mill 全链路复核 → 已正式落地为 `xs_rtl_aggregate`；`=vec` 不采纳
  （`all` 一次通过且保留 struct，`vec` 只小 43% 但丢 struct 无收益）；comb-lane-pack
  残留注册点确认无（源码侧仅 comb_pack.cpp 一行历史注释）。
- xs-components/rob.mk 两处调用同步去除 reg-to-mem 参数。

### 7c reg-to-mem 退役（三步压缩为一次落地）

- 7c-1/7c-2/7c-3 顺序执行、一次验证：wolvrix 侧删 `reg_to_mem.cpp/.hpp`、pass.cpp
  注册点、3 个测试 + 3 个 data 文件（−3234 行）；`docs/grhsim_ir/passes/reg-to-mem.md`
  转 RETIRED 历史记录（负结果知识保留）；overview.md/cpu-st.md 退役注记。
  外层：benchmark/measure/test 目标族与配套脚本删除。
- `test_grhsim_whole_opt.cpp`：删 reg-to-mem 专用段（A3 fixture + transformed=1 断言）；
  移除后 tbl_* 四行译码 mux 暴露给 comb-pack，comb-pack 期望由 groups=1/lanes=4
  修正为 groups=2/lanes=8（注释注明）。
- 门禁即时结果：ctest 57 项 56 过（余 transform-repcut 既有）；hdlbits 162/162；
  xsbug 25/25；**trace 基线 162/162 逐字节一致——reg-to-mem 在 HDLBits 零触发，
  计划中的"重钉"实证为不需要**。
- 负结果知识锚点：pass 退役文档 + `pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`；
  census 分析脚本（grhsim_bucket_dyn_price.py 等）的 "(reg-to-mem)" 分桶标签保留
  （只匹配历史 artifact，非门禁项）。

### 编译期攻坚（本阶段最大偏差：aggregate 首轮 simplify 超线性爆炸）

首轮 aggregate 管线在 GRH simplify 跑了 103 分钟并以 `kSliceArray base value must
carry a shape` 失败。逐层归因与修复（全部实证驱动）：

1. **simplifySlices 的 O(n²) 环守卫**（perf 采样 + 分阶段计时定位）：每个
   kSliceStatic-over-kConcat 候选都做一次全新锥 DFS（带按值物化拷贝）。
   聚合设计 18.7M values 下 simplifySlices 单轮 700s。
   修复：新建 `lib/transform/topo_guard.hpp`——每 sweep 一次 Kahn 拓扑分层
   （valueRank 沿 def-use 严格递增，`rank[o] <= rank[r]` 即证明无依赖，跳过 DFS；
   残留组合环区/新建值无 rank → 回退 lean DFS（stamp 数组取代每调用新建
   unordered_set））。清扫循环同步改 lean（Graph 公开 id/span 访问器，不再
   getValue/getOperation 肥拷贝；fat op 仅在采纳重写时物化）。
   效果：simplifySlices 700s → **127s**（守卫计数 fastSafe=88321 / dfsFallback=8044）。
   有效性论证：sweep 内 replaceUsers(r→o) 只加 rank 一致的边（rank[o] ≤ rank[r] <
   rank[user]），擦除只删边，故 sweep 开始时的拓扑序全程有效；S5 comb-loop-elim
   残留真组合环（本设计有 ~18k-op 环区，status=true analysis=incomplete）经
   generation 校验落到 DFS 回退，语义不变。
2. **同款 DFS 在 redundant-elim 的 4 个调用点**：接入 topo_guard（RE sweep 的
   重写同样只加 rank 一致边）。RE 主 sweep 与 CSE 的肥拷贝由子代理 lean 化重写
   （kConstant 排除出 CSE——常量去重本就是 const-fold ConstantPool 职责；
   makeSignature 不再把巨型 constValue 字符串拷进签名）。
3. **shape 根因修复**（S6 遗留"折叠/别名代表元丢 shape"归 S7 复核，实证闭环）：
   - const-fold/redundant-elim 的 `replaceUsers` 包装加回填：被替换值带 shape、
     替换值扁平且同宽同 Logic 型时，把 shape 回填给替换值（packed-first：shape 是
     结构视图）。修复前：simplify 第二轮即报 `kSliceArray base value must carry a
     shape`（基值经别名/CSE 替换丢 shape）；修复后 8 轮迭代全收敛无错误。
   - **verifier 双向放宽**（kRegisterReadPort 整体读）：52 个
     `result shape [..] does not match register shape []`（hier-flatten 引入：
     标量轨寄存器经端口连接继承了对侧 packed 类型的 tiling 视图）+ xs-bugcase
     4 例反向（shape 寄存器 + 扁平结果）。按 packed-first 教义，整体读结果只校验
     位宽一致 + shape 精确铺满位宽，不再要求与声明 shape 严格相等。grh-ir.md
     §6.4 kRegisterReadPort 契约同步。
   - 归因手段（都留在仓库里可复用）：`--dump-pre-simplify-json` 旋钮、
     ptmp 诊断驱动（逐 pass grh.verify 二分定位到 hier-flatten）、per-call
     checkpoint 复现循环、const-fold 分阶段计时与守卫计数
     （`WOLVRIX_SIMPLIFY_PHASE_TIMING` / `WOLVRIX_CONST_FOLD_GUARD_STATS` env 门控）。
4. 修复后隔离测量（pre-simplify checkpoint 起，simplify 全迭代）：
   首轮 ~1335s（const-fold collectConstants 85s / iterativeFolding 96s /
   simplifySlices 127s / RE 537s / DCE 24s 起步，迭代内递减），第 2 轮起 ~32s
   收敛。**残余编译期热点 = RE 首轮 + 常量机器**（17M ops 中 kConstant 560 万、
   kSliceStatic 321 万——firtool 逐元素展开写的字面量机器；达到 <10min 编译
   目标需要图瘦身：ingest 常量 interning/常量表达式预求值 + mux-tree→动态访问
   逆向识别，归 stage-08 候选）。

### 偏差与顺手修复登记

- 操作教训：多个 Make 目标硬依赖 py_install，并行跑门禁时两个 pip editable
  install 竞争导致 "partially initialized module" 假象失败——重跑前串行化
  py_install。xsbug 首轮 12/25 失败全部为此假象。
- `Design::Design(Design&&)` 等 GRH 容器搬迁成本在聚合设计（19M values）下成为
  显性热点——本次未动（涉及核心 IR 布局，留作后续编译期优化候选）。
- XS 管线新增 grh.verify 两步是行为加固（只读 pass，只报不改）。

### 当前阻塞（2026-10-10 深夜，aggregate 链路最后一里）

门禁全绿、GRH 段全过（含新增 grh.verify 两步）、lowering 与 GrhSIM 语义段全过、
B8 seal 通过；**失败点 = `cpu.st.build-general-nodes`：compute graph 存在组合环**。

实证链（全部可复现，工具在 `ptmp/xs-aggr-diag/`）：

1. aggregate 设计 comb-loop-elim 残留 8 个环（loops=48 true=8，Frontend/TLB/
   MemBlock/DCache 控制区，最大 21086 ops），全部 `analysis=incomplete`；
   基线标量化设计**零环**（当前 comb-loop-elim 跑基线 RTL 复核 loops=0，
   排除 S5 回归；基线 flat GRH Kahn 拓扑残余=0）。
2. 环内容实样（flat GRH 提取，20-op 环）：`replacer$stateBank` 动态读
   `kRegisterReadArrayPort(stateBank[trainReadSetIdx])` 的结果经 wayMask/hit 组合锥
   回馈到 `trainReadSetIdx` 的计算——**读索引组合依赖读结果**，经动态状态数组读
   形成值级环。
3. 基线不存在该环的结构性原因：标量化形态 + reg-to-mem 把这些状态 bank 恢复为
   mem 存储（读为 mem 读口），环结构从未形成；aggregate + 无 reg-to-mem 的形态
   把动态读以单值端口形式保留，值级环出现。**环问题与 reg-to-mem 退役是纠缠的**。
4. comb-loop-elim 的 S5 既定保守分支（含动态读的环不可判定时保留）按设计工作，
   不是 bug。
5. **环的两个具体形态**（flat GRH 逐边提取实证）：
   - **struct 端口束的 pack→slice 往返**：模块边界上 struct 类型端口被打包成一个
     巨型 kConcat（实测一例 120+ 字段整束打包），对侧再逐字段 kSliceStatic 切回；
     束内字段间经真实逻辑互依（如 crossPageWithHit 依赖 sqPtr 字段），值级图上
     共享束节点形成假环（位级无环，Verilator 无 UNOPTFLAT 豁免需求）。
     baseline 无此问题是因为 firtool 默认把 struct 端口也摊平成逐字段标量端口。
   - **动态状态数组读回馈**（replacer stateBank：读索引组合依赖读结果）。
6. 首轮修复方向由此明确：消灭 struct 端口束的 pack/slice 往返（逐叶连接直通），
   让共享束节点不出现；动态读环另行处理。

### 更深的根因（2026-10-11 凌晨实证，优先级最高）——已修复

环分析 bail 的直接原因不是动态读——**8 个环全部 bail 在同一个 kConcat 上**：
该 concat 的结果宽度错（= 操作数个数而非位宽和，如 136 操作数 1350 位却只给
136 位）。这是 ingest 聚合表达体系的**普遍宽度簿记 bug**：`grh.verify` 新增
kConcat 宽度校验后，ingest 后直接报 **58247 处**错宽 concat（Rob/
RenameTableWrapper/LoadQueueReplay/AheadBtb 等聚合 pattern 密集模块）。

- 该 bug 自 S4 起隐性存在（聚合设计从未跑过仿真；当时的 verify 不查 concat
  宽度）。它不只是环分析的障碍——错宽值的切片读出界，是真实的仿真正确性 bug。
- 修复序列（每层修完下一层才可见，逐层剥洋葱）：
  1. plan 层三处 hint 默认点（lowerArrayPatternValue/concatArrayElements/
     flattenStructExpr）：未知元素宽度兜底从 `: 1` 改为元素/叶子类型宽度；
  2. **emit 层决定性修复**：emitExpr 的 kConcat 结果宽度原只在
     `widthHint<=0` 时才按操作数重算——改为**无条件重算**（hint 只做参考）。
     仅此一条，58247 → 0；
  3. 写侧数据宽度按寄存器声明归一（emitMemoryWrites/emitWriteBack：
     写口数据 resize 到被寻址子数组宽度）——kRegisterWriteArrayPort 4979 → 0；
  4. 实例输入端口连接按端口声明宽度 resize（IntRegFile 的 [3:0][5:0] 打包数组
     端口被 4 位驱动需要零扩展）——kInstance 宽度错清零。
- 最终 **verify-after-ingest 0 错误**（5689→12→0）。环的范围分析不再需要
  bail 于畸形 concat；CLE/CPU 映射的表现由全管线复跑验证。

### 环分析收口（2026-10-11）——kSliceDynamic 动态索引建模，无需 stage-08 断环

8 环经宽度修复溶掉 3 个小的后，剩 5 个大环（18337/21070/8546/9062/11847 ops，
srcLoc 均为 `transform:xmr-resolve:instance_out`）全部 bail 在 buildRangeGraph 的
**kSliceDynamic 处理器**：索引非常量时直接 `uncertain=true` 放弃，而非建模。

修复（`wolvrix/lib/transform/comb_loop_elim.cpp` kSliceDynamic 分支）：动态索引时
不再 bail，加保守全区间边 `base(full)→result(full)` + `index(full)→result(full)`
（仅当两端在 loopSet 内），与 kSliceArray 动态读的全区间归一化同精神，交由 range
SCC 判定真假环。

实证（pre-CLE checkpoint 复放，`WOLVRIX_CLE_DEBUG=1`）：
**loops=48 true=0 false=48 false-fixed=48**（修复前 true=5）——所有残留环均被
range SCC 证伪，无一需要断环。上文"动态读环断路属 stage-08 级工作"的旧结论
作废：那些环不是真环，只是分析盲区。

连带测试更新：`test_grhsim_ir.cpp` 的 readArray shaped-index 用例从"拒绝"改为
"接受"（stage-07 packed-first 契约下索引按扁平整数读，shape 视图良性）。

### 最后一里的真根因（2026-10-11 下午）——SoA 叶切片布局错位，非环问题

CLE 清零后全管线仍死于 `cpu.st.build-general-nodes`（"six-phase flat branch
contains a dependency cycle"）。逐层实证（诊断设施：新增
`WOLVRIX_CPU_PARTITION_CYCLE_DUMP=<path>` 环境变量，在 throw 前倒出环成员的
op/类型/名字/依赖；pre-partition GrhSIM checkpoint 可经
`XS_WOLF_GRHSIM_IR_DUMP_PRE_PARTITION_JSON` + `..._RESUME_FROM_FLAT_GRH_JSON=1`
在 ~5min 内复现）：

1. Event flat 分支残留 240 个不可调度 op = 两个 30 元 SCC（mbtb alignBanks_0/1
   镜像）+ 下游粘连。SCC 核心：`state.readArray(stateBank$states)` 的读索引
   `io_trainReadSetIdx` 经 LruStateGen/wayMask 锥依赖读结果 `io_trainReadState`。
2. 但源 RTL（`MainBtbAlignBank.sv`/`MainBtbReplacer.sv`）**无此环**：
   `io_trainReadSetIdx = io_touch[1].bits.setIdx`，`_GEN_31.bits.setIdx =
   s3_replacerSetIdx`（寄存器），train 触摸的 wayMask 才来自 victim 逻辑。
   基线标量化设计 CLE loops=0 也佐证源级无环。
3. 位级核算定案：`io_touch` 是 `struct packed {valid, bits:{setIdx[7:0],
   wayMask[3:0]}}[1:0]`（26 位，元素主序）。`io_touch[1].bits.setIdx` 应为
   bundle `[24:17]`，而 flat GRH 实际接的是 `[23:16]`——**整整偏 1 位**
   （`valid` 字段宽度），把 `wayMask` 的位接进了读索引，凭空造出环。
4. 根因：stage-04 SoA 叶拆分内部约定"字段主序"（同一字段的所有元素连续，
   `aggregateLeafOffsets`/`structLeafOffsets`），而 SV 打包布局是"元素主序"。
   两者在**带外层的 packed struct 数组**上不一致。凡是"裸扁平值 ↔ 叶值"
   的翻译点都用字段主序偏移切/拼，遇到 struct 数组端口/表达式即错位：
   - 实例输入端口连接（`ingest.cpp` emitInstances 的 struct 端口分支）——
     本 bug 的肇事现场；
   - `lowerStructRhsValues` 扁平 RHS 路径、`lowerPatternComponent` 扁平路径、
     struct 整型字面量切片（同法切片方向）；
   - `flattenAggregateValues`/`flattenStructExpr`（反方向的字段主序 concat）。
   纯 struct（无外层数组维）时两种布局相同，所以 bug 只在 struct 数组上出现。
5. 修复：新增 `collectSvLeafSegments`（ingest.cpp，类型递归走 SV 打包布局，
   产出每叶逐元素段表 `{flatOffset, leafOffset, width}`；unpacked 维/union
   无打包布局，返回失败走旧路径兜底），上述六个现场全部改为按段表
   gather/scatter；平凡布局（无外交错维）保持旧单切片/整叶 concat 快路径不变。
   建值方向（concat 叶值）按段表降序 flatOffset 拼。
6. 最小复现（`ptmp/aggr-layout-repro/top.sv`）：packed struct `[1:0]` 端口 +
   concat 驱动 + 动态数组读。修复前 setIdx 叶 = `slice [23:8]`（错），修复后 =
   `concat(bundle[24:17], bundle[11:4])`（对）；全 GRH 管线 CLE loops=0。

影响面评估：这不只是调度障碍——错位接线本身是**仿真数据错误**（读索引接到了
wayMask/valid 的位上）。凡 preserve-aggregate 下 packed struct 数组端口用扁平
表达式（concat/字面量/整束引用）驱动的设计都受影响；基线标量化流无此类端口，
门禁全绿不受影响。

### 配套修复（同日）：CLE 看穿寄存器数组读的索引边 + 单体 op 分裂重写

布局修复后，replacer 环退化为**值级假环**（位级已无环：`setIdx`/`wayMask` 位段
不相交），但它穿过 `kRegisterReadArrayPort`——CLE 的 boundary op 把整个读端口
（含索引边）排除在分析外，假环永远不可见，GrhSIM 扁平分支（值级拓扑）照旧卡死。

修复（`wolvrix/lib/transform/comb_loop_elim.cpp`）：

1. 扁平图与范围图都放行 `kRegisterReadArrayPort`，但只建 `index(full)→result(full)`
   边（状态内容不进图，仍是边界语义）；范围 SCC 由此能把这类假环证伪。
2. 假环分裂器此前遇非拷贝映射 op（kShl/kSub/…/kRegisterReadArrayPort）直接
   `return false` 放弃（`false-unresolved=2` 即这两个 replacer 环）。新增
   `isMonolithicLoopOp`：此类 op 结果强制整值单段（unsplittable）、操作数以
   full-view 重组、原位改写——与 compare/kSliceArray 的既有单体路径同型。
   实测 **loops=49 true=0 false=49 false-unresolved=0 false-fixed=49**
   （比上轮多 1 个环正是新看见并溶掉的 readArray 环）。

遗留语义备注：若未来出现**位级真**的 `idx = f(state[idx])` 环，CLE 会如实报
true loop，CPU 映射器仍会拒绝——那是真实的组合环，需要 mem 化或迭代调度语义，
届时再议（本阶段 XS 全核未出现）。

### 同族宽度簿记 bug 第二批（emit 段才暴露，最小复现 `ptmp/aggr-layout-repro/tlb_repro.sv`）

布局修复后管线首次抵达 emit，又剥出两层：

1. **emit 校验过严**：`cpu_phase_emit.cpp` 的 system task 校验拒绝一切带 shape
   的实参——按 packed-first 契约放宽：shaped logic 按整宽扁平整数打印（SV 对
   packed 数组本就整体打印），非 logic 的 shaped 实参仍拒绝。
2. **叶子元素选择的宽度双重计数**（`applyReadSlices`，读路径）：折叠叶
   （shape 清空）上 `arr[i]` 的位宽算成 `elementWidth × ∏剩余维`，而
   `packedDimInfos` 已含叶子自身宽度维——实测 `req_out[1'h0]`（[0:0] 外层维）
   读出 2500 位（50×50）。改为**扁平宽 ÷ 被消费维 extent**（与连接侧
   `elementSelectOnLeafConn` 的既有公式一致）。
3. **写路径同族**（`resolveSliceSelection` 的 BitSelect 分支）：叶子类型不含
   外层维（在 SignalInfo 元数据里），`getPackedArrayElementSlice(叶类型)` 为空
   → 宽度兜底成 1——整元素写 `req_out[1'h0] <= '{...}` 的掩码变成只写 bit 0！
   修复：类型查不到时查目标 SignalInfo 的 `packedDimInfos`，同样用
   扁平宽 ÷ extent。修后整元素写正确地变为无掩码 `kRegisterWritePort`。
   （连带修复：叶路径命中后不再重复扣 packedOffset——否则普通 `[3:1]` 寄存器
   位写会双重减偏移，HDLBits dut_059 曾因此回归。）

### emit 段修复（宽常量 parser 栈溢出）

- `cpu_phase_emit.cpp::literal` 的宽常量按每字一对括号左嵌套，数千词的 init
  常量（聚合存储的零填充）把 clang parser 递归栈撑爆（tu13 段错误）。
  修复：>16 词改走语句形式 lambda（与既有大 concat statement form 同模式），
  全零常量直接 `(wide_t)0`。
- **编译期体量警示**：aggregate 模型 emit 出 7463 个 TU（基线 1091），
  `clang -O3 -j32` 全量编译约 95 min——约 7× 于基线。这是 preserve-aggregate
  保留宽向量/大 concat 的直接代价，是后续编译期优化的头号对象（估算行数
  启发式对宽 op 的成本模型、TU 装箱粒度都还没适配）。

### 图瘦身主修复（2026-10-11）：mux-tree-fold pass + ingest 元素读 widthHint 根修

背景：aggregate 首轮编译期失控（GRH simplify 超线性 + emit 7463 TU / clang 95min+），
用户明确要求"必须先做 mux 树折叠"——把 firtool `--preserve-aggregate` 展开的三个
常量索引形态逆向恢复为动态数组访问，在图最小的模块级阶段（xmr-resolve 之后）
直接缩小后续所有 pass 与 emit 的输入。

**新 pass `mux-tree-fold`**（`wolvrix/lib/transform/mux_tree_fold.cpp`，GRH 流水线
第 2 位，xmr-resolve 之后、memory-read-retime 之前）：

- **读 mux 树 → 动态读**：`idx==c0 ? arr[c0] : ... : arr[cN-1]` 全覆盖（条件 =
  同一下标值与常量比较、叶子 = 同寄存器常量索引元素读、下标集合精确铺满
  [0,N)）折叠为 `kRegisterReadArrayPort(arr, idx)`；下标可能越界时补
  `mux(lt(idx,N), idx, tailIdx)` 钳位（保持树尾部语义）。
- **逐元素写译码 → 动态写口**：每 entry 一条 `arr[e] <= chain_e`，链 =
  `hit_i ? d_i : ... : arr[e]`（hit_i = en_i & (ptr_i==e)，兜底自读保持）或
  常量兜底，全 entry 结构一致（同一 ptr/data/enable 表达式，结构等价比较
  `sameValue`）时折叠为每源一条动态 `kRegisterWriteArrayPort(en_i, ptr_i, d_i)`
  ——优先级 = 链嵌套序（最外层最高），按 op 声明顺序排放（IR 写口优先级语义）；
  常量兜底加一条低优先 `kRegisterFillPort`，统一常量复位写折叠为高优先 fill。
  OR-of-ANDs 形态（条件可重叠，优先语义不等价）**保守不折**。
- **pad 拼接读 → 钳位动态读**：`kSliceArray(concat(replicate(arr[p])…, arr…), idx)`
  （firtool 的 `{160{e0}, arr}[idx]` 补长形态）折叠为
  `arr[idx < N ? idx : p]`（元素 pad）或 `idx < N ? arr[idx] : const`（常量 pad），
  消灭最宽的 _BitInt 物化（robEntries 案例：160×470=75200 位 replicate +
  512×470=240640 位 concat）。
- 折叠后接工作清单驱动的死锥清扫：纯组合 op 结果无使用者即删（含
  declared-symbol 线网——pass 位于 xmr-resolve 之后，跨模块引用已解析，
  这些线网是被折叠语义完整替代的临时产物）。全图扫描 + 可重入工作清单
  （不用 visited 集——使用者后死必须可复检）。

实测（XS aggregate 一轮）：fold 本体 **7.2s**；writeGroups=408、padReads=2138、
readTrees=0（读侧 mux 树在真实设计里都属于写译码链内部，无独立全覆盖读树）、
swept≈58 万 ops。效果：simplify **1335s+（首轮）→ 368s**，hier-flatten 88s→68s，
CPU 段图量 -6%（partitions 176 万→165 万，TU 1398→1342）。

**ingest 元素读 widthHint 根修**（mux-tree-fold 的 P 匹配连带挖出的**潜在功能
bug**，比编译期更严重）：

- 症状：packed struct 数组的**整元素读**（`entries[3'h0]`、`{160{robEntries[0]}}`
  的 replicate 操作数）装配成 `{63'b0, data0, 7'b0, tag0}` 这类带
  "字段宽−1 个零"填充的错误 concat（142 位值驱动 72 位目标）。
- 根因：`elementSelectOnLeaf`/`applyReadSlices` 对 packed 维选择给
  `makeSliceArray/makeSliceDynamic` 传 widthHint=1，graph 层元素读实际宽度是
  元素宽（64）；`resizeValueToWidth` 信任 widthHint=1 → 补 63 个零。
  修复：widthHint 改为 `flatWidth/extent`（与连接侧 `elementSelectOnLeafConn`
  调用方既有公式一致）；`SignalInfo.width` 口径为元素宽、`shape` 为维，
  `applyReadSlices` 统一用 `signalTotalWidth(info)/extent`，选择收缩跟踪
  同步擦 `shape` 首维。复现/验证资产：`ptmp/mux-fold-repro/`（gen/dump/verify/
  iso1/iso2 + 全管线通过）。
- 该 bug 自 stage-04 SoA 引入起即存在，aggregate 流从未跑过功能验证所以潜伏；
  标量化流（无 packed struct 数组）免疫。**它是 emu/difftest 的前置必修项。**

**待办/回归登记**：

- comb-loop-elim 在本轮回退 **142s → 672s**（loops=49 同前、dyn-array=0、
  split-values=3636、split-ops=152442、fix-iters=2）——**归因更正**：时间线复核
  （10-11 各轮日志）显示回退发生在 09:12 轮（retargeted-slices 7440→34627，
  165s→737s），早于 mux-tree-fold，是当天凌晨 SoA 叶布局修复使更多切片可
  retarget 所致，与本 pass 无关；本 pass 轮 CLE 672s 持平略优。perf 叶符号：
  ~50% 在 Value/Operation/SrcLoc 按值物化（`SrcLoc` 拷贝、`valueFromBuilder`、
  `operationFromBuilder`）+ ValueId 哈希插入，驱动点是
  `retargetLoopSliceEntrances` 的 while 不动点对 loopOps 全扫 × 每次 10-15 个
  按值拷贝。优化已立项（零拷贝访问器 + 单遍链式解析取代不动点）。
- 读 mux 树零命中：探针 §7.5 里"读侧树"实证均在写译码链内部，R 匹配器暂为
  预埋能力。
- emit/clang 体量只降 ~10%：emit 1342 TU / 19.2M 行 / 2.4GB（前轮 7463 TU /
  21.2M 行 / 2.7GB，估算器修正前轮为 1389 TU）；17M ops 的大头（常量/切片
  机器、struct 端口束 pack/slice 往返等）不在本次三个形态内，归 stage-08 候选。
- **ROB 本体未折叠**（零 writeGroups 命中，WOLVRIX_MUXFOLD_DEBUG 在 pre-CLE
  checkpoint 上复核）：robEntries 系（debug_exuData 等，352 entry 全覆盖链）
  尾部是 `valid ? T2 : uopNum` 条件尾（非自读保持）——稀疏写口不能表达"无命中
  时按条件写回"，匹配器正确放弃；更大头的 TAGE usefulCtrs(4097 写)/
  intFreeList(1249)/fpFreeList(1247)/RAT difftest_table/busPMU latencyRecord/
  dcache 各 bank 组里**混有 kRegisterWritePort 整体写**（复位/批量更新），v1 对
  混合组整组保守放弃（stage-08 候选：剥离整体写、只折叠译码子集）；enqOH 位选
  条件与 OR-of-ANDs 同列待办。折叠收益集中在 LoadQueueReplay(141)/
  LoadQueueRAR(129)/TLBFA(30×2)/RenameBuffer(10)/L2TLB(2) 等。
- 端到端时间（本轮实测）：GRH 段 ~21min（xmr 110s / fold 7.2s / flatten 68s /
  CLE 672s / simplify 368s），lower+CPU+emit ~15min，model clang（1342 TU,
  -O3 -fno-strict-aliasing + PCH）主体 ~7min 编完，**尾部 2-3 个宽值密集 TU
  （_BitInt(16896) ×900 级，调度器 ComputeHeight + KnownBits::shl 热点）各卡
  ~20-35min**——尾部 TU 是 stage-08 emit 形态（按 store/宽 op 密度拆函数）的
  头号对象。

### 门禁与验收

## 1. 目标

1. 建立 `firtool --preserve-aggregate` 的 XiangShan SV 生成链路，wolvrix 全流程
   （ingest → GRH passes → GrhSIM → CPU emit）直接消费，正确仿真。
2. reg-to-mem 从默认管线**完全退役**（不是默认关闭，是移除），仿真仍然正确。
3. 全部门禁恢复并清零历史豁免；性能不低于现行基线的约定阈值。

## 2. 现状事实

- XiangShan SV 生成：根 Makefile `xs_rtl`（Makefile:1334）→ `testcase/xiangshan/Makefile`，
  firtool 选项固定在 :79（`--firtool-opt "-O=release --disable-annotation-unknown
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,
  locationInfoStyle=none"`），**未开 preserve-aggregate**；`FIRTOOL=` 可指定二进制（:86）。
- `--preserve-aggregate` 在 circt firtool 存在（取值 none/1d/all）；已知限制：含 Clock
  字段的 struct 会报错（circt issue #8931）。XiangShan 当前 firtool 版本对
  `all` 档的兼容性**未实证**——这是本阶段第一个要回答的问题。
- 现有手写最小复现：`testcase/xs-bugcase/CASE_021`（Tage t2_setIdx preserve-aggregate
  形态）、`CASE_022`（indexed write）、`CASE_009`——可作为早期冒烟输入。
- `testcase/xs-components/Makefile:274-279` 已有 mill + firtool 的合成隔离用例流程
  （`DynArrayWrite.scala`、`CamMatchSynthLarge.scala` 等正是数组/聚合形态）。
- reg-to-mem 在 `CPU_SEMANTIC_PIPELINE`（`scripts/wolvrix_xs_grhsim_ir.py:170-185`）中，
  位于 canonicalize-compute 之后；它是现行性能的承重墙（关闭 +41%，
  `pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`）——但那是
  "前端标量化"前提下的结论；数组保留后该前提消失，需重新测量。
- 验收门禁（继承 perf-optimization/README）：test_wolvrix、HDLBits IR 162、xs-bugcase 25、
  黄金 trace 161、XS CoreMark difftest（instrCnt=663,688 / cycleCnt=297,291）。

## 3. 执行计划

### 3.1 子阶段 7a — firtool 链路实证（纯调查，不改 wolvrix）

**已完成首轮（2026-10-08），结论与形态清单见
[20261008-preserve-aggregate-probe.md](20261008-preserve-aggregate-probe.md)。要点：**

1. ~~确认 `--preserve-aggregate` 支持矩阵~~ → 取值为 `none|1d-vec|vec|all`
   （firtool 1.135.0/1.144.0 一致；注意是 `1d-vec` 不是 `1d`）。
2. ~~XiangShan 全量 `all` 档可行性~~ → **一次通过**，未触发 Clock-struct（#8931）类错误；
   设计逻辑 100% packed 聚合 + unpacked Memory + 仿真 _RANDOM，无 unpacked 数组。
3. 形态清单（ingest 必须承接的全集）与对 stage-01/stage-04 的回灌结论：见探针报告
   §3/§4（packed 维全量进 shape、部分索引返回子数组、结构体字段路径等；
   注意报告 §4.1 的"分流"解释已被 §6 补充取代，以 stage-01/04 当前文本为准）。
4. ~~待补：mill 全链路（MFC_ARGS 注入）复核；xs-components 合成用例变体；
   `=vec` 中间档的收益评估~~ → 2026-10-10 全部关闭：mill 全链路正式落地为
   根 Makefile `xs_rtl_aggregate`（`PRESERVE_AGGREGATE=all` 变量化注入，
   375s 产出 2148 个 split 文件，与探针产物形态一致）；`=vec` 不采纳——
   `all` 档一次通过且保留 struct，`vec` 仅小约 43% 但丢 struct 无收益；
   xs-components 变体以 rob.mk 去除 reg-to-mem 参数后的冒烟运行代替。

### 3.2 子阶段 7b — Makefile 与管线接入

- `testcase/xiangshan/Makefile`：`--firtool-opt` 增加 preserve-aggregate 选项
  （建议做成变量如 `PRESERVE_AGGREGATE=all`，默认关，避免冲击现有 `xs_rtl` 用户）。
- 根 Makefile 新增目标族（遵循"一切走 Makefile"约束，先在 Makefile 加 target 再使用）：
  - `xs_rtl_aggregate`：生成 preserve-aggregate 版 SimTop.sv（独立 BUILD_DIR）。
  - `xs_wolf_grhsim_ir_aggregate(+_build_emu/_emu)`：复用 `scripts/wolvrix_xs_grhsim_ir.py`，
    通过参数切换 RTL 来源与管线。
- 管线变化（`scripts/wolvrix_xs_grhsim_ir.py`）：
  - `CPU_SEMANTIC_PIPELINE` 中 **移除 reg-to-mem**（aggregate 模式）。
  - ~~评估 comb-lane-pack 在 aggregate 模式下是否直接移除~~ **已定移除
    （2026-10-08）**：comb-lane-pack 退役（当前测试结果确认，见 stage-05 §8 Q1），
    代码删除执行于 stage-02；本阶段仅确认管线无残留注册点。
  - GRH 段管线（xmr-resolve → … → comb-loop-elim → simplify）不变，但 stage-05 的
    片段化默认开启。

### 3.3 子阶段 7c — reg-to-mem 退役

退役分三步，每步可独立验证：

1. **默认关**：aggregate 管线不含 reg-to-mem；legacy 管线保留（对照组）。
2. **移除出全部默认管线**：legacy 输入（标量化 SV）不再支持 XS 规模仿真——
   文档明确"legacy 链路降级为 HDLBits/小用例维护模式"。
3. **代码移除**：删除 `lib/grhsim/pass/reg_to_mem.cpp`、注册点、文档
   `docs/grhsim_ir/passes/reg-to-mem.md` 转为历史记录（划线保留结论，按
   perf-optimization 惯例"被推翻的结论划线不删"）；`benchmark_grhsim_reg_to_mem.py`
   等配套脚本归档或删除。

注意保留 reg-to-mem 文档中的**负结果知识**（为什么标量化前端必须配 reg-to-mem），
防止未来有人重造轮子。

### 3.4 子阶段 7d — 验收

- 正确性（全绿才算完成，不接受豁免）：
  - `make test_wolvrix`
  - `make run_all_hdlbits_grhsim_ir_tests`（162/162）
  - `make run_xs_bugcase_grhsim`（25/25；CASE_009/021/022 在 aggregate 链路上的表现
    单独核对）
  - `make check_sim_refactor_baseline`：trace 基线**重钉**（数组形态改变 op 序列是预期
    行为，逐条核对后 `capture_sim_refactor_baseline` 重新捕获，提交说明引用本计划）
  - XS CoreMark difftest：aggregate RTL + 无 reg-to-mem 管线，轨迹钉死
    instrCnt=663,688 / cycleCnt=297,291（与现行基线相同数值才算"正确仿真"）
- 性能：`make benchmark_grhsim_ir` A/B（旧链路 vs aggregate 链路）。
  目标：不劣于现行基线的 105%（容许 5% 内波动）；若显著更优，更新基线文档。
- 编译时间：记录 emit C++ 的 clang 编译时长（参照 bitint 经验的 30min 闸意识），
  数组保留预期减少 P_general 体积，若编译时间恶化需归因（发射形状问题回 stage-06）。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `testcase/xiangshan/Makefile` | preserve-aggregate 选项变量化 |
| 根 `Makefile` | `xs_rtl_aggregate`、`xs_wolf_grhsim_ir_aggregate*` 目标族 |
| `scripts/wolvrix_xs_grhsim_ir.py` | aggregate 模式参数；CPU_SEMANTIC_PIPELINE 去 reg-to-mem |
| `wolvrix/lib/grhsim/pass/reg_to_mem.cpp` 等 | 7c-3 移除 |
| `wolvrix/docs/grhsim_ir/passes/reg-to-mem.md` | 转历史记录 |
| `pdocs/perf-optimization/README.md` | 门禁清单更新（aggregate 口径） |

## 5. 风险与缓解（本阶段特有）

| 风险 | 缓解 |
|------|------|
| firtool `all` 档对 XiangShan 不可用 | 7a 先实证；`1d` 档过渡方案；必要时给 circt 提 issue/绕行（struct 字段重排） |
| difftest 数值不一致且难以归因 | 保留 legacy 链路作为对照；按模块二分（`scripts/grhsim_gsim_module_compare.py` 可复用） |
| 性能回退超阈值 | 归因顺序：P_general 体积（数组 op 是否被逐元素展开）→ P_mem 激活率 → 变化检测次数；参照 perf-optimization 既有测量工具链 |
| reg-to-mem 移除后才发现某些 legacy 输入依赖它 | 7c-2 的文档声明 + 移除前全仓 grep 确认无默认管线残留 |

## 6. 完成定义（DoD）

- aggregate XiangShan 链路从 `make xs_rtl_aggregate` 到 difftest 全绿，无 reg-to-mem。
- 本目录各阶段文档的"开放问题"全部有结论（采纳/否决+理由）。
- `wolvrix/docs/` 规范文档与实现一致（grh-ir.md、grh-json-spec.md、grhsim_ir/*）。
- 豁免清单清零；perf-optimization README 门禁更新完毕。
