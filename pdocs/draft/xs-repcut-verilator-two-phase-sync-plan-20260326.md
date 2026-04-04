# XiangShan RepCut Verilator 两阶段同步模型改造方案（2026-03-26）

## 1. 目标

本文提出一个新的 `emitVerilatorRepCutPackage` 运行时生成方案，目标不是复刻 ESSENT 的 shared-buffer 实现，而是在保留 Verilator 后端与复杂时钟模型兼容性的前提下，把当前 runtime 的同步模型尽量贴近 RepCut 的“两阶段 barrier”思路。

目标 step 模型固定为三个阶段：

1. 装载所有输入
2. 启动所有 part eval，并等待结束
3. 启动所有 part 的更新数据推送，并等待结束，然后直接返回

其中：

- 第 2 步对应 `Evaluation barrier`
- 第 3 步对应 `Global update barrier`

## 2. 设计约束

本方案建立在以下约束上：

1. 后端必须继续使用 Verilator 单元模型，不能退回到 ESSENT 的 shared-global-state 仿真器。
2. 需要兼容更复杂的时钟模型，不能要求“简化时钟语义”。
3. C++ 生成仍然必须分模块输出，不能回退成一个巨大的 `partitioned_wrapper.cpp`。
4. 现有 `sv/` 单元划分保持不变，改动只发生在 host 侧 runtime 生成方式。

换句话说：

- 不复制 ESSENT 的共享状态布局
- 复制的是“同步模型”
- 不是“数据表示”

## 3. 当前实现的问题

当前生成器把每个 part 的工作融合成单个本地任务：

- `scatter`
- `eval`
- `gather`

然后在 step 末尾统一做一次 `writeback`：

- 每个 part 的 fused 方法定义：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1113](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1113)
- step 尾部统一 `commit_writeback_()`：
  - [wolvrix/lib/emit/verilator_repcut_package.cpp:1748](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1748)

这会带来几个问题：

1. `scatter` 和 `gather` 被绑定在单个 part 内部，缺少全局 barrier 语义。
2. `writeback` 变成单线程集中提交，不能并行化推送。
3. 边界状态使用 `snapshot/writeback` 双缓存，导致运行时更像“信号搬运器”，而不是“两阶段同步器”。
4. 目前源码切分只分为：
   - `common`
   - `normal_*`
   - `writeback_*`
   这与新的 phase 模型不匹配。

## 4. 新同步模型

## 4.1 总体阶段

新的 `step()` 固定执行如下三步：

### 阶段 1：装载所有输入

主线程负责：

- 把 `top_to_unit` 连接直接写入目标 part 的 Verilated 输入端口
- 如有必要，重置本轮 transient 标志
- 常量输入不在这里重复装载，常量端口在构造时初始化一次

这一阶段不启动 worker。

### 阶段 2：并行 part eval

所有 worker 并行执行自己负责的 `part eval` 方法，并等待全部结束。

每个 part eval 方法只做两件事：

1. 假定该 part 输入端口已经在阶段 1 或上一轮阶段 3 中准备好
2. 直接调用该单元的 `eval()`

这一阶段结束后进入 `Evaluation barrier`。

### 阶段 3：并行 global update

所有 worker 并行执行自己负责的“输出推送”方法，并等待全部结束。

每个更新方法从 source part 的输出端口读取结果，并按 manifest 中的 fanout 关系：

- 直接写入目标 part 的 Verilated 输入端口
- 如果连接到 top output，也在这里直接写入 `top_out_*`

这一阶段结束后进入 `Global update barrier`。

## 4.2 语义对应

这个模型与 ESSENT / RepCut 的对应关系是：

- 阶段 2：近似 `Evaluation Phase`
- 阶段 3：近似 `Global Update Phase`

不同点在于：

- ESSENT 的 update 写回的是 shared global state
- 本方案的 update 直接写回的是目标 part 的 Verilated 输入端口

所以它是“同步模型贴近”，不是“共享状态贴近”。

## 5. 数据结构改造

## 5.1 删除 `snapshot/writeback` 信号缓存

当前实现对每条 `unit_to_unit` 边都维护：

- `signal_*_snapshot_`
- `signal_*_writeback_`

对应位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:1362](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1362)

新方案建议删除这套按“边界信号”建模的双缓存。

原因：

1. 它天然对应“先 gather 到中间缓存，再 writeback 到下一轮 snapshot”。
2. 它会把阶段 3 固定成集中式 commit。
3. 它不适合实现“每个 source part 并行推送到目的 part 输入”的模型。

## 5.2 直接把 update 写入目标 part 输入端口

新方案不再引入任何输入 shadow。

原因是你指出的这一点成立：

1. 阶段 3 发生在所有 part eval 完成之后。
2. 此时不存在其他 worker 正在读取 destination part 的输入端口。
3. 因此可以把 source part 的输出直接写到 destination part 的 Verilated 输入端口上，避免额外拷贝。

这意味着：

- 阶段 1：`top_to_unit` 直接写 destination unit 输入端口
- 阶段 2：part 直接读自己当前的 unit 输入端口并 `eval()`
- 阶段 3：`unit_to_unit` 直接写 destination unit 输入端口，供下一次 step 使用

这样更接近 ESSENT 中“global update 直接把下一轮可见状态写回去”的节拍，只是这里写回的是 Verilated 模型端口而不是 shared state。

## 5.3 顶层输出直接在阶段 3 发布

`unit_to_top` 也不需要额外 shadow。

建议处理方式是：

- 阶段 3 中把 `source unit output` 直接写入 `top_out_*`
- `Global update barrier` 结束后，`step()` 直接返回

只要保证：

1. `top_out_*` 只有单一 driver
2. host 不会在 barrier 结束前并发读取这些 getter

那么把顶层输出并入阶段 3 是更自然的做法，也少一层顺序 phase。

## 5.4 常量输入

对 `const_to_unit`：

- 不需要每个 step 重复装载
- 在构造函数中一次性初始化到目标 unit 输入端口

这样可以减少阶段 1 的工作量。

## 6. Manifest 到运行时计划的重构

当前 manifest 已经区分：

- `top_to_unit`
- `unit_to_unit`
- `const_to_unit`
- `unit_to_top`

对应位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:2274](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L2274)
- [wolvrix/lib/emit/verilator_repcut_package.cpp:2319](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L2319)

新方案不需要改 manifest 语义，但需要改生成期的中间结构。

建议把当前的运行时计划拆成三类：

1. `TopInputLoadAction`
2. `PartEvalAction`
3. `PartUpdateAction`

### 6.1 `TopInputLoadAction`

按 `top_to_unit` 边生成。

每个 action 包含：

- source top input 成员
- destination unit 输入端口

### 6.2 `PartEvalAction`

按 part 生成。

每个 action 包含：

- `unit->eval()`

也就是说，`PartEvalAction` 不再做任何 scatter，它只负责真正的 eval。

### 6.3 `PartUpdateAction`

按 source part 生成。

每个 action 包含：

- 从 source unit output 读取值
- 写入所有 fanout 的 destination unit 输入端口
- 写入所有对应的 `top_out_*`

这里的关键点是：

- 一个 destination unit 输入端口只有一个合法 driver
- 因此阶段 3 不需要锁
- fanout 复制由 source worker 独占执行

## 7. C++ 生成组织方式

## 7.1 新的 header 结构

建议 `wolvi_repcut_verilator_sim.h` 中的核心成员改成：

- `top_in_*`
- `top_out_*`
- `std::vector<StepFn> load_step_fns_`
- `std::vector<StepFn> eval_step_fns_`
- `std::vector<StepFn> update_step_fns_`

其中：

- `load_step_fns_` 主要给主线程阶段 1 顺序执行
- `eval_step_fns_` 给 worker 阶段 2 并行执行
- `update_step_fns_` 给 worker 阶段 3 并行执行

不再保留：

- `signal_*_snapshot_`
- `signal_*_writeback_`
- `commit_writeback_()`

## 7.2 worker 调度接口

建议把当前：

- `run_part_eval_phase_()`

推广成更一般的：

- `run_phase_workers_(const std::vector<StepFn>& phaseFns)`

这样阶段 2 和阶段 3 都复用同一个线程池与 barrier 逻辑。

阶段 1 保持主线程执行，不走 worker。

## 7.3 step 伪代码

建议生成的 `step()` 结构如下：

```cpp
void WolviRepCutVerilatorSim::step() {
  ++step_count_;
  ++step_timing_.steps;
  const auto stepBegin = WolviClock::now();

  const auto loadBegin = WolviClock::now();
  run_host_phase_(load_step_fns_);
  const auto loadEnd = WolviClock::now();

  const auto evalBegin = loadEnd;
  run_phase_workers_(eval_step_fns_);
  const auto evalEnd = WolviClock::now();

  const auto updateBegin = evalEnd;
  run_phase_workers_(update_step_fns_);
  const auto updateEnd = WolviClock::now();

  // timing...
}
```

## 8. 源码分模块生成

这是本方案的硬约束之一：phase 改造不能把编译压力重新推高。

## 8.1 保留 chunked generation

当前生成器已经有：

- `chunkEntriesByEstimatedSize(...)`
- `normal_*` chunk
- `writeback_*` chunk

对应位置：

- [wolvrix/lib/emit/verilator_repcut_package.cpp:1145](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1145)
- [wolvrix/lib/emit/verilator_repcut_package.cpp:1163](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1163)
- [wolvrix/lib/emit/verilator_repcut_package.cpp:1770](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1770)
- [wolvrix/lib/emit/verilator_repcut_package.cpp:1794](/workspace/wolvrix-playground/wolvrix/lib/emit/verilator_repcut_package.cpp#L1794)

新方案应继续沿用同样的 chunk 机制，但按 phase 切分：

- `wolvi_repcut_verilator_sim_common.cpp`
- `wolvi_repcut_verilator_sim_load_<n>.cpp`
- `wolvi_repcut_verilator_sim_eval_<n>.cpp`
- `wolvi_repcut_verilator_sim_update_<n>.cpp`

## 8.2 各 phase 的 chunk 原则

建议：

- `load` chunk：
  - 只包含 `top_to_unit` 装载方法
  - 直接写 destination unit 输入端口
  - 需要只包含本 chunk 用到的 model header
- `eval` chunk：
  - 只包含 `unit->eval()`
  - 需要只包含本 chunk 用到的 model header
- `update` chunk：
  - 包含 `unit output -> destination unit input port / top_out_*`
  - 同样只包含本 chunk 用到的 model header

这样可以继续利用“最小 include 集 + 按估算大小切 chunk”的思路，避免生成大翻译单元。

## 8.3 Makefile 侧的变化

构建 glue 逻辑基本不用改，只需要：

- `WRAPPER_SRC_NAMES` 改成包含新的 `load/eval/update` 文件名

现有：

- `WRAPPER_SRC_NAMES`
- `WRAPPER_OBJS`
- `$(BUILD_DIR)/%.o`

这套规则都可以继续复用。

## 9. Timing 建议

当前 timing 口径是：

- `scatter`
- `eval`
- `gather`
- step-level `part_eval`
- step-level `writeback`

新模型建议改成：

- step-level：
  - `input_load`
  - `part_eval`
  - `global_update`
- part-level：
  - `input_apply`
  - `eval`
  - `update_push`

## 10. 与当前测试的关系

当前 `test_emit_verilator_repcut_package` 明确检查了：

- 存在 `snapshot/writeback` 成员
- 正常 chunk 里同时有 scatter/eval/gather
- step 尾部有 `commit_writeback_()`

对应位置：

- [wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp:368](/workspace/wolvrix-playground/wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp#L368)
- [wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp:404](/workspace/wolvrix-playground/wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp#L404)
- [wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp:490](/workspace/wolvrix-playground/wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp#L490)
- [wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp:520](/workspace/wolvrix-playground/wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp#L520)

这些断言在新方案下都需要整体改写。

新的测试重点应改成：

1. header 中不再存在 `snapshot/writeback` 或任何新增 shadow 成员
2. wrapper source 中不存在 `snapshot/writeback` 与 `commit_writeback_()`
3. `step()` 中按 `load -> eval barrier -> update barrier` 排序
4. `eval` chunk 只负责 `unit->eval()`
5. `load` chunk 只负责 `top input -> destination unit input port`
6. `update` chunk 负责 `source unit output -> destination unit input port / top_out_*`
6. 源码输出仍然按多个 `cpp` 文件分块

## 11. 风险与开放问题

## 11.1 `debug_part` 兼容性

已有文档 [xs-repcut-verilator-partitioned-backend-plan.md](/workspace/wolvrix-playground/docs/draft/xs-repcut-verilator-partitioned-backend-plan.md) 记录过：

- `debug_part` 可能包含需要同一 host step 内立即生效的环境返回路径

因此这个新方案虽然在同步模型上更接近两阶段 barrier，但在 XiangShan 实际接入时需要单独验证：

- `debug_part` 是否能和普通 logic part 一起放进同一个阶段 2 / 阶段 3
- 或者仍然需要保留特殊路径

本文不强行假设这个问题已经解决，只把它列为迁移风险。

## 11.2 多时钟 / 复杂时钟模型

本方案不改变单个 Verilated 单元内部的时钟语义，只改变：

- 分区之间的同步方式
- host 侧边界数据传播方式

因此它对复杂时钟模型的态度是：

- 不试图像 ESSENT 那样重建统一共享状态机
- 继续把时序细节留给每个 Verilated 单元

## 12. 建议的实施顺序

建议按以下顺序推进：

1. 先重构生成期中间结构，从 `signal cache` 转成 `load/eval/update` 三类 phase actions。
2. 再把 runtime 从 `normal_step_fns_ + commit_writeback_()` 改成 `load/eval/update` 三阶段。
3. 然后保留 chunk 机制，新增 `load/eval/update` 三类源文件生成。
4. 最后统一更新 emit 测试与 timing 输出。

## 13. 最终结论

在 Verilator 后端和复杂时钟模型约束下，直接照搬 ESSENT 的 shared-buffer 机制并不现实；但把同步模型改成“两阶段 barrier + 三步 step”是可行而且合理的。

这个方案的核心不是复刻 ESSENT 的数据结构，而是复刻它最重要的执行节拍：

1. 先准备本轮可见输入
2. 所有分区完成 evaluation
3. 所有分区并行完成 global update / publish，并在 `Global update barrier` 结束后直接返回

同时，通过继续按 `phase + chunk` 分文件生成 `cpp`，可以在改同步模型的同时维持当前对编译压力的控制。
