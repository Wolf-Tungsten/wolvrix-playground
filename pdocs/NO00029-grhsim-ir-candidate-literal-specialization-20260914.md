# NO00029：GrhSIM IR 代数归一化与表达式共享

- Node：`literal_specialization_20260914_01`（节点编号保留，方向已从字面量发射调整为 IR 归一化）。
- 当前阶段：`ACCEPTED`；正式六次复测、完整路线和归档提交均已通过。
- 根基线 `dd453b0`，GrhSIM 子模块基线 `8b8c990adbeced0a46b2d1cfad5330d165e6ab2d`（NO00028）。
- 本节点主证据目录为 `ptmp/no00029_literal_specialization_20260914_01/`；旧流程目录偏差见下文。

## 理论依据与当前方案

用户指出代数化简应修改 GrhSIM IR。当前实现放在已有 SemanticTransform
`grhsim.canonicalize-compute`，CPU emitter 已恢复基线。这样删除的运算和重接的
ValueId 会进入后续依赖、分区及调度分析。新意在于把常量恒等式、可交换表达式
归一化和已有 CSE/等价状态共享连接起来，消除重复求值和相应的数据依赖。

初始假设把生成源码中约 1,430,333 次常量截断 helper 语法当作运行时调用，
依据不足。代表 task 的反汇编后来显示相同指令：编译器已折叠许多常量。
最早引用的 26,355 样本实际来自 NO00028 实施前的 NO00027 二进制，不能冒充
当前基线 profile。字面量首版正式复测失败后已撤回该 emitter 改动。

本次重新对确切 NO00028 基线在 CPU 2、100k、单线程配置采样。该诊断运行退出
0，Host 126.186 s，NEMU 终点精确一致；200 Hz 共 25,241 样本。通过现有
`analyze_grhsim_cpu_profile` 验证 ELF 映射、符号边界、task 覆盖、样本总数后：

| 类别 | 样本 | 占比 |
| --- | ---: | ---: |
| compute tasks | 17,807 | 70.547918% |
| commit tasks | 4,454 | 17.645894% |
| evaluator | 719 | 2.848540% |
| 其余主程序 | 2,003 | 7.935502% |
| 外部库 | 202 | 0.800285% |
| 未映射 / 主程序未解析 | 51 / 5 | 0.202052% / 0.019809% |

4,449 个 compute task 中 2,880 个被采到，前十个只占 727 样本（约 2.88% 总量）。
因此应利用通用图结构覆盖分散计算，不能把某个生成文本 helper 的数量等同于
动态成本。若能削减 compute 成本的 1–5%，忽略其他影响时整体上界约 0.7–3.5%；
本轮局部目标 0.5–3%，这是可证伪假设，不是已经取得的收益。最终以同窗口交替
100k 实测为准，静态 op 数下降不能单独证明收益。

当前规则仅用于两态纯计算：同完整类型的标量零/一/全一恒等式，常量条件或
相同分支 mux，同值 and/or；逻辑恒等式要求 1 位。输入同类型的已知可交换
运算按 ValueId 构造无序 CSE 键，减法等保留顺序。保留 parameters、类型转换、
四态值及循环；有符号 1 位除法保守保留，模除/除零不套用恒等式。常量先按
字面量符号 resize，再将 X/Z 投影为零，读取该位宽原始位模式。拓扑遍历先解析
操作数别名，再化简及 CSE，后继立即看到替代值；等价状态共享仍按既有逻辑重复。

## 输入、配置、计时与复现

- CoreMark：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 基线 emu SHA-256：`d3540cf80d0e4b3044d0d57bcee983a3493ce335c4e552bb72ca74b9e66f1912`。
- 冻结 flat GRH SHA-256：`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`。
- 基线 GrhSIM IR SHA-256：`0229e80c1f4dd1f70d4034017ccb9aa86d2fb5aa2e304685ef21e740d6e21cf5`。
- 所有工作通过 Makefile；环境 `PATH=$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH`、
  `WOLF_ENV_SOURCED=1`、`PYTHON=$PWD/.venv/bin/python`。`XS_LOG_DIR` 必须是 make
  命令行参数，环境赋值会被 Makefile 的 `:=` 覆盖。
- 正式运行：CPU 2，`XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1`，100,000 cycles；
  waveform、commit/RAM trace、progress 关闭。正式性能不启用 profiler。
- 精确 100k 终点：`instrCnt=240349 cycleCnt=99996`、guest `100001`、PC `0x80000c0c`；
  历史 50k 筛选终点：`instrCnt=73580 cycleCnt=49996`、guest `50001`、PC `0x80001312`。
- 主指标为 emu Host time，另列 emu wall 和退出状态。生成/编译墙钟从 Make 启动
  到目标结束，启动前以 `timeout --signal=KILL 1800s` 安装进程组截止。仿真预选
  NO00028 正式均值 126.976 s，止损 `190.464s`（1.5 倍）；失败立即否定当前尝试。
- 正式须从 SV 完整生成，resume=0，fresh 编译；恢复 flat GRH 只用于筛选。
- 六次正式顺序须运行前登记 `old1/new1/old2/new2/old3/new3`，三次新都快于三次旧
  方可接受，报告均值、样本 SD、效应量、单侧精确 Mann–Whitney U/p。
- gsim 100k 复用 46.965 s，本节点只验收相对 NO00028 的局部收益。

## 已否定的尝试与验证缺陷

所有以下尝试均未 ACCEPTED，不提交中间代码。历史 50k 样本仅用于筛选，不能
代替当前 100k 正式门禁。生成产物、日志和二进制只保留在 ptmp。

| 尝试 | 结果与限制 |
| --- | --- |
| 字面量直接编码 | 完整 SV 生成约 658.167 s、fresh 编译约 234.4 s；task 文本 1,128,306,810→1,087,948,648 bytes，常量截断语法 1,430,333→0。六次正式复测不通过，数据见下表。 |
| emitter 纯标量常量折叠 | 先修正 `-1` 在 32→64 位转换中的符号扩展错误；聚焦 suite 67.84 s PASS。模型中没有全常量的纯计算，最终 task 源码与字面量首版相同。50k 新 53.217 s、随后旧 53.884 s 不能证明相同模型代码取得收益。 |
| 常量 cast 特化 | 去掉 656,005 处 helper 语法，50k 新 54.697 s，无正式验收。 |
| 去掉全部冗余 cast | 50k 新 54.656 s，ELF text 增约 86 KB，无正式验收。 |
| 只去掉等宽 cast | 50k 新 54.117 s，text 仍增，无正式验收。 |
| emitter 代数恒等式 | 50k 新 53.879 s，仅删除约 7,712 处 cast，native code 减少很小；已按用户要求撤回并迁移至 IR。 |
| IR 初版 ir-screen | values 3,762,933→3,734,311，ops 3,988,626→3,958,979。恢复生成内部计时 155.012 s；50k 新 Host 54.252 s / wall 54.28 s，随后旧 Host 54.218 s / wall 54.25 s。没有收益证据。 |
| IR mux 版 ir-screen2 | values 3,730,566、ops 3,954,968，恢复生成内部计时 146.311 s；50k 新 Host 54.333 s / wall 54.36 s，text 115,519,518 bytes。没有相邻独立旧样本，不作性能结论。 |

两版历史 IR screen 含后来删除的错误 `x % 1 -> 1` 规则，且未用直接规则测试
覆盖；虽然 50k 终点一致，不能证明该规则正确，也不能作为当前源码的验证。
这些是恢复 flat GRH 的生成，不是完整 SV 生成。旧报告误写了运行时刻、Host/wall、
profile 来源、活动传播影响和聚焦测试归属，本版已纠正。IR 重接确实会改变后续
依赖/活动传播的结构，必须以语义和完整仿真验证保证行为等价。

早期 Make 次级日志因环境赋值被覆盖而落在 `build/logs/xs`，pip 的临时缓存也曾
落在 `/tmp`，不符合项目目录要求；主实验日志仍在 ptmp。本轮已用命令行
`XS_LOG_DIR` 和项目内 `TMPDIR/PIP_CACHE_DIR` 修正，不把旧目录偏差隐去。

字面量首版正式 100k 六次（主日志在 ptmp，部分历史 tool 记录未单列退出 metadata；
日志均正常到达终点，无 difftest mismatch，不能补造缺失 metadata）：

| 顺序 | Host s | emu wall s |
| --- | ---: | ---: |
| old1 | 126.900 | 126.93 |
| new1 | 127.911 | 127.94 |
| old2 | 126.225 | 126.26 |
| new2 | 126.079 | 126.11 |
| old3 | 126.065 | 126.09 |
| new3 | 127.593 | 127.62 |

旧均值 126.396667 s、样本 SD 0.443180 s；新均值 127.194333 s、SD 0.978906 s，
新慢 0.631082%，没有秩次分离。以“新更快”为备择，`U_new=7`，枚举 20 种分组
得到单侧精确 `p=0.90`。该尝试 `REJECTED`。首版 emu SHA-256
`9935c5b8e8a700b28bbc4d4136ca2d1ccdc1763cca2f2f8f30534378419493f6`。

## 当前实现验证与门禁记录

新增直接 IR 测试覆盖 1/5/64 位有符号/无符号恒等式、不同常量参数表示、X 投影、
逆序操作、常量别名、吸收律暴露后继、交换 CSE、非交换操作、模除与除零、重复
运行幂等性及 JSON round-trip。扩展已有生成 C++ identity fixture，把零/一/全一
化简放在组合结果和状态快照的读写路径，沿用随机/穷举输入、重复 eval、多次
init 和 ASan/UBSan 检查。初次测试发现 `SVInt::as<uint64_t>()` 对负数符号扩展
影响窄位模式，修为 resize 后 `getRawPtr()[0]`，1 位回归通过。

`make test_grhsim_cpu_mapping test_grhsim_cpu_schedule test_grhsim_cpu_emit` 已通过
（IR/mapping/schedule 各约 0.01 s，最终 emitter 71.62 s）。类型/参数/循环负例
也已在 IR suite 通过；完整 SV 生成、fresh 编译和正式六次均见下文。

类型/参数/循环负例已通过 `make test_grhsim_cpu_mapping`。当前源码冻结后启动
`flow-canonical-full` 完整路线（resume=0），输出目录此前不存在生成物。设置
`TMPDIR`、`PIP_CACHE_DIR` 到本节点 ptmp 子目录，保留命令日志和步骤 wall/exit。
生成入口为 `xs_wolf_grhsim_ir`，参数：

```sh
XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl
XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src
XS_GRHSIM_IR_BUILD=ptmp/no00029_literal_specialization_20260914_01/flow-canonical-full
XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/no00029_literal_specialization_20260914_01/flow-canonical-full/model
XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0
XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0
XS_LOG_DIR=ptmp/no00029_literal_specialization_20260914_01/flow-canonical-full/logs
RUN_ID=no00029_canonical_full_generate
```

预注册本候选的正式顺序仍为 `old1/new1/old2/new2/old3/new3`，主指标 Host，
各组 3 个有效 100k 样本、190.464 s 止损，按前述秩次门禁判断；不根据中途的
好坏样本选择性丢弃或调整顺序。若候选失败，在本节点记录并修改机制。

完整生成启动后的边界复核又发现：常量同时携带 `value` 和 `constValue` 时，
不能按参数存储顺序任选其一。新增保守限制：只读取恰好一个参数的常量，并加入
两种参数顺序的负例。已启动的 `flow-canonical-full` 使用这一限制之前的源码，
只能作为该版本实验；最终接受前仍需对最终源码完成完整 SV 路线。

筛选版 `flow-canonical-full` 已完整生成：Make wall **683.86 s**、内部计时
657.972 s、exit 0；stable JSON round-trip PASS。flat GRH 哈希与基线相同，
该版 IR 哈希 `919d4242b1c60caec9ca3afe7e6c671e1e4856fdc71828d7f916102b58c7a30b`。
这是未加多参数常量保护的筛选版本；最终版本对同一工作负载的 IR/C++ 输出逐字节一致。

| 静态指标 | NO00028 | 筛选版 | 减少 |
| --- | ---: | ---: | ---: |
| operations | 3,988,626 | 3,937,483 | 51,143（1.282221%） |
| values | 3,762,933 | 3,713,085 | 49,848 |
| states / init records | 467,657 | 464,343 | 3,314 |
| C++ tasks | 4,954 | 4,896 | 58 |
| task C++ bytes | 1,128,306,810 | 1,109,025,895 | 19,280,915（1.708836%） |

通过 `make audit_grhsim_cpu_emit GRHSIM_AUDIT_MODEL=...` 比较两份 IR：or 减少
15,263、mux 12,321、and 8,470、logicAnd 3,379、logicOr 2,800、eq 1,445；
regWrite 少 1,295、state.read 少 1,294。其余 concat、slice 等也因后续 CSE 减少，
说明规则确实暴露了跨计算链和状态的进一步共享，而非只改了表达式文本。
静态操作下降不能单独证明收益；正式复测随后确认了动态收益。

包含最终常量参数保护的 emitter suite 复验 PASS，CTest **71.62 s**，Make wall
71.86 s、exit 0。测试与生成并行的时长不作为性能样本。

在任何本版性能样本运行前调整计划：由于筛选版早于最后的参数保护，其原定
六次正式运行取消，改为仅 `old1/new1` 的 100k 同窗口方向筛选，不能作接受证据。
完整六次留给最终源码生成/编译的版本；没有根据中途样本改变选择。两次筛选
仍使用同一 CPU 2、190.464 s 止损和关闭 profile/trace 的配置。

筛选版 fresh 编译：`xs_wolf_grhsim_ir_build_emu`，32 jobs、单线程 emu，Make wall
**226.59 s**、exit 0。emu SHA-256
`72b12b83ff96cbfa092c3495f5dd6654a23bb0ed32b89041730d90a70e3a9943`；ELF text
**116,262,582→114,297,322 bytes**，data/bss 均 9,344/18,416 bytes。
主机为 AMD Ryzen 9 7950X3D，16 cores / 32 logical CPUs；仿真固定逻辑 CPU 2，
两次运行期间不再执行构建或生成。

筛选版同窗口 100k：old Host **125.143 s** / wall **125.17 s**；new Host
**122.599 s** / wall **122.63 s**。两次 Make/emu 均 exit 0/0，达到精确 100k
NEMU 终点，无 mismatch/profile 输出，截止未触发。单对快约 **2.032874%**，
支持进入最终版本验收；它不是六次统计结论。

最终源码冻结到 `flow-canonical-final/source.patch`，pass 文件 SHA-256 为
`57104193bdc96919443c953ece3a21af114b048d2394584af1571e38e71c3f32`，emitter
与 NO00028 完全一致。新增常量多参数保护后，IR/mapping 与 emitter suite 均已
通过。启动新目录 `flow-canonical-final` 的完整 SV 路线，resume=0，沿用上文
全部资源/环境和 1800 s 截止，`RUN_ID=no00029_canonical_final_generate`。

正式预注册：以该最终完整模型为 new，NO00028 完整模型为 old，顺序
`old1/new1/old2/new2/old3/new3`，RUN_ID 前缀 `no00029_formal-canonical_`。
CPU 2、100k、单线程、profile/trace 关闭、190.464 s emu 截止；Host 主指标，
另记录 emu wall、Make/emu exit 和精确 NEMU 终点。全部有效样本保留，三次新
须全快于三次旧，按 20 种 3+3 分组计算单侧精确 Mann–Whitney U/p。

## 最终路线的复现命令

XiangShan revision 为 `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，复核工作区
无源码修改。以下从 playground 根目录执行；另选一个不存在的新 flow 目录可
重做完整流程，生成/编译计时都包含对应 Make 目标的全部子步骤。

```sh
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1
node_dir="$PWD/ptmp/no00029_literal_specialization_20260914_01"
final_flow="$node_dir/flow-canonical-final"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
mkdir -p "$final_flow" "$TMPDIR" "$PIP_CACHE_DIR"
timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$final_flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD="$final_flow" XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$final_flow/model" \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 \
  XS_LOG_DIR="$final_flow/logs" RUN_ID=no00029_canonical_final_generate \
  > "$final_flow/generation.log" 2>&1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e,exit=%x' \
  -o "$final_flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$final_flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$final_flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 \
  XS_LOG_DIR="$final_flow/logs" RUN_ID=no00029_canonical_final_compile \
  > "$final_flow/compile.log" 2>&1
```

只有生成和编译均成功、wall 小于 1800 s 才进入运行。原始使用的串行运行脚本
逐项记录命令、起止时刻、Make exit、emu time 和精确终点；其主要命令等价于：

```sh
old_flow="$PWD/ptmp/no00028_profile_20260914_01/flow-direct-full"
for run_label in old1 new1 old2 new2 old3 new3; do
  run_flow="$old_flow"
  case "$run_label" in new*) run_flow="$final_flow";; esac
  run_dir="$node_dir/formal-canonical/$run_label"
  mkdir -p "$run_dir"
  env -u CPUPROFILE -u CPUPROFILE_FREQUENCY -u LD_PRELOAD \
    EMU_RUNTIME_PROFILE=0 EMU_PHASE_TIMING=0 \
    timeout --signal=KILL 210s make --no-print-directory run_xs_wolf_grhsim_ir_emu \
    PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$run_flow" \
    XS_LOG_DIR="$run_dir/logs" RUN_ID="no00029_formal-canonical_$run_label" \
    XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 XS_EMU_CPU=2 XS_SIM_MAX_CYCLE=100000 \
    XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_PROGRESS_EVERY_CYCLES=0 \
    XS_EMU_PREFIX="timeout --signal=KILL 190.464s /usr/bin/time -f wall=%e,exit=%x -o $run_dir/emu.time taskset -c 2 stdbuf -oL -eL" \
    > "$run_dir/make.log" 2>&1 || break
  # 每项退出状态与精确终点通过后才进入下一项；异常保留日志并停止。
done
```

基线采样使用同一 emu Make 目标，唯一诊断差异是 prefix 末尾加入
`env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so.0 CPUPROFILE=.../old.prof CPUPROFILE_FREQUENCY=200`。
分析为 `make analyze_grhsim_cpu_profile`，参数 `GRHSIM_CPU_PROFILE=.../old.prof`、
`GRHSIM_CPU_PROFILE_BINARY=.../flow-direct-full/emu/grhsim-compile/emu`、
`GRHSIM_CPU_PROFILE_MODEL=.../flow-direct-full/model/grhsim_SimTop.cpp`、
`GRHSIM_CPU_PROFILE_SAMPLES=25241`；该采样不进入正式性能统计。

## 最终完整路线结果

最终源码 `flow-canonical-final` 的完整 SV→C++：Make wall **672.24 s**、内部
653.781 s、exit 0，1800 s 截止未触发，fresh-session JSON round-trip 逐字节一致。
flat GRH 仍为冻结哈希 `518f4148…923`，最终 GrhSIM IR 为
`919d4242b1c60caec9ca3afe7e6c671e1e4856fdc71828d7f916102b58c7a30b`。
最终 IR 与筛选版逐字节相同，全部生成 C++、header 和 Makefile 也逐字节相同
（仅排除筛选版已编译的 `.o/.a`）。因此多参数常量保护在本工作负载没有触发，
前述 51,143 ops / 49,848 values / 3,314 states 的静态缩减同样适用于最终版。
最终版本随后执行了独立 fresh 编译及正式六次，避免混用构建身份。

最终 fresh 编译 Make wall **227.14 s**、exit 0，1800 s 截止未触发；没有复用
筛选版 `.o/.a`。最终 emu SHA-256
`339ce7e63fb2cb1c6f8d6a131be78caec9ad3367e0dfb93d8c8bcfcb7b6e5bbf`，ELF text
114,297,322 bytes，data/bss 9,344/18,416 bytes。正式六次已按预注册顺序完成，
编译与生成均已结束。

## 最终六次正式数据

以下均为最终二进制，100k、CPU 2、单线程、profile/trace 关闭，按登记顺序串行；
NEMU PASS 表示每次达到前述精确 PC/instrCnt/cycleCnt/guest 终点且无 mismatch。

| 顺序 | Host s | emu wall s | Make/emu exit | NEMU |
| --- | ---: | ---: | --- | --- |
| old1 | 126.061 | 126.09 | 0/0 | PASS |
| new1 | 123.005 | 123.03 | 0/0 | PASS |
| old2 | 126.512 | 126.54 | 0/0 | PASS |
| new2 | 123.069 | 123.10 | 0/0 | PASS |
| old3 | 126.499 | 126.53 | 0/0 | PASS |
| new3 | 122.018 | 122.05 | 0/0 | PASS |

三次 old 的 Host 均值 **126.357333 s**、样本 SD **0.256714 s**；三次 new
均值 **122.697333 s**、样本 SD **0.589190 s**。new 比 old 快 **2.896547%**，
均值差的 Cohen's d（new−old）为 **−8.053720**，Cliff's delta 为 **−1.0**。
所有 3 个 new 样本都小于所有 3 个 old 样本，new 组的 Mann–Whitney
`U=0`，单侧精确 `p=0.05`（20 种 3+3 分组），达到 `p≤0.05` 的预注册门禁。
六次 Make/emu exit 均为 0/0，六次都到达 `instrCnt=240349`、`cycleCnt=99996`、
guest `100001`、PC `0x80000c0c`，无 difftest mismatch；emu wall 对应为
old **126.09/126.54/126.53 s**、new **123.03/123.10/122.05 s**。

本节点保留的机制是 IR 层的代数恒等式、常量条件 mux、同值分支和可交换纯计算
CSE，以及已有赋值/状态共享的拓扑重跑。emitter 的字面量改写已撤回，不能把
早期失败的字面量版本收益混入本结论。正式结果满足正确性、1800 s 生成/编译
门限、190.464 s 仿真止损和统计门禁；节点判定为 `ACCEPTED`。
