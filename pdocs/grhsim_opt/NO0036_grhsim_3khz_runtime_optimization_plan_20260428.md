# NO0036 GrhSIM 3kHz Runtime Optimization Plan（2026-04-28）

> 归档编号：`NO0036`。目录顺序见 [`README.md`](./README.md)。

这份文档把 [`NO0035`](./NO0035_grhsim_compute_commit_perf_breakdown_3khz_gap_20260428.md) 的结论收敛成一份实施计划。目标不是继续做零散优化，而是围绕 `3 kHz` 目标，把 runtime 降本拆成几条可独立推进、可量化验收的主线。

## 1. 目标与现状

当前 `XiangShan coremark 50k` 观测结果：

- `guest cycles/s = 77.49`
- `host us / guest cycle = 12904.34`
- `host us / eval(avg) = 6452.30`
- sampled `compute = 816.3 us / eval`
- sampled `commit = 807.9 us / eval`
- sampled `eval total = 2516.0 us / eval`

`3 kHz` 目标对应预算：

- `333.33 us / guest cycle`
- 按当前约 `2 eval / cycle` 粗算，约 `166.67 us / eval`

所以当前差距不是百分比级，而是数量级：

- 整机平均约落后 `38.7x`
- 仅 sampled `compute + commit` 也仍落后约 `9.75x`

## 2. 已知瓶颈

基于 [`NO0035`](./NO0035_grhsim_compute_commit_perf_breakdown_3khz_gap_20260428.md)，当前可以把瓶颈分成三层：

1. `compute` 慢在正文。

- 热 compute batch 稳定重复出现。
- 单看 sampled compute body，已经达到 `816.3 us / eval`。

2. `commit` 慢在 phase 框架。

- sampled commit batch body 只有约 `191 us / eval`。
- round 级 `commit_us` 却有 `807.9 us / eval`。
- 说明大头不是 sink body，而是全局扫描、派发和大量 tiny batch 调度。

3. `eval` 之外还有大量整机成本。

- sampled `eval total = 2516 us / eval`
- 但整机 `host avg = 6452 us / eval`
- 还有约 `3936 us / eval` 在 `eval()` 之外，主要来自 runtime harness、difftest、外层循环和当前构建口径下的其他成本。

因此，后续路线不能只盯 `grhsim eval()` 内部，也不能只盯 `commit`。

## 3. 实施原则

这轮优化按四条原则推进：

1. 优先改“大头框架”，不优先做小补丁。

- `NO0034` 已经说明，sink 激活局部收窄这类微优化收益太小。

2. 优先改首轮主路径。

- `round 2` 很轻，不应作为第一优先级。

3. 优先把 phase 成本和整机成本分开计量。

- traced `eval` 与 wall-clock 不是同一口径，后续所有对比都必须保持口径一致。

4. 每个阶段都要有独立验收线。

- 不接受“做完一大坨再看总时间”的推进方式。

## 4. 总体路线

建议把后续工作拆成四条主线，按顺序推进：

1. `Phase A`：把测量口径和 baseline 固化。
2. `Phase B`：重写 `commit` phase 驱动方式。
3. `Phase C`：针对 compute 热 batch 做正文降本。
4. `Phase D`：清理 `eval` 外部的整机成本。

其中：

- `Phase B` 和 `Phase C` 是 runtime 主战场。
- `Phase D` 决定最后能不能真正接近 `3 kHz`。

## 5. Phase A：测量与基线固化

### 5.1 目标

建立三套稳定口径，避免后续优化被 trace 噪声和测试口径变化污染。

### 5.2 工作项

1. 固化现有 perf plumbing。

- 保留 `WOLVRIX_GRHSIM_PERF=1`
- 保留 `GRHSIM_TRACE_EVAL`
- 保留 `GRHSIM_TRACE_EVAL_EVERY`
- 保留 round 级和 batch 级 trace

2. 把 perf trace 与 wall-clock 分开使用。

- `trace build` 只用于结构拆解
- `non-trace build` 用于真实速度回归

3. 新增轻量级非 trace 统计。

- `eval_count`
- `round1_count`
- `round2_count`
- `commit_batch_exec_count`
- `compute_batch_exec_count`
- `touched_shadow_count`
- `touched_write_count`

这些统计必须能在不开 `fprintf` 的情况下采集。

4. 给 emu 外围加阶段计时。

- `emu outer loop`
- `grhsim eval()`
- `difftest step`
- `device / memory / other runtime`

### 5.3 验收

必须同时得到三组基线：

1. `trace build` 下的 `eval round / eval batch` 结构画像
2. `non-trace build` 下的真实 `50k` 速度
3. 整机 wall-clock 的大类分项占比

如果 `eval()` 之外的时间占比仍然很大，后续不能只做 emitter/runtime 内部优化。

## 6. Phase B：Commit Phase 重写

### 6.1 目标

把 `commit` 从“active-word 全局扫 + tiny batch 派发”改成“touched-set 驱动”，优先消掉框架成本。

### 6.2 设计方向

当前 `commit` 的问题不是 body 太重，而是：

- 扫描范围太大
- 触发的 batch 太碎
- 调度粒度太细

因此新方案必须避免“每轮都把 commit active word/batch 表扫一遍”。

建议主方向：

1. 由 `compute` 直接生成 commit touched-set。

- 每个 write / sink 激活不再只落到 `supernode_active_curr_`
- 同时登记到更紧凑的 touched queue / bitset

2. `commit` 只遍历 touched entries。

- 直接遍历 touched `state shadow`
- 直接遍历 touched `memory write`
- 或直接遍历 touched `commit batch`

3. `commit` 完成后再产生下一轮 compute touched-set。

- `reader` 激活也改成 touched-set 驱动
- 尽量避免回到全局 active-word sweep

### 6.3 推荐实现顺序

1. 先做最小闭环版本。

- 保持现有 `commit batch` 不变
- 只改变“谁驱动 commit batch 执行”
- 从 `active-word sweep` 改成 `touched commit batch list`

2. 再做第二层收敛。

- 把多个 tiny commit batch 合并为更粗的 touched unit
- 优先按共享 writer / shared fanout / contiguous state region 合并

3. 最后再决定是否要进一步下沉到“按 touched write entry 直接 commit”，完全绕开部分 batch dispatch。

### 6.4 风险

1. touched-set 去重本身可能引入新成本。

- 如果队列去重太重，会把扫描成本换成登记成本。

2. memory write 的语义更复杂。

- 需要区分 addr/data/mask 的最终合成时机。

3. reader 激活语义不能退化。

- 仍然必须保持“只有 state 真变化才激活 reader”。

### 6.5 验收

第一阶段只看 `commit`：

- sampled `commit_us` 从当前 `~808 us / eval` 压到 `<= 250 us / eval`
- 同时 sampled commit body 不显著变重
- `50k` 功能结果保持一致

如果连 `250 us / eval` 都压不下来，说明 touched-set 设计还不够激进。

## 7. Phase C：Compute 热 batch 正文降本

### 7.1 目标

直接降低 compute 热路径正文成本，而不是继续把时间花在低价值 scan/dispatch 微调上。

### 7.2 工作方法

基于 `NO0035` 的热点 batch，先盯最稳定的重 batch：

- `669`
- `262`
- `453`
- `332`
- `385`

每个热点 batch 都要做单独剖析，至少回答四个问题：

1. batch 里最重的是哪类语句。
2. 是否存在重复 load / store / mask 组合。
3. 是否存在不必要的宽值 helper / words helper 往返。
4. 是否存在过大的 mixed-shape batch，导致局部性和编译结果都变差。

### 7.3 推荐优化方向

1. 拆热点 batch，而不是全局继续调 batch 数。

- 当前热点说明“少数 batch 很重”
- 不应先全局改 `targetBatchCount`
- 应优先支持 hotspot-aware split

2. 为热点 batch 引入专门的 shape-aware 拆分规则。

- 宽值密集段单独成块
- memory/state 访问密集段单独成块
- side-effect guard 密集段单独成块

3. 继续削减正文内部重复访问。

- 合并重复索引
- 缩短 helper 链
- 降低宽值 mask / merge 的中间量

4. 保持 phase purity，不把 commit 逻辑重新混回 compute。

### 7.4 验收

第二阶段只看 compute：

- sampled `compute batch_us` 从 `~816 us / eval` 压到 `<= 250 us / eval`
- 热点 top-5 batch 的累计时间至少下降 `50%`
- 不接受通过增加 `commit` 时间换取 compute 表面下降

## 8. Phase D：整机成本清理

## 增量更新 2026-04-28

[`NO0037`](./NO0037_grhsim_dynamic_active_word_queue_failed_experiment_20260428.md) 已对“动态 active-word 队列替代固定扫描”做过一次直接实验，结果是：

- `1000-cycle` smoke 明显回退。
- `XiangShan coremark 50k` 发生功能错误。

因此，本计划里凡是隐含“全量 active-word 扫描是主瓶颈”的假设，都应视为已被证伪。后续不再继续推进这类动态 active-word 队列方向，优化重点应放回：

- 真正重的 `compute` batch 正文。
- `commit` phase 中除 active-word 固定扫描之外的其它框架成本。
- `eval()` 外部整机 runtime 成本。

### 8.1 目标

解决 `eval()` 外部仍有约 `3936 us / eval` 的整机成本，避免 runtime 内部优化被外围吞掉。

### 8.2 重点排查对象

1. difftest

- 每轮交互次数
- 数据搬运大小
- 不必要的同步点

2. emu 外层循环

- `eval` 调度频率
- 每 guest cycle 的固定外围工作

3. memory / device 模拟

- RAM 路径
- flash / uart / 其他设备路径

4. runtime 层通用逻辑

- 输入发布
- 输出刷新
- 波形 / debug 相关残留

### 8.3 验收

在 `Phase B + C` 做完后，整机平均仍需继续压到：

- `host us / eval <= 500 us`

这是进入最终 `3 kHz` 冲刺前的中间线。

如果 `host us / eval` 仍显著高于 `500 us`，说明外围成本仍未被真正拆掉。

## 9. 里程碑与预算

建议用三道中间线管理节奏：

### Milestone 1

- `commit <= 250 us / eval`
- `compute` 暂不设硬线
- 目标：先证明 phase 框架可以被大幅压缩

### Milestone 2

- `commit <= 250 us / eval`
- `compute <= 250 us / eval`
- `sampled eval total <= 800 us / eval`

目标：证明 `eval()` 内主成本已经被真正打穿。

### Milestone 3

- `host us / eval <= 200 us`
- `host us / guest cycle <= 400 us`

目标：接近并最终跨过 `3 kHz` 所需量级。

这里不直接把最终线写成一步到位 `166.67 us / eval`，是因为：

- 当前离目标还有数量级差距
- 需要先把 runtime 内外成本拆干净
- 否则无法知道真正阻塞点在哪

## 10. 建议的提交顺序

为了降低回归和定位成本，建议按以下顺序落地：

1. perf plumbing 与非 trace 统计固化
2. emu 外围分项计时
3. touched-set 驱动的最小版 commit phase
4. commit touched unit 合批
5. compute hotspot 单 batch 剖析与 split 规则
6. compute 正文去重 / helper 收敛
7. difftest 与外围运行时压缩

每一步都要求：

- 单独可回归
- 单独可测量
- 单独可撤回

## 11. 不建议的方向

基于当前数据，以下方向不应再作为主线：

1. 继续做 sink 激活局部小优化。

- 收益太小
- 已被 `NO0034` 证明不值复杂度

2. 优先优化 `round 2`。

- 占比太低

3. 只改 batch 个数，不看热点正文。

- 这很容易重新回到“全局调参”，而不是直面真热点

4. 只看 traced `eval total_us`，不看 wall-clock。

- 会误判整机真实收益

## 12. 本轮结论

这份计划对应三个明确判断：

1. 第一主线是 `commit` 框架重写。

- 目标是从 active-word sweep 改成 touched-set 驱动。

2. 第二主线是 compute 热 batch 正文降本。

- 目标是围绕稳定热点 batch 做 split 和正文收敛。

3. 第三主线是整机外围压缩。

- 不解决 `eval()` 外部成本，就算 runtime 内部优化成功，也到不了 `3 kHz`。
