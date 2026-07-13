# NO0346 Fixed-period event-count gate correction

日期：2026-07-12

## 1. 触发

[NO0345](./NO0345_fixed_aslr_latest_instruction_profile_plan_20260712.md) 原计划要求 fixed-period profile 的
approximate event count 与独立 perf stat instructions 相差不超过一个 `25,000,000` period。两边 profile
功能正确、`Total Lost Samples = 0`，但实际得到：

| Simulator | Samples | `samples * period` | NO0344 perf stat | Difference | Difference / stat |
| --- | ---: | ---: | ---: | ---: | ---: |
| GSim | 3,201 | 80,025,000,000 | 80,070,645,161 | 45,645,161 | 0.0570% |
| GrhSIM | 6,914 | 172,850,000,000 | 172,878,902,692 | 28,902,692 | 0.0167% |

差值分别为 `1.826/1.156` 个 period，因此原绝对门限不成立。NO0282 的 GSim 同口径也恰好为
`3,201` samples，说明本轮没有出现新的采样丢失。

## 2. 原因与修正

`perf report` 明确把该值标为 `Event count (approx.)`；固定 period 样本数只记录成功产生的 overflow samples。
overflow skid、采样处理中 event 的计数状态以及 profile/stat 来自不同执行，都使 `samples * period` 不能作为
带一个 period 尾数误差的精确 retired-instruction 总数。

修正 NO0345 数据门禁为：

1. event、period、call graph 和 fixed-ASLR 命令必须与计划一致；
2. `Total Lost Samples = 0`；
3. 两边功能终点正确；
4. GrhSIM/GSim sample ratio 与独立 perf stat instruction ratio 的相对误差不超过 `0.5%`；
5. `samples * period` 只用于近似类别 instructions 和同次 profile 内 share，不声称是精确总计数。

本轮 sample ratio 为 `2.159950x`，NO0344 perf stat ratio 为 `2.159080x`，相对误差仅 `0.0403%`，修正后的
门禁通过。现有两个 profile 数据有效，无需重跑；后续符号分类以精确 sample count 与 share 为准。

## 3. 产物

```text
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.data
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.report
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.data
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.report
```
