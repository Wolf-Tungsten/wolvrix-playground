# TNO0362：干净默认生成入口的实现与小型回归

日期：2026-10-28。承接 [TNO0361](./TNO0361_grhsim_clean_default_flow_plan_20261028.md)。

## 实现

`make xs_grhsim` 与 `make build_xs_repcut_grhsim` 转入 [grhsim32.py](../../scripts/grhsim32.py)。不要求 `env.sh`，不接受历史 assignment/HGR/JSON 作为默认输入。每次建立新设计输出目录，依次运行当前源码前端、配置中的 mem-to-reg、六维权重提取、8 份独立求解、km1 择优、assignment replay、完整 preset 发射和原始 O3/native 编译。

前端和求解器辅助工具的 CMake 工程位于 [tools/grhsim32](../../tools/grhsim32/CMakeLists.txt)，链接本轮构建的 Wolvrix。求解器从公开 revision `135b23da324e6c35b0cde5a9a7db03200272f3b7` 构建。正常 CMake 依赖缓存可保留，设计中间产物重新产生。没有独立执行计划 gate、历史身份核验或中间源码/对象对比；迁移分析也使用不生成和复查输入哈希的模式。

memory 阶段仍为用户指定的控制实验口径：固定三个 memory，`row_limit=2`；这些值已进入 [默认配置](../../config/grhsim32.json)，不需要逐次填写。分区迁移的来源、目的地和完整 ASC 集合由当前生成结果的动态 profile 及通用提案、通信预算、排序工具决定。最终 emu 的功能检查与 walltime 测量保留。

生成使用本进程可用 CPU；最终运行按本机 NUMA/物理核拓扑选取 32 个 CPU，允许显式覆盖。没有固定 node030、CPU96–127 或 NUMA1。代码大页默认尝试 collapse，机器不支持时允许普通页；ASLR 根据本机权限设置。模型使用 `-std=c++20 -O3 -march=native -pthread`，不添加 no-SLP，保留生成 Makefile 中的 archive 成员顺序，并对齐可执行 section。

输出提供 `emu` 运行入口、`emu.bin`、package、初解及迁移测量报告。`make run_xs_repcut_grhsim` 重测最后的保留结果。旧手工 GrhSIM 入口保留为 `_legacy`，Verilator 入口不切换。

## 求解器的零维权重修正

实际小型 Verilog 回归发现，某些负载维度总权重为零时，原 fallback 在最小维度归一化处计算 `0/0`，造成目标分区编号保持无效值，继而越界。已将该修正加入版本化 [fallback patch](../../tools/grhsim32/mt-kahypar-fallback.patch)。这项修正不使用 workload 名称、分区编号或旧求解结果。

修正后，临时新建的 64 个独立反馈寄存器 Verilog 经前端产生 128 个 ASC、69 条超边及 6 个权重维度。8 个 seed 全部正常返回且满足容量条件；按完整图 km1 选择 seed 6，km1=22202（seed 7 同值，按 seed 破同分）。该例包含零权重维度，用于回归此次崩溃。

## 验证

40 项测试通过：默认流程 9 项（含上述真正从 Verilog 开始的原生求解回归）、critical profile 8 项、local search rank 5 项、piece candidates 6 项、旧 auto flow 5 项、backend 入口 7 项。Python 编译检查与 `git diff --check` 通过。原生工具和求解器均已从源码实际构建。

香山全量一键试跑已从 Verilog 启动；此时仍在前端转换阶段，没有完整 emu 或 walltime 结论。全量结果另立记录，不将小型回归当作香山端到端验收。

新 clone 的系统依赖、命令和输出位置见 [使用文档](../../docs/grhsim32.md)。
