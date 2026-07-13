# NO0395 Direct scalar-locality runtime-profile plan

日期：2026-07-12

## 1. Objective

[NO0394](./NO0394_scalar_read_locality_baseline_fire_proxy_gate_20260712.md) 的 baseline-fire proxy 给出 `32.821%`
source-load saved 上界，但 direct state-read 已改变 activation frontier，必须采集 direct model 自身的 50k fire 才能
决定是否继续。此阶段只增加 runtime counters，不实现 typed local cache。

## 2. Fresh emit/build

从 NO0300/NO0392 相同 pre-reg-to-mem checkpoint fresh emit：

```text
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
GRHSIM_EMIT_RUNTIME_PROFILE=1
WOLVRIX_GRHSIM_STORAGE_REF_ALIASES=0
```

108-op compute、4096-op commit、64 batch target、4 路 emit、ordered/decoded write 和 `level-id` 保持不变。scalar
locality TSV 不需要重复生成；分析继续使用 NO0392 已验证且与 direct production code byte-identical 的 static TSV。

独立输出：

```text
build/xs_grhsim_no0395_direct_rtprof_20260712/grhsim
```

emit gate 要求 schedule stats SHA 仍为 `e3056375...`、direct reads 仍为 `75,830`、header
`kRuntimeProfileCompiled=true`、`grhsim_supernode_static.tsv` 恰有 63,726 data rows。随后用标准 XiangShan difftest
Clang/O3 flow 构建 emu；最终 binary 必须包含 `EMU_RUNTIME_PROFILE` 和 `GRHSIM_RUNTIME_PROFILE` strings。

## 3. Functional/runtime gate

先做 100-cycle smoke，再以 CoreMark 两迭代镜像、NEMU difftest 跑 50k：

```text
EMU_RUNTIME_PROFILE=1
WOLVRIX_GRHSIM_SUPERNODE_TSV=<NO0397 direct fire path>
-b 0 -e 0 -C 50000
```

50k 必须到达 guest/model cycles `50001/50000`、`cycleCnt=49996`、`instrCnt=73580`、PC `0x80001312`，无
mismatch/assert/abort/error/`input_fullpass_blocked`。fire TSV 必须与 63,726 static keys 严格一一匹配。

这是动态诊断，不使用插桩 binary 的 host time 判断性能。运行前仍记录 load average；机器繁忙只影响完成时间，不改变
确定性的 fire counts，因此不要求 fixed-ASLR A/B/A 或 PMU quiet gate。

## 4. Analysis gate

用 direct fire 替换 NO0394 脚本的 proxy 输入，重新计算全模型、threshold、compute1/62 和 top candidates，并直接
报告 direct vs baseline proxy fire/saved 差异。若 direct weighted saved/all scalar touches 低于 `10%`，停止本方向；
否则对 direct-fire top candidate functions 做 O3 disassembly，确认同一 slot 是否仍发生重复 memory loads，再决定是否
实现默认关闭的 typed local cache。

本篇只声明计划，尚未 fresh emit/build 或运行仿真。
