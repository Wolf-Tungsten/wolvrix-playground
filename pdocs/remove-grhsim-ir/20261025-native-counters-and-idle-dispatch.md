# 原生执行计数与空 sink 调用

历史记录：本文保留 sink-run、idle-dispatch 和插桩版本各自的结果及当时边界。当前工作树的 R5/R6 验证、真实 ROB 动态计数/family 与模块来源见 [2026-10-26 验证报告](20261026-r5-r6-validation.md)，阶段状态以 [PROGRESS](PROGRESS.md)为准。

## 已完成结果

- sink-run 版本 XS 独立执行结束，100,000 host cycles、238,535 committed instructions、cycleCnt=99,996、guest cycles=100,001、PC=0x80000cde；difftest 开启，退出 0，Host=2215.470s。证据：`ptmp/remove-grhsim-ir/r6-xs-sink-run-run.log`。这是正确性结果和单次计时，不是正式 A/B。
- idle-dispatch 公共回归 74/74，104.92s；统一图重启 10 个模型、provenance 3 项通过，见 `r6-idle-dispatch-public-flow.log`。
- 原生计数 11、原生 GRH reader 16、历史 family 23、历史 paired 31、tooling 12 项通过，见 `r6-idle-dispatch-readers-final.log`。此前 counter 测试因公共 CTest 清理了 fixture 运行日志失败，已补 Make 依赖及两个插桩模型的执行步骤，未将失败回填为成功。

## emitter 改动

General 的连续 sink run 在 fire 为假时跳过函数调用；已由 nonsink 采样的外部 boundary guard 可在调用处检查，属于当前 sink 的 guard 仍在函数内求值。LargeSink 的连续 run 保留原 writer 顺序，单个 bitmap word 的空 run 在调用处跳过；跨 word run 保留内部检查。没有新增虚拟分区或跨 pass 计划。

最新 idle-dispatch XS 候选在独立 `xs-idle-dispatch` 目录从 sink-partitioned GRH checkpoint 重发并编译；它不是原始 SV 完整重生，也不改正式 A/B 正在使用的 sink-run 候选。最终整机及性能结果尚待补齐。

## 动态计数契约

`execution-counters=on` 是默认关闭的 emitter 诊断选项；Python `emit_grhsim_cpu_st_cpp` 接口提供 `execution_counters=False`，重发入口提供 `--execution-counters`，Make 提供 `GRHSIM_REEMIT_EXECUTION_COUNTERS=1`。默认和显式 off 的生成文件逐字一致。

开启后生成选定 top 的原生 GRH 快照、manifest 中的 sites、绑定信息及 `dump_execution_counts(FILE*)`。每个 site 关联实际 operation symbol、源函数和类别：`operation`、`effect`、`writer-sample`、`writer-commit`、`history-write`。effect 记录 guard 内真实调用，writer 记录访问次数而非成功写入次数，evals 不是硬件 cycles；初始化重置计数，随后初始化期间实际访问仍计入。view-only assign 另列为 elided operations。

绑定包含完整 GRH、sites 和全部生成 C++/header；唯一 dump tag 在绑定时归一化。FNV1a64 用于一致性核对，报告额外提供 SHA256，不声称 FNV 具备密码学认证能力。读者拒绝错图、源码/header/guard 改动、缺失或重复 site、截断、溢出以及两次运行不一致。

原生 family/paired 诊断可读取这组计数，以真实 operation visits 对 final 同图写口数据锥定价，共享 union 只计一次；缺失成员与无法还原的 packed 原成员报告 unpriced，不补零、不借用旧 mapping ID，也不声称旧 G1–G4/gsim 已有动态归一化。

首次真实 ROB 插桩诊断位于 `r6-native-rob-counters`：2,000 trace cycles、4,000 eval、checksum=14806783039636027445，两次独立运行计数相同；756,880 sites、operation=1,107,616,406、writer-sample=61,039,050、writer-commit=28,201,460。该模型早于完整 C++/header 绑定及 idle-dispatch 修订，最新 reader 会拒绝其缺失 binding_files 的 manifest，因此只保留历史诊断，不能作为最新门禁。

## 性能证据与待办

CPU 2 上 sink-run 版 XS 前 10,000 cycles 的 perf 定位完成，Host=197.928s、39,488 samples、lost=0。按整数 Period 汇总：writer 43.857%、commit 35.001%、nonsink 7.143%、publish 6.401%、General dispatch 2.236%、event 0.505%、output 0.023%、memory 2.252%、other 2.582%。保留内核符号权限警告；该短程采样不是正式性能门禁。证据：`r6-xs-sink-run-prefix-profile.log` 和 `xs-sink-run-prefix-profile/prefix.perf-all.txt`。

正式 CPU 4、完整预热后交替 3+3 的 sink-run 门禁继续在 `r6-xs-runtime-ab-v1` 运行，冻结 runner 与候选身份不改。当前已记录旧/新预热 Host=636.587s / 2122.342s、old1=265.705s；完整样本尚未结束，不能发布正式中位数或通过结论。已有结果提示明显运行回退，仍需定位 writer/commit 成本。

剩余：最新绑定版本的真实 ROB 两次计数与定价；最新 emitter 的 ROB/XS 验证；XS 原始 SV 完整重生；受控旧/新生成、编译和并发峰值 RSS；最终 3+3 运行门禁。

## 后续 private-payload 与 frame 修订

private-payload 按精确 enable 反向传播需求：fire/enable、跨 enable 共享锥和持久 boundary 无条件求值，同 enable 的私有纯 payload 在首次 writer 访问时求值一次。每个 writer 仅继承无条件 pack 缓存，避免复用另一条未执行分支里的 pack。该版本完整生成执行矩阵、公用 74/74、flow 10、provenance 3、reader 16 和 tooling 12 已通过；日志为 `r6-private-payload-matrix-final-install.log`、`r6-private-payload-public-flow.log`。

最后追加的 same-enable 调用处 guard 经审查补充了可观测边界限制：存在 sink 内的持久结果（含 declared waveform value）时不得因为 writer enable 为假跳过整个 run。`testWaveformContents` 新增 disabled writer 的 sink-local declared payload，在两种函数预算和三次初始化下读取真实 FST，验证值仍在有效时钟沿刷新、状态不写入。`r6-observed-payload-matrix.log` 完整生成执行通过。该修订晚于 `xs-private-dispatch-fresh` 开始生成时加载的库，不能将这个在途模型称为最终 emitter 版本。

检查旧 `SixPhaseEmitter::frameNeedsZeroInit` 后，新 writer-run 的纯锥/read、pack、index 和 writer temporary 改为先赋值后使用，省去其默认局部量和 chunkFrame 的冗余清零；其他函数默认策略、显式 initializer 和跨块 return-control 仍保留初始化。`r6-assigned-frame-matrix-install.log` 的完整执行矩阵及安装通过；公共回归、独立 `xs-assigned-frame` 候选和整机实测仍在途。没有改变分区、SinkSchedule 或 chunk 行数约束。

真实 ROB v2 插桩位于 `r6-native-rob-counters-v2`：两次 2,000 trace cycles/4,000 eval，checksum=14806783039636027445，756,880 sites；operation=1,054,771,383、writer-sample=49,717,194、writer-commit=28,201,397、compute-operation=958,412,470，effect/history=0、elided=117。最新绑定 reader 验证图/sites/全部源码和两次计数一致。`r6-native-rob-families-dynamic-v2/summary.json` 定价 231 states、10 families，union=441,505 compute visits；输入是 final 同图快照，不能称原始成员迁移全量对照。该版本早于最后 dispatch/frame 修订。

idle-dispatch 的 XS 10k 定位完成，Host=139.114s；按整数 Period 汇总 writer=65.785126%、commit=7.162192%、publish=8.375866%、nonsink=10.150578%、general=2.959434%、event=0.697172%、output=0.010941%、memory=2.925279%、other=1.933411%。这是与 sink-run 的独立短程定位记录，不能替代正式 A/B。

冻结旧绑定的隔离 import smoke 曾通过，见 `r6-frozen-binding-isolated.log`；但这不证明 C++ ABI 匹配。补充冻结库在完整 XS ingest 中于 `grh::Design::~Design()` 崩溃，见 `xs-frozen-ingest-debug-v2/gdb.log`。归档头的默认构造布局与补充库的强定义 `Design::Design()`/新增描述符符号不符，故不能将补充库与 R0 头文件配成有效的冻结编译器。失败测量 `r6-xs-frozen-generation-resources-v1` 原样保留，不计入生成性能证据。

随后从 R0 归档全部旧源码、头和绑定独立重建旧编译器，依赖 revision 与 manifest 核对，见 `frozen-compiler/source-identity.json` 和 `r6-frozen-compiler-build.log`。重建成功且无上述 ABI 崩溃，但完整冻结 XS 原 SV 的 ingest 失败于 `kArrayCreate elements must have identical full types`，见 `xs-frozen-source-fresh-measured-v2/generation.log`。`r6-xs-frozen-source-generation-resources-v2/result.json` 为 FAILED/exit 2，wall=43.423s、峰值同时 RSS=27,645,156 KiB；这是失败定位，不能当作成功生成的基线。冻结原件未修改，生成性能门禁仍缺少可运行且来源一致的旧侧。

`generate_remove_grhsim_ir_xs_frozen` 现在使用上述完整归档源码重建的旧编译器；历史 binding-only 目标仅保留作定位入口。`measure_remove_grhsim_ir_resources` 记录整个 Make 进程树同时 RSS 总和（50ms 采样，共享页逐进程计数，有短峰漏采限制），不是最大单子进程 RSS。每次测量先登记输入、工具链、生成源码身份，拒绝复用输出及带对象/PCH 的非净编译目录。工具回归分别 14/14 和 3/3 通过，见 `r6-frozen-compiler-tools.log`。

原 sink-run 正式 A/B 已结束，原注册与身份保持不变，见 `r6-xs-runtime-ab-v1/summary.json`：old=265.705/328.225/371.160s，new=2029.371/2207.131/1968.372s；Host 中位数 old/new=328.225/2029.371s，new/old=6.182865；RSS 中位数 old/new=190,856/209,352 KiB，new/old=1.096911。old/new spread=32.128875%/11.765173%，classification=NOISY，noise/runtime/RSS 三项均不通过，accepted=false，driver exit 2。所有样本 endpoint 正确且 difftest 无 mismatch。该失败属于 sink-run 版本，不能代表后续候选性能；也不能调整 3% Host/5% RSS 门槛或静默覆盖重跑。

private-payload 候选的 XS 10k perf 已完成，见 `r6-xs-private-payload-prefix-profile.log` 和 `xs-private-payload-prefix-profile/prefix.perf-all.txt`：Host=90.287s，18,020 samples，lost=0，整数 Period 总和 457,039,032,814。按整数 Period 分类 writer=62.983842%、commit=8.866927%、publish=8.651782%、nonsink=10.305551%、general=3.479132%、event=0.750657%、output=0.010859%、memory=3.821175%、other=1.130076%。endpoint instr=458、cycleCnt=9996、guest=10001、PC=0x800027c6，difftest 无差异。这是热点定位，早于可观测边界及纯 writer frame 修订，不是最终候选或正式 A/B。

最新 assigned-frame 局部验证已完成：公共 74/74（135.23s）、flow 10、provenance 3、原生 reader 16、resource tools 3；计数回归 11，冻结逐次观测 8 fixture/168 记录，18 条用户批准原始差异、0 未解决项，equal=false、accepted=true。日志分别为 `r6-assigned-frame-public-flow.log`、`r6-assigned-frame-counters-observations.log`，比较报告为 `r5-observations-assigned-frame/comparison.json`。HDLBits 162/162 和 bugcase 27/27 均通过，见 `r6-hdlbits-assigned-frame/logs/summary.txt`、`r6-bugcases-assigned-frame.log`。最新 ROB 原 SV 重生已成功，后续全输出比较与 XS 编译/执行仍在途。R5/R6 继续未验收，R7 未开始。
