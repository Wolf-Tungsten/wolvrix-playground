# NO0355 Single-writer state-read direct-forward implementation gate

日期：2026-07-12

## 1. Implementation

按 [NO0354](./NO0354_single_writer_state_read_direct_forward_plan_20260712.md)，在 `wolvrix` commit
`0a065df` 中实现默认关闭的 single-writer scalar register-read direct forwarding：

```text
emit attribute: direct_single_writer_state_reads=1
environment:    WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
default:        0
```

实现不按 SimTop、`timer` 或 `logEndpoint` 名称特判。每个 read 必须满足 single-result scalar register、全图恰好
一个 write port、materialized/tracked/boundary、非 output/inout/event/waveform/packed/reg-to-mem，且全部 users 都是其他
compute supernodes，user active-ID 集合与 boundary fanout 精确一致。

同一 materialized slot 的 canonical/alias group 采用 all-or-none eligibility。通过后：

1. consumer 表达式直接引用 visible state storage；
2. read source 不再生成 slot compare/store、changed predicate、alias OR 或 boundary activation；
3. state commit frontier 加入 direct consumers；仅当同一 state/source supernode 的所有 reads 都已直连时，才移除原
   source head；
4. 初始化继续依赖首次 `eval()` 激活全部 compute，后续只在 commit 确认 visible state 真正变化后激活 direct
   consumers；
5. runtime-profile source/ASucc 权重、line estimator、deferred-activation 建组和 storage-ref alias 收集同步排除 direct
   reads。

第一阶段仍保留已经分配但不再引用的 persistent value slots，避免将 storage layout 回收与调度语义改写混在同一门禁。

## 2. Repeated-read alias gate

复用已有 repeated scalar state-read design，并分别以默认关闭和开启直连 fresh emit。该用例经 schedule split 后有
`17` 个 `repeated_q` reads：`15` 个 boundary reads、一个 public-output protected read、一个与 system-task consumer
同 supernode 的 local read。15 个候选分布在 pure 和 mixed source supernodes 中。

开启后的 emitter 统计为：

```text
reads                 15
canonical               4
aliases                11
canonical groups         4
source groups            4
removed source heads     4
unique consumer heads    1
```

结构检查结果：

```text
                                      default   direct
generated schedule bytes               14,769    9,553
direct markers                              0       15
grhsim_changed occurrences                 19        0
same-state alias changed-predicate ORs      11        0
residual protected/local reads               2        2
```

即 4 个 canonical 与 11 个 aliases 整组直连，protected/local 两条路径保留；mixed source 中与 read 无关的 op 仍保留。
两版 harness 都验证初值 `3`、posedge 写入 `9` 和后续可见值，均返回 `0`。

## 3. Single/protected/multi-writer gate

新增第二个 generated design，同时包含：

- single-writer `direct_q`，read 经过独立 add consumer；
- single-writer `protected_q`，read 直接绑定 public output；
- two-writer `multi_q`，read 经过独立 add consumer。

emitter 只选择 `direct_q`：

```text
reads=1 canonical=1 aliases=0 groups=1
source_groups=1 removed_source_heads=1 consumer_heads=1
```

generated C++ 中 `direct_q` consumer 直接读取 `state_logic_storage_`，read source 没有 changed/slot update；
`protected_q` 与 `multi_q` 保持原 materialized path。harness 覆盖：

```text
initial values
changed posedge writes
same-value posedge writes
later changed writes
second multi_q writer priority/path
```

所有输出均符合预期，harness 返回 `0`。same-value write 不会错误激活或改变 downstream 输出。

## 4. Regression

所有命令均先执行 `source env.sh`。最终门禁：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j32
ctest --test-dir wolvrix/build --output-on-failure -R '^emit-grhsim-cpp$'

1/1 Test #11: emit-grhsim-cpp ... Passed 168.79 sec
100% tests passed, 0 tests failed
```

`git diff --check` 通过。默认关闭路径同时跑过原 repeated-read alias 结构检查和全部既有 generated-model cases，因此本次
实现尚未改变默认 SimTop 代码生成。

## 5. Next gate

下一步从 NO0300 的 pre-reg-to-mem checkpoint fresh emit SimTop，只额外开启
`WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1`：

1. 记录实际 reads/canonical/aliases/source-head/consumer-head 数量，并与 NO0353 的 `75,830` rows 上界对照；
2. 检查 supernode 7804 的 boundary read 扫描是否消失、local `NSamples`/`Sum` 与 `kDiv` 是否保留；
3. 编译 emu，先执行短功能与 difftest 门禁；
4. 功能正确后才在检查机器负载的前提下做 fixed CPU/NUMA/ASLR 的 baseline/new/baseline 性能夹测。

本篇只证明通用实现及 synthetic 语义成立，不宣称 SimTop 已提速。
