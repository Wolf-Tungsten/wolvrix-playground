# TNO0155 Stage 7+ current-baseline rebuild and formal gate interruption

日期：2026-07-19

状态：在父仓库 `1ed4154`、`wolvrix` 子模块 `f17e90e` 的同一提交上，重新生成了
current C++ default control 和三个已经存在的 Stage7+ 候选。生成、O3、link、功能输入
staging 均完成；正式 walltime 只启动了 `dp_p050` 的第一轮 16 个样本，其中只有 N0
`BAAB` 是完整 accepted order。其余样本被 runtime whole-node monitor 拒绝，不能用于
性能结论。随后整节点 survey 再次失败，`dp_p200`、`fanin_strict` 和 Stage33 strict
尚未启动新的 formal run。没有根据不完整数据改变任何 C++ 默认选项。

本文只记录已经存在的候选和测试收尾，不引入新的 activity-schedule 优化。

## 1. Baseline and option boundary

唯一 A 是同提交 fresh current C++ default，基线语义为 NO0300、ASLR 关闭。emit 前清除
`WOLVRIX_XS_GRHSIM_*`、`WOLVRIX_GRHSIM_*`、`GRHSIM_*` 和 `EMU_RUNTIME_PROFILE`，只保留
任务需要的输入和固定 `max_op_in_compute_supernode=108`、batch `2048/8192/64`、
`emit_parallelism=4`。运行时使用 `setarch x86_64 -R`；不把 XS 脚本中的临时参数当作默认。

候选只改变显式参数：

| variant | explicit change |
| --- | --- |
| `dp_p050` | `WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM=500000` |
| `dp_p200` | `WOLVRIX_XS_GRHSIM_DP_SEGMENT_PENALTY_PPM=2000000` |
| `fanin_strict` | `final_fanin_pullback_policy=strict`, `max_node_ops=8`, `max_width=64`, `min_gain=3`, `max_moves=4096`, `max_moved_op_ppm=5000` |

## 2. Static and build results

Control absolute activity values are `63709/63241/468` supernodes (total/compute/commit),
`527990` DAG edges, `1000463` boundary values, `1983326` boundary activation edges, and
`1721698/261628` compute/commit value pairs. The control source/header set is `134` files,
`1356643748 B`; archive is `99249366 B`; linked ELF is `93671816 B` (`.text=87095345`,
`.rodata=5647080`, `.eh_frame=706144`, `.data=152`, `.bss=14688`). See
[`TNO0154`](./TNO0154_stage33_fresh_same_commit_default_control_20260719.md) for the control
input hashes and logs.

Candidate absolute structure and artifact values:

| variant | SN total/compute/commit | DAG | boundary values | BAE | compute/commit pairs | source bytes | archive bytes | ELF `.text` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control | 63709/63241/468 | 527990 | 1000463 | 1983326 | 1721698/261628 | 1356643748 | 99249366 | 87095345 |
| `dp_p050` | 63886/63418/468 | 528385 | 1000466 | 1983149 | 1721521/261628 | 1356397381 | 99223180 | 87056984 |
| `dp_p200` | 63566/63098/468 | 527876 | 1000471 | 1983608 | 1721980/261628 | 1356717225 | 99210272 | 87046629 |
| `fanin_strict` | 63709/63241/468 | 527990 | 1000537 | 1983072 | 1721444/261628 | 1356632706 | 99263020 | 87104849 |

`fanin_strict` selected/applied `84/84` entries, moved `262` operations, and reported actual
BAE gain `254`; its validators were all true. The three candidate activity stats are distinct
raw files, while the emitter stats are identical to control (`sha256=
9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`, `418 B`).

Artifact log hashes:

```text
dp_p050 emit 273f2123493234381ec8916ce6df4bd44c60e90a4888f2060175c09575782f98 14290 B
dp_p050 O3   863cc281766c4abb206684b8f5fa42c0ee1cadd4f576b5741ef5c54bfb31eff7 24897 B
dp_p050 link cf0980314714b099be4979ccebd457a8af54440c183ac6505ecea9bbc56366cb 7006 B
dp_p050 emu  77fdfdfb04f3b6d9ade3fdc48797aa0b6de7be26b556ab8eca177e4b44cee4f4 93626032 B

dp_p200 emit 1d03174a84762a6fac3fffa46b3ba3af2ab2c0b65798bb44c60e3342393e16d2 14292 B
dp_p200 O3   f9d056d65c4b85829cda08815ec904f19d0de526e2dd27b7fdd0c7204e025d6f 24897 B
dp_p200 link ad4210d54813503e87b5afd4871aab957bfe4ef6d0f70c9d010e4f0e444d906d 7006 B
dp_p200 emu  24fecd9d1ad863d3a7f608375b94e8d3fb23b96ed76f682539a5a2d9c527e9b4 93622648 B

fanin emit 1eddbee39a68e3c96dd55f8c2c893871f66865b0c2cb9915aa398bdd16a62e2e 15372 B
fanin O3   09063c9d24cfbf5a83f8c9ff152135c508179e3297c9698c6f06efb8aeb2dc6d 24912 B
fanin link b0fa4fcea3ba50a5b66e10504d32417584727560fe5234cf2020bebd0d48bdb4 7021 B
fanin emu  8b83aaa14178c82ced1bb02abe2d1f55b85a132f71f29f1d8e5240d9d75a2aa2 93680088 B
```

All emit/O3/link commands exited zero. The corresponding raw logs are under
`build/logs/xs/stage7plus_retest_current_20260719/`.

## 3. NUMA staging and runtime command

Each order/node/variant received a distinct `/dev/shm` inode: 20 emu, 20 CoreMark and 20 NEMU
files. The copy operation first-touched pages on the target node:

```text
N0: taskset -c 43  numactl --physcpubind=43  --membind=0 cp --reflink=never SRC TMP
N1: taskset -c 139 numactl --physcpubind=139 --membind=1 cp --reflink=never SRC TMP
```

The formal runner then used:

```text
taskset -c CPU numactl --physcpubind=CPU --membind=node perf stat ... -- \
  setarch x86_64 -R emu -i coremark.bin --diff nemu.so -b 0 -e 0 -C 50000
```

Placement and affinity gates passed for every started `dp_p050` sample. The runner observed
N0 local pages `emu=21260`, `nemu=115` and the mirrored N1 placement, with zero remote pages;
the ASLR probe was `00040000`.

The fresh pre-run survey preceding the first attempt was already marginal but recorded for
audit: N0 `count=192 mean=99.516302% min=98.13% target=99.83% sibling=99.80%`, N1
`count=192 mean=99.544896% min=97.10% target=99.27% sibling=99.90%`.

## 4. `dp_p050` formal walltime records

The only headline metric is the unique positive model line `Host time spent: N ms` from each
50k log. A row is usable only when every runner gate is one, including the 191-CPU runtime
monitor. The raw result files are under
`build/logs/xs_perf/stage7plus_retest_current_20260719/formal/dp_p050/`.

| node/order | A walltimes (ms) | B walltimes (ms) | rejected row(s) | order status |
| --- | ---: | ---: | --- | --- |
| N0 ABBA | 74414, 74200 | 74521, 74245 | A2 monitor `mean=98.340%, min=71.990%` | invalid |
| N0 BAAB | 74219, 74073 | 74132, 74117 | none | valid |
| N1 ABBA | 74253, 74190 | 74321, 74237 | B1 monitor `mean=98.937%, min=80.790%` | invalid |
| N1 BAAB | 74108, 74445 | 74190, 74519 | A2 monitor `mean=96.643%, min=84.520%` | invalid |

For the sole complete order, A mean is `74146.0 ms`, B mean is `74124.5 ms`, delta
`-21.5 ms` (`-0.028996844%`). This is not a dual-NUMA balanced result and is insufficient to
promote or reject `dp_p050`. The rejected rows retain their walltime values for traceability,
but are excluded from all averages and decisions.

## 5. Second quiet-window survey and interruption

After the rejected samples, a new 30-second whole-node survey was run with the same `mpstat`
scope. It failed both nodes:

```text
N0 count=192 mean_idle=99.107031% min_idle=80.930000% target=99.900000% sibling=99.930000%
N1 count=192 mean_idle=97.380885% min_idle=0.000000% target=99.200000% sibling=99.500000%
N0 raw sha256=fa0d51a0a7c5ec3edbee6f0ff5801c5728a32e70f7c54fc7b1277b662d6083b3
N1 raw sha256=209ea91be5e68a95bbd75a1bd1c953f752f83282c8030bc17875ab66fbf5df0d
```

The low samples corresponded to an unrelated externally owned vector `emu` process whose
threads occupied CPU285 and CPUs288--291. It was not terminated or otherwise modified. Since
the whole-node gate is a hard admission rule, no `dp_p200`, `fanin_strict`, or Stage33 strict
formal run was started in this contaminated window.

## 6. Decision and stopping boundary

The static reductions are useful diagnostics but do not override walltime. Because there is no
complete dual-NUMA balanced walltime set, all three Stage7+ candidates remain explicit,
default-off experiments; the current C++ default and NO0300 baseline are unchanged. The
partial `dp_p050` N0 BAAB result is recorded, not promoted. No cycles, instructions, ELF size,
BAE, or rejected walltime is used as the end-to-end performance criterion.

The remaining formal runs are an environment-gated continuation only: rerun the existing
`strict`, `dp_p050`, `dp_p200`, and `fanin_strict` ABBA/BAAB groups after a fresh survey passes,
using new `/dev/shm` staging roots. No new optimization candidate should be added before the
next instruction.

## 7. 增量更新：single-NUMA representative closure

根据 NUMA 对称性审计，后续正式口径改为只用 N0 作为代表节点；N1 的已有样本和 survey
仍保留作交叉验证，不再为了补齐 N1 追加运行。N0/N1 的绑核是镜像的（N0 `43/235`、
N1 `139/331`），复制和运行均使用 `taskset` 加 `numactl --physcpubind/--membind`，
`numa_maps` 显示目标页全在本地。TNO0149 的两轮 survey 还出现过 N0/N1 PASS/FAIL
互换，证明差异来自可迁移外部 workload 窗口而不是 NUMA 拓扑；本轮 attempt3/4/5 的
双节点 survey 也同时通过。运行期间再次观察到外部 `emu` 线程跨 CPU/NUMA 迁移，故不
放宽 runtime gate。

本轮通过的双节点 survey 原始绝对值如下（每节点 `count=192`）：

| survey | N0 mean/min/target/sibling idle | N1 mean/min/target/sibling idle | N0 raw SHA | N1 raw SHA |
| --- | ---: | ---: | --- | --- |
| attempt3 | `99.530365/98.13/99.53/100.00%` | `99.439115/95.86/99.37/99.63%` | `ae6c254ccb92c04219a540e7c44bf00ace5ee0f16ac305d7f6530dace9d4287d` | `1fc825f4d9c6d7e96f6a762472a948ee5f8047f0ad3e5227eb2d20dc2b4d18a6` |
| attempt4 | `99.752604/98.56/99.83/99.93%` | `99.770208/96.77/99.93/100.00%` | `8936062b4e0b7d9f6bb606f23db2e6858402bd4f5a31ce9321ed4e37cc96c74c` | `64ce2cbce4a744c9a78609af737830700149e27ef11ef58f55957f6f6be3f304` |
| attempt5 | `99.709531/98.86/99.47/99.83%` | `99.801563/96.77/99.70/99.87%` | `c15c81e6773b43892b0fe46d958e91c09645a328fe1c90f0cba1cfc3f36dc796` | `23466e01c68bdbbafb8875699f655b5f1815de2f3ede5608668861dbc71882a4` |

四个既有候选均完成了 fresh N0 `ABBA`（A、B、A、B）四样本，所有 runner gate=1。以下
是唯一使用的端到端 headline：`Host time spent` walltime（单位 ms）。

| variant | A1/A2 | B1/B2 | A mean | B mean | B-A | change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage33 `strict` | 74387/74713 | 74223/74344 | 74550.0 | 74283.5 | -266.5 | -0.357478203% |
| `dp_p050` | 74796/74411 | 74714/74360 | 74603.5 | 74537.0 | -66.5 | -0.089137909% |
| `dp_p200` | 74325/74398 | 74420/74556 | 74361.5 | 74488.0 | +126.5 | +0.170114912% |
| `fanin_strict` | 74382/74320 | 74109/74114 | 74351.0 | 74111.5 | -239.5 | -0.322120752% |

Raw result directories and aggregate result-file hashes are:

```text
strict      formal_attempt3/strict/n0/abba      e502430fab5f4f25349d198aabb97a0687b9d1e0e1301729d26d4d5f5a414b90
dp_p050     formal_attempt3/dp_p050/n0/abba     9a08188ac23437c68f09a4f6dfc485fe7019bbee85fd95ac08e96c39f8f7d962
dp_p200     formal_attempt4/dp_p200/n0/abba     cced5684bd082bd46d712ec560db98cc701c70748e6157aafac1b5dc3b29c81c
fanin_strict formal_attempt4/fanin_strict/n0/abba a1eaeecd614d7c08531041db19a2c0b4fc41546397d802c51b229de4fc43a3e0
```

BAAB was attempted only to check order sensitivity, but no candidate obtained a complete
accepted N0 order in the available windows:

```text
strict      a2=74466 ms, monitor min=61.480%; retry b2=74485 ms, min=38.960%; retry b2=74589 ms, min=94.420%
dp_p050     a1=74416 ms, min=91.890%
dp_p200     b2=74462 ms, min=91.970%
fanin_strict b2=74417 ms, min=86.050%
```

These rows are rejected evidence, not performance samples. A later N1-only survey during an
external run also failed with `mean=96.020833%`, `min=0.000000%`; it was not used to substitute
an easier but contaminated node. Therefore the ABBA values above are a representative
single-NUMA indication, not a claim of a complete ABBA+BAAB confidence interval.

The final N0-only admission immediately before the last strict retry was
`count=192 mean=99.450990% min=97.390000% target=99.070000% sibling=99.670000%`;
its raw `mpstat` SHA256 is
`65ae03d08f48398dfd44910213303c811230fa8d834820f41527503bcde14cc0`.
The retry still encountered an externally owned `emu` before its final B2 monitor sample,
which is why the hard gate remains the stopping boundary rather than a relaxed threshold.

## 8. Single-NUMA decision

The ABBA indication is positive for `strict` and `fanin_strict`, near-neutral for `dp_p050`,
and negative for `dp_p200`, but the missing accepted BAAB order prevents a robust adoption
decision. Accordingly all four remain explicit experiments: C++ defaults stay unchanged
(`same_batch_activation_cohort=strict` off, DP penalty cpp-default, and fanin pullback off).
No cycles, instructions, BAE, DAG, ELF size, or rejected walltime is promoted over the walltime
criterion. This closes the current test-and-document phase; no new optimization or further
formal retry is scheduled without a new instruction and a quiet-window decision.
