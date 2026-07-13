# NO0399 Direct scalar-locality runtime-profile 50k gate

日期：2026-07-12

## 1. Run conditions

承接 [NO0398](./NO0398_direct_scalar_locality_runtime_profile_smoke_gate_20260712.md)，在 CPU188、NUMA1 上运行
profile-enabled direct CoreMark/NEMU difftest 50k。运行前 load average `22.48/22.82/23.53`，CPU188/380 三秒平均
idle `100%/99.67%`。所有命令先执行 `source env.sh`。

这是 fire 诊断，不使用插桩 host time 作性能结论，也不需要配跑 production baseline。

## 2. Functional gate

五个 10k progress checkpoints 均到达，最终：

```text
exit:          0
guest cycles:  50,001
model cycles:  50,000
cycleCnt:      49,996
instrCnt:      73,580
terminal PC:   0x80001312
profile host:  76,758 ms (completeness only)
```

终点与 NO0361/NO0381 direct production 功能结果一致。日志无 mismatch、assert、abort、fatal/error、segmentation
fault 或 `input_fullpass_blocked`。

## 3. Fire gate

direct fire TSV 有 header + 63,726 data rows，SHA256：

```text
44503e17def5e6aa05c5c5238d0503bd61cecc19b81650ca320c111b02421394
```

NO0311 compare tool 确认 emit-time static 与 runtime fire 的全部 `(supernode_id, phase)` keys 一一匹配。direct 动态
汇总：

```text
compute fire    789,272,336
commit fire       8,091,650
total fire      797,363,986
```

与 NO0311 NO0300 baseline fire 在同 key 上逐项比较：

| Phase | Baseline | Direct | Delta | Changed rows |
| --- | ---: | ---: | ---: | ---: |
| Compute | 805,762,327 | 789,272,336 | -16,489,991 (-2.047%) | 665 decreased, 0 increased |
| Commit | 8,091,650 | 8,091,650 | 0 | 0 |
| Total | 813,853,977 | 797,363,986 | -16,489,991 (-2.026%) | 665 |

这证明 NO0393 的担忧成立：schedule ID 不变但 direct fire 并不相同；同时 direct frontier 只减少 fire，没有把工作转移
为其他 supernode 的额外 fire。下一步必须用本轮 direct TSV 重算 scalar locality，baseline proxy 只保留作差值对照。

产物：

```text
build/logs/xs_perf/no0399/direct_rtprof_50k.log
build/logs/xs_perf/no0399/direct_rtprof_50k_fire.tsv
build/logs/xs_perf/no0399/direct_rtprof_50k.{report,json}
```
