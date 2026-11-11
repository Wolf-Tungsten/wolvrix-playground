# F24 历史原始记录：截至 v11 启动

本文件冻结保存结构化整理前的完整原文，供排查历史判断、配置变更和原始证据。
**不再追加，不作为当前状态或验收结论。** 其中标记“当前”“下一轮”的表述均为
当时记录；旧基线、旧假设和旧配置可能已被后续结果取代。

当前结论、阶段及累计耗时、验收矩阵和证据索引统一见
[F24 主文档](F24-xs-firrtl-grhsim.md)。

以下为原文。

# F24：XiangShan FIRRTL → GrhSIM 联调流水线

建立日期：2026-11-10。目标输入固定为 XiangShan 全图 `SimTop.fir`，激励为
CoreMark 100k，运行启用 difftest。生产入口是 `make xs-firrtl-grhsim`；该
目标必须把每个阶段的开始、结束、耗时、退出状态写入 `ptmp/xs/logs/`，生成
超出硬截止时由 `timeout --signal=KILL` 终止。

当前状态：**用户已恢复 F24，native 联调继续进行**。用户明确要求 Verilator 基线输入不使用
`--preserve-aggregate=all`，Verilator 使用上游默认配置。此约束优先于下文的
历史试跑计划：aggregate SV 的编译/失败记录不作为正式 Verilator 基线；不再
尝试通过 `--language`、`-Wno-fatal`、`-fno-*`、generator `-O0` 或手工修改
Verilator 来建立基线。此前将断言失败直接归因为工具 bug 的结论未排除输入 SV
及其生成流程，应保留为旧配置下的观察，不能当作默认流程的根因结论。

基线入口修正为 `make xs_ref_rtl xs_ref_emu`，SV 默认目录为
`ptmp/xs/ref-rtl/rtl/`（`XS_REF_RTL_BUILD`），与 aggregate 目录分开。
生成时清空继承的 `PRESERVE_AGGREGATE`，不向 firtool 传入该选项；检查成功
生成记录，并拒绝复用带 preserve-aggregate 选项的 reference RTL。
`xs_ref_emu` 不再覆盖 `SIM_VFLAGS`、`EMU_THREADS` 或随机化设置，继承 DiffTest
自身的宏、include、优化和断言默认值。DiffTest 的 `EMU_THREADS=0` 默认值不加
额外 `--threads`，满足原始单线程基线要求。共享 harness 路径和启用功能仍沿用
工程已有设置。入口修正阶段仅修改入口、mock 回归及记录，不恢复 F24，不启动真实 RTL
生成、模型编译、仿真或 optimizer 参数实验。

入口修正验证：`make test_xs_workflow test_xs_firrtl_workflow SKIP_PY_INSTALL=1`
通过 8 + 80 项测试，`git diff --check` 通过。日志保存于
`ptmp/firrtl-ingest/F24/validation/reference-defaults.log`；这些结果验证流程及
小型回归，不代表已重新生成、编译或运行全 XiangShan reference。

2026-11-10 用户授权继续跑通 **Verilator reference**；当时 native F24 流水线仍暂停。
本次独立目录为 `ptmp/firrtl-ingest/F24/verilator-default/`，先运行 `xs_ref_rtl`，
再运行 `xs_ref_emu` 与 CoreMark 100k difftest，不给 Verilator 编译设置超时，
不添加参数或修改工具绕过失败。实际执行结果以该目录日志和报告为准。

默认 reference 现已通过 CoreMark **100k cycles + NEMU difftest**：
`xs_ref_rtl` 323.76 s；Verilator 生成 C++ 235.91 s；C++ 编译/链接 165.86 s。
首轮 C++ 编译因沙箱内 ccache 目录只读中止（0.58 s），随后将缓存放在本次
`ptmp` 目录并在沙箱外继续同一默认构建；未改 Verilator 参数。运行退出码 0，
Host 152.190 s，guest 100001/core 99996 cycles，instr 238535，PC `0x80000cde`。
退出原因是设定的 100k cycle limit，无断言失败或 difftest mismatch；这不代表
两轮 CoreMark 程序完整结束。实际 XiangShan HEAD 为 clean `faa4aeacb9776c369c902409ae5130d1fa36c0f6`，
DiffTest 为 clean `ee3eee0788384fd819bd3792425f4817b1992eb8`；使用默认 firtool
1.135.0 和 Verilator 5.051 devel。此前 aggregate 输入下的断言失败未复现，
不再把该旧记录视为默认 Verilator 流程的失败结论。
完整命令、输入与二进制哈希见 `ptmp/firrtl-ingest/F24/verilator-default/report.md`，
运行日志为 `logs/xs_ref_f24_default_100k.log`。这次基线采集期间未恢复 native F24。

用户追加的调试参考也已归档在同一目录：`commit-trace/commit.trace` 和
`commit-trace/commit.tsv` 包含 231,568 条提交记录，序号连续、cycle 单调；
`waveform/coremark-100k.fst` 约 1.18 GiB，包含复位及两个半周期。
波形版只增加用户要求的上游 FST 功能，沿用同一份默认 SV；其 100k cycles
difftest 通过，提交 trace 与独立非波形版逐字节相同。libfst 校验已确认时间范围
0..200101、1 ps 单位和信号可读性。完整周期对齐与打开说明见
`waveform/README.md`；抓 trace/波形的耗时不作为未插桩性能基线。

本阶段的 canonical 顺序是：

```text
ingest-firrtl
→ xmr-resolve
→ hier-flatten
→ comb-loop-elim
→ split-static-array
→ dead-code-elim
→ expr-opt
→ used-bits
→ split-nodes
→ dead-code-elim
→ constant-analysis
→ dead-code-elim
→ alias-analysis
→ pattern-detect
→ comm-expr
→ dead-code-elim
→ grhsim-dialect-translate
→ split-event-and-output
→ split-nonsink-and-sink
→ partition-nonsink
→ partition-sink
→ emit-grhsim-cpp
```

`grhsim-dialect-translate`、`split-event-and-output`、
`split-nonsink-and-sink`、`partition-nonsink`、`partition-sink` 和 `comm-expr`
是新路线的公开名称；旧的 `grh-to-grhsim`、`grhsim-*` 与 `common-expr` 名称
保留为 checkpoint/API 回放兼容别名。`emit-grhsim-cpp` 是 emitter 阶段，不是
普通 GRH rewrite pass。

## 阶段开始记录

- 输入、SV 外部实现、include 目录和 difftest harness 继续由
  `xs_firrtl_inputs`/`xs_firrtl_harness_inputs` 生成并写入 `sources.json` 与
  `build-identity.json`。
- FIRRTL→C++ 的硬截止默认设置为 `XS_FIRRTL_GENERATION_TIMEOUT=14m`；GSIM
  全路线 778.590 s 的 1.1 倍是 856.449 s，任何超过该预算的试跑都必须先终止
  再定位热点。
- `XS_FIRRTL_PIPELINE_MANIFEST`（默认位于 `ptmp/xs/firrtl-grhsim/`）保存
  固定阶段顺序、顶层和硬截止；`XS_FIRRTL_STAGE_LOG`（默认位于
  `ptmp/xs/logs/`）逐阶段写入 JSONL 的 `start`/`done`/`failed` 和耗时。
  这两个文件即使后续阶段超时也应保留，作为本轮开始、进行中和结束记录。
  JSONL 的 `scope=pipeline` 记录正式生成顺序；roundtrip、schedule 重建和
  字节比较使用 `scope=verification`。用 `scope=pipeline` 过滤后，完整新生成
  应得到上面的 22 对 `start`/`done`；失败诊断在同一阶段记 `failed`，不记
  `done`。roundtrip 中的 `partition-sink` 不能作为额外生产阶段计数。
  Make 父进程另外写 `scope=run` 的 `start` 和 `exit`，记录管道整体退出状态、
  timeout 命令退出状态、tee 退出状态及基于 `/proc/uptime` 的墙钟耗时。子进程被
  SIGKILL 时仍有 run 终态；137 标为 `termination_reason=timeout-or-sigkill`，
  不把 timeout 发出的 SIGKILL 与子进程自杀信号混为可区分事件。tee 失败同样保留
  终态并让 Make 失败。`scope=run` 不计入正式 22 阶段。
- flat checkpoint 同目录保存 `<stem>.prefix-identity.json`，复用现有 generation
  identity 的原子发布方式。F24 普通优化已经完成时记录 `post-opt`；旧 SV 前置
  路线记录 `pre-opt`。恢复读取该标记决定是否运行普通优化，不依赖当前是否传入
  FIRRTL manifest，也不重复已完成的 F24 prefix。
  标记中的设备、inode、字节数和纳秒时间是本地 freshness 检查，不是密码学内容
  身份；过期或矛盾标记直接拒绝。没有标记的旧 checkpoint 必须经核对后显式设置
  `XS_GRHSIM_FLAT_GRH_STAGE=pre-opt|post-opt`（CLI `--flat-grh-stage`）。
- 参照 GSIM 全图记录：FIRRTL→C++ 外层 778.590 s，1.1 倍预算 856.449 s。
  参照日志在 `ptmp/gsim-firrtl/full40m/`。

## 已完成的联调准备

- native pass factory 接受 canonical 名称，并保留旧名称；Python binding 也
  发布相同的参数接口。
- `partition-nonsink` 的 `firrtl-nodes=auto|prefer` 直接按 SemanticTree 的
  Declaration/Expression family 分组，Field/Element 归入所属 family；实例
  子树使用不同 SemanticId，避免混合实例。`semantic-nodes=1` 额外保留声明
  结果值边界；操作上的声明 provenance 不再把表达式内每个 primitive 切成独立
  node。分区 clone 保留 operation/value SemanticIds。
- `source env.sh && make test_grhsim_firrtl_nodes` 已通过；该测试覆盖 FIRRTL
  node 提示、node 数容量、clone 策略和 checkpoint 配置拒绝。
- 已有短时单线程 Verilator difftest 证据：10k cycles 用时 18.183 s，日志为
  `ptmp/firrtl-ingest/F24/verilator-baseline/logs/xs_ref_f24_verilator_st1_10k.log`。
- 现有 CoreMark 100k Verilator 日志记录 Host 170.421 s，
  `instr=238535`、`cycle=99996`、`guest=100001`、`PC=0x80000cde`，
  difftest 已启用，设计报告的 Commit SHA 为 `4a6e3da8bf`（dirty=0）；这是
  硬件内嵌的版本字段，不能代替 FIRRTL 或 workload 文件的 SHA-256。原始日志为
  `ptmp/firrtl-ingest/F24/verilator-baseline/logs/xs_ref_f24_verilator_st1_100k.log`。
  旧运行缺少 binary 哈希/argv，170.421 s 仅作历史对照。后续审计确认
  `build/xs/ref/time.log` 的 `--threads 2` 来自早期失败构建，当前 binary 的
  `VSimTop::threads()` 机器码返回 1；实际生成命令也没有 threads 参数。
  已用该 binary 补跑并冻结新基线，见下节。
- 阶段 journal 和 flat resume 修复已通过
  `make test_xs_firrtl_workflow SKIP_PY_INSTALL=1` 的 78/78 项验证，包含真实非法
  FIRRTL 的失败记录、mixed FIRRTL/SV 生成的精确 22 阶段顺序、独立 roundtrip
  记录上下文、过期/矛盾 prefix 标记拒绝，以及恢复后不重跑 prefix 的模型执行。
  原始和恢复模型均通过全部 256 个输入值的独立记分板；临时 ID 在 load 时会压紧，
  不用两次 final JSON 的内部符号字节一致性代替行为验证。日志为
  `ptmp/firrtl-ingest/F24/journal-tests/workflow-resume.log`。
- Make 父进程 run 终态验证同样通过 78/78 工作流测试：成功、普通非零退出、
  native 阻塞超时、忽略 TERM、覆盖截止时间和 tee 失败均有完整 run 记录；
  原有 `timeout --signal=KILL` 参数断言保留。日志为
  `ptmp/firrtl-ingest/F24/journal-tests/workflow-run-exit.log`。
- 当前 nonsink checkpoint 配置是
  `v4/<capacity>/<segment>/<semantic>/<clone>/<fanout>/<max-clones>/<lossy>/<hint>/<cost>/semantic-tree-mffc-v1`；
  旧 v3 或更早 checkpoint 必须从 `nonsink-sink-split` 重建，Python 恢复入口同样
  拒绝旧配置，不能只重建 SinkSchedule 后沿用旧 node 归属。

## C++ 编译预算与记录

`xs_firrtl_grhsim_build_emu` 和包含编译的 `xs_firrtl_grhsim_emu` 必须显式设置
正数 `XS_FIRRTL_COMPILE_TIMEOUT`。该值只能来自同输入 GSIM C++ 编译测量，
不得超过其 1.1 倍；FIRRTL→C++ 的 14 分钟截止不能当作编译预算。未设置、零、
负数或非 GNU timeout 时间格式在运行编译前拒绝。

截止覆盖整个 `_xs_grhsim_build_emu` 递归 Make 进程组，包括生成模型、PCH、
所有翻译单元、difftest harness 和链接。父 Make 在 `XS_FIRRTL_STAGE_LOG` 中追加
`scope=run`、`stage=compile-grhsim-cpp` 的开始/退出记录；字段与生成 run 相同，
完整输出日志是 `ptmp/xs/logs/xs_firrtl_compile_<RUN_ID>.log`。SIGKILL 终止嵌套
Make 及其编译子进程后，父进程仍会写入退出状态和墙钟耗时。

正式对照须使用没有 `.o`、PCH、`.a` 和 emu 的新目录，同时固定两方工具链、
输入 SHA-256、model 来源、harness snapshot/build identity、flags 和并行度。
native 模型使用 `-std=c++20 -O3 -march=native -fno-strict-aliasing`，harness 使用
`-O3 -march=native -fno-strict-aliasing`，`EMU_THREADS=0`；外层 Make 和模型构建
均采用 `XS_VM_BUILD_JOBS`。若同时设置 `VM_BUILD_JOBS`，须保证它与
`XS_VM_BUILD_JOBS` 一致。增量或 no-op 构建成功不作为编译性能达标证据。
同输入 GSIM 基线可直接使用 difftest 的 `gsim-build-emu`，以
`GSIM_GEN_CSRC_DIR` 指向本轮已生成 model，避免把 generation 再混入编译计时。

编译预算和进程组回归已通过现有 `make test_xs_firrtl_workflow` 的 80/80 项
测试：成功、普通编译失败和嵌套阻塞进程组的强制终止均保留 run 终态，未启动
大图编译。日志为 `ptmp/firrtl-ingest/F24/journal-tests/workflow-compile-exit.log`。

## 当前未通过的质量门

生成和 C++ 编译分别受同输入 GSIM 的 1.1 倍耗时上限约束；运行要求是达到
单线程 Verilator 的速度并保持同负载端点/difftest 一致。旧 GrhSIM 100k 记录
约 111.4–112.9 s，虽然快于历史 Verilator 170.421 s，但端点不一致，不能作为
正确性或新路线的性能通过证据。GSIM 同负载约 46.96–47.11 s 只是额外对照，
运行速度不设 GSIM 1.1 倍门禁。尚未取得新 canonical FIRRTL 路线的全图 C++、单线程 CoreMark
100k difftest、Verilator 等价负载以及 partition-nonsink 边数 ≤ GSIM 1.5 倍
的完整证据，因此 F24 保持“进行中”。

后续每次试跑都要同时保存：阶段 JSONL/日志、生成 identity、partition report、
Verilator/GSIM/GrhSIM 端点和 difftest 结果；若任一门超过预算，立即杀死并在本
文档追加原因与下一步优化，不把缩短 workload 作为达标证据。

## 新 native 构建与短路验证记录（2026-11-10）

- `make py_install` 最初在 sandbox 内因无法解析 GitHub、缺少 pinned fmt
  依赖而失败；受限升级获取依赖后已构建并安装新的 `_wolvrix.so`，不再依靠
  旧扩展兼容回退。`py_install` 的 wheel/cache 临时目录已改放 `ptmp/py-install/`。
- 真实 `make xs-firrtl-grhsim` 使用 `effects/source_lines.fir` 时，新扩展暴露
  转换 helper 的借用 SemanticId span 失效：先写 operation 语义时共享池扩容，
  随后用旧 span 写 result。改为写入后重新取得 source span，避免副本分配。
  补充 clock value SemanticId 的 op/result 双向保留断言，四项 GrhSIM transform
  CTest 通过，日志 `ptmp/firrtl-ingest/F24/validation/native-build-and-transforms.log`。
- 修复后的真实短路路径完成所有 22 阶段、emit、final/roundtrip 字节一致性；
  tiny 输入没有 Verification layer，显式 `XS_FIRRTL_ENABLED_LAYERS=`。
  证据在 `ptmp/firrtl-ingest/F24/short-native-fixed/`；该运行在 v4 分图升级之前，
  用于转换回归证据，不能替代最终 v4 分图/整机门禁。
- 发现旧 native 前缀首次 DCE 用时 509.694 s；718 s 是 native 阶段之和，892 s
  包含 correctness JSON 序列化。DCE 已将全位需求规范为内联 `allBits` 标志，
  避免每条全位依赖反复分配 interval；`test_transform_dead_code_elim` 通过。
  尚未取得全图加速测量，不把此改动视为耗时已达标。
- 当前全图可用输入为 `build/xs/rtl/rtl/SimTop.fir`，1,671,325,062 bytes，
  SHA-256 `b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b`。
  历史 GSIM 778.590 s 的输入为 `cc46aae1...`，旧路径目前已不存在；14m 暂作
  保守探索截止，正式比例需当前同输入、同配置 GSIM 基线。新的参考已开始收集，
  证据目录 `ptmp/firrtl-ingest/F24/gsim-current-full/`，本轮同样 840 s 硬截止。

## 同输入全图测量（2026-11-10）

- 重新冻结的单线程 Verilator CoreMark 100k difftest 基线成功：Host
  **170.790 s**，整体 **170.84 s**，exit 0，Seed 0，端点为
  `instr=238535/cycle=99996/guest=100001/PC=0x80000cde`。binary、CoreMark、
  NEMU 的前后 SHA-256 一致，`threads()` 机器码前后均返回 1，固定 CPU 2。
  证据 `ptmp/firrtl-ingest/F24/verilator-baseline/verified-100k/`。这是当前既有
  参考 executable 的可追溯运行，尚不能证明该旧 executable 来自当前 FIRRTL
  文件；新路线仍需同 workload/端点/difftest 一致，若有差异必须先定位设计身份。
- GSIM 同输入新模型的 C++ 编译基线成功：全新 281 个对象（240 model、
  41 harness）及链接合计 **300.63 s**，exit 0；1.1 倍编译门为 **330.693 s**，
  native 将使用 `XS_FIRRTL_COMPILE_TIMEOUT=330s`。固定 Clang 22.1.2、24 jobs、
  `-std=c++20 -O3 -march=native -fno-strict-aliasing`、同一冻结 harness，未使用
  PGO/PCH 或旧对象。GSIM `$`/`$$` 端口名称通过强制 include 的 10 个宏别名
  适配当前 harness，不改变模型计算源码。281 源文件、工具和 harness 前后哈希
  一致；证据 `ptmp/firrtl-ingest/F24/gsim-current-compile/`。
- 当前输入的 GSIM FIRRTL→C++ 已在 840 s 截止内成功结束：整个 Make 墙钟
  **779.02 s**，正式生成预算为其 1.1 倍 **856.922 s**；GSIM 内部 timer 为
  757.823 s，峰值 RSS 102.313 GiB，生成 240 个 C++ 文件、2,386,301,976 bytes。
  本轮使用冻结的 `bc46a232...` GSIM binary；完整身份、命令、原始日志保存在
  `ptmp/firrtl-ingest/F24/gsim-current-full/`。`--log-level=1` 的 ConstantAnalysis
  会输出逐常量日志，此项 I/O 开销包含在参考墙钟内。
- 本轮 GSIM final stats 为 222,593 supernodes、1,001,806 DAG edges、
  1,491,356 activation edges、1,490,154 boundary activation edges 和
  1,121,323 unique boundary activation edges。GSIM 的 boundary 统计混合了
  scalar 条件变动检测和 array/writer 无条件唤醒，还排除 always-active 目标；
  不能直接用不同含义的 native total 宣称 1.5 倍门禁通过。
- 原生 canonical 全图已在 **12:17:43 UTC** 开始 producer，保留更紧的
  **840 s** 硬截止（预计 12:31:43 UTC）。GSIM 正常退出后才启动；
  使用 10 lowering threads、SemanticTree node auto、默认 clone 策略，关闭
  自动 GRH JSON checkpoint 和 roundtrip；身份捕获、所有 pass 和 emit 仍在
  同一生成预算内。`WOLVRIX_SIMPLIFY_PHASE_TIMING=1` 记录 DCE 的分析、删除、
  SemanticTree 回收分项，结果目录为
  `ptmp/firrtl-ingest/F24/full-native-capped/`。本条是开始记录，尚非生成通过证据。
- 12:25:45 UTC 进行中记录：ingest 45.294 s、xmr-resolve 0.504 s、
  hier-flatten 52.663 s、comb-loop-elim 26.136 s、split-static-array 33.801 s；
  首次 DCE 从 12:20:23 UTC 开始，已运行约 322 s，尚未结束。全位需求内联
  优化未消除主要瓶颈，仍保持原 840 s 截止。只读审计确认 concat 依赖映射
  为每个操作数重复扫描后缀，存在平方复杂度；CommonExpr 的完整子表达式字符串
  key 在共享 DAG 上存在指数展开风险。修复先在 ptmp 准备，当前测量不更换
  native 源码或二进制。
- 本轮 producer 在 **673.40 s** 因 `split-nodes` 诊断失败而正常退出，未达到
  840 s 超时线；外层 Make 675.45 s、exit 2，峰值 RSS 75.936 GiB。
  原因是通过 scalar assign 追到 shaped source 时，`makeSliceView` 复制数组
  shape 后缩短 width，新 width 不再能被 shape 的元素数整除。bit-range view
  现明确创建无 shape 的 unsigned scalar；新增 signed/unsigned 数组输入各
  256 个模式的原图/重写图观察对照。当前为修复开始记录，尚待 native 构建验证。

## 首轮全图失败与 DCE 修正（2026-11-10）

首轮 native 在 **673.40 s** 正常非零退出，未触发 840 s 截止；`split-nodes` 报
`LogicalType shape dimension product must divide the total width`。stage journal
保留该阶段 `failed` 和父 run 的 `exit_status=1`。首次 DCE 的 pass 内计时为
**491.499 s**：analysis **431.915 s**、removal **59.022 s**、SemanticTree prune
**0.436 s**；Python stage 计时为 491.835 s。该结果证明本轮主要 DCE 开销在分析，
不能沿用旧图删除阶段占主导的结论。

退出后应用的 DCE 改动分为两类，均尚待本轮单测与全图复测：

- 行为保持的复杂度修正：concat 对每个操作数重复后缀扫描改为一次反向线性遍历，
  全位需求直接传播；worklist pop 移动区间对象，避免复制 interval vector。
- 耦合的区域语义修正：正位宽的空需求不再播种 root mask；ArrayCreate 按元素在结果中
  的区间求交、减偏移，正确转换到元素局部坐标；位区间后来扩大时，在 value、op 和
  状态族三处携带累计 root reason。只加入空需求过滤会暴露原映射及 reason 丢失，
  因此这些修正必须同时验证。

新增真实 GRH 回归覆盖三个数组元素各自的需求、全数组保活，以及经过额外 assign 后
才到达的第二段不相交需求，并将后者穿过寄存器状态族和写口数据。补丁与只读审计草案
保存在 `ptmp/firrtl-ingest/F24/dce-audit-draft/`；修复尚无全图性能通过证据。

补充审计发现 indexed state port 的坐标不能直接共用：read result / write data 为
所选行的局部位区间，storage demand 为整个状态的平坦位区间。当前采用保守策略：
indexed read 的非空需求升级为整个 storage，indexed write 数据和控制保持全位。
回归覆盖静态/动态索引以及 masked write，避免空需求过滤后暴露必须数据被删的错误。
广播 `kRegisterFillPort` 的 data 同样只有一个元素宽度，也采用全位保守依赖并添加
高位状态需求回归。

## 第二轮修复验证与全图开始（2026-11-10）

- `split-nodes` 的标量 bit view 清除数组 shape/符号标志；递归切片前用小向量
  保存 operand IDs，clone 前保存 owned attributes，避免共享 operand/attribute
  arena 扩容后继续读取旧 span。shaped signed/unsigned 输入、深层 mux 两分支及
  多属性复制均有独立原图/重写图观察回归。
- `comm-expr` 使用精确浅结构签名和 ordered child IDs，显式后序栈避免完整
  共享 DAG 字符串指数展开和深递归。保留 SemanticId/origin 并集、5 次/256 位
  门槛，并按不同 consumer operation 冻结 fanout，重复使用同一值的单个
  consumer 不再误算为两个 consumer；double 属性使用完整位表示判等。
- `constant-analysis` 的就绪遍历改为按 operand-use 计数的 Kahn FIFO，消除
  每条 use 重扫高 fanin 全部 operands 的平方开销。重复输入、多结果 producer、
  逆序定义和环拒绝都有回归。DCE 与静态数组拆分共用私有 constant index helper，
  按 producer 位宽/符号投影后再解释最终 assign view，覆盖 underscore、未知位、
  宽度截断和 signed/unsigned alias。
- 更新后的 native 已安装；四项 GrhSIM CTest、DCE、静态数组拆分、80 项工作流、
  6 项 flow 测试及生成 C++ 全输入输出对照通过，activation census 自检通过。
  日志 `ptmp/firrtl-ingest/F24/validation/final-index-topology.log`。
  `py_install` 这次仅构建 `wolvrix_python` 及依赖，测试由独立 Make targets 执行；
  项目的 CLI settings 变量改为 `PY_INSTALL_CONFIG_SETTINGS`，避免与 pip 同名环境
  变量的 settings 解析冲突。
- native v2 producer 于 **12:56:19 UTC** 开始，硬截止 **13:10:19 UTC**，同一
  FIRRTL、10 lowering threads、SemanticTree auto、默认 clone、不保存自动 JSON。
  Clang 22 路径和 24 compile jobs 已显式固定；编译门仍为 330 s，但本次命令
  仅执行生成。源码快照、已装 native SHA 和完整命令在
  `ptmp/firrtl-ingest/F24/full-native-v2/`；尚未取得 v2 全图通过结果。
- GSIM 当前输入模型已完成 100k difftest：Host **51.443 s**，整体 **51.46 s**，
  exit 0、Seed 0、guest 100001；端点为 `238550/99998/0x80000b40`，与旧
  Verilator 的 `238535/99996/0x80000cde` 不同，暂不作严格同端点性能对比。
  证据 `ptmp/firrtl-ingest/F24/gsim-current-run100k/`。已查明当前 FIRRTL/SV 为
  commit `2193b15d35`，旧 Verilator 为 `4a6e3da8bf`；当前 `SimTop.sv` 和
  `CommitIDModule.sv` 来自同一 Chisel `--dump-fir --preserve-aggregate=all`
  生成，准备从冻结 SV 建立当前设计的单线程参考机，不以调整 cycle 上限掩盖差异。
- v2 在 **13:00:51 UTC** 的进行中记录：首次 DCE stage **68.624 s**，pass 内
  **68.284 s**（analysis **21.630 s**、removal **46.086 s**、SemanticTree prune
  **0.446 s**），较首轮 491.835 s stage 快约 **7.17 倍**；此收益包含线性
  concat 和区域语义修正，不能单独归因于其中一项。`expr-opt` 2.235 s、
  `used-bits` 17.696 s，`split-nodes` 成功完成 171,433 个 slice rewrite，耗时
  **8.800 s**，已越过上轮 shape 错误；第二次 DCE 进行中。已安装的两个 native
  library 与启动前 SHA 核对一致，仍未取得全图生成成功证据。

第一次统一 `make py_install test_grhsim_transforms test_transform_dead_code_elim
test_transform_split_static_array` 已通过，日志为
`ptmp/firrtl-ingest/F24/validation/full-fixes-native.log`。随后静态索引解析进一步统一到
私有 `lib/transform/constant_index.hpp`，供 DCE 和 split-static-array 共用：SVInt 先按
常量 producer 类型定宽，再解释等宽 assign 的最终 signedness。新增 separator、
GRH 位宽截断、unknown/negative/out-of-range 和 signedness alias 回归；此最后一组
共享 helper 改动随后已在 `validation/final-index-topology.log` 的统一增量验证中通过。

## native v2 类型校验失败与当前参考机构建（2026-11-10）

v2 producer 在 **394.96 s** 正常非零退出，外层 Make exit 2，未触发 840 s
截止。`split-nodes`、后续优化和最终 DCE 已完成，但
`grhsim-dialect-translate` 的完整 GRH 前置校验发现 30 个 `kAssign` 的
operand/result 位宽或 kind/domain 不一致。首个为
`SimTop::tmp_op_38640500`，原始 FIRRTL **5760643:50** 的
`bits(dataSources[0].value, 3, 3)`；其余分布在相邻 datapath 位选和若干更后面的
位选表达式。当前尚未确定产生不合法 Assign 的 pass，不能将前面的轻量 descriptor
校验成功视为结构类型校验成功，也没有生成/编译/100k 门禁通过证据。

接下来先以小图定位并修复，再保持同一 840 s 生成截止进行全图复测。
同时释放主机给当前设计的单线程 Verilator fresh build：沿用已有 `xs_ref_emu`
target、冻结 generated harness、当前 SV、Clang 22、24 jobs，设置独立的
1200 s 探索截止；此截止不替代 native 对 GSIM 的 330 s 编译门。
构建计划及输入身份在 `ptmp/firrtl-ingest/F24/verilator-current-plan/plan.md`。

修复进行中记录：UsedBits 的 indexed-read 分支现在将每个 index operand 全位保活，
再传播 storage demand。原逻辑完全漏传索引需求：索引 producer 若还有一个低位
可观察用处，会被错误缩窄，其上未被分析到的等宽 Assign 仍保留旧宽度。
新增 16 行状态数组 fixture，在显式 DCE 前后做完整 GRH 校验，并穷举 16 个索引
与原图 Oracle 对照。另修复 `split-static-array::select` 借用 operand span 跨递归
建图的问题；递归前保存 IDs，外层保存 result ID，并拒绝选择结果类型与原 slice
不符的改写。新增 128 输入的不同位宽 concat tree，强制共享 arena 扩容后比较
中间 512 位的选择结果。两项当前均已写入，尚待构建和实际测试；不提前归因为
v2 全图 30 处错误的唯一原因。Assign 完整校验诊断同时补上两侧 width/kind/domain。

当前 Verilator 首轮在解析字段名 `until` 时退出（3.36 s，exit 2），没有进入 C++
编译；沿用 F10 已记录的 `--language 1800-2005 -Wno-fatal` 兼容参数，保持
`--assert`、DiffTest、单线程及同一 RTL。第二个 fresh 目录
`ptmp/firrtl-ingest/F24/verilator-current-language2005/` 于 **13:09:08 UTC**
启动，独立截止 **13:29:08 UTC**。这两项兼容参数不修改输入 RTL。

两处修复已在 **13:15 UTC** 前完成短增量安装与验证：四项 GrhSIM CTest 全部通过
（transform suite 12.30 s），静态数组拆分 suite 通过（0.02 s），包括上述新 Oracle
回归。日志 `ptmp/firrtl-ingest/F24/validation/assign-width-fixes.log`。本次短构建与
Verilator codegen 有并发，Verilator build 因而只作为建立参考可执行文件的探索记录；
正式 native 计时和各后端 100k 性能运行仍需隔离执行。

额外审计发现一个当前默认 FourState ingest 合法反例：Add/Sub/Mul 的高位若含 X，
SV 算术会令结果全 X；只为低位需求截掉输入高位，会将未知结果变成已知数。
GRH 文档明确采用 SV 四态规则，因此本次还将限制这三类算术的 prefix 优化到
TwoState，保留 FourState 的完整输入及结果，添加高 X / 已知低位的原图对照。
此项正在实施，尚未安装验证；它不是已确定的 v2 Assign 错误原因。

四态算术修复源码及回归随后已冻结，尚待下一次增量安装。回归使用
`preserveUnknowns=true` 的独立 Oracle，覆盖 Add/Sub/Mul 的未知低位结果、
显式 DCE 前后完整校验、常量折叠后 TwoState 投影一致，以及三类 TwoState
算术各 256 对输入仍可窄化并保持结果。

当前参考机 codegen 已在 **461.33 s** 成功结束（峰值约 20.58 GiB），生成代码
直接 `VSimTop::threads() == 1`；**13:16:49 UTC** 进入 24 jobs 编译。
13:24 UTC 其余对象已完成，剩余 `VSimTop___024root__304.cpp` 约 **408 MiB**，
只有一个巨大的 nba/reset 函数；现有 `--output-split 30000` 和
`--output-split-cfuncs 30000` 未拆开其中的条件块。保留 **13:29:08 UTC** 原截止。
如触发截止，应针对编译长尾优化，不能降低 `-O3` 来建立偏慢的性能参考机；
可先评估与 native/GSIM 一样的 `-fno-strict-aliasing`，旧 GrhSIM 路线已记录
Clang 在大量不同 struct member 上的 TBAA 平方开销。

参考机构建于 **13:29:08 UTC** 达到原 **1200.00 s** 截止，GNU timeout 立即
KILL 整个构建进程组，exit 137；未完成链接，未运行 100k。不能将被杀外层
`time` 的 1908 KiB/CPU 0 当成模型资源统计。冻结输入和生成源码保留，后续
从同一源码 fresh 编译的方案位于 `verilator-current-plan/fallback.md`，使用
既有 `verilator-build-emu`、`OPT_FAST=-O3`、
`USER_CPPFLAGS=-fno-strict-aliasing`，完整 dry-run 已确认保留宏、include 和 PCH。
先释放主机给 native 修复验证和 v3 计时；不会在当前窗口自动重启参考构建。

四态修复已增量安装，四项 GrhSIM suite、6 项 flow 测试的生成 C++ 执行/对照、
80 项 workflow 测试全部通过。日志分别为
`validation/four-state-arithmetic.log`、`validation/shared-jobserver-workflow.log`。
native 编译入口显式传递空 `GRHSIM_MODEL_MAKE_J`，使递归模型编译继承外层
24-job jobserver，避免与 harness 形成两个独立 24-job 池；workflow mock 实际
递归验证该 CLI override。root/nested diff whitespace 校验通过。

**13:31 UTC** 开始 native v3 全图生成：仍是相同完整 FIRRTL、10 lowering
threads、SemanticTree auto、默认 clone、关闭自动 JSON/roundtrip，生成硬截止
**840 s**、后续完整编译硬截止 **330 s**。源码 tar 与已安装 native SHA 已冻结在
`ptmp/firrtl-ingest/F24/full-native-v3/`。此处记录开始，尚非全图通过证据；本轮
生成与其余编译/仿真隔离。

v3 producer **151.79 s**、外层 **153.84 s** 退出，exit 134 / Make 2；
不是超时。新类型检查在 `split-static-array` 当场拦住 **38640500**，正是
v2 首个非法 Assign 的 ID，因此故障已定位在 UsedBits/SplitNodes 之前。
此处 C++ 未捕获异常使子进程 abort；父 journal 仍保留真实 exit 134。

源码分析找到确定性缓存污染：`select(key, depth=0)` 对不支持的局部选择
`finish(key.base)`，把宽原值缓存到窄选择 key 下；外层第一次因 selected==base
而安全跳过，后续经 Assign/Mux 的递归查询却会直接复用该缓存，把整值当局部选择
返回。修复将禁止缓存这种 no-op sentinel，保留真正等宽同类型 whole selection
的缓存，添加“先直接访问，再经 alias 访问同一范围”的小图 Oracle 回归。
此项当前为实施记录，尚未验证。与此同时释放主机给参考机 fresh C++ fallback：
保留原生成源、保留 `-O3`，添加 `-fno-strict-aliasing`，独立 **600 s** 探索截止。

缓存修复及小图回归已写入：不再将 unsupported depth-0 no-op 返回值写入选择
缓存；16 组输入比较直接选择与经 Assign 递归选择，DCE 前后完整校验并观察
原图结果。类型守卫补全双方 width/sign/domain/shape，pass 捕获异常并返回
failed，避免 abort。当前等待安装验证。

用户随后明确要求 **Verilator 等到编译完成**，因此 Verilator 后续不再设超时；
native 的 **840 s / 330 s** 门保持不变。撤掉已有 watchdog 需要宿主进程访问，
工具审批返回前原 600 s watchdog 已触发（exit 137），没有完成 ELF。现保留
824 个同配置 no-alias 对象，通过既有 target 增量继续唯一缺失的 304 TU，
不再加 watchdog，也不把这次增量时间描述为 fresh/隔离编译时间。

为继续推进 native，最后一个 Verilator TU 编译期间可以并发运行 native 回归及
v4 生成；显式记录该后台负载，native 原有硬时限仍约束实际 wall，不因并发
放宽。各后端的最终 100k 性能测量仍隔离执行。13:59 UTC 本机内存可用约
181 GiB，上一 native 峰值约 74 GiB；后续继续观察资源。

缓存修复已安装验证：静态数组拆分 suite（0.02 s）、四项 GrhSIM suite
（transform 12.93 s）、6 项 flow 及生成 C++ 对照、6 项 activation census
测试全部通过，整体 Make exit 0 / 47.17 s。日志
`validation/selection-cache-fix.log`。native v4 于 **14:00 UTC** 开始，仍为
同一输入和 canonical 配置、**840 s** 生成截止；源码 tar、命令及 native SHA
冻结在 `ptmp/firrtl-ingest/F24/full-native-v4/`。后台为唯一 Verilator 304 TU
无 watchdog 增量编译，不重复生成 SV/C++；尚无 v4 通过证据。

v4 进行中：ingest **45.002 s**、xmr **0.483 s**、flatten **50.508 s**、
comb-loop **29.776 s**；`split-static-array` **31.531 s** 成功，已越过 v3
cache guard 故障边界，首次 DCE 开始。当前后台仍仅一个 Verilator 编译 TU，
未报错；本机 32 核、192 GiB RAM。生成截止保持 **14:14:33 UTC**，尚待后续
完整 GRH 校验和 emit，不能只凭此确认 v2 的全部 30 个 Assign 已消失。

v4 后续进行中：DCE1 **70.731 s**（analysis 24.217 / removal 45.644），
UsedBits **19.318 s**、SplitNodes **9.497 s**、DCE2 **26.086 s**、
ConstantAnalysis **15.053 s**、DCE3 **22.687 s**、Alias **7.056 s**、
Pattern **1.553 s**、CommonExpr **42.916 s**（shared 3,487,115）、
DCE4 **34.275 s**。已进入 `grhsim-dialect-translate`，截至 **14:08 UTC**
未再报 v2 的 Assign 类型错误；此阶段尚未结束，不能把开始记录当作转换通过。

v4 在 **14:14:33 UTC** 达到 **840 s** 生成硬截止，producer journal 为
**841.41 s / exit 137 / timeout-or-sigkill**，外层 Make **843.45 s / exit 2**。
全部 GRH 优化阶段已完成，剩余约 430 s 耗在转换阶段，尚未到 partition 或 emit。
本轮未输出 Assign 类型错误，但转换未完成，不能据此声明全图通过；也没有 native
编译、边数或 100k 结果。被杀父进程的 time CPU/RSS 不代表模型资源消耗。

下一轮先为转换添加受 `WOLVRIX_SIMPLIFY_PHASE_TIMING` 控制的细分计时，覆盖前后
校验、contract/literal 准备、类型及操作改写、内部 symbol 批量生成；同时将 preflight
中仅查询 partition 属性的 owned operation snapshot 改为 borrowed attr range。
这项修改保留转换和 symbol ABI；先通过 Make 安装及转换回归，再按同一 **840 s**
截止复测，用阶段证据定位瓶颈。唯一 Verilator TU 仍在后台无超时编译。

转换分段计时与 borrowed preflight 查询已安装，四项 GrhSIM suite 全部通过
（transform 12.72 s，转换测试 0.01 s），证据 `validation/conversion-phases.log`。
native v5 于 **14:18:15 UTC** 开始，同一全图输入和配置，生成截止仍为 **840 s**；
源码 tar、完整命令及已安装 native SHA 位于 `full-native-v5/`。
本轮仍与唯一 Verilator TU 编译并发，最终仿真计时需隔离。

**14:22 UTC** poll 确认 Verilator 无 watchdog 恢复编译已正常 exit 0，完成 ELF。
其 ELF mtime 和正常 time 记录表明实际结束于 **14:17:11 UTC**，因此 v5
**14:18:15 UTC** 开始后已无该后台 compiler；上面的 v5 并发描述是启动时尚未
收到完成通知的保守记录。恢复 Make wall **1044.30 s**、user **996.31 s** /
sys **47.52 s**、99% CPU、max RSS **8,906,740 KiB**；这是保留 824 对象后的
增量恢复耗时，包含与 v4/验证的并发，不能作为 fresh/隔离编译基准。
ELF **227,366,496 B**，SHA256
`72d0dee115ebcf42ac1ad446ead376f0be1a4a97a2f63c30fc4be3f12da111fd`；
`threads()` 机器码返回 1，RTL/model/harness/tool/runtime 身份复核全部通过，
既有 Make target 已补 emu symlink。等待 native v5 结束后隔离运行 100k/difftest。

v5 转换内部证据（**14:25 UTC**）：完整 GRH 前置校验 **2.279 s** 成功，
6808417 operations / 6296803 values；没有重现 v2 的 30 个 Assign 类型错误。
operation contracts **0.333 s**、state contracts **0.307 s**、event contracts
**0.644 s**、constant literal 准备 **0.580 s**、undriven scan **0.057 s**、
state literal 准备 **0.028 s**、value domains **0.419 s**、constant 更新
**0.190 s**、state 更新 **0.194 s**、undriven materialize **0.005 s**，合计
**5.041 s**。随后 operation rewrite loop 长时间未完成，故不实施先前准备的
event memo / verifier / domain setter 优化草稿；这些路径尚无占时瓶颈证据。
下一步针对 rewrite 的 origin/semantic 合并和 graph mutation 做精确进度计数。
当前 core addOp/ValueSemanticIds 对大列表逐项 std::find，代码上有平方复杂度；
已准备保留 first-seen 顺序的 hash 去重草稿及回归，尚未安装，实际全图 source
列表大小仍待下一轮 census，不能提前认定为唯一原因。

v5 于 **14:32 UTC** 再次触发 **840 s** 截止，producer **841.34 s / exit 137**，
外层 Make **843.37 s / exit 2**。约 **444 s** 的转换时间仍未走出 operation
rewrite loop；没有 partition/emit/compile 或 native 100k 证据。v5 运行期间没有
Verilator 编译/仿真负载。已释放主机，让当前设计 Verilator 隔离运行 100k，
保持 seed 0、reset 50、max-cycle 100000、相同 CoreMark/NEMU 和 CPU 2，不加 watchdog。

下一轮已写入 rewrite census/分桶计时和大 SemanticId 列表 hash ordered-dedup：
小列表及少量 incoming IDs 保留线性扫描；大列表用集合判重，输出仍严格保留既有
顺序、既有重复元素以及新 ID 首次出现的顺序。borrowed 源先读完再写回，不改变
public ABI。回归覆盖大小边界、重复/乱序输入、源/目标 pool alias 和 clone 隔离。
此刻仅源码完成；Verilator 仿真结束后再安装和测试，避免污染运行耗时。

当前设计 Verilator 隔离 100k 尝试于 **14:32:51 UTC** 启动，约 **43.794 s**
Host（whole **43.83 s**）后在 guest **10273** / core **10269** / instr **524** /
PC `0x800027c6` 触发 `AheadBtbReplacer.sv:124`：
`writeReplacerGen's replaceWay doesn't match replacer!`。emu exit 1 / Make 2，
不是 timeout，未到 100k；此前已启用 NEMU difftest，未出现架构 mismatch。
冻结 binary/workload/NEMU 的 pre/post hash 通过。断言保持启用，不以移除 checker
或更改 reset/seed/cycle 上限取得成功。证据 `verilator-current-run100k/`。
GSIM 模型包含同一四 bank checker，ELF failure path 实际调用 `__assert_fail`，
所以先前 GSIM 通过不能简单解释为 checker 被 NDEBUG 删除；尚待分析输入、调度
与初始化的实际差异。这次失败不能当作当前设计 Verilator 100k 性能基线。

用户询问是否主线 KMHv3：当前冻结 RTL commit 为 **2193b15d35**，来源
`grh/tes-grhsim-am` 联调分支，当前 checkout HEAD **faa4aeacb**。与本地
`kunminghu-v3` 的共同基点 **a20df0c360ff7abf1831c3ba8f0593ce96e26690**；
从共同基点到冻结 commit 的 tree diff 只有 `.gitmodules`、`Makefile`、`difftest`，
没有 CPU Scala 修改；生成时 DiffTest 是 **5d20df054...-dirty**，其未提交内容
无法仅凭生成头重建。因此称为 KMHv3 派生联调分支，不能称为原样上游主线，
也不能从本次断言推断主线 KMHv3 无法通过。未联网更新 refs 或更换冻结输入。

大列表 ordered-union 和 rewrite 计数已安装验证：semantic-tree suite 及新增
空 target/source 完整性检查通过（**0.01 s**）；四项 GrhSIM suite、6 项 flow
及生成 C++ 输出比较全部通过。日志 `validation/rewrite-union.log` 和
`validation/rewrite-union-final-semantic.log`。native v6 于 **14:38:19 UTC**
开始，仍为同一输入/配置、**840 s** 截止；源码 tar、命令和已安装 native SHA
冻结在 `full-native-v6/`。此轮无其他编译/仿真负载，基线故障排查仅做只读分析。

基线断言进一步定位：已有 [F10-replacer.md](F10-replacer.md) 记录同一问题的
6 周期独立 scoreboard 复现。当前 `AheadBtbReplacer.sv` 和 `ReplacerState.sv`
SHA 分别仍为 **e20c8011...6b02** 和 **9ed51f83...b04f**，与 F10 完全相同；
当前生成的 `VSimTop___024root__301.cpp:11987/14843/17699/20555`（四个 bank）
仍含错误的 `state_vec_dly[2] = 0x21U | (0xffffffc0U & state_vec_dly[2])`，
遗漏跨 word packed slice 应保留的 **0x1c**，与 F10 已定位的错误完全对应。
因此后续针对 Verilator 优化生成错误修复，不修改 CPU RTL 或豁免断言。
本轮漏关联已有 F10 证据，重复建立了会失败的默认优化基线，已向用户说明。
安装工具为 **5.051 devel / v5.050-126-gdaf582661**，源码 HEAD
**daf5826610da81ac92bd798f3bd51793d52cd14f**，clean；当前 tool SHA 仍与编译前一致。
先准备 `-fno-expand` / substitution 等特定 generator pass 的小复现实验，
保持 host C++ `-O3`，不先以全面关闭 generator 优化作为性能基线。

## 基线归档后恢复 F24

用户已明确恢复 F24。正式功能/性能参考采用上文默认 SV、默认 Verilator 的
100k-cycle NEMU 运行：Host **152.190 s**，CPU 2，seed 0，guest **100001**、
core **99996**、instr **238535**、PC **0x80000cde**。独立提交 trace 及 FST
采集均通过 difftest，两者的 **231,568** 条提交记录逐字节一致；调试采集耗时
不替换未插桩性能参考。旧 aggregate 输入下的失败和优化器试验不再作为基线。

补记 v6 结束：producer **520.82 s**，外层 Make **522.83 s / exit 2**，
峰值 RSS **112,558,240 KiB**，为正常非零退出，**不是超时**。转换预校验成功，
准备约 **5.138 s**；rewrite 已处理超过 **307200 / 359319** 个转换，约
**128.4 s**，最后报 `SemanticId pool capacity`。当时 detector **452,803**、
join **146,013**；重复传播的累计 op/value IDs 已达数十亿。尚无本轮 partition、
emit、native 编译或 100k 通过记录。完整证据在 `full-native-v6/`。

恢复时先修复转换 helper 的重复生成与语义池增长：完整 event 键相同的 edge
detector 共享，有序 pulse 前缀可共享 OR join；按唯一 helper 外部累计元数据，
最后一次写入，保留语义集合和确定顺序，避免反复追加增长后的集合。join 的
provenance 从原 consumer/event 定义与值累计，不能因共享 pulse 而混入其他
consumer 的语义。此项尚在实现和小图回归阶段，不提前宣称整机容量或耗时达标。

native 生成保持 **840 s** 强制截止，完整模型+harness 编译保持 **330 s**
强制截止；旧同输入 GSIM 测量为 **779.02 s / 300.63 s**。新默认 reference
与冻结 native/GSIM 输入的身份关系另作审计，不用哈希不同的文件冒充同输入。
最终仍需完成 canonical 22 阶段、可比 activation 边数门、100k difftest 和
提交行为对照，以及隔离的单线程运行性能测量。任何 native 阶段超过预算即终止
并优化，不能缩短负载作为通过证据。

**2026-11-10 16:56 UTC**：共享 helper 实现已完成。完整 event key 共享 detector、
有序 OR prefix 共享 join；helper 外部按唯一原始 op/value 引用累计 provenance，
rewrite 后一次发布 operation/result SemanticIds。两态/四态、事件隔离、AB/BA/ABC
前缀、join provenance、稳定顺序、roundtrip，以及 1536 consumers/1024 clock IDs
压力用例通过；转换 suite **3/3**。独立复核未发现阻塞问题。

emitter fixture generation **16.80 s / exit 0**；transforms、virtual partitions、
sink schedule 和 **28** 个 large capture/latch/interrupted 生成 C++ 实际运行全部
通过，组合 Make **81.59 s / exit 0**。fixture 显式构造负例的私有 OR，去除对旧版
每 writer 独占 detector 的假设，未放宽 owner、语义或运行行为断言。`make py_install`
**43.53 s / exit 0**。日志在 `validation/shared-helper-*.log`。安装后先验证 Python
flow/workflow，再冻结 v7 源码、库、命令和输入，启动同输入 **840 s** 全图生成。

**16:57:55 UTC**：安装后的 Python flow/生成模型输出比较及 **80** 项 FIRRTL
workflow 测试通过，组合 Make **30.65 s / exit 0**。v7 正式全图生成开始，目录
`full-native-v7/`；源码 tar、库 SHA256、输入 SHA256、完整 Make 命令均已冻结。
保留 `b313a3ec…` FIRRTL 和旧冻结 harness，10 lower threads、unknown init/invalid，
canonical 22 阶段，generation hard cap **840 s**。本轮没有其他编译/仿真负载。

v7 后续核对：359319 个转换 rewrite **1.232 s**，detector **422**、join **46**，
helper metadata publish **69 ms**，转换完整 **14.140 s**；前次语义池故障点已通过。
split-event/output **32.216 s**、split-nonsink/sink **27.353 s**、partition-nonsink
**140.659 s**（activity nodes 2261545、supernodes 21789、hint analysis 129.062 s）。
**17:07:49 UTC** 开始 partition-sink 后无正常终态。内核没有相关 OOM，但系统日志
明确记录 **17:09:21 UTC systemd-oomd** 因 pressure **74.14%**、该 scope 用量
**160.2 GiB** 杀死原 tmux scope（19 个进程）；外层日志/timeout recorder 也随之退出。
不能把缺失 exit 的运行当成功或 timeout。系统证据归档 `memory-audit/v7-oomd.log`。

用户要求避免耗尽内存。下一轮全图运行前先建立独立 workload cgroup，硬上限
**128 GiB**、禁用 workload swap，并记录峰值/退出原因；保护上层记录进程，保留
**840 s / 330 s** 时间上限。当前不重跑全图，先检查 partition-sink 的规模增长。

**23:25 UTC**：发现 sink schedule 对每个连续 writer run 常驻完整 nonsink 祖先
闭包，并逐项复制四段文本 owner；交错 clock/priority 会重复保存同一大型祖先 DAG。
改为 schedule 唯一 leaf 字典与 CSR prerequisite DAG、每 run sorted unique 直接根，
完整拓扑闭包通过查询按需恢复。effect-order edges、writer 顺序和完整依赖验证保留；
verifier 重建后逐项比较字典/CSR/roots，不能把 direct roots 当完整闭包。可读输出
使用同一无损 DAG+roots 表达，避免再次展开所有 run。独立只读复核通过，尚不声称
这就是 v7 内存增长的唯一原因。

新增 192 级祖先、256 个交错时钟 run 压力例，逐 run 核对完整闭包、顺序、唯一性，
持久存储条目少于展开条目的 1/16，并验证伪造 roots/CSR 拒绝。调度/分图/transform
**3/3**、store **4/4**、emitter generation **1/1** 通过，组合 Make **59.13 s**、
max RSS **416476 KiB**；日志 `validation/compact-sink-schedule.log`。两类 partition
新增分段 wall/RSS/HWM 与规模计数；旧 `hint-analysis-us` 覆盖大部分整个 nonsink pass，
不能视为单纯 hint 时间。下一步安装并验证受限运行器，再启动 v8 同输入全图。

compact schedule 安装 **77.16 s / exit 0**；安装后 flow 模型输出比较及 **80** 项
FIRRTL workflow 通过（组合 **31.02 s**）。新增 readable Python 验证最初失败于
旧 fixture 要求 `origin-set` 一定存在：hier-flatten 现行来源是 SemanticTree，
不再自动制造 legacy `originModules`。fixture 通过 public JSON API 显式注入四个
已知 state/read/write 的可选 legacy 来源，保留 origin-set 断言并增加来源精确
映射核对；**5** 种输出配置实际编译、NBA/read/write 对照全部通过，**5.87 s**。
未修改生产来源规则。日志 `validation/compact-sink-{install,flow-workflow,readable-python}.log`。

受限运行器 `scripts/run_resource_capped.py` 已完成：独立 user service cgroup，启动前
核对 memory.max、swap.max=0、oom.group=1，ExecStopPost 在 unit 卸载前保存峰值、
memory.events 和退出原因。报告绑定本次 UUID unit，重试清除旧 sidecar；无法确认
限制或取证不完整时拒绝成功。外层 recorder 留在原 scope；Make 失效 jobserver fds
不传入 service，内部完整 compile 仍显式24 jobs。`make test_resource_capped` **8/8**
通过。真实 **64 MiB** 正常退出与两个子进程合计触顶测试通过；后者只有独立组被杀，
峰值 **67108864 B**、swap **0**、`oom_group_kill=1`，完整 stop sidecar 保留。
证据 `memory-audit/{live-selftest.log,success.json,oom.json,mock-tests.log}`。

清理审计补齐10个已退役 XS_GRHSIM 设置的中央表与 Make guard（空/0也拒绝），
mixed FIRRTL 明确拒绝仅适用于旧 SV simplify 前缀的 pre-simplify dump。既有 tooling
**17** 项与 FIRRTL workflow **80** 项通过，**16.14 s / exit 0**；未改变22阶段内容。
v8 源码与已安装库重新冻结，下一轮通过 `xs_firrtl_resource_capped` 启动 canonical
`xs-firrtl-grhsim`，硬限制 **128 GiB/swap0/840 s**，输入与冻结 harness 保持一致。

**2026-11-11 00:54:56 UTC**：v8 受限全图正式启动，独立 service
`wolvrix-capped-f05f4c80adf14f779a1d8c9fbd12732a.service`。ExecStartPre 确认
`memory.max=137438953472`、`memory.swap.max=0`、`memory.oom.group=1`，随后进入
ingest-firrtl。完整命令、源码 tar、库/输入 SHA 和 limit 起始证明均在
`full-native-v8/`；本条为开始记录，不是全图通过证据。本轮没有其他编译/仿真负载。

v8 进行中：nonsink pass **141.098 s**，其中 activity-node build **9.629 s**、
cluster coarsen **82.699 s**、clone **9.441 s**、verify **12.291 s**。图结构与 v7
一致（2261545 leaves /21789 supernodes）。sink pass **55.037 s** 完成：writers
**351368**、groups **6817**、runs **144602**，共享 DAG **2261545 nodes /3788939 edges**，
直接 roots **913946**；schedule 构造 **12.127 s**。未常驻所有 run 的传递闭包。
进入 emit-grhsim-cpp 时 cgroup 峰值约 **101 GiB**，memory.events max/oom 均0；
尚未取得完整生成终态。

v8 于 **01:08:56 UTC** 达到 **840 s** 强制截止，run journal **841.91 s /137**，
外层含 harness/cgroup 启停 **844.16 s /exit2**。emit 于约 **640.25 s** 开始，
约 **201 s** 后仍未完成。受限 recorder 正常存活并保存终态：cgroup peak
**119582482432 B（111.37 GiB）**、swap **0**、memory.events 的 max/oom/kill 均 **0**；
本次为时间截止，不是内存触顶或 OOM。外层 `/usr/bin/time` 的 child RSS/CPU 不包括
由 systemd 独立启动的工作进程，资源应看 `generation-resources.json` 的 cgroup 数据。

临时 staging 的隐藏 `.function-bodies` 已写约 **7.5 GiB**，所以 emitter 并非
尚未开始正文生成；不能用不显示隐藏文件的 `ls` 推断停在 analyze。没有完整发布的
model、compile、activation-stats 或 native100k 结果。下一步给 emitter 增加阶段与
正文规模计数，先定位实际热点，再优化；继续 **128 GiB/swap0/840s** 上限，不提高
预算，不缩短 workload。证据 `full-native-v8/{driver.log,generation-resources.json,
generation-time.txt,logs/}`。

**01:15 UTC**：进入 v9 优化准备。emitter 增加受现有 phase-timing 开关控制的
analyze、各 phase、函数/Code 节点/实际正文字节与文件发布计时，尚未重跑全图。
有界采样只读取 v8 正文头/中/尾各 2 MiB，采样 RSS 约 35 MiB；中段四条
4096-bit concat 各约 377 KiB，包含约 3223 次全宽 cast，尾段 270 个循环均为
单元素。此证据提示生成代码膨胀，但不能代替具体编译耗时或证明 analyze 是热点。
先精简已知 count=1 的代码，再替换 nonsink coarsen 中不影响候选/成员顺序的
树容器与冗余排序；完整 partition 报告须与 v8 对照。下一轮继续独立 cgroup 的
128 GiB / swap0 与 840 s 截止，不提高资源上限。

v9 小图验证完成：FIRRTL node（新增等权/容量/重排 golden）、transform、virtual
partition、sink schedule 与 emitter generation 全部通过，组合 **50.30 s**。
**24** 个生成 C++ 模型实际编译运行通过（**38.57 s**），覆盖 signed scalar、
mask、单叶 copy/assembly、索引 guard、capture/latch 与中断恢复；独立只读复核
未发现语义问题。安装 **46.97 s / exit0**，安装后 flow 行为对照和 **80** 项
FIRRTL workflow 通过。日志 `validation/v9-{native-tests,scalar-models,install,
installed-workflow}.log`。完整源码、已安装库、输入与命令冻结在 `full-native-v9/`。
本轮仍使用 `b313a3ec…` 原始 FIRRTL 与同一冻结 harness。

**01:24:15 UTC**：v9 受限生成正式开始，service
`wolvrix-capped-f7f5df38c3a54cea87dd91dff3396c7f.service`。启动 sidecar 已核对
memory.max=137438953472、swap.max=0、oom.group=1；进入 ingest-firrtl。
本条仅为开始记录，生成尚未通过；本轮没有其他编译/仿真负载。

v9 进行中：nonsink **136.180 s**（v8 141.098 s），coarsen **77.233 s**
（v8 82.699 s）；完整 `nonsink.txt` 与 v8 **逐字节一致**。细分显示后期多轮
每次仅收缩少量 clusters，mode1/2 常无变化，quotient 各约131 ms、重排约140 ms，
候选约2–11 ms；容器替换不是主要构图成本。sink **55.722 s** 完成，仍为
144602 runs /913946 roots /2261545 DAG nodes /3788939 edges，进入 emitter。
内存观测记录 `full-native-v9/resource-observations.log`；至此未触顶、swap0。

v9 源码和库冻结后，仅在工作树准备下一轮补丁，不构建或替换本次已加载库：
未变化的 quotient 跨 mode/round 复用；私有宽常量支持 leaf literal assembly；
FIRRTL 静态局部写从旧 pieces 直接取得目标片段，避免先物化整数组再切片的依赖。
这些补丁尚未验证，不能归入 v9 结果。生成 identity 在 ingest 前已捕获，v9 源码
归档和已安装库 SHA 均保留，之后须复核库未替换。

v9 于 **01:38:15 UTC** 达到840 s截止，journal **841.86 s /137**，独立
recorder 保存正常终态（service wrapper **842.07 s**）。cgroup peak
**123239219200 B（114.78 GiB）**，swap **0**，max/oom/oom_kill/group_kill 均0。
库 SHA 结束复核仍与冻结一致。没有发布完整 model，不启动本轮 compile/runtime。

这次 emitter 实测：schedule verification **24.850 s**；context analyze
**54.409 s**，其中 leaf planning约14.8 s、use-coverage elision **17轮/约15.5 s**。
constant source functions约0.12 s；全部21789个nonsink函数正文生成 **93.137 s**，
已写 **6965809110 B**。writer阶段首个进度之后累计 **7629282190 B**、
**9763444 Code节点**，context累计159.066 s，随后超时。可以确认正文生成及规模
是主要开销，不能再把失败泛归为 analyze 固定点扫描。下一轮针对静态局部写的旧值
依赖、宽常量 leaf assembly 与已测重复扫描继续优化，保留相同资源和时间上限。
证据 `full-native-v9/{driver.log,generation-resources.json,resource-observations.log,logs/}`。

v10 准备：四项实现完成并经独立只读复核：静态局部写从 pieces 直接组成旧目标
片段；未变化的 quotient 跨 mode/round 复用；私有宽常量按叶片 literal/RLE
直接写目标；use-coverage 使用反向 worklist，按 operand use 处理重复依赖，
保留 materialized、control、跨 owner 阻塞及无 seed 环。没有增加 runtime wide
临时或更改 helper ABI、4096 规划限额、分图候选/成员/拓扑顺序。

node/partition/transform/sink 回归通过；emitter generation通过，**14** 个生成模型
实际编译运行 **46.46 s /exit0**。新增常量用例覆盖80-bit mixed runs、4096-bit
压力、signed1/2/4/8叶、24级候选链/重复use、复用frame、两实例重启、packed/
boundary/waveform观察和counter/source-map。FIRRTL state/memory生成与实际运行
**76.12 s /exit0**，aggregate含新增多piece/重叠guard/动态切换用例通过。

aggregate既有测试原先检查已退役的legacy node attrs，现改为等价6个字段
SemanticTree身份检查；原始数组假环未经过flatten/comb-loop就直接Oracle，还会
递归栈溢出，v9冻结库亦复现。行为解释改在独立规范化副本上执行，原图形状、
metadata、roundtrip、真实环拒绝、unknown断言保留。新增emitter fixture使用真实
跨owner消费者建立存储边界，不能给纯constant伪造sampleBoundary；verifier没有
放宽。诊断和通过记录均保留在 `validation/v10-*.log`。安装后再次验证Python入口，
再冻结 v10 并受限运行；尚无本轮全图通过结果。

安装 **49.07 s /exit0**，安装后 flow 及80项workflow再次通过；输入/源码归档/
已安装库SHA核对通过。**02:00:29 UTC** v10 正式启动，service
`wolvrix-capped-b0b325052e644b8c94f5b1a428ae502f.service`，启动证明确认
128 GiB / swap0 / oom.group=1。目录 `full-native-v10/`；仍使用原始 `b313a3ec…`
FIRRTL 和冻结harness，840s生成截止；本轮没有其他编译/仿真负载。
本条为开始记录，不代表全图生成通过。

v10 于 **02:12:28 UTC** 正常报错退出，run journal **719.57 s / exit1**，
独立 service **719.75 s / exit2**。nonsink **58.908 s**（v9 136.180 s），
其中 coarsen **13.716 s**；sink **50.278 s**。emitter analyze **20.447 s**，
正文 **6713541941 B**、**57964** definitions 写入 **7187** translation units；
此后完整流式 code-map 写完，触发默认单文件 **4 GiB** 输出检查，emitter 以
`Generated artifact exceeds maxOutputFileBytes: code-map.json` 拒绝发布。
没有完整 model，不启动 compile/runtime。此轮不是超时或 OOM：cgroup peak
**114453049344 B（106.59 GiB）**，swap0，max/oom/kill 均0；结束复核已安装库
SHA 与冻结一致。完整失败 journal、资源和开始身份均在 `full-native-v10/`。

复核确认 `maxOutputFileBytes` 是磁盘 artifact 检查，不是内存限制；code map
使用 `StreamingJsonWriter`，完整文件 close 后才检查大小，没有在内存积累全文件。
现有文档、Make/CLI 和回归已支持显式更大的输出预算。下一轮 v11 仅对这份全图
显式设置 `XS_GRHSIM_MAX_OUTPUT_FILE_BYTES=34359738368`，保留全部 v1 映射、
readable graph 和相同 C++；**128 GiB / swap0 / 840s** 不变。此设置不改变分图、
调度或运行代码，不修改通用4 GiB默认值。后续仍须通过完整生成与各独立验收。

**02:16:44 UTC**：v11 正式启动，service
`wolvrix-capped-6c80177f5fa142dbaaa83163a08ee0d7.service`。启动 sidecar 已核对
128 GiB / swap0 / oom.group=1，生成截止 **02:30:44 UTC**。源码、输入与原样
v10 已安装库重新冻结于 `full-native-v11/`；本轮没有其他全图负载。
沙箱内首次启动因无法连接 user bus 在 ingest 前拒绝，预检失败日志/资源独立
保留为 `sandbox-preflight-*`；正式启动使用受限 service，没有绕过 cgroup。
此外 wrapper 新增可选 service RuntimeMaxSec + SIGKILL，用于后续完整编译330s
整组截止，默认不影响生成。11项 mock 回归通过，尚不代表真实编译通过。

新增截止机制的真实64 MiB /2s小负载验证通过：主进程和另起session的子进程
均由service级SIGKILL终止，外层recorder存活并收集完整sidecars；result=timeout、
KillSignal=9、KillMode=control-group，峰值 **18280448 B**、swap0、OOM0，
含取证总墙钟 **2.255 s**。证据 `memory-audit/deadline/service/`；这只验证
截止/隔离机制，不代表完整330s编译验收。正式编译仍必须是fresh全模型+harness+link。
