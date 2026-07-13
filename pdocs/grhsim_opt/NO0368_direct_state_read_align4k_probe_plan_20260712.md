# NO0368 Direct state-read 4 KiB alignment probe plan

日期：2026-07-12

## 1. 依据与目的

[NO0367](./NO0367_direct_state_read_full_empty_profile_gate_20260712.md) 证明 direct state-read 的 cmask6
full-empty 回退是广泛、compute-dominated 的：总样本增加 `12.949%`，compute 占增量 `86.749%`，top-10
functions 只覆盖 `33.745%`，代表函数 annotate 也没有单 IP 热点。

同一轮还发现 direct fresh emission 同时改变 110 个 batch 函数体，并因 text 缩小使 116/117 个 batch 入口及
低 12-bit offset 漂移。当前无法区分：

1. 超大 batch 的 native entry/page/predictor layout 变化；
2. direct frontier 改变动态 activation、fixed-point rounds 或函数访问序列。

[NO0329](./NO0329_batch_function_page_alignment_plan_20260712.md) 至
[NO0333](./NO0333_batch_function_page_alignment_runtime_gate_20260712.md) 已构建并验证 NO0300 的 4 KiB aligned
binary，且逐项证明 alignment 不改变 117 个 symbol body sizes。NO0333 的 runtime 因未固定 PIE 基址而被后续勘误为
provisional；本轮用 `setarch -R` 修正该缺口，先完成更便宜的 entry-layout 因果探针。

## 2. 构建变量

复用以下 generated C++，不重新 transform、partition、schedule 或 emit：

```text
baseline aligned source/binary:
  build/xs_grhsim_no0329_no0300_align4k_20260712/grhsim/grhsim_emit
  build/xs_grhsim_no0329_no0300_align4k_20260712/grhsim/grhsim-compile/emu

direct source:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit

direct aligned output:
  build/xs_grhsim_no0368_direct_align4k_20260712/grhsim
```

direct 副本使用与 NO0331 完全相同的工具和 flags：

```text
CXX=clang++ AR=ar ARFLAGS=rv
CXXFLAGS=-std=c++20 -O3 -falign-functions=4096
```

使用 16 个 model build slots；构建前记录全机 load 和可用内存。generated source 用 hardlink copy，随后只在副本中
删除旧 `.o/.a/.pch` 并完整重编，原 NO0357 目录和 emu 不得修改。difftest 使用独立 `BUILD_DIR`。

## 3. build/layout 门禁

1. direct 副本的全部 `.cpp/.hpp/Makefile` 与 NO0357 source manifest、内容 SHA256 完全一致；
2. 117 个 sched objects 均由 Clang 21 生成，主 `.text` section alignment 为 4096；
3. 最终 direct aligned emu 精确包含 117 个 `eval_{compute,commit}_batch_*` symbols，入口都满足
   `address % 4096 == 0`；
4. direct aligned 与 unaligned 的 117 个 symbol sizes 逐项相同，证明函数 body/内部指令规模未被编译器改变；
5. archive、emu 成功链接，记录 SHA256、`.text` 与 padding 增量。

若任何一项失败，不进入仿真。

## 4. 功能门禁

先对 direct aligned 串行运行 CoreMark/NEMU difftest：

1. 10k：guest cycles `10001`、`cycleCnt=9996`、`instrCnt=458`、PC `0x800027c6`；
2. 50k：guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、PC `0x80001312`；
3. 与 NO0360/NO0361 checkpoints 一致，且无 mismatch/assert/abort/fatal/error/`input_fullpass_blocked`。

NO0300 aligned 已由 NO0332 通过相同 10k/50k 功能门禁，不重复无信息量的功能长跑；正式性能 A/B/A 仍会再次验证
三轮 50k 终点。

## 5. fixed-ASLR runtime 门禁

固定 CPU138、NUMA1、`setarch -R`，串行执行：

```text
aligned NO0300 / aligned direct / aligned NO0300
```

CoreMark 50k 参数、seed、NEMU difftest、progress 和五项 PMU 与 NO0365 完全一致：host cycles、instructions、
frontend empty、cmask6 full-empty、backend stalls。每轮前检查全机 load 以及 CPU138/330 三秒空闲度；两者均达到
99% 才启动。若全机负载显著升高，则等待，并补跑原始 aligned baseline 夹测，避免跨时段失真。

有效性要求：

- 三轮功能终点一致，无 `input_fullpass_blocked`；
- 五项 PMU 全部 `100.00%` 调度；
- 两次 aligned baseline host cycles spread `<=1%`；
- 固定 PIE state/text mapping 可重复。

主比较是 aligned direct 相对 aligned NO0300 mean，并与 NO0365 未对齐的 cycles `+6.263%`、instructions
`-3.466%`、cmask6 density `+5.839%` 对照：

- 若 instructions 收益保持、cycles/cmask6 回退明显收敛，说明累计函数入口布局是主要混淆因素；
- 若回退基本保持，则 entry/page drift 不是主因，下一步 fresh 构建 runtime-profile direct，直接统计 fire、eval rounds
  和 activation work；
- 4 KiB alignment 是诊断变量，不因单次收益直接进入默认实现。

## 6. 预定产物

```text
build/xs_grhsim_no0368_direct_align4k_20260712/grhsim/
build/logs/xs_perf/no0368/direct_align4k_model_build.log
build/logs/xs_perf/no0368/direct_align4k_emu_link.log
build/logs/xs_perf/no0368/direct_align4k_layout.tsv
build/logs/xs_perf/no0368/direct_align4k_functional_{10k,50k}.log
build/logs/xs_perf/no0368/fixed_align4k_{baseline1,direct,baseline2}_{emu.log,perf.csv}
```
