# NO0296 Ordered memory-write rank-fix fresh gate

日期：2026-07-11

## 1. 口径

承接 [NO0294](./NO0294_ordered_memory_write_priority_rank_failure_20260711.md) 与 [NO0295](./NO0295_ordered_memory_write_conflict_rank_fix_20260711.md)，从同一份 SimTop pre-reg-to-mem checkpoint 完成修复后的 fresh lowering、activity-schedule、C++ emission、O3 编译和 emu 链接：

```text
build/xs_grhsim_no0296_ordered_rank_fix_fresh_20260711/grhsim
```

本次不是复用 NO0294 的错误产物；新 emu SHA256 为：

```text
dc89fa38c6dd9bb276211f5d1aec3154fa72a0db491b3c37def8919321f91b6e
```

## 2. Priority rank 检查

三组 write-only RAT memory 均启用 ordered lowering，priority 改由 `regular.conflicts.size()` 派生：

| Group | Writers | Rank range | Distinct ranks | Rank valid | `rank != regularIndex` |
| --- | ---: | ---: | ---: | ---: | ---: |
| fpRat | 511 | 0..510 | 511 | 1 | 510 |
| intRat | 511 | 0..510 | 511 | 1 | 510 |
| vecRat | 520 | 0..519 | 520 | 1 | 520 |

`regularIndex` 的大量错配仍然存在，证明 NO0294 的诊断成立；但它现在只保留为诊断计数。三组 rank 均唯一连续覆盖 `[0,N)`，因此满足 ordered-write contract，不触发显式 conflict guard 回退。

## 3. Fresh 静态结构

| Metric | NO0286 baseline | NO0296 rank fix | Delta |
| --- | ---: | ---: | ---: |
| graph ops | 7,196,059 | 7,204,108 | +0.11% |
| supernodes | 67,934 | 63,726 | -6.19% |
| compute supernodes | 67,449 | 63,241 | -6.24% |
| commit supernodes | 485 | 485 | 0 |
| DAG edges | 638,649 | 528,622 | -17.23% |
| boundary values | 1,162,161 | 1,000,463 | -13.91% |
| boundary activation edges | 2,261,833 | 1,983,923 | -12.29% |
| compute-compute value pairs | 2,003,556 | 1,721,698 | -14.07% |
| compute-commit value pairs | 258,277 | 262,225 | +1.53% |
| generated `.cpp + .hpp` bytes | 1,488,642,375 | 1,379,649,713 | -7.32% |
| emu `.text` bytes | 97,049,715 | 88,272,265 | -9.04% |

`commit_ops_max` 保持 `42,937`，与 NO0286 一致。最终结果与 NO0293 的 activity-only 预期一致：pairwise priority-conflict 网络没有重新出现，且 corrected rank 不损失静态收益。

## 4. SimTop 功能门禁

使用 CoreMark 两迭代镜像和 NEMU difftest，分别执行 10k 与 50k 仿真周期：

| Limit | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| ---: | ---: | ---: | ---: | --- | --- |
| 10,000 | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| 50,000 | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |

两次均正常到达 cycle limit，没有 assertion、abort 或 difftest mismatch。单次未固定 CPU 的 Host time 分别为 `10,442 ms` 与 `84,858 ms`，只用于证明进程完整执行，不作为性能结论。

日志：

```text
build/logs/xs/xs_wolf_grhsim_build_no0296_ordered_rank_fix_fresh_20260711.log
build/logs/xs/xs_wolf_grhsim_no0296_ordered_rank_fix_functional_10k_20260711.log
build/logs/xs/xs_wolf_grhsim_no0296_ordered_rank_fix_functional_50k_20260711.log
```

## 5. 结论与下一步

修复后的 fresh 静态与 SimTop 10k/50k 功能门禁通过，NO0294 的错误优先级没有复现。该产物可以进入固定 CPU 性能门禁；下一步采用 NO0286 old / NO0296 new / NO0286 old 的相邻 50k 运行，并同时采集 cycles、instructions、branches 和 branch misses，避免把机器负载变化误判为优化收益。
