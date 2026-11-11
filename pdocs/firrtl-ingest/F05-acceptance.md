# F05 寄存器、复位与有序数组写验收

实施日期：2026-10-31。主仓和 wolvrix 均位于 `grh/firrtl-ingest`；
实施基点为主仓 `bda586b`、wolvrix `5be5cb9`。正式支持合约见
[firrtl-state.md](../../wolvrix/docs/ingest/firrtl-state.md)。
实现提交为 wolvrix `f38084a`；node 执行复制基础修复独立提交为
`a77e6c6`，两者均位于 `grh/firrtl-ingest`。

## 交付与退出条件

| 条件 | 实现及验证 |
| --- | --- |
| reg/regreset 与类型 | semantic descriptor 记录 clock/reset/reset data；检查非 const storable UInt/SInt/Vector/无 flip Bundle、Clock 时钟、one-bit UInt/Reset/AsyncReset 复位、reset data 类型及异步 const 限制；推导宽度同时纳入 reset data 和普通连接 |
| 既有状态族 | 每个展平 Bundle 叶子生成一个 kRegister，Vector 维度保留 shape；whole/indexed read/write 复用普通 GRH 族；没有新增独立可执行状态 IR |
| 有序部分及整体写 | connect 先汇总为按文本排序的意图，再产生 whole/indexed writer；不同地址分别生效，同地址后写覆盖；whole→row→element→whole 两个方向均对照 |
| reset barrier | 普通写 gate !reset；最终 whole writer gate reset；sync 事件只有 clock posedge，async 全部 writer 统一 clock/reset posedge；验证独立 reset 断言、高时钟解除、持续 reset 和无重复时钟写 |
| 旧状态采样 | data、indices、enable、同步 reset data 都是旧状态观察；RenameTable 端口 1 从端口 0 地址读旧值；priority 索引从本周期被整体覆盖的旧状态读取；同步 self-reset 保留旧值 |
| 不展开动态数组写 | RenameTable 结构断言 1 个 shaped kRegister、2 个 kRegisterWriteArrayPort、1 个 reset whole writer；没有 kMul/kShl 地址运算，也不构造全数组副本逐槽提交 |
| 初始化与 invalid | FirrtlInitPolicy 默认 Unknown/显式 Zero、独立 FirrtlInvalidPolicy；元数据可追溯；FourState 保留到既有显式投影；regreset 值不冒充启动值；signed 扩展、invalid 后写优先、零宽/零 extent 均有检查 |
| 条件声明 | 硬件声明本身无条件；只有不包含 destination 声明的 interleaving 条件控制 connect；局部 wire 和 reg 在外层条件为假时仍具有规范行为 |
| node 边界 | state declaration/read/write 不带 members；真实 node 的 General/Output 计算复制保留 source key/roots；显式 grhsim.nodeClone 区分合法 owner 间复制和非法重复根，JSON、普通 GRH 优化与转换阶段后仍验证 |
| 多周期独立记分板与等价 SV | RenameTable 384 cycle × 4 phase，priority 512 cycle × 5 phase；对照普通图、JSON 重载及 simplify 后图；FIRRTL 和 SV 共四个生成模型实际编译运行，每个模型重复 3 次 init/eval epoch |

独立记分板为 `wolvrix/tests/ingest/data/firrtl/state/workload.hpp`，只使用
标准库数组和位操作，不引用 GRH、lowering、emitter 或图求值 API。普通图用
现有独立 state Oracle 执行，再分别和 SV 输出、记分板比较。生成模型直接
运行相同的独立预期，不复用 lowering 的 writer 选择。

测试每份普通 SV 参考图的所有输出都必须有实际 producer。调查发现当前
SV ingest 的直接 aggregate state forwarding 会留下无驱动 aggregate output，
所以参考 fixture 显式 concat 各槽形成 packed observation 端口，规定元素 0
位于低位。参考状态和动态写仍是数组；FIRRTL 的输入、状态、输出全保留原
shape。没有为通过对照而删除动态写、reset、旧值读取或宽度/条件构造。

F05 真实时序 node 首次覆盖 General/Output 双需求，从而发现原 verifier 把
合法 phase clone 视作重复根。分图 clone 现在写入 provenance marker；
同 source key 的多个根只允许分处不同非空 owner，最多一个未标记原件。
同 owner 重复、跨 owner 但未标记重复仍失败；标记不进入功能 CSE key，
rewrite 和 root carrier 保留标记。完整 F08 属性/clone 审计不因此提前完成。

## 验证命令与证据

构建和测试全部通过项目 Makefile。日志位于
`ptmp/firrtl-ingest/F05/`，测试工作产物位于
`wolvrix/build/artifacts/firrtl-state/`。模型生成 CTest 与消费同一目录的
模型编译顺序执行，不并行重建正在编译的目录。

| 命令 | 日志 |
| --- | --- |
| `make test_wolvrix` | `test_wolvrix.log` |
| `make test_grh_register_write` | `register_write.log` |
| `make test_grh_to_grhsim` | `grh_to_grhsim.log` |
| `make test_grhsim_cpu_st_cpp` | `cpu_st_cpp.log` |
| `make test_wolvrix test_firrtl_state test_firrtl_comb test_grh_register_write test_grh_to_grhsim` | `final-checks.log` |
| `make run_grhsim_cpu_st_cpp GRHSIM_CPU_ST_CPP_JOBS=8`（完整 CTest 重生成后消费最终模型） | `cpu-final.log` |

已验证：完整 CTest 73/73；FIRRTL state/node attributes/CSE scope 三项定向
检查；四份 state FIRRTL/SV 模型及三份组合模型实际编译运行；register-write
1/1，GRH→GrhSIM 及基础/方言 3/3；CPU suite 的生成 CTest 1/1，
首次 154 项模型用例编译运行通过；完整 CTest 重生成后的最终 154 项模型
用例再次全部通过，`cpu-final.log` 对应命令退出码为 0。

命令带 `WOLF_ENV_SOURCED=1`；完整构建使用
`CMAKE_BUILD_PARALLEL_LEVEL=8`，TMPDIR/CCACHE_DIR 指向本阶段 tmp/ccache。
定向入口的临时目录沿用 Makefile 各模块既有约定。

## 阶段边界

F05 不修改 F03 冻结输入及 manifest，也不据小用例声称香山整机仿真正确性或
性能收益。F00 剩余身份/性能基线仍待补；memory/effects/annotation 是 F06；
实例、真正 FIRRTL/SV 混合链接及 Python FIRRTL 请求配置是 F07；完整 node
CSE 和 node-aware nonsink 利用继续由 F08/F09 完成。
