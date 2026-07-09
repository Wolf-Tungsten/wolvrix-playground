# NO0221 NO0217 Plain BAE Artifact Rebuild

记录日期：2026-07-07

关联：[`NO0217`](./NO0217_gsim_grhsim_bae_commit_split_classification_20260706.md)、[`NO0218`](./NO0218_grhsim_compute_node_granularity_profile_20260706.md)

状态：按 NO0217 的 BAE 统计口径重建构件，但 GrhSIM 使用当前仓库 plain path，不恢复 CBAW / iter8 / iter16 / iter32 变体。

## 1. 重建范围

本轮仓库 HEAD：

```text
e2de687 refactor(transform): keep activity schedule on plain path
```

已按 `env.sh.template` 恢复本地 `env.sh`，并用该环境执行重建。`env.sh`、`build/`、`tmp/` 均被 ignore，不进入版本提交。

重建出的 NO0217 相关构件：

| 路径 | 说明 |
| --- | --- |
| `build/xs/rtl/rtl/SimTop.fir` | XiangShan FIRRTL 输入，`make xs_rtl` 生成 |
| `build/xs/rtl/rtl/SimTop.sv` | XiangShan SV 输入，`make xs_rtl` 生成 |
| `build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json` | 当前 plain GrhSIM activity-schedule supernode stats |
| `build/xs/grhsim/grhsim_emit/wolvrix_xs_stats.json` | plain GrhSIM post `reg-to-mem` stats |
| `build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json` | plain GrhSIM pre `reg-to-mem` resume artifact |
| `build/xs/grhsim/wolvrix_xs_post_stats.json` | plain GrhSIM post-stats resume artifact |
| `build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json` | rebuilt GSim `Final` stats |
| `tmp/no0214_gsim_rtprof_20260703/gsim-compile/model/SimTop_supernode_stats.json` | restored NO0217 strict GSim comparison path, copied from the rebuilt GSim stats |

未重建：

| 路径 | 原因 |
| --- | --- |
| `build/xs/grhsim_iter8/...` | 本轮要求使用 plain，不使用 CBAW / iter 变体 |
| `build/xs/grhsim_iter16/...` | 同上 |
| `build/xs/grhsim_iter32/...` | 同上 |

## 2. 命令记录

```bash
source env.sh
make py_install
make xs_rtl RUN_ID=no0221_plain_no0217_rebuild_20260707
make -C reference/gsim build-gsim
WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1 \
  make xs_wolf_grhsim_emit \
  RUN_ID=no0221_plain_no0217_rebuild_20260707 \
  XS_WOLF_GRHSIM_ENABLE_STATS=1 \
  XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0
reference/gsim/build/gsim/gsim \
  --supernode-max-size=15 \
  --cpp-max-size-KB=8192 \
  --sep-mod=__DOT__ \
  --sep-aggr=__DOT__ \
  --dump-stats-json \
  --dump-stages=Final \
  --dir build/xs/gsim/gsim-compile/model \
  build/xs/rtl/rtl/SimTop.fir
mkdir -p tmp/no0214_gsim_rtprof_20260703/gsim-compile/model
cp build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json \
  tmp/no0214_gsim_rtprof_20260703/gsim-compile/model/SimTop_supernode_stats.json
```

关键生成时间：

| 产物 | 时间 |
| --- | --- |
| `build/xs/grhsim/grhsim_emit/activity_schedule_supernode_stats.json` | `2026-07-07 12:52:04 +0800` |
| `build/xs/gsim/gsim-compile/model/SimTop_supernode_stats.json` | `2026-07-07 13:09:52 +0800` |
| `tmp/no0214_gsim_rtprof_20260703/gsim-compile/model/SimTop_supernode_stats.json` | `2026-07-07 13:11:48 +0800` |

## 3. Plain BAE 主表

GSim rebuilt stats 仍是 strict 口径：

| 指标 | 数值 |
| --- | ---: |
| GSim `activation_edges` | `1378665` |
| GSim `boundary_activation_edges` | `1367268` |
| GSim `self_activation_edges` | `11397` |

按 NO0217 口径，后续对比使用 GSim strict BAE `1367268`。

| 指标 | 数值 |
| --- | ---: |
| GSim strict BAE | `1367268` |
| GrhSIM plain BAE | `2446334` |
| GrhSIM plain - GSim | `1079066` |
| GrhSIM plain / GSim | `1.789x` |
| GrhSIM plain over GSim | `+78.92%` |

按 target kind 拆分 plain GrhSIM BAE：

| target kind | BAE | 占 GrhSIM BAE |
| --- | ---: | ---: |
| compute -> compute | `2095811` | `85.67%` |
| compute -> commit | `350523` | `14.33%` |
| total | `2446334` | `100.00%` |

因此：

- commit 分离解释 plain GrhSIM 总 BAE 的 `14.33%`。
- 如果只看 plain GrhSIM 相比 GSim 多出来的 `1079066` 条 BAE，commit 分离解释 `32.48%`。
- 扣掉 commit 分离后，plain GrhSIM compute->compute 仍有 `2095811` 条，比 GSim strict BAE 多 `728543` 条，仍是 GSim 的 `1.533x`。

结论与 NO0217 保持一致但幅度更强：commit 分离是固定贡献项，但当前 plain path 的主要 gap 仍在 compute->compute boundary propagation 和 value-target multiplicity。

## 4. Source Kind 分类

按 source group 粗分：

| source group | BAE | 占 GrhSIM BAE |
| --- | ---: | ---: |
| other compute | `2302919` | `94.14%` |
| state read | `130103` | `5.32%` |
| constant | `12470` | `0.51%` |
| memory read | `842` | `0.03%` |

Top source kind：

| source kind | BAE | 占 GrhSIM BAE | source values |
| --- | ---: | ---: | ---: |
| `kAnd` | `506611` | `20.71%` | `238967` |
| `kLogicAnd` | `420679` | `17.20%` | `233073` |
| `kAssign` | `243984` | `9.97%` | `74194` |
| `kMux` | `220817` | `9.03%` | `187106` |
| `kSliceStatic` | `195891` | `8.01%` | `91858` |
| `kEq` | `178703` | `7.30%` | `75595` |
| `kRegisterReadPort` | `130103` | `5.32%` | `129900` |
| `kOr` | `117741` | `4.81%` | `59089` |
| `kLogicOr` | `96728` | `3.95%` | `92948` |
| `kSliceDynamic` | `67010` | `2.74%` | `23000` |
| `kConcat` | `59732` | `2.44%` | `24411` |
| `kNot` | `57301` | `2.34%` | `16767` |

## 5. Multiplicity 分类

other-compute 内部：

| 指标 | 数值 | 占比口径 |
| --- | ---: | ---: |
| single-target values | `743176` | `56.22%` of all boundary values |
| single-target edges | `743176` | `30.38%` of GrhSIM BAE |
| multi-target values | `439125` | `33.22%` of all boundary values |
| multi-target edges | `1559743` | `63.76%` of GrhSIM BAE |
| other-compute unique source-target pairs | `697923` | `30.31%` of other-compute edges |
| duplicate edges vs unique pairs | `1604996` | `69.69%` of other-compute edges |

补充指标：

| 指标 | 数值 |
| --- | ---: |
| boundary_values | `1321994` |
| commit_input_root_values | `350578` |
| compute_commit_value_pairs | `350523` |
| direct_source_inputs_to_commit_supernodes | `13343` |

## 6. 与 NO0217 老数据差异

| 指标 | NO0217 | 本轮 plain rebuild | 差异 |
| --- | ---: | ---: | ---: |
| GSim strict BAE | `1367270` | `1367268` | `-2` |
| GSim activation_edges | `1378667` | `1378665` | `-2` |
| GSim self_activation_edges | `11397` | `11397` | `0` |
| GrhSIM BAE | `2253277` | `2446334` | `+193057` |
| GrhSIM compute->compute | `1902754` | `2095811` | `+193057` |
| GrhSIM compute->commit | `350523` | `350523` | `0` |

GSim rebuild 与 NO0217 几乎一致，只少 `2` 条 strict BAE；plain GrhSIM 相比 NO0217 老 GrhSIM 数据增加的 `193057` 条 BAE 全部来自 compute->compute，commit 项不变。

这说明本轮 plain 口径下，后续追 gsim / grhsim 性能差距时，应优先继续拆 plain compute->compute 的 value-target multiplicity，而不是把 commit 分离作为主因。

## 7. 当前 50k CoreMark Runtime 对比

测量日期：2026-07-07。

构建说明：

- GSim 和 GrhSIM 构建可以并行，但 GrhSIM 使用独立 `XS_WORK_BASE=build/xs_grhsim_perf`，避免同时写 `build/xs/rtl`。
- runtime 测量串行执行，避免两边同时运行造成 CPU / memory bandwidth 干扰。
- GSim `emu`：`build/xs/gsim/emu`。
- GrhSIM `emu`：`build/xs_grhsim_perf/grhsim/emu`。

负载沿用之前 XiangShan CoreMark 测试负载：

| 项 | 配置 |
| --- | --- |
| image | `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin` |
| difftest ref | `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so` |
| max cycle | `50000` |
| progress interval | `25000` |
| waveform | off |
| commit trace | off |
| log begin/end | `0` / `0` |

执行命令：

```bash
source env.sh
/usr/bin/time -f 'elapsed_sec=%e user_sec=%U sys_sec=%S maxrss_kb=%M' \
  -o build/logs/xs/xs_gsim_no0221_plain_perf_gsim_50k_20260707.time \
  make run_xs_gsim_emu \
  RUN_ID=no0221_plain_perf_gsim_50k_20260707 \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0

/usr/bin/time -f 'elapsed_sec=%e user_sec=%U sys_sec=%S maxrss_kb=%M' \
  -o build/logs/xs/xs_wolf_grhsim_no0221_plain_perf_grhsim_50k_20260707.time \
  make run_xs_wolf_grhsim_emu \
  RUN_ID=no0221_plain_perf_grhsim_50k_20260707 \
  XS_WORK_BASE=build/xs_grhsim_perf \
  XS_SIM_MAX_CYCLE=50000 \
  XS_PROGRESS_EVERY_CYCLES=25000 \
  XS_COMMIT_TRACE=0 \
  XS_WAVEFORM=0 \
  XS_WAVEFORM_FULL=0 \
  XS_LOG_BEGIN=0 \
  XS_LOG_END=0
```

日志：

| 项 | 路径 |
| --- | --- |
| GSim run log | `build/logs/xs/xs_gsim_no0221_plain_perf_gsim_50k_20260707.log` |
| GSim host time | `build/logs/xs/xs_gsim_no0221_plain_perf_gsim_50k_20260707.time` |
| GrhSIM run log | `build/logs/xs/xs_wolf_grhsim_no0221_plain_perf_grhsim_50k_20260707.log` |
| GrhSIM host time | `build/logs/xs/xs_wolf_grhsim_no0221_plain_perf_grhsim_50k_20260707.time` |

仿真日志内 progress / final 结果：

| simulator | point | model cycles | instr | commit pc | trap pc / limit pc | host ms | cycles/s | GrhSIM / GSim |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |
| GSim | 25k progress | `25000` | `20049` | `0x8000043a` | `0x80000442` | `19719` | `1267.8` | `1.000x` |
| GrhSIM | 25k progress | `25000` | `20048` | `0x8000043c` | `0x80000440` | `129428` | `193.2` | `6.564x` |
| GSim | 50k progress | `50000` | `73584` | `0x800012f8` | `0x8000131e` | `43462` | `1150.4` | `1.000x` |
| GrhSIM | 50k progress | `50000` | `73580` | `0x800012f8` | `0x80001312` | `292009` | `171.2` | `6.719x` |

最终退出统计：

| simulator | final host time | instrCnt | cycleCnt | IPC | exit |
| --- | ---: | ---: | ---: | ---: | --- |
| GSim | `43464ms` | `73584` | `49998` | `1.471739` | `EXCEEDING CYCLE/INSTR LIMIT at pc = 0x8000131e` |
| GrhSIM | `292022ms` | `73580` | `49996` | `1.471718` | `EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312` |

`/usr/bin/time` 交叉核对：

| simulator | elapsed sec | user sec | sys sec | max RSS |
| --- | ---: | ---: | ---: | ---: |
| GSim | `43.51` | `43.21` | `0.08` | `55296 KB` |
| GrhSIM | `292.11` | `291.73` | `0.15` | `132096 KB` |

结论：

- 以仿真日志 final host time 计算，当前 plain GrhSIM 在该 50k CoreMark 负载上为 `171.2 cycles/s`，GSim 为 `1150.4 cycles/s`，GrhSIM 慢 `6.719x`。
- `/usr/bin/time` 的 wall time 比值为 `292.11 / 43.51 = 6.714x`，与日志内 host time 基本一致。
- 两边都在 cycle limit 退出且 difftest 未报错；cycle boundary 上 GrhSIM 少提交 `4` 条指令，最终 limit PC 也不同，后续若做严格等价采样，应改用相同 commit count 或更早的 deterministic checkpoint。
- runtime gap `6.719x` 明显大于本文件 BAE gap `1.789x`。因此 BAE 数量差异不能单独解释当前性能差距；下一步需要继续拆 GrhSIM compute->compute BAE 的实际执行成本，并同时检查生成 C++ 的 instruction mix、cache locality、调度批次和单个超大 commit/sched 单元的热点。
