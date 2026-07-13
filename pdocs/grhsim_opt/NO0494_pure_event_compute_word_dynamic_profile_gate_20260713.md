# NO0494 Pure-event compute-word dynamic profile gate

日期：2026-07-13

## 1. Implementation

按 [NO0493](./NO0493_pure_event_compute_word_dynamic_profile_plan_20260713.md) 在 `wolvrix` 子仓库
`f9475be` 实现默认关闭的：

```text
EmitOptions attribute: pure_event_compute_word_profile
Environment:          WOLVRIX_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE
TSV override:         WOLVRIX_GRHSIM_PURE_EVENT_WORD_TSV
```

profile 与 bypass 复用唯一 `eligiblePureEventComputeWordExpr`，该 helper 同时封闭 compute phase、dispatch/clear equality、
full-active-word consume、split-helper allow gate 与 GRH purity/event analysis。emit-time 按 batch 计算 static eligible words；runtime
只在 active outer guard 内、underlying clear 后统计 event hit/miss。

profile-only 在 `runtime_profile_enabled_` 为真时才读取 event 并计数，不生成 bypass marker。profile+bypass 为每个 eligible word
生成一个 hit temporary，同时供计数与 wrapper 使用。

## 2. Generated API and dump

profile 编译开启时生成：

- `kPureEventComputeWordEligibleCount`；
- `PureEventComputeWordProfile { eligibleWordCount, activeHitCount, activeMissCount }` 与 getter；
- 两个 `kBatchCount` hit/miss arrays；
- init 清零；
- 复用既有 `set_runtime_profile_enabled` / `dump_runtime_profile`。

独立 TSV 为 `batch_id/eligible_words/active_hit/active_miss/active_total`。dump 标准输出同时报告 rows、eligible、hit、miss、
total 和 miss ratio。只有 per-supernode profile 或本 profile 至少一个编译开启时才生成 runtime enable field；默认 source 不增加状态。

## 3. Synthetic result

16-task fixture 的 profile-only 与 profile+bypass 都得到：

```text
eligible=2 hit=4 miss=6 total=10 miss_ratio=0.600000
```

TSV 精确为：

```text
batch_id  eligible_words  active_hit  active_miss  active_total
4         1               2           3            5
5         1               2           3            5
```

计数在初始化 eval 后启用；五次受测 eval 中两个 posedge 各命中两个 words，三个 data/negedge miss 各消费两个 words。
getter、日志与 TSV 三处逐项闭合，`active_total = hit + miss`。

结构结果：

- default、bypass=0、profile=0 的全部 generated source byte-identical；
- profile-only 有 2 对 increments、0 marker；
- profile+bypass 有 2 increments、2 marker、2 hit temporaries；
- once-only、multi-event、commit、full-active-word consume static eligible 均为 0；
- fullpass 不新增 marker/increments；原 per-supernode runtime-profile fixture 继续通过。

## 4. Build and regression

首次 test target build 中 emitter library 已成功，但新增 fixture lambda 因补参数时丢失显式
`std::optional<std::filesystem::path>` 返回类型而在 test C++ 编译失败；没有生成/运行无效模型。恢复显式返回类型后：

```text
emit-grhsim-cpp             PASS  240.38 s
emit-grhsim-cpp-memory-fill PASS    5.05 s
```

generated profile-only/profile+bypass harness 均编译运行通过，`git diff --check` 通过。

## 5. Decision

dynamic profile gate 通过，进入 fresh SimTop profile-only emit/build/function gate。当前仍不打开 bypass 做性能结论；先量化生产
eligible words、active miss ratio 与 batch 分布，并解释相对 NO0484 的静态 107 words 差异。
