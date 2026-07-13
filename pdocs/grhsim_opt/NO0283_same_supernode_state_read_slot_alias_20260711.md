# NO0283 Same-supernode state-read slot alias

日期：2026-07-11

## 1. 目标与约束

[NO0282](./NO0282_same_fir_instructions_profile_compute8_timer_fanout_20260711.md) 将最大
instruction hotspot 定位到 compute8 的 `timer`/`logEndpoint` cloned state reads。本轮只合并
满足以下不变量的持久 value slot：

- read op 位于同一个最终 compute supernode；
- 读取同一个 register/latch state，类型、宽度和 signedness 一致；
- result 为 scalar logic、已 materialize 且有 compute boundary fanout；
- 排除 event、waveform、public output/inout、packed-array lane 和 reg-to-mem bypass value。

同 supernode 内这些 read 必然一起执行，期间不存在 commit write，因此结果值始终相同。本轮不
改变 activity schedule、supernode DAG 或 state-reader activation。

## 2. 实现

emitter 为每组建立 `alias result -> canonical result`：

1. `rebuildMaterializedValueStorage()` 只为 canonical result 分配一个 typed slot，并让所有 alias
   的 `valueFieldByValue`/`valueScalarSlotByValue` 指向同一位置；
2. supernode-local storage-ref lookup 先 canonicalize value，避免为同一槽位生成多份局部引用；
3. canonical read 生成 changed comparison 和 slot write；alias read 复用 changed predicate，仍逐个
   保留原 `boundaryFanout` effects，但跳过重复 slot write；
4. `WOLVRIX_GRHSIM_STATE_READ_SLOT_ALIASES=0` 可恢复同一版生成器的旧行为，默认启用。

这与曾导致激活面扩大的 state-read tail absorb 不同：consumer 仍由原 value fanout 激活，不直接
挂到 state write，也不移动 read op 或改变拓扑。

## 3. 小设计 gate

扩展现有 repeated scalar state-read emitter test。测试在 `maxOpInComputeSupernode=4` 下把 16 个
同状态 cloned read 分到 4 个最终 supernode：

- alias 前需要 16 个 cloned read slots；
- alias 后每个 supernode 只保留 1 个，共 4 个 slots；
- generated C++ 明确包含 `reuse consolidated storage slot`；
- 完整 harness 编译、运行通过，覆盖状态不变和 posedge 更新后的输出。

验证命令均先执行 `source env.sh`：

```text
cmake --build wolvrix/build -j8 --target emit-grhsim-cpp
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

CTest 用时 143.91s，通过。

## 4. SimTop 结构结果

从 NO0278 相同的 pre-reg-to-mem checkpoint fresh 恢复。reg-to-mem 与 activity-schedule 统计逐项
一致：`832` 个 true groups、`67934` 个 supernodes、`638649` 条 DAG edges、
`2044602` 个 source clones。

emitter 找到 `711` 个同 state/supernode group，合并 `35745` 个 slots。分布高度集中在 NO0282
的目标热点：

| generated batch | aliased slots |
| --- | ---: |
| sched8 | `29197` |
| sched7 | `2870` |
| sched6 | `2113` |
| sched1 | `713` |
| sched2 | `373` |
| sched4 | `287` |
| sched0 and others | `192` |

typed scalar slot 变化为：

| kind | NO0278 | NO0283 | delta |
| --- | ---: | ---: | ---: |
| bool | `815553` | `813015` | `-2538` |
| u8 | `234657` | `234212` | `-445` |
| u16 | `26402` | `26344` | `-58` |
| u32 | `8626` | `8573` | `-53` |
| u64 | `141838` | `109187` | `-32651` (`-23.02%`) |
| total | `1227076` | `1191331` | `-35745` (`-2.91%`) |

代码与二进制变化：

| metric | NO0278 | NO0283 | delta |
| --- | ---: | ---: | ---: |
| generated `.cpp` bytes | `1487326148` | `1485974119` | `-1352029` (`-0.09%`) |
| sched8 source bytes | `34153438` | `33171233` | `-982205` |
| sched8 function text | `1363199` | `1153296` | `-209903` (`-15.40%`) |
| full emu `.text` | `103032693` | `102595917` | `-436776` (`-0.42%`) |

## 5. SimTop 功能 gate

CoreMark + NEMU difftest 均无 mismatch/abort：

| gate | Guest cycles | instrCnt | cycleCnt | terminal PC |
| --- | ---: | ---: | ---: | --- |
| 10k | `10001` | `458` | `9996` | `0x800027c6` |
| 50k | `50001` | `73580` | `49996` | `0x80001312` |

## 6. CPU138 old/new/old 50k gate

运行前机器为 384 logical CPUs，load average `25.97/33.75/21.27`（包含刚结束的并行编译），
CPU138 连续三秒 `99%~100%` idle。三次 perf event 均为 `100%` scheduled：

| run | Host time | cycles:u | instructions:u |
| --- | ---: | ---: | ---: |
| NO0278 old 1 | `83233ms` | `304719282343` | `190435678281` |
| NO0283 slot alias | `82597ms` | `302315977644` | `188789374509` |
| NO0278 old 2 | `83159ms` | `304338725191` | `190435693881` |

相对两次 old 均值：

- Host time `-0.72%`；
- cycles `-0.73%`；
- instructions `-0.86%`，约减少 `1.646B`。

随后独立复测 NO0283 得到 `82339ms / 301361407554 cycles / 188789156631 instructions`，
instructions 与首次候选只差 `0.0001%`，收益方向复现。

## 7. 结论

1. 同最终 supernode 的 cloned state-read results 可以安全共用一个物化槽，功能与激活关系保持。
2. 优化精确命中 compute8：该函数 text 缩小 `15.40%`，SimTop instructions 稳定下降 `0.86%`。
3. wall/cycles 收益约 `0.7%`，应保留，但远小于 NO0282 基于近邻 sample 的粗略热点比例；大量
   重复源码已被编译器消除，slot 邻近 sample 还包含 fanout/consumer 控制成本。
4. 当前 GrhSIM 相对 GSim 的主要剩余差距仍是 compute 动态指令，不能把后续工作停在 slot 数量。

## 8. 产物

```text
build/xs_grhsim_no0283_state_read_slot_alias_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0283_state_read_slot_alias_emit_20260711.log
build/logs/xs_perf/no0283/state_read_slot_alias_build_20260711.log
build/logs/xs_perf/no0283/state_read_slot_alias_functional_10k_20260711.log
build/logs/xs_perf/no0283/paired_old_no0278_cpu138_50k_run1.log
build/logs/xs_perf/no0283/paired_new_slot_alias_cpu138_50k.log
build/logs/xs_perf/no0283/paired_old_no0278_cpu138_50k_run2.log
build/logs/xs_perf/no0283/paired_*_perf_stat.csv
build/logs/xs_perf/no0283/bracket_slot_alias_cpu138_50k.log
build/logs/xs_perf/no0283/bracket_slot_alias_cpu138_50k_perf_stat.csv
```
