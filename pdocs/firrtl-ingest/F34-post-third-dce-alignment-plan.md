# F34 第三次 DCE 后至第四次 DCE 的功能与性能对齐

2026-11-18 建立。F34.0–F34.4 已核验，实施记录见第 7 节；AliasAnalysis 回退重构与差异溯源规划见第 8 节。

## 1. 窗口与起点

| 快照 | GRH 生产调用 | GSIM 生产调用与原生计时身份 |
| --- | --- | --- |
| R0 | 第三次 `dead-code-elim#2` 返回，提供输入 | `RemoveDeadNodes2` 返回，原生 `RemoveDeadNodes#1` |
| R1 | `alias-analysis#0` | `AliasAnalysis#0` |
| R2 | `pattern-detect#0` | `PatternDetect#0` |
| R3 | `common-expr#0`，FIRRTL 入口拼写为 `comm-expr` | `CommonExpr#0` |
| R4 | 第四次 `dead-code-elim#3` | 第四次 DCE，原生 `RemoveDeadNodes#2` |

窗口从 R0 后、AliasAnalysis 调用前开始，到第四次 DCE 返回结束。GRH 按生产流程
使用 `keep_declared_symbols=False`，第三次 DCE 保留 FIRRTL canonical pipeline
的 `drop_disabled_firrtl_assertions=True`，第四次保持该选项的默认值。GRH 停在
普通未分区图，后继是 `grhsim-dialect-translate`。GSIM 在 `graphPartition` 前停止。
分图、发射、仿真及其性能另属后续阶段。
[FIRRTL 入口](../../scripts/wolvrix_xs_grhsim.py#L88) · [GRH 共用流程](../../scripts/grhsim_flow.py#L265) · [GSIM 主入口](../../reference/gsim/src/main.cpp#L800)

起点为主仓库 `fbeeeb57bb4a05831d474af8c381946777d3d77d`、
Wolvrix `690a394ce00baf5b5666a617525259c4183d4050`、
GSIM `052ef2d9937b175de8cc19a20a8af80a0498e57a`。沿用原始
`build/xs/rtl/rtl/SimTop.fir` 和 F26 `ingest-request.json`，在启动时校验输入、
源清单、双方冻结包、依赖和构建配置。两端按 FIRRTL 生产二值语义运行，
未显式启用二值改写的普通 API 保持既有语义。

R0 由本轮冻结候选实际运行生产前缀得到。F33 的 Q2 库存用于核对起点：
GRH 有 4,616,189 个 Node，其中 4,596,538 个有 GSIM 唯一同名候选（99.5743%）。
GSIM 有 5,775,134 个库存 Node，其中 4,877,861 个是执行成员，
897,273 个是内联常量来源。逐项功能归因仍待完成，ConstantAnalysis
正式门差 0.956 秒。这些事项随 R0 记录，F34 可以独立推进。
前缀耗时、失败及继承差异单列。涉及 ingest、前置 pass 或公共 DCE 修改并改变
R0 时，先记录复现和影响，再按已有前驱审核流程处理。F32 的 U1、U2、U4 继续保留，
U3 四态问题单独记录。
[F33 功能与性能记录](F33-constant-analysis-dce-alignment-plan.md#11-f334-首轮全图功能对照) · [F32 前驱事项](F32-post-dce-pass-alignment-plan.md#10-前驱人工审核项)

## 2. 各 pass 的实现与验证

F33 的 PassManager 在修改前拒绝带 SemanticTree 或 `kCombArrayUpdate` 的前三个
窗口 pass。F34 以各 pass 的回归为依据开放。旧 F32、F33 捕获照常在各自边界
停止。完成 R4 后验证 `grhsim-dialect-translate` 仍在图修改前被支持门拒绝。
[支持门与变换计时](../../wolvrix/lib/core/transform.cpp#L50) · [F23 普通 GRH 基础](F23-alias-pattern-common.md)

### 2.1 AliasAnalysis

先支持完全同类型的纯标量 `kAssign` 和全宽静态 slice，例如 8 位
`b = bits(a, 7, 0)` 的普通消费者可改用 `a`。检查别名链、源是输入端口、
同值多个消费者和多个来源 owner，核对结果 binding、源端点及 operand slot。
输出、时钟、状态、memory 和外部效果保持各自的观察与依赖合同。部分 slice、
有重解释的 view、宽度或 shape 不同的值不进入这条规则。GSIM 另外会处理部分
整数组别名和索引引用。先取香山实例，只有 shape、元素坐标和引用语义都能用
已有 helper 证明时才加入单条规则。有序组合数组更新的先后顺序和后写优先保持。
[GRH AliasAnalysis](../../wolvrix/lib/transform/alias_analysis.cpp) · [GSIM AliasAnalysis](../../reference/gsim/src/aliasAnalysis.cpp)

### 2.2 PatternDetect

先迁移现有 `eq(concat(high, low), K)` 规则，保留原结果身份。
例如高位 2 bit、低位 3 bit 时，使用 `K[4:3]` 和 `K[2:0]` 建立两个比较，
输出为两比较结果的按位 AND。核对新增比较、常量的来源和新旧 operand slot。
用高字段最低位为 1 的非对称常量覆盖 GSIM CAT 实现中高字段从
`rwidth + 1` 开始取位的路径，并记录原生规则是否命中。独立位向量预期以原表达式为准。

按香山命中量评估两条简单补齐机会。对于 `bits(dshl(1, s), i, i)`，
在宽度、截断和索引可证明时改成 `s == i`，覆盖越界移位、截断以及仍有其他
消费者的 one-hot。对于 `eq(or(shl(high, n), pad(low)), K)`，验证两段
无重叠，且符号扩展、补位及截断后的实际位图与拼接相同，再复用拼接比较规则。
无实际收益或无法用局部证据判定的形态保持原样。
[GRH PatternDetect](../../wolvrix/lib/transform/pattern_detect.cpp) · [GSIM PatternDetect](../../reference/gsim/src/patternDetect.cpp)

### 2.3 CommonExpr

复用现有精确结构 key，包含类型、位宽、符号、逻辑域、shape、语义属性和
有序 operands。核对候选边界与三条既有共享条件，分别为至少 5 个等价候选、
位宽大于 256 bit，或某一结果有多个不同消费者。分别记录 GSIM 的下游 Node
和 GRH 的 consumer op。测试同一消费者两次使用一个结果、宽度 256/257、
组大小 4/5、深链和共享 DAG。代表选择在同一输入上可重复。

优先在合同允许的 owner 范围内共享纯标量表达式。旧 `mergeCseOperations`
会拒绝跨执行 owner；整图启用前要有对应正负例。跨 owner 共享仅在能给出明确的
代表结果、活跃 owner、anchor、binding 和旧消费者迁移证据时启用。标量 key
也可能递归遇到 `kCombArrayUpdate`。初版按该值的身份比较，待独立验证完整
有序写语义后再评估结构比较。数组状态、memory、effect、外部边界和不能合法替换
的结果保持原样。逐条追踪旧 Node 迁移，规则限于已有结构等价和可证明的局部改写。
[GRH CommonExpr](../../wolvrix/lib/transform/common_expr.cpp) · [owner 检查](../../wolvrix/lib/ingest/node_attributes.cpp#L468) · [GSIM CommonExpr](../../reference/gsim/src/commonExpr.cpp)

### 2.4 第四次 DCE

复用现有显式 DCE，以 R3 图分别验证别名生产者、被替换 pattern 的中间值、
CSE 重复值在最后一个需求消失后的回收，同时保留顶层接口、clock/reset、
memory reader/writer 关联、外部端口、效果根和多结果共享生产者。
验证仍有需求的 Node，及最后一个成员消失时的 Node、binding 和来源回收。
公共 DCE 的修改须有前三轮行为回归。所有 fixture 保留独立值或有界状态预期，
跨端快照用于定位差异。
[GRH DCE](../../wolvrix/lib/transform/dead_code_elim.cpp) · [GSIM DCE](../../reference/gsim/src/deadNodes.cpp)

## 3. 五界全图证据

每端运行 R0–R4，校验扁平 SemanticTree 或 GSIM 原生库存，绑定同一轮的
Node 身份、类型、owner、anchor、来源、端点、连接、消费槽以及 GSIM 执行成员
分类。原地替换须能追踪存活身份。跨 Node 转移须能追踪代表、被替换的值及
可观察端点。GRH 的用法重定向和 GSIM 在 AliasAnalysis、PatternDetect、
CommonExpr 内的即时移除须落到各自的实际边界。

报告 R0–R4 每一界的 GRH 与 GSIM Node **总数**，GSIM 执行成员、内联常量
和其他目录项各自的数量，以及 GRH 有唯一 GSIM 同名候选的分子、分母和比例。
对相邻边界报告新增、退休和净变化。单列 **R3 → R4 的实际删除量和两端 R4
总数**，同时报告 R0 → R4 累计变化。按唯一同名、歧义、单端、候选同名但身份
不符建立台账，用类型、端点、活跃消费者和 retention 证据解释本窗口的变化。
R0 已存在的差异、在窗口传播或消失的差异及新出现的差异均可追溯。功能退出
依赖实际行为证据、图合法性和生命周期核对，名称比率用于报告对应情况。

## 4. 功能期逐 pass 两倍守卫

先给 GSIM 第四次 DCE 增加唯一停止标识，计划用 `RemoveDeadNodes3`，
保留原生 `RemoveDeadNodes#2`，并回归旧 `RemoveDeadNodes` 仍命中第一轮。
GRH 显式绑定第四次逻辑调用 `dead-code-elim#3`，逐次 `run_pass` 的原生
序号可能都是 `#0`。启动前校验四个调用的顺序、输入边界和停止配置，运行后
根据事件核对位于 R4 之后的 pass 调用次数为零。

复用 F33 守卫和采集合同中可共用的部分，锁定同输入、语义、冻结实现与配置的
GSIM 参考。受守卫的配对功能轮使用至少三次有效参考的逐 pass 中位数乘二作为预算。
GSIM 每个样本用新进程，避免 CommonExpr 全局缓存复用。毫秒级小例确有计时抖动时
复用独立新图批次校准，先验证四个逻辑调用、所有成员各走一次，导出在 pass
计时外。粗略诊断可按用户指定采一次，正式组和正式功能守卫基于各自的合同。

守卫在窗口 pass 开始时锁定时限，结束证据不全时继续计时。超过两倍时先记录
最后一个完整边界和失败原因，再终止私有进程组。原生返回后查实超限同样判为失败。
立即定位超时的 pass，核对两端实际工作量。实现热点优先检查重复扫图、逐值重连和
来源索引更新、PatternDetect 新 op 及槽位维护、CSE key/分组成本、DCE retention。
维持规则和可观察行为，修复并重跑专项后再以同一输入边界复测。前缀、导出和总体
资源各有独立守卫，失败样本保留。合同测试先覆盖超时、缺参考、重复 DCE、
错误计时顺序、慢导出、子进程清理和 R4 停止。
[F33 守卫实现](../../scripts/f33_guard.py) · [F33 捕获合同](../../scripts/test_capture_f33_pipeline.py)

## 5. 正式性能验收

冻结通过功能验证的候选。相同原始 FIRRTL、同机、固定 CPU 亲和集合、两端实际线程
设置和构建配置，每端至少 3 个新鲜样本，串行交错。入组核对实际二进制、依赖、
输入指纹和运行配置，记录有效线程设置。正式样本保留生产验证、Node、binding 和
retention 成本，关闭窗口内快照、trace、export、额外 oracle 和 profiler。
前缀单独计时。连续窗口用单调时钟，从 R0 后 AliasAnalysis 调用前记录到
R4 返回，计入 pass 间框架成本。GSIM 原生计时和 GRH 连续区间分别与对应
pass 计时及事件交叉校验。

```text
median(GRH, p) <= median(GSIM, p) + max(3% × median(GSIM, p), 0.010 s)
p ∈ { AliasAnalysis, PatternDetect, CommonExpr, 第四次 DCE, 连续四 pass 窗口 }
```

两端各指标的最大样本偏差均须在 `max(3% × 本侧中位数, 0.010 s)` 内。
功能期两倍预算继续作为外层保护。超时、资源干扰和抖动超限保留原始证据，
更换候选或配置后采集完整新组。逐项发布中位数、比值、门槛和抖动。
正式性能缺口继续定位，或按用户明确接受的实测范围收尾。

## 6. 实施顺序与交付

| 阶段 | 交付与退出条件 |
| --- | --- |
| F34.0 起点与停止点 | 冻结 R0 和输入身份，五界与四个逻辑调用明确，小例验证停在第四次 DCE，列出继承差异 |
| F34.1 参考与守卫 | 四个 GSIM pass 参考和两倍预算可追溯，守卫及失败保留合同通过 |
| F34.2 AliasAnalysis | 现有安全规则接通新 Node 与新 op，独立值、边界与来源回归通过 |
| F34.3 PatternDetect | 拼接比较规则接通新 Node，记录 GSIM 取位差异，按实测评估简单规则 |
| F34.4 CommonExpr | 精确等价及候选范围验证，代表和 owner 迁移合同通过 |
| F34.5 第四次 DCE 与香山全图 | 四个 pass 在功能两倍门内，R0–R4 全量库存、删除量、对应率与逐界台账完成，本轮功能差异有证据 |
| F34.6 正式性能 | 冻结候选的交错样本与五项独立判定，报告每项尚存缺口 |
| F34.7 收尾 | 记录源码与二进制身份、支持矩阵、功能与性能状态及证据目录 |

建设对应的现有或新增 Make 入口，覆盖小例、捕获、比较和正式 benchmark。
build、test、install 及 Python 工作流都经 Make 执行。运行记录与失败证据放在
`ptmp/firrtl-ingest/F34/`。实现后在
[GRH 变换文档](../../wolvrix/docs/transform/grhsim-transforms.md)同步支持矩阵与入口，
本计划记录进展和验收结果。

## 7. F34.0–F34.4 实施记录

- **F34.0**。GRH 从香山原始 FIRRTL 和 F26 manifest 执行生产前缀到 R0，SemanticTree
  校验通过，共 4,616,189 个 Node。GSIM 支持独立的 R0 采集和 R0–R4 采集。
  小图确认 `RemoveDeadNodes3` 的原生计时为 `RemoveDeadNodes#2`，旧停止标识仍命中
  对应轮次。GRH 两张独立小图均核对四个逻辑调用，R4 后的 dialect translation
  被支持门拒绝，拒绝前后的序列化图一致。继承差异见第 1 节。
- **F34.1**。GSIM 参考共同绑定原生计时、窗口事件、资源守卫结果和冻结身份。
  功能期限取三个有效样本的逐 pass 中位数乘二，同时记录相对正式性能容差的样本偏差。
  回归覆盖缺参考、重复 DCE、计时乱序、慢导出、超限、进程组清理和 R4 停止。
  香山补采使用互斥锁、120 GiB 进程树 RSS 采样阈值及持续内存压力监控。
- **F34.2**。同类型标量赋值和全宽静态 slice 接通 SemanticTree 及有序数组更新图。
  回归覆盖输入端口、别名链、多结果生产者的精确 anchor、消费槽、状态、时钟、
  DPI 及数组的后写优先。香山 R0 的锚点库存有 25,848 个带 shape 的 `kAssign`。
  当前快照缺少核对源 shape 和消费坐标的证据，保留聚合赋值。
- **F34.3**。拼接比较保留旧结果身份和 binding，把高低字段来源挂到各自生成的
  比较槽。非对称 CAT 小例枚举全部 32 组输入，原式和 GRH 只在 `(1, 5)` 成立，
  GSIM 原生规则只在 `(0, 5)` 成立。香山 GSIM 记录 3,646 个 one-hot 和 168 个
  CAT/OR 合计。FIRRTL 二值入口启用带范围和低位截断检查的 one-hot 改写。
  原始 FIRRTL 扫描检出零条直接 shift-or 比较链，保留该形态。
- **F34.4**。保留精确结构及三条共享阈值。组内首个候选作为代表，回归核对
  operation membership、anchor、binding、消费槽及第四次 DCE 后的存活身份。
  分区 owner 负例在图修改前拒绝。数组更新按值身份入 key，同一更新的重复读取
  可共享，并以独立数组预期验证结果。

Make 入口为 `f34_gsim_build`、`snapshot_f34_package`、`capture_f34_pipeline`、
`test_f34_passes`、`test_f34_gsim_stop` 和 `test_f34_contract`。原生 Python 批次
与生产调用顺序分别由 `test_f33_native_batch`、`test_f33_flow_contract` 核对。
采集用 `F34_MODE=baseline|reference|capture`，GRH 候选配对通过 `F34_PACKAGE`
和 `F34_ARGS=--reference=...` 传入冻结包及参考。

### 7.1 香山 R0

| GRH Node | GRH 唯一同名候选 | GSIM Node 总数 | GSIM 执行成员 | GSIM 内联常量来源 | GSIM 其他目录项 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4,616,189 | 4,596,538（99.5743%） | 5,775,134 | 4,877,861 | 897,273 | 0 |

冻结的 GRH 候选从原始 FIRRTL 运行到 R0 后，四张快照表的数据与 F33
基线一致。GSIM 的 F34 R0 与 F33 Q2 名称库存一致。`SplitNodes` 按指针顺序
分配新 Node，跨进程比较时有 2,990 个存活切片的原生 ID 重排。按名称映射后
Node 详情、执行成员分类和 7,855,917 条连接一致，31,170 条切片记录的来源
和位区间一致。证据位于 `ptmp/firrtl-ingest/F34/` 下的
`r0-grh-candidate-v1/`、`r0-gsim-v2/` 和 `r0-compare/summary.json`。
[GSIM 切片分配](../../reference/gsim/src/splitNodes.cpp#L794)

### 7.2 香山功能守卫预算

| Pass | GSIM 三次中位数（秒） | 两倍上限（秒） | 最大样本偏差（秒） |
| --- | ---: | ---: | ---: |
| AliasAnalysis | 22.116 | 44.231 | 1.248 |
| PatternDetect | 18.914 | 37.829 | 1.220 |
| CommonExpr | 89.243 | 178.486 | 2.527 |
| 第四次 DCE | 28.711 | 57.423 | 0.742 |

预算文件为 `ptmp/firrtl-ingest/F34/reference-candidate-v1/reference.json`，
已绑定冻结 GRH 候选。AliasAnalysis 和 PatternDetect 超出正式采样的偏差容差。
首份参考与早期 GRH 基线存在运行重叠，后续全图采集串行执行。串行 R0 的
进程树峰值 RSS 为 GRH 76.0 GiB、GSIM 106.9 GiB，均未触发资源守卫。
F34.5 的香山全图逐 pass 预算和库存对照见下节。

### 7.3 初始候选的香山 R0–R4 库存对照

| 边界 | GRH Node 总数 | GSIM Node 总数 | GSIM 执行成员 | GRH 唯一同名候选 |
| --- | ---: | ---: | ---: | ---: |
| R0 第三次 DCE 后 | 4,616,189 | 5,775,134 | 4,877,861 | 4,596,538（99.5743%） |
| R1 AliasAnalysis 后 | 4,616,189 | 4,035,180 | 3,137,907 | 3,125,777（67.7134%） |
| R2 PatternDetect 后 | 4,616,189 | 4,031,534 | 3,134,261 | 3,122,181（67.6355%） |
| R3 CommonExpr 后 | 4,616,189 | 3,631,588 | 2,734,315 | 2,731,493（59.1720%） |
| R4 第四次 DCE 后 | 4,557,148 | 3,608,026 | 2,710,753 | 2,696,683（59.1748%） |

GSIM 每界另有 897,273 个内联常量来源，其他目录项为 0。R4 同名候选中，
2,640,856 个对应 GSIM 执行成员，55,827 个对应内联常量来源。两端五界均无
重复名称或无名 Node。

按同一运行的原生 ID 核对，第四次 DCE 删除 GRH 59,041 个、GSIM 23,562 个
Node，两端均新增 0 个。R0 至 R4 累计删除 GRH 59,041 个、GSIM 2,167,108 个，
其中 GSIM AliasAnalysis 删除 1,739,954 个，PatternDetect 删除 3,646 个，
CommonExpr 删除 399,946 个。名称候选的最大降幅出现在 AliasAnalysis。
GRH 保留的名称仍需按其当前 anchor、binding 和消费者核对实际计算。

两端采集串行完成并停在 R4，进程树峰值 RSS 分别为 85.17 GiB 和 107.17 GiB，
进程 swap 采样值为 0。GRH 四个 pass 在功能预算内。采集摘要在
`ptmp/firrtl-ingest/F34/r4-capture-grh-v1/` 和
`ptmp/firrtl-ingest/F34/r4-capture-gsim-v2/`，比较结果在
`ptmp/firrtl-ingest/F34/r4-assessment/summary.json`。GRH 的连接和端点表以
`.tsv.zst` 保存，解压内容已按采集摘要的 SHA-256 校验。逐项功能差异和
代表迁移台账仍待核验。

### 7.4 AliasAnalysis 恒等链退休

UsedBits 收窄后，香山 `_timer_c_T_1` 的全宽切片与外层赋值形成恒等链。
逐 op 判断时，先删除的内部 op 会把 owner 迁到上游，使后续仍保留转发 Node。
AliasAnalysis 现在在改图前解析整条恒等链，按原图核对 Node 的 anchor、成员、
binding 和边界引用。沿显式命名引用迁移下游消费者，保留消费槽和端口身份。
香山复测中，`_timer_c_T_1` 退休，寄存器写入端引用执行加法的 `_timer_c_T`。

| 边界 | GRH Node | GSIM Node | GRH 唯一同名候选 |
| --- | ---: | ---: | ---: |
| R0 | 4,616,189 | 5,775,134 | 4,596,538（99.5743%） |
| R1 | 3,685,241 | 4,035,180 | 3,114,480（84.5122%） |
| R2 | 3,685,241 | 4,031,534 | 3,110,884（84.4147%） |
| R3 | 3,685,241 | 3,631,588 | 2,721,739（73.8551%） |
| R4 | 3,647,084 | 3,608,026 | 2,674,504（73.3327%） |

R0 与前版一致。R1 退休 930,948 个 GRH Node，比 `alias-op-only-capture-v2`
多退休 590,474 个。唯一同名候选率从 73.0388% 升至 84.5122%，候选数减少
8,452 个。R1 依赖连接未解析数从前版的 1,049,169 降至 309,650，R0 为
120,313。第四次 DCE 回收 38,157 个 GRH Node，全窗口累计回收 969,105 个。

R0 同名且在 R1 双方均退休的 Node 有 915,205 个。GRH 单边退休 11,297 个，
GSIM 单边退休 555,556 个。后者中 453,350 个 GRH Node 已绑定到新的值端点，
99,599 个仍使用原端点，2,607 个在 R0 缺少唯一值端点。仍使用原端点的形态
以标量寄存器读（47,636）、数组赋值（21,030）和数组寄存器读（11,687）为主。
统计见 `ptmp/firrtl-ingest/F34/alias-chain-source-tests/retirement-explanation.json`。

五个边界均通过 SemanticTree 校验。四个 pass 分别用时 14.226、0.709、55.335、
15.632 秒，均在功能守卫预算内。C++ 变换回归 5/5，采集合同和 GSIM 停止回归
11/11。证据位于 `ptmp/firrtl-ingest/F34/alias-chain-source-capture/summary.json`
和 `ptmp/firrtl-ingest/F34/alias-chain-source-tests/comparison.json`。剩余名称和
连接差异的逐项归因、正式性能采样待完成。

### 7.5 AliasAnalysis 第四轮剩余归因

第四轮复用三个冻结的 GSIM 样本，只导出 GRH 的 R0/R1；worker 仍运行全部四个
pass，并在 R4 检查 SemanticTree。R4 校验 1 个图、0 个错误，资源守卫未报告干扰。
AliasAnalysis 用时 15.397 秒。C++ 变换回归 5/5、采集合同 7/7。

| 边界 | GRH Node | GSIM Node | 唯一同名候选 | GRH 唯一同名候选率 |
| --- | ---: | ---: | ---: | ---: |
| R0 | 4,616,189 | 5,775,134 | 4,596,538 | 99.5743% |
| R1 | 3,254,033 | 4,035,180 | 3,112,465 | 95.6495% |

原始 555,556 个 GSIM-R1 独有名称中，426,502 个已在候选 R1 退休，129,054 个仍存活。
新增 GRH 独有名称为 0。另有 2,015 个原来匹配的名称在候选 R1 不再存活，其中
777 个归为 inline constant source，1,238 个为 active computation。候选相对第二轮的
同名率上升 2.4885 个百分点，但同名候选数减少 1,001 个。结果位于
`ptmp/firrtl-ingest/F34/alias-iteration4/cohort.json` 和
`ptmp/firrtl-ingest/F34/alias-iteration4/comparison.json`。

剩余 129,054 个名称中，22,244 个在 AliasAnalysis 前后转发到 GRH 上与 GSIM 活跃源
相同的值。抽样发现这些 Node 仍拥有真实运算，包括 `kConcat` 和共享
`kSliceStatic`。另有 7,640 个值端点前后不变且与 GSIM 源同值，其中 7,281 个锚定共享
`kMux`。因此相同端点不能单独证明名称冗余。

55,573 个转发后值不同的样本中，49,185 个结构上有单入单出赋值端点，但抽样涉及
`[1]` 数组形状。`kSliceArray` 的坐标、剩余形状和边界消费仍需要逐类验证，不能按标量
身份转发处理。索引寄存器读取也保留独立名称，其读取和值锚点不能仅凭常量索引移给
存储 Node。分类证据见 `ptmp/firrtl-ingest/F34/alias-iteration4/remaining-peers.json`、
`analysis-forwarded-distinct.md` 和 `analysis-forwarded-same.md`。

第四轮没有放宽数组形状检查或运算成员检查。C++ 夹具覆盖常量索引读取、普通赋值别名
退休及动态、越界、未知索引保留；完整采集通过 R4 校验。下一轮从 `[1]` 投影和 GSIM
源缺少 GRH-R0 对端的类别继续取证，保持新增多留名称为零的比较条件。

### 7.6 寄存器读取选择边界别名

第五轮复测前，针对 3,172 个共享标量 `kRegisterReadPort` 值的名称归属作了抽查。例子中
GSIM 的别名 Node 只表示寄存器读取结果，GRH 则把读取操作和身份 `assign` 都放在一个
Node 下，并用绑定到读取操作、无操作数槽位的 `data` 边表示存储来源。AliasAnalysis
现在仅当该边的值就是读取结果、读取上下文与结果定义操作相同、寄存器声明恰有一个
所有者，且该 Node 的其他成员均属于同一身份链时，才把它作为候选。

夹具验证了带此选择边的别名可退休，同时读取操作仍留在存储 Node、下游消费者槽位保留，
Oracle 输出不变。普通标量读取、共享读取别名和静态数组读取边界回归均通过。

| 边界 | GRH Node | GSIM Node | 唯一同名候选 | GRH 唯一同名候选率 |
| --- | ---: | ---: | ---: | ---: |
| R1 | 3,252,769 | 4,035,180 | 3,112,454 | 95.6863% |

相对第四轮，原始多余名称减少 1,179 个至 127,875 个，新增 GRH 独有名称仍为 0。原来
匹配但在候选 R1 不再存活的名称为 2,026 个，比前轮增加 11 个，均归类为 inline constant
source；需继续核对这些变化是否与别名规则相邻。R4 校验 1 个图、0 个错误，资源守卫未
报告干扰。AliasAnalysis 用时 15.741 秒，C++ 变换回归 5/5、采集合同 7/7。

证据位于 `ptmp/firrtl-ingest/F34/alias-iteration6/cohort.json`、
`ptmp/firrtl-ingest/F34/alias-iteration6/comparison.json`、
`ptmp/firrtl-ingest/F34/alias-iteration6/capture/summary.json` 和
`ptmp/firrtl-ingest/F34/alias-iteration6/final-tests.log`。

### 7.7 拆分后重建值的恒等投影

GSIM 在 R0 已把 `AgeDetector` 的高位分量表达为独立的上游引用。GRH 的同名 Node
`age_1._T_4`（`2866873`）拥有 `kAssign` `13347748`、第 1 位的 `kSliceStatic`
`13347747`，以及把整值送到切片的两层 `kAssign` `13347746`、`35451986`。整值由
`35575296 = concat(34752743, 34752742)` 重建。切片恰好选回宽度和类型均相同的
高位操作数 `34752743`，归属 Node `9727874`，对应 GSIM R0 的 `io.enq_0$1_1`。

AliasAnalysis 现在沿同类型赋值找到拼接，只有切片范围恰好覆盖一个完整且同类型的操作数
时，才替换切片并转发其消费者。被绕过的重建仅在没有消费者、端口、值锚点、语义绑定和
边界记录时回收。第 14 轮中 `_T_4` 和 `_T_5` 都已退休，幸存消费者 `_T_6`
（`2866876`）直接引用拆分源 `9727874`、`9727880`。迁移表按相同消费者和边类型匹配。
原消费者也退休时，沿原始依赖链核对仍存活的消费者及其操作数槽位。

前几轮的两条迁移也在同一次采集中得到核实。`7671832` 退休后，`73640` 提供切片
`35338253` 槽 `0` 的四位输入，消费者保留一位切片。共享标量寄存器读别名 `409728`
退休后，消费者 `415503` 引用寄存器源 `9447837` 的读值 `1517946`。其余已实现的规则
包括零索引从单元素数组选回同类型标量，以及把全宽切片归属迁给源 Node 并保留其结果
类型。普通 signedness 转换 `kAssign` 保留独立名称。

| 捕获 | R0 Node | R1 Node | 退休 Node |
| --- | ---: | ---: | ---: |
| GRH 第 13 轮 | 4,616,189 | 3,235,008 | 1,381,181 |
| GRH 第 14 轮 | 4,616,189 | 3,204,828 | 1,411,361 |
| GSIM 冻结参考 | 5,775,134 | 4,035,180 | 1,739,954 |

两端 R0 库存不同。退休总数用于记录各自的 pass 效果，判断漏删需核对 R0 同名节点和
R1 的执行成员，再以实际连边验证。第 14 轮 AliasAnalysis 耗时 17.527 秒，R0、R1、R4
SemanticTree 校验均为零错误。`make test_f34_passes` 通过 5/5，重建投影夹具检查两层
转发、跨拼接段的真实切片、消费边以及 Oracle 输出。香山验证覆盖图结构和归属，整机仿真
未包含在本次采集中。

证据位于 `ptmp/firrtl-ingest/F34/alias-iteration14/` 的 `capture/summary.json`、
`capture/R1/node-details.jsonl`、`alignment-tables/manifest.json` 和
`alignment-tables/migration.tsv`。迁移表双端合计 6,290,112 行，覆盖 3,151,315 个
退休 Node。`AgeDetector` 的 R0 详细操作链见
`ptmp/firrtl-ingest/F34/alias-iteration13/slice-probe/R0/node-details.jsonl`。

按原始 555,556 个 GRH R1 存活、GSIM R1 退休的同名节点追踪，第 14 轮已退休
471,125 个，剩余 84,431 个，比第 13 轮减少 25,790 个。相对这组数据使用的旧基线，
第 14 轮还有 6,618 个 GSIM R1 存活的同名节点在 GRH 退休，其中 5,815 个是 GSIM
执行成员，803 个是内联常量来源。这些名称需要结合两端实际操作和迁移判断。
统计见 `ptmp/firrtl-ingest/F34/alias-iteration14/trace-analysis-cohort.json`。

逐 ID 比较第 13、14 轮 GRH R1，有 33,985 个 Node 新退休，3,805 个恢复存活。
例如 FIRRTL 将 `_wakeupOHVec_0_T` 直接连到 `wakeupOHVec[0]`。GSIM 上该别名
`8243487` 的消费者迁到 `_wakeupOHVec_0_T`（`2119346`）。GRH 第 13 轮中 `8119444`
也退休，消费者迁到 `2225157`。第 14 轮 R1 中这两个 Node 同时存活，共享 `kConcat`
`10375977` 的结果 `10864471`，两者之间仍有从 `2225157` 到 `8119444` 的依赖边。
原始连接、两轮端点和迁移可从 FIRRTL 的 `connect`、相应 R1 `node-endpoints.tsv`
和 `alignment-tables/migration.tsv` 交叉核对。

### 7.8 保留具名拼接的消费边界

补采显示 `wakeupOHVec_0` 在 GRH R0 只有值锚点。它的消费者既读取整值，也通过
局部投影读取分量。第 14 轮将位 0 折成一位值 `10863996`，下游边界记录仍以整值别名
`8119444` 为来源。该边界无法按整值转发，`8119444` 因此存活。

第 15 轮只对没有操作归属和值锚点的拼接进行该投影折叠。`8119444` 重新退休，`_T_2`
（`2281871`）的真实切片 `35385422` 在槽 `0` 读取 `2225157` 的九位值 `10864471`。
`AgeDetector` 的两个别名仍退休，`_T_6` 继续引用 `9727874`、`9727880`。回归同时
覆盖具名拼接、重建拼接和 signedness 转换的槽位边界。证据见第 14 轮 `wakeup-probe`
和第 15 轮 `capture` 的 R0/R1 `node-details.jsonl`，以及第 15 轮迁移表。

香山第 15 轮从 4,616,189 个 Node 降至 3,205,852 个，退休 1,410,337 个。
AliasAnalysis 耗时 17.096 秒，R0、R1、R4 的 SemanticTree 校验均为零错误，
`make test_f34_passes` 通过 5/5。原始 555,556 个同名差异中已有 474,339 个退休，
剩余 81,217 个，比第 14 轮减少 3,214 个。同一旧基线下，GRH 退休而 GSIM R1 仍执行
的同名节点从 5,815 降至 1,551，另有 803 个 GSIM 内联常量来源。统计见
`ptmp/firrtl-ingest/F34/alias-iteration15/cohort.json`。

剩余样本包括 PLIC `99717` 从 `[1]` 寄存器整值读取后再切片，以及 RAT `8161827`
的 `kRegisterReadArrayPort` `11911214`。后者的存储来源边无操作数槽，R0 上引用赋值
`11911216` 的结果，仍需证明迁移后读端口的索引与存储归属。ICache `9723132` 则在
GRH 上确实从 256 位值选出 128 位，GSIM 在 R0 已有独立的 128 位上游。剩余同名差异
包含这类不同的 R0 表达，仍待逐类判定。

### 7.9 静态索引寄存器读的归属迁移

RAT `8161827` 的 R0 存储边引用 `kAssign` `11911216` 的结果 `12232157`，并以赋值
操作充当无槽位的选值上下文。赋值输入来自 `kRegisterReadArrayPort` `11911214`，
常量下标为 0。GSIM 的同名节点 `8340939` 在 R1 退休，消费者迁到 `spec_table`。

规则要求无槽位存储边确实指向同类型赋值的结果，`regSymbol` 解析到唯一的存储
所有者，且每一维均有确定的界内下标。读端口及赋值保留，操作归属和值锚点迁到存储
节点。第 16 轮曾只迁操作归属与显式边界，导致同一 Mux 的共享所有者 `7945015` 丢失
通过锚点解析的依赖。第 17 轮中 `8161827` 退休，`11911214` 仍使用原下标，Mux
`11908080` 的槽 `2` 仍读取 `12232157`。显式消费者 `2553589` 与共享消费者
`7945015` 均解析到存储 `2553413`。

第 17 轮香山从 4,616,189 个 Node 降至 3,205,836 个，退休 1,410,353 个，耗时
17.020 秒。R0、R1、R4 的 SemanticTree 校验均为零错误。`make test_f34_passes`
通过 5/5，回归覆盖静态选择、显式和共享消费边、动态与非法下标及 Oracle 输出。
原始 555,556 个同名差异中，474,355 个已退休，剩余 81,201 个。静态索引规则贡献
其中 16 个新增退休。剩余组仍包含 PLIC 整值读取后的投影及 ICache 位段几何差异。

证据位于 `ptmp/firrtl-ingest/F34/alias-iteration17/` 的 `capture/summary.json`、
`capture/R1/node-details.jsonl`、`capture/R1/connections.tsv`、
`trace-analysis-cohort.json` 和 `alignment-tables/migration.tsv`。

### 7.10 单元素寄存器的标量投影

PLIC `99717` 通过 `kSliceArray` `220101` 从存储 `7242293` 的一位 `[1]` 整体读值
`32027280` 中选取元素 0，产出标量 `291501`。新版将这个切片及其值锚点迁给存储
节点，保留读取、索引、切片和标量类型。第 18 轮中消费者 `115913` 和 `115915`
都从 `99717` 迁到 `7242293`，与 GSIM 消费者对 `intBuffer.REG` 的迁移一致。

本轮新增退休 3 个同名节点，全部在 GSIM R1 退休。GRH R1 为 3,205,833 个节点，原始
同名差异组剩余 81,198 个。R4 语义树校验零错误，F34 回归通过 5/5。原始槽位和迁移表
见 `ptmp/firrtl-ingest/F34/alias-iteration18/` 的 `capture/R1/node-details.jsonl`、
`alignment-tables/migration.tsv` 和 `trace-analysis-cohort.json`。

### 7.11 直接索引寄存器读的归属迁移

UBTB `_WIRE.value_0`（`7721617`）的 R0 存储来源边由 `kRegisterReadArrayPort`
`702342` 直接提供。第 17 轮的静态索引规则只接受读值经过同类型 `kAssign`
的形态。第 19 轮两种形态使用相同的存储归属、下标、消费边和成员检查。
`7721617` 退休后，`702342` 仍使用 `32'b0`，读值 `907421` 锚定在存储
`282985`。消费者 `283697` 的 `kReduceOr` 继续读取 `907421`，R1 依赖解析到
`282985`。GSIM 同名节点 `7863444` 与中间消费者 `7863380` 都退休，最终消费者
`242665` 依赖同名存储 `242629`。

香山 R0 为 4,616,189 个节点，R1 为 3,198,702 个。AliasAnalysis 用时 17.153 秒，
R0、R1、R4 的 SemanticTree 校验均为零错误。`make test_f34_passes` 通过 5/5，
覆盖读取与赋值两种形态、有效和无效下标以及消费边。香山采集验证了结构和归属，
整机仿真尚未运行。

相较第 18 轮新增退休 7,131 个，其中 7,021 个也在 GSIM 退休。另 110 个发射队列
节点在 GSIM R1 仍有三个输入依赖，在 GRH R0 则分别是单一寄存器数组读。逐节点
核对确认其原消费者在 GRH R1 均可从原存储来源到达。原始 555,556 个同名差异中
已有 481,379 个退休，剩余 74,177 个。计入后来新增的 216 个名称，当前全部同名
差异为 74,393 个。同一旧基线下，GRH 已退休而 GSIM R1 仍执行的同名节点为
1,661 个。

证据位于 `ptmp/firrtl-ingest/F34/alias-iteration19/` 的 `trace-analysis-cohort.json`、
`new-loss-analysis.json`、`capture/{R0,R1}/node-details.jsonl` 和
`capture/{R0,R1}/connections.tsv`。双端 `alignment-tables/migration.tsv` 共
6,300,737 行。UBTB 样本在两端的第一跳都指向后来退休的中间节点，第二跳分别由
GRH `7721585` 和 GSIM `7863380` 迁到存储。

### 7.12 转发节点的共享打包归属

Timer `_out_T_323`（`118815`）的标量恒等链把原字节转发到 `out_prepend_9`
（`118839`）。R0 中 `118815` 还共享 `kConcat` `302092` 与数组打包赋值
`302093` 的归属，原规则因此保留该名称。第 20 轮允许具有唯一转发锚点和明确输入
来源的节点放弃这类共享归属，前提是打包结果无独立锚点或绑定，且每个共享操作仍有
存活所有者。

R1 中 `118815` 退休，`118839` 的拼接 `248996` 在槽 `1` 使用原字节值
`338975`，来源为 `118233`。共享打包的两个操作均从 16 个所有者降至 15 个。
对照 GSIM，`91200` 和下一跳 `91201` 也在 AliasAnalysis 后退休。

第 20 轮 R0 为 4,616,189 个节点，R1 为 3,198,554 个，AliasAnalysis 用时 18.818 秒。
F34 回归通过 5/5，R0、R1、R4 的 SemanticTree 校验为零错误。相较第 19 轮新增
退休 169 个节点，全部也在 GSIM 退休。恢复的 21 个中，16 个在 GSIM 退休，
4 个在 GSIM R0 没有同名节点，1 个在 GSIM R1 作为内联常量。原始差异组剩余
74,024 个，加上后来新增的 216 个名称，全部同名差异为 74,240 个。

证据位于 `ptmp/firrtl-ingest/F34/alias-iteration20/` 的
`capture/{R0,R1}/node-details.jsonl`、`capture/summary.json`、
`trace-analysis-cohort.json` 和 `trace-analysis-delta.tsv`。

### 7.13 从操作结果发现候选并统一退休提交

第二阶段从 op 的结果值收集候选，再按 SemanticId 顺序检查语义归属、绑定和依赖。
两阶段共用消费边改写和批量退休入口。第二阶段在恒等值转发完成后读取更新后的图。

以第 21 轮实现为冻结基线，两次香山采集的 R0 都有 4,616,189 个节点，R1 都有
3,197,762 个。R0 和 R1 的节点、连边、端点和位切片表正文逐行一致。14 个抽样
节点的原生明细在排除采集元数据、边界序号和行顺序后也一致，覆盖操作归属、值锚点
和操作数槽。ICache 的 `7713097` 在两次采集中均退休，`7713099` 从 `7713095`
读取原 Mux 的值 `33614638`。

两次采集均在 R4 结束，R0、R1、R4 的 SemanticTree 校验均为零错误。
`make test_f34_passes` 通过 5/5。单次 AliasAnalysis 用时分别为 17.504 秒和
18.063 秒，本次重测覆盖香山图结构和变换回归。

采集摘要位于 `ptmp/firrtl-ingest/F34/alias-op-refactor/` 的
`baseline/capture-retry/summary.json` 和 `candidate/capture/summary.json`。

### 7.14 AliasAnalysis 后仍存活的同名节点

冻结 GSIM 与 GRH 在 R0 有 4,596,538 个同名节点。R1 中两端均保留 3,112,019 个，
均退休 1,397,285 个，退休判定一致率为 98.10%。其中 73,476 个只在 GRH 保留，
13,758 个只在 GSIM 保留。GRH R1 另有 12,267 个名称在 GSIM R0 无同名节点。

从 GSIM R0 的单一已解析前驱沿退休链追到 R1 存活来源，发现 21,242 个 GRH 保留名
在 R1 与该来源的 GRH 同名节点共享唯一值。其中 18,683 个在本 pass 改了值锚点，
其余 2,559 个未记录到明确的旧值到新值迁移，其中 2,353 个锚定 Mux 结果。另有
27,315 个可找到来源的唯一 GRH R1 值，但保留名锚定不同的值或缺少唯一值端点。
15,926 个在 GRH R0 找不到来源的同名节点。剩余 8,993 个
的来源无法沿 GSIM R0 连边解析，或其 GRH 同名节点已退休、缺少唯一的 R1 值端点。
这些计数来自端点和连边，保留原因由下面的原生样本确认。

| GRH R1 节点 | 原生记录与保留条件 |
| --- | --- |
| BPU `rasAction` `279887` | 与 `700638` 共享 Mux `3038050` 的值 `3142875`，另外仍拥有常量 `2542963`。`282429` 的切片 `695262` 在槽 `0` 读取 `3142875`，`7718512` 的切片 `2565803` 在槽 `0` 读取另一个数组值 `34517418`，其边界来源也记为 `279887`。共享 producer 路径要求只有一个操作成员，且出边均使用锚值。两项在此均不满足。 |
| IFU `perfCnt_bore` `591872` | 与 `664637` 共享 `kAnd` `2822220` 的值 `2943314`。恒等赋值消失后，`591872` 仍是常量 `2823121` 的唯一所有者，常量结果 `2943932` 被 Mux `2823784` 的槽 `2` 使用。因此只接受单个操作成员的共享 producer 规则仍保留 `591872`。 |
| IBuffer `inst` `677377` | 与 `697933` 共用 `kOr` 结果 `3073165`，仍拥有两个常量操作。输入边来自 `677361`，值为形状 `[1]` 的 `3104658`。该边也不满足共享 producer 路径所要求的同一锚值。 |
| ITTAGE `maskTarget_0` `7850215` | R0 和 R1 均与 `7850200` 共用 Mux 结果 `33615322`。节点拥有结果 Mux `34266068` 和上一级 Mux `34266063`，后者输出 `33615317`，作为 `34266068` 的槽 `2`。下游 `7850225`、`517820` 的实际消费者继续读取 `33615322`。额外的 Mux 成员已足以挡住退休。 |
| 共享标量寄存器读 `7874116` | 与存储 `9451471` 共用读端口 `2848973` 和 12 位值 `2733343`。下游 `664936` 还有一条来自 `7874116` 的 6 位切片值 `34524837` 的边。共享标量读取规则要求全部出边直接使用读值。 |
| ABTB `readValidVec_0` `7725817` | `kRegisterReadArrayPort` `811168` 产生形状 `[4]` 的值 `1053560`，`kSliceStatic` `34265640` 提取位 0。GSIM 将同名别名转发到 `needWrite`。GRH 现有规则接受直接标量索引读或受限的单元素数组投影，这组读和位切片超出了规则范围。 |
| IFU `lowPCVec_0_T` `612862` 和 ICache `missResp` `9723132` | GRH 分别保留 `35347085` 的 50 位取 7 位及 `35551927` 的 256 位取 128 位。GSIM R0 已将对应位段表示为独立上游节点。 |
| `cpu._l_soc_io_reset_T_1` `40492` | 恒等赋值已转发，R1 仍由 `kOr` `27042` 用 `reset` 值 `2` 和 `DMCONTROLReg.ndmreset` 值 `400180` 计算 `54103`。GSIM 的同名节点在 R0 经单前驱链指向 `reset`。 |

共享结果的归属检查见 `wolvrix/lib/transform/alias_analysis.cpp` 的 `representsAlias` 和
`findOwnedAssignmentAliases`。GSIM 的 `Node::isAlias` 检查赋值树根和前驱，
`ExpTree::replace` 将相应子树转发给消费者。GRH 的 `279887` 在 R0 已有使用非锚值的
消费边，`7850215` 在 R0 已有双 Mux 归属。对这两类名称，迁移需要分别处理投影依赖
或额外操作归属。ITTAGE 样本的两个 Mux 已同时归属 `7850200`，其出边都使用
`33615322`，可用来验证接受共同操作成员的退休条件。

全图统计见 `ptmp/firrtl-ingest/F34/alias-op-refactor/candidate/` 的
`gsim-retirement-explanation.json` 和 `trace-analysis-remaining-peers.json`。原生证据位于
同级 `remaining-details/{R0,R1}/node-details.jsonl`。补采使用同一输入和冻结二进制，
R0、R1、R4 SemanticTree 校验均为零错误。本轮只补采和归因，整机仿真未运行。

### 7.15 修复 IFU 静态切片的来源追踪

在 IFU 中，`UsedBits` 缩窄消费赋值，把原先读取 50 位整值的语义边移到切片结果。整值
由两个语义名共用，`split-nodes` 当时无法从切片输入槽确定来源。现在当未绑定的静态切片
结果上，每个消费槽均有显式数据边且边的来源一致时，拆分计划采用该来源，并沿消费者的
赋值和切片计算实际读取区间。消费边迁移沿本次据此改写的切片继续追踪。普通赋值链使用
原有迁移路径，AgeDetector 的重建拼接保留匿名，`2866873` 和 `2866874` 在 R1 均退休。

香山的 `_triggerHitVec_WIRE_0`（`7877995`）拆成 `[6:0]`、`[7]`、`[49:8]`，与
GSIM 的拆分相同。GRH 在 R0 已将 `612862` 接到低 7 位子节点 `9723499`，R1 中
`612862` 退休。R1 共 3,197,527 个 GRH 节点，其中 3,112,109 个在 GSIM 有唯一同名
节点，对齐率从 97.3187% 升至 97.3286%。在 R0 同名、R1 仅 GRH 保留的节点从
73,476 降至 73,157，退休判定一致率从 98.1022% 升至 98.1083%。

`make test_f32_split_nodes` 通过 1/1，`make test_f34_passes` 通过 5/5。完整 F32 套件
通过 19/20，`transform-f32-pipeline` 仍要求已经实现的 `alias-analysis` 拒绝运行。
香山采集进程使用 `MIMALLOC_ALLOW_LARGE_OS_PAGES=0` 运行至 R4 并返回 0，R0、R1、R4
语义树校验均为零错误。资源守卫在进程退出时读取 VmRSS 失败，保留了失败状态。对账使用
独立校验过哈希、行数和快照标识的 R0/R1 表。整机仿真未运行。

证据位于 `ptmp/firrtl-ingest/F34/ifu-split-nodes/v3/` 的 `capture/R0/bit-slices.tsv`、
`capture/R1/node-details.jsonl`、`capture/summary.json`、`capture/guard.json` 和
`gsim-alignment-delta.json`。

### 7.16 修复 SplitNodes 后的保留节点追踪

沿 GSIM R0 的唯一已解析数据前驱追到 R1 存活节点，再用同名节点和 GRH 原生值端点对照。
73,157 个在 GSIM 退休但在 GRH 保留的名称全部纳入统计。

| GRH 对照结果 | 节点数 |
| --- | ---: |
| 与 GSIM 指向的来源共用唯一 R1 值 | 21,245 |
| 来源有唯一 R1 值，候选锚定另一值或缺少唯一值 | 28,112 |
| GSIM 来源在 GRH R0 无同名节点 | 14,788 |
| GRH 来源存活但缺少唯一 R1 值 | 7,045 |
| GSIM 前驱链未解析 | 1,182 |
| GSIM 来源的 GRH 同名节点也已退休 | 785 |

共享同一个 R1 值的节点中，18,686 个在本 pass 换了值锚点。另有 2,353 个从 R0 到 R1
始终与来源共享同一个 Mux 值。后者中，1,787 个在 R1 的唯一导出入边来自该来源，且
导出出边中无非数据边、回边或相关未解析边。另 530 个涉及未解析边，36 个的已解析
入边不满足单来源条件。连边表未枚举完整操作成员、语义绑定和原生边的值与槽位。

ITTAGE `7850215` 的原生记录显示，来源 `7850200` 已共同拥有两级 Mux `34266063` 和
`34266068`，唯一入边、两条出边都使用结果 `33615322`。当前共享 producer 规则要求候选
仅有一个操作成员，因此保留 `7850215`。如放宽此检查，应在别名链解析后核对最终代表
是否仍拥有候选的每个操作成员。IFU `591872` 则独占仍有物理消费者的常量 `2823121`，
BPU `279887` 有一条出边读取另一数组值 `34517418`，两者需要额外的归属或边迁移检查。

IFU `7874116` 与寄存器存储节点共用 12 位读值 `2733343`，还有一条出边携带 `[5:0]`
的投影值 `34524837`。ABTB `7725817` 的独立位切片来自形状 `[4]` 的数组索引读。当前
两条规则分别限制出边必须直接使用读值，以及索引读本身必须产出标量。

ICache `9723132` 的差异在前序 P3 已出现。GSIM 将 `missUnit.io.resp.bits.data` 拆为
四个 128 位段，GRH 将其拆为两个 256 位段。两端各有四个 128 位 `mainPipe` 消费端。
GSIM 消费端转发已有子节点，GRH `9723132` 继续执行 256 位取 128 位的切片。
调试复位 `40492` 在 GSIM 的 Q1 常量分析中失去调试复位输入。GRH R1 的 `kOr` 仍读取
`DMCONTROLReg.ndmreset`。两端采用的 SimJTAG 时钟模型有差异，GSIM 将其第二个时钟
端口视作普通无驱动节点。GSIM 将该寄存器判为常量的具体分支未在逐节点 trace 中记录。

结果见 `ptmp/firrtl-ingest/F34/ifu-split-nodes/v3/` 中的 `remaining-peers.json`、
`shared-mux-topology.json` 和三份样本记录 `same-value-findings.md`、
`storage-findings.md`、`prior-pass-findings.md`。本轮复用 §7.15 独立校验的 R0/R1 快照。

### 7.17 退休共享多个纯操作的转发名称

AliasAnalysis 现在允许共享同一个值的转发名称拥有多个纯操作。候选必须拥有锚值的
定义操作，并通过原有的绑定和消费边检查。沿别名链确定最终代表后，再检查该代表已
拥有候选的每个操作成员。夹具覆盖完整共享、直接来源缺少成员、最终代表缺少成员，
同时核对 Mux 输出和两条消费边的操作数槽位。

香山 ITTAGE `7850215` 在 R1 退休，`7850200` 接管指向 `7850225` 和 `517820` 的
两条语义边。物理操作 `34266073` 的槽 `2` 和 `2134425` 的槽 `1` 继续读取 `33615322`。

与 §7.15 相比，R0 的 4,616,281 条节点记录逐行一致。R1 新退休 2,098 个节点，
其中 2,024 个也在 GSIM 退休，另 74 个在 GSIM R0 无同名节点。R1 的 3,195,429 个
GRH 节点中有 3,112,109 个与 GSIM 唯一同名，对齐率从 97.3286% 升至 97.3925%。
仅 GRH 保留的 R0 同名节点从 73,157 降至 71,133，退休判定一致率从 98.1083% 升至
98.1523%。

`make test_f34_passes` 通过 5/5。香山采集使用 `MIMALLOC_ALLOW_LARGE_OS_PAGES=0`，
进程运行至 R4 并返回 0，R0、R1、R4 语义树校验均为零错误。资源守卫在退出时读取
VmRSS 失败并保留失败状态，对账独立复核了 R0/R1 快照的哈希、行数和标识。整机仿真
未运行。

原生样本、库存差异和同名对账位于 `ptmp/firrtl-ingest/F34/shared-op-members/` 的
`capture/R1/node-details.jsonl`、`inventory-changes.json` 和 `gsim-alignment-delta.json`。

### 7.18 在 AliasAnalysis 中追踪投影来源

折叠单元素数组的零索引读取时，AliasAnalysis 记录原数组操作数。候选名称只有一条
无操作数槽位的数组入边时，沿该名称独占的赋值链确认入边对应本次折叠的切片，再用
拥有并锚定标量值的唯一节点迁移消费边。IBuffer `677377` 在 R1 退休，`697933`
接管指向 `677441` 的值 `3073165` 的边。数组打包仍由 `677361` 持有。

共享标量寄存器读按 `regSymbol` 确认存储节点。若消费边携带目标节点拥有的静态切片
结果，AliasAnalysis 将该边接到切片的输入槽 `0`。IFU `7874116` 在 R1 退休，
`9451471` 通过槽 `0` 向切片 `35347383` 提供读值 `2733343`，下游仍读取原切片结果。
本轮生产代码改动集中在 AliasAnalysis。回归覆盖共享常量归属、独立控制依赖、
切片归属、物理操作数和改写前后的输出值。

与 §7.17 相比，R0 的 4,616,281 条节点记录逐行一致。R1 新退休 133 个节点，其中
130 个也在 GSIM 退休，另外 3 个是 GSIM 仍保留的
`vecException.io.decodedInst.srcType_{0,1,2}`。R1 的 3,195,296 个 GRH 节点中，
3,112,106 个与 GSIM 唯一同名，对齐率从 97.3925% 升至 97.3965%。仅 GRH 保留的
R0 同名节点从 71,133 降至 71,003，退休判定一致率从 98.1523% 升至 98.1551%。

`make test_f34_passes` 通过 5/5。香山采集进程完成 R4 并返回 0，R0、R1、R4
语义树校验均为零错误。资源守卫在退出时读取 VmRSS 失败并保留失败状态，对账独立
复核了快照哈希、行数和标识。整机仿真未运行。

原生样本、库存差异和同名对账位于 `ptmp/firrtl-ingest/F34/alias-provenance/` 的
`capture/R1/node-details.jsonl`、`r1-inventory-changes.jsonl` 和
`gsim-alignment-delta.json`。

### 7.19 在静态数组拆分时完成成员转发

`split-static-array` 在改写固定索引读时记录原寄存器节点、对应的标量成员和读值。
数组两端的成员都创建后，用原数据边和标量读值确认转发关系。只有一个锚值、
没有独立操作、绑定或其他依赖的内部转发成员可以在本 pass 退休。迁移出边时
保留边上的值、消费操作和槽位。仍需保留的成员补回寄存器来源边。

香山 IFU 端口成员 `7874116` 在 R0 已退休，寄存器成员 `9451471` 接管其出边。
到 `664936` 的边在 R0 仍携带切片值 `34524837`，消费操作 `2824096` 的槽位为
`0`。AliasAnalysis 随后折叠该消费操作，R1 边保留切片值和源节点，操作及槽位不再
存在。

与 §7.18 相比，R0 少 14,345 个节点，同名对齐率由 99.5759% 变为 99.5747%。
R1 少 4 个节点，均为 GSIM 仍保留的 `storeQueue.new_vec_1` 成员
`_3`、`_6`、`_15` 和 `_23`。R1 同名对齐率四舍五入后仍为 97.3965%，
仅 GRH 保留的 R0 同名节点仍为 71,003。

`make test_transform_split_static_array` 通过，`make test_f34_passes` 通过 5/5。
香山采集进程完成 R4 并返回 0，R0、R1、R4 语义树校验均为零错误。资源守卫在退出时
读取 VmRSS 失败，对账用独立复核了哈希、行数和标识的快照完成。整机仿真未运行。
采集和对账产物在 `ptmp/firrtl-ingest/F34/split-indexed-source/`。

### 7.20 AliasAnalysis 全图原生采集

两端从同一份原始香山 `SimTop.fir` 运行到 AliasAnalysis 返回。GRH 使用按 F24
配置重建的 ingest manifest，采用 `invalid_policy=zero` 和 10 个 lowering 线程。

| 引擎 | R0 节点 | R1 节点 | 原生 trace 退休节点 |
| --- | ---: | ---: | ---: |
| GRH | 4,601,936 | 3,195,292 | 1,406,644 |
| GSIM | 5,775,134 | 4,035,180 | 1,739,954 |

两端原生 trace 的退休 ID 集合均与各自的 R0 → R1 节点差集完全一致，新增节点均为 0。
GRH 记录了 3,143,027 次边界引用迁移，两个边界的 SemanticTree 校验均为零错误。
GSIM 首轮漏记动态赋值左值索引改写。修正后全图重跑正常退出，原生 trace 包含
3,228,625 条演化事件和相同数量的变更记录，`replayComplete=true`。

R0 的 4,582,365 个唯一同名节点中，4,497,563 个在两端的退休判定一致（98.1494%）。
仅 GRH 保留 71,003 个，仅 GSIM 保留 13,799 个。R1 有 3,112,102 个唯一同名候选，
占 GRH R1 节点的 97.3965%。

产物位于 `ptmp/firrtl-ingest/F34/alias-capture/`。`grh/` 和 `gsim-native/` 均包含
`R0/nodes.tsv`、`R1/nodes.tsv` 和 `alias-analysis-migrations.jsonl`。逐 ID 对账及
文件 SHA-256 见 `validation/native-report.json`。`make test_f34_passes` 通过 5/5，
`make test_f34_contract` 通过 9/9，`make test_f34_gsim_stop` 通过 6/6。

### 7.21 仅 GRH 保留的 71,003 个同名节点

范围为 R0 两端唯一同名、R1 在 GRH 存活且在 GSIM 退休的节点。全部 71,003 个节点
均关联到一条 GSIM 原生迁移，替代表达式的根节点都在 GSIM R1 存活。其中 38,226 条
迁移的直接目标与表达式根不同。GRH 中有 56,750 个节点换了值锚点，30,829 个出现在
原生边界引用迁移中或成为其他退休节点的代表。

| R1 对照结果 | 节点数 |
| --- | ---: |
| 与 GSIM 最终来源的 GRH 同名节点共享值锚点 | 20,856 |
| GSIM 最终来源在 GRH R0 无同名节点 | 15,752 |
| GRH 锚值与 GSIM 最终来源的位宽、符号或形状不同 | 13,449 |
| 位宽、符号、形状相同，GRH 锚定不同的值 | 12,147 |
| GSIM 替代表达式含常量数组索引 | 6,118 |
| 找到 GRH 同名来源，保留节点只有操作记录 | 1,924 |
| GSIM 最终来源的 GRH 同名节点也已退休 | 757 |

对账按 GSIM 替代表达式、最终来源在 GRH 的唯一同名节点和 GRH 实际值锚点依次判断。
全部节点中有 2,167 个在 GRH R1 只导出了操作记录，其中 243 个已计入其他行。
表中的同名关系和形状用于定位，操作成员、绑定和消费槽位仍需逐项证据才能判定可退休性。

- 在共享锚值的 20,856 个节点中，20,187 个在本 pass 换了锚点。3,497 个的唯一导出
  入边来自对应来源，导出的相邻边均为已解析依赖，且无自环或指回来源的出边。
  其中 3,001 个有导出的下游边。BPU `rasAction` `279887` 与 `700638` 共享 Mux
  值 `3142875`。GRH 仍从 `279887` 导出依赖，GSIM 则把 32 个仍存活的直接消费者
  改接到最终来源 `681808`。
- 类型差异中有 12,756 个是 GRH 的 `[1]` `kAssign` 对应 GSIM 的同宽同符号标量。
  其中 10,585 个的 GRH 导出入边直接来自最终来源的同名节点。GSIM 的 6,118 条索引
  替代中有 5,316 条单索引和 802 条双索引。ABTB `7725817` 在 GRH 保留切片，
  GSIM 则把 `needWrite[0]` 带入替代表达式。
- ICache `9723132` 在 GRH 从已有 256 位段取低 128 位，GSIM 在 R0 已拥有对应的
  128 位段。调试复位 `40492` 在 GRH R1 仍计算 `reset | ndmreset`，GSIM 的
  `ndmreset` 在 R0 已为零，替代表达式只引用顶层 `reset`。

沿 GSIM R0 已解析依赖穿过退休节点时，71,000 个节点可达 R1 存活消费者。按目标
ID 和边类型核对，有 70,998 个的全部终点都能从替代表达式的根找到对应边。两个
例外为 `ClockGate.Q` 和 `ClockGate_1.Q`。trace 均指向顶层 `clock`，但相关 GSIM R1
寄存器的 `clock_node_id` 仍引用已退休的中间时钟，连接表记录为未解析。

逐节点台账和复查材料位于 `ptmp/firrtl-ingest/F34/alias-capture/retained-analysis/`。
`ledger.tsv` 记录最终来源、GSIM 原始 trace 序号与字节偏移，以及 GRH R1 端点对照。
`grh/evidence.jsonl` 记录双边界的 GRH 端点、依赖和相关原生事件，消费者链和样本分别
见 `gsim/consumer-chains.json` 和 `examples/findings.md`。

### 7.22 共享值锚点的别名退役

AliasAnalysis 先解析最终代表，再按源节点、值、消费操作和槽位核对重复入边，按出边的
实际值确认来源。若消费节点独占本地打包链，并且已有一条可迁移的共享锚值依赖，退役时
移除该节点内部的冗余边界记录，保留原操作数。别名独占的内部常量仅在存在唯一纯消费操作
及可确认的存活所有者时转交。共享锚值相等只用于筛选候选。

同一份香山 `SimTop.fir` 重跑 GRH 到 R1，使用 §7.20 的冻结 GSIM 采集对账。GRH R0 的
节点、端点、连接和切片四张表与基线逐行一致。R1 从 3,195,292 降至 3,195,289，新增退役
3 个节点，新增保留 0 个。三者均属于初筛的 3,001 个共享值候选，且均已在 GSIM 退役。

| 新退役节点 | GRH 最终代表 | 原生 trace 序号 |
| --- | ---: | ---: |
| BPU `rasAction` `279887` | `700638` | `4191503` |
| IFU `perfCnt_bore` `591872` | `664637` | `4193136` |
| ROB `enqPtrVec_0_new_ptr.flag` `2150839` | `2150851` | `4193767` |

逐条核对三者原有的 66 条出边。58 条在代表节点下保留原值、边类型、消费操作和槽位。
BPU 的另外 8 条变为消费节点内部的投影。以目标 `7718512` 为例，`kSliceArray` 操作
`2565803` 在槽位 `0` 继续读取本地打包所得的数组值 `34517418`，对共享锚值 `3142875`
的边界依赖由 `700638` 接管。共享值类仍有 20,853 个节点仅在 GRH 保留，其中 2,998 个
通过初筛。全部仅 GRH 保留的 R0 同名节点共 71,000 个。

`make test_f34_passes` 通过 5/5。香山 R0、R1 SemanticTree 校验均为零错误。原生 trace
包含 1,406,647 条退役记录和 3,143,085 条边界引用迁移记录，退役 ID 集合与 R0 → R1
节点差集一致。IFU 定向补采的 R0、R1 节点库存及 trace 与全图重测相符。常量操作
`2823121` 产生的值 `2943932` 仍供 Mux `2823784` 的槽位 `2` 使用，常量由该 Mux 的三个
语义节点 `9454269`、`9454307`、`9454345` 接管。本轮香山验证运行到 AliasAnalysis 返回。

重测快照和原生 trace 位于 `ptmp/firrtl-ingest/F34/alias-repair/retest/grh-v2/`，出边核对见
同级 `verified-edges.json`。逐节点差异 `R1-node-delta.tsv`、原生样本、`report.json` 和
`ifu-owner-verification.json` 位于 `ptmp/firrtl-ingest/F34/shared-value-retirement/verification/`。

### 7.23 全图核对别名判定和切片来源

§7.22 的 3,001 个节点是按共享锚点和导出边初筛所得，最终只有 3 个通过原生消费槽位和
操作归属检查。原规则依赖折叠后的边界，转发链中缺失具名边界时，即使有唯一的上游计算
所有者也无法退役。放宽前先允许别名释放无消费者、锚点、绑定及边界引用的内部常量。
相对 §7.22，此轮新增退役 2,444 个，其中共享值类 2,364 个，R1 唯一同名率为
3,112,098 / 3,192,845（97.4710%）。

随后加入唯一上游计算所有者回退、折叠前投影输入归因和保留附属常量的类型视图迁移。
相对上一轮共新增退役 46,319 个。GSIM 同样退役的有 30,896 个，GSIM R1 仍保留的
唯一同名节点有 15,384 个，另有 39 个没有唯一同名对应。R1 唯一同名率为
3,096,714 / 3,146,526（98.4169%）。R0 节点、端点、连边和位切片表逐行一致，
GRH 原生 trace 的 1,455,410 个退役 ID 与快照差集一致。

误退役的最大一组有 11,448 个，在 GRH R0 锚定 `kAssign`，而 GSIM R0 赋值根为
`BITS`。以 ROB 节点 `1811446` 为例，它与 `1736578` 在 FIRRTL 各自计算 `[8:3]`，
两者在 GSIM R1 都保留。GRH 的 `1811446` 在 R0 的入边存在歧义，改用物理切片的唯一
操作所有者时把它归到 `1736578`。仅完整切位成员判断的实验未恢复这个样本，反而新增
128 个 GSIM 仍保留的同名退役，相关代码已撤回。

首轮常量扩展见 `ptmp/firrtl-ingest/F34/shared-value-retirement/v3/`。投影候选的唯一同名
统计、逐节点误退役和 trace 差集核验见 `ptmp/firrtl-ingest/F34/alias-coverage/` 下的
`metric/grh-projection-r1-alignment.json`、`metric/projection-delta-profile.tsv` 和
`projection-verification/report.json`。

### 7.24 寄存器静态索引和单元素数组

静态寄存器读按实际存储声明、界内常量下标、原生来源及读端口判定。操作或锚点允许其他
合法所有者，迁移时保留索引、实际读操作和消费槽位。相对 §7.23 投影版，新增 3,039 个
双端一致退役，唯一同名匹配数仍为 3,096,714，R1 唯一同名率为 98.5121%。
退役 ID 与 R0、R1 快照差集一致，四张 R0 表逐行一致。

单元素数组内固定索引 `0` 的读取可进入既有赋值链验证。规则核对读出值、边界记录的
数组槽位、打包及常量归属，保留实际读取和打包操作。全图新增 1,477 个退役，其中 1,475
个在 GSIM 也退役，另两个在 GSIM R1 的赋值根已折叠为常量。冻结包还带有独立的 128 个
投影实验误退役，故该包直接实测为 3,096,584 / 3,141,882（98.5583%）。

包含撤回投影实验、严格恢复拆分位段和初版共享赋值的后续包实测
3,096,712 / 3,141,241（98.5824%）。这 3,141,241 个 GRH R1 节点中，有 32,389 个在
R0 有 GSIM 同名节点且该节点经 GSIM AliasAnalysis 退役，另有 12,140 个名称在
GSIM R0 已不存在。若保持当前匹配数，达到 99.6% 需要修正其中至少 32,093 个漏退役。
反向核对还记录了 29,189 个 R0 唯一同名、在 GSIM R1 存活但 GRH 已退役的节点。

直接匹配、原生 trace 与逐节点对账位于 `ptmp/firrtl-ingest/F34/` 下的
`indexed-alias-review/verification/report.json`、
`shared-value-retirement/aggregate-audit/verification/report.json`、
`split-child-projection/r1-alignment.json` 和
`alias-coverage/metric/split-child-retirement-gap.json`。

### 7.25 共享赋值与第一类剩余节点

共享的单元素数组到标量赋值通过真实 `kAssign` 操作及其唯一输入边确定代表。迁移保留
原有赋值和消费槽位。与 §7.24 最后一版相比，新增退役 2,011 个节点，GSIM 对这批节点
全部退役。GRH R1 有 3,139,230 个节点，其中 3,096,712 个在 GSIM R1 有唯一同名节点
（98.6456%）。R0 四张表与基线逐行一致，R0、R1 的 SemanticTree 校验均为零错误。
原生 trace 的 1,462,706 个退役 ID 与快照差集完全一致。

按 §7.21 冻结的 71,003 个节点逐 ID 核对，此版仍保留 30,378 个。第一类共享值节点
从 20,856 个降至 4,369 个，其中 1,406 个锚定 `kMux`，1,243 个锚定
`kRegisterReadPort`。反向核对仍有 29,189 个 R0 唯一同名节点在 GSIM R1 存活且在
GRH 退役。验证文件位于 `ptmp/firrtl-ingest/F34/assignment-audit/`，其中
`shared-verification.json` 记录快照和 trace 核对，`shared-retirement-gap.json` 记录
双向差异，`shared-r1-alignment-retired.tsv` 列出本轮新增退役的 ID。

折叠后没有消费槽位的具名依赖也可参与共享值归并。规则要求代表节点记录相同的
来源、值和依赖类型。解码器节点 `8146094` 退役时，向 `2413803` 的依赖迁移至
`8139594`，使用的值仍为 `11590834`。相对上一版新增 29 个双端一致退役，其中 21 个
属于第一类。原始 71,003 个节点剩 30,349 个，第一类剩 4,348 个，最初筛出的 3,001 个
节点中剩 1,414 个。R1 唯一同名率为 3,096,712 / 3,139,201（98.6465%）。R0 四张表
逐行相同，双界 SemanticTree 校验零错误，原生 trace 的 1,462,735 个退役 ID 与快照差集
一致。核对结果和本轮新增退役 ID 位于 `ptmp/firrtl-ingest/F34/shared-named-dependency/verification/`。

### 7.26 撤回缺少具名来源的别名推断

GSIM 在赋值树中判定别名。普通节点必须只有一棵赋值树和一个前驱，右值根必须引用
另一个节点。数组目标还要求完整左值和普通节点来源。索引是右值节点引用的组成部分，
迁移时随引用传递。

GRH 撤回折叠后的数组或位切片追到唯一操作所有者的判定，也撤回具名来源缺失时用
计算所有者补全代表的判定。同时撤回打包寄存器专用退役及其在 DCE
中生成的专用记录。保留物理值折叠，并用回归验证无槽位的单元素读取折叠后，其具名
节点和下游消费槽仍然存在。

香山 ROB 的 `1811446` 与 `1736578` 各自定义 `bits(deqPtrVec[0].value, 8, 3)`。
两者可共享 GRH 的切片值 `34211825`。此前用切片所有者作代表导致 `1811446` 退役。
本轮两名均存活，与 GSIM 一致。原有误退役中 GRH R0 为 `kAssign`、折叠后为
`kSliceStatic`、GSIM R0 根为 `BITS` 的 11,448 个节点全部恢复。

Decode 的 `8136538` 在数组拆分后仍由标量赋值 `34303723` 直接转发寄存器成员
`9478833` 的读值。到 R0，标量锚值和赋值已被清理，节点仅剩共享打包操作。
1,495 个同组节点有相同的前缀证据。这里应在形成和清理赋值时维护具名右值或将其按
合法的转发边替换，使 AliasAnalysis 可以直接消费。ROB 样本则要求保留独立切片计算
的节点身份，即使下层共用一个值。

香山全图 R0 四张表与 §7.20 基线逐行一致。GRH R1 有 3,172,354 个节点，其中
3,112,094 个有 GSIM R1 唯一同名节点（98.1005%）。相比
`split-child-projection/verification-v2`，R1 恢复了 15,387 个唯一同名匹配。
在两端 R0 唯一同名的 4,582,365 对中，48,101 对仅 GRH 保留，13,807 对仅 GSIM
保留。§7.21 冻结的 71,003 个节点还保留 48,090 个，第一类还保留 18,468 个。
第一类剩余节点中，17,340 个在 R0 锚定 `kAssign`，11,759 个在 R0 至少有一条
未解析入边。导出的连接表有 1,512 个节点显示来自 GSIM 最终来源同名节点的直接数据边。
这些统计可以重叠。原生边界记录的核对见 §7.27。

GRH 两界 SemanticTree 校验零错误。GRH 的 1,429,582 个原生退役 ID 和 GSIM 的
1,739,954 个原生退役 ID 均与各自 R0、R1 的快照差集一致。
`make test_f34_passes` 通过 5/5。本轮完成到 R1。
证据在 `ptmp/firrtl-ingest/F34/rule-simplification/`，包括 `native-report.json`、
`R0-equivalence.json`、`r1-alignment.json`、`original-retained-cohorts.tsv` 和
`restored-bits.tsv`。第一类的 R0 端点和入边统计见 `first-cohort-r0-*.tsv`。
Decode 前缀证据见 `operation-only-audit/provenance.json`。

### 7.27 第一类的赋值右值与原生边界

最初只新增退役 3 个的版本，在共享值和导出连线初筛后，仍要求常量能交给存活消费者，
并校验其他入边与共享计算的关系。2,998 个未通过的候选里，1,563 个首先被无消费者的
内部常量挡住，1,229 个首先被非转发入边挡住。这里把实现操作的归属和具名赋值右值一起
用作了别名判定。拒绝原因见 `shared-value-retirement/rejection-audit/rejection-audit.json`。

补采 §7.26 的 1,512 个节点及其来源的原生记录后，只有 316 个在 R0 有通往该同名来源的
原生直接边。63 个有同类型、单操作数的 `kAssign`，且该唯一操作数有对应的具名入边；
63 个都同时挂有其他值的无槽位入边。以 Rename 的 `uops.fuOpType_0`（`8164376`）为例，
赋值只读 `3523684`，其来源是 `7945785`，原生入边却同时列出该数组的 8 个成员。到 R1，
1,512 个节点都与对应来源共享物理值。证据见 `first-class-direct/audit.json` 及同目录的
`grh/R0`、`grh/R1` 快照。

具名右值实验只在 FIRRTL lowering 中把直接全量赋值的引用绑定到 `kAssign` 的槽位 0。
全图双向对账显示，GSIM 保留的节点有 154 个恢复匹配，同时 GSIM 已退役的节点有 107 个
回到 GRH R1。R1 唯一同名率从 98.1005% 到 98.0974%（3,112,248 / 3,172,611）。
该实验改变了前缀的节点分配和 R0 库存，跨版本按唯一名称比较，每次运行内部按原生 ID
验证迁移。GRH 的 1,429,323 个退役 ID 与 R0、R1 差集一致，双界 SemanticTree 校验零错误，
相关回归通过 6/6。证据见 `named-rhs/native-report.json`、`named-rhs/tests/test.log` 和
`mux-guard-audit/named-rhs-delta.tsv`。

GSIM 的判定读取当前赋值树的右值根。GRH 对应的信息应由产生或改写赋值的 pass 维护。
数组拆分应把每个成员的真实右值传给该成员，表达式折叠应在根变成具名引用时同步更新
节点引用，独立切片计算则保留自己的节点身份。具名右值全图实验尚未修复这些前缀差异。

## 8. AliasAnalysis 回退重构与差异溯源规划

2026-11-21 建立并经用户确认。R1 唯一同名率是硬指标：后续活跃度划分分析以两端同名
Node 为依据，没有名字对应就没有分析基础。本节不降低该目标，而是改变达到它的路径：
不在 AliasAnalysis 内补偿前缀差异，而是回退该 pass、定义 R0 右值根契约、在产生
差异的 pass 中修复，最后把 AliasAnalysis 重写为 GSIM 判定的直译。

### 8.1 判定

§7.4–§7.26 共 26 轮，AliasAnalysis 从已提交的 F23 版本 137 行增至 1,779 行，其中
1,642 行是本轮未提交改动。R1 唯一同名率停在 98.65% 附近，两次撤回。剩余差异双向各约
三万：GRH 保留而 GSIM 退役约 30,349 个，GRH 退役而 GSIM 保留 29,189 个，另有 12,140 个
GRH R1 名称在 GSIM R0 不存在。

GSIM 的判定只读当前赋值树：普通 Node 只有一棵赋值树、一个前驱、右值根是节点引用；
退役即把引用表达式替换进消费者，索引随引用传递，替换时沿用旧引用的宽度。这个形状由
它的 SplitArray、ExprOpt、UsedBits、SplitNodes、ConstantAnalysis 在 R0 之前决定。GRH 在
R0 的对应形状由自己的前缀 pass 产生，F31、F32、F33 各自冻结了未归因差异。AliasAnalysis
是第一个判定完全取决于右值根语法的 pass，因此把前缀差异集中暴露出来。§7.21 的分类中，
GSIM 来源在 GRH R0 无同名（15,752）、宽度或形状不同（13,449，其中 `[1]` 数组对标量
12,756）、锚定不同值（12,147）都是 R0 已存在的差异；§7.23 的 11,448 个误退役是 GRH R0
根为 `kAssign` 而 GSIM 根为 `BITS`。

本轮新增的规则没有一条对应 `isAlias` 的任何分支，全部是在 R0 形状已不同的前提下推断
GSIM 会退役哪个名字。名字率以 GRH R1 为分母，退掉任何 GRH 独有名称都会使比率上升，
误退同名节点几乎不扣分；§7.23 新增 46,319 个退役中 15,384 个 GSIM 仍保留，比率仍从
97.47% 升到 98.42%。继续加规则只会使误退与漏退同时增长。
[GSIM isAlias](../../reference/gsim/src/aliasAnalysis.cpp#L13) · [GSIM replace](../../reference/gsim/src/aliasAnalysis.cpp#L94)

### 8.2 原则

1. **别名差异是探测器，不是修复对象。** 每个剩余差异必须归到两端右值根签名首次不一致的
   边界，修复在该边界之前的 pass 中进行。AliasAnalysis、第四次 DCE 和导出脚本都不做名字
   补偿。
2. **AliasAnalysis 只允许是 GSIM 判定的直译。** 每条判定和迁移行为须能指到 `isAlias`、
   `ExpTree::replace` 或 `mergeSubTree` 的具体行为。没有 GSIM 对应行为的规则不写。
3. **双向计量。** 每轮同时报告 R1 唯一同名率、R0 同名节点上的退役判定一致率（双向）和
   两个单边集合的数量。名字率上升但误退增加的改动不接受。
4. **前序阶段不退化。** 修改前缀 pass 后，F31 v51、F32 P4、F33 Q2 的同名率和既有回归
   必须不低于已记录值；各阶段冻结的已知差异只能减少，被修复的差异在原阶段文档补记来源。
5. **接受一次性退步。** 回退后 R1 名字率预计回到 §7.4 的 84.5% 附近，在前缀修复落地前
   低于 98.65%。此期间 R2–R4 的采集不作为对齐依据，F34.6 正式性能顺延。

### 8.3 回退 AliasAnalysis

`wolvrix/lib/transform/alias_analysis.cpp` 回退到已提交版本（F23 的同类型标量 `kAssign`
与全宽静态 slice 转发），从未提交改动中只保留三项，均不是补偿规则：

| 保留项 | 原因 |
| --- | --- |
| `AliasMigrationTrace` 与 `-trace-alias-migrations` 入口 | §8.5 的台账和双向对账依赖原生迁移记录 |
| 改图前解析整条恒等链（§7.4） | 逐 op 判断会把 owner 迁到上游并残留转发 Node，是算法修正 |
| `requireWholeGrh` / `verifyWhole` 前后校验 | 对任何版本都成立的合法性门 |

删除的函数：`replaceReconstructedBitSlice`、`wholeConcatOperand`、`singletonArrayElement`、
`findSharedRegisterReadAliases`、`findSharedRegisterReadSelectionAliases`、
`sharedPackingMember`、`findOwnedAssignmentAliases` 及其 `sharedSingletonAssignmentSource`、
`indexedRegisterSource`、`fixedArraySelectionSource`、`singletonRegisterSource`、
`sharedScalarRegisterSource`、`planLiteralRetirement`、`planSharedComputationRetirement`、
`hasLocalProjection`、`consumerProjection`，以及 `retireOwnedAssignmentAliases`。
`representsAlias` 收缩为：Node 的全部成员 op 与 anchor 都转发到同一 root 值、binding
均为普通值绑定，其余分支删除。

`test_f34_passes` 中编码上述补偿行为的 fixture 同步删除；保留输入端口、别名链、多结果
生产者 anchor、状态、时钟、DPI 和有序数组后写优先的边界回归。§7.19 对
`split-static-array` 的成员转发修改属于前缀 pass，按 §8.6 的契约重新评估后决定保留或
替换，不随本节回退。回退后以同一香山输入重跑到 R1，记录基线名字率和双向指标，作为
后续每一步的对照起点。

2026-11-21。F34.5a 冻结包中的 AliasAnalysis 为 448 行。香山 GRH R0 有 4,613,618
个节点，较 §7.20 新增 11,686 个名字、缺少 4 个，净增 11,682 个。R1 有 3,680,017 个
节点，原生 trace 的 933,601 个退役 ID 与快照差集完全一致，两界 SemanticTree 校验均为零
错误。R1 唯一同名率为 3,122,213 / 3,680,017（84.8424%），cohort A、B、C、D
分别为 542,676、11,769、15,128、901,198。R0 唯一同名对为 4,594,039 / 4,613,618（99.5756%），
高于 §7.20 的 99.5747%，新增的 11,686 个 R0 名字几乎都有 GSIM 同名。cohort D 中 823,627 个是
GSIM 内联常量来源，真正的执行成员差异为 77,571 个。AliasAnalysis 用时 19.103 秒。v1 在
`hier-flatten` 期间因构建与快照遗留的文件缓存触发持续回收，内存 PSI 超限后被守卫终止。
v2 采集、对账和失败证据见
`ptmp/firrtl-ingest/F34/culprit-ledger/{f34-5a-xiangshan-r1-v2/,baseline/,f34-5a-xiangshan-r1/}`。

基线采集期间发现一个并行的 Codex 持久 goal 线程（10:10 启动，objective 为对照 GSIM 从原理上
改进 AliasAnalysis、对齐率回到 99，已用 2,181 万 token）在同一工作树上继续加退役规则，
与 §8.2 相悖。13:27 按用户指示用 `codex remote-control stop` 终止；其与冻结包不一致的 5 个
文件原样备份到 `culprit-ledger/goal-thread-leftovers/`，工作树恢复为冻结包版本（AliasAnalysis
448 行）。恢复后 `test_f34_passes` 5/5、`test_grhsim_transforms` 4/4、
`test_transform_split_static_array` 1/1 通过，日志在 `culprit-ledger/resync-tests/`。该 goal 在
`~/.codex/goals_1.sqlite` 中仍为 `active`，重启守护进程会恢复运行，需在 Codex 侧关闭。
F34.5a 完成，F34.5b 从此状态开始。

### 8.4 R0 右值根契约

GSIM 读的是赋值树右值根；GRH 对应的信息必须由产生或改写赋值的 pass 维护（§7.26）。
定义每个 Node 在任一边界的**右值根签名**：

| 字段 | GRH | GSIM |
| --- | --- | --- |
| 存在性 | SemanticTree 中有该限定名 | 库存中有该名且非 DEAD/SPLITTED |
| 根 op | 唯一 anchor 值的定义 op kind | `assignTree[0]` 根的 opType |
| 宽度、符号、shape | anchor 值类型 | Node 的 width、sign、dimension |
| 具名来源 | 根为 `kAssign` 或 `kSliceArray` 时直接引用的具名 Node | 根 ENode 的 `nodePtr` |
| 索引 | `kSliceArray` 的常量下标 | 根 ENode 的 index 子项 |
| 前驱数 | 入边具名来源去重数 | `prev.size()` |
| 赋值数 | 定义该 anchor 的赋值 op 数 | `assignTree.size()` |
| 常量 | anchor 定义为 `kConstant` | 根为常量 |

契约要求：到 R0 时，两端同名 Node 的签名逐字段一致。满足契约后，GSIM 的 `isAlias` 在
GRH 上有唯一对应判定，AliasAnalysis 不需要任何推断。签名导出复用
`semantic_node_exchange.py` 的表格式，两端各一个导出入口，并有合同测试覆盖字段缺失、
名字重排和多 anchor。

#### rhs-root-signature.v2

TSV 沿用 SemanticNodeExchange 的元数据、转义和完整 footer。每行以限定名 `name` 和本界原生
`node_id` 标识。ID 不参与对账；无名行无匹配对象。限定名重复时拒绝对账。

| 字段 | GRH 导出 | GSIM 导出 |
| --- | --- | --- |
| `exists` | SemanticTree 有该限定名 | 库存有该名，排除 `DEAD_NODE` 和 `SPLITTED_NODE` |
| `root_op` | 唯一 anchor 的原始定义 op kind | `assignTree[0]` 根的原始 `opType`，根有 `nodePtr` 时加 `:nodePtr` |
| `root_class` | 归一后的根类别 | 归一后的根类别 |
| `width`、`signed`、`shape` | anchor 类型的元素位宽、符号和各维度 | Node 的 `width`、`sign`、`dimension` |
| `named_source` | 归一后引用的第 0 操作数，优先取精确边界引用，其次取唯一其他 anchor owner | 根 `nodePtr` 的限定名，或符号转换下直接引用的限定名 |
| `constant_indices` | `kSliceArray` 第 1 个及后续操作数的可解常量 | 引用的 `OP_INDEX_INT` 或可读为字面常量的 `OP_INDEX` 子项 |
| `predecessor_count` | 已解析依赖入边的具名来源去重数，排除独立状态更新边和时钟、复位事件操作数 | `prev.size()`，按 `Node::updateConnect` 建立 |
| `assignment_count` | 唯一 anchor 的 SSA 定义数，有定义为 1，无定义为 0 | `assignTree.size()` |
| `constant` | 归一后根为 `kConstant` | 根为 `OP_INT` |

数组下标按维度顺序记录，动态或无法表示的下标记 `null`，无下标为 `[]`。没有唯一 anchor
时，GRH 的 anchor 派生字段为 `null`。时钟、复位按原生事件操作数槽排除，数据操作数
仍计数。GRH 前驱数依赖已解析边，GSIM 则包含其原生内存端口邻接等关系。

GRH 从 anchor 沿同类型 `kAssign` 读取内部值；遇到其他 Node 的 anchor、精确具名引用、
端口或绑定即停。若落在具名值上，记 `reference`；遇到计算则取该计算的根类别。位宽、
维度和逻辑域相同而符号不同的 `kAssign` 记 `sign_view`，可继续越过其输入的内部同类型
赋值以定位直接来源。GSIM 符号转换下有直接引用时取其 `nodePtr`。部分位切片不填来源。

| GSIM 根 | GRH 定义 | 比较值 |
| --- | --- | --- |
| `OP_EMPTY:nodePtr`，无下标 | 同类型 `kAssign` 的引用边界 | `reference` |
| 带下标的 `OP_EMPTY:nodePtr`、`OP_INDEX_INT`、`OP_INDEX` | `kSliceArray` | `array_index` |
| `OP_BITS` | `kSliceStatic` | `kSliceStatic` |
| `OP_INT` | `kConstant` | `kConstant` |
| `OP_ASSINT`、`OP_ASUINT` | 仅变更符号的 `kAssign` | `sign_view` |
| 对应的算术、比较、位运算、拼接、归约和 Mux | 同类 GRH op | 对应的 `k*` |
| 其余 op | 其余 op | `other:<native>` |

GSIM 在 `Init` 和 `SplitArray` 将 `width`、`signed` 记为 `unknown`（TSV `\U`）；
从 `InferAllWidth` 起读取原生类型，仍为负的位宽及其符号记为 `null`（TSV `\N`）。
比较只用 `root_class`，保留 `root_op` 供核验。任一端为 `unknown` 的字段跳过，并在
`unknown_fields` 记录截至首次分歧或末界的跳过项。两端 `null` 相等，`null` 与已知
值不同。单边缺名时只比 `exists`。

例：`x = bank[1]` 的 GRH anchor 由 `kAssign(kSliceArray(bank, 1))` 定义，
内层结果无名且无绑定。GSIM 根为带 `OP_INDEX_INT(1)` 子项的 `nodePtr`。两端
`root_op` 分别为 `kAssign` 和 `OP_EMPTY:nodePtr`，比较值均为 `array_index`，
来源为 `bank`，下标为 `[1]`。若外层赋值只是引用另一具名 Node 的 anchor，则停在
该具名引用，比较值为 `reference`。

### 8.5 逐边界溯源

| 边界 | GRH pass | GSIM stage | 已有对照 |
| --- | --- | --- | --- |
| B0 | ingest-firrtl → xmr-resolve → hier-flatten | AST2Graph/Init | F28 |
| B1 | 数组 lowering 与 split-static-array | SplitArray → InferAllWidth | F29、F30 |
| P0 | `dead-code-elim#0` | RemoveDeadNodes0 | F31 |
| P1 | `expr-opt` | ExprOpt | F32 |
| P2 | `used-bits` | UsedBits | F32 |
| P3 | `split-nodes` | SplitNodes | F32 |
| P4 = Q0 | `dead-code-elim#1` | RemoveDeadNodes1 | F32 |
| Q1 | `constant-analysis` | ConstantAnalysis | F33 |
| Q2 = R0 | `dead-code-elim#2` | RemoveDeadNodes2 | F33、§7.1 |
| R1 | `alias-analysis#0` | AliasAnalysis | §7、本节 |

GSIM 的 SemanticNodeExchange 已支持在上述各 stage 停止并导出，每个 stage 用新进程；
GRH 在一次运行内按 `run_pass` 取快照。
[GSIM 停止与导出](../../reference/gsim/src/main.cpp#L217) · [GRH 生产顺序](../../scripts/grhsim_flow.py#L281)

输入为回退后的四个 cohort，以 §7.20 冻结的 GSIM 采集为准：

| cohort | 定义 |
| --- | --- |
| A | R0 唯一同名，GRH R1 保留，GSIM R1 退役 |
| B | R0 唯一同名，GRH R1 退役，GSIM R1 保留 |
| C | GRH R1 名称在 GSIM R0 不存在 |
| D | GSIM R1 名称在 GRH R0 不存在 |

对 cohort 中每个名字及其 GSIM 替代表达式的根来源，在 B0 到 R0 逐边界导出签名，首次不一致
的边界为分歧边界，其前一个 pass 记为始作俑者；cohort C、D 以名字首次单边出现的边界为准。
追溯只对 cohort 名字及其一跳来源做，不做全图逐界导出。

产出 `ptmp/firrtl-ingest/F34/culprit-ledger/ledger.tsv`，每行一个名字：cohort、分歧边界、
始作俑者 pass、两端签名、不一致字段、处置（fix、freeze）。按始作俑者和不一致字段汇总为
`summary.json`，写回 §8.9。

已有线索的预判归属，需由台账确认或否定：

| 类别 | 数量 | 预判始作俑者 | 依据 |
| --- | ---: | --- | --- |
| GRH `[1]` 数组赋值对 GSIM 同宽标量 | 12,756 | B1 数组 lowering / split-static-array | §7.21；§7.19 |
| GSIM 最终来源在 GRH R0 无同名 | 15,752 | P3 split-nodes 位段切分（ICache 256/128 位）或 B0 命名 | §7.21 |
| GRH R0 根 `kAssign`、GSIM 根 `BITS` | 11,448 | P1/P2 折叠后未更新节点引用的右值根 | §7.23、§7.26 |
| 常量折叠结果不同（`ndmreset`） | 待计 | Q1 constant-analysis 或 P1 expr-opt | §7.21 |
| 共享 `kMux`、`kRegisterReadPort` 锚点 | 4,348 | B0 右值绑定（§7.26 具名右值实验） | §7.25、§7.26 |

### 8.6 在始作俑者 pass 中修复

按台账汇总数量从大到小处理。每项修复：在该 pass 的现有回归目录新增最小 fixture，先在
小例上复现签名差异并修正；再在香山上重跑到 R0，核对该类别台账行数下降、§8.2 第 4 条的
前序阶段不退化；最后跑到 R1 记录双向指标。前缀 pass 维护签名的方式按 §7.26 结论：数组
拆分把每个成员的真实右值传给该成员，表达式折叠在根变成具名引用时同步更新节点引用，
独立切片计算保留自己的节点身份。

归为 freeze 的类别须说明两端表达的实际差异和不修的原因，并给出活跃度划分中处理这些
名字的方式（例如以 GSIM 替代表达式根建立显式映射）。

2026-11-21。F31 v51、F32 P4、F33 Q2 冻结库存已清理，§8.2 第 4 条改用已验收 v4 前缀在 P0、P4、R0 的新双端库存，同名率不得下降，新增单边名逐名举证，旧占比仅供参考。

### 8.7 AliasAnalysis 直译重写

签名契约在香山 R0 达成后，重写 AliasAnalysis，判定与迁移均与 GSIM 一一对应：

| GSIM 行为 | GRH 对应 |
| --- | --- |
| `type == NODE_OTHERS` | Node 非端口、非寄存器、非 memory、非外部效果 |
| `assignTree.size() == 1`，根为节点引用 | 唯一 anchor 的定义为 `kAssign` 或常量下标 `kSliceArray`，直接引用具名来源 |
| `prev.size() == 1` | 入边具名来源去重数为 1 |
| 数组目标：完整左值、来源为普通 Node | shape 非空时同样要求整值赋值且来源非状态 |
| `mergeSubTree`：索引随引用传递 | 迁移消费者时保留 `kSliceArray` 下标 |
| `replace` 沿用旧引用宽度、不检查符号 | 不以 `sameValueType` 作为拒绝条件，宽度差由消费者侧保持原值类型 |
| `aliasMap` 链式解析 | 改图前解析整条恒等链到根（§7.4 保留项） |
| 退役后 `removeNodesNoConnect` + `reconnectAll` | 退役 Node、迁移边界引用，死 op 留给第四次 DCE |

重写后不得再出现 §8.3 删除列表中的任何推断。小例回归覆盖表中每一行各一正一负例；
香山复测以 R1 唯一同名率不低于 **99.6%**、R0 不低于 99.5743%、cohort A、B 全部有归属
为退出门。R2–R4 在 R1 达标后按 §3 重新采集，PatternDetect、CommonExpr 和第四次 DCE 的
差异沿用 §8.5 的台账方法。

### 8.8 阶段与交付

| 阶段 | 交付与退出条件 |
| --- | --- |
| F34.5a 回退 | AliasAnalysis 回到 F23 版本加三项保留；补偿 fixture 删除；香山 R1 基线名字率与双向指标记录 |
| F34.5b 契约与导出 | 右值根签名定义、两端逐边界导出入口和合同测试完成 |
| F34.5c 溯源台账 | `culprit-ledger/ledger.tsv` 覆盖全部 cohort，无未归因行；§8.9 汇总填写 |
| F34.5d 前缀修复 | 按汇总逐 pass 修复，每项附 fixture、前序阶段回归和香山 R0 复测；R0 签名一致 |
| F34.5e 直译重写 | AliasAnalysis 按 §8.7 重写，小例正负例通过，香山 R1 达到退出门 |
| F34.5f 全窗口复采 | R0–R4 五界重采，更新 §7.3 格式的库存表，进入 F34.6 正式性能 |

Make 入口在现有 `capture_f34_pipeline`、`test_f34_alignment_tables` 之外新增签名导出、
逐边界溯源和台账汇总目标，命名随脚本确定。运行记录与失败证据放在
`ptmp/firrtl-ingest/F34/culprit-ledger/`。§7.4–§7.26 的记录保留为历史，其中的规则不再
作为实现依据。

2026-11-21。F34.5b 复审改用 `rhs-root-signature.v2`，比较归一根类别并记录未定义字段。
小例 B0 至 R1 首次分歧分布为 B0 3 个、P3 4 个、R1 3 个；`namedAlias` 在 P3 因
GRH 重组两个具名位段而首次分歧。合同测试 15/15，F34 pass、采集合同和 GSIM 停止
回归分别为 5/5、9/9、6/6。命令和证据见
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5b-report.md` 及同目录 `f34-5b-review/`。

复核发现工作树的 `constant_analysis.cpp` 仍是被终止的 goal 线程 12:57 的版本，缺少 F34.5a
冻结包中保留具名赋值不折叠的分支，复审包因此与 F34.5a 基线前缀不一致。该文件已备份到
`goal-thread-leftovers/` 并按冻结包恢复；工作树相对冻结包只剩 F34.5b 新增的 4 个只读导出文件。
重建的 `f34-5b-v3/package` 中 AliasAnalysis 与 448 行版本逐字节一致，小例台账与复审版逐行相同，
RHS 合同 15/15、F34 pass 5/5、采集合同 9/9、`test_grhsim_transforms` 4/4、
`test_transform_split_static_array` 1/1 通过。F34.5b 完成，F34.5c 使用 `f34-5b-v3/package`。

2026-11-21。F34.5c R0 门诊断：同一 F34.5a 包复跑，4,613,618 个 R0 名字及 ID 与 v2 全同；
v3 关闭中间 RHS 导出仍少 12,854 名、多 3,538 名，与原 RHS 采集的 813,118 个请求命中名字及 ID 全同。
恢复源码的时间戳早于增量构建对象，v3 冻结了与复审包逐字节相同的旧二进制，其中仍有
`split-static-array` 的 `named_member_bit_projection` 分支。先干净重建并核对 R0，再恢复溯源台账。
证据见 `ptmp/firrtl-ingest/F34/culprit-ledger/f34-5c-drift-report.md` 和同目录 `f34-5c/drift/`。
v3 恢复源码时保留旧时间戳，增量构建跳过了六个已恢复的源文件；v4 刷新时间戳、删除对应对象并重新构建后冻结。

2026-11-21。F34.5c 完成。v4 的 `SplitStaticArrayPass::run` 符号长度与 F34.5a 同为 `0xd004`，
GRH R0 四个 cohort 及额外来源的名字、ID 与 4,613,618 节点冻结库存一致，缺失、额外均为零。
两端 B0–R0 串行采集通过，台账 1,470,771 行、无未归因行。GSIM 新进程 ID 单独记录，
逐界对账按限定名。证据见 `ptmp/firrtl-ingest/F34/culprit-ledger/{f34-5c-v4/,f34-5c-report.md,ledger.tsv,summary.json}`。

2026-11-21。F34.5d 九项均已核查，验收 SplitNodes，P3 类 43,093→39,727，P0/P4/R0 库存同名率及单边集保持。香山 R0 99.57562590%、R1 84.92053454%，A 539,288、B 11,769、C 15,128、D 901,198。数组拆分、UsedBits、ExprOpt 的试验未过门并回退，余 300,180 行按 §8.9 记录处置。F34.5e 以 `culprit-ledger/f34-5d/split-nodes/package` 为前缀，证据见 `culprit-ledger/f34-5d-report.md`。

2026-11-21。F34.5e 首次直译版保持香山 R0 的全部 4,613,618 个名称和 ID，R1
唯一同名率为 84.57657026%，双向退役判定一致率为 87.53401963%。A 551,834、B 20,858，
均较 F34.5d 增加。R0、R1 SemanticTree 校验均为零错误，932,783 个原生退役 ID 与
库存差集完全一致。按 R0 ID 与 GSIM `node-details.tsv` 对账，新增的 11,266 个 B 均有
一棵赋值树，其中 8,275 个普通节点标记为常量，2,975 个普通节点仍有效，16 个是外部输入。
完整两端 R0 签名重算后，
A、B 中分别有 2,081、878 个签名一致而判定不同，另有 381,956、11,265 个有签名差异的
名称尚欠首次分歧边界。首轮验收未通过。证据见
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5e/full-v3/alignment/`。

第二轮把唯一前驱数量与具名 RHS 来源分开读取，对应 `Node::isAlias` 的 `prev.size() == 1`。
香山 R0 的节点、连边、端点和位片表数据均与 F34.5d 一致，同名率 99.57562590%。
R1 为 3,112,617 / 3,581,347（86.91190773%），相对 F34.5d 上升 1.99137 个百分点。
判定一致率从 88.00495599% 升至 89.66094977%，A 从 539,288 降至 453,615，B 从 11,769
增至 21,365，C 为 15,115，D 为 901,198。两界 SemanticTree 校验零错误，1,032,271 个
退役 ID 与快照差集完全一致。AliasAnalysis 单次原生计时 9.799 秒，F34.5d 为 19.579 秒。
`test_f34_passes` 5/5。99.6% 及 A/B 完整归因两项仍未通过。

A、B 全部已有两端 R0 签名及原生退役证据，分别有 285,119、11,415 项还缺最早分歧边界。
A 中有 387,763 项在 GRH R0 的归一根不是具名引用或常量索引，光是静态位切片就有
183,482 项。`_timer_c_T_1` 的缩减例中，GSIM UsedBits 将 `tail` 改为对 `sum` 的引用，
GRH 在 R0 仍为 `kSliceStatic`。这是前缀对齐问题。对账、签名和缩减例位于
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5e/{full-v4/alignment,prefix-tail}/`。

2026-11-22。外部模块补链后的端口使用扁平化发布的原生 SemanticId。v6 比 v4 多保留
1,005 个 GSIM 也保留的名字，A 增加 802、B 减少 1,005。v6 R0 仍为 99.57562590%，
四张 R0 表数据一致。R1 为 3,113,622 / 3,583,154（86.89612559%），双向退役判定一致率
89.66536854%，A 454,417、B 20,360。A、B 各有 285,119、11,399 个名字仍缺最早分歧边界。
两界 SemanticTree 校验零错误，迁移 trace 与节点差集按 ID 一致。证据见
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5e/full-v6/alignment/summary.json`。

固定该 R0，即使所有潜在的 3,133,982 个唯一同名都能保留，原始定义既非 `kAssign` 也非
`kSliceArray` 的 69,433 个 A 与 7,338 个 C 也须保留。仅计这些最保守的单边项，R1 上限
为 97.60894096%。达到 99.6% 需要实际改变 R0 前缀产生的签名或库存。计数见
`full-v6/alignment/fixed-r0-alias-ceiling.tsv`，最大同名数见 `full-v6/alignment/summary.json`。

UsedBits 候选在同类型操作数缩至完整低位切片时原地改为 `kAssign`。`TimerTail` 的 `low`
从 P2 起与 GSIM 同为 `reference/sum`，且两端 R1 均退役。香山 P0、P4、R0 的同名率和单边名
集合一致，R0 有 98,612 个 `kSliceStatic` 根变为 `reference`。R1 为 89.08180681%，漏退
较 v6 减少 89,042，误退增加 9,619，其中 8,755 个在两端的 RHS 根类别和具名来源均不同。
候选因误退增加回退。代码、回归与对账见
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5e/prefix-tail/`。

仅处理 FIRRTL `tail` 的候选也通过香山 P0、P4、R0 库存门，R0 四张表的数据与 F34.5d
一致。R1 为 3,113,456 / 3,527,891（88.25261325%），双向退役判定一致率为
90.86085251%。A 为 399,330，较 v6 减少 55,087，B 为 20,526，较 v6 新增 166。
新增误退在 GSIM R0 分别是 `OP_BITS` 164 个、`OP_INT` 2 个。此候选也已回退。
独立小例确认，GSIM UsedBits 可以把同样几何和需求下的 `tail` 与 `bits` 都缩成引用。
因此 `tail` 标记不足以区分 GSIM 是否消除切片。
补丁与证据见 `prefix-tail/tail-only-rejected.patch` 和 `prefix-tail/full-tail-only/alignment/`。

`MemberRhs` 缩减例将两个具名标量表达式分别连接到 `lanes[0]` 和 `lanes[1]`，再分别
读到输出。GRH 在 B1 把两个成员锚定到各自来源已使用的 SSA 值，并保留值上的入边。
GSIM 为每个成员各保留一棵根是具名引用的赋值树。两端这一差异持续到 R0，只有 GSIM 在
R1 退役两个成员。数据见 `f34-5e/member-rhs/member-ledger.tsv` 及 `member-rhs/v6/B1/design.json`。

`split-static-array` 候选只为单 owner、无绑定、消费者全为常量下标标量读取的数组成员建立
独立赋值，且要求原生入边证实唯一来源。`MemberRhs` 的签名从 B1 一致到 R1，B1 和 R0 各
通过 256 组输出值检查。带整值消费者的对照在 B1、R0、R1 签名不变。香山 P0 新增 60 个
GSIM 单边名，P4 新增 64 个 GSIM 单边名和 18 个 GRH 单边名，R0 同名率虽升至
99.57590749%，仍新增 63 个 GSIM 单边名和 18 个 GRH 单边名。前缀门失败，该补丁已回退，
未采集该候选的香山 R1。补丁和逐名门结果见 `f34-5e/member-rhs/{candidate.patch,full/prefix/}`。

2026-11-22。FloatDividerR64 的 B0 与 `comb-loop-elim` 后快照显示，循环修复先将数组
读取改为标量赋值，再将后续 `bits` 直接接到上游。原数组来源仍记在被绕过的赋值槽上。
第二个候选保留已解析的读取和成员偏移，由 B1 将具名成员接到该槽。缩减例中的成员在
P0、R0 保留，到 R1 随别名退役。死读取对照仍在 P0 删除无消费者的成员，独立小例在
B1、R0 各通过 256 组输出值检查。

香山第二个候选恢复上轮 P0 缺失的全部 60 个名称。P0 无新增单边名，P4 仍新增 18 个
GRH 单边名和 4 个 GSIM 单边名，R0 新增 18 个 GRH 单边名和 3 个 GSIM 单边名。
R0 同名率为 4,594,282 / 4,613,840（99.57610147%）。其中 `selDataMatrix_2` 两个成员
保留在整宽，缺少应在 P3 产生的四个位段名。独立小例用两臂 Mux 选择互补的 128 位有效
数据和零填充，复现了这个变化。另 16 个 `_raw_rdata_T*` 是 P0 已有、基线在 P4
删除的 SRAM 数据切片名。该候选未过前缀门，未采 R1。证据见
`f34-5e/member-rhs/{divider-parent/baseline/BC,p4-mini,retargeted/liveness/full/prefix}`。

第三个候选只为 1 位成员建立独立赋值。小例在 B1、P0、R0、R1 的六个名字均与 GSIM
签名一致，B1 和 R0 各通过全部 16 组输入。定向原生回归通过 11/11 项。香山 P0、P4、
R0 库存门全部通过，无新增单边名。R0 同名对由 4,594,039 增至 4,594,211，同名率为
4,594,211 / 4,613,782（99.57581438%）。证据见 `f34-5e/member-rhs/single-bit/`。

第三个候选的香山 R1 为 3,113,064 / 3,421,737（90.97905537%），双向退役判定一致率
为 93.15055403%。A/B/C/D 分别为 293,720 / 20,958 / 14,953 / 901,158。相对 v6，
A 减少 160,697，B 移除 240、增加 838，净增 598。新增 B 中，GSIM 仍执行 375 个位切片
和 42 个 AND，另有 421 个内联常量来源。原生迁移 trace 与快照的退役 ID 差集完全一致。
该候选的 R1 同名率和误退未过验收，工作树恢复到 v6。见
`f34-5e/member-rhs/single-bit/{full/alignment,new-b-vs-v6.tsv,removed-b-vs-v6.tsv}`。

用 v6 和第三个候选逐界复采新增的 838 个 B。与 v6 比，796 个消费者在 B1 已改变
右值签名，42 个到 Q1 才改变具名来源。FloatFMA sticky 位的小例加入假组合环及整值
消费者后复现原现象。两版 GRH 都在循环修复中把静态位切片改为标量赋值，候选又在
B1 给该赋值接上唯一的具名成员，最终在 R1 退役。GSIM 在 R0 保留 `OP_BITS`。
两个冻结包在 B1 和 R0 各通过 72 组值检查。见
`f34-5e/member-rhs/single-bit/{targeted/candidate-first-differences.tsv,sticky-scc-v2/}`。

v6 补采完成。新采集覆盖 296,518 个剩余 A/B 名称和 227,336 个 GSIM 替代根。合并已有
台账后覆盖全部 474,777 个 A/B 名称。其中 A 在 B1 首次分歧 317,792 个，在 B0 首次
分歧 68,228 个。B 在 Q1 首次分歧 11,359 个。另有 A 2,883 个、B 1 个的 R0 导出签名
相同，已定位到 R1 判定，需进一步核对节点资格和来源种类。完整证据在
`f34-5e/residual-prefix/v6-retry/{v6-a-b-ledger.tsv,v6-a-b-ledger.json,replacement-attribution.tsv}`。

Q1 首次分歧的 11,359 个 B 中，GSIM R0 有 9,697 个 `inline_constant_source` 和 1,662 个
执行成员。`ConstantReference` 的扩展例含共享常量源、被折叠的消费者和仍动态的 Mux。
直接移除 GRH `constant-analysis` 对具名赋值的保留规则后，各别名在 Q1 都折为常量，
仍被 Mux 使用的 `secondAlias` 在 R0、R1 都保留。其原来源 `source` 和 `liveAlias`
在第三次 DCE 消失，GSIM 则在来源目录保留二者。因此直接移除保留规则会把一部分
R1 误退转移成 R0 缺名，已回退。运行与执行成员表见 `f34-5e/constant-rhs/physical-retention/`。

按 GSIM R1 的执行成员表对账，F34.5d 的 11,769 个 B 包含 9,348 个活跃计算节点和
2,421 个内联常量来源。v6 的 20,360 个 B 包含 10,199 个活跃计算节点和 10,161 个内联
常量来源。仅比较活跃计算节点，误退仍净增 851。按原验收口径，v6 的 R1 同名率及误退
两项仍未达标。见 `f34-5e/constant-rhs/cohort-b-r1-membership.tsv`。

R0 签名相同但退役判定不同的唯一 B 样本，可用香山的 `Queue8_TPmetaReq` 原模块加
一个小封装复现。父模块将入队的 `rawData` 标成 invalid。GRH 在零值策略下将该载荷
降为零，Q1 将读取折叠为常量，随后有形状的输出引用在 R1 退役。GSIM 保留
`NODE_READER` 的 `OP_READ_MEM`，R1 保留引用。动态写入的 `set` 字段在两端均保留
存储读取。此处的等签名只涵盖候选自身，引用来源的根和节点种类在 Q1 分歧。
证据见 `f34-5e/memory-source/queue-write/{fixture.fir,clean/}`。

常量分类候选由 Q1 记录物理赋值已被证明为常量，R1 读取该分类并保留节点，对应 GSIM
只扫描 `VALID_NODE`。小例的常量来源和两个活引用均保留，F33/F34 原生定向回归 8/8。
香山与 F34.5d 的四张 R0 表数据一致。R1 为 3,121,662 / 3,594,955（86.83452227%），
双向退役判定一致率为 89.75877218%。相对 v6，B 减少 8,040，无新增 B，A 增加 3,749。
减少的 B 中 8,039 个为 GSIM 内联常量来源，1 个为执行成员。新增 A 的两端 R0 根均为
具名引用，说明 GRH 证明为常量与 GSIM 判为常量仍有差异。B 为 12,320，比 F34.5d
多 551，仍未通过验收。见 `f34-5e/constant-rhs/status/{fixture,full/alignment}/`。

此前回退候选后重新安装，原生库与 v6 冻结包的 SHA-256 一致。原生定向回归 9/9，
右值签名、采集、对账和 GSIM 停止合同回归分别 16/16、10/10、3/3、6/6。完整
`ingest-mixed` 另在 `mux-tree-fold` 阶段失败，该 pass 拒绝 SemanticTree；同一测试二进制的
`firrtl-semantic-abi` 子用例通过。见 `f34-5e/v6-restored/regressions-retry.log`
和 `f34-5e/native-v6-ingest.log`。

### 8.9 台账汇总

共 1,470,771 行，A 542,676、B 11,769、C 15,128、D 901,198，无未归因行。D 中
823,627 个 GSIM 内联常量来源记 `freeze`，用原生执行成员表排除；77,571 个活跃成员保留
单边名字溯源。A、B 各有 342,614、984 个 R0 签名一致而 R1 判定不同，交 F34.5e。
共 303,546 个 `fix` 候选。下表按首次分歧的边界归类。B0、B1 为组合边界，原生字段细项
和逐名替代根轨迹见 `culprit-ledger/{summary.json,f34-5c-v4/replacement-root-ledger.tsv}`。

| 首分歧前 GRH pass / GSIM stage | 字段类 | 行数 | 建议处置 |
| --- | --- | --- | --- |
| `dead-code-elim#2 / RemoveDeadNodes2` | 存在性 | 835,182 | freeze 787,121 / fix 48,061 |
| 无首分歧 | 显式分类 | 342,227 | AliasAnalysis-semantics 342,227 |
| `split-static-array#0 / InferAllWidth` | 根/来源 | 103,889 | fix 103,685 / AliasAnalysis-semantics 204 |
| `dead-code-elim#0 / RemoveDeadNodes0` | 存在性 | 47,597 | fix 28,524 / freeze 19,073 |
| `split-nodes#0 / SplitNodes` | 根/来源＋前驱/赋值 | 33,069 | fix 33,069 |
| `split-static-array#0 / InferAllWidth` | 根/来源＋前驱/赋值 | 17,544 | fix 17,540 / AliasAnalysis-semantics 4 |
| `hier-flatten#0 / Init` | 根/来源 | 15,752 | fix 14,605 / AliasAnalysis-semantics 1,147 |
| `hier-flatten#0 / Init` | 根/来源＋类型 | 15,437 | fix 15,437 |
| `hier-flatten#0 / Init` | 存在性 | 13,162 | freeze 7,826 / fix 5,336 |
| `dead-code-elim#1 / RemoveDeadNodes1` | 存在性 | 11,487 | freeze 9,105 / fix 2,382 |
| `split-static-array#0 / InferAllWidth` | 前驱/赋值 | 9,236 | fix 9,236 |
| `split-nodes#0 / SplitNodes` | 存在性 | 7,350 | fix 7,328 / freeze 22 |
| `hier-flatten#0 / Init` | 类型 | 5,453 | fix 5,453 |
| `constant-analysis#0 / ConstantAnalysis` | 根/来源 | 2,647 | fix 2,647 |
| `split-nodes#0 / SplitNodes` | 根/来源 | 2,480 | fix 2,480 |
| `constant-analysis#0 / ConstantAnalysis` | 根/来源＋前驱/赋值 | 2,434 | fix 2,434 |
| `dead-code-elim#0 / RemoveDeadNodes0` | 根/来源＋类型＋前驱/赋值 | 1,619 | fix 1,619 |
| `split-static-array#0 / InferAllWidth` | 存在性 | 1,548 | fix 1,068 / freeze 480 |
| `used-bits#0 / UsedBits` | 根/来源 | 1,197 | fix 1,181 / AliasAnalysis-semantics 16 |
| `used-bits#0 / UsedBits` | 根/来源＋类型 | 423 | fix 423 |
| `used-bits#0 / UsedBits` | 类型 | 374 | fix 374 |
| `dead-code-elim#0 / RemoveDeadNodes0` | 前驱/赋值 | 313 | fix 313 |
| `split-nodes#0 / SplitNodes` | 根/来源＋类型＋前驱/赋值 | 216 | fix 216 |
| `used-bits#0 / UsedBits` | 根/来源＋前驱/赋值 | 96 | fix 96 |
| `hier-flatten#0 / Init` | 根/来源＋前驱/赋值 | 13 | fix 13 |
| `dead-code-elim#0 / RemoveDeadNodes0` | 根/来源 | 12 | fix 12 |
| `hier-flatten#0 / Init` | 根/来源＋类型＋前驱/赋值 | 6 | fix 6 |
| `expr-opt#0 / ExprOpt` | 根/来源＋前驱/赋值 | 5 | fix 5 |
| `hier-flatten#0 / Init` | 前驱/赋值 | 2 | fix 2 |
| `split-static-array#0 / InferAllWidth` | 根/来源＋类型 | 1 | fix 1 |

`fix` 按数量排：`split-static-array` 131,530（成员具名 RHS 及索引），第三次 DCE 48,061
（活跃单边名的实际消费），`split-nodes` 43,093（位段与引用），B0 40,852（单元素端口和条件根），
第一次 DCE 30,468，`constant-analysis` 5,081，第二次 DCE 2,382，`used-bits` 2,074，
`expr-opt` 5。先用小例区分首界与持续到 R0 的差异，再修实际产生形状的 pass。
历史 12,756 个单元素数组差异均先见于 B0；19,157 个缺最终来源的行中 12,114 个来源先在 P3
单边出现；旧 11,448 个误退名已不在本轮 cohort；当前 5,363 个可比较的常量标记差异中
5,359 个先见于 Q1。共享锚点分属前缀与 R1 迁移两类。计数、样本和核验路径见
`ptmp/firrtl-ingest/F34/culprit-ledger/{f34-5c-report.md,ledger.tsv,summary.json}`。

`named-rhs` 的 48,208 个漏退中，有 7,104 个引用了同一组 30 个未拆开的两位源。原生记录
显示，`split-static-array` 将实际消费改接到共享物理投影，具名来源留在随后被 DCE 清除的
赋值上。香山样本在 `ptmp/firrtl-ingest/F34/upstream-array-selection-audit/xiangshan-v2/`，
复现用例 `member_fanout_from_state.fir` 和对照库存位于 `ptmp/firrtl-ingest/F34/retained-root-audit/`。

常量转发实验达到 R1 98.1022%，相对 `named-rhs` 修正 1,031 个漏退，同时新增 4,288 个
误退。按 §8.2 的双向指标，该结果未通过验收。对账记录位于
`ptmp/firrtl-ingest/F34/constant-forwarding/comparison.json`。

2026-11-21。F34.5d `split-static-array`：独立成员 RHS 与整值回拼使小例 B1 6→1，香山 P0 新增 GSIM 单边 90,272、GRH 单边 485，门失败回退，131,530 行待定 freeze，试验 R0 99.62041509%、R1 未跑，见 `culprit-ledger/f34-5d/split-static-array/repack/full/prefix/prefix-gate.json`。

2026-11-21。F34.5d 第三次 DCE：三个 AXI 恒真断言样本在 GSIM 由旧 `prev` 保活，值核对通过，样本待定 freeze，48,061 行未改，R0/R1 沿用冻结值，见 `culprit-ledger/f34-5d/dead-code-elim-2/`。

2026-11-21。F34.5d `split-nodes`：有原生槽证据的透明赋值后整段切片直接使用子段，43,093→39,727，P0/P4/R0 单边集全同，R0 99.57562590%、R1 84.92053454%，A 539,288、B 11,769，见 `culprit-ledger/f34-5d/split-nodes/full/`。

2026-11-21。F34.5d B0：单元素端口形状与条件根在 FIRRTL lowering 已不同，动态越界值策略与 GSIM 去轴行为不同，小例 64 组值通过，40,852 行未改，R0/R1 沿用已验收值，见 `culprit-ledger/f34-5d/ingest-flatten/`。

2026-11-21。F34.5d 第一次 DCE：小例复现无消费的外部输出根差异，32 组值通过，该样本待定 freeze；队列消费与零位宽 memory 端点仍待复现，30,468 行未改，R0/R1 沿用已验收值，见 `culprit-ledger/f34-5d/dead-code-elim-0/`。

2026-11-21。F34.5d ConstantAnalysis：小例复现依赖复位值的 AND/Mux 折叠，首拍前零初值反例及 32 组值通过，样本待定 freeze，5,081 行未改，R0/R1 沿用已验收值，见 `culprit-ledger/f34-5d/constant-analysis/`。

2026-11-21。F34.5d 第二次 DCE：原生边确认符号扩展和 RAT mask 有消费，小例两端均保留活扩展、删除截断对照的死高位，128 组值通过，2,382 行未改，R0/R1 沿用已验收值，见 `culprit-ledger/f34-5d/dead-code-elim-1/`。

2026-11-21。F34.5d UsedBits：窄化 concat 原槽转发使 P2 2,074→1,846，三处前缀单边集全同，试验 R0 99.57562590%、R1 84.94092413%，B 11,769→11,811，回退并列为待定 freeze，见 `culprit-ledger/f34-5d/used-bits/full/`。

2026-11-21。F34.5d ExprOpt：按两臂具名引用保留 Mux，小例 P1 2→0，香山 P4 新增 GRH 单边 34、GSIM 单边 8，R0 降至 99.57529831%、R1 未跑。回退并列为待定 freeze，5 行未改，见 `culprit-ledger/f34-5d/expr-opt/owner-evidence/full/prefix/`。

2026-11-22。F34.5e 香山前缀复测通过。组合环修复保留原生位投影和单比特具名数组读取的区别，恢复上一候选在第一次 DCE 后丢失的 40 个名字。P0/P4/R0 同名率分别为 99.68662846%、99.62574820%、99.57562590%，三个边界均无新增单边名。R0 名字和 ID 与已验收 F34.5d 库存完全一致，连接和端点有改动。

同一冻结包的 R1 唯一同名率为 90.90454700%（3,120,904 / 3,433,166），双向退役判定一致率为 93.24413659%。A 为 297,289，B 为 13,078，分别有 148,105 和 3,969 个节点仍缺首次分歧归因。相对已验收 F34.5d，A 减少 241,999，B 增加 1,309。GRH 原生迁移 trace 与快照退役 ID 完全一致。F34.5e 的 99.6% 门、B 不增加门和归因门均待通过。证据位于 `culprit-ledger/f34-5e/member-rhs/preserve-original-bit-projection/full/`。

寄存器读取的语义成员可以同时属于状态源与普通消费者。AliasAnalysis 在读取定义实际 RHS，且源节点拥有该读口及其结果锚点时，按具名引用判定消费者。香山 R0 库存仍与已验收版本完全一致，R1 唯一同名率为 90.95368838%（3,120,893 / 3,431,299），双向退役判定一致率为 93.28268654%。A 降至 295,507，B 增至 13,089。新增的 11 个误退都在 DebugModule，GSIM 将对应的 `programBufferMem` 消费者折叠为常量，GRH 保留其状态读取。候选未通过 R1 退出门。证据见 `culprit-ledger/f34-5e/member-rhs/state-read-alias/full/`。

`track-bit-projection` 和 `state-array-bit-projection` 均通过香山 P0、P4、R0 库存门，
R0 名称与 ID 和 F34.5d 完全一致。前者在循环修复前记录多位数组读取的原始单比特投影，
R1 同名率 90.95145967%，双向退役判定一致率 93.28399258%，A 为 295,607，B 为 12,929。
后者在静态数组拆分改接此类投影时保留切片，消除 4,594 个误退且 B 无新增项，
也新增 18,688 个漏退。R1 同名率为 90.47151519%（3,125,647 / 3,454,841），
双向退役判定一致率为 92.97720372%，A 为 314,295，B 为 8,335。误退数量通过上限
11,769，仍有 170,571 项待定位首次分歧，R1 同名率低于 99.6%。证据见
`culprit-ledger/f34-5e/member-rhs/{track-bit-projection,state-array-bit-projection}/full/`。

Decoder 缩减例的两个目标在 B1 都锚定到赋值，但赋值操作数同时是多个 Node 的锚点。
`indexed-source-read` 候选在成员化期间记下原始常量下标读取，在物理改接后用原始
消费槽和实际成员锚点确认来源。两个目标的 R0 签名与 GSIM 一致，R1 同时退役。
B1 和 R0 各通过 32,768 组独立输入值检查。证据见
`culprit-ledger/f34-5e/residual-prefix/decoder-member/indexed-source-read/`。

该候选的香山 R0 同名率为 99.60022418%，P0、P4、R0 各新增相同的 212 个 GSIM
单边名，前缀门失败，未采 R1。IssueQueue 缩减例复现其中 16 个名称在第一次 DCE 后
消失。新增的精确消费槽引用的是 `currentStatus`，对应值由 `kRegisterReadPort` 定义，
也锚定公开的 `commonOut` 成员。只撤销这 16 个共享读值上的 26 条新增边，可在 P0
恢复全部 16 个名称。改进候选 `indexed-source-comb` 要求实际赋值操作数由纯操作定义，
小例恢复这 16 个名称，同时保留两条 Decoder 修正，B1 和 R0 各通过 32,768 组值检查。
香山复测证据位于 `culprit-ledger/f34-5e/residual-prefix/decoder-member/indexed-source-comb/`。

2026-11-22。`array-member-bit-fix` 在 `split-static-array` 中把单比特切片接到具名数组成员，
让 `split-nodes` 保留成员与位索引的对应关系。香山全量对账使用与工作树源码一致的冻结包。
相对上一候选 `indexed-source-comb`，R1 唯一同名率提高 0.6954 个百分点，漏退减少 25,841，
误退增加 400。

| 指标 | `indexed-source-comb` | `array-member-bit-fix` |
| --- | ---: | ---: |
| R0 唯一同名率 | 99.59950509% | 99.60850432%（4,595,781 / 4,613,844） |
| R1 唯一同名率 | 91.07487836% | 91.77030328%（3,126,851 / 3,407,258） |
| R0 同名节点的退役判定一致率 | 93.45046984% | 94.00648116%（4,320,332 / 4,595,781） |
| A，GRH 保留而 GSIM 退役 | 292,475 | 266,634 |
| B，GRH 退役而 GSIM 保留 | 8,415 | 8,815 |
| C / D，R0 单边名称 | 13,825 / 901,179 | 13,773 / 899,514 |

在上一候选的 160,702 个静态位切片漏退节点中，25,823 个现已在 R0 获得与 GSIM 相同的
右值签名并在 R1 退役，其中 18,688 个来自 IssueQueue `fuTypeVec`。新增的 400 个误退也在
IssueQueue。GRH 将对应节点迁移到 `fuTypeVec` 的单比特片段，GSIM 在 R0 保留
`OP_BITS_NOSHIFT`，对应具名节点在 R1 仍在库存内。

AliasAnalysis 耗时 12.170 秒。R0、R1 的 SemanticTree 校验均为零错误，1,206,586 个
退役 ID 与快照差集完全一致。`make test_f34_passes` 通过 5/5。R0 同名率和 B 数量通过
对应验收门。R1 仍低于 99.6%，R0 名称和 ID 与 F34.5d 冻结库存存在差异。
全量对账、采集与测试证据见
`ptmp/firrtl-ingest/F34/culprit-ledger/f34-5e/array-member-bit-fix/full-alignment/`，
静态位切片的逐名对照见同级 `static-slice-cohort/`。

## 逐 pass Node trace 采集

`make capture_f34_pass_trace` 使用 FIRRTL 生产流水线。`F34_ENGINE=grh`
使用当前安装的 Wolvrix，也可用 `F34_PASS_TRACE_PACKAGE` 指定包含身份记录的包。
`F34_ENGINE=gsim` 使用 `F34_GSIM_BINARY` 指定的 trace 版 GSIM，可通过
`make f34_gsim_build` 构建。两端使用同一 `F34_INPUT` 和 `F34_MANIFEST`，
各自写入 `F34_PASS_TRACE_OUTPUT`。默认采集到第四次 DCE，传入
`F34_PASS_TRACE_ARGS=--stop-before-final-dce` 可停在 CommonExpr 后。

每个 pass 的目录包含 `before.nodes.tsv`、`after.nodes.tsv`、相应的连接清单和
`evolution.tsv`。设置 `F34_PASS_TRACE_ARGS=--verify-replay` 可逐包重放并写出
`verification.json`。GRH 在 `xmr-resolve` 按模块记录，`hier-flatten` 还
导出参与变换的模块快照和顶图的 `relocations.tsv`。GRH 与 GSIM 的 AliasAnalysis
同时导出原生别名迁移 JSONL。GSIM 的表达式改写等事件记录在 `native-mutations.jsonl`，
位段拆分和 CSE 的 Node 谱系也进入 `evolution.tsv`。GRH 的 CSE 谱系记录共享值所关联
的 Node 名称，删除仍由后续 DCE 记录。首份 Node 清单来自 ingest／`Init`。
