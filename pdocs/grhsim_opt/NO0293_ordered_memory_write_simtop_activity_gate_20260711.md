# NO0293 Ordered memory-write SimTop activity gate

日期：2026-07-11

## 1. 口径

承接 [NO0292](./NO0292_ordered_memory_write_implementation_gate_20260711.md)，从固定 checkpoint：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

恢复同一份 SimTop pre-reg-to-mem GRH，启用 `WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES=1`，运行至 activity-schedule 后停止：

```text
build/xs_grhsim_no0293_ordered_write_activity_stop_20260711/grhsim
```

执行前机器 load average 为 `4.52/8.15/9.27`，机器有 384 个逻辑 CPU；本阶段只比较确定性的图结构，不用 build wall time 推导仿真性能。

## 2. RAT lowering

write-side discovery 与 NO0289 相同：

```text
matched_rows=95
families=3
true_groups=835
```

三组 lowering 结果：

| Group | Rows | Writers | Theoretical pair conflicts | Ordered rewrite |
| --- | ---: | ---: | ---: | ---: |
| fpRat | 32 | 511 | 130,305 | 19 ms |
| intRat | 32 | 511 | 130,305 | 18 ms |
| vecRat | 31, offset 1 | 520 | 134,940 | 23 ms |
| Total | 95 | 1,542 | 395,550 | 60 ms |

三组日志均为 `ordered_writes=1`。`priority_conflicts` 是 matcher 识别出的理论冲突数，只用于说明被省略的工作；ordered lowering 没有为这些冲突创建 Eq/And/Not 网络。

reg-to-mem 总时间为 `142.745 s`。相对 NO0289 的约 149-152 s 只略有下降，因为主要成本仍在 discovery、regular-write matching 和其他 835 个 true groups；该时间不是本次 runtime 优化的验收指标。

## 3. Activity 结构对比

| Metric | NO0286 baseline | NO0290 explicit conflicts | NO0293 ordered | Ordered vs baseline |
| --- | ---: | ---: | ---: | ---: |
| graph ops | 7,196,059 | 9,186,156 | 7,202,647 | +0.09% |
| supernodes | 67,934 | 82,809 | 63,699 | -6.23% |
| compute supernodes | 67,449 | 82,324 | 63,213 | -6.28% |
| commit supernodes | 485 | 485 | 486 | +1 |
| DAG edges | 638,649 | 664,523 | 528,247 | -17.29% |
| boundary values | 1,162,161 | 1,374,680 | 1,000,463 | -13.91% |
| boundary activation edges | 2,261,833 | 2,850,858 | 1,983,476 | -12.31% |
| compute-compute value pairs | 2,003,556 | 2,589,598 | 1,721,277 | -14.09% |
| compute-commit value pairs | 258,277 | 261,260 | 262,199 | +1.52% |

相对 NO0290，ordered 方案的 graph ops `-21.59%`、supernodes `-23.08%`、boundary activation edges `-30.43%`。因此 NO0290 的近二次结构回退已消除。

相对 NO0286，最终 graph ops 仅 `+6,588`，原因是 95 个 scalar register writes 被 1,542 个 indexed memory writes 和 3 个 fill 替换；commit sink ops 从 `217,544` 增至 `218,994`，正好增加 `1,450`。与此同时 scalar row decoder/common-expression 结构被消除，使 compute、DAG 和 boundary 指标均显著下降。

## 4. Commit 聚合检查

NO0293 的 `commit_ops_max=42,937` 看似较大，但 NO0286 与 NO0290 的同一指标也都是 `42,937`，因此不是 ordered group 新引入的异常聚合。三组 ordered RAT 的最大 writer 数仅为 `520`；synthetic gate 另外验证了 ordered group 不会被 commit size cap 拆开。

## 5. 结论与下一步

Activity 静态 gate 通过：ordered contract 消除了 NO0290 的结构爆炸，并在多数执行图指标上优于 NO0286 baseline。仍需 fresh 完整生成和链接来确认：

1. generated C++ 与 emu `.text` 是否同步下降；
2. SimTop 10k/50k difftest 是否保持正确；
3. 静态与功能 gate 均通过后，固定 CPU old/new/old runtime 是否有稳定收益。

本阶段没有运行 emu，因此不包含 guest cycle 或 Host time 结论。
