# NO00021：按采样等价类共享 commit history

- Node：`history_batch_overwrite_20260912_01`（续行仍属同一节点）。
- 当前阶段：`ACCEPTED`；六次交替复测、50k 等价和完整生成/编译门槛均通过。
- 根基线：`20089a0`，子模块指向 NO00020 的 `8801a711fb9283969dc4252bfd99c19f8976a6ca`。
- 本轮实验：`no00021_history_cohorts_20260913_01`。

## IDEA：从省略复制改为消除重复采样

原始方案为完整覆盖的 history batch 省去 visible→shadow memcpy，并缓存重复
boundary event。前期尝试未取得合格收益，详见下文的否定记录。本轮转向更大的结构
限制：旧 `planSharedHistories()` 要求整个 commit task 的所有 history 都满足私有、
单次引用等条件。一个被观察、被直接写入或多次引用的 history，会阻止同 task 内
其他独立 history 共享。此前热点 task 5141 / 5142 占 activity-word-scan profile 的
282/13,789 样本（2.05%，不含 helper）；此外 `cpu_write_scalar<bool>` 占 1.97%。
剩余 212 个 batch、16,096 个 byte-history 仍在反复采样、暂存和发布。

机制是逐个 history 证明采样序列等价，再按等价类共享存储和边沿谓词。适用于
`DomainGatedCommit` 和因无关 history 冲突而回退的 `AlwaysScanCommit`。这是对
混合 task 的采样上下文分析，不是扩大复制 helper 或调整编译参数。触发条件完全
来自引用、事件、类型、初始化、发布目标和 task 归属，不匹配模块名。

局部预期为总 Host 时间降低 1–5%，主要来自重复采样、发布及边沿检查的删除；
commit 相位 22.06 s 是粗略成本上界，不能把静态条数直接换算成运行收益。证伪条件：
聚焦回归或 50k 终点改变、生成/编译达到 1800 s、仿真达到预选止损线，或者正式
六次交替复测无法把收益与噪声分离。节点必须取得统计确认的真实收益后才结束。

## BASELINE 与预注册

- XiangShan：`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，top `SimTop`。
- 输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`；SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 对照为 [NO00020](NO00020-grhsim-ir-candidate-seed-quiesce-20260911.md) 的未插桩
  seed-quiesce 构建，源码 `8801a711`。对照可执行文件
  SHA-256 `0a3ed4790bf50a88328cba9e485a786cfa909e6858c8c34e55a8c1233143b3c3`。
- 本轮统一 `XS_NUM_CORES=1`（harness，与 NO00020 实际构建一致）、
  `XS_EMU_THREADS=1`、CPU 2、50,000 cycles；waveform、commit/RAM trace、
  runtime profile 关闭。仍使用冻结的现有 RTL，不重新用单核参数生成 XiangShan RTL。
- 标准 NEMU：`testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`；SHA-256
  `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。
  本轮不使用前期实验的 dual NEMU 替代路径。
- 主机 32 CPU；新旧可执行文件均为 clang **22.1.2**（ELF `.comment` 验证一致）；
  候选模型采用 `clang++ -std=c++20 -O3`，编译 32 jobs。
  不变配置的 gsim 20.640 s 档案复用，不重跑。
- 启动前固定参考 66.962 s，仿真进程树截止 `100.443 s = 1.5 × 66.962`。
  生成和编译均在启动前安装 1800 s 进程树 KILL；超时隔离未完成 flow。
- 完整生成从 Make 启动计时，包含 Python 包更新、SV 读取、GRH 转换、IR、C++
  和 Makefile 发射；不以 checkpoint 恢复代替。编译从 build-only Make 启动至 emu
  链接完成。仿真墙钟在 emu 执行前计时，不计 Make 编译或初始化工具的准备时间。
- 正式复测在筛选通过后按 `old1 / new1 / old2 / new2 / old3 / new3` 顺序，
  同一窗口内串行、独占运行。Host 为主指标，同时记录 emu 墙钟、退出码和终点。
  每组保留 3 次有效运行；无效运行作废并补跑。报告均值、样本标准差、变化比例、
  效应量和 Mann–Whitney 单侧精确检验；只有 `max(new)<min(old)` 才接受。
  筛选/插桩诊断不纳入正式六次样本；所有日志、时间和临时目录在 `ptmp/`。

## IMPLEMENTED：语义证明与改动

本轮从已存在的子模块提交 `440eb889117c60a51fc0945e165ffe1424449cbd` 继续；它包含
最初的 overwrite helper 和 commit boundary event 快照。本轮入口还存在未提交的
helper/cache 实验。保存其完整差异后移除了未验证的 bool always-inline helper、
compute operand cache、无调用的 pattern helper、非连续 `(history,event)` 去重，
然后实现本方案。该既有提交早于本次续行，不重写历史；本轮仅在最终验收后提交。

实现仅改 CPU emitter 与回归/文档，冻结 GRH、GRH pass、XiangShan 和测试负载不变。
逐 history 收集当前 task 的事件采样引用，并与全模型引用总数比较。资格如下：

1. 所有引用都是本 task 中 `regWrite/memWrite/memFill/memWriteSeq` 的无条件
   posedge/negedge 采样，且每次采样同一 event ValueId。
2. event 为不经 state-read alias 的 boundary 读取；commit task 不写 boundary，
   所以整个调用期间该事件值不变。
3. history/event 均为同一 unsigned two-state 1-bit 类型；history 唯一初始化
   记录为常量，publication 目标恰为本域 arm。
4. 等价类键为 `(event ValueId, history TypeId, 规范化初始常量)`。同一 history
   被多个端口采样允许；外部读取、直接写入、跨 task 引用、不同 event 和随机初值
   均保留独立存储。无关不合格 history 不再否决整 task。

相同初值加相同的无条件采样序列，归纳保证每次 publication 后值相等。各 guard
始终读取 visible history，shadow 不会提前暴露；代表元的原始采样和所有 payload
写顺序保留。只有所有 history 均通过上述证明的重复边沿谓词才缓存。布局 arena
大小与 IR/schedule 元数据不变，无新增运行时分配或宽值返回数组。

例：`h0=0` 被两个端口采样 `clk`、`h1=0` 被一个端口采样 `clk`、`h2=0` 被外部
读取，则 h0/h1 可共享，h2 独立；h0 的两次原始采样仍保留。如果同一 h0 依次采样
`clk_a; clk_b; clk_a`，则不得共享或跨越中间写入去重。

聚焦测试通过：`make test_grhsim_cpu_emit`，50.88 s、1/1 PASS。
`test_grhsim_cpu_schedule`、`test_grhsim_cpu_mapping`（含 IR suite）均 PASS。
新的混合 task 夹具确认 11 个 history 合并，保留不同初值、观测 history、额外
写入和跨时钟域 last-writer-wins 行为；同一 history 的多引用也有覆盖。原扫描
夹具改为观察全部 history，确保独立范围扫描仍被测试。随机初始化 history 不得
共享，新增其 batch overwrite 的运行验证。生成模型测试使用 ASan/UBSan，含
四次 init 和数千次事件/数据变化；测试中的 O0 编译仅用于检查内存语义，性能模型
始终 O3。两次测试准备失败分别为旧静态覆盖断言失效、尝试多步 scalar InitSpec
被 emitter 正确拒绝；已用合法夹具修正，失败结果不作为验收证据。

## 复现命令

以下为本轮固定参数；从根仓库运行。路径作为运行参数列出，不作为结果分析的替代。

```bash
root=$PWD
node=$root/ptmp/no00021_history_cohorts_20260913_01
export PATH="$root/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export TMPDIR="$node/tmp" PIP_CACHE_DIR="$node/pip-cache"
export CCACHE_DIR="$root/ptmp/cpu_emit_ccache" CMAKE_BUILD_PARALLEL_LEVEL=32
export LC_ALL=C EMU_RUNTIME_PROFILE=0
mkdir -p "$node/tmp" "$node/logs"
common=(PYTHON="$root/.venv/bin/python" XS_NUM_CORES=1 XS_EMU_THREADS=1
  VM_BUILD_JOBS=32 XS_VM_BUILD_JOBS=32 XS_SIM_MAX_CYCLE=50000 XS_EMU_CPU=2
  XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_RAM_TRACE=0
  XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0 WOLVRIX_GRHSIM_PERF=0
  XS_LOG_DIR="$node/logs" XS_GRHSIM_IR_BUILD="$node/flow-final"
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$node/flow-final/model"
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0)
make --no-print-directory test_grhsim_cpu_emit test_grhsim_cpu_schedule test_grhsim_cpu_mapping
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/generate.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir "${common[@]}" \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 RUN_ID=no00021_cohorts_full_generate \
  > "$node/generate.log" 2>&1
/usr/bin/time -f 'wall_s=%e,user_s=%U,sys_s=%S,exit=%x' -o "$node/build.time" \
  timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  "${common[@]}" RUN_ID=no00021_cohorts_full_build > "$node/build.log" 2>&1
# 正式六次的 Make 调用顺序；复现时另选目录和唯一 RUN_ID，保留既有记录。
for pair in 1 2 3; do
  for version in old new; do
    run_id="no00021_cohorts_${version}${pair}"
    run_flow="$node/flow-final"
    if [[ "$version" == old ]]; then
      run_flow="$root/ptmp/seed_quiesce_20260911_01/flow"
    fi
    make --no-print-directory run_xs_wolf_grhsim_ir_emu "${common[@]}" \
      XS_GRHSIM_IR_BUILD="$run_flow" RUN_ID="$run_id" \
      "XS_EMU_PREFIX=timeout --signal=KILL 100.443s /usr/bin/time -f wall_s=%e,user_s=%U,sys_s=%S,exit=%x -o $node/$run_id.emu.time taskset -c 2 stdbuf -oL -eL" \
      > "$node/$run_id.log" 2>&1 || exit "$?"
    # 实际脚本在每次继续前检查退出码及下述 NEMU 终点，失败即停。
  done
done
```

实际执行脚本逐步记录命令、起止时间、Make/emu 退出状态与时间；异常终止立即
停止该尝试。仿真另检查 73,580 instructions、cycleCnt 49,996、PC `0x80001312`、
guest cycles 50,001，且无 mismatch、assertion 或 BAD TRAP。

## VALIDATED

正式完整 SV→C++ 生成 `no00021_cohorts_full_generate`：Make 墙钟 **597.25 s**
（user 669.35 / sys 17.93 s），exit 0，1800 s 门槛通过。包含 package 更新和
完整 SV/GRH/IR 路线；内部 flow 时间 591.679 s，未从 IR 恢复。fresh `flow-final`
中完整 C++、header 和 Makefile 与筛选 `flow-resume` 的对应源码逐字节一致。
flat GRH 与 NO00020 `cmp` 完全相等，SHA-256
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`；
GrhSIM IR round-trip 同样稳定。正式 fresh 32-job 编译
`no00021_cohorts_full_build`：Make 墙钟 **265.58 s**（user 6429.26 / sys 463.70 s），
exit 0，1800 s 门槛通过，未复用筛选对象文件。候选可执行文件 138199688 bytes，
旧构建 138412752 bytes；候选 SHA-256
`3cd75af70fd115a5f9fab97cd17ad68b4c06726993888236aea0abba16d029c0`。

### 正式六次交替复测

2026-09-13 12:57:56–13:04:31（UTC+08:00）按预注册顺序完成全部六次运行。
下表 RUN_ID 均加前缀 `no00021_cohorts_`；Host 是 emu 报告值，墙钟仅计 emu
执行区间。新构建使用上述完整生成、fresh 编译得到的可执行文件。

| 顺序 / RUN_ID 后缀 | 启动时间 +08:00 | Host s | emu 墙钟 s | Make / emu 退出码 | 等价性 / 状态 |
|---|---|---:|---:|---|---|
| 1 / old1 | 12:57:56 | 67.350 | 67.38 | 0 / 0 | NEMU PASS / VALID |
| 2 / new1 | 12:59:04 | 63.319 | 63.35 | 0 / 0 | NEMU PASS / VALID |
| 3 / old2 | 13:00:07 | 66.480 | 66.51 | 0 / 0 | NEMU PASS / VALID |
| 4 / new2 | 13:01:14 | 65.287 | 65.31 | 0 / 0 | NEMU PASS / VALID |
| 5 / old3 | 13:02:19 | 66.547 | 66.58 | 0 / 0 | NEMU PASS / VALID |
| 6 / new3 | 13:03:26 | 65.150 | 65.18 | 0 / 0 | NEMU PASS / VALID |

六次均仅初始化 core 0 的 difftest，均在 73,580 instructions、cycleCnt 49,996、
PC `0x80001312`、guest cycles 50,001 的相同终点退出；无 mismatch、assertion、
BAD TRAP 或超时。无无效样本和补跑，未丢弃任何正式样本。

| 统计量 | NO00020 对照 | NO00021 候选 |
|---|---:|---:|
| Host 均值 s | 66.792333 | 64.585333 |
| Host 样本标准差 s（分母 n−1） | 0.484114 | 1.098814 |
| Host 中位数 s | 66.547 | 65.150 |
| Host 最小–最大 s | 66.480–67.350 | 63.319–65.287 |
| emu 墙钟均值 s | 66.823333 | 64.613333 |
| emu 墙钟样本标准差 s | 0.483356 | 1.096008 |

Host 均值减少 **2.207 s**，按 `(old_mean−new_mean)/old_mean` 计算为
**3.304271%**；墙钟同口径降低 **3.307228%**。全部九个新旧跨组比较均为新快：
`max(new)=65.287 < min(old)=66.480`，最小间隔 **1.193 s**。Mann–Whitney
`U_new=0`，无并列值；n=3+3 的 20 种标签分配中只有一种达到该方向极值，
单侧精确 **p=0.05**，满足预注册秩次门槛。合并样本标准差为 0.849046 s，
以 old−new 为改善方向的 Cohen's d 为 **2.599388**；Cliff's delta 为 **+1**。

new1 比另两次候选快约 1.8–2.0 s，候选离散度高于对照；保留该值并报告全部
数据，不筛选最快值或替换样本。结论依赖同窗口六次交错的全秩分离，不能将此
小样本效应量外推到其他负载、CPU 或时段，也不能用历史 66.962 s 替代同期对照。

### 筛选与结构证据

筛选阶段从 NO00020 flat checkpoint 恢复，90.346 s 完成 IR/C++ 与稳定 round-trip；
该时间不作为完整生成门槛。O3/32-job 编译完成，50k 筛选 Host **64.791 s**、
emu 墙钟 **64.82 s**、exit 0、NEMU 对拍通过；73580 instructions、cycleCnt 49996、
PC `0x80001312`、guest cycles 50001。筛选值不纳入正式六次统计。

通过已有 `make analyze_grhsim_history_sharing` 比较生成源码；筛选和正式生成源码
逐字节相同，因此以下结构计数同样适用于正式候选。总 task 数仍为 5595。

| 静态指标 | NO00020 | NO00021 |
|---|---:|---:|
| bool initializer 数 | 399130 | 399130 |
| 独立 bool 地址数 | 100335 | 91931 |
| 逐 bool stage 站点 | 2873 | 1545 |
| history batch 站点 | 212 | 0 |
| 边沿快照数 | 496 | 500 |
| 边沿快照复用次数 | 226510 | 230874 |
| 总 C++ bytes | 1340158730 | 1339210868 |

独立 bool 地址减少 8404，500 个 commit task 文件发生变化。新增共享与边沿
谓词复用的四个 task 为 5141、5142、5594、5595（这里只列举诊断结果，代码不以
这些编号触发）；5141 源码 3341946→2577431 bytes、5142 源码 471668→300540 bytes。
evaluator 主文件与 legacy runtime header 相对 NO00020 逐字节不变。独立地址数是
静态存储引用数，不表示 arena 分配缩小；这些条数也不是动态工作量。

前两次完整生成均被助手误判进程状态后主动 Ctrl-C：工具调用间的 PID namespace
隔离导致其他调用的 `ps` 不显示生成进程，而原会话仍报告运行中。这是观察错误，
没有证明编译器或生成器失败；均记 `INVALID / INTERRUPTED`，不作为时间证据。
后续后台脱离启动也未实际开始。筛选编译此前漏装计时/截止，因此同样不能作为编译
门槛证据。正式验收改用保留会话、同一 namespace 心跳观察、fresh `flow-final`
目录的完整 SV 生成与 1800 s 截止编译；不复用筛选对象文件。

## 前期尝试及审计纠正（均非节点完成）

- 原 overwrite-only 尝试记录约 0.63% 回归，未接受。
- overwrite + commit event snapshot 的旧六次表为：

  | 顺序对 | candidate Host s | old Host s |
  |---|---:|---:|
  | 1 | 67.163 | 67.306 |
  | 2 | 66.930 | 67.333 |
  | 3 | 67.378 | 67.914 |

  均值 67.157 / 67.518 s、差异约 0.534%。旧报告误写 `U=0, p=0.05`；实际候选
  67.378 慢于旧样本 67.306、67.333，`U=2`、单侧精确 `p=0.20`，未排除噪声。
  进一步核对日志发现 candidate 初始化 core 0/1 的 dual difftest，old 仅初始化
  core 0；因此整组比较配置不一致，判为 `INVALID`，不能作为性能收益证据。
- 早期漏参数生成了 526 个超大 task，编译超时终止，部分产物隔离；复用非空 emit
  目录也曾失败。恢复 flat checkpoint 的生成时间不能替代完整 SV 生成门槛。
  前期报告的 641.43 / 899.98 / 89.98 s 来自不同尝试，本轮重新完整验证。
- 后续 helper/cache 试验日志 Host：75.548、68.770、67.957、69.524、75.499、
  75.102、75.108、70.722 s。其同期少量旧构建值 66.598 / 67.646 s，不形成有效
  六次交替统计；没有被接受。本轮已删除这些实验的未验证代码，保存差异供追溯。
- 既有子模块 `440eb889` 在本次续行前已提交，入口根仓库仍指向 `8801a711`。
  最终归档保留该历史，清楚区分既有提交和本轮验收后提交；已有提交本身不表示
  节点通过。本轮正式测量覆盖其与采样等价类共享的组合，未单独归因各自贡献。

## 最终判定与归档

判定 **ACCEPTED**：聚焦 emitter（含 ASan/UBSan 生成模型）、schedule、mapping
和 IR 测试通过；完整生成 **597.25 s**、fresh 编译 **265.58 s** 均低于 1800 s；
冻结 flat GRH 逐字节不变；正式六次 50k NEMU 对拍均通过；同窗口 Host 均值
降低 **3.304271%**，全部新样本优于全部旧样本，单侧精确 p=0.05。

本轮最终子模块提交：`118d024096d7cfc0792227b6dcde971b6f44ae1d`
（`perf(grhsim): share histories within mixed commit tasks`），父提交为既有 `440eb889`。
保留改动为 [CPU emitter](../wolvrix/lib/grhsim/backend/cpu_emit.cpp)、
[emitter 回归](../wolvrix/tests/grhsim/test_cpu_emit.cpp)、
[history 运行夹具](../wolvrix/tests/grhsim/data/cpu_history_scan_main.cpp) 和
[CPU 后端文档](../wolvrix/docs/grhsim_ir/backends/cpu.md)。根仓库集中提交该子模块
指针、本报告、[索引](grhsim-ir-xiangshan-coremark-50k.index.md) 和
[goal 当前最佳记录](grhsim-ir-xiangshan-coremark-50k.goal.md)。生成代码、日志、
profile、波形、二进制及临时实验补丁留在 `ptmp/`，不纳入归档提交。

当前最佳均值 **64.585333 s**，距约 40 s 仍差 **24.585333 s**，整个性能目标未完成。
本轮未追加相位/profile 诊断；旧版 compute 42.96 s、commit 22.06 s 等数据仅用于
提出假设，不能当作候选相位实测。后续方向应先刷新残余成本证据，再探索 compute
输入粒度的重复求值消除和未覆盖的 staged memory 访问；5141/5142 的私有多引用
history 已由本节点覆盖，不再视为未处理问题。本次仅完成 NO00021，不启动下一节点。
