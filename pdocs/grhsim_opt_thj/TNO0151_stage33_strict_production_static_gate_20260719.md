# TNO0151 Stage 33 strict production static gate

日期：2026-07-19

状态：final editable binding reinstall 后，fresh current-default SimTop strict emit 成功；完整
manifest FNV、252 个 cohort 和全部结构绝对值通过 production fail-closed gate。activity schedule
与 emitter stats 均和 current default byte-identical，实际改动只在生成 C++ lowering。O3/archive、
功能与 walltime 另行归档，本文不作默认采用结论。

## 1. Fresh command boundary

输入固定为：

| input | SHA256 |
| --- | --- |
| Stage22 filelist | `68cbb67e3350ed8e59318f51939603e9aa694b1e39dfa2e63c115524906d3d28` |
| p050 post-stats JSON | `165f5c58e06d0d8a483c49d80733f5a7a211bc27772dac5b1608b0c177a0b573` |
| current read args | `b0fade4b968e4491b42fc6693eea0aa65d6a8b4829c2c5d902175acc647414d5` |
| current 50k fire profile | `308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a` |

输出目录此前不存在：

```text
build/xs_activity_stage33_same_batch_cohort_strict_20260719/
```

命令先 source `env.sh`，清除所有旧 `WOLVRIX_XS_GRHSIM_*`、`WOLVRIX_GRHSIM_*`、
`GRHSIM_*` 和 `EMU_RUNTIME_PROFILE`，随后只注入 current canonical common env 与：

```text
WOLVRIX_XS_GRHSIM_SAME_BATCH_ACTIVATION_COHORT_POLICY=strict
WOLVRIX_XS_GRHSIM_SAME_BATCH_ACTIVATION_COHORT_PROFILE_PATH=<current fire TSV>
```

日志首行确认 commit cap/direct/bypass/DP/topo 等继续来自 C++ default；XS 没有附带其它实验
policy。full-active-word consume 的现有 wrapper 显式 false 与 C++ false 同值，strict 也有独立
fail-closed 检查。

## 2. Emit result

fresh emit exit0，script total=`260,498 ms`，`/usr/bin/time` wall=`4:22.30`，max RSS=
`28,066,148 KiB`。raw：

```text
build/logs/xs/stage33_same_batch_cohort_strict_emit_20260719.log
sha256=b070de0c26e4a5b98fe702718c6b3861b9ec064079cd596e7a3789a82bf145de
bytes=122795
```

activity schedule absolute identity：

```text
supernodes=63709
compute/commit=63241/468
dag_edges=527990
boundary_values=1000463
boundary_activation_edges=1983326
compute/commit value pairs=1721698/261628
```

| artifact | SHA256 | bytes | vs current default |
| --- | --- | ---: | --- |
| activity stats | `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` | `5382` | `cmp=0` |
| emitter stats | `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b` | `418` | `cmp=0` |

这里的 raw activity BAE 仍是 `1,983,326`，因为 strict 是 final-emitter overlay，不改 IR 或
activity-schedule JSON；下面的 `2,169` 是在生成 ordinary activation fanout 中实际删除的
follower edges，二者不能混写。

## 3. Manifest and selection

production summary：

```text
profile compute/ignored commit rows=63241/468
compute supernodes=63241
pure boundary-only=14814
signature runs=252
selected cohorts/members/ops=252/902/88334
control/projected BAE=3619/1450
BAE saved=2169
control/projected entries=342/252
control/projected chunks=257/252
manifest_fnv1a64=2221bbc3ffd74a71
production_request=true
production_witness_valid=true
```

reject absolute counts 与 Stage32 current replay 一致：commit0、impure306、input2354、
state41152、memory2050、event801、empty_source12、source_owner0、source_order1752、profile0、
noncontiguous0。

strict overlay absolute result：

```text
cohorts=252
members=902
leaders=252
followers=650
removed_follower_bae=2169
fullpass_unchanged=true
commit_unchanged=true
runtime_probe_compiled=false
```

manifest FNV 与 [TNO0150](./TNO0150_stage33_strict_implementation_manifest_and_focused_gate_20260719.md)
独立 v2 oracle 精确相同，不是只检查 cohort11 或总行数。scan log
明确 `scan_no_mutation=true emit_mutation=strict_overlay no_mutation=false`。

## 4. Generated source boundary

historical same-config oracle 路径为
`build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit`；它与 strict 都有
132 CPP + 2 HPP=`134` 个生成源码/header，无文件缺失。fresh same-commit control 尚未生成，
因此这里的 oracle 只作静态解释，不冒充后续 formal A：

| field | historical same-config oracle | strict | delta |
| --- | ---: | ---: | ---: |
| files | `134` | `134` | `0` |
| bytes | `1,356,643,748` | `1,356,609,139` | `-34,609` |
| byte-identical files | - | `75` | - |
| changed files | - | `59` | - |

strict codegen markers 的绝对数：

```text
leader blocks=252
follower payload blocks=650
cross-word accumulator declarations=90
sched CPP containing leader blocks=39
cohort runtime counter source/header files=0
compute word helper references=0
kRuntimeProfileCompiled=false
```

59 个 changed file 包含 cohort target batch、source fanout 和 initial seed/eval；只有 39 个含
leader payload 是预期的，不能把 changed-file 数误写成 cohort batch 数。source/header 总量
小幅下降也只描述静态边界，不代替 O3 `.text` 或 50k walltime。

## 5. 后续

1. fresh O3/archive 并记录 archive SHA/bytes、ELF sections；
2. 独立 difftest link；
3. per-node fresh first-touch inode 上 100/10k/50k 功能；
4. fresh same-commit control 与 strict 的 whole-node gated balanced walltime。
