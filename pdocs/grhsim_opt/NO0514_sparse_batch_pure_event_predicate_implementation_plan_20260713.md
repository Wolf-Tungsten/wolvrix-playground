# NO0514 Sparse-batch pure-event predicate implementation plan

日期：2026-07-13

## 1. Candidate shape

承接 [NO0513](./NO0513_sparse_batch_volatile_threshold_audit_gate_20260713.md)，不新增用户开关，直接改进现有默认关闭的
`pure_event_compute_word_bypass=1` 输出形态：

```text
eligible pure-event words in batch <= 2:
  const volatile bool hit = <exact event equality>;
  if (hit) { ... entries/payload/restore ... }

eligible pure-event words in batch > 2:
  if (<exact event equality>) { ... entries/payload/restore ... }
```

阈值是 emitter 内部常量，只读取当前 `ScheduleBatch::Word` 结构和既有 eligibility helper；不引用 SimTop batch id、active-word
index 或编译后 object delta。NO0513 后补的 14 个真实 volatile-bool objects 相对 NO0357 为
text/instructions/memory/jumps=`-1,950/-325/-227/-91`，相对 plain 为 `-12,095/-1,861/-1,358/-244`，calls 不变。

## 2. Emitter changes

在每个 batch 开始 emit 前，用 `word.helperChunks.empty()` 作为与现有 `allowPureEventBypass` 一致的 gate，统计 eligible words。
只有 bypass 开启且 count `1..2` 时使用 opaque local hit：

- bypass-only：新增唯一 `const volatile bool grhsim_pure_event_word_hit_<word>`；
- profile+bypass：沿用共享 hit temporary，但 sparse 时改为 volatile，profile counter 与 wrapper 读取同一值；
- profile-only、bypass disabled/default、fullpass、split helper 和不 eligible words 均不改变 generated source；
- clear 仍在 wrapper 前，restore 仍在 wrapper 内，inner exact-event guards 与 payload/order 不改。

## 3. Synthetic gates

扩展 pure-event fixture 以显式构造同一 batch 内 1/2/3 个 eligible words：

1. one/two-word batches 必须每个 wrapper 都有 volatile hit；
2. three-word batch 必须有三个 wrappers、0 volatile hit，并保留 direct outer expression；
3. 现有 homogeneous fixture、combined profile+bypass 和 hit/miss/profile harness 继续通过；
4. default、explicit bypass=0、profile=0 source 继续 byte-identical；
5. once-only、multi-event、commit、fullpass、full-active-word consume 等负向门禁不变。

完成定向 `emit-grhsim-cpp` 后再跑 memory-fill emitter regression。通过后提交 wolvrix 子仓库与顶层 pointer/docs，随后 fresh
SimTop source 应精确得到 14 volatile batches/20 volatile words、其余 87 direct wrappers，再进入 O3 build/function。

本篇只声明实现与验证方案，尚未修改 emitter。
