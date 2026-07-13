# NO0506 SimTop pure-event word bypass 50k functional gate

日期：2026-07-13

## 1. Scope

承接 [NO0505](./NO0505_simtop_pure_event_word_bypass_10k_functional_gate_20260713.md)，使用 profile-off production
candidate 执行 CoreMark/NEMU difftest 50k cycle：

```text
EMU_RUNTIME_PROFILE unset
WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV unset
EMU_PROGRESS_EVERY_CYCLES=10000
seed=0
limit=-C 50000
```

日志：

```text
build/logs/xs_perf/no0506/bypass_functional_50k.log
```

## 2. Endpoint gate

```text
exit                 0
guest cycles    50,001
cycleCnt        49,996
instrCnt        73,580
terminal PC  0x80001312
```

终点与 NO0361 direct-state-read baseline 及 NO0500 profile run 精确一致。负向扫描未发现
`input_fullpass_blocked`、difftest mismatch、assertion、abort、segfault、fatal 或 error，也没有 profile dump。

## 3. Checkpoint identity

去掉 `host_ms` 后，五个 10k progress checkpoints 与 NO0361 逐字节 diff 为 0：

| Cycle | `instr` | `commit_pc` | `trap_pc` |
|---:|---:|---|---|
| 10,000 | 458 | `0x80001cdc` | `0x800027c6` |
| 20,000 | 14,121 | `0x8000043a` | `0x80000440` |
| 30,000 | 27,809 | `0x8000043a` | `0x80000442` |
| 40,000 | 43,350 | `0x80000432` | `0x80000428` |
| 50,000 | 73,580 | `0x800012f8` | `0x80001312` |

production bypass 没有改变从启动到 CoreMark 稳态执行的可见模拟时序或指令轨迹。

## 4. Host-load caveat

运行前后 load average 约为 `122.94/129.23/138.91` 与 `215.24/158.16/146.14`（384 逻辑 CPU），raw host
time 为 `95,216 ms`。主机负载在运行期间明显上升，且本轮没有固定 CPU/NUMA/ASLR、没有相邻 baseline；该时间只作
功能运行记录，不能与历史 NO0361 的 `78,272 ms` 比较。

## 5. Decision

fresh candidate 已通过 emit/build、100-cycle、10k 和 50k 全部功能门禁。下一步先记录独立 fixed-ASLR PMU 方案，
再按固定 CPU/NUMA 的 baseline/bypass/baseline 串行夹测；高负载下必须保留两侧相邻 baseline，并要求 baseline cycles
spread `<=1%`。
