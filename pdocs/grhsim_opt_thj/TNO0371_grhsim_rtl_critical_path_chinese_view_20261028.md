# TNO0371：关键路径中文 RTL 视图

## 更新内容

根据首版报告的使用反馈，报告首页已改为 RTL-first 关键路径清单，不再先展示英文概览表。
`report.html` 现在用中文直接展示：

- 分区、clock 电平和静态路径名次；
- 每条路径上的 RTL module/interface/program；
- 信号或表达式名称；
- 每个 GRH 节点对应的 RTL 文件、行列和源码行；
- 求值 batch、结构工作量、运行时拖尾证据和来源覆盖；
- 对没有可靠来源的生成操作明确显示“RTL 来源未映射”。

箭头只表示静态 GRH 组合依赖顺序。模块名来自源码声明，信号名来自记录源码行中的词法证据；
报告不会把多个源码位置拼成一个不存在的实例层次，也不会把 batch 时间拆成逐信号时间。

## 新增输出

以同一份 `critical-path-thp-v1` 诊断结果重新生成：

- `report.html`：中文交互报告，首页直接显示 30 条可审阅路径；
- `critical_paths.md`：无需浏览器即可阅读的中文路径清单；
- `critical_paths.csv`：便于筛选的路径表；
- `rtl_paths.json`：路径、源码上下文、模块、信号和 batch 结构化数据。

示例中 p27 的 clock=0 路径可读为：

```text
Rob.debug_exuData_128
→ Rob.debug_exuData_0
→ Rob._GEN_8227
→ Rob.trapVec_6 … Rob.trapVec_0
→ Rob.difftest_trap_hasTrap
→ CtrlBlock/Backend/XSCore/... 的 gatewayIn_packed_20_bore
→ GatewayEndpoint.in
→ DelayReg_26.REG_addr
```

这是一条由 GRH 操作依赖和来源位置串起来的仿真结构路径，仍需结合 batch 运行时证据判断是否值得改 RTL。
报告继续把 p0 的状态提交 batch、p27 的计算 batch 和它们的模块/信号关联单独列出。

## 验证

报告重新生成成功，真实 Chromium 检查覆盖中文页面加载、动态阶段筛选、batch 搜索、模块/信号展开、
路径卡片和源码位置。此前 37 项 Python/native 测试继续运行；路径视图的 Python 编译和 `git diff --check`
也通过。诊断数据、页面模式、CPU 和采样窗口均未改变。
