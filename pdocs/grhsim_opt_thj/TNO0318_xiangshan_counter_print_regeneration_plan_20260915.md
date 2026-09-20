# TNO0318: XiangShan counter-print regeneration plan

日期：2026-09-15

状态：`PLAN; FRESH RTL AND GRH STRUCTURAL GATE`。

## 1. 范围

用户要求继续验证 [TNO0317](./TNO0317_xiangshan_perf_print_current_counter_experiment_20260915.md)
的单行实验。唯一设计变更仍为 XSPerfAccumulate 打印 next_counter→counter；不叠加
selector/write-pack、不删除其他 debug/DPI、不调求解器权重、不改变 runtime。

## 2. 构建与身份

新产物位于 `build/asc_counter_print_20260915/`，保留旧 `build/xs` 和先前 O/A/B/AB。
旧 RTL time.log 记录 `TLConfig`、`E.b`、1 core、difftest G、Chisel systemverilog、
split-verilog/dump-fir、release lowering、default-layer-specialization=enable、enable-difftest。
新 RTL 使用同一参数；Mill 编译缓存、NOOP_HOME/build/generated-src、RTL 输出均隔离。

重新运行同一 wolvrix_xs_emit 前端及 pass 序列生成 GRH；通过单独 cwd 隔离脚本的 tmp
统计输出。先比较新旧 RTL 和配置，若有非目标差异，不能直接把新旧 GRH 差异归因本修改，
需补对称 fresh control 或缩小结论。保留工具、源码、输入和产物身份、退出码及日志。

## 3. 判据

重用已验证的只观测 RepCut overlay，运行 phase A/B/C 并在 solver 前返回，保持 memory
共置和结构 guard。对比 ASC 数、max sinks/comb/full closure，以及 O 中 giant ASC 的
429 个 memory symbol 在候选中的归属，不能把编号变化或权重下降直接叫作拆分。

先闭合 RTL/GRH 和 ASC gate，再决定是否进入分区重建/功能/runtime 测试；不由静态结果
声称 Host 提速。构建结果、结构结果按目录规则另建记录，不覆盖本计划。
