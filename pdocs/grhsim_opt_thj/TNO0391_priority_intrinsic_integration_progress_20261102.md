# TNO0391：优先编码原语接入进度

日期：2026-11-02。状态：实施中，尚无新的整机性能结论。

按批准方案接入同名 utility.PriorityEncoder、Parallel/WithFlag/Default，默认保持
原实现；开启时覆盖所有合法已知正位宽，不根据性能挑选位宽或模块。
circt_dpi_call 保留当前 context void + output ABI；Wolvrix 在导入时识别版本化
契约并转换为无副作用的 kCountTrailingZeros，不执行该 DPI。

验证覆盖宽度边界、两组输入、活动/SSA/常量折叠/CSE/DCE，并使用专用单模型流程
完整生成香山 A/B。正式测量 node030 CPU96、本地 NUMA、默认 SLP，8 对交替 A/B。
历史基线见 [TNO0388](./TNO0388_native_single_thread_slp_local_baseline_results_20261030.md)。

## 启动检查

开始时主仓库工作区干净。当前执行节点为 node029；系统 NSS 无法解析当前 UID，
OpenSSH 客户端在建立连接前报 `No user exists for uid 1216200098`。
先核对使用显式用户名的 SSH 传输是否可用；不修改系统账户或测量协议。
本地实现工作可独立推进，远端情况和所有失败原样记录。

## 接入与首次验证

- 同名 utility 包装及 35 处显式同名 import 已落地。Scala 的后续通配 import 会影响
  名称解析，显式 import 已统一置于其他 import 之后，未使用别名。
- node030 可使用已有 SSH 密钥连接；启动时以显式主机地址/用户名绕过客户端 NSS
  故障，随后系统账户查询恢复，未修改系统账户、认证或测量环境。
- 任意宽度纯 CTZ 已接入导入、序列化、常量折叠和标量/宽字 C++ 发射。
- native 专项验证通过：CSE/DCE/常量折叠/来源、活动来源、跨组结果变化检测；
  无关输入不触发 CTZ，输入变化但结果不变不激活后续组。
- 65 位独立案例已通过两组种子、五种分布共 1,000,133 个输入的普通 GrhSIM、
  原语 GrhSIM、原始 RTL Verilator 与独立参考比较。pilot 时间仅用于运行检查，
  不作为正式性能结论。
- 完整香山普通 RTL 已生成；本配置记录 466 个 utility 调用，位宽为
  1/2/4/5/6/7/8/9/10/14/16/32/36/38/64，实际额外位宽将加入固定实验矩阵。
  原语 RTL 生成正在继续。
