# NO0228 xs-components 单模型 perf 对比与 2x work 迹象（2026-07-09）

## 1. 背景

`NO0222`-`NO0227` 用小负载直接对比 GSIM / GrhSIM 生成 C++ 与 perf 热点后，已经确认：

- generic `grhsim_*_words<N>` 的 runtime width / tail / out-of-line call 是真实慢点；
- full-width helper 与 `always_inline` 可把 `VtypeBuffer` / `FTQ` / `Tage` 的 GrhSIM runtime 明显拉低；
- 但在 `NO0226` 后，`XsReal075RobVtypebufferLarge` 仍约为 GSIM 的 `~2.0x`。

此前 xs-components bench 默认在同一进程中先跑 GSIM、再跑 GrhSIM。为了让 perf stat/report 不被另一套模型的构造、reset、符号与缓存行为干扰，本轮给 bench 增加单模型选择能力，并用同一二进制分别采样 GSIM / GrhSIM。

## 2. Harness 改动

文件：`testcase/xs-components/tb/xs_component_bench.hpp`

新增命令行参数：

```text
--model both|gsim|grhsim
```

口径：

- 默认仍为 `both`，不改变既有 `make run ...` 行为；
- `--model gsim` 只构造、reset、运行、dump GSIM；
- `--model grhsim` 只构造、init/reset、运行、dump GrhSIM；
- `--verify 0` 时不再先构造两边做 cross-model verify，而是打印 `vectors=0 status=pass`，便于单模型 perf 长窗口；
- 运行时新增 `[MODEL] top=... selection=...` 行，方便日志确认口径。

## 3. 构建与基础验证

构建目录：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/
```

日志目录：

```text
tmp/no0228_model_select_perf_20260709/
```

默认 `both` 口径重建并跑 `VtypeBuffer`：

```bash
make -C testcase/xs-components one CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0228_model_select_perf_20260709/raw_bench \
  BENCH_VECTORS=200000 BENCH_VERIFY=2048 BENCH_REPEAT=3
```

结果：

| model | vectors | min ms | median ms | checksum |
|---|---:|---:|---:|---|
| GSIM | 200002 | 206.247 | 206.330 | `0xa6ff99241ea2cc48` |
| GrhSIM | 200002 | 410.359 | 412.331 | `0xa6ff99241ea2cc48` |

静态 objdump stats：

| model | instructions | text size bytes |
|---|---:|---:|
| GSIM | 11047 | 50133 |
| GrhSIM | 12922 | 61243 |

单模型 smoke：

```bash
XsReal075RobVtypebufferLarge_bench --vectors 1000 --verify 0 --repeat 1 --model gsim
XsReal075RobVtypebufferLarge_bench --vectors 1000 --verify 0 --repeat 1 --model grhsim
```

两边 checksum 均为：

```text
0xee9cecd35b7b67e5
```

## 4. 单模型 perf stat 长窗口

命令口径：

```bash
perf stat -e cycles,instructions,branches,branch-misses,duration_time,user_time,system_time \
  XsReal075RobVtypebufferLarge_bench --vectors 2000000 --verify 0 --repeat 1 --model gsim

perf stat -e cycles,instructions,branches,branch-misses,duration_time,user_time,system_time \
  XsReal075RobVtypebufferLarge_bench --vectors 2000000 --verify 0 --repeat 1 --model grhsim
```

注意：这里的 `cycles` 是 host CPU perf counter；bench 输出中的 `vectors=2000002` 是输入向量数量。对这个 xs-component harness 来说，每个向量会调用一次 `eval_gsim()` 或一次 `eval_grhsim()`；其中 `eval_grhsim()` 内部包含 `clock=false` / `clock=true` 两次 `dut.eval()`。

| metric | GSIM | GrhSIM | GrhSIM / GSIM |
|---|---:|---:|---:|
| bench ms | 2079.119 | 4128.859 | 1.986x |
| host cycles | 15,457,228,518 | 30,501,229,021 | 1.973x |
| retired instructions | 40,364,368,177 | 81,649,329,326 | 2.023x |
| IPC | 2.61 | 2.68 | 1.025x |
| branches | 2,113,979,360 | 1,550,922,752 | 0.734x |
| branch misses | 113,283,265 | 123,028,264 | 1.086x |
| branch miss rate | 5.36% | 7.93% | - |
| host cycles / vector | 7728.6 | 15250.6 | 1.973x |
| instructions / vector | 20182.2 | 40824.6 | 2.023x |

## 5. perf report 热点

GSIM top symbols：

| self | symbol |
|---:|---|
| 68.44% | `SXsReal075RobVtypebufferLarge::subStep0()` |
| 26.53% | `SXsReal075RobVtypebufferLarge::subStep1()` |
| 1.58% | bench loop |
| 1.46% | `get_io$$out1()` |
| 1.03% | `eval_gsim(...)` |

GrhSIM top symbols：

| self | symbol |
|---:|---|
| 43.26% | `GrhSIM_XsReal075RobVtypebufferLarge::eval_compute_batch_3()` |
| 16.69% | `eval_compute_batch_1()` |
| 14.44% | `eval_compute_batch_2()` |
| 11.56% | `eval_commit_batch_4()` |
| 10.77% | `eval_compute_batch_0()` |
| 2.73% | `eval()` |

与 `NO0225` / `NO0226` 不同，当前 perf top 中已经没有明显的 `grhsim_*_words_full<16>` out-of-line helper self；这符合 `_full` helper `always_inline` 后的预期。剩余热点几乎全部落在 batch 级生成代码里。

## 6. 生成代码形态观察

GrhSIM `eval()` 的关键形态：

```cpp
if (!initial_eval && ((clock != prev_in_clock))) {
    pending_eval_round = true;
}
...
while (pending_eval_round) {
    pending_eval_round = false;
    this->eval_compute_batch_0();
    this->eval_compute_batch_1();
    this->eval_compute_batch_2();
    this->eval_compute_batch_3();
    commit_activated_readers_ = false;
    this->eval_commit_batch_4();
    pending_eval_round = commit_activated_readers_ || grhsim_any_active_flags(supernode_active_curr_);
    event_edge_slots_[0] = grhsim_event_edge_kind::none;
}
```

而 bench 侧 GrhSIM 每个输入向量执行：

```cpp
drive_grhsim(dut, in);
dut.clock = false;
dut.eval();
Outputs out = sample_grhsim(dut);
dut.clock = true;
dut.eval();
```

因此当前证据链更像是：

1. GrhSIM 已经消除了主要 out-of-line 宽字 helper 自身热点；
2. 但每个输入向量仍退休约 `2.02x` 指令；
3. IPC 并没有变差，GrhSIM 甚至略高；
4. 所以 `VtypeBuffer` 剩余 `~2x` runtime gap 的主因更可能是执行工作量本身接近 `2x`，而不是 host pipeline 效率、单个 helper call 或代码体积单独导致。

这与 “GrhSIM 一个向量中包含 low-clock eval + high-clock eval 两次 direct schedule 固定点求值，而 GSIM 由 `step()` 包装 `subStep0/subStep1`” 的结构差异高度吻合。但目前还不能简单下结论说 low/high 两次成本各占 50%，因为：

- high-clock eval 负责 posedge commit，commit 后可能激活 reader 并触发下一轮 compute；
- low-clock eval 负责输入变化后的组合传播；
- 当前 perf 只能看到 batch 总 self，尚不能区分同一个 batch 是在 low-clock eval、high-clock eval 的第一轮，还是 commit 激活后的后续 fixed-point round 中消耗。

## 7. 结论

本轮单模型 perf 把 `VtypeBuffer` 剩余差距从“宽字 helper / 代码形态混合嫌疑”进一步收敛为：

> 在 `NO0226` always-inline full-width helper 之后，`VtypeBuffer` GrhSIM 相对 GSIM 的剩余 `~2.0x` slowdown 与 `~2.0x` retired instructions / host cycles 高度一致；CPU 执行效率不是主矛盾，主矛盾是 GrhSIM 每个输入向量执行的 batch/schedule 工作总量约为 GSIM 的两倍。

## 8. 下一步

下一步不宜先做大改，而应先补 phase 级证据：

1. 给 xs-component bench 增加可选 GrhSIM phase timing / counter，分别统计每个向量的 `clock=false eval` 与 `clock=true eval` 耗时；
2. 若可低侵入拿到 GrhSIM 内部信息，再统计每次 eval 的 fixed-point round 数、active flag 非空次数、commit 激活次数；
3. 用 phase 数据判断：
   - 是否存在 clock-only eval 中大批 compute batch 空转；
   - 是否 high-clock commit 后的 compute round 是主要成本；
   - 是否可以安全做 event/active-aware batch skip，或需要先调整 bench / simulator step 语义。

只有 phase 级证据坐实后，才继续评估具体优化，例如 empty-compute-round skip、posedge commit/compute 调度融合、或更深层的 wide-lane scalarization。
