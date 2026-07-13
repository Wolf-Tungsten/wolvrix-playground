# NO0284 Same-state read fanout-union negative probe

日期：2026-07-11

## 1. 动机

[NO0283](./NO0283_same_supernode_state_read_slot_alias_20260711.md) 共用物化槽后，generated
sched8 仍对每个 alias result 发射相同 changed condition 的 fanout effect，例如重复执行：

```cpp
grhsim_any_changed_7813_1 =
    static_cast<bool>(grhsim_any_changed_7813_1 | grhsim_changed_6379547);
```

由于 alias reads 位于同一 supernode、读取同一 state，changed condition 严格一致。本 probe 将
各 alias 的 boundary fanout ID 并入 canonical value，由 canonical read 统一传播一次；集合本身
不增加任何 consumer activation。

## 2. 静态结果

fresh SimTop 覆盖全部 `35745` 个 NO0283 aliases：

| metric | slot alias | slot + fanout union | delta |
| --- | ---: | ---: | ---: |
| tracked-change values | `915971` | `880226` | `-35745` |
| boundary edges after dedup | `2003556` | `1967952` | `-35604` |
| sched8 lines | `350129` | `320879` | `-29250` |
| sched8 source bytes | `33171233` | `30247726` | `-2923507` |

但编译结果几乎没有变化：

| metric | slot alias | slot + fanout union | delta |
| --- | ---: | ---: | ---: |
| sched8 function text | `1153296` | `1153125` | `-171` |
| full emu `.text` | `102595917` | `102594861` | `-1056` |

这说明 clang `-O3` 已在 NO0283 中消除了绝大多数连续重复 OR；源码减少约 4.92 MB，并没有转化
为对应机器码或动态指令减少。

## 3. 功能 gate

10k 和两次 50k 均通过 NEMU difftest，终点保持：

```text
10k: guest=10001 instrCnt=458   cycleCnt=9996  PC=0x800027c6
50k: guest=50001 instrCnt=73580 cycleCnt=49996 PC=0x80001312
```

因此该 probe 的拒绝原因是性能，而不是功能错误。

## 4. CPU138 fanout/slot/fanout 夹测

运行时机器 load average 为 `4.66/9.48/11.14`（384 logical CPUs）。三次 event 均为 `100%`
scheduled：

| run | Host time | cycles:u | instructions:u |
| --- | ---: | ---: | ---: |
| fanout union 1 | `82943ms` | `303518950059` | `188786770097` |
| retained slot alias | `82339ms` | `301361407554` | `188789156631` |
| fanout union 2 | `82622ms` | `302363211736` | `188786734403` |

fanout 两次均值相对中间 slot alias：

- Host time `+0.54%`；
- cycles `+0.52%`；
- instructions `-0.0013%`，可视为没有动态工作收益。

两次 fanout instructions 只相差约 36k，负向 cycles 则稳定在约 0.3%~0.6% 范围，符合代码布局
变化而非 workload 变化。

## 5. 决策

fanout union 不保留：它没有降低实际 host instructions，反而在相邻夹测中稳定增加 cycles。
实现已从工作树撤下，默认路径回到 NO0283 的行为：共用 slot，但保留每个 alias 的原 fanout
effect，让编译器做局部消除。

该结果也修正了下一步方向：继续删重复 state-read 源码不会解释剩余 `2.38x` instructions gap；
应重新 profile NO0283，观察 compute8 退热后真正保留下来的机器指令热点，并继续与 GSim
`subStep*` 对照。

## 6. 产物

```text
build/xs_grhsim_no0284_state_read_fanout_alias_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0284_state_read_fanout_alias_emit_20260711.log
build/logs/xs_perf/no0283/state_read_fanout_alias_build_20260711.log
build/logs/xs_perf/no0283/state_read_fanout_alias_functional_10k_20260711.log
build/logs/xs_perf/no0283/paired_new_fanout_alias_cpu138_50k.log
build/logs/xs_perf/no0283/paired_new_fanout_alias_cpu138_50k_perf_stat.csv
build/logs/xs_perf/no0283/bracket_fanout_alias_cpu138_50k_run2.log
build/logs/xs_perf/no0283/bracket_fanout_alias_cpu138_50k_run2_perf_stat.csv
```
