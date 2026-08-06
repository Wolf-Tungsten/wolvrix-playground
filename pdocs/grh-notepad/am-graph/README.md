# am-graph 专题索引

主题：grhsim AM 指令/执行模型升级与转换路径重构——在 GRH IR 与 grhsim am program 之间引入 grhsim am graph 层（instr 为 op、var 为 value；var 区分状态/非状态并补足声明语义；显式快照/破环），graph 上承载优化与调度 pass，定型后一次性生成 program 交付 emit/interpreter。硬约束：执行语义不变、香山 difftest 通过、性能不回退。

管理规则见 [../RULES.md](../RULES.md)。

## 记录索引

| 编号 | 标题 | 日期 | 内容摘要 |
|---|---|---|---|
| [NO0001](NO0001_AM执行模型升级与图重构_20260804.md) | AM 执行模型升级与图重构 | 2026-08-04 | 五条指令模型升级的落地；AmGraph 图层落地（容器/调度器过图）；锥打包两个 def-after-use 根因修复后，mem.write 回退 cond/mask（快照 vs 活读不对称），锥打包随之整体移除（保留事件签名门控 + def-before-use 硬校验 + 相位审计）；t0 错位根治，香山 difftest 73,580/49,996 通过，回退版取优 329.7s |
