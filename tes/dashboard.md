# TES 性能看板

> 本文件由 `python3 tes/tools/tesctl.py dashboard` 生成；record-baseline / record-eval /
> finish-step / close-run / action-done 等状态变更后也会自动刷新。**请勿手改。**
> 生成于 2026-08-15T07:11:09+08:00

## 任务 `grhsim-am-coremark`

run **r001**（active）· C=3 L=8 K=2 · evals 8/48 · actions 5 · 下一步 `step`：推进轨迹 t0 到第 2 步（round-robin 最少步数优先）

| 基准 | eval | Host 中位 | vs target |
|---|---|---|---|
| gsim（target） | e00002 | 24.7s | 1.00x |
| am（y0 基线） | e00001 | 273.1s | 11.06x |
| **当前 best** | e00006 | **270.5s** | **10.96x** |

基线→target 进度：`░░░░░░░░░░░░░░░░░░░░` 1.0%（273.1s → 目标 24.7s，当前差距 10.96x）

| 轨迹 | 分支 | 步数 | best eval | best Host |
|---|---|---|---|---|
| t0 | `tes/r001/t0/main` | 1/8 | e00004 | 271.1s |
| t1 | `tes/r001/t1/main` | 1/8 | e00006 | 270.5s |
| t2 | `tes/r001/t2/main` | 1/8 | e00008 | 272.7s |

| eval | 类别 | 位置 | Host 中位 | vs target | 状态 | 假设 |
|---|---|---|---|---|---|---|
| e00001 | baseline-am | - | 273.1s | 11.06x | ok | am baseline |
| e00002 | baseline-gsim | - | 24.7s | 1.00x | ok | gsim baseline |
| e00003 | candidate | t0/s01c1 | 279.2s | 11.31x | ok | chunk 3000->12000 使更多窄值 chunk 内标量化、减少跨 chunk uint6… |
| e00004 | candidate | t0/s01c2 | 271.1s | 10.98x | ok | 标量 mux 全量 if/else 化（branchy-mux）：若显著恶化则量化分支误预测成本并关… |
| e00005 | candidate | t1/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和性聚簇布局（标量成员+宽值池，stateLayout=affinity）后热块工… |
| e00006 | candidate | t1/s01c2 | 270.5s | 10.96x | ok | 消除同宽无符号resize_value胶（静态94.1%站点、占胶95%）后热块动态指令数/依赖链缩… |
| e00007 | candidate | t2/s01c1 | - | - | compile_timeout | 状态按块静态访问亲和聚簇布局（init宽池store按offset升序修复后）热块工作集局部性改善，… |
| e00008 | candidate | t2/s01c2 | 272.7s | 11.05x | ok | 对常量切片主导的宽状态做标量炸开（元素数组声明+直读/单元素写）后，计数器网络族的词提取+栈数组往返… |

最近 actions：A0001 run-init；A0002 step；A0003 step；A0004 step；A0005 round-summary

