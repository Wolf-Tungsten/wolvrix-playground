# NO0229 VtypeBuffer GrhSIM low/high eval phase timing（2026-07-09）

## 1. 背景

`NO0228` 用单模型 perf stat 确认：在 `NO0226` 的 `_full` 宽字 helper `always_inline` 之后，`XsReal075RobVtypebufferLarge` GrhSIM 相对 GSIM 的剩余 runtime gap 约为 `1.99x`，同时 retired instructions 约为 `2.02x`、host cycles 约为 `1.97x`、IPC 基本不差。

这说明剩余慢点更像是 GrhSIM 每个输入向量执行了约两倍工作。为了验证这个 `2x work` 是否确实来自 xs-component harness 中的 GrhSIM `clock=false` / `clock=true` 两次 `eval()`，本轮增加默认关闭的 phase timing。

## 2. Harness 增量改动

文件：`testcase/xs-components/tb/xs_component_bench.hpp`

新增参数：

```text
--grhsim-phase-profile
```

实现口径：

- 默认关闭，不影响普通 `both` / `gsim` / `grhsim` benchmark；
- 只在 GrhSIM benchmark 中生效；
- `run_benchmark()` warmup 之后清零统计，避免预热污染；
- 对正式 repeat 中每个向量拆分累计：
  - `drive_ns`：写 GrhSIM 输入；
  - `low_eval_ns`：`clock=false; dut.eval()`；
  - `sample_ns`：采样输出；
  - `high_eval_ns`：`clock=true; dut.eval()`。

注意：该模式每个向量增加多次 `steady_clock::now()` 调用，会放大绝对 runtime；本轮只看 low/high 比例，不把 phase-profile 模式的 wall time 当作无插桩性能数。

## 3. 构建与 smoke

复用 `NO0228` 构建目录：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/
```

重编译 bench 并跑 10k 默认 both smoke：

```bash
make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0228_model_select_perf_20260709/raw_bench \
  BENCH_VECTORS=10000 BENCH_VERIFY=256 BENCH_REPEAT=1
```

结果：

| model | vectors | ms | checksum |
|---|---:|---:|---|
| GSIM | 10002 | 10.264 | `0xc57bb1d60f748a01` |
| GrhSIM | 10002 | 20.341 | `0xc57bb1d60f748a01` |

## 4. Phase timing 实测

命令：

```bash
XsReal075RobVtypebufferLarge_bench \
  --vectors 200000 --verify 0 --repeat 3 \
  --model grhsim --grhsim-phase-profile
```

输出：

```text
[BENCH_RUN] model=grhsim run=0 vectors=200002 ms=436.669 checksum=0x7d62abe96844fe00
[BENCH_RUN] model=grhsim run=1 vectors=200002 ms=446.261 checksum=0xa9ae1139ddc5feed
[BENCH_RUN] model=grhsim run=2 vectors=200002 ms=435.939 checksum=0xa6ff99241ea2cc48
[BENCH] model=grhsim vectors=200002 repeat=3 ms=435.939 median_ms=436.669 checksum=0xa6ff99241ea2cc48
[GRHSIM_PHASE] vectors=600006 measured_ms=1257.400 drive_ms=14.962 low_eval_ms=616.420 high_eval_ms=610.960 sample_ms=15.058 low_eval_pct_of_eval=50.22 high_eval_pct_of_eval=49.78 low_eval_ns_per_vector=1027.4 high_eval_ns_per_vector=1018.3
```

整理：

| metric | value |
|---|---:|
| measured vectors | 600006 |
| drive ms | 14.962 |
| low eval ms | 616.420 |
| high eval ms | 610.960 |
| sample ms | 15.058 |
| low share of eval | 50.22% |
| high share of eval | 49.78% |
| low ns/vector | 1027.4 |
| high ns/vector | 1018.3 |

## 5. 结论

这次 phase timing 支持 `NO0228` 的判断，并把它进一步细化为：

> `VtypeBuffer` 当前 GrhSIM 每个输入向量中的 `clock=false eval` 与 `clock=true eval` 消耗几乎相同，二者合计构成了剩余 `~2x` work 的直接表现。

因此，不能再把主因理解成单个 `_full` 宽字 helper 或某一个 batch 的局部 out-of-line call。`clock=true` 阶段并不是可以忽略的纯空转；它和 low phase 一样昂贵，说明 posedge commit、commit 后 reader 激活、或 high phase 中的 fixed-point compute round 都可能在执行大量真实工作。

## 6. 对优化方向的影响

本轮结果对后续方向有两个约束：

1. **简单跳过 clock-only compute round 可能不足。** 如果 high phase 的成本接近 low phase，那么 high phase 很可能不只是“clock 变了但 active flags 为空”的批量空调用；必须先看 high eval 内部 fixed-point round 与 commit 激活情况。
2. **下一步应做 eval 内部 round 级统计。** 需要进一步区分：
   - low eval round 数、active flag 非空次数、各 batch 是否实际触发；
   - high eval 第一轮 compute 是否空转；
   - commit batch 是否激活 reader 并导致后续 compute round；
   - 每个 phase 中 compute / commit batch 的触发次数与耗时。

只有拿到 round 级数据后，才能判断优化应落在：

- event/active-aware batch skip；
- posedge commit 与后续 compute round 的调度融合；
- 减少 commit 后 activation fanout；
- 或继续做宽字 lane scalarization / producer fusion。
