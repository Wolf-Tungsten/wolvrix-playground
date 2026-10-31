# F08 完整 node CSE 与属性保真

状态：已完成（2026-10-31）。分支：`grh/firrtl-ingest`。
Wolvrix 实现提交：`5f31043`。

## 实现与验证

完整合约见 [node-cse.md](../../wolvrix/docs/ingest/node-cse.md) 和
[node-attributes.md](../../wolvrix/docs/ingest/node-attributes.md)。
实现采用完整局部 signature 的精确 intern，hash 仅选桶，memoized child term
避免 DAG 指数展开；来源名不参加功能判等，真实外部 ValueId/完整类型参加。
先分析全部等价类，再独立按组大小、位宽、不同后继数决定物理合并。
未合并上游的等价事实可用于下游，未合并计算的成员作用域仍独立。

| 要求 | 结果及证据 |
| --- | --- |
| GSIM 门槛边界 | 4/5、256/257、1/2 后继及重复 operand 单计全部通过 |
| 判等精度 | 有序参数、功能 attrs、常量 payload、signed/domain/shape 差异；全 hash=0 的精确 intern 碰撞测试通过 |
| 保守候选 | 数组、多结果、state read/history、常量、不完整/逃逸区域均跳过；不提前抽取跨 node 公共内部 And |
| 等价事实与共享分离 | 两份小 And 不物理合并，其两个 257-bit 下游仍正确合并 |
| 来源与实例 | 多源 roots/members、输入 alias、合法 DCE；真实两 child 实例不同输入不误合并，inventory 与实例路径一致 |
| 持久化与身份 | sparse IDs 经 clone/freeze/符号 rename/JSON 后保持相同共享与4096组输入行为；幂等通过 |
| checkpoint/identity | off/gsim 全阶段恢复、配置切换拒绝、旧 policy 拒绝、后段恢复字节一致、生成身份包含 policy/config |
| 真实完整流水线 | FIRRTL ingest → 普通生产 transforms → convert/pack/masked-OR/CSE → JSON → phase/nonsink/sink；256步状态行为一致 |
| memory/effects | 真实 state/masked memory/multi-clock 128步 oracle；effects 顺序使用编译记分板，bit-vector oracle 不解释字符串 |
| 意外丢失 | 清空真实 node attrs 后 retention 必须失败，不能冒充 DCE |

## 生产变换审计

| 入口 | 本阶段规则与验证 |
| --- | --- |
| XMR resolve | replacement 前转移 roots，输入/无关 producer 用 assign view，重绑 graph output；原结果 ID 在创建 op 前 snapshot；tagged XMR 回归 |
| mux-tree-fold | annotated producer 为结构匹配屏障，跳过 annotated mux/slice 根；合法死锥删除显式记账；普通 SV 优化保持原路线 |
| register-write-normalize | strip/collectArms/pruneHolds 遇 tagged 表达式保留为不透明 data arm，避免跨 node 抽取 mux 控制 |
| memory-read-retime | ROM/RAM 两条替换均重定向 roots/output；两个 tagged read 结果根专项通过 |
| hier-flatten | ops 与 inventory/tombstones 使用同一真实 instancePath 限定，混合 FIRRTL/SV 多级路径及两个 child 输入回归 |
| ordinary simplify/CSE/DCE | 沿用 F02 scope/root helpers；primitive CSE 同成员域；DCE 才可记录源结果删除 |
| grh-to-grhsim | 原位变换保持 attrs；已有 source policy 必须兼容，不替旧 graph 补策略 |
| used-bits/state merging | 计算原位改类型/操作数；新 lowBits/makeOperation 复制 members；源 node 不标 state declarations/writers |
| bit packing/masked-OR | read 改 slice 保持 op/result attrs；新内部 op 复制 members；跨节点融合受 mayInline/sameScope 限制 |
| phase/sink/clone | clone 全 attrs/result mapping 加 nodeClone，真实 owner 分离；leaf CSE 不跨 owner；partition-sink 在 schedule stamp 前记录 census |

retention 是 source-result 可用性审计，不能把它表述成每个原始 primitive 的
不变性校验。合法变换可删除/重写成员；内部作用域由生产变换规则及回归保证。

## 执行命令

命令均通过根 Makefile；使用 `WOLF_ENV_SOURCED=1`，Python 指定 `.venv`。
生成与消费同一模型目录的流程顺序执行。

| Make 入口 | 实际结果 | F08 日志 |
| --- | --- | --- |
| `test_grhsim_node_cse test_firrtl_node_pipeline test_wolvrix inspect_firrtl_node_retention` | 定向各1/1、最终78/78 CTest，含tagged XMR/retime；真实 RenameTable gsim检查通过 | `final-audit.log` |
| `test_firrtl_node_pipeline test_firrtl_node_attributes test_firrtl_cse_scope test_grhsim_transforms test_grhsim_readable_store inspect_firrtl_node_retention` | pipeline/attrs/scope各1/1、transforms 4/4、readable 3/3 | `regressions-second.log` |
| `test_wolvrix test_firrtl_comb test_firrtl_state test_firrtl_memory test_firrtl_effects test_ingest_mixed` | 78/78及组合、状态、memory、effects、11个混合源编译模型全部执行通过 | `full-regressions.log` |
| `test_grhsim_node_cse test_wolvrix run_grhsim_cpu_st_cpp` | 78/78；选取16/1024预算的phase、sink-private、effects、snapshot-identity共8个CPU模型编译执行通过 | `final-ctest-cpu.log` |
| `py_install` 后 `test_grhsim_flow test_ingest_python test_grhsim_provenance run_hdlbits_test run_hdlbits_grhsim` | Python 3/3+8/8+3/3；flow全部SV checkpoint模型执行；DUT001普通SV/GrhSIM均通过 | `python-hdlbits-final.log` |
| 最终 `py_install test_grhsim_flow test_ingest_python test_grhsim_provenance` | 最新实现包重新安装，Python 3/3+8/8+3/3及flow生成模型编译执行通过 | `final-package-flow.log` |
| `inspect_firrtl_node_retention FIRRTL_NODE_CSE=off` | real hierarchy及JSON往返通过 | `retention-off-final.log` |

早期缺依赖、缺 include、string oracle 不适用等失败日志不作为通过证据；
补齐依赖/使用编译 effects scoreboard 后的最终日志为准。

## 大模块属性成本

冻结 `SimTop.fir`：1,671,325,062 bytes，SHA256
`cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
选择 RenameTable，递归 lower 自包含 FIRRTL 依赖（含 SnapshotGenerator_4），
未 lower 整机或替代 shared mixed frontend。报告为
`RenameTable-{off,gsim}-retention.txt`，每份2504 bytes。

| 指标 | off | gsim |
| --- | ---: | ---: |
| flatten 后 source nodes | 2230 | 2230 |
| 最终 operations | 19493 | 19484 |
| 最终 available / proved-dead / missing | 2070 / 160 / 0 | 2069 / 161 / 0 |
| 参与重复等价组的 nodes | 19 | 19 |
| 合并 / 未共享组内 nodes | 0 / 19 | 8 / 7 |
| threshold命中：count / width / fanout groups | 0 / 0 / 0 | 1 / 0 / 4 |
| key references | 9481 | 9478 |
| key bytes / unique key bytes | 587106 / 127263 | 586866 / 127183 |
| JSON checkpoint bytes | 20031601 | 20020953 |
| 同图去掉node信息的JSON bytes（仅测量） | 18571292 | 18562625 |
| node序列化增加bytes | 1460309 | 1458328 |
| inspector wall / max RSS (KiB) | 4.26 s / 1992524 | 4.12 s / 1991856 |

最初74013 ops/2156 nodes有47438次key引用、2921349 key bytes；flatten后
48216次/2992078 bytes；优化后约9478次/586866 bytes。未传播全上游闭包。
真实 key 仍是标准 attribute 字符串，尚未增加全图字符串池，统计不冒充
分配器独立开销；RSS含整个1.67GB源文件映射和索引。时间为单次热缓存
表示成本检查，不能当仿真性能对比，也不声称整机提速。

## 后续边界

F09 的 node-aware nonsink 初始工作单元尚未实现；当前 nonsink 仍走既有
op分图。F10整机混合输入等价及F11性能消融继续待实施。完整node CSE仅
接受可证明完整的标量纯组合区域，其余保守保留并报告。

实现和验证日志位于 `ptmp/firrtl-ingest/F08/`，测试模型位于
`wolvrix/build/artifacts/`，不提交生成的香山源或模型。
