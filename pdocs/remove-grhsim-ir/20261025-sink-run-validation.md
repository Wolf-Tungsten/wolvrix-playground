# Sink run 发射与函数预算修复

状态：sink-run 版本局部生成执行、冻结观测、公共回归、ROB 原始 SV 全输出及 XS 100k 已验证；后续 idle-dispatch 修订、原生动态诊断与正式性能门禁尚未完成，R5/R6 不据此验收，R7 未开始。

## 发射职责

`emit/grhsim/cpu-st-cpp.cpp` 直接消费已有 SinkSchedule 的连续 run，不另建调度计划或虚拟分区：

- General 中每个 run 计算一次共享纯锥，先计算公共 guard，再在使能条件内计算 payload，按 orderedWriters 发射原写口。
- fire 仍由 Event 的 detector/OR grammar 决定；同沿的连续 run 可共用外层 fire guard，但不交换写口。
- LargeSink 提交按原 largeCommitRuns/orderedWriters 发射，连续相同 bitmap word 共享外层检查；写参数仍来自 General 快照。
- `writer_runN`/`commit_runN` 是 C++ 函数组织名称，受同一 max-function-lines 拆分，不写入 GRH 分区属性，不增加跨 pass 数据。

新增反例保留 small/large 各 48 个状态和写口，分为两个 enable 组；不同初值阻止合法状态合并缩小测试。粗 sink 内先 CSE 共享 payload，再做最终时钟/门控分组，检查 4 个 General run 各有 24 writer、2 个 LargeSink commit run。两种函数预算、三次 init、64 步均核对全部 scalar/array 输出。

## 分块停滞

首次 tiny-budget 矩阵停在模型生成，日志为 `ptmp/remove-grhsim-ir/r6-sink-run-matrix.log`。将一个局部声明很多的单 guard 移入 helper，并不会减少该 helper 的声明数；原逻辑可以继续包裹同一 guard，不能收敛。

function writer 现在在语句结构能满足预算、只有私有声明超限时，将这组局部值持久标为 frame 字段。重新分析保留这个决定，根函数创建 frame 的行数也进入预算；原局部初值和源函数寿命不变。新增 20 个带非零初值的局部值、单 guard/statement 反例，验证生成终止、实际函数行数及重复调用结果。没有增加重试上限、放宽预算或引入新虚拟分区。

## 已完成验证

全部命令通过项目 Make target 执行；日志目录均为 `ptmp/remove-grhsim-ir/`。

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| 生成/执行与实际函数行数 | 42 模型及七万字段构造通过 | r6-sink-run-frame-matrix-distinct-init.log |
| 安装 | make py_install 成功 | r6-sink-run-install.log |
| 公共回归 | 74/74，105.33s | r6-sink-run-public.log |
| 冻结观测 | 8 fixture、168 记录，accepted=true；原始 equal=false、18 项已批准差异、未解决项 0 | r5-observations-source-order/comparison.json |
| 重启/静态读者 | 10 生成模型、provenance 3、reader 16、tooling 12、历史 paired 31 通过 | r6-sink-run-flow-readers.log |
| HDLBits | 162/162 | r6-hdlbits-sink-run/logs/summary.txt |
| bugcase | 27/27 | r6-bugcases-sink-run.log |
| 生产依赖审计 | 30 源文件、13 编译产物，无独立 IR 引用 | r6-sink-run-production-audit.json |
| ROB checkpoint 重发全输出 | 4,394,996,424 bytes 完全相同，exclusions=0 | r6-rob-sink-run/comparison.json |
| ROB 原始 SV 完整重生 | 相同字节数/摘要，exclusions=0，243.998s | r6-rob-sink-run-fresh/comparison.json |

ROB 全输出 SHA256 为 `688ac2f6e9c5509eb00dad368ead600a07ec27d956b1ec9a429d8e46309a7df1`，输入 trace SHA256 为 `cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1`。先做 checkpoint 重发，后在独立 r6-rob-sink-run-fresh 从冻结原始 SV 完整重生，两者分别报告来源，不相互替代。生成 sidecar 绑定源文件/加载库与生成源码；比较报告另外绑定库/可执行文件、bench 和输入，并在比较前后检查身份。

冻结观测按[两项明确的用户决定](20261025-single-call-decision.md)分类：一次原调用及共享 held sample；独立调用保留原图顺序。trigger、参数、返回值、inputs/outputs/states 均未豁免，冻结日志与历史严格报告未改写。

## 规模与性能证据边界

相同 checkpoint/config 的 manifest 中，ROB 函数由 51,247 减至 25,607，定义行数由 3,271,523 减至 3,094,289，nonsink 超节点仍为 2,260。XS 函数由 501,473 减至 357,238，定义行数由 28,170,956 减至 26,918,472，nonsink 超节点仍为 36,656。这证明函数组织变化，不证明性能通过；TU 数还受实际函数文本打包影响，不能从行数直接推断编译时间。

本轮 ROB 全输出运行 362.606s；同时有 XS 编译。2000 周期交替诊断固定 CPU 0，预热后 3+3，checksum 均为 14806783039636027445；旧/新中位数 6.63992s / 2.45189s。旧侧是冻结静态库重新链接的探针，不是历史全输出重放程序；当前主机负载与上一轮不同，这些数字不构成正式运行、生成、编译或 RSS 门禁。

profile 分类器同步识别 writer_run/commit_run 及其 chunk，避免将 sink 成本漏归为 main_other；保留前版按 writer 的函数名。短程探针拒绝零运行时间，避免比值除零。工具测试记录在 `r6-sink-run-profile-tools.log`。

最新原 SV 重生分别用 /usr/bin/time -v 包装 Make 目标记录：生成 wall=4:04.09、最大 RSS=9,614,160 KiB，编译 wall=2:37.61、最大子进程 RSS=510,192 KiB；日志为 r6-rob-sink-run-fresh-generation/build.time。这些是本轮单次观测，运行期间有其他工作；编译字段也不是四个并发编译进程的同时 RSS 总和，不能冒充受控旧/新生成/编译/RSS 门禁。

## 正式 XS 运行计时入口

`make benchmark_remove_grhsim_ir_runtime` 单独承载迁移运行门禁，复用现有 XS Make 运行入口。冻结旧程序复制到隔离 flow；候选也有独立运行目录，模型源/身份只读引用原生成目录，不写冻结目录。先核对旧程序及 CoreMark/NEMU 输入与冻结摘要，再执行 old0/new0 两次完整预热，预热不计入随后 old1/new1/old2/new2/old3/new3 的统计。每次都验证 seed=0、difftest、100k 周期和相同指令/PC 终点，保存 Host、wall 和运行进程最大 RSS。

按冻结政策判定 Host 中位数回退 ≤3%、运行 RSS 中位数回退 ≤5%；每侧 Host 极差/中位数超过预先登记的 5% 时报告 NOISY，不宣称通过。它不复用优化实验的 max(new)<min(old) 排名门槛，不将 2% 的允许回退误判为失败。5400s 单次超时仅为运行保护，不是观测到的旧基线。程序、输入和候选身份在运行前后绑定；原始记录/批准差异的口径不变。

`make test_benchmark_grhsim_ir` 六项测试通过，覆盖预算/排名区别、噪声、缺失/无效样本、预热排除，以及模拟八次 Make 调用的完整入口与冻结身份拒绝；这些是工具测试，不是实际 XS 性能结果。最终日志为 r6-migration-runtime-gate-tests-final.log。

实际计时已在 CPU 4、r6-xs-runtime-ab-v1 启动，登记顺序、门槛与身份见该目录 preregister.json；计时器代码/Make 驱动副本与摘要也保存在同目录。完整预热结束，正式样本仍在进行，未取得 3+3 结论；当前样本及后续 emitter 修订见[补充记录](20261025-native-counters-and-idle-dispatch.md)。

## 未完成项

- `xs-sink-run` 已执行 100k，difftest 无 mismatch、退出 0，Host=2215.470s；日志依次为 r6-xs-sink-run-reemit/build/run.log。后续 idle-dispatch 修订仍需整机验证。
- ROB 最终完整原 SV 生成与同输入全输出已通过；旧/新受控生成/编译 wall、并发峰值内存门禁仍未完成。
- 受控的正式交替 3+3，运行回退不超过 3%，生成/编译/RSS 回退不超过 5%；不能以本轮有并行负载的短程诊断代替。
- 原生动态图计数绑定/定价已实现并通过局部测试，最新真实 ROB 和整机证据仍待补齐；不复用旧 mapping ID，历史静态读取不替代动态门禁。
