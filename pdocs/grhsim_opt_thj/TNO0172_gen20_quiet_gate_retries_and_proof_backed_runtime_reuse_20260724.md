# TNO0172 gen20 quiet-gate retries and proof-backed runtime reuse

## 1. 范围

本文增量记录 [TNO0171](./TNO0171_simpletes_18pct_ablation_design_and_static_attribution_20260724.md) 启动后的 gen20/no-cold-hint fresh 消融前两次 runtime admission 失败，以及为避免重复约 80--90 分钟 clone/emit/build 而新增的 proof-backed runtime-only retry。两次失败均为外部负载导致的 infrastructure retryable，没有形成 SimTop 50k walltime 样本，不能评价候选性能。

候选保持不变：

```text
label: gen20/no-cold-hint
full digest: 6397b7de38d265552feaaaa34ab5f79bfb53f2bd53bf191a46f0f3ad0fd4fb45
control generated fingerprint: 57819a3d9f1165af
candidate generated fingerprint: f618a36bf55a531d
patch files: 1 (lib/emit/grhsim_cpp.cpp)
enable options: active_mask_gap_pack_policy=targeted-direct
```

## 2. Full attempt 1

第一轮完整 evaluator 用时 `5,403.366719 s`。clone、unpatched-options attribution、disabled identity、enabled build、focused tests 和 100/10k 功能均完成，随后动态选择：

```text
CCD: node0:64-71,256-263
CPU: 68
sibling: 260
NUMA: 0
```

初始 whole-CCD gate 通过：

| 指标 | 绝对值 | 门槛 |
| --- | ---: | ---: |
| count | `16` | `16` |
| mean idle | `98.997500%` | `>=98.000000%` |
| min idle | `97.320000%` | `>=95.000000%` |
| target idle | `99.330000%` | `>=98.000000%` |
| sibling idle | `100.000000%` | `>=98.000000%` |

但临运行 atomic gate-to-run 复核失败：

| 指标 | 绝对值 | 相对门槛 |
| --- | ---: | ---: |
| mean idle | `97.416875%` | 低 `0.583125` 个百分点 |
| min idle | `87.040000%` | 低 `7.960000` 个百分点 |
| target idle | `99.330000%` | 高 `1.330000` 个百分点 |
| sibling idle | `99.330000%` | 高 `1.330000` 个百分点 |

结果为 `external load prevented the fixed CCD pre-gate`。accepted 50k samples=`0`，walltime=`N/A`；地址随机化、PMU 与运行功能审计没有被伪造为通过。

## 3. Full attempt 2

同一 digest 的第二轮 standalone evaluator 用时 `5,210.357311 s`。由于旧入口每次重建 slot，本轮再次完成三份 emitter/build/function gate。runtime survey 遍历 `24` 颗 CCD，没有一颗满足：

```text
3s whole-CCD count=16
mean idle >= 98%
min idle >= 95%
target idle >= 98%
sibling idle >= 98%
```

结果为 `no dynamically discovered CCD passed the strict quiet-window gate`。accepted 50k samples=`0`，walltime=`N/A`。这仍是纯 infrastructure retryable，不是 candidate invalid，也没有启动 gen24。

## 4. 重复构建根因

`GRHSIM_INFRA_RETRIES=4` 已在每个 full evaluator 内提供最多五次 runtime admission，但五次全部耗尽后，standalone 进程退出。旧 evaluator 的下一次进程会重建 candidate slot；旧 manifest 只记录 generated fingerprint，没有把 candidate ELF、runtime inputs、`env.sh` 和完整 gate incarnation 绑定到内容哈希，因此不能把旧路径直接当作正式 artifact 复用。

直接复用会有 wrong-binary、旧 clone 错配和 manifest 撕裂风险，所以前两轮 artifact 没有被降级绕过 gate。第二轮结束后才合入新的 fail-closed 契约，旧结果按设计不能迁移。

## 5. Proof-backed runtime reuse

SimpleTES commit `fc17b90` 新增：

1. full evaluator 只有在 attribution、default-off、focused tests、100/10k function 和 enabled attribution 全部通过后，才原子写 candidate proof marker；
2. marker 绑定 full candidate digest、patch SHA、canonical options、完整 commits、repo、generated/build/toolchain fingerprints、candidate ELF/image/NEMU 路径与完整 SHA-256，以及 candidate/control `env.sh` 路径与 SHA-256；
3. 每次 runtime 写唯一 immutable attempt，runtime/evaluation JSON 先原子发布，compatibility latest 随后发布，`complete.json` 作为严格最后 commit point 并记录两份 JSON 与 candidate proof SHA；
4. `retry_runtime.py` 持有同一 slot flock，重新验证以上身份后调用 evaluator 原生 runtime、五次 admission、ABBA/BAAB promotion、score 和 manifest 路径；它不能 clone、emit、build，也不会 fallback rebuild；
5. slot path/symlink、lock inode replacement、candidate binary/env mutation、schema/type 混淆、alias 撕裂、incomplete attempt 和 retry-of-retry 均 fail closed。

验证绝对结果：

```text
tests/test_grhsim_bench.py: 53 passed in 0.31 s
py_compile: PASS
retry_runtime.py --help: PASS
git diff --check: PASS
```

## 6. 第三轮状态

`2026-07-24 18:45 +08:00`，已用 SimpleTES `fc17b90` 启动第三轮 gen20 full evaluator。它仍必须重新完成一次 full gate，才能建立新 proof。若本轮得到有效 ABBA/BAAB，直接进入 gen24；若仅因 quiet CCD 返回 retryable，则后续只运行 proof-backed runtime retry，不再重复构建。

当前不修改 wolvrix 代码或默认配置，也没有可用于默认决策的 fresh walltime。

## 7. 权威产物

```text
/tmp/grhsim-ablation-20260724/candidates/gen20_no_cold_hint.txt
/tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0/results/evaluation_6397b7de38d26555.json
SimpleTES/datasets/grhsim/simtop_50k/retry_runtime.py
```
