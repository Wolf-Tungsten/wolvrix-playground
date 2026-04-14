# GrhSIM CoreMark Debug

## 2026-04-14 Signed Wide Compare Root Cause

### Confirmed Root Cause

- `fpFreeList` 上最早暴露出来的坏值不是 `kShl` 自己算错。
- 真正的根因在 GrhSIM 宽位有符号比较 helper：
  - `grhsim_compare_signed_words`
  - generator 源码：`wolvrix/lib/emit/grhsim_cpp.cpp`
  - 当时 emitted runtime：`build/xs/grhsim/grhsim_emit/grhsim_SimTop_runtime.hpp`
- 旧实现对“同号且都为负数”的情况错误地把无符号比较结果整体取反，导致顺序颠倒。

### Concrete Failing Example

- 在 `fpFreeList` 路径中：
  - `diff = 802`
  - 这是 10-bit 有符号数 `-222`
  - 比较对象是 `value_words_4_slots_[3911] = -1`
- 正确语义应当是：
  - `-222 > -1` 为假
- 但旧实现错误返回了正值，于是：
  - `neg = 1`
  - 选择了 `slice_pos = 34`
  - 后续 `shift = 34`
  - `grhsim_shl_words(..., 34, 256)` 产生了错误的 `bit34`

### Runtime Instrumentation Evidence

- 修复前，同一条路径的运行时插桩显示：
  - `diff=802 cat=0 slice_pos=34 neg=1 shift=34 hot=34`
- 修复 `grhsim_compare_signed_words` 后，同一路径变为：
  - `diff=802 cat=0 slice_pos=34 neg=0 shift=0 hot=0`
- 说明：
  - `kShl` 只是消费了错误的 shift
  - 首个确定的 functional bug 实际发生在宽位有符号比较阶段

### Fix

- 修复后的策略是：
  - 若符号不同，直接按符号决定大小
  - 若符号相同，无论正负，直接返回宽位无符号逐字比较结果
- 这与补码比较在“同宽同号”条件下的词典序是一致的。

### Superseded Earlier Hypothesis

- 先前文档里“更可能是 stale / transient / ordering 问题”的判断，现在应视为过时。
- 至少对于 `fpFreeList` 这条最先定位到的错误路径，已经有更直接、可复现、并且经运行时插桩证实的根因：
  - `grhsim_compare_signed_words` 实现错误

## 2026-04-14 Baseline

### Build

- Rebuilt XiangShan GrhSIM emu from the latest emitted C++ model.
- Final executable:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim-compile/emu`
- Symlink entry:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/emu`
- GrhSIM model directory:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim_emit`
- Build flags confirmed in generated model Makefile invocation:
  - `clang++ -std=c++20 -O3 -I. -c ...`

### Run

- Command:

```bash
cd /workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim && \
stdbuf -oL -eL ./emu \
  -i /workspace/gaoruihao-dev-gpu/wolvrix-playground/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff /workspace/gaoruihao-dev-gpu/wolvrix-playground/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0
```

- Log:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/logs/xs/xs_wolf_grhsim_20260414_105250.log`

### Exact Failure Output

```text
The first instruction of core 0 has commited. Difftest enabled.
Assertion failed at build/xs/rtl/rtl/MEFreeList.sv:2026.
Assertion failed at build/xs/rtl/rtl/StdFreeList_1.sv:652.
Assertion failed at build/xs/rtl/rtl/StdFreeList.sv:1381.
The simulation stopped. There might be some assertion failed.
Core 0: ABORT at pc = 0x0
Core-0 instrCnt = 2, cycleCnt = 662, IPC = 0.003021
Seed=0 Guest cycle spent: 666 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 82641ms
```

### Current Conclusion

- The current GrhSIM C++ emit and emu build complete successfully.
- CoreMark still fails at the same early free-list-related assertion site after the first committed instruction.
- The active debug cone is:
  - `MEFreeList.sv:2026`
  - `StdFreeList_1.sv:652`
  - `StdFreeList.sv:1381`

## 2026-04-14 Wave Check

### Waveforms

- Reference waveform:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/xs_wolf_20260413_165458.fst`
- Current GrhSIM waveform:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/xs_wolf_grhsim_coremark_20260414_1109.fst`

### Assertion Instance Mapping

- `MEFreeList.sv:2026`
  - instance: `intFreeList`
- `StdFreeList.sv:1381`
  - instance: `fpFreeList`
- `StdFreeList_1.sv:652`
  - instance: `vecFreeList`

### Direct Compared Signals

- `StdFreeList.sv:1381`
  - assertion condition: `~_GEN_44 & ~reset`
  - direct compared signals inside `_GEN_44`:
    - `tailPtr_flag != archHeadPtr_flag`
    - `_tailPtr_new_ptr_value_T_1 == archHeadPtr_value`
- `StdFreeList_1.sv:652`
  - assertion condition: `~_GEN_28 & ~reset`
  - direct compared signals inside `_GEN_28`:
    - `tailPtr_flag != archHeadPtr_flag`
    - `_tailPtr_new_ptr_value_T_1 == archHeadPtr_value`
- `MEFreeList.sv:2026`
  - assertion condition: `_GEN_45 & ~reset`
  - `_GEN_45` is not directly dumped in the current waveform
  - directly inspected operands / sub-terms:
    - `tailPtr_flag`
    - `tailPtr_value`
    - `debugArchHeadPtr_flag`
    - `debugArchHeadPtr_value`
    - `freeRegCntReg`
    - `_GEN_42`
    - `_GEN_43`
    - `_GEN_44`

### Wave Comparison At Cycles 660-663

- `intFreeList`:
  - current and reference both show:
    - `tailPtr_flag = 0`
    - `tailPtr_value = 11011111`
    - `debugArchHeadPtr_flag = 0`
    - `debugArchHeadPtr_value = 00000001`
    - `freeRegCntReg = 11011101`
    - `_GEN_42 = 00010`
    - `_GEN_43 = 0000`
    - `_GEN_44 = 0000`
- `fpFreeList`:
  - current and reference both show:
    - `_GEN_44 = 1`
    - `tailPtr_flag = 1`
    - `archHeadPtr_flag = 0`
    - `_tailPtr_new_ptr_value_T_1 = 00000000`
    - `archHeadPtr_value = 00000000`
- `vecFreeList`:
  - current and reference both show:
    - `_GEN_28 = 1`
    - `tailPtr_flag = 1`
    - `archHeadPtr_flag = 0`
    - `_tailPtr_new_ptr_value_T_1 = 0000000`
    - `archHeadPtr_value = 0000000`

### Conclusion From Waveforms

- At least in the dumped waveforms around the failing point, the three assertion cones do not show an actual mismatch between the current GrhSIM run and the reference SV run.
- The two directly dumped assertion booleans also look non-failing in the waveform:
  - `fpFreeList$_GEN_44 = 1`
  - `vecFreeList$_GEN_28 = 1`
- This strongly suggests the current failure is not caused by the final persisted values of these declared signals being wrong.
- A more likely direction is:
  - assertion evaluation is seeing a stale / transient / wrongly ordered value during GrhSIM eval
  - while the final dumped declared value after eval already matches the reference waveform

### Reference Assertion Value Check

- Reference waveform lookup used fuzzy name matching because signal names differ slightly between runs:
  - reference root prefix: `TOP.SimTop...`
  - current GrhSIM root prefix: `SimTop...`
- In the reference waveform:
  - `fpFreeList$_GEN_44 = 1` at cycles `660-663`
  - `vecFreeList$_GEN_28 = 1` at cycles `660-663`
- Therefore the actual assertion predicates are not true in the reference waveform:
  - `~fpFreeList$_GEN_44 = 0`
  - `~vecFreeList$_GEN_28 = 0`
- For `MEFreeList/intFreeList`, no direct `_GEN_45` signal is present in the reference waveform even under fuzzy matching.
- But the available direct operands / sub-terms of that assertion cone remain matched between current GrhSIM and reference at cycles `660-663`.

## 2026-04-14 Assertion Lowering And Cond Backtrace

### C++ Lowering Shape

- XiangShan assertions are not lowered into a single special `fwrite`.
- In emitted GrhSIM C++, one assertion is usually split into two side-effect ops under the same `cond && posedge` guard:
  - a system task `execute_system_task("fwrite", ...)` for the message text
  - a DPI call `xs_assert_v2(file, line)` for the assertion bookkeeping
- Example:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_946.cpp:7143-7161`
- Runtime behavior:
  - `execute_system_task("fwrite", ...)` only formats and emits text
  - `xs_assert_v2` prints `Assertion failed at <file>:<line>.` and increments `assert_count`
  - emu exits later when `assert_count > 0`

### Common Cond Skeleton

- For the currently failing free-list assertions, emitted `cond` always simplifies to:
  - `failure_pred && ~reset`
- The apparent extra `&& value_u32_slots_[234]` is irrelevant:
  - `value_u32_slots_[234]` is constant `1`
  - definition: `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_13.cpp:129`
- `~reset` comes from:
  - `value_bool_slots_[40031] = ~cpu$l_soc$core_with_l2$reset`
  - definition: `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_594.cpp:1855`

### MEFreeList.sv:2026

- Trigger site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1441.cpp:3532-3538`
- Immediate cond chain:
  - `value_bool_slots_[1664124] = value_bool_slots_[1664123] && 1`
  - `value_bool_slots_[1664123] = value_bool_slots_[7671] && ~reset`
- Therefore:
  - `cond = value_bool_slots_[7671] && ~reset`
- `value_bool_slots_[7671]` comes from:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1139.cpp:4475-4481`
  - expression: `value_u16_slots_[50824] != value_u16_slots_[3024]`
- Known substructure:
  - `value_u16_slots_[3024] = 224`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_52.cpp:775-781`
  - `value_u16_slots_[50824] = value_u16_slots_[50822] + value_u16_slots_[50823]`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1139.cpp:4470-4473`
  - `value_u16_slots_[50822] = cat(value_bool_slots_[8039], value_u8_slots_[550124])`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_445.cpp:10335-10342`
  - `value_u16_slots_[50823] = cat(value_u8_slots_[3210], value_u8_slots_[550130])`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1139.cpp:4463-4467`
- Static reading:
  - this assertion is checking whether one 9-bit accumulated count/sum equals constant `224`

### StdFreeList.sv:1381

- Trigger site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1286.cpp:2722-2729`
- Immediate cond chain:
  - `value_bool_slots_[1675816] = value_bool_slots_[1675815] && 1`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_946.cpp:8224-8229`
  - `value_bool_slots_[1675815] = value_bool_slots_[7672] && ~reset`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_946.cpp:8141-8144`
- Therefore:
  - `cond = value_bool_slots_[7672] && ~reset`
- `value_bool_slots_[7672]` comes from:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_446.cpp:6032-6039`
  - expression: `compare_unsigned_words(value_words_4_slots_[1124], value_words_4_slots_[1120]) != 0`
- Static reading:
  - this assertion is a wide-vector inequality check
  - it is not a simple scalar compare, but a mismatch between two 4-word-wide states

### StdFreeList_1.sv:652

- Trigger site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1286.cpp:267-280`
- Immediate cond chain:
  - `value_bool_slots_[1686422] = value_bool_slots_[1686421] && 1`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_946.cpp:8233-8240`
  - `value_bool_slots_[1686421] = value_bool_slots_[7676] && ~reset`
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_946.cpp:8147-8150`
- Therefore:
  - `cond = value_bool_slots_[7676] && ~reset`
- `value_bool_slots_[7676]` comes from:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_446.cpp:9040-9047`
  - expression: `compare_unsigned_words(value_words_2_slots_[7917], value_words_2_slots_[7913]) != 0`
- Static reading:
  - this assertion is another wide-vector inequality check
  - it is a mismatch between two 2-word-wide states

### Current Static Conclusion

- The three currently failing free-list assertions are not triggered by any special assertion-only runtime rule.
- Their effective predicate is:
  - `failure_pred && ~reset && posedge`
- The meaningful `failure_pred` forms are:
  - `MEFreeList`: accumulated 9-bit count is not equal to constant `224`
  - `StdFreeList`: 4-word-wide vector mismatch
  - `StdFreeList_1`: 2-word-wide vector mismatch
- Since the wave dump near failure still matches the reference for visible declared signals, the remaining likely issue is still:
  - a stale / transient / ordering problem during the evaluation of these `failure_pred` values
  - not a straightforward final-state mismatch after the whole eval settles

## 2026-04-14 Actual Compared Value Names

### MEFreeList.sv:2026

- compare site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_1139.cpp:4475-4481`
- actual compared values:
  - lhs: `_val_4432580` (`value_u16_slots_[50824]`, `value_id=2482554:0`)
  - rhs: `_val_275467` (`value_u16_slots_[3024]`, constant `224`)
- note:
  - `_val_4432580` is not a declared symbol; it is the internal 9-bit sum
    - `_val_4432580 = _val_4432564 + _val_4432578`

## 2026-04-14 fpFreeList headPtrOH Nearest-Symbol Wave Diff

### Compared Waveforms

- reference:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/xs_wolf_20260413_165458.fst`
- GrhSIM:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/xs_wolf_grhsim_coremark_vec64fix_clean.fst`

### Extracted Traces

- reference trace:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/headPtrOH_nearest_ref.csv`
- GrhSIM trace:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/headPtrOH_nearest_grhsim.csv`
- diff summary:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/headPtrOH_nearest_diff.txt`

### Nearest Declared Symbols Compared

- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList_io_doAllocate`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$io_canAllocate_last_REG`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$_rob_io_rabCommits_isWalk`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$io_redirect_valid`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$needFpDest_0..7`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$lastCycleRedirect`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$lastCycleSnpt_useSnpt`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$lastCycleSnpt_snptSelect`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$archHeadPtr_{flag,value}`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$snapshots_snapshotGen$io_snapshots_0..3_{flag,value}`
- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$io_walkReq_0..7`

### Result

- In the overlap window of the two waveforms, the first divergence happens at:
  - `cycle=713`
  - `phase=rise`
- The first divergent nearest symbol is:
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
- At that point:
  - reference `headPtrOH` is still one-hot at bit 0
  - GrhSIM `headPtrOH` has already moved to one-hot at bit 34
- The nearest declared-symbol inputs around it are still matched at that same point:
  - `fpFreeList_io_doAllocate = 1`
  - `_rob_io_rabCommits_isWalk = 1`
  - `io_redirect_valid = 0`
  - `needFpDest_0..7 = 0`
  - the tracked `lastCycleRedirect / lastCycleSnpt / archHeadPtr / snapshots / io_walkReq_*` signals do not diverge before `headPtrOH`

### Current Conclusion

- The bug is now narrowed down further:
  - it is not that the nearest declared-symbol cone first diverges and then propagates into `headPtrOH`
  - instead, `headPtrOH` itself is the first visible divergence in this local cone
- Therefore the next debug target should be the `headPtrOH` register write path in emitted C++:
  - write enable
  - selected write data
  - the write mask / merge path
    - `_val_4432564` is `cat(value_bool_slots_[8039], value_u8_slots_[550124])`
    - `_val_4432578` is `cat(value_u8_slots_[3210], value_u8_slots_[550130])`

### StdFreeList.sv:1381

- compare site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_446.cpp:6032-6039`
- actual compared values:
  - lhs: `_val_4448831` (`value_words_4_slots_[1124]`, `value_id=2495434:0`)
  - rhs: `_val_4448560` (`value_words_4_slots_[1120]`, `value_id=2495054:0`)
- resolved meaning:
  - `_val_4448560` is read of `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
  - `_val_4448831` is a dynamic slice taken from `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_GEN`

### StdFreeList_1.sv:652

- compare site:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_446.cpp:9040-9047`
- actual compared values:
  - lhs: `_val_4477098` (`value_words_2_slots_[7917]`, `value_id=2511770:0`)
  - rhs: `_val_4476968` (`value_words_2_slots_[7913]`, `value_id=2511549:0`)
- resolved meaning:
  - `_val_4476968` is read of `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$vecFreeList$headPtrOH`
  - `_val_4477098` is a dynamic slice taken from `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$vecFreeList$_GEN`

## 2026-04-14 StdFreeList.sv:1381 Wave Diff

The original conclusion in this section is now obsolete.
The earlier GrhSIM FST was corrupted by a `libfst` wide-vector serialization bug in
`fstWriterEmitValueChangeVec64()`, so the old wave diff mixed a real model run with a bad
waveform dump.

### Trace Sources

- Old pre-fix GrhSIM waveform artifacts:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_1381_raw.csv`
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_1381_trace_rise.csv`
- Reference SV waveform artifacts:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_1381_ref_raw.csv`
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_1381_ref_trace_rise.csv`
- Fixed GrhSIM waveform:
  - `/home/gaoruihao/wksp/wolvrix-playground/tmp/xs_wolf_grhsim_coremark_vec64fix_clean.fst`
- Re-extracted declared-symbol CSVs:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_declared_symbols_grhsim.csv`
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_declared_symbols_ref.csv`
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/std_freelist_declared_symbols_aligned.csv`

### Reconstruction Rule

- `StdFreeList.sv:1381` compare is:
  - `compare_unsigned_words(value_words_4_slots_[1124], value_words_4_slots_[1120]) != 0`
- In waveform terms:
  - rhs is `fpFreeList$headPtrOH`
  - lhs is reconstructed as the 222-bit dynamic slice of `fpFreeList$_GEN`
- The emitted dynamic slice index used by current GrhSIM C++ is:
  - `value_u8_slots_[3209]`
  - current emitted mapping:
    - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_7.cpp:52`
    - `cpu$l_soc$dma_awlen -> value_u8_slots_[3209] [value_id=12105:0]`
- In both current and reference waveforms over cycles `0..663`:
  - `dma_awlen = 0`

### Obsolete Pre-fix Conclusion

- The old GrhSIM waveform showed a stable `{32, 0}` one-hot pattern in both:
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_GEN`
- That old conclusion is invalid.
- Root cause of the old mismatch:
  - `libfst` `fstWriterEmitValueChangeVec64()` truncated each 64-bit word through a 32-bit temporary
  - the extra stable `bit32` was a waveform artifact, not a model-state artifact

### Updated Declared Symbol Diff

- Compared range:
  - `cycle 0..663`
  - total rows: `1328`
- Compared declared symbols:
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_GEN`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtr_value`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$snapshots_snapshotGen$io_enqData_value`
  - `cpu$l_soc$dma_awlen`
- New result:
  - no mismatch remains in any of the 5 tracked declared symbols
  - reference and fixed GrhSIM are identical across all `1328` rows
- Concrete update:
  - `headPtrOH` first-row one positions are now `{0}` in both reference and GrhSIM
  - `_GEN` first-row one positions are now `{0}` in both reference and GrhSIM

### Updated Interpretation

- The previously reported steady-state `bit32` mismatch was only a bad waveform dump.
- `fpFreeList$headPtrOH`, `fpFreeList$_GEN`, `headPtr_value`, `io_enqData_value`, and `dma_awlen`
  do not explain the current `StdFreeList.sv:1381` assertion failure.
- The next useful debug target is no longer this declared-symbol chain.
- The next useful debug target should move to:
  - the assertion trigger chain itself, such as `cmp / guard / fire`
  - or intermediate combinational values not covered by this declared-symbol export

## 2026-04-14 fpFreeList Wide-Shift Re-Localization

### New Artifacts

- Expanded aligned waveform CSV:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/fpFreeList_declared_sources_ref_vs_grhsim.csv`
- Signal manifest:
  - `/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/fpFreeList_declared_sources_manifest.txt`

### Compared Signal Set

- The expanded CSV contains 41 common signals across reference and GrhSIM, covering:
  - nearest declared symbols around `fpFreeList$headPtrOH`
  - `redirectedHeadPtrOH_new_value`
  - `redirectedHeadPtrOH_new_value_1`
  - `_redirectedHeadPtrOH_T_14`
  - `_redirectedHeadPtrOH_T_30`
  - `_GEN_49`
  - `headPtrOH`

### Diff Result

- Only 4 signals differ in the expanded 41-signal comparison:
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_redirectedHeadPtrOH_T_14`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_redirectedHeadPtrOH_T_30`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$_GEN_49`
  - `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rename$fpFreeList$headPtrOH`
- Timing:
  - `_redirectedHeadPtrOH_T_14` first differs at `cycle=0 rise`
  - `_redirectedHeadPtrOH_T_30` first differs at `cycle=0 rise`
  - `_GEN_49` and `headPtrOH` first differ later at `cycle=713 rise`

### Concrete Mismatch Shape

- At `cycle=0 rise`:
  - reference:
    - `redirectedHeadPtrOH_new_value = 0`
    - `redirectedHeadPtrOH_new_value_1 = 0`
    - `_redirectedHeadPtrOH_T_14` is one-hot at `bit 0`
    - `_redirectedHeadPtrOH_T_30` is one-hot at `bit 0`
  - GrhSIM:
    - `redirectedHeadPtrOH_new_value = 0`
    - `redirectedHeadPtrOH_new_value_1 = 0`
    - `_redirectedHeadPtrOH_T_14` is one-hot at `bit 34`
    - `_redirectedHeadPtrOH_T_30` is one-hot at `bit 34`
- Therefore the bad value is not only in high padding bits.
- The low valid 222-bit region is already wrong before `headPtrOH` itself diverges.

### Static Mapping In Emitted C++

- Failing XiangShan path is in:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_3374.cpp`
- Relevant ops:
  - `_op_4738373`
    - `fpFreeList$_redirectedHeadPtrOH_T_14 -> value_words_4_slots_[1122]`
  - `_op_4738772`
    - `fpFreeList$_redirectedHeadPtrOH_T_30 -> value_words_4_slots_[1123]`
- Both are emitted as:
  - `grhsim_shl_words(value_words_4_slots_[704], grhsim_index_words(value_u8_slots_[...], 256), 256)`
- Their shared left operand is:
  - `value_words_4_slots_[704]`

### Shared One-Hot Base Constant

- `value_words_4_slots_[704]` is initialized in:
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_37.cpp`
- Exact emitted constant:
  - `std::array<std::uint64_t, 4>{1, 0, 0, 0}`
- So the shared one-hot base constant itself is correct and matches `256'h1`.

### kShl Emit / Runtime Location

- Emit-side helper selection is in:
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
  - `shiftWordsBufferOpExpr(...)`
  - wide `OperationKind::kShl` lowers to `grhsim_shl_words(...)`
- Runtime helpers are in the same file:
  - pointer-buffer version: `grhsim_shl_words(const std::uint64_t *...)`
  - array version: `grhsim_shl_words(const std::array<std::uint64_t, N> &...)`
- Shift index conversion goes through:
  - `grhsim_index_words(...)`

### Independent Runtime Check

- A standalone local C++ check was run with the current helper body:
  - input: `{1, 0, 0, 0}`
  - width: `256`
  - shifts tested: `0, 1, 34, 63, 64, 65`
- Result:
  - `shift=0` produces `bit 0`
  - `shift=34` produces `bit 34`
  - `shift=64` produces `bit 64`
- So `grhsim_shl_words({1,0,0,0}, shift, 256)` is mathematically self-consistent in isolation.

### Current Conclusion

- Current best localization is:
  - wide `kShl` path / one-hot construction around `_redirectedHeadPtrOH_T_14` and `_redirectedHeadPtrOH_T_30`
- Already ruled out:
  - bad declared-symbol source values in the nearest exported cone
  - bad shared one-hot base constant `value_words_4_slots_[704]`
  - a trivial standalone bug in `grhsim_shl_words({1,0,0,0}, shift, 256)`
- Remaining likely directions:
  - shift amount reaching these `kShl` ops is not the value it appears to be in the current debug view
  - or the observed waveform / exported slot for these wide intermediates is still affected by pooled-slot / observation semantics rather than the actual value consumed later

## 2026-04-14 StdFreeList.sv:1381 Windowed Path Instrumentation

### Instrumented Scope

- Added windowed GrhSIM-only logs for the path:
  - `headPtrOH` read: `value_words_4_slots_[1120]`
  - `_GEN`: `value_words_4_slots_[1121]`
  - dynamic-slice lhs: `value_words_4_slots_[1124]`
  - cmp: `value_bool_slots_[7672]`
  - guard0: `value_bool_slots_[1675815]`
  - guard1: `value_bool_slots_[1675816]`
  - fire path / actual fire
- Window:
  - around the known failing outer evals `1409..1431`
  - only when `clock=1 && prev_clk=0`

### Key Observation

- Up to `eval=1427`, the path is stable:
  - `headPtrOH = 1`
  - `_GEN = 1`
  - `lhs = 1`
  - `cmp = 0`
  - `guard0 = 0`
  - `guard1 = 0`
  - `fire = 0`
- The first real divergence appears at `eval=1429`, after the initial posedge round of that same outer eval:
  - earlier in `eval=1429`, logs still show:
    - `edge=1`
    - `cmp=0`
    - `guard0=0`
    - `guard1=0`
    - `fire=0`
  - later in the same `eval=1429`, logs show:
    - `edge=0`
    - `headPtrOH=[0000000400000000 0000000000000000 0000000000000000 0000000000000000]`
    - `_GEN=[0000000000000001 0000000000000000 0000000000000000 0000000000000000]`
    - `lhs=[0000000000000001 0000000000000000 0000000000000000 0000000000000000]`
    - `cmp_next=1`
    - then `guard0` and `guard1` both flip to `1`
- On the next posedge eval `1431`:
  - `cmp=1`
  - `guard0=1`
  - `guard1=1`
  - `fire=1`
  - assertion side effects execute

### Interpretation

- This is no longer a declared-symbol mismatch problem.
- The trigger is caused by an intra-`eval()` mutation:
  - `headPtrOH` changes inside the failing outer eval
  - `_GEN`, `lhs`, `headPtr_value`, `io_enqData_value`, and `dma_awlen` stay unchanged in the observed window
- Therefore the current failure is specifically:
  - `headPtrOH` becomes inconsistent with the compare lhs during a later fixed-point round of `eval=1429`
  - that late flip propagates through `cmp -> guard0 -> guard1`
  - then the next posedge at `eval=1431` consumes the already-latched guard and fires the assertion

### Next Target

- Investigate what writes or commits `state_logic_words_4_slots_[5]` / `state_shadow_words_4_slots_[5]`
  between the early and late rounds of `eval=1429`.
- In other words:
  - debug should move upstream from the assertion path into the `fpFreeList$headPtrOH` state update / commit timing path

## 2026-04-14 fpFreeList headPtrOH Write-Port Input Trace

### Target Write Port

- `headPtrOH` write port is `_op_4738860`
- source: `StdFreeList.sv:1573`
- emitted in `grhsim_SimTop_sched_3374.cpp`
- inputs:
  - enable: `_val_4462154`
  - data: `_val_4462170`
  - mask: `_val_4462171`

### Enable `_val_4462154`

- static chain:
  - `_val_4462154 = _val_4462151 | _val_4462153`
  - `_val_4462151 = reset | _val_4462150`
  - `_val_4462150 = _val_4462104 & lastCycleRedirect`
  - `_val_4462153 = _val_4462104 & !lastCycleRedirect`
- equivalent form:
  - `_val_4462154 = reset | _val_4462104`
- and `_val_4462104` is the `if` condition at `StdFreeList.sv:1805`:
  - `_val_4462104 = ~reset & ~io_redirect & (isWalkAlloc | isNormalAlloc)`
- interpretation:
  - `headPtrOH` only writes on reset, or when the free list enters the
    `~io_redirect & (isWalkAlloc | isNormalAlloc)` update block

### Data `_val_4462170`

- static chain:
  - `_val_4462170 = _val_4462153 ? _val_4462157 : _val_4462168`
  - `_val_4462168 = _val_4462150 ? _val_4462166 : _val_4462167`
  - `_val_4462166 = lastCycleSnpt_useSnpt ? _val_4462161 : _val_4462165`
- therefore:
  - if `~io_redirect & (isWalkAlloc | isNormalAlloc) & !lastCycleRedirect`
    - write `_val_4462157 = _GEN_49[numAllocate]`
  - else if `~io_redirect & (isWalkAlloc | isNormalAlloc) & lastCycleRedirect`
    - write `_val_4462166`
    - if `lastCycleSnpt_useSnpt`
      - `_val_4462161 = _redirectedHeadPtrOH_T_14[221:0]`
    - else
      - `_val_4462165 = _redirectedHeadPtrOH_T_30[221:0]`
  - else
    - `_val_4462167 = 222'h1`
- nearest declared-symbol view:
  - normal-allocate path depends on:
    - `fpFreeList$headPtrOH`
    - `fpFreeList$_GEN_49`
    - `fpFreeList$numAllocate`
  - redirect path depends on:
    - `fpFreeList$lastCycleRedirect`
    - `fpFreeList$lastCycleSnpt_useSnpt`
    - `fpFreeList$_redirectedHeadPtrOH_T_14`
    - `fpFreeList$_redirectedHeadPtrOH_T_30`

### Mask `_val_4462171`

- `_val_4462171` is a constant all-ones 222-bit mask
- emitted as:
  - `value_words_4_slots_[1140] = 222'b111...111`
- interpretation:
  - the write is always a full-width overwrite
  - no partial-mask semantics are involved in this bug

### Implication For Next Debug Step

- the bug space is now narrower:
  - if the first bad `headPtrOH` value comes from normal allocate,
    the suspicious path is `headPtrOH -> _GEN_49 -> slice(numAllocate)`
  - if it comes from redirect,
    the suspicious path is
    `_redirectedHeadPtrOH_T_14/_30 -> slice -> mux(lastCycleSnpt_useSnpt)`
- because earlier wave comparison already showed nearby declared symbols still match
  at the first divergence point, the highest-probability failure remains:
  - an internal temporary / scheduling / late-commit problem inside this write-port data path

### Branch Decision At First Divergence

- at the first waveform divergence (`cycle=713 rise`):
  - reference: `lastCycleRedirect=0`
  - GrhSIM: `lastCycleRedirect=0`
  - reference: `lastCycleSnpt_useSnpt=1`
  - GrhSIM: `lastCycleSnpt_useSnpt=1`
- therefore the bad `headPtrOH` update is not taking the redirect path
- the first bad write is on the normal-allocate path:
  - `_val_4462170 = _GEN_49[numAllocate]`
- this further narrows the next target to:
  - current `headPtrOH`
  - `_GEN_49`
  - `numAllocate`
  - dynamic slice / index lowering in emitted C++

### Runtime C++ Instrumentation: Actual Bad-Write Cause

- newer `emu cpp` instrumentation supersedes the earlier "normal path" suspicion above
- incremental rebuild + runtime prints show the first bad `headPtrOH` write is caused by a spurious delayed redirect pulse

### Counter Alignment Note

- do not directly compare these three counters as if they were the same thing:
  - waveform `cycle` from `fst_cycle_trace`
  - internal `logEndpoint$clock_cycleCounter`
  - `emu` printed `cycleCnt` / `Guest cycle spent`
- they are different accounting domains

- confirmed mapping near the failure window:
  - waveform `cycle=708` corresponds to `logEndpoint$clock_cycleCounter=660`
  - waveform `cycle=709` corresponds to `661`
  - waveform `cycle=710` corresponds to `662`
  - waveform `cycle=713` corresponds to `665`
  - waveform `cycle=714` corresponds to `666`
- therefore the waveform cycle index is ahead of the internal cycle counter by about `48`
  cycles in this run, because the waveform cycle index starts counting from the beginning
  of the dumped clock history, including reset / startup cycles

- `emu` also prints two different counters:
  - `cycleCnt = 662`
    - comes from `trap->cycleCnt`
  - `Guest cycle spent: 666`
    - comes from the emulator-side `cycles` variable
- so the earlier apparent mismatch
  - "waveform divergence at cycle 713"
  - vs "emu reports cycleCnt 662"
  is not a contradiction

- practical rule for later debug:
  - compare waveforms to waveforms by aligned waveform cycle or by internal traced counters
  - compare `emu cpp` instrumentation logs to themselves by `eval` / fixed-point round
  - do not equate `eval=1425` with waveform `time=1425` or waveform `cycle=712/713`

### Key Runtime Sequence

- `eval=1425 round=1 edge=1`
  - `fpFreeList-lastCycleRedirectReg-write`
  - `prev=0 robFlush=0 stage2Redirect=1 xmr=1 merged=1`
  - meaning:
    - `fpFreeList$lastCycleRedirect_REG` is written to `1`
    - source is `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$_redirectGen_io_stage2Redirect_valid`
    - `robFlush_valid` is `0`; the pulse comes purely from `stage2Redirect_valid`
- `eval=1427 round=1 edge=1`
  - `fpFreeList-lastCycleRedirect-write`
  - `prev=0 src_prev_reg=1 merged=1`
  - `fpFreeList-lastCycleRedirectReg-write`
  - `prev=1 robFlush=0 stage2Redirect=0 xmr=0 merged=0`
  - meaning:
    - the delayed register chain behaves sequentially as emitted
    - `lastCycleRedirect` takes the previous-cycle `lastCycleRedirect_REG=1`
    - simultaneously `lastCycleRedirect_REG` is cleared back to `0`
- `eval=1427 round=2 edge=0`
  - path mux already sees:
    - `lastCycleRedirect=1`
    - `lastCycleSnpt_useSnpt=1`
    - `selected_data = redirect_data = 0x0000000400000000`
- `eval=1429 round=1 edge=1`
  - `headPtrOH` write executes with:
    - `write_base = 0x1`
    - `write_data = 0x0000000400000000`
    - `write_merged = 0x0000000400000000`
  - then `StdFreeList.sv:1381` assertion fires

### Conclusion

- the write port itself is not the bug:
  - dynamic slice result for the redirect path is internally consistent
  - full-width mask / merge are internally consistent
  - state-shadow commit order for the two redirect registers is internally consistent
- the proximate cause is earlier:
  - runtime instrumentation sees
    `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$_redirectGen_io_stage2Redirect_valid`
    sampled as `1` at `eval=1425`
  - that pulse loads `fpFreeList$lastCycleRedirect_REG`
  - one cycle later it propagates into `fpFreeList$lastCycleRedirect`
  - that delayed redirect flag selects `redirect_data` and writes bad `headPtrOH`
- therefore the next target is not `headPtrOH` mask/slice lowering itself, but:
  - why emitted C++ samples `_redirectGen_io_stage2Redirect_valid` as high at that `eval`
  - or why that signal is observed/activated at the wrong moment relative to the runtime
    scheduling point in GrhSIM
