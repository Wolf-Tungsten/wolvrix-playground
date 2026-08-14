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
3. **测量纪律**：计时 rep 串行、绑核、无构建等并发负载；计数/计时分离（正式计时不开 `EMU_RUNTIME_PROFILE` / `EMU_AM_BLOCK_EXECS` 等插桩）。
4. **编译预算**：从 cmake 到 emu 二进制就绪的累计墙钟 ≤ **40 min**，超预算即判 `compile_timeout` 失败，不进入计时——生成代码体积/单 TU 复杂度也是成本（NO0007 曾单 TU >40min），病态膨胀的候选没有资格谈运行时。

## 工作面

候选解 = wolvrix 仓库的一个 commit（在 tes 候选分支上）+ 可选的 emit 参数覆盖（`emit_args`，如 `--blocks-per-source`、`--dp-coarsen-*`、`--max-atoms-per-block` 等旋钮）。评估输入固定为 gsim 导出的同一张 exec-GRH（见 manifest 指纹），保证跨候选可控对比。

## 已知机制背景（来自 pdocs/grh-notepad/emit-cost 等，run-init 时的起点知识）

- Host 465.8s → 324.0s 的修复链：巨 atom 常量折叠（NO0011）、动态基座元素级发射（NO0012）、装配锥窗口化（NO0013）、dynblend 锥塌缩（NO0014）、窄值标量化（NO0016）、宽状态切片内联 + 掩码写展开（NO0018）。
- 当前残余成本画像（NO0018 收口）：跨 chunk uint64 数组槽 store→load 往返、状态 gather（194MB 模型对象上的值散布）、2.87x instr/atom 适配胶；匹配对加权 4.14x、>100x 尾部 13 对 / 1.5G。
- 已证伪方向：分区形状（NO0002）、存储宽度本身（NO0016 Stage A）；已回撤负优化先例：独立 concat 去零换 replace（NO0013 F2）。
- 测量陷阱先例：`-j32` 构建负载污染计时（supernode-align NO0017）、ASLR/PIE 布局效应（NO0338+）、跨构建 id 漂移导致 join 错配（emit-cost NO0017）。
