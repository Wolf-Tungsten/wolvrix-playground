# 30 R-B lane 重向量化 pass 设计草案（2026-08-01）

承接 doc 29 的路线重锚。设计目标：把 firtool 打平的逐 lane 标量寄存器及其
同构写锥合并回宽向量形态，op 数向 gsim 的数组级表示看齐。默认关开关。

（覆盖面决策门数据见 §8，出来后本文定稿。）

## 1. pass 定位

- 名称：`lane-aggregate`（transform pass，`lib/transform/lane_aggregate.cpp`）。
- 流水位置：hier-flatten 之后、reg-to-mem 之前。被本 pass 合并的组不再需要
  reg-to-mem 处理；合不了的组维持原样走 reg-to-mem。
- 输入图形态假设（已实测）：每 lane 寄存器恰好 1 个写口（全图 211,641 个
  register 全部单写口）；lane 写锥结构同构、仅常量与 lane 寄存器读不同。

## 2. 分组

- 名字模式：`..._<idx>_...` 第一个数字段为 lane 下标（firtool 打平命名），
  组 = 前缀+后缀相同、下标密集（0..N-1，允许少量空洞）、N ≥ 8、位宽一致。
- 排除：带 init/readmem 的寄存器、被 XMR/层级引用、声明符号保留冲突
  （simplify 的 keep_declared_symbols 语义与 reg-to-mem 相同处理）。

## 3. 同构签名

对每 lane 的 (updateCond 锥, data 锥) 算结构签名：

- op kind 树递归哈希；
- `kConstant` → 抽象为 `C`，但记录每 lane 的常量值表（§5 参数化用）；
- 叶分两类：
  - **lane 参数叶**：本组 lane i 的寄存器读，或同下标系统的兄弟组 lane i
    寄存器读（跨组耦合，见 §6）；
  - **共享叶**：所有 lane 引用同一个值（enqPtr、全局使能等）——必须逐
    lane 完全相同（同一 ValueId），否则不同构。
- 签名相同才合并；合并 lane 数 < 阈值（如 8）的组放弃。

## 4. 合并后形态（写侧）

每组合并为一个 N*W 位宽 kRegister + 单写口：

```
condVec[N-1:0]   = 合并后的 cond 锥（每 lane 的 1-bit cond 变宽向量）
dataVec[N*W-1:0] = 合并后的 data 锥
mask             = 每 lane W 个 cond 位的复制扩展（kReplicate/按位扩展）
write: updateCond = |condVec（任意 lane 写）∪ reset 条件
       data       = (reg & ~mask) | (dataVec & mask)
```

- reset：各 lane reset 值拼接成宽 reset 常量；reset 条件不一致时用 mask
  表达（reset 也是一次 masked 写）。
- lane 0 特化（wflags 实测 351/1 分裂）：多数派合并，特化 lane 保留原
  标量寄存器（牺牲一个 lane，不影响正确性）。

## 5. 常量 lane 参数化

合并锥时，签名里 `C` 位置的每 lane 常量 c_i：

- c_i == i（或 i 的仿射）：直接用 lane 下标物化（常量向量 + slice，或对
  `ptr==i` 形态直接 onehot：`shl(1, ptr)`）；
- 其他情况：把 N 个常量打包成常量表（N×cwidth 的 kConstant）+
  静态/动态 slice 取出——仍是每组一次成本，不是每 lane 一次。

**实证**（wflags 组，E1 图）：lane 间唯一差异是 2 处 kConstant，lane1/2/3
分别为 `9'd1`/`9'd2`/`9'd3`——c_i==i 精确成立（`enqPtr==i` 地址常量）。
lane1 vs lane2/3 平行走锥其余 0 差异（kind/arity/叶全同）。

**私有锥的 compute 口径**：wflags lane 私有 35 ops 中 27 个 compute
（kAnd 17/kOr 7/kNot/kReduceOr/kConcat）+ 8 个 kRegisterReadPort（跨组
lane 读，合并后变 kSliceStatic）。组节省换算 compute 口径 ≈ 77%。

## 6. 跨组耦合

data/cond 锥读了兄弟组的 lane i（如 robEntries 的 data 锥读 robState_i）：
要求兄弟组同下标系统且也参与合并；耦合组一并处理。兄弟组不合并则本组
放弃（lane 参数叶无法物化）。

## 7. 读侧（Phase 2，I1 的 22.5 万）

- 逐 lane 散读：`kRegisterReadPort(lane_i)` → `kSliceStatic(read(wide), i*W, W)`，
  一对一替换，数量持平（必须先做，写侧合并的代价为 0）。
- 选通树（I1 的大头）：`mux(ptr==0, lane0, mux(ptr==1, lane1, ...))` 链与
  `or(and(replicate(eq(ptr,i)), lane_i), ...)` 树 → `kSliceDynamic(read(wide),
  ptr*W, W)`。独立 matcher，作为 pass 第二阶段；与 onehot-to-mux 的关系：
  本 matcher 直接产 slice_dynamic，不再需要中间 mux 形态。
- 资产：寄存器读口的正确映射在 `/tmp/grh_read_ports.json`（RRP 的
  regSymbol→out 值，21 万条；之前 pickle 的 attrs 存的是 out 值不是
  regSymbol，python 侧 join 要用这个文件）。
- Rob uopNum 抽查：读侧几乎没有跨 lane 汇聚（352 lane 仅 1 个 8-lane
  kConcat，疑为 debug 打包）——Rob 类数组的读是逐 lane 散读，I1 选通树
  集中在 doc 22 的 RenameBuffer/DataModule/MSHR 等模块，Phase 2 估算
  沿用 doc 22 的 ~22.5 万，go/no-go 在 Phase 1 落地后定。
- **全图读侧估算**（`exp/tools/p0_lane_readside.py`，数据集
  `exp/dataset/lane_readside_v1_20260801.json`）：2,210 组合计
  **~315,300 ops**（上界）。注意口径膨胀：检测只要求"合并多 lane 的
  mux/or/and 树"，未校验 select-guard 形态——如 delayedWriteBack
  valid_last 的 22,911-op 树实为 24-lane 归约而非选通，不能换
  slice_dynamic。真实可选通子集需加 guard 形态校验（mux(eq(ptr,i)) /
  and(onehot_i)），估算打 5~7 折看待（~16~22 万），与 doc 22 I1 的
  ~22.5 万吻合。

## 8. 覆盖面决策门：**通过**（2026-08-01，v4 精确口径）

分析脚本：`topo-partition-proj/exp/tools/p0_lane_isomorphism.py`（v4 两阶段：
全局哈希 + lane 私有锥签名）。数据：
`topo-partition-proj/exp/dataset/lane_iso_v4_20260801.json`。

- **全图精确汇总：1,811 个 lane 组可合并，合计省 901,408 ops（≥40 万
  门槛的 2.25 倍）**。写侧私有锥口径，只低估不高估（边界规则对锥内
  扇出有假阴性）。
- compute 口径换算 ≈ 77%（wflags 实测），即 ~69 万 compute ops；
  另有 (merged−1) 个寄存器+写口的状态位缩减（不计入 compute）。
- Top 组形态一致：Rob robEntries 各字段 351/352 lane 合并（lane 0 reset
  特化，sigs=2），私有锥 35~101 ops/lane。
- 单组验证：wflags v4=12,250 vs 手工精确 12,285（差 lane 0 口径），吻合。

实现注意（v4 分析遗留）：
- 签名只含 (cond, data) 两锥，写口 event/reset 结构未比对——C++ pass
  必须显式校验各 lane event 集合一致（或按 reset 特化剥离 lane）。
- 哈希相等不等于结构相等：C++ pass 在改写前必须做**精确结构比对**
  （常量除外），哈希只用于分组加速。
- **读侧编码**（python 分析实测）：寄存器读走 kRegisterReadPort（全图
  211,642 个 ≈ 每寄存器一个），其 regSymbol/attr 引用的是寄存器的
  **读值名**（常为 `_val_N`），与寄存器 op 的符号名（分层路径名）不是
  同一字符串——python 侧按符号名 join 会漏（v4 因此低估了含 lane 相对
  读的组，901,408 是下界）。C++ pass 用 Graph API 按 op/attr 解析，
  不受此影响，但单测必须覆盖"读值名 ≠ 寄存器符号名"的情形。
- **真实形态参照**（doc 27 §3/§4，单测应覆盖）：
  - A 类写 cond cone = **8 dispatch 口的 or-of-ands**（每项恰一个
    `enqPtr_j==i`，j=0..7 8 个不同地址信号）——同构签名的典型形态；
  - `valid` 字段全 lane 带**异步复位写口**（352/352）——event 集合
    一致的正当情形，宽寄存器的 reset 必须正确表达；
  - 读侧 55% 是 **concat 并行消费**（全 lane 打包做 CAM 式匹配）——
    宽寄存器合并后 concat(slice_0..slice_N) 应塌缩成对宽寄存器的直接
    引用（顺序一致时）或一个宽 slice，这是收益不是代价；
  - lane 0 reset 特化（351/352 分裂）在多个字段出现。
- **位宽核查**（v4 Top-30 组实测）：1-bit×9、64-bit×6、2/5/6/7/8/9/32/36/48/50
  其余；最大 lane 宽 64——最宽合并寄存器 352×64 = 22,528 位，GRH 宽值
  常规范围，无病态超宽组。

## 9. 与现有 pass 的关系

- comb-lane-pack：它打包同构 comb 树但寄存器侧不动；lane-aggregate 应先
  于它运行（先把寄存器变宽，comb 树随之变宽，pack 的目标形态自然出现，
  甚至部分替代 pack 的工作）。需要在实现时验证两者的先后与重叠。
- reg-to-mem：lane-aggregate 之后，被合并组不再出现于其 discovery；
  未合并组照常。
- simplify（2state）：合并产物的 mask/replicate/slice 由它常规清理。

## 9. 验证策略

- 单测（`tests/transform/lane_aggregate.cpp`）：构造 N lane 同构组（含
  `ptr==i` 常量参数化、跨组耦合、lane 0 特化、非密集下标拒绝、共享叶
  不一致拒绝）验证合并形态与拒绝路径。
- 全香山：stats 对账（决策门 ≥40 万）+ 50k difftest + ctest 无新增失败。

## 10. 风险

- firtool 打平后 CSE 已把部分 lane 无关子表达式共享（cond cone 144 中
  可能有共享前缀），合并后这部分不省反可能略增——净收益以全香山实测
  为准，估算打 5 折。
- 宽向量的 masked 写在 AM 调度/emit 的代价形态与逐 lane 不同（更少
  detector、更宽指令），runtime 影响单独评估（本目标只看 op 数）。
