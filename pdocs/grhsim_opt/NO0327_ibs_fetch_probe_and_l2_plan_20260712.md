# NO0327 IBS fetch probe and L2 instruction plan

日期：2026-07-12

## 1. 目的

[NO0326](./NO0326_stable_op_origin_density_gate_20260712.md) 指向广泛的 fetch-layout latency，但 cmask6
不是 precise event。本阶段探测 AMD IBS fetch 能力，并确定先用原生 L2 instruction counters 闭合 cache level，
再按结果用 IBS 映射精确函数。

## 2. IBS 接线修正

三步探针结果：

1. per-thread `ibs_fetch//u` 被内核拒绝，IBS 必须 system-wide；仿真未启动；
2. `perf record -a -C 138` 加 `/u` 仍被拒绝，Zen4 IBS 不支持 privilege filter；仿真未启动；
3. `perf record -a -C 138 -e ibs_fetch//` 成功，目标进程仍固定 CPU138。

默认 IBS 1000-cycle、period 100,000 探针得到约 `5K` samples、lost `0`，symbol 可解析；但当前 perf/kernel
没有在 sample 中设置 `weight`、`data_src`、`ins_lat` 或 `code_page_size`，因此不能直接读取 fetch latency 或
cache source。system-wide 模式还包含少量 kernel/其他 command 样本，正式报告必须按 comm/DSO 过滤并报告
非 emu 占比。

## 3. L3-miss-only 能力

本机 `ibs_fetch` PMU 暴露 `l3missonly=config:59`。使用：

```text
ibs_fetch/l3missonly=1/
```

1000-cycle、period 1000 探针成功得到 `1,268` samples、lost `0`，主要 IP 可解析到 generated compute/commit
functions。该事件可在后续用作精确 L3-miss fetch 分布，但仅靠 IBS approximate event count 不足以先判断
old/new cache-level 总量。

## 4. 原生 L2 计数计划

先对无 profile NO0286 / NO0300 做 fixed CPU138、NUMA node 1、CoreMark 50k 的 old / new / old：

```text
cycles:u
ic_tag_hit_miss.instruction_cache_miss:u
l2_cache_req_stat.ic_access_in_l2:u
l2_cache_req_stat.ic_hit_in_l2:u
l2_cache_req_stat.ic_fill_miss:u
```

先用短探针要求五项全部 `100%` 调度。正式结果报告绝对值、per cycle、per work、L2 hit/miss rate，并要求
功能终点一致与 baseline 稳定。

NO0286 `-C 100` 接线探针五项均为 `100.00%`，且 `L2 access = L2 hit + L2 fill miss` 精确闭合；短跑
数值不进入性能结论。

## 5. 分支判定

- L2 instruction miss density 恶化：运行 old/new l3miss-only IBS profile，定位到 phase/batch，并检查 L3/DRAM；
- L2 miss 不恶化但 L2 hit/miss 总 fetch penalty 仍可疑：比较 hit/miss 组合与 full-empty 增量，再测试函数对齐；
- L2 access/hit/miss 均改善：cache miss 数量链条全排除，优先做只改链接/函数对齐的 no-regenerate code-layout
  probe，并用 cmask6 + runtime 验证。

IBS profile timing 不作为性能门禁；system-wide 样本必须过滤 `comm=emu` 和 user `emu` DSO。
