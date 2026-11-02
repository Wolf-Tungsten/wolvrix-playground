# TNO0380：广泛模式调查交付、双实现设计与后续优先级

日期：2026-10-29。研究范围与过程见 [TNO0375](./TNO0375_chisel_simulation_pattern_survey_progress_20261029.md)。

## 本轮完成的交付

- [中文交互报告](../../wolvrix/build/artifacts/chisel-pattern-study/survey/report.html) 与
  [完整案例卡片](../../wolvrix/build/artifacts/chisel-pattern-study/survey/report.md)。
- 源码覆盖扩大到 1,583 个 Scala 文件、12 个源码组：仓库源文件 1,251 个，固定版本
  Chisel 7.3.0 sources.jar 全部 332 个 Scala 文件。包括 CIRCT/FIRRTL 的宿主侧代码。
- 51 项开放候选逐项记录硬件目的、成本机制、软件表达、已有优化、当前处置与语义边界；
  未分类文件和未找到的预设文件名都保留。文件计数是词法覆盖，不是全设计实例化证明。
- 冻结生成包反向扫描 7,412 个 C++ schedule 文件、1,685,265,822 字节；32 份原生来源
  CSV 共检查 7,519,299 条 operation 记录。列明 RTL 模块的线索为 385,458 个操作，分布
  于 2,455 个文件/batch 组合；未把其中的 batch 时间分摊到源码行。
- 47 个真实发射实例（35 组合、12 状态），主实验 47,463,120 个输入/周期检查、1,880
  对 AB/BA；每种实例五种输入分布。状态例子比较时钟沿前后输出。
- [真实 MSHR count](./TNO0378_chisel_pattern_frozen_mshr_count_20261029.md) 原样提取，
  穷举 262,144 输入，另检查 200,000 随机输入；三种分布 × 三候选 × 8 对。
- [CRC 共同调用复核](./TNO0379_chisel_crc_call_context_control_20261029.md) 另检查
  1,000,000 输入、80 对；根据反证撤回通用查表收益判断。
- [双实现与自定义 IR 设计](../../wolvrix/docs/emit/chisel-semantic-simulation.md)，覆盖
  纯组合操作、组合算法块和有状态组件，不新增生产 API 或 OperationKind。

## 接口可行性的重要发现

Chisel 7.3.0 的 IntrinsicExpr、DPI 和 ChiselStage.elaborate 提供了保留意图的入口，
但不是完整接入：新的 intrinsic 需要消费者；ElaboratedCircuit 的 `_circuit` 是
`private[chisel3]`，公共接口不等于任意内部图遍历 API。

局部接入应先解决有类型端口、稳定 occurrence/绑定、硬件回退、来源传递及 emitter
lowering；组件还要明确事件、状态 owner、重复 eval 无副作用和每事件 commit 一次。
完整前端另需承接宽度、连接优先级、aggregate、memory、时钟、blackbox 和版本适配。
设计文档逐项列明了工作边界，没有把“取得 elaboration 对象”当成已经完成前端。

## 后续优先级的依据

| 去向 | 代表候选 | 本轮依据 | 接入前仍缺什么 |
|---|---|---|---|
| 先做语义保留小闭环 | 优先编码、Gray decode、旋转、有限完整 LUT、递归基数谓词 | 真实库参数实例中有明显生成计算体残留 | 精确绑定真实实例、布局、活动依赖与生产功能回归 |
| 先做布局/状态契约 | Reg(Vec) 动态索引、masked write、Queue、CAM、histogram | 完整独立组件与软件模型差异大；table64 未进入 reg-to-mem 候选 | 外部读者激活、真实端口/协议、内部观察投影 |
| 保留为布局敏感研究 | PopCount、bit gather、宽重排 | 打包输入与分散状态槽结果不同，ISA 也改变候选 | gather/维护成本，真实调用上下文 |
| 保留已有实现或反例 | parity/ECC encode、小排序网络、部分 mux、CRC | 已有紧凑机器码或软件替代退化/不稳定 | 更明确的参数或实际热点证据才值得继续 |
| 先补语义与来源 | 完整乘除/FPU、MIMOQueue、仲裁/FreeList、SRAM、多时钟、日志 | 本轮没有可验证的完整替代契约 | 周期、特殊值、优先级、冲突、副作用与观察条件 |
| 继续真实调度诊断 | batch345 的提交、广播与固定点传播 | 已有 batch 动态线索，但没有每写操作因果分解 | guard/变化计数、激活读者和传播链 |

优先级不是只保留几个函数的名单。新模式可继续进入目录；未测项保留具体源码和限制。
本轮没有修改 XiangShan RTL、生产生成选项或性能默认配置，也没有据微基准宣称整机加速。

## 复现与审计

[使用说明](../../docs/chisel-simulation-pattern-study.md) 给出编译、独立实验、冻结代码
抽取、CRC 复核与报告生成命令。原始失败轮次、早期 raw 发射和最终 normalized-v5
均按目录保留。主实验源文件快照、编译输入/输出哈希、机器码和每对原始采样可独立核查。

结果汇总会拒绝有失败的轮次、缺失/重复 pair、错误 AB/BA 次序、非有限计时、缺少
沿前/沿后验证及被修改的生成输入/二进制。故意注入错误的软件输出已被差分拒绝。
中文 HTML 使用真实 Chromium 检查筛选、搜索、展开和结果数量。

## 最终验证记录

8 项工具/解析/结果完整性测试通过；C++ 研究 emitter 构建、Python 编译检查及两层仓库 diff 检查通过。
真实 Chromium 完成组合/状态/完整 eval 与五种分布筛选、搜索、证据展开、51 项处置和 CRC 复核检查。
[浏览器检查结果](../../wolvrix/build/artifacts/chisel-pattern-study/browser-final/browser.json)。

以上工具检查之外，功能证据来自主实验、冻结 count 和 CRC 复核的真实生成模型差分。
未运行新的整机性能 A/B，也没有把独立 helper 的百分比作为整机加速结论。
