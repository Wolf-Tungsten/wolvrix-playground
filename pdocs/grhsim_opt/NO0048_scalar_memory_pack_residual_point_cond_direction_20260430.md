# NO0048 Scalar Memory Pack 残余案例换方向结论

## 1. 结论

`scalar-memory-pack` 在 v7 之后，继续扩 `fill` 侧已经没有明显收益。

直接证据：

- v7 回放结果：`candidate_members=66548`
- v8 在加入“多 fill arm”解析后，回放结果仍然是 `candidate_members=66548`
- `mixed fill/point` residual 仍然是 `20 / 1512`

对应产物见：

- [build/xs/scalar_memory_pack_replay_from_json_20260430_v7_lowered_wide_slice/summary.json](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/scalar_memory_pack_replay_from_json_20260430_v7_lowered_wide_slice/summary.json)
- [build/xs/scalar_memory_pack_replay_from_json_20260430_v8_multi_fill/summary.json](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/scalar_memory_pack_replay_from_json_20260430_v8_multi_fill/summary.json)

因此下一跳不应继续钻 `fill` parser，而应改成扩展 `point cond` 的识别域。

## 2. 残余样本分布

### 2.1 `mixed fill/point`

样本高度集中在两个模块：

- `ICacheWayLookup.sv`
  - `_op_165959`
  - `_op_165993`
  - `_op_166027`
  - `_op_166061`
- `VecExcpDataMergeModule.sv`
  - `_op_8512620`

### 2.2 `multiple point-update branches`

样本集中在：

- `VTypeBuffer.sv`
  - `_op_2299558`
  - `_op_2299626`
  - `_op_2299694`
  - 其余同族点位

这说明剩余问题已经不是分散的随机边角，而是两三类稳定结构。

## 3. 为什么 `fill` 方向不再是主矛盾

为了验证这一点，已经新增一个局部单测，支持：

- `point ? pointData : (fillA ? fillAData : fillBData)`

并且单测已通过：

- [wolvrix/tests/transform/test_scalar_memory_pack.cpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/tests/transform/test_scalar_memory_pack.cpp)

但真实回放没有任何增量，说明当前残余样本卡点不是：

- “false arm 里有多个 fill 候选”

而是更早的一步：

- `point cond` 自身未被识别成“member-local 单点更新条件”

## 4. `ICacheWayLookup` 残余的真实形态

以 `_op_166252` 为例：

- 写条件：`_val_168452 = _val_168407 OR _val_168451`
- 数据：`_val_168456 = mux(_val_168451, missResp, _val_168454)`
- 其中 `_val_168454 = mux(_val_168406, prefetchWrite, default)`

关键点不在 `fill`，而在两个“点更新条件”形态不同：

- `_val_168406`
  - 可继续追到 `kEq`
  - 仍接近当前 pass 可识别的“地址等于常数”模式
- `_val_168451`
  - 是 `kLogicAnd(_val_168419, _val_168450)`
  - 其中 `_val_168419 = wrBase & !_val_168405`
  - 即它带有“前一优先级条件取反”的痕迹

这类条件本质上不是：

- `base & (addr == const)`

而更像：

- `base & !previous_hit & member_local_match`

也就是“优先级串行 point branch”。

当前 `parsePointCond(...)` 只接受：

- `Eq(addr, const)`
- `ReduceAnd(addr)` 这类全 1 命中

所以它不会把这类优先级链识别成 point update。

## 5. `VTypeBuffer` 残余的真实形态

以 `_op_2304293` 为例：

- 写条件是多个 `or` 链
- 每个分支像：
  - `needAllocVec_6 & ...`
  - `needAllocVec_7 & ...`
- 数据侧也是多个对应 lane 的 `or` / `and` 组合

这里的问题更明显：它根本不是“动态地址 + 常数比较”的 memory-like 写法，而是：

- 每个 member 自己一根 lane-local enable
- cluster 整体形成一组并行的固定槽位更新

也就是说，这类 residual 更像：

- `fixed-lane update cluster`

而不是：

- `addr == i` 风格的 point write

## 6. 下一跳应当做什么

### 6.1 方向 A：优先级 point-chain 识别

优先处理 `ICacheWayLookup` / `VecExcpDataMergeModule` 这类。

建议目标：

- 允许 `point cond` 含有对前序命中条件的否定项
- 允许从数据 mux 的优先级结构反推 point branch 顺序

可接受的第一版保守策略：

- 只在同一 cluster 内，
- 发现 `cond = base & !prev_cond & local_match`
- 且数据树是同序的 nested mux
- 才恢复为多个 ordered point writes

这比继续扩 `fill` 更贴近真实 residual。

### 6.2 方向 B：cluster-level fixed-lane enable 识别

优先处理 `VTypeBuffer` 这类。

建议目标：

- 不再要求 `parsePointCond(...)` 必须产出 `addr`
- 允许“member index 由 cluster 内 enable 家族直接给出”

一个可落地的保守版本是：

- 对同一 cluster 的所有写口，
- 收集每个 member 的 member-local enable 信号
- 若这些信号能按索引一一对应，且数据侧也一一对应
- 则直接把 `constIndex` 绑定到 cluster member index

这本质上是从“单写口局部匹配”切到“cluster 全局归纳”。

## 7. 推荐顺序

不建议再在当前分支上继续堆 `fill` 相关规则。

推荐顺序：

1. 先做 `ICacheWayLookup` 这类优先级 point-chain 识别
2. 若收益仍有限，再做 `VTypeBuffer` 这类 fixed-lane enable 识别

原因：

- `ICacheWayLookup` 这类仍然比较接近现有 memory-pack 心智模型
- `VTypeBuffer` 已经开始偏向“按槽位寄存器簇”的另一类抽象，复杂度更高

## 8. 当前状态

代码状态：

- “多 fill arm” 局部能力已经实现并有单测覆盖
- 但真实设计无增量

因此这部分可以保留，但不应继续作为主攻方向。
