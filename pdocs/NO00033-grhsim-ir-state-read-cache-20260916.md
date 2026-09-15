# NO00033：计算 helper 的状态读取缓存

日期：2026-09-16。节点阶段：`ACCEPTED`。

本节点在 NO00032 的 packed-bit-register 构建上继续优化。诊断 profile 显示
compute 占 eval 时间约 78.65%，而生成的 helper 对同一个状态的多个切片会反复
从 `cpu_objects` 加载。新机制在 CPU emitter 的每个 compute helper 中，按语义
追踪 `core.state.read` 及透明的 `sliceStatic`、`sliceDynamic`、`sliceArray`、
`assign` 来源；同一 helper 内重复使用的 two-state 标量状态只加载一次到局部
`const auto`。compute 阶段位于 commit 之前，状态对象在该 helper 调用期间不会被
修改，因此缓存保留提交前快照语义；宽值、数组、四态和复合表达式不缓存。

基线为根仓库 `8ed26ec589459f8d34ed6c6ffe6abb6797616310`、wolvrix 子模块
`2b320c91a37963cd2c8bd0a40c7330a6b1e2685c`（NO00032 实现）；节点开始时两仓库
均干净，最终子模块变更只涉及本报告所述 emitter 文件。

## BASELINE 与预注册

对照使用已接受的 NO00032 `flow-pack-final`，其三次 new 均值为 109.970333 s。
本节点运行固定 CPU2、单核、`XS_EMU_THREADS=1`、100000 cycles、CoreMark 两次
迭代、NEMU 对拍，waveform/commit/RAM trace/profile 关闭。仿真截止预先选择
`1.5 × 109.970333 = 164.9554995 s`，达到即杀死进程树并否定当次实验。

正式顺序预注册为 `old1/new1/old2/new2/old3/new3`，主指标为 emu Host time，
要求 `max(new) < min(old)`；统计报告均值、样本 SD、Cohen d、Cliff delta、
Mann–Whitney U 及精确单侧 p。完整 SV→C++ 生成和 fresh C++ 编译均在启动前安装
`timeout --signal=KILL 1800s`，失败或 endpoint/difftest 不一致的样本作废并补跑。

## 实现与聚焦验证

改动文件为 `wolvrix/lib/grhsim/backend/cpu_emit.cpp`。构造 emitter 时记录每个
value 的 producer；`stateReadSource` 只沿上述透明 op 递归，避免把一般表达式或
可变来源误判为状态别名。`computeGroup` 统计 helper 内来源次数，满足次数大于
1 且为 64 位以内 two-state logic 才声明缓存，并在生成完成后清除 emitter 上下文。
没有新增 runtime helper ABI，也没有修改冻结 GRH、现有 GRH pass、XiangShan 或
CoreMark 源码。

聚焦回归已通过：

```text
make test_grhsim_cpu_emit PYTHON=.venv/bin/python SKIP_PY_INSTALL=1
1/1 Test #8: grhsim-cpu-emit-tests ... Passed (95.59 s)
```

从 NO00032 IR checkpoint 重发射的筛选构建 `flow-cache-state` 生成 30.04 s，
fresh emu 编译 219.22 s，均 exit 0。独立一对筛选（不计入正式六次）为 old
109.885 s、new 108.410 s，new 快 1.342312%；两次均到达预期终点
`instrCnt=240349, cycleCnt=99996, guest=100001, PC=0x80000c0c`，NEMU 无
mismatch。该 n=1+1 结果只作为进入正式验证的依据。

复现实验使用以下环境和 Makefile 命令：

```bash
node_dir="$PWD/ptmp/no00033_batch_probe"
flow="$node_dir/flow-cache-final"
old="$PWD/ptmp/no00032_state-read-views_20260915/flow-pack-final"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache"
export PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH"
export WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/generation.time" make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00033_cache_generate

timeout --signal=KILL 1800s /usr/bin/time -f 'wall=%e exit=%x' \
  -o "$flow/compile.time" make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00033_cache_compile

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$old" GRHSIM_IR_BENCH_NEW="$flow" \
  GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal-cache" GRHSIM_IR_BENCH_CPU=2 \
  GRHSIM_IR_BENCH_PAIRS=3 GRHSIM_IR_BENCH_BASELINE_SECONDS=109.970333
```

## VALIDATED / ACCEPTED

全新目录完整 SV→C++ 生成耗时 **680.49 s**（exit 0），fresh C++ 编译耗时
**215.26 s**（exit 0），均低于 1800 s。生成使用 `XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`
和 packed-bit-registers，其 IR round-trip 字节稳定；生成后的 emu SHA256 为
`229ce08989b587cfa7104cbc57d8c65b9317ae04fbcc9767245d6a7b850fcb28`，对照 emu
SHA256 为 `5848c381f680088609a2c62deb28790ce54790684ca88dd2e60161efdb2d8652`。
输入 CoreMark 与 NEMU SHA256 分别为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` 和
`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

六次正式运行严格按预注册顺序交错，均 exit 0、Difftest 无 mismatch，且得到同一
endpoint：`instrCnt=240349`、`cycleCnt=99996`、guest cycles `100001`、PC
`0x80000c0c`。Host 秒数如下：

| old1 | new1 | old2 | new2 | old3 | new3 |
|---:|---:|---:|---:|---:|---:|
| 110.397 | 108.032 | 111.023 | 107.969 | 110.543 | 108.233 |

old 均值 **110.654333 s**、样本 SD **0.327514 s**；new 均值 **108.078000 s**、
样本 SD **0.137880 s**，降低 **2.328272%**。Cohen d(new−old) **−10.253121**，
Cliff delta **−1.0**，Mann–Whitney `U_new=0`，精确单侧 `p=0.05`；
`max(new)=108.233 < min(old)=110.397`，通过真实性能门槛。每次仿真使用
`timeout --signal=KILL 164.955500s`，没有触发截止。

静态反汇编（`make analyze_grhsim_cpu_code ... GRHSIM_CPU_CODE_PHASE_ONLY=1`）显示
compute phase 指令从 15,202,092 降至 14,795,401（−2.67%），条件跳转从
670,261 降至 530,277（−20.89%），ELF text 从 105,403,692 降至 102,912,740
字节（−2.36%）；commit phase 不变。生成代码中共有 78,409 个不同缓存状态名、
392,169 个缓存引用（同一状态可在多个 helper 中独立缓存），与 compute 侧静态
收缩和实测收益一致。该统计是静态证据，正式结论以六次交错 Host 测量为准。

聚焦回归 `test_grhsim_cpu_emit`、`test_grhsim_cpu_mapping`、
`test_grhsim_cpu_schedule` 以及 HDLBits DUT 086、097 均通过。实现只修改
`wolvrix/lib/grhsim/backend/cpu_emit.cpp`，没有新增 runtime helper ABI，也没有
修改冻结 GRH、现有 GRH pass、XiangShan 或 benchmark 源码。节点最终判定：
**ACCEPTED**。保留实现待在节点收尾时与本报告、索引一起集中提交。

子模块实现提交为 `c652264`（`feat: cache repeated state reads in grhsim cpu emit`）。
