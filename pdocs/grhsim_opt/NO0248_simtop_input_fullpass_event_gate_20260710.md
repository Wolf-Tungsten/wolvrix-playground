# SimTop input full-pass event gate correctness regression

## 背景

用户要求先确认当前 `input+posedge full-pass` 优化的功能正确性，再回归 XiangShan `SimTop` 仿真并继续主线分析。此前 `NO0241-NO0247` 主要在 `xs-components` 小负载上验证，尤其是 `XsReal075RobVtypebufferLarge`；本轮把同一优化组合放回完整 `SimTop`，结果发现原优化版并不满足 `SimTop` 功能正确性。

本轮所有构建/运行命令均先执行：

```bash
source env.sh
```

## 初始 SimTop 回归：原优化版 10k 功能失败

构建口径：

```bash
RUN_ID=no0248_simtop_grhsim_best_func_20260710
WORK_BASE=build/xs_grhsim_regress_20260710
POST_STATS=$PWD/build/xs_grhsim_perf/grhsim/wolvrix_xs_post_stats.json
GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1 \
GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION=1 \
make xs_wolf_grhsim_emu \
  RUN_ID=$RUN_ID \
  XS_WORK_BASE=$WORK_BASE \
  XS_WOLF_GRHSIM_POST_STATS_JSON="$POST_STATS" \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=1 \
  XS_WOLF_GRHSIM_ENABLE_STATS=0 \
  WOLVRIX_GRHSIM_WAVEFORM=0 \
  WOLVRIX_GRHSIM_PERF=0
```

构建成功，日志：

- `build/logs/xs/no0248_simtop_grhsim_best_func_20260710_make_xs_wolf_grhsim_emu.log`

随后运行 `2k` smoke 能到 cycle limit，但只提交 `3` 条指令，覆盖不足。继续运行 `10k`：

- wrapper log: `build/logs/xs/no0248_simtop_grhsim_best_func_10k_20260710_run_xs_wolf_grhsim_emu.log`
- emu log: `build/logs/xs/xs_wolf_grhsim_no0248_simtop_grhsim_best_func_10k_20260710.log`

关键失败信息：

```text
cacheid=0,mask=ff,realpaddr=0x80001d00: Refill test failed!
cacheid=0,mask=ff,realpaddr=0x80001d40: Refill test failed!
cacheid=0,mask=ff,realpaddr=0x80001d80: Refill test failed!
cacheid=0,mask=ff,realpaddr=0x80001dc0: Refill test failed!
cacheid=0,mask=ff,realpaddr=0x80001e00: Refill test failed!
Core 0: ABORT at pc = 0x0
Core-0 instrCnt = 38, cycleCnt = 8354, IPC = 0.004549
Host time spent: 89826ms
```

结论：`NO0246` 记录的当前 best 小负载优化在完整 `SimTop` 上不正确，不能视为可启用实现。

## 定位：关闭 input fullpass 后 10k 通过

为了区分是整体 emitter 改动还是 fastpath 本身的问题，本轮对生成物做一次临时 patch，把 `input_fullpass_candidate && !input_fullpass_blocked` 强制改成 false，仅关闭 input fullpass fastpath。重新编译后运行 `10k`：

- build log: `build/logs/xs/no0248_simtop_fastpathoff_rebuild_20260710.log`
- wrapper log: `build/logs/xs/no0248_simtop_grhsim_fastpathoff_func_10k_20260710_run_xs_wolf_grhsim_emu.log`
- emu log: `build/logs/xs/xs_wolf_grhsim_no0248_simtop_grhsim_fastpathoff_func_10k_20260710.log`

结果：

```text
[CYCLE_LIMIT] cycles=10000 max_cycles=10000
Core-0 instrCnt = 458, cycleCnt = 9996, IPC = 0.045818
Host time spent: 19422ms
```

无 `Refill test failed` / `ABORT` / `MISMATCH`。因此功能错误定位到 input fullpass fastpath，而不是普通 GrhSIM 主路径。

## 根因：SimTop 存在 input event negedge commit

检查生成的 `SimTop` 调度代码，发现至少存在 clock negedge guard 下的 commit：

```text
build/xs_grhsim_regress_20260710/grhsim/grhsim_emit/grhsim_SimTop_sched_71.cpp:37198:
    if (event_edge_slots_[0] == grhsim_event_edge_kind::negedge) {
```

这一路会更新如 `cpu$l_simMMIO$sd$DifftestSDCard$helper$io_data_1` 之类的状态/commit 输出。原 input fullpass 的 gate 只保守阻断 reset / clock posedge 等情形，clock negedge 上仍可能把输入变化误判为普通 data-input settle，然后直接执行 compute-only fullpass，跳过本应发生的 event commit。完整 `SimTop` 的 refill 数据因此被破坏，最终触发 refill fail 与 abort。

这也解释了为什么 `VtypeBuffer` 小负载未暴露该 bug：该 case 的 input-low 数据 settle 不是下降沿顺序工作；其下降沿本身几乎无实质状态 commit。完整 `SimTop` 则确实存在 negedge event commit。

## 修复策略

本轮在 `wolvrix/lib/emit/grhsim_cpp.cpp` 中修复 `input_fullpass_specialization` 的 gate：

1. `commitInputValues` 中的非 event input 变化仍阻断 input fullpass，因为这类 input 会直接触发 commit 语义。
2. 对 event input，不再一刀切按“任意边沿”阻断，而是扫描 `model.commitSupernodeIds` 里的 commit op 及其 `EventSampleDecl`：
   - 若 commit sample 是 direct input event 且 edge 为 `posedge`，只在该 input 的 posedge 阻断 input fullpass。
   - 若 edge 为 `negedge`，只在 negedge 阻断。
   - 若 edge 未知/anyedge，则在非 none 边沿阻断。
   - 若 commit op 缺失 event sample，或 sample 不是 direct input event，则保守地完全阻断 input fullpass。
3. 对重复条件排序去重，避免生成重复 gate。

第一版过宽修复曾简单地在任意 input event edge 上阻断 input fullpass。它能修复 `SimTop`，但会明显伤害小负载性能：`VtypeBuffer` 200k GrhSIM 从 best 附近退回到 `418.834ms`。因此最终采用上述 edge-specific / fallback-conservative gate。

## 生成物检查

最终 `SimTop` 生成物中，由于存在更复杂或缺少 sample 的 commit event，仍触发了 fallback-conservative gate：

```cpp
input_fullpass_blocked = true;
if (!initial_eval && (
    classify(clock) == negedge ||
    classify(clock) == posedge ||
    classify(reset) == posedge)) {
    input_fullpass_blocked = true;
}
```

即：对当前完整 `SimTop`，input fullpass 实际保守关闭，以保证功能。

而 `XsReal075RobVtypebufferLarge` 的最终生成物只在 `clock` posedge 阻断 input fullpass，未阻断 negedge：

```cpp
if (!initial_eval && (classify(clock) == grhsim_event_edge_kind::posedge)) {
    input_fullpass_blocked = true;
}
const bool posedge_fullpass_candidate = !initial_eval &&
    (event_edge_slots_[0] == grhsim_event_edge_kind::posedge) && ...;
```

这说明修复没有把小负载的 input-low fastpath 一并打掉。

## 回归结果

### Wolvrix build / CTest

构建：

- `build/logs/xs/no0248_wolvrix_build_precise_event_gate_20260710.log`
- status 0

Python editable install：

- `build/logs/xs/no0248_py_install_precise_event_gate_20260710.log`
- status 0

CTest：

- `build/logs/xs/no0248_wolvrix_ctest_precise_event_gate_20260710.log`

结果：

```text
96% tests passed, 2 tests failed out of 48
The following tests FAILED:
  21 - transform-comb-lane-pack (Failed)
  29 - transform-repcut (Failed)
```

关键的 `emit-grhsim-cpp` 通过：

```text
11/48 Test #11: emit-grhsim-cpp ... Passed
```

上述两项 transform failure 在本轮 emitter 修复前已复现，暂按既有非本轮引入问题记录。

### VtypeBuffer precise gate

命令口径：

```bash
make -C testcase/xs-components \
  CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0248_precise_event_gate_vtype_20260710 \
  GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1 \
  GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION=1 \
  BENCH_VECTORS=200000 \
  BENCH_VERIFY=200000 \
  BENCH_REPEAT=1 \
  bench
```

日志：

- `build/logs/xs/no0248_vtype_precise_event_gate_20260710.log`

结果：

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=200000 status=pass
[BENCH] model=gsim   ... ms=212.506 checksum=0x7d62abe96844fe00
[BENCH] model=grhsim ... ms=324.891 checksum=0x7d62abe96844fe00
```

对照过宽 gate：

```text
broad event gate:   GrhSIM 418.834ms
precise event gate: GrhSIM 324.891ms
```

说明最终 gate 保住了 `VtypeBuffer` 的 input-low fastpath 收益。

### SimTop precise gate 50k

重新从修复后的 emitter 生成并构建完整 `SimTop`：

- `build/logs/xs/no0248_simtop_grhsim_precise_event_gate_build_20260710_make_xs_wolf_grhsim_emu.log`
- status 0

运行 `50k`：

- wrapper log: `build/logs/xs/no0248_simtop_grhsim_precise_event_gate_func_50k_20260710_run_xs_wolf_grhsim_emu.log`
- emu log: `build/logs/xs/xs_wolf_grhsim_no0248_simtop_grhsim_precise_event_gate_func_50k_20260710.log`

结果：

```text
[EMU_PROGRESS] host_cycles=50000 model_cycles=50000 instr=73580 ... host_ms=135406
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
Host time spent: 135410ms
```

日志扫描未见：

- `Refill test failed`
- `ABORT`
- `MISMATCH`

机器负载记录：运行结束时 load average 约 `54.31, 57.40, 54.33 / 384`。本轮 `SimTop` 侧关注功能正确性，不把 host time 作为新的性能 baseline。

## 结论

1. 原 `input+posedge full-pass` best 小负载优化并非完整 `SimTop` 功能正确：`10k` 会因 refill fail abort。
2. 根因是 input fullpass gate 没有覆盖完整 `SimTop` 中真实存在的 input event negedge commit，导致 negedge 上跳过必要 commit。
3. 最终修复改为按 commit event sample 精确阻断；未知/非 direct input event commit 则保守 fallback。
4. 修复后：
   - `VtypeBuffer` 200k verify 通过，并保持接近 `NO0246` 的 fastpath 性能区间。
   - 完整 `SimTop` GrhSIM `50k` 功能回归通过，没有 refill fail / abort / mismatch。
5. 对当前完整 `SimTop`，生成物仍因复杂 commit sample 保守关闭 input fullpass；因此该修复主要是“安全性修正”，并不表示 SimTop 已获得 input fullpass 性能收益。

## 下一步

继续主线性能分析时需要注意：

- `input_fullpass_specialization` 与 `posedge_fullpass_specialization` 仍应默认关闭，作为实验开关使用。
- 小负载上可以继续利用 precise gate 分析 remaining gap；当前 `VtypeBuffer` 仍约 `1.5x` 慢于 GSIM。
- 完整 `SimTop` 若要获得类似收益，需要继续识别 fallback-conservative 的来源：哪些 commit op 缺少可直接归因到 input event 的 sample，是否能把这些 event sample 规范化/补全。
- `NO0247` 的 high-phase subset / value-level 裁剪仍是小负载 remaining gap 的主线；SimTop 侧则先把 fullpass 功能安全边界守住。
