# 20261005 变化检测比较次数普查（grhsim IR vs gsim，XS CoreMark 100k）

> 测量记录，非优化项；为 P_general 优化方向提供定量依据。模板中"基线/方案/结果"
> 三节合并为"方法与数据"。

## 元信息

- 日期：2026-10-05 / 作者：kimi
- wolvrix commit：`66000f6` + 未提交工作树（同 `20261005-002919-pmem-act-cluster-dead-compare.md`）
- 上游记录：`20261005-002919-pmem-act-cluster-dead-compare.md`（178.9s 版模型，即本次测量对象）

## 测量对象与口径

- 设计：完整 XiangShan（SimTop）；负载：CoreMark 2 iterations，100k 周期上限，
  终点 instrCnt=240,349 / cycleCnt=99,996 / pc=0x80000c0c（与标准口径一致）。
- 统计目标：**变化检测（change detection）比较的执行次数**——判定"值是否变化"
  的比较，不含设计逻辑自身的比较运算（如 OP_EQ）。按区域细分：
  - grhsim IR：非 sink 超节点 publish compare-store（`boundaryValueStore.x != cpu_v`）
    与 sink 写体比较 A（`regLatchStoreNext.x != cpu_merged`）/ 比较 B
    （`regLatchStore.x != cpu_merged`，驱动 state 读者激活）。
    注：这里的 "publish" 指发射器 `publishBoundary`/`publishDpiResult` 的边界值
    发布（在 **P_general** 超节点体内执行），与六阶段的 **P_publish** 阶段无关——
    后者是每轮提交：激活位图 OR 合并 + regLatchStoreNext→regLatchStore 的
    529KB 整体 memcpy（`grhsim_SimTop_tu0.cpp:1341`），无逐值比较。
  - gsim：`cond_` 激活比较（新值 vs `$old$` 影子，分"寄存器更新块内"与
    "组合块内"）与 `if (x != y)` compare-store（输入引脚等）。

## 方法

- **grhsim IR**：静态解析全部 1,082 个生成 TU，按超节点序号统计比较站点
  （publish 669,506 站 / sink A 99,992 站 / sink B 99,992 站，sink/非 sink 边界 =
  序号 34286，由生成代码调用点门控形式核实）；再对 4 个 pGeneral 扫描 TU
  （tu35–tu38）的全部 34,741 个超节点调用点插桩计数点火次数
  （`++g_fire[ord]`，定义与退出转储在 tu0），其余 TU 硬链接复用未重编。
  比较次数 = Σ 点火数 × 站点数。插桩模型与运行：`ptmp/grhsim-cmpcount/`
  （model/、build/emu/fire_counts.txt、compare_sites.tsv、census_and_instrument.py）。
- **gsim**：直接对 `build/xs/gsim` 生成模型（329 TU）的全部比较行插桩计数
  （`++g_gsimCmp*`），按所在超节点块是否含 `$NEXT` 状态拷贝区分寄存器更新块与
  组合块；`ptmp/grhsim-cmpcount/`（gsim-build/、instrument_gsim.py）。
  插桩计数的是**执行次数**，无需点火数换算。

## 数据：grhsim IR（精确）

100k 周期运行（99,996 guest cycles，Host 178.0s，插桩开销可忽略）：

| 区域 | 比较次数 | 占比 | 每周期 |
|---|---|---|---|
| 非 sink publish compare-store | **22,794,874,449** | 70.1% | ~227,950 |
| sink 写体比较 A | **9,741,051,924** | 29.9% | ~97,415 |
| 合计 | **32,535,926,373** | 100% | ~325,365 |

- 点火：非 sink 合计 1,047,714,464 次（34,286 个全部点过），sink 合计
  12,787,743 次（424/455 个点过）；sn_34287 与 sn_34290 各 100,051 次
  （每时钟沿一次）；escape（sn_34286）301,155 次 ⇒ **每周期 ~3.01 轮 eval**
  （此前"每 eval 轮数"一直待实测，此处顺带钉死）。
- sink 比较 B 的执行次数 = 比较 A 为真的次数（上界 = A 的 9.74e9）；单写者
  状态下 A-true == B-true == 可见状态变化，故 B ≈ 实际寄存器更新量。
- 与耗时对照：非 sink 比较占 70.1% 次数 / 76.3% P_general 耗时（单次 ~1.09）；
  sink 29.9% 次数 / 19.0% 耗时（单次 ~0.64）——sink 比较是 regLatchStoreNext
  上的紧凑顺序访问 + 完美预测分支，单次更便宜。
  （耗时占比来源：`ptmp/grhsim-ir-phase-perf-20261004/sn_category_report_20261005.txt`，
  perf-20261005.data 按序号边界归因。）

## 数据：gsim（精确）

100k 周期运行（99,998 guest cycles，Host 48.2s；终点 instrCnt=238,550 /
pc=0x80000b40，与 grhsim 侧略有行为差异——两模拟器轨迹本就不逐拍一致，
周期上限同为 100k）。插桩直接计数比较执行次数：

| 区域 | 静态站点 | 比较次数 | 占比 | 每周期 |
|---|---|---|---|---|
| cond_ 寄存器更新块内（`$NEXT` 拷贝块） | 395,577 | **5,228,322,650** | 77.3% | ~52,286 |
| cond_ 组合块内 | 50,365 | **963,170,599** | 14.2% | ~9,632 |
| if (x != y) compare-store（输入引脚等） | 26,660 | **575,700,689** | 8.5% | ~5,757 |
| 合计 | 472,602 | **6,767,193,938** | 100% | **~67,675** |

注：cond_ 比较有两种形式——`!=`（208,505 站）与 `^`（1-bit 异或变化检测，
237,437 站），已全数计入。

## 两侧对比（同负载 100k 周期）

| 区域 | gsim | grhsim IR | 倍数 |
|---|---|---|---|
| 寄存器/锁存写变化检测 | 5.23e9（~52,286/周期） | 9.74e9 sink 比较 A（~97,415/周期） | **1.86×** |
| 组合/边界激活检测 | 1.54e9（comb+ifcmp，~15,389/周期） | 22.79e9 publish（~227,950/周期） | **14.8×** |
| **合计** | **6.77e9（~67,675/周期）** | **32.54e9（~325,365/周期）** | **4.81×** |

- **寄存器侧 1.86×**：grhsim 的 sink 事件毯（每沿 88.5k 写整体点火、逐写
  比较）对 gsim 的纯数据驱动更新块（不变不点火）——这是复杂时钟语义的
  结构性代价，倍数与"每沿全量 vs 按变化点火"的直觉一致。
- **组合侧 14.8×**：差异远大于静态站点比（669,506 vs 446k ≈ 1.5×）。主因：
  ① grhsim 在**每个超节点边界发布点**都做 compare-store（边界值 = 跨超节点
  通信的全部值），gsim 只在**有激活 fanout 的节点**上比较；② grhsim 非 sink
  超节点更小（~32 op），边界/体积比更高，同一数据流被切成更多次发布；
  ③ gsim 超节点大，大量节点间变化在超节点内部消化，不出现在激活检测里。
- 净结论：grhsim IR 的变化检测总量约为 gsim 的 **4.8 倍**；其中组合侧是
  绝对大头（22.8e9 / 32.5e9 = 70%）。publish compare-store 的站点合并
  （死 compare 删除已去掉 23.3%）与发布路径降本仍有结构性空间。

## 口径与局限

- grhsim 侧计数不含：pInput 输入 publish（~0%）、P_mem 写口 cell 比较与
  memEnableBits 位测试（P_mem 区域，~3% 耗时）、P_publish 的 529KB memcpy
  （整体拷贝无逐值比较）、P_event 边沿检测 prev 比较（~420 站点 × 每轮，量级
  ~1e8，可忽略）、扫描循环的位图字测试（派发而非值比较）。
- gsim 侧计数不含：激活位图的 OR 写（无比较）、`$old$` 影子更新（拷贝非比较）。
- 宽值比较按站点计 1 次，不按机器字展开；两侧一致。
- 两侧模型均为 -O3；插桩对运行时长的影响：grhsim 侧 +0%（178.0s vs 178.9s 均值，
  仅扫描 TU 插桩）；gsim 侧每个比较行一个全局自增，Host 48.2s 为含插桩值
  （计数精确，时间仅作参考）。

## 后续

- grhsim 的 228 亿次非 sink publish 比较单次成本更高（散布 boundary 读写 +
  激活位图写），是与耗时占比匹配的大头；对 gsim 的 14.8× 差距说明边界发布
  模型本身（每边界一 compare-store）是最大的结构性成本项，而非 sink 事件毯。
- 优化方向（按优先级，2026-10-05 评审，数据依据见上文）：
  1. **点火剖面驱动的边界消减（PGO-BR，主攻 14.8× 差距）**：边界多的根源
     不是 128 帽（平均 32 op/超节点，帽未起作用），而是 `segmentGeneral`
     的均匀权重代价（`cpu_partition.cpp:374`："distinct incoming activation
     values + one per segment"）——冷热边界同价，热边界被切成 compare-store。
     方案：① DP 代价改率加权 `Σ rate(producer) + λ`（rate 取
     `ptmp/grhsim-cmpcount` 的逐超节点点火剖面），热边界并入段内、冷边界
     保留切割；② coarsen 的 out1/in1 对点火率差 ≤ 阈值（如 2×）的单消费者
     链解除尺寸限制（gsim 式链吸收，但按率判据而非无脑放大）；③ compare-
     true 率插桩精化后闭环迭代。语义保守（点火只变大），零正确性风险；
     唯一风险是 CoreMark 剖面过拟合，用 gain 裕度过滤候选。
  2. **轮数 3.01 削减**：每轮固定成本 = 扫描 543 字（4.7%）+ 529KB commit
     memcpy（3%）+ P_mem 守卫（~3%）。先分解 3 轮构成（时钟沿轮/沉降轮），
     沉降轮若可合并，固定成本立省约 1/3。
  3. **NBA commit 稀疏化**：sink 写 A-true 时置脏字位图（529KB ≈ 130 个
     u64 位图字），commit 先扫位图、全零跳过、否则只拷脏行；现每轮 529KB
     × 30.1 万轮 ≈ 159GB 流量。预期 ~2%，低风险。
  4. **发布 compare 聚合**：同一次点火内发往同一 target 超节点的多个 publish
     合并为 XOR-OR 归约 + 一次位图写，消散布激活写。预期 1-3%。
  5. **明确不做**（数据支持）：sink 侧守卫再尝试（A1 已否；sink compare
     单次 0.64、仅占 30% 次数 / 19% 耗时，大头在簇本体工作）；单点死
     compare 删除（23.3% 已做）。ThinLTO/小超节点内联降级为超节点放大
     的后续（放大后调用次数自然下降）。
- 测量基建已就位（`ptmp/grhsim-cmpcount/`：静态站点普查 + 点火插桩流程），
  后续候选可用"次数 + 时间"双指标廉价评估。
