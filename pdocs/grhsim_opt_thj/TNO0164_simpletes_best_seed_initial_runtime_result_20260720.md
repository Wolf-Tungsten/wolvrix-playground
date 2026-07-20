# TNO0164 SimpleTES best-seed initial runtime result

记录日期：2026-07-20

状态：continuation instance `4269c986` 的初始 best seed 已完成 strict attribution、
fixed-ASLR/NUMA/PMU/function gate，以及 ABBA screen 和 BAAB promotion。候选是功能正确且
可归因的 valid candidate，但端到端 walltime 为负向，因此不保留为默认配置；instance 已
继续进入 generation worker。

启动、输入快照与空闲 CCD retry 见
[TNO0162](./TNO0162_simpletes_best_seed_continuation_launch_20260720.md) 和
[TNO0163](./TNO0163_simpletes_quiet_ccd_retry_and_rebuild_audit_20260720.md)。

## 1. Gate completion

第二次 evaluator attempt 在第一次 quiet-CCD retry 后完成了同一 seed 的全套构建。enabled
focused tests 为 `24 passed`；100-cycle 为 `190 ms`，10,000-cycle 为 `9,405 ms`，均通过。
candidate 没有重新运行 XiangShan `sim-verilog`，control/candidate generation-input manifest
仍为 `2,103` 文件、fingerprint
`e9ca0efd737dcc0b7a7e145059fce052fd5729abe34df43d8e4b10e1a84154ab`。

runtime 的两个 order 都通过：

```text
ASLR personality       00040000 / setarch -R: PASS
process affinity       single expected CPU, zero migration: PASS
NUMA binary and NEMU   local_ratio 1.0: PASS
PMU scheduled          100% / task clock 1.0: PASS
functional signature   all 8 samples: PASS
```

ABBA screen 使用 node0 CCD `56-63,248-255`、target CPU `74`；BAAB promotion 使用 node0
CCD `56-63,248-255`、target CPU `56`。两组的 whole-CCD pre-gate、15-CPU monitor 和
gate-to-run gap 均通过；CPU 选择由 runtime 动态发现，未手工放宽空闲阈值。

## 2. Absolute walltime

SimTop 50k headline 是每个 emu log 的 `Host time spent`，单位为毫秒：

| order | role | sample 1 | sample 2 | arithmetic mean | range |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | control | `74,005` | `74,128` | `74,066.50` | `123` |
| ABBA | candidate | `73,905` | `73,808` | `73,856.50` | `97` |
| BAAB | control | `71,725` | `71,315` | `71,520.00` | `410` |
| BAAB | candidate | `73,433` | `72,369` | `72,901.00` | `1,064` |
| combined | control | `74,005/74,128/71,725/71,315` |  | `72,793.25` | `2,813` |
| combined | candidate | `73,905/73,808/73,433/72,369` |  | `73,378.75` | `1,536` |

相对结果为：

```text
candidate - control       +585.50 ms
relative walltime         +0.804332819% (candidate slower)
combined score             0.9920208507
ABBA screen                73,856.50 vs 74,066.50 ms  (-210.00 ms, -0.2835%)
BAAB promotion             72,901.00 vs 71,520.00 ms  (+1,381.00 ms, +1.9306%)
```

ABBA 的单边正向被 BAAB 反向样本否定，不能作为性能收益。combined control spread 已为
`2,813 ms`（`3.864369292%`），candidate spread 为 `1,536 ms`；因此即使方向相反，也不
满足把该 patch 晋升默认的可信条件。

## 3. PMU and generated-work signal

runtime 同时保留了每个 sample 的 perf CSV 和结构化 PMU 审计。四组 arithmetic mean 如下，
用于解释候选为何不能仅凭 ABBA 的 walltime 采用：

| order | role | instructions | cycles | backend stalls | frontend no-ops |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | control | `164,220,565,069` | `271,299,277,731` | `89,853,965,378` | `1,240,775,438,896` |
| ABBA | candidate | `162,191,372,611` | `270,637,603,478` | `88,905,533,666` | `1,240,449,958,209` |
| BAAB | control | `164,220,562,207` | `262,224,753,695` | `87,227,521,039` | `1,189,568,427,344` |
| BAAB | candidate | `162,191,371,768` | `267,128,991,950` | `88,556,812,367` | `1,219,527,159,028` |

candidate instruction count 在两个 order 都约少 `1.23565%`，但 BAAB cycles、backend stalls
和 frontend no-ops 均上升，且 walltime 回退。这再次说明静态 generated work/单 order PMU
下降不能替代端到端 walltime 裁决。

## 4. Decision and continuation

该 seed 的 `valid_candidate=1` 只表示它通过功能、归因和 runtime integrity gate，不表示
性能正向。由于 combined walltime `73,378.75 ms` 高于 control `72,793.25 ms`，保持
`active_mask_gap_pack_policy=targeted-table-contiguous` 的候选 patch 不进入 wolvrix 默认，
也不复制到父仓库 source。

run log 已记录：

```text
Initial score: 0.992021
Starting 1 gen workers and 1 eval workers
```

SimpleTES 继续使用本轮 `16 proposals / 8 valid` fresh budget 搜索；后续新候选仍需同样的
default-off fingerprint、enabled functional 和 ABBA→BAAB walltime gate。当前文档只对初始
seed 作决定，后续 generation 结果另立 TNO。
