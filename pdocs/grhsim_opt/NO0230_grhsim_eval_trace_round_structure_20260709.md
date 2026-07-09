# NO0230 GrhSIM eval trace 启用与 VtypeBuffer round 结构（2026-07-09）

## 1. 背景

`NO0229` 用 bench 外层 phase timing 发现：`XsReal075RobVtypebufferLarge` 的 GrhSIM `clock=false eval` 与 `clock=true eval` 耗时几乎各占一半。但这只能说明 high phase 不便宜，不能回答 high phase 内部到底是 commit 自身贵，还是 commit 激活 reader 后又跑了一轮 compute。

阅读 `wolvrix/lib/emit/grhsim_cpp.cpp` 后发现 GrhSIM emitter 已经有 `perf=eval` 路径，可生成 eval/round/batch trace：

- 运行时环境变量 `GRHSIM_TRACE_EVAL=1` 打开 trace；
- 或 `GRHSIM_TRACE_EVAL_EVERY=N` 每 N 次 eval 打印一次；
- trace 内容包括每个 eval 的 round 数、`active_in`、`touched_writes`、`commit_activated`、batch/commit timing 等。

但 xs-components flow 之前无法打开该路径，且 `perf=eval` 生成代码存在一个未暴露的编译问题。

## 2. 代码增量

保留的诊断性改动：

1. `testcase/xs-components/scripts/emit_grhsim.py`
   - 新增 `--perf off|eval` 参数；
   - 默认仍为 `off`；
   - 传给 `sess.emit_grhsim_cpp(..., perf=args.perf)`。
2. `testcase/xs-components/Makefile`
   - 新增 `GRHSIM_PERF ?= off`；
   - emit GrhSIM 时传 `--perf $(GRHSIM_PERF)`。
3. `wolvrix/lib/emit/grhsim_cpp.cpp`
   - 修复 `perf=eval` 下多个 batch 在同一 `eval()` scope 中重复生成 `const auto batch_begin_time` / `batch_elapsed_us` 的问题；
   - 改为按 batch index 生成唯一局部变量名，例如 `batch_begin_time_3`、`batch_elapsed_us_3`。

默认 `GRHSIM_PERF=off`，因此普通 benchmark / emit 输出不受 trace 代码影响。

## 3. 构建验证

由于当前 shell 没有安装 editable `wolvrix` 包，fresh emit 需要显式指定 Python binding 路径：

```bash
PYTHONPATH=$PWD/wolvrix/build/skbuild/python:$PWD/wolvrix/app/pybind \
make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0230_eval_trace_20260709/perf_eval \
  GRHSIM_PERF=eval BENCH_VECTORS=1000 BENCH_VERIFY=128 BENCH_REPEAT=1
```

`perf=eval` trace 版 smoke 结果：

| model | vectors | ms | checksum |
|---|---:|---:|---|
| GSIM | 1002 | 1.040 | `0xee9cecd35b7b67e5` |
| GrhSIM | 1002 | 1.963 | `0xee9cecd35b7b67e5` |

trace 版 objdump stats：

| model | instructions | text size bytes |
|---|---:|---:|
| GSIM | 11047 | 50133 |
| GrhSIM perf=eval | 13589 | 64608 |

说明：`perf=eval` 会增加 trace / counter 代码体积，因此只用于诊断，不作为性能数。

## 4. Eval trace 实测

命令：

```bash
GRHSIM_TRACE_EVAL=1 \
XsReal075RobVtypebufferLarge_bench \
  --vectors 4 --verify 0 --repeat 1 --model grhsim
```

bench 输出：

```text
[VERIFY] top=XsReal075RobVtypebufferLarge vectors=0 status=pass
[MODEL] top=XsReal075RobVtypebufferLarge selection=grhsim
[BENCH] model=grhsim top=XsReal075RobVtypebufferLarge vectors=6 repeat=1 ms=3.012 checksum=0x42d29e93605fc60b
```

解析完整 trace：

| scope | evals | total rounds | commit activated rounds | touched writes | executed batches | round histogram |
|---|---:|---:|---:|---:|---:|---|
| reset | 3 | 4 | 1 | 112 | 20 | `{1: 2, 2: 1}` |
| warmup | 12 | 16 | 5 | 339 | 80 | `{0: 1, 1: 6, 2: 5}` |
| measured | 12 | 17 | 5 | 336 | 85 | `{1: 7, 2: 5}` |

其中 measured 部分的 12 次 eval 对应 6 个输入向量，每个向量 low/high 各一次：

| phase | evals | rounds | executed batches | touched writes | commit activated rounds | peak active sum |
|---|---:|---:|---:|---:|---:|---:|
| low (`clock=false`) | 6 | 6 | 30 | 0 | 0 | 41 |
| high (`clock=true`) | 6 | 11 | 55 | 336 | 5 | 113 |

逐 eval 摘要：

```text
low : #16 r=1 peak=7  writes=0  commit_activated=0 batches=5
high: #17 r=1 peak=0  writes=0  commit_activated=0 batches=5
low : #18 r=1 peak=6  writes=0  commit_activated=0 batches=5
high: #19 r=2 peak=17 writes=15 commit_activated=1 batches=10
low : #20 r=1 peak=7  writes=0  commit_activated=0 batches=5
high: #21 r=2 peak=26 writes=69 commit_activated=1 batches=10
low : #22 r=1 peak=7  writes=0  commit_activated=0 batches=5
high: #23 r=2 peak=22 writes=79 commit_activated=1 batches=10
low : #24 r=1 peak=7  writes=0  commit_activated=0 batches=5
high: #25 r=2 peak=26 writes=87 commit_activated=1 batches=10
low : #26 r=1 peak=7  writes=0  commit_activated=0 batches=5
high: #27 r=2 peak=22 writes=86 commit_activated=1 batches=10
```

## 5. 结论

这次 round trace 解释了 `NO0229` 的 low/high 50/50 现象：

- low phase 通常是输入变化驱动的 1 个 compute round；
- high phase 通常先以 `active_in=0` 进入 clock/event round，执行 posedge commit；
- commit touch write 后会设置 `commit_activated=1` 并激活 reader；
- 随后 high phase 进入第 2 个 round，消费 commit 激活出来的 active compute；
- 因此 high phase 不是单纯 clock-only 空转，而是 `commit + commit-activated compute` 的组合。

这进一步支持主线判断：`VtypeBuffer` 剩余慢点与 GrhSIM 的两阶段 eval / fixed-point round 结构强相关，而不是单个宽字 helper 的残余问题。

## 6. 后续约束

直接优化方向应从“跳过显然空的 batch 调用”开始做 A/B，但预期收益可能有限，因为 high phase 的主要成本可能在 commit 后的 active compute，而非第一轮 `active_in=0` 的空 compute batch 调用。该 A/B 已另见 `NO0231`。
