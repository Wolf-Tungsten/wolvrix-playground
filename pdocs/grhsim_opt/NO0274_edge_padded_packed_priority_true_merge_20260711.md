# NO0274 Edge-padded packed-priority true-merge

日期：2026-07-11

## 目标

承接 [NO0273](./NO0273_post_tage_commit_miss_state_family_diagnosis_20260711.md)，补齐
`reg-to-mem` 对 ROB `debug_VecOtherPdest[352][8]` 的通用识别能力。目标不是按 ROB 或信号名做
特例，而是同时处理真实 IR 中的三个结构缺口：512-view/352-storage 的 edge padding、
`comb-lane-pack` 产生的 packed mux，以及包含窄 lane selector 的复合写优先级。

## Edge-padded storage discovery

目标 packed view 的 512 个 operand 为：

```text
[row0 repeated 160 times, row351, row350, ..., row1, row0]
```

新增 discovery 只接受以下保守形态：

1. 去掉单侧连续 padding 后，core 中每个 register symbol 恰好出现一次；
2. padding value 必须等于 core 对应边缘的 value；
3. memory depth 使用唯一 core 的实际行数，原 concat 与 dynamic slice 保留；
4. scalar register read 仍逐个替换为 constant-row memory read，因此越界 view operand 继续 alias
   到原 edge row，不改变 9-bit index `352..511` 的图语义；
5. 是否删除 scalar storage 仍由完整 read closure 和逐行 write-family matcher 决定。

synthetic case 显式使用 leading edge padding，并检查 padding operand 与 row0 仍共享同一个替换后的
memory-read value。

## Packed mux 与复合优先级

`comb-lane-pack` 在 `reg-to-mem` 之前运行。目标 register write 的 next value不再是标量 `kMux`，
而是 `pack-result-slice` 指向由 `pack-mux-*` operation 组成的 packed tree。写 guard 同时含：

```text
wide robIdx == row
narrow vdIdx == lane
!(higherEnable && higherRobIdx == row && higherVdIdx == lane)
```

本轮实现保持以下 strict 边界：

- 仅投影 `SrcLoc` 明确标记为 `transform/comb-lane-pack` 且 note 精确匹配的 generated operation；
- packed data 只接受完整 lane 边界上的 concat operand 或常量，不接受任意 partial slice；
- row0 的 `!(|addr)` 只按零值 equality 处理；
- storage address 的位宽必须覆盖全部 memory rows；不能覆盖 row 数的 equality 留作普通 lane
  selector，不能误选为 memory address；
- 复合冲突必须包含恰好一个与当前 row 对齐的 storage-address equality，并至少包含一个窄
  selector，避免把普通 group-wide reset/fill 条件误识别为写冲突；
- rewrite 将冲突恢复为 `!(commonTerms && conflictAddr == writeAddr)`，保持原有写优先级。

新增 synthetic 回归先运行真实的 `comb-lane-pack + two-state simplify`，再运行 `reg-to-mem`；它
检查两个 indexed memory write 均被恢复，并检查低优先级 write guard 中仍存在同时依赖高优先级
address 和 lane selector 的取反子树。

## SimTop stop-after 结构门禁

复用 pre-reg-to-mem checkpoint：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

最终 stop-after-pre-sched 结果：

| metric | value |
| --- | ---: |
| candidate groups | `760` |
| total groups | `4315` |
| edge-padded groups / anchors | `476 / 493` |
| all true-merged groups | `825` |
| edge-padded true-merged groups | `171` |
| target ROB groups | `8 / 8` |
| target rows per group | `352` |
| target scalar storage rows | `2816` |

group `870..877` 分别对应 lane `0..7`，每组均完成 `true_match_done` 和
`rewrite_true_done ok=1`，且 `true_merged=1`。这证明 matcher 已在真实 SimTop IR 上越过 packed mux、
双索引 guard 和复合优先级三道门禁；本阶段尚不把 stop-after 结果当作可执行 emu 的功能结论。

日志：

```text
build/logs/xs_perf/no0274/rob_priority_conflict_stop_after_diag_20260711.log
```

## Local gate

所有命令均先执行 `source env.sh`。相关 CTest：

```text
emit-grhsim-cpp       PASS 147.54s
transform-reg-to-mem PASS   0.03s
```

完整 CTest 为 `46/48`。本轮相关的 `transform-reg-to-mem`、`emit-grhsim-cpp`、
`emit-grhsim-cpp-memory-fill` 与全部 ingest 测试均通过；失败项仍为既有基线：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

日志：

```text
build/logs/xs_perf/no0274/ctest_reg_to_mem_priority_conflict_20260711.log
build/logs/xs_perf/no0274/ctest_full_20260711.log
```

## 下一步

下一阶段必须 fresh emit/build，检查 generated C++ 中目标 2816 个 scalar write 是否实际消失，
再独立执行 SimTop 10k/50k difftest。只有功能门禁通过后，才与 NO0271 当前基线在同一机器负载
窗口做 paired 性能测试。
