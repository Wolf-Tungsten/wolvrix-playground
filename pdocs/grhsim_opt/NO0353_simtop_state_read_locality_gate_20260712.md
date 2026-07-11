# NO0353 SimTop state-read locality gate

日期：2026-07-12

## 1. Fresh emit gate

按 [NO0350](./NO0350_state_read_boundary_locality_diagnostic_plan_20260712.md) 和
[NO0352](./NO0352_state_read_locality_read_args_correction_20260712.md)，从 NO0300 使用的同一
pre-reg-to-mem checkpoint fresh emit，只额外开启默认关闭的 `state_read_locality_stats=1`：

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
read args:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
  SHA256 bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
ordered writes:             1
decoded write storage:      1
final topo:                 level-id
compute node/supernode max: 108
batch target:               64
emit parallelism:           4
```

所有命令均先执行 `source env.sh`。fresh emit 结果：

```text
reg-to-mem true groups       835
graph ops                    7,204,108
eligible ops                 6,990,363
source clones                2,045,861
compute supernodes           63,241
commit supernodes            485
total supernodes             63,726
DAG edges                    528,622
boundary values              1,000,463
boundary activation edges    1,983,923
state-read activation edges  84,972
total emit time              396.622 s
```

这些结构计数与 NO0300 一致。两边 154 个 `grhsim_SimTop*.cpp/.hpp` 文件逐文件 SHA256 完全相同，证明 locality
诊断没有改变 schedule、storage layout 或生成代码。

诊断输出：

```text
build/xs_grhsim_no0352_state_read_locality_20260712/grhsim/grhsim_emit/grhsim_state_read_locality.tsv
rows   924,826
size   164,694,496 bytes
SHA256 238fac1f81c28b2be7dfdacc2fac9f91dd7ae8f487380bdeba7a9948a147ae5e
```

## 2. Dynamic join

将每个静态 read row 与 NO0311 的 NO0300 CoreMark 50k `supernode_fire` 按 source supernode ID 连接。所有
`42,976` 个 source supernode 均找到 fire count；下文的 dynamic visit 是
`静态 row 数 * source supernode fire count`，表示当前生成直线代码实际执行该 read row 的次数，不是 perf 抽样。

```text
all state-read visits                  13,672,673,345
materialized read visits                2,828,265,235
canonical materialized visits           1,216,110,981

pure-read-supernode canonical visits      172,642,702   14.196%
strict pure-forward canonical visits      142,953,826   11.755%
mixed-supernode canonical visits         1,043,468,279   85.804%

batch 8 canonical visits                1,000,216,097   82.249%
logEndpoint canonical visits             1,016,190,646   83.561%
timer canonical visits                      27,251,090    2.241%
```

因此，只有整个 supernode 都是 state read 时才绕过该 supernode，最多覆盖约 `11.76%` canonical visits，不能解决
主项。主要开销在 mixed supernode 内，必须允许逐 read 直连并保留同 supernode 的其他计算。

## 3. Single-writer direct-forward upper bound

从生成 commit C++ 的 `kRegisterWritePort`/`kLatchWritePort` 注释统计每个 state symbol 的写端口数。`timer` 和全部
`logEndpoint$...` 共 `30,937` 个状态，每个都恰好只有一个写端口。没有按信号名放宽条件；候选 read 必须同时满足：

```text
kRegisterReadPort
scalar and materialized
tracked_change and boundary_fanout > 0
no same-supernode user
no unscheduled user
unique scheduled user supernodes == boundary fanout
state has exactly one write port
```

最后一项先排除多写端口在同一次 commit 中发生中间变化、最终值不变时的过早激活。user/fanout 等式排除 commit
consumer 和无法由 compute active flag 完整表达的用户。实现时还必须沿用 emitter 的 public output、event、waveform、
packed lane 等 protected-value 判定；因此这里是严格结构候选的动态上界，不是已经通过功能门禁的结果。

```text
eligible rows                         75,830
eligible source supernodes             1,333
eligible canonical rows               40,108
eligible alias rows                   35,722
eligible materialized visits       2,751,685,542   97.292% of all materialized visits
eligible canonical visits          1,139,531,288   93.703% of all canonical visits
eligible alias visits              1,612,154,254

batch 8 eligible canonical visits    999,892,679   99.968% of batch 8 canonical visits
                                                     82.221% of all canonical visits
```

候选只涉及 `3.10%` 的 source supernodes，却覆盖 `93.70%` 的 canonical dynamic visits，说明开销高度集中在少量
高频 mixed supernodes 中。

## 4. Concrete mixed-supernode case

NO0352 的 `grhsim_SimTop_sched_8.cpp` 中，supernode 7804：

```text
static ops                 108
state reads                106
logEndpoint reads           53
timer reads                 53
materialized reads         104
canonical materializations  52
same-state aliases          52
same-supernode local users   2
50k fire count          50,002
```

其中 51 个 boundary-only `logEndpoint` read 各自执行 slot compare/store；53 个 `timer` read 共享一个 canonical
slot，但 52 个 alias 仍逐项把同一个 changed predicate OR 到聚合 flag。只有 `NSamples` 和 `Sum` 的两个本地 read
直接从 state storage 参与尾部 `kDiv`。高频 `timer` 将整个 mixed supernode 激活约每 guest cycle 一次，于是与它同组的
大量无关 `logEndpoint` 状态也被反复扫描。

## 5. GSim comparison

同一状态 `logEndpoint__DOT__ifu2ibuffer_validCnt_20_21` 在 GSim 的 `SimTop20.cpp` 中没有经过独立 state-read
中转层。GSim 在状态写回处：

1. 保存 state old value；
2. 将 `$NEXT` 写回 state；
3. 直接比较 state old/new；
4. 用该 change predicate 直接置两个 downstream `activeFlags`。

对应的 `$NEXT` 组合更新也在 `SimTop294.cpp` 中直接置 state-write substep 的 active flag。也就是说，GSim 将
state change 与 downstream activation 连接在写入点；GrhSIM 当前多出“state write -> state-read source supernode ->
materialized slot compare/alias OR -> downstream activation”这一层。NO0349 中 GSim 的函数局部 `$old` 并非没有
change detection，而是没有 GrhSIM 这层大规模持久化 read slot 和聚合扫描。

## 6. Conclusion and next gate

根因候选已经从“compute 8 较慢”收敛为可操作的代码生成差异：高频状态与大量其他 state reads 被打包进 mixed
supernode，导致每次状态变化都执行宽扫描；现有 alias 优化只合并 storage/compare，没有消除 alias OR 和同组扫描。

下一步先做独立实现计划，逐项确认：

- single-writer state 在 commit 中得到最终 change predicate 的位置；
- commit 后直接置 compute consumer active flag 是否跨 cycle 保留；
- 初始化 fullpass 与 direct state expression 的等价性；
- 如何从 source supernode 的 state-head activation 中移除已直连 read，同时保留本地 read 和其他计算；
- synthetic 覆盖 single/multi-writer、mixed supernode、alias、初始化和不变写回。

通过结构和 synthetic 功能门禁后再 fresh emit SimTop；未通过前不据此宣称性能改善。
