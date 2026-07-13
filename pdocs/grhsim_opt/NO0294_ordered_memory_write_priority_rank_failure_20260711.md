# NO0294 Ordered memory-write priority-rank failure

日期：2026-07-11

## 1. Fresh 静态结果

承接 [NO0293](./NO0293_ordered_memory_write_simtop_activity_gate_20260711.md)，完成 fresh SimTop C++ emission、O3 编译和 emu 链接：

```text
build/xs_grhsim_no0294_ordered_write_fresh_20260711/grhsim
```

静态门禁相对 NO0286 baseline 明显改善：

| Metric | NO0286 | NO0290 explicit conflicts | NO0294 ordered | Ordered vs NO0286 |
| --- | ---: | ---: | ---: | ---: |
| generated `.cpp + .hpp` bytes | 1,488,642,375 | 1,686,685,146 | 1,379,551,278 | -7.33% |
| emu `.text` bytes | 97,049,715 | 114,083,082 | 88,275,097 | -9.04% |

C++ emission 为 `57.393 s`，完整 emit 为 `374.132 s`，emu 成功链接。上述静态收益只说明 pairwise conflict network 已消失，不能替代功能 gate。

## 2. 10k 功能失败

10k CoreMark/NEMU difftest 在很早阶段失败：

```text
Assertion failed at .../Phr.sv:14181
instrCnt = 2
cycleCnt = 660
Guest cycle spent = 664
terminal PC = 0x0
result = ABORT
```

因此 NO0294 emu 不进入 50k 或 runtime gate，静态收益也不能保留为正确优化。

## 3. 根因诊断

初版 lowering 将 `candidate.regulars` 的容器下标 `regularIndex` 直接写入 `memoryWrite.priority`。两写 synthetic 中 matcher 顺序与语义优先级恰好一致，但 OR-decoded RAT family 没有这个保证。

每个 `RegularWriteFamily` 已保留 `conflicts`：该集合列出所有会阻断当前 writer 的更高优先级 writers。因此 `conflicts.size()` 才是严格语义 rank，`0` 表示最高优先级。增加只读诊断并从同一 checkpoint 跑到 reg-to-mem 后停止，得到：

| Group | Writers | Rank range | Distinct ranks | `rank != regularIndex` |
| --- | ---: | ---: | ---: | ---: |
| fpRat | 511 | 0..510 | 511 | 510 |
| intRat | 511 | 0..510 | 511 | 510 |
| vecRat | 520 | 0..519 | 520 | 520 |

三组 rank 都唯一且连续，总数仍分别形成 `130,305/130,305/134,940` 的三角数；正因为 aggregate conflict count 正确，NO0293 的总量统计没有暴露排列错误。初版实际按错误排列执行同地址覆盖，违反 scalar RTL 优先级。

诊断产物：

```text
build/xs_grhsim_no0294_priority_rank_diag_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0294_priority_rank_diag_20260711.log
build/logs/xs/xs_wolf_grhsim_no0294_ordered_write_functional_10k_20260711.log
```

## 4. 修复要求

下一实现必须：

1. 从 `regular.conflicts.size()` 派生 priority，不依赖 matcher 容器顺序；
2. 仅当 ranks 唯一且连续覆盖 `[0,N)` 时启用 ordered lowering；
3. rank 不合法时保守回退显式 conflict guards；
4. synthetic 将 writer address 与预期 priority 一一对应，避免只检查“priority 唯一”再次漏掉方向/排列错误；
5. 重新执行 generated collision harness、SimTop fresh 10k/50k 和静态 gate。
