# NO0300 Ordered memory-write affine-loop fresh gate

日期：2026-07-12

## 1. 口径

承接 [NO0299](./NO0299_ordered_memory_write_affine_loop_implementation_20260712.md)，从与 NO0296 相同的 SimTop pre-reg-to-mem checkpoint 重新执行 reg-to-mem、activity-schedule、C++ emission、O3 编译和 emu 链接：

```text
build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim
```

本次 Python editable package 在 fresh flow 中重新构建和安装，生成器不是旧进程或旧扩展。新 emu SHA256 为：

```text
c30220ac6f7601a261e2aec4eccbf2191af100a8a16de77a6deb87267d159078
```

## 2. Fresh 结构检查

reg-to-mem 和 activity-schedule 的图结构与 NO0296 完全一致：

| Metric | NO0296 | NO0300 |
| --- | ---: | ---: |
| graph ops | 7,204,108 | 7,204,108 |
| supernodes | 63,726 | 63,726 |
| compute supernodes | 63,241 | 63,241 |
| commit supernodes | 485 | 485 |
| DAG edges | 528,622 | 528,622 |
| boundary values | 1,000,463 | 1,000,463 |
| boundary activation edges | 1,983,923 | 1,983,923 |
| compute-compute value pairs | 1,721,698 | 1,721,698 |
| compute-commit value pairs | 262,225 | 262,225 |
| `commit_ops_max` | 42,937 | 42,937 |

因此本轮只改变 ordered memory-write 的 C++ 表达，不改变 lowering、分区、拓扑或 activation contract。

fresh C++ 中只命中预期的三个 RAT group：

| Batch | State | Writers | Affine ranges | Generated loops |
| --- | --- | ---: | ---: | ---: |
| `sched_90` | `fpRat.difftest_table` | 511 | 1 | 1 |
| `sched_90` | `intRat.difftest_table` | 511 | 1 | 1 |
| `sched_104` | `vecRat.difftest_table` | 520 | 2 | 2 |

vecRat 的前 511 个 writers 形成一个 range，剩余 9 个 writers 因 slot 走势不同形成第二个 range。全目录仅有上述 3 个 affine group、4 个循环；其他 ordered 或普通 writes 均走既有路径。

## 3. 生成代码体积

| Metric | NO0296 unrolled | NO0300 affine | Delta |
| --- | ---: | ---: | ---: |
| generated `.cpp + .hpp` bytes | 1,379,649,713 | 1,377,946,849 | -1,702,864 (-0.123%) |
| `sched_90.cpp` bytes | 3,970,358 | 2,851,479 | -28.18% |
| `sched_104.cpp` bytes | 3,830,350 | 3,246,365 | -15.25% |
| `sched_90.o + sched_104.o` bytes | 534,552 | 448,008 | -86,544 (-16.19%) |
| emu `.text` bytes | 88,272,265 | 88,185,721 | -86,544 (-0.098%) |

1.70 MB 的源码缩减全部来自 `sched_90/104`，最终 `.text` 减量也与两个对象文件的合计减量相同。全 emu 百分比很小，不能据此推断 runtime 收益；本轮目标是移除 NO0298 定位到的 1,542 个稀疏、前端不友好的直接 guard。

## 4. SimTop 功能门禁

使用 CoreMark 两迭代镜像和 NEMU difftest，分别执行 10k 与 50k 仿真周期：

| Limit | Guest cycles | `cycleCnt` | `instrCnt` | Terminal PC | Result |
| ---: | ---: | ---: | ---: | --- | --- |
| 10,000 | 10,001 | 9,996 | 458 | `0x800027c6` | PASS |
| 50,000 | 50,001 | 49,996 | 73,580 | `0x80001312` | PASS |

两次均正常到达 cycle limit，没有 assertion、abort 或 difftest mismatch，且终点与 NO0296 完全一致。未固定 CPU 的 Host time 分别为 `10,430 ms` 与 `83,128 ms`，仅作为完整执行记录，不作为性能结论。

日志：

```text
build/logs/xs/xs_wolf_grhsim_build_no0300_ordered_affine_fresh_20260712.log
build/logs/xs/xs_wolf_grhsim_no0300_ordered_affine_functional_10k_20260712.log
build/logs/xs/xs_wolf_grhsim_no0300_ordered_affine_functional_50k_20260712.log
```

## 5. 结论与下一步

fresh 结构与 10k/50k 功能门禁通过，仿射循环没有改变 SimTop 可观察行为。下一步先检查机器与 CPU 138/330 的负载，再采用 NO0296 unrolled / NO0300 affine / NO0296 unrolled 的固定 CPU 相邻 50k 配对，直接判断 NO0298 的 runtime 退化恢复了多少；之后再与 NO0286 比较整体净收益。
