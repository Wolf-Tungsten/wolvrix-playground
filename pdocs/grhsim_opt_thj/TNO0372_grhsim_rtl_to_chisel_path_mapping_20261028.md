# TNO0372：RTL 关键路径到 Chisel 模块映射

## 实现

在中文 RTL 路径视图上增加了 Chisel 来源解析：扫描 canonical Scala source，
按生成模块名、数字后缀归一化和源码信号前缀进行匹配，并把 package、文件和声明行
放到每个路径节点和 batch 详情中。唯一、信号最佳、名称唯一但缺少信号证据、歧义和
未解析结果均显式记录。

## 当前结果

本次报告得到 32,471 个独立 RTL module/signal 上下文：

| 状态 | 数量 |
| --- | ---: |
| 唯一匹配 | 3,570 |
| 信号最佳匹配 | 1,017 |
| 唯一名称但缺少信号证据 | 15,298 |
| 歧义匹配 | 10,707 |
| 未解析 | 1,879 |

p27 clock=0 的路径现在可以回到：

```text
xiangshan.backend.rob.Rob       Rob.scala:53
→ xiangshan.backend.CtrlBlock   CtrlBlock.scala:56
→ xiangshan.backend.Backend     Backend.scala:50
→ xiangshan.XSCore              XSCore.scala:77
→ xiangshan.XSTile              XSTile.scala:35
→ top.XSTop                     Top.scala:86
→ top.XiangShanSim / difftest.GatewayEndpoint / difftest.DelayReg
```

`MSHR_64` 等模块会保留多个候选实现，并用 `w_releaseack`、`s_writeprobe`、
`req_fromProbeHelper` 等信号命中给出最佳候选；无法区分 coupledL2、huancun 或
其它实现时，报告会把候选全部列出。

## 限制

这一步对应的是 Chisel module 和源码证据，不是完整 FIRRTL/Chisel Data provenance。
生成过程可能复制 wrapper、展开 `Vec`、重命名 wire 或合并表达式，因此不能把一个
RTL wire 直接宣称为唯一 Chisel 表达式。若后续需要表达式级映射，应在 Chisel/FIRRTL
发射阶段保留 source info 和 instance path，再与当前 GRH operation ID 合并。

中文 HTML、`critical_paths.md`、`critical_paths.csv` 和 `rtl_paths.json` 已用同一份
THP 诊断数据重新生成；真实 Chromium 检查和原有 37 项测试继续通过。
