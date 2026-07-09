# NO0221 XiangShan CoreMark 50k GSim / GrhSIM 统一动静态统计快照

## 1. 记录目的

本文记录 2026-07-08/09 完成的一次完整 XiangShan `CoreMark 50k` 统计快照。该快照使用新的统一 JSON 口径：

- 静态统计：`gsim_static_stats.json` / `grhsim_static_stats.json`
- 运行期统计：`gsim_runtime_stats.json` / `grhsim_runtime_stats.json`
- join key：`sim + top + supernode_id`
- runtime activation：只统计实际执行的 activation 次数，不统计尝试次数
- 输出格式：仅 JSON，本次 work base 下没有 `stats/activity` TSV

本次数据的直接背景是：旧的 runtime stats dump 曾把每个 supernode 的输出语句展开成大量 C++ 代码，导致完整 XiangShan 的 `SimTop1.cpp` 编译异常变慢。本次统计使用修复后的 emitter：runtime JSON dump 在 GSim 和 GrhSIM 中都由固定大小循环生成，避免按 supernode 展开 C++ 输出语句。

## 2. 数据来源

work base：

```text
build/xs/stats_coremark50k_20260708_fix_stats_dump
```

JSON 产物：

| 文件 | 路径 | 大小 |
| --- | --- | ---: |
| `gsim_static_stats.json` | [`../../build/xs/stats_coremark50k_20260708_fix_stats_dump/gsim/gsim-compile/model/gsim_static_stats.json`](../../build/xs/stats_coremark50k_20260708_fix_stats_dump/gsim/gsim-compile/model/gsim_static_stats.json) | `13M` |
| `gsim_runtime_stats.json` | [`../../build/xs/stats_coremark50k_20260708_fix_stats_dump/gsim/gsim-compile/model/gsim_runtime_stats.json`](../../build/xs/stats_coremark50k_20260708_fix_stats_dump/gsim/gsim-compile/model/gsim_runtime_stats.json) | `8.7M` |
| `grhsim_static_stats.json` | [`../../build/xs/stats_coremark50k_20260708_fix_stats_dump/grhsim/grhsim_emit/grhsim_static_stats.json`](../../build/xs/stats_coremark50k_20260708_fix_stats_dump/grhsim/grhsim_emit/grhsim_static_stats.json) | `17M` |
| `grhsim_runtime_stats.json` | [`../../build/xs/stats_coremark50k_20260708_fix_stats_dump/grhsim/grhsim_emit/grhsim_runtime_stats.json`](../../build/xs/stats_coremark50k_20260708_fix_stats_dump/grhsim/grhsim_emit/grhsim_runtime_stats.json) | `7.4M` |

运行日志：

- GSim: [`../../build/logs/xs/xs_gsim_stats_coremark50k_20260708_fix_stats_dump.log`](../../build/logs/xs/xs_gsim_stats_coremark50k_20260708_fix_stats_dump.log)
- GrhSIM: [`../../build/logs/xs/xs_wolf_grhsim_stats_coremark50k_20260708_fix_stats_dump.log`](../../build/logs/xs/xs_wolf_grhsim_stats_coremark50k_20260708_fix_stats_dump.log)

核心构建/运行命令：

```bash
source env.sh && make xs_gsim_emu \
  XS_WORK_BASE=build/xs/stats_coremark50k_20260708_fix_stats_dump \
  XS_GSIM_EMIT_RUNTIME_STATS=1 \
  XS_SIM_MAX_CYCLE=50000 \
  RUN_ID=stats_coremark50k_20260708_fix_stats_dump \
  XS_PROGRESS_EVERY_CYCLES=10000 \
  EMU_OPTIMIZE=-O1

source env.sh && make run_xs_gsim_emu \
  XS_WORK_BASE=build/xs/stats_coremark50k_20260708_fix_stats_dump \
  XS_GSIM_EMIT_RUNTIME_STATS=1 \
  XS_SIM_MAX_CYCLE=50000 \
  RUN_ID=stats_coremark50k_20260708_fix_stats_dump \
  XS_PROGRESS_EVERY_CYCLES=10000 \
  EMU_OPTIMIZE=-O1

source env.sh && make xs_wolf_grhsim_emu \
  XS_WORK_BASE=build/xs/stats_coremark50k_20260708_fix_stats_dump \
  XS_WOLF_GRHSIM_EMIT_RUNTIME_STATS=1 \
  XS_SIM_MAX_CYCLE=50000 \
  RUN_ID=stats_coremark50k_20260708_fix_stats_dump \
  XS_PROGRESS_EVERY_CYCLES=10000 \
  EMU_OPTIMIZE=-O1

source env.sh && make run_xs_wolf_grhsim_emu \
  XS_WORK_BASE=build/xs/stats_coremark50k_20260708_fix_stats_dump \
  XS_WOLF_GRHSIM_EMIT_RUNTIME_STATS=1 \
  XS_SIM_MAX_CYCLE=50000 \
  RUN_ID=stats_coremark50k_20260708_fix_stats_dump \
  XS_PROGRESS_EVERY_CYCLES=10000 \
  EMU_OPTIMIZE=-O1
```

说明：本次目标是收集统计数据，不是性能正式 gate，因此 emu 编译使用 `EMU_OPTIMIZE=-O1`。

## 3. 统计口径

静态统计文件格式：

- 顶层 `format`：`wolvrix.sim-supernode-static-stats.v1`
- 顶层 `sim`：`gsim` 或 `grhsim`
- 顶层 `top`：`SimTop`
- 顶层 `summary`：全局汇总
- `supernodes[]`：每个 supernode 的可 join 行

静态 per-supernode 字段：

- `sim`
- `top`
- `supernode_id`
- `kind`
  - GSim 当前为 `supernode`
  - GrhSIM 为 `compute` 或 `commit`
- `activation_edges`
  - 表示 outgoing activation edge 数
  - 若 supernode `s1` 可激活 supernode `s2`，则 `s1 -> s2` 记一条有向边
  - 同一 `(s1, s2)` 不重复计数
  - `self` 为 `s1 == s2` 的子集
  - GrhSIM 额外拆分 `compute_compute` / `compute_commit` / `commit_compute` / `commit_commit`
- `activation_checks`
  - 表示 activation 检测成本
  - GSim：按被检测的 node 数量计算
  - GrhSIM：按被检测的 value 数量计算

运行期统计文件格式：

- 顶层 `format`：`wolvrix.sim-supernode-runtime-stats.v1`
- `supernodes[]` 每行包含 `sim + top + supernode_id + kind + activation_count`
- `activation_count` 是该 supernode 在本次 50k run 中实际执行 activation 的次数

本文还派生两个 join 后指标：

- `runtime_weighted_checks = activation_count * activation_checks`
- `runtime_weighted_edges = activation_count * activation_edges.total`

这两个指标不是新 JSON 字段，只是本文用于定位 runtime 压力的派生量。

## 4. 完整性校验

四个 JSON 都可被 `json.load` 解析。

| sim | static rows | runtime rows | join key 集合一致 | bad static key | bad runtime key |
| --- | ---: | ---: | --- | ---: | ---: |
| GSim | `84,713` | `84,713` | yes | `0` | `0` |
| GrhSIM | `72,368` | `72,368` | yes | `0` | `0` |

本次 work base 下未发现 `*stats*.tsv` 或 `*activity*.tsv`。

运行结果：

| 项 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| max cycle | `50,000` | `50,000` | - |
| guest cycle spent | `50,001` | `50,001` | `1.000x` |
| core cycleCnt | `49,998` | `49,996` | `1.000x` |
| guest instrCnt | `73,584` | `73,580` | `1.000x` |
| guest IPC | `1.471739` | `1.471718` | `1.000x` |
| end PC | `0x8000131e` | `0x80001312` | - |
| host time | `42,023 ms` | `325,783 ms` | `7.752x` |

两边都跑满 `-C 50000` 并以 cycle limit 正常退出。guest 指令数只差 `4` 条，本文把它们视为同 workload / 同 cycle limit 下的统计对照。

## 5. 顶层 summary

| 指标 | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| static supernodes | `84,713` | `72,368` | `0.854x` |
| static activation edges | `719,229` | `761,624` | `1.059x` |
| static activation checks | `442,047` | `1,251,744` | `2.832x` |
| runtime activation_count | `766,596,798` | `907,159,590` | `1.183x` |
| runtime_weighted_checks | `3,832,780,896` | `24,440,291,074` | `6.377x` |
| runtime_weighted_edges | `6,554,449,656` | `12,192,168,157` | `1.860x` |

直接观察：

- GrhSIM supernode 数更少，约为 GSim 的 `85.4%`。
- GrhSIM 静态 outgoing activation edge 只比 GSim 多 `5.9%`。
- GrhSIM 静态 activation checks 是 GSim 的 `2.83x`。
- GrhSIM runtime activation 总次数是 GSim 的 `1.18x`。
- join 后看，GrhSIM `runtime_weighted_checks` 是 GSim 的 `6.38x`，显著高于静态 checks 的 `2.83x` 和 activation_count 的 `1.18x`，说明高 checks supernode 在 runtime 中并不冷。

## 6. GrhSIM compute / commit 拆分

### 6.1 数量和 share

| kind | supernodes | static checks | static edges | runtime activation_count | runtime_weighted_checks | runtime_weighted_edges |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| compute | `71,871` | `983,434` | `661,965` | `898,467,340` | `11,397,357,904` | `7,310,995,131` |
| commit | `497` | `268,310` | `99,659` | `8,692,250` | `13,042,933,170` | `4,881,173,026` |
| total | `72,368` | `1,251,744` | `761,624` | `907,159,590` | `24,440,291,074` | `12,192,168,157` |

| kind | supernode share | static checks share | static edges share | runtime activation share | weighted checks share | weighted edges share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| compute | `99.31%` | `78.57%` | `86.91%` | `99.04%` | `46.63%` | `59.96%` |
| commit | `0.69%` | `21.43%` | `13.09%` | `0.96%` | `53.37%` | `40.04%` |

关键点：

- commit supernode 只有 `497` 个，占 `0.69%`。
- commit 只贡献 `0.96%` runtime activation_count。
- 但 commit 贡献 `53.37%` 的 `runtime_weighted_checks`，说明少量 commit supernode 的 activation 检测成本极高，并且每 50k 周期高频执行。
- commit 还贡献 `40.04%` 的 `runtime_weighted_edges`，说明 commit->compute 激活 fanout 仍是 runtime 压力核心之一。

### 6.2 GrhSIM activation edge class

| edge class | count | share |
| --- | ---: | ---: |
| `compute_compute` | `661,463` | `86.84%` |
| `compute_commit` | `502` | `0.07%` |
| `commit_compute` | `99,659` | `13.09%` |
| `commit_commit` | `0` | `0.00%` |
| `self` | `0` | `0.00%` |
| total | `761,624` | `100.00%` |

GSim 的 `self` edge 为 `5,134`，GrhSIM 本次为 `0`。

## 7. 分布画像

### 7.1 每 supernode 静态 activation_checks 分位数

| percentile | GSim | GrhSIM |
| ---: | ---: | ---: |
| min | `0` | `0` |
| p50 | `2` | `2` |
| p75 | `6` | `18` |
| p90 | `15` | `45` |
| p95 | `15` | `68` |
| p99 | `30` | `108` |
| p99.9 | `129` | `108` |
| max | `2,905` | `42,937` |

| 指标 | GSim | GrhSIM |
| --- | ---: | ---: |
| average | `5.218` | `17.297` |
| nonzero rows | `82,662 / 84,713` | `46,937 / 72,368` |
| max row | `supernode_id=10307, checks=2905` | `supernode_id=71871, kind=commit, checks=42937` |

GrhSIM 的 p99 不算极端，但 max 非常重，且 top static checks 全部落在 commit supernode 上。

### 7.2 每 supernode 静态 activation_edges.total 分位数

| percentile | GSim | GrhSIM |
| ---: | ---: | ---: |
| min | `0` | `0` |
| p50 | `2` | `2` |
| p75 | `7` | `6` |
| p90 | `16` | `24` |
| p95 | `27` | `46` |
| p99 | `76` | `96` |
| p99.9 | `456` | `616` |
| max | `13,742` | `13,903` |

| 指标 | GSim | GrhSIM |
| --- | ---: | ---: |
| average | `8.490` | `10.524` |
| nonzero rows | `82,662 / 84,713` | `46,937 / 72,368` |
| max row | `supernode_id=7286, edges=13742` | `supernode_id=72080, kind=commit, edges=13903` |

GrhSIM 的边分布中位数不高，但 p90 以后更重，最大值也落在 commit。

### 7.3 每 supernode runtime activation_count 分位数

| percentile | GSim | GrhSIM |
| ---: | ---: | ---: |
| min | `102` | `0` |
| p50 | `864` | `2,176` |
| p75 | `12,537` | `18,219` |
| p90 | `31,999` | `29,382` |
| p95 | `50,101` | `50,000` |
| p99 | `50,101` | `114,836` |
| p99.9 | `50,101` | `150,103` |
| max | `50,101` | `200,653` |

| 指标 | GSim | GrhSIM |
| --- | ---: | ---: |
| average | `9,049.341` | `12,535.369` |
| nonzero rows | `84,713 / 84,713` | `72,309 / 72,368` |
| max row | `supernode_id=84711, activation_count=50101` | `supernode_id=71900, kind=commit, activation_count=200653` |

GrhSIM 的 runtime activation tail 明显更重。GSim 最大值约等于 guest cycle 数；GrhSIM 出现 `200k` 级 activation_count，说明同一个 guest cycle 内可能多次执行相关 supernode activation。

## 8. Top static hotspots

### 8.1 Top static activation_checks

GSim：

| rank | supernode_id | activation_count | checks | edges.total | weighted_checks |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `10307` | `1,090` | `2,905` | `81` | `3,166,450` |
| 2 | `69187` | `19,276` | `2,817` | `57` | `54,300,492` |
| 3 | `18734` | `50,101` | `1,524` | `368` | `76,353,924` |
| 4 | `50431` | `1,454` | `1,092` | `124` | `1,587,768` |
| 5 | `37936` | `10,859` | `896` | `16` | `9,729,664` |
| 6 | `37935` | `10,407` | `896` | `16` | `9,324,672` |
| 7 | `37934` | `11,544` | `896` | `16` | `10,343,424` |
| 8 | `37933` | `10,966` | `896` | `16` | `9,825,536` |

GrhSIM：

| rank | supernode_id | kind | activation_count | checks | edges.total | weighted_checks |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `71871` | `commit` | `50,050` | `42,937` | `11,982` | `2,148,996,850` |
| 2 | `72080` | `commit` | `50,050` | `18,439` | `13,903` | `922,871,950` |
| 3 | `71905` | `commit` | `50,050` | `5,130` | `1,845` | `256,756,500` |
| 4 | `72097` | `commit` | `50,050` | `4,096` | `746` | `205,004,800` |
| 5 | `72096` | `commit` | `50,050` | `4,096` | `44` | `205,004,800` |
| 6 | `72095` | `commit` | `50,050` | `4,096` | `42` | `205,004,800` |
| 7 | `72094` | `commit` | `50,050` | `4,096` | `46` | `205,004,800` |
| 8 | `72093` | `commit` | `50,050` | `4,096` | `43` | `205,004,800` |

GrhSIM top checks 不是泛化分布问题，而是少数 commit supernode 特别重，且每个都接近每周期执行一次。

### 8.2 Top static activation_edges.total

GSim：

| rank | supernode_id | activation_count | checks | edges.total | weighted_edges |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `7286` | `103` | `8` | `13,742` | `1,415,426` |
| 2 | `20635` | `102` | `1` | `3,530` | `360,060` |
| 3 | `4867` | `30,101` | `15` | `1,793` | `53,971,093` |
| 4 | `19005` | `20,700` | `13` | `1,777` | `36,783,900` |
| 5 | `19001` | `20,816` | `13` | `1,776` | `36,969,216` |
| 6 | `18997` | `20,218` | `13` | `1,775` | `35,886,950` |
| 7 | `18993` | `14,959` | `13` | `1,774` | `26,537,266` |
| 8 | `18989` | `9,254` | `13` | `1,774` | `16,416,596` |

GrhSIM：

| rank | supernode_id | kind | activation_count | checks | edges.total | edge class | weighted_edges |
| ---: | ---: | --- | ---: | ---: | ---: | --- | ---: |
| 1 | `72080` | `commit` | `50,050` | `18,439` | `13,903` | `commit_compute=13903` | `695,845,150` |
| 2 | `71871` | `commit` | `50,050` | `42,937` | `11,982` | `commit_compute=11982` | `599,699,100` |
| 3 | `311` | `compute` | `50,003` | `5` | `10,558` | `compute_compute=10502, compute_commit=56` | `527,931,674` |
| 4 | `71890` | `commit` | `50,050` | `4,092` | `4,763` | `commit_compute=4763` | `238,388,150` |
| 5 | `71888` | `commit` | `50,050` | `4,096` | `4,673` | `commit_compute=4673` | `233,883,650` |
| 6 | `71875` | `commit` | `50,050` | `4,034` | `4,526` | `commit_compute=4526` | `226,526,300` |
| 7 | `71886` | `commit` | `50,050` | `4,067` | `3,992` | `commit_compute=3992` | `199,799,600` |
| 8 | `71879` | `commit` | `50,050` | `4,082` | `3,861` | `commit_compute=3861` | `193,243,050` |

GrhSIM 的 static edge 最大值和 GSim 接近，但 GrhSIM top edge 多数是高频 commit supernode，因此动态加权后明显更重。

## 9. Top runtime / join hotspots

### 9.1 Top runtime activation_count

GSim 的最高 activation_count 为 `50,101`，大量尾部 supernode 达到该值。Top 8 如下：

| rank | supernode_id | activation_count | checks | edges.total |
| ---: | ---: | ---: | ---: | ---: |
| 1 | `84711` | `50,101` | `0` | `0` |
| 2 | `84710` | `50,101` | `1` | `1` |
| 3 | `84709` | `50,101` | `0` | `0` |
| 4 | `84708` | `50,101` | `1` | `1` |
| 5 | `84707` | `50,101` | `3` | `2` |
| 6 | `84706` | `50,101` | `5` | `5` |
| 7 | `84705` | `50,101` | `2` | `1` |
| 8 | `84704` | `50,101` | `4` | `1` |

GrhSIM：

| rank | supernode_id | kind | activation_count | checks | edges.total | edge class |
| ---: | ---: | --- | ---: | ---: | ---: | --- |
| 1 | `71900` | `commit` | `200,653` | `402` | `75` | `commit_compute=75` |
| 2 | `6534` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 3 | `6533` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 4 | `6532` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 5 | `6531` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 6 | `6530` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 7 | `6529` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |
| 8 | `6528` | `compute` | `200,098` | `8` | `8` | `compute_commit=8` |

GrhSIM 的 top runtime activation_count 行本身 checks/edges 不一定大；真正的 runtime 成本要看 join 后加权指标。

### 9.2 Top runtime_weighted_checks

GSim：

| rank | supernode_id | activation_count | checks | edges.total | runtime_weighted_checks |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `18734` | `50,101` | `1,524` | `368` | `76,353,924` |
| 2 | `69187` | `19,276` | `2,817` | `57` | `54,300,492` |
| 3 | `42723` | `41,632` | `586` | `48` | `24,396,352` |
| 4 | `42840` | `41,618` | `586` | `48` | `24,388,148` |
| 5 | `43920` | `41,616` | `586` | `49` | `24,386,976` |
| 6 | `73873` | `37,565` | `521` | `6` | `19,571,365` |
| 7 | `46827` | `27,254` | `489` | `100` | `13,327,206` |
| 8 | `37932` | `13,494` | `896` | `16` | `12,090,624` |

GrhSIM：

| rank | supernode_id | kind | activation_count | checks | edges.total | runtime_weighted_checks |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `71871` | `commit` | `50,050` | `42,937` | `11,982` | `2,148,996,850` |
| 2 | `72080` | `commit` | `50,050` | `18,439` | `13,903` | `922,871,950` |
| 3 | `71905` | `commit` | `50,050` | `5,130` | `1,845` | `256,756,500` |
| 4 | `72097` | `commit` | `50,050` | `4,096` | `746` | `205,004,800` |
| 5 | `72096` | `commit` | `50,050` | `4,096` | `44` | `205,004,800` |
| 6 | `72095` | `commit` | `50,050` | `4,096` | `42` | `205,004,800` |
| 7 | `72094` | `commit` | `50,050` | `4,096` | `46` | `205,004,800` |
| 8 | `72093` | `commit` | `50,050` | `4,096` | `43` | `205,004,800` |

对比 top 1：

- GSim top weighted checks：`76,353,924`
- GrhSIM top weighted checks：`2,148,996,850`
- GrhSIM / GSim：`28.15x`

这比全局 `runtime_weighted_checks` 的 `6.38x` 更极端，说明 GrhSIM 的 checks 成本有明显 top-heavy commit 热点。

### 9.3 Top runtime_weighted_edges

GSim：

| rank | supernode_id | activation_count | checks | edges.total | runtime_weighted_edges |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `4867` | `30,101` | `15` | `1,793` | `53,971,093` |
| 2 | `19009` | `21,059` | `13` | `1,773` | `37,337,607` |
| 3 | `19001` | `20,816` | `13` | `1,776` | `36,969,216` |
| 4 | `19005` | `20,700` | `13` | `1,777` | `36,783,900` |
| 5 | `19125` | `50,101` | `14` | `731` | `36,623,831` |
| 6 | `18997` | `20,218` | `13` | `1,775` | `35,886,950` |
| 7 | `5532` | `50,101` | `7` | `659` | `33,016,559` |
| 8 | `18993` | `14,959` | `13` | `1,774` | `26,537,266` |

GrhSIM：

| rank | supernode_id | kind | activation_count | checks | edges.total | edge class | runtime_weighted_edges |
| ---: | ---: | --- | ---: | ---: | ---: | --- | ---: |
| 1 | `72080` | `commit` | `50,050` | `18,439` | `13,903` | `commit_compute=13903` | `695,845,150` |
| 2 | `71871` | `commit` | `50,050` | `42,937` | `11,982` | `commit_compute=11982` | `599,699,100` |
| 3 | `311` | `compute` | `50,003` | `5` | `10,558` | `compute_compute=10502, compute_commit=56` | `527,931,674` |
| 4 | `71890` | `commit` | `50,050` | `4,092` | `4,763` | `commit_compute=4763` | `238,388,150` |
| 5 | `71888` | `commit` | `50,050` | `4,096` | `4,673` | `commit_compute=4673` | `233,883,650` |
| 6 | `71875` | `commit` | `50,050` | `4,034` | `4,526` | `commit_compute=4526` | `226,526,300` |
| 7 | `71886` | `commit` | `50,050` | `4,067` | `3,992` | `commit_compute=3992` | `199,799,600` |
| 8 | `71879` | `commit` | `50,050` | `4,082` | `3,861` | `commit_compute=3861` | `193,243,050` |

对比 top 1：

- GSim top weighted edges：`53,971,093`
- GrhSIM top weighted edges：`695,845,150`
- GrhSIM / GSim：`12.89x`

GrhSIM 的 top weighted edges 主要由 commit->compute fanout 构成，另有一个 compute supernode `311` 的 `compute_compute=10502` 也非常重。

## 10. 当前判断

这组新 JSON 口径比旧 TSV/临时 profile 更适合做后续统一分析，原因是：

- static/runtime 都有稳定 JSON schema；
- GSim/GrhSIM 都能按 `sim + top + supernode_id` join；
- GrhSIM 的 `kind` 能把 compute 和 commit 拆开；
- GrhSIM edge class 能进一步定位 compute->compute 与 commit->compute 压力；
- runtime activation_count 只统计实际执行，能和静态 checks/edges 做乘法加权。

本次数据给出的主要优化信号：

1. GrhSIM 的 supernode 数不是问题本身：总数比 GSim 少 `14.6%`。
2. 静态 unique outgoing activation edge 总量也不是数量级问题：GrhSIM 只比 GSim 多 `5.9%`。
3. activation checks 是更强信号：静态为 `2.83x`，runtime 加权后为 `6.38x`。
4. commit supernode 是 checks 的主热点：只占 `0.69%` supernode，却贡献 `53.37%` weighted checks。
5. commit->compute fanout 是 edge 动态压力主热点：commit 只贡献 `0.96%` activation_count，却贡献 `40.04%` weighted edges。
6. GrhSIM runtime activation tail 更重：最大 activation_count `200,653`，约为 GSim 最大值 `50,101` 的 `4.00x`。
7. 后续分析应优先看：
   - top commit supernode `71871` / `72080` 的 value 检测与 commit->compute fanout；
   - compute supernode `311` 的高 `compute_compute` outgoing edge；
   - 为什么少数 GrhSIM supernode 会在 50k guest cycle 内出现 `~200k` activation_count。

## 11. 复现和校验命令

解析 summary：

```bash
python3 -c 'import json,pathlib; base=pathlib.Path("build/xs/stats_coremark50k_20260708_fix_stats_dump"); names=["gsim_static_stats.json","gsim_runtime_stats.json","grhsim_static_stats.json","grhsim_runtime_stats.json"]; 
for name in names:
    p=next(base.rglob(name)); d=json.load(open(p))
    print(name); print(p); print(d["format"]); print(d["sim"], d["top"]); print(d["summary"]); print(len(d["supernodes"]))'
```

join key 校验：

```bash
python3 -c 'import json,pathlib; base=pathlib.Path("build/xs/stats_coremark50k_20260708_fix_stats_dump"); pairs=[("gsim","gsim_static_stats.json","gsim_runtime_stats.json"),("grhsim","grhsim_static_stats.json","grhsim_runtime_stats.json")]
for sim,sname,rname in pairs:
    sp=next(base.rglob(sname)); rp=next(base.rglob(rname))
    sd=json.load(open(sp)); rd=json.load(open(rp))
    sk={(x["sim"],x["top"],x["supernode_id"]) for x in sd["supernodes"]}
    rk={(x["sim"],x["top"],x["supernode_id"]) for x in rd["supernodes"]}
    print(sim, len(sk), len(rk), sk==rk)'
```

确认没有 TSV：

```bash
find build/xs/stats_coremark50k_20260708_fix_stats_dump \
  -name '*stats*.tsv' -o -name '*activity*.tsv'
```
