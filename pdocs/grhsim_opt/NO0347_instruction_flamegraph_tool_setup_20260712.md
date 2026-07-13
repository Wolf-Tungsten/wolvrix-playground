# NO0347 Instruction flamegraph tool setup

日期：2026-07-12

## 1. 工具固定

[NO0345](./NO0345_fixed_aslr_latest_instruction_profile_plan_20260712.md) 的两份 fixed-ASLR
`instructions:u` perf data 已通过功能、配置、0 lost 和 ratio 门禁。系统未安装 `stackcollapse-perf.pl` 或
`flamegraph.pl`，因此将官方 FlameGraph 仓库浅克隆到不提交的 build 工具目录：

```text
path = build/tools/FlameGraph
source = https://github.com/brendangregg/FlameGraph.git
revision = 41fee1f99f9276008b7cd112fca19dc3ea84ac32
revision date = 2024-10-21
```

`stackcollapse-perf.pl` 与 `flamegraph.pl` 均已确认可执行。第三方仓库位于 `build/`，不进入源码提交。

## 2. Perf 6.8 后处理修正

本机 `perf version 6.8.12` 不支持 `perf script --no-callchain`；首次探测只输出 usage，没有修改 perf data
或产生有效分析产物。正确的 hide-callgraph 选项为 `-G`。

此外，`perf script -G -F sym` 会只输出空行；精确 leaf symbol 必须保留 IP 字段：

```text
perf script -G -F ip,sym -i <perf.data>
```

该命令对 GSim/GrhSIM 分别输出 `3201/6914` 行，与完整 perf-script event header 数和 report symbol
sample sum 精确一致。后续 symbol TSV 使用 `ip,sym`，flamegraph 则使用保留完整 callchain 的默认
`perf script` 输出，两者不混用。

## 3. Flamegraph 口径

生成链路为：

```text
perf script -i <perf.data> > <name>.perf-script
stackcollapse-perf.pl < <name>.perf-script > <name>.folded
flamegraph.pl --countname samples --title <title> < <name>.folded > <name>.svg
```

纵轴 stack 来自 DWARF 8192 call graph；横轴单位标为 `samples`，不是精确 instructions。每个 sample 对应
25M instruction overflow，但按 [NO0346](./NO0346_fixed_period_event_count_gate_correction_20260712.md)，
`samples * period` 只能作近似计数。

## 4. 预定产物

```text
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.folded
build/logs/xs_perf/no0345/fixed_gsim_50k_instructions.svg
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.folded
build/logs/xs_perf/no0345/fixed_grhsim_50k_instructions.svg
```

## 5. 增量勘误

`stackcollapse-perf.pl` 实际按 sample period 加权，横轴不是 raw sample count。有效 SVG 已由
[NO0348](./NO0348_flamegraph_period_weight_correction_20260712.md) 修正为 `approx instructions` 标签；本篇
第 3 节的 `--countname samples` 命令不再使用。
