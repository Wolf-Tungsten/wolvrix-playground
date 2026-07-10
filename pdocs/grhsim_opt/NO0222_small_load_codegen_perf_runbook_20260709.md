# NO0222 Small-Load Codegen / Perf Analysis Runbook

记录日期：2026-07-09

关联：[`NO0078`](./NO0078_grhsim_gsim_generated_code_static_sample_20260509.md)、[`NO0079`](./NO0079_big_comb_chisel_gsim_grhsim_benchmark_20260509.md)、[`NO0099`](./NO0099_hot_function_disasm_shape_20260521.md)、[`NO0194`](./NO0194_xs_real100_5s_profile_feature_delta_20260613.md)、[`NO0221`](./NO0221_no0217_plain_bae_artifact_rebuild_20260707.md)

## 1. 目标

此前主要用完整 XiangShan `SimTop` / CoreMark 观察 GrhSIM 与 GSIM 的性能差距，负载太大时容易只得到总体统计而难以直接定位生成代码形态。本轮改为小负载深挖：

- 直接比较 GSIM / GrhSIM 生成的 C++ 源码、对象/汇编和 hot symbol；
- 对同一个 C++ benchmark 采集 `perf stat` / `perf report` / `perf annotate`；
- 结合 runtime profile TSV 判断 runtime-weighted `comp/src/sink/succ` 与热点机器码形态是否一致；
- 首轮只做诊断，不改 simulator 算法和 codegen。

SVG flamegraph 不作为硬要求：当前仓库和 `PATH` 未找到 `flamegraph.pl` / `stackcollapse-perf.pl`，本轮以 perf 文本报告和 annotate 作为必备证据。

## 2. 负载选择

首轮使用少量高信号 case 深挖：

| workload | 作用 |
| --- | --- |
| `BigComb` | 纯组合 compute-only 对照，延续 `NO0079` |
| `XsReal100BackendNfmappedelemidxSmall` | 小型 Vec-of-Bundle / packed array 案例，和 `NO0199` 事实集相关 |
| `XsReal053FtqFtqLarge` | FTQ / metaQueue 类 aggregate 拆分重负载 |
| `XsReal043TageTageLarge` | BPU/TAGE 类表结构，历史上多次暴露寄存器/数组展开差异 |
| `XsReal075RobVtypebufferLarge` | VTypeBuffer 类状态更新案例，覆盖 commit/state path |

## 3. 产物目录

```text
tmp/no0222_small_load_codegen_perf_20260709/
testcase/big-comb/build/no0222_small_load_codegen_perf_20260709/
testcase/xs-components/build/no0222_small_load_codegen_perf_20260709/
```

约定子目录：

| 子目录 | 内容 |
| --- | --- |
| `raw_bench/` | no-profile benchmark 原始日志和 `model_stats.json` |
| `runtime_profile/` | `GSIM/GRHSIM_EMIT_RUNTIME_PROFILE=1` 生成的 static/fire TSV |
| `perf/` | `perf stat`、`perf.data`、`perf report --stdio`、`perf annotate --stdio` |
| `code_shape/` | `nm`、`objdump`、hot symbol 汇编/计数、emit metrics |

## 4. 执行命令

环境和依赖：

```bash
source env.sh
make py_install
make -C reference/gsim build-gsim
```

BigComb raw bench：

```bash
make -C testcase/big-comb bench \
  BUILD_DIR=build/no0222_small_load_codegen_perf_20260709 \
  BENCH_VECTORS=1000000 \
  BENCH_VERIFY=4096
```

xs-components raw bench：

```bash
for case in \
  XsReal100BackendNfmappedelemidxSmall \
  XsReal053FtqFtqLarge \
  XsReal043TageTageLarge \
  XsReal075RobVtypebufferLarge; do
  make -C testcase/xs-components one \
    CASE="$case" \
    BUILD_DIR=build/no0222_small_load_codegen_perf_20260709/raw_bench \
    BENCH_VECTORS=200000 \
    BENCH_VERIFY=2048 \
    BENCH_REPEAT=3
done
```

xs-components runtime profile：

```bash
python3 testcase/xs-components/scripts/collect_runtime_profile_matrix.py \
  --build-dir build/no0222_small_load_codegen_perf_20260709/runtime_profile_build \
  --out-dir build/no0222_small_load_codegen_perf_20260709/runtime_profile \
  --vectors 200000 \
  --verify 2048 \
  --repeat 1 \
  --case XsReal100BackendNfmappedelemidxSmall \
  --case XsReal053FtqFtqLarge \
  --case XsReal043TageTageLarge \
  --case XsReal075RobVtypebufferLarge
```

Perf 采样对 raw bench 产物执行，避免 runtime profile 插桩污染 no-profile 热点：

```bash
perf stat -o <out>.stat -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,duration_time,user_time,system_time -- <bench> --vectors <N> --verify 0 --repeat 1
perf record -F 999 -e cycles:u -g -o <out>.data -- <bench> --vectors <N> --verify 0 --repeat 1
perf report --stdio --demangle -i <out>.data > <out>.report
perf annotate --stdio --demangle -i <out>.data > <out>.annotate
```

## 5. 记录要求

本 runbook 只记录执行口径。实验完成后另起 `NOxxxx` 文档记录：

- 每个 case 的 correctness / timing；
- static/fire TSV 摘要；
- perf stat / report / annotate 摘要；
- GSIM `subStep*` 与 GrhSIM `eval_*_batch_*` 的 hot symbol 源码/汇编形态；
- 当前最可信 root-cause 假设，以及不能由本轮数据支持的结论。

新增文档和 README 更新必须继续遵守 [`RULES.md`](./RULES.md)：独立议题新建文档，索引使用相对链接，不覆盖历史结论。
