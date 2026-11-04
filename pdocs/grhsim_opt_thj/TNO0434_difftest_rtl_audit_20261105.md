# TNO0434：DiffTest RTL 结构审计与候选改写

日期：2026-11-05。

本轮目标是在保留 S3（完整采集、NEMU reference checking 和 DiffTest schema）的前提下，先检查 RTL 中是否存在适合 GrhSIM 的冗余表达，再决定是否进行 walltime 测量。没有把“运行时关闭 DiffTest”当作优化目标。

## 当前生成结构

当前 `XiangShanSim` 直接调用 `DifftestModule.top`，没有设置 `Gateway.setConfig("U")`，所以默认配置是 `softArchUpdate=false`。同一份生成产物中有 106 个 DiffTest bundle 和 106 个 packed gateway port：

| 项目 | 数值 |
| --- | ---: |
| packed gateway bits | 79,263 |
| 非零延迟接口 | 75 / 106 |
| 每周期延迟位数 | 66,484 |
| 延迟寄存器存储位数 | 135,663 |
| GatewayEndpoint | 988,522 B |
| PreprocessEndpoint | 179,606 B |
| Dummy DPIC wrapper 实例 | 103 |

三个物理寄存器观察器（整数、浮点、向量）延迟存储共 99,888 bit，占全部延迟存储的 73.63%。`PreprocessEndpoint` 还包含 256×64、256×64 和 512×64 的动态索引查找表，用于物理寄存器到架构寄存器及 commit data 的转换。

## 已检查的改写

### 取消中间 `dontTouch`

`--difftest-relax-intermediate-wires` 只取消 Gateway bundle 的 `dontTouch`。106 个接口、Endpoint、Preprocess 和 wrapper 拓扑完全不变；RTL 总量只减少约 0.015%，GRH compute nodes 减少 0.071%，compute supernodes 减少 0.134%。这说明该标记不是主要成本来源。

### 直接使用 `bundle.asUInt` 作为 Boring source

将 `WireInit(UInt(...), bundle.asUInt)` 改成直接 source 后，RTL 文件数、GatewayEndpoint、PreprocessEndpoint 和 GRH 结构均未变化；RTL 总量只差 81 B。firtool 已经消除了这层表达差异，不值得保留为优化开关。

### 将延迟寄存器按整包 UInt 保存

`--difftest-packed-delay-regs` 将字段级 `RegNext` 改成整包 UInt 的 `RegNext`。RTL 文件和 Endpoint 大小只有微小变化，GRH 统计逐项完全相同：

```text
graph_ops                 6,484,088
graph_values              6,124,081
compute_nodes             1,003,644
compute_supernodes           60,225
boundary_values              923,327
boundary_activation_edges 1,794,798
topo_edges                8,918,010
dag_edges                   478,569
```

这条改写没有减少 GrhSIM 调度工作。

### 无效 payload 置零

在 `PreprocessEndpoint` 中尝试只在 `commit.valid` 或寄存器更新依赖有效时传递 payload，否则输出零。生成 RTL 的 `PreprocessEndpoint` 增大约 8.9 KB，增加了 Mux；GRH activity-schedule 在 canonicalization 后仍得到与默认版本完全相同的统计。因此该写法既没有降低当前模型规模，也可能增加 RTL 组合逻辑，已撤回代码。

## 结论

这次审计没有发现可以通过局部 Chisel 改写直接缩小 GrhSIM 主模型的结构。当前主要成本来自完整物理寄存器观察器、Preprocess 的动态映射和 106 个接口本身，而不是 `dontTouch`、单个 packed wire 或延迟寄存器的字段布局。

下一步应把优化放在 GRH 的 observer-side 组织：保留所有 S3 输出和 NEMU 检查，但让 DiffTest snapshot、物理寄存器映射和提交边界数据不参与 DUT 主状态的调度划分。这个方向需要在 Wolvrix 中定义 observer/commit-boundary 语义，不能靠继续堆叠局部 RTL Mux 得到稳定收益。本轮没有进行 walltime 测量，也没有改变默认 DiffTest 配置。

原始审计由 `scripts/difftest_rtl_audit.py` 生成，产物分别保存在 `build/xs/difftest_*` 对应目录。
