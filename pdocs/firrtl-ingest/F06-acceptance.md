# F06 memory、效果及目标版本特性验收

状态：已完成（2026-10-31）。实施基点为主仓 `766259d`、wolvrix `f38084a`，分支均为
`grh/firrtl-ingest`。本文件不以 parser 成功代替行为验收。
实现提交为 wolvrix `60ee737`；共享字面量 node provenance 的独立修复为
`8f4a4a4`。两者均已提交，未推送。

## 推进与退出清单

1. 标准 mem 和 CHIRRTL cmem/smem/mport 统一描述；保留数据 shape，复用
   既有 memory/数组状态及必要流水状态，定义端口方向、clock/enable、latency、
   mask、read-under-write、冲突和越界语义。
2. printf/stop/assert 及冻结输入使用的 intrinsic 映射到现有效果机制；验证
   触发条件、旧值采样、执行次数、顺序和终止行为。
3. 按冻结输入构造矩阵处理 layer、Probe/引用及 annotations；验证层显式配置
   并可追溯。初始化/随机化策略具有身份，未知功能/观察语义明确失败。
4. 不含外部依赖的目标模块端到端运行；外部引用有明确绑定请求，不以空实现
   伪装成功。混合绑定仍为 F07。
5. 新增 `make test_firrtl_memory`、`make test_firrtl_effects`；复验
   `make test_transform_memory_read_retime`、完整 CTest 和 CPU 生成/执行用例。
6. 更新正式支持文档、架构合约与逐项证据，通过后再标记 F06 完成。

## 证据约定

日志与临时材料使用 `ptmp/firrtl-ingest/F06/`；回归 fixture 使用
`wolvrix/tests/ingest/data/firrtl/` 下独立目录，不改动 F03 冻结 fixture。
生成模型沿用 `wolvrix/build/artifacts/`。构建、测试和工作流脚本均通过项目
Makefile；生成和编译同一模型目录时顺序执行。

## 已取得的直接证据

| 要求 | 实现及证据 |
| --- | --- |
| 标准 mem 和 CHIRRTL 统一表示 | `firrtl/memory.cpp` 的 Memory/MemoryPort 与 `lower.cpp` 的数组状态 lowering；普通 GRH verifier 和 JSON 往返全部通过 |
| 时序/mask/越界 | `make test_firrtl_memory`：15 组同钟 old/new/undefined × latency，12 组独立读写时钟，各 140/480 次周期或时点；3 组 node/wire 时钟别名矩阵与 masked/multi-clock/chirrtl/bundle-rdwr/depth-one/cmem/standard 合计 37 个模型。普通 GRH 与完整后端编译执行、重复 init；最终结果见 `final-boundaries-target.log` |
| 未定义值不静默变零 | FourState Oracle 明确观察正常读数、冲突 X、历史 X 的传播/清除、禁用读 X；TwoState 仅由后续既有转换显式选择。回归见 `test_firrtl_memory.cpp::fourState` |
| 端口方向与部分写 | inferred mport 的动态 lane、两个静态 lane、覆盖优先级、OOB 和零写 mask；Bundle rdwr 的 120 周期独立记分板核验任一字段写入统一关闭本端口全部读字段、其他存储字段不变；depth-one 零宽地址标准 readwriter；非法 clock/const writer/inferred const writer/零 depth 拒绝 |
| 效果次数、旧值采样和顺序 | `make test_firrtl_effects` 的 ordered driver 精确比较 stdout；无边沿/disabled/repeated eval 不新增效果；cover 注释百分号按字面输出并有非 formal 警告 |
| 终止行为 | stop、negative stop、assert、assume、目标 ifelsefatal 独立进程比较退出码和 stdout/stderr，验证 before 存在、after 不执行；共 8 个 compiled effect 模型 |
| layer/Probe | 显式完整路径选择、嵌套祖先、disabled 不生成效果、JSON 配置持久化；aggregate/indexed Probe、alias 和 when 内无条件 define；invalidate 跳过 Probe、不能代替 define；普通/聚合 connect、重复/缺失/错误方向/越层读写/错误 color/错误 nesting 拒绝；接口保留 Probe/RWProbe 的待解析 ABI 身份 |
| annotation | 五类冻结 schema、DontTouch 保留符号、inline SV payload 持久化；unknown/额外字段/错目标/circuit/Unicode surrogate 拒绝并指向 JSON 记录 |
| 初始化/随机化身份 | storage/pipeline InitSpec 使用既有 initPolicy；invalidPolicy 单独记录。history/collision 的确定零启动是仿真事件历史；不发明随机化，不识别的初始化 annotation 明确失败 |
| 原始目标模块运行 | `make test_firrtl_target` 读取原始 1.67 GB 文件及全部 annotation，选择 Queue2_TLBundleA、sram_array_1p128x138m69s1h0l1b_icache_meta、JtagBypassChain；250/220/200 周期独立记分板及完整后端执行通过，Queue/JTAG 同时核验普通 GRH，SRAM 使用独立记分板对照编译模型；JTAG 启用 Verification.Assert 并核验非法组合 fatal；最终日志 `final-boundaries-target.log` |
| 外部引用 | 具名实例/external binding 诊断，保留 signatures/defname/parameters；inline payload metadata 保留。不以 kBlackbox 伪装成功，混合链接仍 F07 |
| 正式文档 | `wolvrix/docs/ingest/firrtl-{memory,effects}.md`，架构 5.2 和公共 reading/parser/state 文档已同步 |
| node provenance | 死 node 可以留下共享字面量来源，不能留下无 root 的活非字面量计算；`test_firrtl_node_attributes` 及 JSON 往返回归；独立提交 `8f4a4a4` |

最终验收命令已以退出码 0 完成：`final-acceptance.log` 中完整 CTest
75/75、memory-read-retime 1/1、CPU generator（全量 CTest 中）、全部
154 个 CPU 模型编译执行、37 个 memory 模型及 8 个效果模型编译执行、
输入校验 4/4、冻结输入复验通过（10,008 个模块、2,146 份 SV/头文件）。
定向最终验收 `final-boundaries-target.log` 已退出 0，包含 37 个 memory、
8 个效果模型、node 属性回归及原始目标三个模块的编译/执行和 fatal 核验。

实际命令均带 `WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=8`，
TMPDIR/CCACHE_DIR 使用 F06 tmp/ccache；定向 target 内部沿用其各自工作
目录约定，不并发生成与消费同一个模型目录。最终全量顺序命令为：

```sh
make test_wolvrix test_transform_memory_read_retime run_grhsim_cpu_st_cpp \
  test_firrtl_memory test_firrtl_effects test_firrtl_parser_inputs verify_firrtl_inputs
```

最终日志为 `final-acceptance.log`。完整 CTest 包含 CPU generator；之后
`run_grhsim_cpu_st_cpp` 消费本轮新生成的全部 CPU 模型。

| Make 命令 | 最终结果 | 日志 |
| --- | --- | --- |
| `make test_firrtl_memory test_firrtl_effects test_firrtl_node_attributes test_firrtl_target` | 全部通过，退出码 0；包括新增聚合 Probe/Bundle rdwr 边界与原始三个目标模块 | `final-boundaries-target.log` |
| `make test_wolvrix test_transform_memory_read_retime run_grhsim_cpu_st_cpp test_firrtl_memory test_firrtl_effects test_firrtl_parser_inputs verify_firrtl_inputs` | 全部通过，退出码 0；全量回归后顺序消费重新生成的模型，冻结身份与统计无变化 | `final-acceptance.log` |

逐项退出条件均已具备直接证据。F00 整机依赖/性能基线、F07 混合绑定和
F08/F09 完整 node CSE/nonsink 利用保持其独立阶段状态，本阶段不作整机
等价或性能提升承诺。

## 支持边界

F03 保留的广泛语法不代表 F06 要执行所有方言：enum/match、property/class、
force/release、fprintf/fflush、未知 intrinsic 和时间/层级特殊格式不在冻结
目标必要执行矩阵中，均明确拒绝。F07 负责跨模块/跨语言链接和 Probe ABI。
保留 Inline/Dedup/Decode 的优化来源不改变已 elaborated 的功能逻辑。
无 CIRCT 链接或调用，不提交目标大文件、生成模型或日志。
