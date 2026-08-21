# TES 任务指令（x0）：grhsim-am xiangshan coremark 50k 性能优化

这是每个 proposal 都会携带的常驻任务指令。它定义目标、约束与裁决口径，不随实验进展改变；如需修改，修改即构成新的实验条件，必须在 `tes/grhsim-am-coremark/state/insights.md` 追加记录。

## 目标

最小化 grhsim-am emu 仿真 xiangshan coremark 50k 周期（`-C 50000`）的 **Host wall time**（3 rep 中位，`taskset` 绑核，串行无干扰），直至**不劣于 gsim 同等负载**（同一 coremark bin、同一 difftest 协议、同一机器、同一测量协议测得的 gsim emu Host 中位）。

- 分数：`score = -median_host_ms`（越高越好）。
- 进度指标：`ratio = am_median / gsim_median`，目标 `ratio <= 1.0`。
- 参考基线在 run-init 时实测并冻结进 `tes/grhsim-am-coremark/runs/<run>/manifest.json`。

## 硬约束（任一违反即判失败候选）

1. **功能门**：difftest 逐位一致——每 rep 进程退出码 0 且 `instrCnt = 73,580`、`cycleCnt = 49,996`（coremark-2-iteration 50k 窗金标）。
2. **回归门**：`ctest -R grhsim` 全绿（emit-cost 系列确立的 17 项）。
3. **测量纪律**：固定 3 rep 在三个独立物理核上单批并行、评估之间严格串行、无构建等
   并发负载；计数/计时分离（正式计时不开 `EMU_RUNTIME_PROFILE` /
   `EMU_AM_BLOCK_EXECS` 等插桩）。
4. **编译预算**：从 cmake 到 emu 二进制就绪的累计墙钟 ≤ **40 min**，超预算即判 `compile_timeout` 失败，不进入计时——生成代码体积/单 TU 复杂度也是成本（NO0007 曾单 TU >40min），病态膨胀的候选没有资格谈运行时。

## 工作面

候选解 = wolvrix 仓库的一个 commit（在 tes 候选分支上）+ 可选的 emit 参数覆盖（`emit_args`，如 `--blocks-per-source`、`--dp-coarsen-*`、`--max-atoms-per-block` 等旋钮）。评估输入固定为 wolvrix 自解析 XiangShan SV 的归一化 GRH（post-stats JSON，见 manifest 指纹），保证跨候选可控对比。

## 优化哲学（变更面纪律，r002 起）

1. **GRH IR 冻结**：候选不得改变 GRH IR 的定义与语义（`wolvrix/include/core/grh.h`、`wolvrix/lib/core/grh.cpp` 等 GRH 数据结构与算子语义），也不得以 ingest 侧行为变化作为收益来源——GRH 是跨工具的稳定契约，冻结它以保证候选间可比、可归因。
2. **按 Φ 做局部精修**：AM IR（lower 之后的块/atom/调度结构）允许重构，但每个 step
   必须从 Φ 选中的历史节点与反馈出发，围绕已观测病灶形成连续的因果链；不能因“允许激进”
   就跳到与 proposal 无关的方向。
3. **大改先分解再验证**：调度/分区/布局等算法可以替换，但须先有当前轨迹内的 TES 证据
   支持，并拆成可归因、可回撤的局部候选逐步验证。无证据的大跨度新方向应由不同轨迹承担，
   或等当前方向被 TES 评估否决后再由 Φ 选择。
4. **改进尽可能显式化**：优化手段应尽量体现为**显式的 grhsim AM 优化 pass / 算法阶段**——有名字、可独立开关、能在 pipeline 中定位，便于单变量归因与回撤；避免把变换隐式揉进 emit/lower 的边角逻辑里。即使是激进重构，也应落为可指认、可开关、可文档化的显式机制，而非不可分离的整体改写。
5. **机制收益导向**：候选应追求足以缩小对 gsim 差距的机制收益，避免平庸参数扫掠；
   原创性不能替代 refinement 连续性和可证伪证据。
6. **emit 规则变更须配文档**：确需改变 emit 规则的候选，应尽可能同步提供或更新文档（`wolvrix/docs/grhsim/`，如 `grhsim-am-pipeline.md`），说明规则变化与动机；文档随候选 commit 一并提交。

## 非 TES 历史背景（来自 pdocs/grh-notepad/emit-cost 等，仅作先验）

以下记录不是 TES ledger 节点，其中的失败或“证伪”不能直接作为负方向、关闭条件或禁止
重试的依据；它们可能受旧输入、旧实现完整度或旧测量协议限制。候选若能指出实现补足或条件
变化，可以在当前 TES 内重新检验。

- Host 465.8s → 324.0s 的修复链：巨 atom 常量折叠（NO0011）、动态基座元素级发射（NO0012）、装配锥窗口化（NO0013）、dynblend 锥塌缩（NO0014）、窄值标量化（NO0016）、宽状态切片内联 + 掩码写展开（NO0018）。
- 当前残余成本画像（NO0018 收口）：跨 chunk uint64 数组槽 store→load 往返、状态 gather（194MB 模型对象上的值散布）、2.87x instr/atom 适配胶；匹配对加权 4.14x、>100x 尾部 13 对 / 1.5G。
- 历史负结果：分区形状（NO0002）、存储宽度本身（NO0016 Stage A）；历史回撤先例：
  独立 concat 去零换 replace（NO0013 F2）。
- 测量陷阱先例：`-j32` 构建负载污染计时（supernode-align NO0017）、ASLR/PIE 布局效应（NO0338+）、跨构建 id 漂移导致 join 错配（emit-cost NO0017）。
