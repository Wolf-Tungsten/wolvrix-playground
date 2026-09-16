# NO00037：标量 mux 无分支发射

日期：2026-09-16。当前阶段：`ACCEPTED`。

本节点承接 NO00036 的 GrhSIM-IR CoreMark 100k 最佳构建，围绕“减少 compute
表达式控制流成本”推进一个可验证方向。冻结 GRH、GRH pass、XiangShan 和测试
源码均不修改；机制只由结果类型、两态语义和操作类型触发，不按模块名匹配。

## IDEA

NO00036 的动态覆盖显示 mux 占静态 compute op 的 14.90%，compute 每次 eval
约执行 574,637 个 op，boundary 写回虽然大多不变，但每个 mux 仍需计算选择。
CPU emitter 过去对 ≤64 位 mux 生成 `cond ? true : false`。当选择值动态变化时，
该形式会暴露数据相关控制流；运行时已有 `grhsim_mux_u64`，可用 `cond != 0`
生成全位掩码并按位合并两个已归一化分支，保持 SystemVerilog 的“任意非零
条件选择真支路”语义。候选仅覆盖两态标量结果，宽值和其他类型继续旧路径。

局部目标是降低 compute 热路径中的 mux 分支与错误预测，预期收益为百分之一量级；
若 checkpoint 筛选无正向或出现等价性问题，则否定该假设。正式接受仍要求完整
SV→C++ 生成、fresh 编译、100k 对拍和 6 次新旧交替统计。

## BASELINE 与预注册口径

对照为 NO00036 的 `flow-c-final`，正式 new 预期 Host 均值 **100.320333 s**，
仿真截止值为 **150.480500 s**（1.5 倍）。机器、CoreMark 输入、CPU2、单线程、
100000 cycles、NEMU 对拍、waveform/commit/RAM trace 配置均保持 NO00036；gsim
归档 46.965 s 仅作差距参照。正式顺序固定为 `old1/new1/old2/new2/old3/new3`，
要求全部有效样本满足 `max(new) < min(old)`。

checkpoint 筛选从 NO00036 的完整 GrhSIM JSON 重发射，筛选输出和所有临时文件
位于 `ptmp/no00037_mux_mask_20260916/`；筛选结果不计入正式统计。聚焦回归使用
Makefile 目标 `test_grhsim_cpu_emit`、`test_grhsim_cpu_mapping` 和
`test_grhsim_cpu_schedule`。

## IMPLEMENTED

实现只修改 `wolvrix/lib/grhsim/backend/cpu_emit.cpp` 的标量表达式发射：结果为
两态、宽度不超过 64 位且操作为三输入 mux 时生成
`grhsim_mux_u64(cond,trueValue,falseValue)`，其他 mux 仍生成原有条件表达式。
该 runtime helper 用 `cond != 0` 形成全位掩码，再合并两个已经按结果宽度转换的
分支；`normalize()` 继续执行最终截断或符号扩展，因此不改变 IR、依赖、边界写回、
fanout 或调度。新增 emitter 断言检查 scalar fixture 确实采用该 helper。

聚焦验证通过：

```text
make test_grhsim_cpu_emit test_grhsim_cpu_mapping test_grhsim_cpu_schedule
```

三项目标均 exit 0；emitter 测试包含 Verilator 差分、ASan/UBSan fixture 和
`grhsim_mux_u64` 生成断言。

## VALIDATED

checkpoint 筛选从 NO00036 完整 JSON 重发射，old/new Host 为 **101.469 / 94.970 s**，
候选快 6.404912%，终点与 NEMU 对拍通过；该单对只用于筛选。完整 SV→C++ 生成使用
全新 `flow-final`，`generation.time` 为 **698.35 s**、exit 0，GrhSIM checkpoint
store/load/store round-trip 字节一致；fresh emu 编译 `compile.time` 为 **212.93 s**、
exit 0。两项均低于 1800 s。完整模型 JSON SHA256 与 NO00036 相同
（`007b62cd2b895d11ae83a06028922a97400b5fb50e4612419dfcedce6b28fc15`），说明本节点
只改变通用 emitter 行为；new emu SHA256 为
`c4384394a3262269234e38c7e5a3590a79300404ed53f084e576106186aa2a61c`，old 为
`d96d774ac12deace188cdf14511a00b2be929f88fa670019695d8c6b4bbbaba2`。

正式窗口固定为 `old1/new1/old2/new2/old3/new3`，CPU2、`XS_NUM_CORES=1`、
`XS_EMU_THREADS=1`、100000 cycles，waveform/commit/RAM trace 关闭。六次均 Make/emu
exit 0、NEMU 无 mismatch，终点均为 `instrCnt=240349`、`cycleCnt=99996`、guest
cycles `100001`、IPC `2.403586`、末端 PC `0x80000c0c`。

| 运行 | Host (s) | emu 墙钟 (s) | 状态 |
|---|---:|---:|---|
| old1 | 99.404 | 99.43 | VALID / NEMU PASS |
| new1 | 93.645 | 93.67 | VALID / NEMU PASS |
| old2 | 99.395 | 99.42 | VALID / NEMU PASS |
| new2 | 93.734 | 93.76 | VALID / NEMU PASS |
| old3 | 100.786 | 100.81 | VALID / NEMU PASS |
| new3 | 92.460 | 92.49 | VALID / NEMU PASS |

old Host 均值 **99.861667 s**、样本 SD **0.800509 s**；new 均值 **93.279667 s**、
样本 SD **0.711246 s**。均值减少 **6.582000 s**，相对降低
`100*(1-new/old)` 为 **6.591118%**。组内 CV 为 0.8019% / 0.7625%；Cohen d
（new−old）**−8.692624**，Cliff delta **−1.0**，Mann–Whitney `U(new)=0`，
单侧精确 `p=0.05`。`max(new)=93.734 < min(old)=99.395`，满足 3+3 全秩分离门槛。

## ACCEPTED：结论与根因收敛

NO00036 的动态覆盖指出 mux 占 14.90% 静态 compute op；本节点把这一高覆盖的
控制流表达统一转换为无分支掩码选择。静态反汇编统计（只统计 compute/commit/evaluator
阶段，不能替代硬件计数器）为：compute 指令 **15,104,406→14,808,189**，减少
**296,217（1.960%）**；compute 条件跳转 **368,186→208,012**，减少
**160,174（43.506%）**；ELF text **103,441,484→101,908,332 bytes**，减少
**1,533,152（1.482%）**；task 数、IR JSON、commit 指令均不变。代码体积和条件跳转
同步下降与 6.591118% 的交替收益方向一致，支持“高频标量 mux 的分支控制流是
GrhSIM-IR compute 残余成本之一”的根因判断。它仍只解释局部差距：相对 gsim
46.965 s，new 均值为 **1.985×**，仍高 **46.315 s（98.615%）**。

节点最终保留 emitter 特化及其测试；没有生成代码、日志、profile、波形或二进制被
提交。A/B 失败尝试不适用，本节点一次实现即通过真实性能门槛。

## 复现命令

完整实验产物在 `ptmp/no00037_mux_mask_20260916/`。从根仓库执行：

```bash
source env.sh
node_dir="$PWD/ptmp/no00037_mux_mask_20260916"
flow="$node_dir/flow-final"
export TMPDIR="$node_dir/work-tmp" PIP_CACHE_DIR="$node_dir/pip-cache" \
  CCACHE_DIR="$node_dir/ccache" CCACHE_DISABLE=1 \
  PATH="$PWD/.venv/bin:/home/gaoruihao/wksp:$PATH" \
  WOLF_ENV_SOURCED=1 CMAKE_BUILD_PARALLEL_LEVEL=32 PYTHONDONTWRITEBYTECODE=1

timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir \
  PYTHON="$PWD/.venv/bin/python" XS_NUM_CORES=1 XS_RTL_BUILD=build/xs/rtl \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS=1 \
  XS_LOG_DIR="$flow/logs" RUN_ID=no00037_mux_mask_generate

timeout --signal=KILL 1800s make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  PYTHON="$PWD/.venv/bin/python" XS_GRHSIM_IR_BUILD="$flow" \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR="$flow/model" \
  XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src XS_NUM_CORES=1 \
  XS_EMU_THREADS=1 EMU_THREADS=1 VM_BUILD_JOBS=32 XS_LOG_DIR="$flow/logs" \
  RUN_ID=no00037_mux_mask_compile

make --no-print-directory benchmark_grhsim_ir PYTHON="$PWD/.venv/bin/python" \
  GRHSIM_IR_BENCH_OLD="$PWD/ptmp/no00036_dynamic_coverage_20260916/flow-c-final" \
  GRHSIM_IR_BENCH_NEW="$flow" GRHSIM_IR_BENCH_OUTPUT="$node_dir/formal" \
  GRHSIM_IR_BENCH_CPU=2 GRHSIM_IR_BENCH_PAIRS=3 \
  GRHSIM_IR_BENCH_BASELINE_SECONDS=100.320333
```
