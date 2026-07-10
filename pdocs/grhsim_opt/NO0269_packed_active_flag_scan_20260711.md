# NO0269 Packed active-flag scan

日期：2026-07-11

## 目标与根因

承接 [NO0268](./NO0268_wide_bit_replicate_broadcast_fastpath_20260711.md) 的 post-profile，分析
`GrhSIM_SimTop::eval()` 占用约 `10.53%` sampled branches 的原因。`perf annotate` 显示该符号内
约 `95.55%` 的 sample 落在 `grhsim_any_active_flags()` 被内联后的逐字节扫描：它从
`supernode_active_curr_` 首字节一直检查到末尾，每个 inactive byte 都产生一次 compare/branch。

SimTop 当前 activity bitmap 约 `8.8 KiB`，且 fixed-point eval 经常需要确认整个 bitmap 为空，
因此这个通用 helper 在 50k 仿真中约产生 `1.99B` branches。该成本与 RTL 计算无关，是 GrhSIM
调度框架额外引入的空集判定；GSim 的 `step()` 直接调用静态 `subStep` 序列，没有对应的全图
byte scan。

## 实现

把 `grhsim_any_active_flags()` 改为 packed scan：

1. 主循环每次用 `memcpy` 读取四个 `uint64_t`，一次检查 32 bytes；
2. 剩余部分先按 8 bytes 检查，再处理最多 7 个 tail bytes；
3. GCC/Clang 下在 load 后加入 empty inline-asm register barrier，防止优化器重新生成逐字节
   early-exit loop；其他编译器保留相同语义的标准 C++ 路径；
4. 不改变 activity bitmap 布局、fixed-point 顺序或 active bit 的产生/清除逻辑。

emitter 测试同时检查 32-byte loop、8-byte tail、四 word OR 与 barrier 均出现在生成 runtime 中。

## Synthetic gate

所有构建和测试均先执行 `source env.sh`。最终 emitter build 与测试结果：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j8
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

`emit-grhsim-cpp` 通过，用时 `149.72s`。日志：

```text
build/logs/xs_perf/no0269/wolvrix_build_emit_grhsim_cpp_final_20260711.log
build/logs/xs_perf/no0269/ctest_emit_grhsim_cpp_final_20260711.log
```

## Fresh build gate

最初只重建了 CMake test library，没有重装 SimTop emit 脚本实际加载的 editable Python binding；
因此 `build/xs_grhsim_no0269_packed_active_scan_20260711` 仍含旧 byte loop，该产物明确排除，
不进入任何结论。随后执行：

```text
source env.sh
python3 -m pip install --no-build-isolation -e wolvrix
```

安装日志为 `build/logs/xs_perf/no0269/pip_install_editable_20260711.log`。重装后 fresh emit 复用
与 NO0268 相同的 pre-reg-to-mem checkpoint，参数保持
`compute=108, commit=4096, target_batches=64`。新产物：

```text
build/xs_grhsim_no0269_packed_active_scan_fresh_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_emit_no0269_packed_active_scan_fresh_20260711.log
build/logs/xs/xs_wolf_grhsim_compile_no0269_packed_active_scan_fresh_20260711.log
```

activity-schedule SHA256 与 NO0268 完全一致：

```text
3b2b756238a82fafd862df09e75e454f3f6586b1df5da2d38b641d8f313e6400
```

除 runtime helper 所在文件外，其余生成 `.cpp/.hpp` 均 hash-identical。O3 executable `.text`
仅从 `106787143` 增至 `106787223`（`+80 bytes`）。反汇编确认 `eval()` 已变成每轮四次 qword
load、四 word OR 和 32-byte stride，旧 byte loop 不再存在。

## SimTop functional gate

| run | Guest cycles | instrCnt | cycleCnt | mismatch / ABORT |
| --- | ---: | ---: | ---: | ---: |
| 10k | `10001` | `458` | `9996` | `0 / 0` |
| paired 50k runs | `50001` | `73580` | `49996` | `0 / 0` |

10k 日志：

```text
build/logs/xs/xs_wolf_grhsim_no0269_packed_active_scan_fresh_10k_20260711.log
```

## CPU140 old/new/old

测试时系统 load 约 `114~147/384`。为隔离共享机器波动，三次完整 50k 均固定 CPU 140，
同时检查 SMT sibling CPU 332，并用旧版 NO0268 在新版前后各跑一次。四个 perf events 均为
`100%` scheduled，三个 run 的 guest/功能统计完全一致。

| run | Host time | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0268 old 1 | `123736ms` | `435254667142` | `204892643618` | `18857760640` | `7729410974` |
| packed scan | `103140ms` | `366243299520` | `199863006370` | `17134785555` | `7727047398` |
| NO0268 old 2 | `124424ms` | `445014339775` | `204892650571` | `18857786490` | `7726469635` |

以两次 old 均值为 baseline：

| metric | old mean | packed scan | delta |
| --- | ---: | ---: | ---: |
| Host time | `124080.0ms` | `103140ms` | `-16.8762%` |
| cycles | `440134503458.5` | `366243299520` | `-16.7883%` |
| instructions | `204892647094.5` | `199863006370` | `-2.4548%` |
| branches | `18857773565` | `17134785555` | `-9.1368%` |
| branch misses | `7727940304.5` | `7727047398` | `-0.0116%` |
| IPC | `0.465523` | `0.545711` | `+17.2243%` |
| guest cycles/s | `402.966` | `484.778` | `+20.3025%` |

性能日志：

```text
build/logs/xs_perf/no0269/old_no0268_cpu140_50k_run1.log
build/logs/xs_perf/no0269/old_no0268_cpu140_50k_run1_perf_stat.csv
build/logs/xs_perf/no0269/packed_active_scan_cpu140_50k.log
build/logs/xs_perf/no0269/packed_active_scan_cpu140_50k_perf_stat.csv
build/logs/xs_perf/no0269/old_no0268_cpu140_50k_run2.log
build/logs/xs_perf/no0269/old_no0268_cpu140_50k_run2_perf_stat.csv
```

instructions 只减少 `2.45%`，但移除的是一个长依赖链上的高频 taken/not-taken control flow；IPC 提升
`17.22%`，使 cycles 与 Host time 都稳定下降约 `16.8%`。绝对 branch misses 基本不变，说明收益
来自减少前端分支压力和缩短空集判定，而不是修复 branch prediction miss。

## Post-profile

新版 50k branch profile 使用与 NO0268 相同的 `branches:u, period=1500000, dwarf 8192`，得到
`11421` samples、lost `0`，近似 `17.1315B` branches。按列出符号聚合：

| class | NO0268 | packed scan |
| --- | ---: | ---: |
| compute batches | `36.93%` | `41.84%` |
| commit batches | `49.90%` | `54.38%` |
| eval control | `10.53%` | `0.74%` |
| other listed symbols | `2.39%` | `2.80%` |

`eval()` 的绝对 branches 由约 `1.985B` 降至约 `0.127B`，减少约 `93.6%`。占比上升的
compute/commit 是旧热点移除后的归一化结果；新的前三个热点为：

| symbol | share |
| --- | ---: |
| `eval_commit_batch_122()` | `12.75%` |
| `eval_commit_batch_108()` | `5.96%` |
| `eval_commit_batch_86()` | `1.99%` |

profile 产物：

```text
build/logs/xs_perf/no0269/packed_active_scan_simtop_50k_branches.data
build/logs/xs_perf/no0269/packed_active_scan_simtop_50k_branches_run.log
build/logs/xs_perf/no0269/packed_active_scan_simtop_50k_branches_flat.report
build/logs/xs_perf/no0269/packed_active_scan_simtop_50k_branches_symbols.report
build/logs/xs_perf/no0269/packed_active_scan_simtop_50k_eval_annotate.report
```

## 结论与下一步

packed active scan 通过 synthetic 与完整 SimTop 功能 gate，在共享机器上通过同 CPU old/new/old
配对确认 Host time `-16.88%`，应保留。它消除了 GrhSIM 相对 GSim 特有的一项全图调度成本，
但没有减少 branch misses。

下一步转向 `commit_batch_122/108`。初步源码对照显示 GrhSIM 对每个 scalar state write 使用
`if (state != next)`，其中 batch122 含 `42937` 个 writes，50k 下约执行 `2.15B` 次比较；GSim
对应 register update 使用 branchless changed-mask accumulation。后续应先做 generated assembly/source
归因，再用小范围 branchless commit 或分组 activation probe 验证，不能直接全局改写 commit 语义。
