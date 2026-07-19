# TNO0150 Stage 33 strict implementation, manifest, and focused gate

日期：2026-07-19

状态：`same_batch_activation_cohort_policy=strict` 已完成 C++ default-off 实现，并通过
跨 active word 的 generated-source、default/strict 功能 harness、Python/native 与 XS sparse
option focused gate；完整 emitter 也已通过。SimTop production emit/O3/50k 与 full CTest 尚未
包含在本文，不能从 focused fixture 直接声称端到端收益。

## 1. Option ownership

policy 扩展为：

```text
same_batch_activation_cohort_policy = off | probe | strict
same_batch_activation_cohort_profile_path = <current 50k fire TSV>
```

C++ 默认仍是 `off`。native/Python 接受显式 `strict` 并继续拒绝空串、`targeted` 等非法值；
XS 只读取并稀疏转发显式环境变量，未设置时仍打印/使用 `cpp-default`，没有为 XiangShan 在
脚本里创建第二套默认。

focused 结果：

| gate | absolute result |
| --- | ---: |
| same-batch cohort CTest | `1/1 PASS`, `13.37 s` |
| cohort + deferred focused CTest | `2/2 PASS`, `13.77 s` |
| full emitter CTest | `1/1 PASS`, `294.45 s` |
| Python/native option tests | `17/17 PASS` |
| XS sparse option tests | `28/28 PASS` |

最终 focused raw logs 保存在
`build/logs/xs/stage33_same_batch_cohort_strict_20260719/`：

```text
focused_ctest_final.log sha256=6292bf7c6ec16650006a3de9c05928da6ad848169269a35f447462bf332d8270 bytes=450
python_options_final.log sha256=64e97fef4d71b60dbc333f1c83173aafdf2158e11c065edb202d68f0be8bd0a4 bytes=116
xs_options_final.log sha256=9baad65f53342377750c000afc07192fe736418770f80d66d0c945af9b2e8102 bytes=127
```

## 2. Production manifest v2

独立 review 指出 v1 把 source Value、owner SN 与 batch 分成三个集合，不能证明逐 source
对应关系。v1 FNV `4437fba0c9c6b932` 因此作废，没有进入 production 常量。v2 对每个
source 按 source ValueId 顺序编码完整 tuple：

```text
magic, version=2, cohort_count
每 cohort:
  ordinal, batch, source_count
  每 source:
    graph.index, graph.generation, value.index, value.generation,
    owner_supernode, owner_batch, owner_current_profile_fire
  cohort_profile_fire, member_count
  每 member: supernode, active_id, op_count, profile_fire
尾部:
  selected cohorts/members/ops,
  control/projected BAE,
  control/projected entries,
  control/projected chunks
```

所有 field 都以 8-byte little-endian 输入 FNV-1a64，offset=`14695981039346656037`、
prime=`1099511628211`。独立 oracle 与 emitter expected-zero scan 的 v2 结果闭合为：

```text
expected FNV-1a64 = 2221bbc3ffd74a71
canonical u64     = 15030
canonical bytes   = 120240
canonical SHA256  = 1c1cd30e30b45ded5aae02957e87ddfad4d91facbb630517a93681ccfd871624
```

manifest absolute coverage：

| field | value |
| --- | ---: |
| cohorts | `252` |
| source tuples | `1,450 / 1,450` covered |
| source-member pairs / control BAE | `3,619` |
| members / resolved active IDs | `902 / 902` |
| ops | `88,334` |
| projected BAE | `1,450` |
| control/projected entries | `342 / 252` |
| control/projected chunks | `257 / 252` |
| tuple validation errors | `0` |

owner fire 的 min/max/sum/unique 为 `1 / 100,105 / 14,723,320 / 207`。pinned cohort11 的
tuple 是 graph `1:0`、Value `1539803:0`、owner SN6969/batch7/owner fire19175。生产
`SimTop` strict 任一 tuple、顺序、绝对总数或 FNV 不符都 fail-closed；generic fixture 不使用
SimTop 常量，但仍执行结构 validator。

原始 oracle 继续使用 [Stage32 current-profile replay](./TNO0147_stage32_current_profile_replay_and_log_audit_20260719.md)
log、current cohort TSV 和 current fire TSV，
其 SHA 分别为
`5b9ce6dc7b362a54d2fccd56a1d4a09e469c39bec08d7e5cbb410e5d0c7b8175`、
`21b3f250b4919ea8414f7c5f2040232f3c9455f82f31581b653c0ab4999b60d0`、
`308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a`；Stage32 static row
stream SHA 仍为
`5ac64b74cb51d947b5c9c8da422d95ed55a007395be5aac804bbeae4503e3b3b`。

v2 oracle 已持久化并可复跑：
`build/logs/xs_perf/stage33_same_batch_cohort_strict_20260719/manifest_oracle.py`
（SHA `49233cb9adb447fa7407eafdd335363344f7abe8ba64db0e8631658443aa07f6`，bytes `22413`）
及其 raw 输出 `manifest_oracle.log`（SHA
`c684d90c919aa078fa2d66a6077e51c38b9e9bd457839adb13a98983e0a5d8a9`，bytes `2408`）。
log 中 `validation_errors=0`，保留全部输入 SHA、absolute totals、canonical stream
的 bytes/SHA 和 FNV；`120240`-byte stream 本身不另行落盘，而是由上述脚本从已
固定输入确定性重建。

## 3. Strict overlay

scan 完成且 production manifest 通过后，strict 两阶段构造 overlay：

1. 验证 cohort/member 不重叠、leader 不为 follower、active ID 与 batch word 一致、无
   helper/split、无 input/state/memory follower writer；full-active-word consume 必须关闭。
2. 对每个 source fanout 保留 leader、删除所有 follower，并要求每条原 fanout恰好出现一次；
   最后全图 sweep 证明没有任何 follower active ID 残留。
3. ordinary initial compute seed 删除 follower；原 dispatch/clear mask 保留，word load 后清除
   residual follower bits，避免异常残留造成 fixed-point 不终止。
4. direct changed propagation、deferred group 构造与 `DeferredActivationEmitContext` 统一使用
   strict fanout；deferred flush 不能重新写回 follower。
5. ordinary leader 单 guard 后按原 cohort SN/active/op 顺序执行全部 payload；原 follower
   位置不再生成 guard/body。fullpass 仍走原逐 SN 路径，commit 不变。
6. leader word 使用真实 `activeWordFlags`。跨 word 时为每个后续原 word 建立从 0 开始的独立
   accumulator，每个 payload 保留自己的 `currentActiveId/currentWordIndex`，离开 word 时
   `global |= accumulator`。这样不覆盖已有 pending，也不把 propagation 写回 leader byte。

strict 不编译 Stage32 cohort counter/header/reset/dump；scan log 明确
`emit_mutation=strict_overlay no_mutation=false`，不再把 strict 误写成 no-mutation probe。

## 4. Two-cohort focused fixture

fixture 有 24 个 compute SN，同一 active word 内有两个独立 cohort：SN/active ID `8..12` 和
`14..18`。前者留在 word1，后者从 word1 跨到 word2；source fanout control=`10`、strict=`2`。
SN18 的输出继续激活下游 SN19，确保跨 word accumulator 不是只生成但始终为 0。

strict generated source 绝对证据：

```text
leader guards=2
follower payloads=8
original follower guards=0
source ordinary mask=word1 bits1+64 (`UINT8_C(65)`)
word2 accumulator initial=0
SN18 changed propagation=accumulator bit8
word2 accumulator OR-store=1
initial masks: word0=255, word1=97, word2=248
cohort runtime counter references=0
```

default 与 strict archive 分别运行同一 harness：初始化输入3、无变化 eval、输入9、无变化
eval、输入17；每一步同时检查 cohort outputs8..12、14..18 和 downstream output19。两套均
PASS，因此 first seed、input change、unchanged eval、两个 leader/follower payload 与跨 word
same-round later propagation 都有实际功能覆盖。另有 `full_active_word_consume=true` strict
入口负向 gate，确认在 lowering 前 fail-closed。

生成源码/header 绝对大小：

| variant | files | bytes |
| --- | ---: | ---: |
| default | `13` | `107,947` |
| explicit off | `13` | `107,947` |
| probe | `13` | `153,805` |
| strict | `13` | `107,287` |

default/off 的 artifact map byte-identical。strict header 仍为
`kRuntimeProfileCompiled=false`；大小仅为 fixture 边界，不用于预测 SimTop walltime。

该 focused fixture 没有把 strict 与 posedge/fullpass 正向路径或 forced helper/split 变体组合在
同一 harness 中；production strict 对 full-active、helper/split 和非 boundary follower 均有
独立 fail-closed validator，既有 fullpass/helper 测试继续作为邻接覆盖。

## 5. 后续 gate

1. 完整 emitter 与 full CTest；只允许既有 transform 失败集合。
2. final editable binding reinstall 后，用 current profile 进行 fresh pinned SimTop strict emit；
   核对 FNV、252/902/88,334、BAE3,619→1,450、activity schedule identity 和无 counter。
3. O3/archive、独立 emu link、page-local fixed-ASLR 100/10k/50k 功能。
4. fresh same-commit default control 与 strict 做 whole-node gate 下的双 NUMA balanced walltime；
   唯一 headline 是 50k `Host time spent`。
