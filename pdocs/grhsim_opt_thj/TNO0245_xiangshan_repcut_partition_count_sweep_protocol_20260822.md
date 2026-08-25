# XiangShan RepCut partition-count sweep protocol

日期：2026-08-22

## 1. 目标与证据边界

本轮在同一份 XiangShan `SimTop` GRH、同一 Wolvrix 二进制和同一 RepCut 参数下，
只改变 `partition_count`，依次测量：

```text
k = 2, 4, 8, 16, 32, 64
```

目标是形成可直接横向比较的静态分区统计，包括源 op 归属、最终分区 graph op、
op 复制率、最终 op 膨胀率、权重与 op 不平衡度、跨分区 value、cut/KM1、各阶段
生成耗时和峰值 RSS。

本轮只执行 `read_json + repcut`。不执行 JSON roundtrip、SV/package emit、Verilator
构建或仿真，因此结果证明 RepCut transform 在六档 `k` 下成功完成及其静态结构特征，
不证明生成设计的仿真语义，也不产生 runtime speedup 结论。生成耗时和 RSS 作为同机串行
raw snapshot，不作为严格 quiet-host 性能基准。

## 2. 冻结输入与环境

实验根目录为：

```text
build/repcut_partition_sweep_20260822
```

已有 `build/repcut_thread_scaling_20260819` 和其他工作区产物均不删除、不覆盖。身份如下：

| 项目 | 值 |
| --- | --- |
| parent commit | `e088bdbbddecdc8998e82d4ac5410d977768d5ce` |
| Wolvrix commit | `79ec2037b00f2d4894d72785277ebe3f5d37782d` |
| XiangShan commit | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` |
| 输入 GRH | `build/xs/wolf/wolf_emit/xs_wolf.json`，`3,427,740,706 B`，SHA-256 `82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba` |
| Python | `3.12.3`，`.venv/bin/python` |
| `_wolvrix.so` | `7,407,448 B`，SHA-256 `36f2b9d0641e7e59940b9c512346c449906b9bf605eb32053c093385e9329549` |
| `libwolvrix-lib.so` | `49,077,264 B`，SHA-256 `bd9e7aefdb6c61c44a70b82914b19b1d00abf22c3d3c7d408242ea6257176233` |
| sweep runner | `build/repcut_partition_sweep_20260822/run_one.py`，`4,224 B`，SHA-256 `6bace0058042f9a61abff61ebed1e9c4bb469df0f451a8b9dc50d236d8e28d65` |
| host | `node029.bosccluster.com`，Linux `6.8.0-136-generic`，`384` logical CPU，约 `1 TiB` RAM |

实验开始前父仓库已经有 `pdocs/grhsim_opt_thj/README.md` 修改、`TNO0238..TNO0244`
未跟踪文件以及 modified Wolvrix submodule；Wolvrix 内原有 `.gitignore` 修改和
`external/mt-kahypar` 非 clean 状态。本轮不还原这些用户已有变化，也不修改 RepCut
源码或默认参数。参与执行的 Python 扩展和输入另以 SHA 冻结，避免只用 commit 掩盖
工作树状态。

## 3. 固定参数与执行顺序

六档均使用：

| 参数 | 固定值 |
| --- | --- |
| `path` | `SimTop` |
| `imbalance_factor` | `0.015` |
| partitioner | `mt-kahypar` |
| requested preset | `quality` |
| effective preset | 必须由日志确认为 `deterministic-quality` |
| seed | 必须由日志确认为 `0` |
| requested Mt-KaHyPar threads | `0`；本机日志应记录实际 active threads |
| intermediate files | 保留 HGR 和 `.partK` |

为避免内存和 CPU 资源相互污染，按 `2 -> 4 -> 8 -> 16 -> 32 -> 64` 串行执行；每档
启动独立 Python 进程并从原始 GRH 重新读取，不能复用上一档已经改写的 Session。

每档命令模板为：

```bash
/usr/bin/time -v \
  -o build/repcut_partition_sweep_20260822/logs/k${k}.time.log \
  .venv/bin/python build/repcut_partition_sweep_20260822/run_one.py \
    --input build/xs/wolf/wolf_emit/xs_wolf.json \
    --experiment-root build/repcut_partition_sweep_20260822 \
    --k "${k}" \
  > build/repcut_partition_sweep_20260822/logs/k${k}.stdout.log \
  2> build/repcut_partition_sweep_20260822/logs/k${k}.stderr.log
```

每档持久化：

```text
logs/kK.{stdout,stderr,time}.log
results/kK.stats.json
runs/kK/work/SimTop_repcut_kK.hgr
runs/kK/work/SimTop_repcut_kK.hgr.partK
```

结构化 stats 来自 RepCut pass 返回的唯一 `{"pass":"repcut",...}` info diagnostic；
不为统计目的额外写出数 GiB 的最终 GRH JSON。

## 4. 指标口径

设原始 `SimTop` op 数为 `N0`，分区数为 `k`：

- `source_ops_i`：clone 日志记录的第 `i` 个分区所归属的原始 op 数；
- 源 op 复制率：`R_source = (sum(source_ops_i) - N0) / N0`；
- `final_ops_i`：重建结束后第 `i` 个分区 graph 的实际 op 数；
- 最终 op 膨胀率：`R_final = (sum(final_ops_i) - N0) / N0`；该值包含边界
  slice/bundle 等新生成 op，不能称为纯复制率；
- 平均每分区 op：分别报告 `mean(source_ops_i)` 和 `mean(final_ops_i)`；
- op 不平衡度：`I_op = max(op_i) / mean(op_i) - 1`；
- 权重不平衡度：`I_weight = max(weight_i) / mean(weight_i) - 1`；它与配置的
  `imbalance_factor=0.015` 对齐，但不等于 raw op 不平衡度；
- HGR cut：`sum(w_e)`，其中超边 `e` 跨越至少两个分区；
- HGR KM1：`sum(w_e * (lambda_e - 1))`，其中 `lambda_e` 是超边触及的分区数；
- 通信规模：分别保留 `cross_values_total`、`cross_values_need_ports` 和
  `cross_links`，不混用 value、port、word、bit 等不同口径。

所有 rate 和 imbalance 在原始 JSON 中保留整数分子/分母，文档表格只做显示舍入。
min/median/mean/max 均从逐分区原始数组复算，不从已舍入均值反推。

## 5. 有效性门禁

每个 `k` 只有同时满足以下条件才进入正式汇总表：

1. Python 和 `/usr/bin/time -v` 的退出状态均为 `0`；
2. stats diagnostic 恰好一条，`partition_count_requested/observed` 均等于目标 `k`；
3. clone begin/done 均各有 `k` 条，且 source-op 总数可复算；
4. `partition_graph_stats` 恰有 `k` 条，最终 op 总数与 summary 一致；
5. HGR 顶点数等于 `.partK` 行数，partition id 完整覆盖 `0..k-1`；
6. 从 HGR 顶点权重和 `.partK` 复算的每分区权重与 stats 完全一致；
7. 日志没有 error/fatal/bad_alloc/partition incomplete 等负向签名。

失败或中止档不删除，保留日志并在结果文档中标为排除，不用部分数据补齐表格。

## 6. 预注册解释边界

- 六档数据满足同输入、同 binary、同目标和同参数，允许解释为本轮 `k` 变化的结构效应。
- 单次 deterministic-quality 切分不是跨 seed 方差研究；本轮不报告置信区间。
- 不用历史 `SimTop.logic_part/k=128` 数据拼接本轮曲线；其目标、流程和版本不同。
- 不由 transform 完成推断仿真正确，也不从生成时间推断模拟性能。

执行结果、完整统计和结论另记于
[TNO0246](./TNO0246_xiangshan_repcut_partition_count_sweep_results_20260822.md)。

## 7. 指标口径勘误（2026-08-22，`k=2` 完成后、其余档执行前）

第 4 节原先把 `(sum(source_ops_i) - N0) / N0` 命名为“源 op 复制率”。`k=2`
首档结果证明这个命名不成立：`N0=5,826,569`，而 clone membership 总和仅
`5,616,176`。原因是原始 top graph 并非每个 op 都进入 part graph，故该差值混合了
“未克隆进 part 的原 op”和“多分区归属”，可以为负数。

为避免看到结果后仍沿用错误指标，正式结果改用以下三个互不混淆的量，并保留本节作为
预注册口径修正记录：

1. **核心 op 复制率**：RepCut 在 constant/DPI propagation 前已经记录每个分区的
   `partition_static_features.op_count`；日志中的 `op_partitioned` 是同阶段至少有一个
   owner 的唯一 op 数。正式定义
   `R_core=(sum(feature_op_count_i)-op_partitioned)/op_partitioned`。`k=2` 对应
   `(5,583,175-5,567,745)/5,567,745=0.277132%`。
2. **clone membership 净变化率**：仍报告
   `D_source=(sum(source_ops_i)-N0)/N0`，但不再称为复制率；它包含后续 constant/DPI
   propagation，也受未进入 part graph 的原 op 影响。
3. **最终 part-graph op 净变化率**：`D_final=(sum(final_ops_i)-N0)/N0`；它进一步
   包含边界适配 op，也不称为纯复制率。

第 4 节的平均 source/final op、不平衡度、weight、cut/KM1 和通信指标不变。六档均按
上述修正口径重新计算，不能只对 `k=2` 特判。
