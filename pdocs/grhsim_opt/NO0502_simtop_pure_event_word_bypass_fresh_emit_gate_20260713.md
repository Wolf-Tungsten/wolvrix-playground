# NO0502 SimTop pure-event word bypass fresh emit gate

日期：2026-07-13

## 1. Fresh configuration and flow

按 [NO0501](./NO0501_simtop_pure_event_word_bypass_fresh_plan_20260713.md) 从同一 checkpoint/read-args fresh
执行 production bypass emit。direct state read 与 schedule 配置保持不变，profile/per-supernode profile 均关闭。

```text
output:
  build/xs_grhsim_no0501_pure_event_bypass_20260713/grhsim/grhsim_emit
log:
  build/logs/xs/xs_wolf_grhsim_build_no0502_pure_event_bypass_emit_20260713.log
```

受主机 load 影响，本轮 checkpoint/reg-to-mem/schedule/emit 分别约 `70.433/173.798/266.084/124.739 s`，reported
total `635.056 s`、wall `640.98 s`、peak RSS 27.78 GiB、exit 0。时间只作执行记录。

## 2. Structure identity

schedule stats SHA256 再次为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

compute/commit supernodes、DAG、boundary 与 NO0357/NO0496 完全一致。direct-state-read 仍为
reads/canonical/aliases=`75,830/40,108/35,722`，removed source heads/consumer heads=`37,672/39,602`。

## 3. Production source delta

相对 NO0357 no-bypass source：

```text
generated files          154 / 154
changed files             22 sched only
byte-identical files     132
markers                  107
marker batches            22
sched added lines        321 = 107 * 3
sched deleted lines        0
profile references         0
```

marker batch distribution与 NO0496 profile static rows 22/22 逐行一致；batch 35/58/21 分别为 `37/21/8`。generated
总 bytes 从 `1,357,263,998` 增至 `1,357,283,472`，仅 `+19,474`。

每个 diff 只增加 clear 后 marker + outer exact-event `if`，以及原 restore 后 closing brace；entry tests、payload、内部
exact-event guards 和 restore source 均未删除或改序。header/state/eval/init 全部 byte-identical，证明 profile 状态没有泄漏到
production candidate。

## 4. Analysis-report correction

首次 marker-distribution shell 对 `rg -c` 的 no-match exit 未把空输出归零，临时报告混入 95 个空 batch 并产生 shell
integer warnings。generated source 未被修改。已覆盖重算为只含 22 个 nonzero batches，rows=22/markers=107，并与 NO0496
逐行 diff 为 0；后续只使用修正报告。

## 5. Decision

fresh source gate 通过。下一步标准 Clang O3 build/link，比较 NO0357 baseline 的 text/instruction/object delta；通过后执行
100/10k/50k CoreMark/NEMU 功能门禁。
