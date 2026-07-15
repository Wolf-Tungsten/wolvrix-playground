# TNO0055 Stage 6 frozen-batch cost-proxy fix

日期：2026-07-15

## 1. 精确复现

承接 [TNO0054](./TNO0054_stage6_production_probe_and_first_targeted_gate_20260715.md)，增强后的 metadata diagnostic 在相同 current-default checkpoint 上复现首次 targeted failure：

```text
batch             74
phase             commit -> commit
index             74 -> 74
op count          4087 -> 4087
word count        1 -> 1
member count      1 -> 1
estimated lines   71228 -> 71234
```

变化精确限于 `estimatedLines +6`；index、phase、op count、word 数与成员数均保持一致。

## 2. Root cause

commit write 的行数估算会对 `stateHeadSupernodesBySymbol` 调用 activation mask/chunk/table estimator。targeted 保持 commit supernode 和 active ID 不变，但重排了部分 compute reader active ID，因此同一批 reader heads 的 word grouping 可能改变，进而改变 commit activation 的行数代理。

`estimatedLines` 只在 baseline 第一次贪心划分 batch 时使用；frozen rebuild 后它不参与生成语义、helper 选择或 batch 边界。要求 rebuilt 值与 baseline byte-exact 会把预期的 active-ID code-shape 变化误判为结构破坏。

## 3. Validator 修正

frozen rebuild 继续严格验证：

- batch count、index、phase 与 op count；
- 逐 batch member set；
- active-word slot multiset；
- commit order；
- rebuilt boundary/input/state/memory active-ID vectors；
- 最终 production pure-word exact coverage。

`estimatedLines` 不再触发提前失败，而是完整扫描所有 batch 后记录：

```text
frozen_batch_baseline_estimated_lines
frozen_batch_rebuilt_estimated_lines
frozen_batch_estimated_line_changed_batch_count
frozen_batch_max_abs_estimated_line_delta
```

probe 不执行 rebuild，上述四项为 `0`，表示 not applicable。targeted stderr summary 同步打印这四项，便于大图审计。rebuilt batch 保留真实重算值，不伪装为 baseline cost。

## 4. Regression gate

新增 31-task 小图 fixture，稳定制造 compute reader word grouping 变化，同时保留两个 commit 的 membership、active-word slot 与 `clk -> aux` 顺序：

```text
pure words                         0 -> 3
frozen estimated lines             998 -> 1001
changed estimated-line batches     1
max absolute line delta             3
off/targeted harness                identical
```

验证结果：

```text
wolvrix-lib incremental build       PASS
emit-grhsim-cpp object build        PASS
emit-grhsim-cpp full executable     PASS (exit 0)
git diff --check                    PASS
independent read-only review        no blocker
```

## 5. 当前决策

本修正只移除一个不成立的 cost-proxy identity 假设，没有放宽结构或仿真语义门禁。policy 保持默认 `off`，继续重新运行 production targeted。
