# TNO0004 上游 RTL、schema 与 memory 选择

## merge 与 RTL

XiangShan 当前分支 `thj/kunminghu-v3-grhsim-merge-20261110` 已包含真实 merge commit `9d1f24cea2726642bfe04be545f7046f845735ed`，两个 parent 为 `77ed568fc` 和 `41ab74e7d`。相对上游，tree 只更改 difftest gitlink，指向 [TNO0002](./TNO0002_difftest_merge_port_20261110.md) 的 `b58c89454`。

after RTL 在独立 worktree 生成成功，make 总计约 1027 秒。之后 native build 通过 `--xs-source` 指向同一 commit 的独立源码，复用冻结的 `after/rtl-preparation`。before RepCut 的 trace/migration 完成前，原 checkout 中的旧子模块与 generated-src 暂时保留；最终再统一 checkout 到 merge gitlinks。

after native 首次启动发现 argparse 为可选 `model_difftest/compile_difftest` 提供 None，旧构造器没有将 None 解释为继承 runtime 默认。已修正并补回归测试；失败发生在构建开始前，日志保存为 `after-single-build.log`，重启日志为 `after-single-build-r2.log`。

## 本次比较的配置范围

按批准的约定，两侧都显式选用各自版本的 `DefaultConfig`。该名字对应的硬件规格本身发生变化：

| 项目 | before | after |
| --- | --- | --- |
| DefaultConfig | TLConfig 别名 | 上游新 DefaultConfig |
| L2 | 1 MiB，4 banks | 2 MiB，4 banks |
| LLC | 16 MiB TL L3 | 32 MiB OpenLLC |
| firtool | 1.135.0 | 1.149.0 |
| native C++ | Clang 23.1.2 | 同 before |
| RepCut C++ | node030 Clang 19.1.1 | 同 before |

因此，性能变化属于完整上游版本合并（硬件结构、默认参数、DiffTest 和生成依赖共同变化）；不能解释为某个单独 GrhSIM 后端优化的收益。工具完整身份见 [toolchain.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/toolchain.json)。

## DiffTest schema 与 NEMU ABI

实际生成的完整 DiffTestState：6216 → 4672 bytes（−24.839%）。commit/commit_data 宽度 8 → 16，store 49 → 3，refill 5 → 3，sbuffer 1 → 2；StoreEvent 48 → 64 bytes，并新增 highData、wLine、vecNeedSplit、eew、offset 等字段。前后 raw difftrace 不可直接逐字节比较。

两侧寄存器 ABI 均为 `ref_state_t=1400` bytes，offset 完全相同：xrf=0、frf=256、csr=512、pc=656、hcsr=664、vrf=800、vcsr=1312、fcsr=1368、triggercsr=1376。冻结 NEMU 的 `DIFFTEST_REG_SIZE=1400`，提供 init_v2。未启用 matrix/accelerator 状态。此为静态兼容证据，仍须完整 emulator 的 NEMU 检查。

## 三类 memory 的逐项核对

原先计划保持三类 FIFO 的语义选择。RTL hierarchy 与 Scala 连线核对表明：

| 原目标 | after 状态 |
| --- | --- |
| `core_with_l2$l2top$inner_buffers_2$nodeIn_d_q` | 仍存在，d-MMIO 两级 buffer 的 response queue，保留 |
| `socMisc$buffers_1$nodeIn_d_q` | 旧 LLC→mem_xbar TL 路径已被移除，不适用 |
| `socMisc$buffers_1$nodeOut_a_q` | 同上，不适用 |

原两项来自 `77ed568fc:src/main/scala/system/SoC.scala:324` 的 `!enableCHI` 分支；新默认路径通过 CHI/AXI 连接内存。`nocMisc$buffers_1` 虽名字相近，但属于 device_xbar→TLPMA，不能当作原 LLC memory FIFO。

after 独立配置只列仍存在的 L2 MMIO FIFO，row_limit=2、strict_init=false 与 before 相同。两项不存在的角色显式标为 removed-by-upstream-CHI-memory-path。公共 `config/grhsim32.json` 不变。

证据与配置：[memory-hierarchy.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/memory-hierarchy.json)、[memory-selection.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/memory-selection.json)、[after-repcut.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/configs/after-repcut.json)。后续 frontend 的 selected-memory gate 还会检查所选 symbol 真实存在且被转换。

## 资源和运行隔离

node030 生成前可用内存约 712 GiB，满足上游要求。after RTL 与 native emit 进程固定 CPU128–159，避开 before RepCut 的 CPU0–31。构建期观察时间不作为正式前后性能结论。正式 single 固定 CPU96，RepCut 固定同一 CPU0–31；不执行用户已取消的外部 CPU96–127 空闲准入检查。

## 增量：schema 审计归档

完整 header SHA、结构尺寸与偏移、NEMU ELF 常量及 init_v2 反汇编、7 项成功的 syntax check 命令/结果保存在 [difftest-schema-audit.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/difftest-schema-audit.json)。语法检查覆盖 GrhSIM/emu、checker 和 CONFIG_NO_DIFFTEST；不代替新生成模型的完整运行验证。
