# NO0511 Batch 27 event-predicate codegen probe gate

日期：2026-07-13

## 1. Batch 27 variants

按 [NO0510](./NO0510_batch27_event_predicate_codegen_probe_plan_20260713.md)，三个 generated-copy 变体均以 candidate
同一 PCH、Clang 21.1.5、C++20 `-O3` 编译成功。相对 NO0357 batch 27 object：

| Variant | Text bytes | Instructions | Memory forms | Jumps | Calls |
|---|---:|---:|---:|---:|---:|
| plain production | +11,477 | +1,783 | +1,164 | +236 | 0 |
| `volatile_ref` | +11,481 | +1,785 | +1,164 | +236 | 0 |
| `volatile_copy` | -5 | 0 | -6 | -4 | 0 |
| noinline predicate | +10,319 | +1,754 | +1,126 | +234 | +2 |

`const volatile` reference 仍读取原对象，Clang 保留了与内部 field checks 的相关性；noinline control 也没有消除主要 cliff，
并引入 dynamic calls。只有 local volatile copy 阻断值传播后使 batch 27 回到 baseline 附近，证明 NO0503 的整函数跳变
由 outer predicate 的编译期传播触发，而不是 wrapper 本身线性增加 11 KiB。

`volatile_copy` 仍保持同一 edge value 和 equality，payload、entry、内部 guards、clear/restore 与 call order 未改；差异只是在
outer guard 前建立 local volatile value。

## 2. All-production-batch expansion

将 local volatile copy 机械扩展到 22 个 production batches：22 source files、107 markers、107 volatile declarations、0 个
残留 plain outer-if，22/22 objects 编译成功。aggregate 三方结果为：

| Metric | Plain - baseline | Volatile - baseline | Volatile - plain |
|---|---:|---:|---:|
| `.text` bytes | +10,145 | +398 | -9,747 |
| instructions | +1,536 | +148 | -1,388 |
| memory forms | +1,131 | -53 | -1,184 |
| jumps | +153 | -103 | -256 |
| calls | 0 | 0 | 0 |

global volatile-copy 消除了绝大部分 cliff，但相对 baseline 的 text/instructions 仍没有转负。更重要的是，它只在
batches 27/50/57/61 相对 plain 改善，另外 18 个 batches 都增加 instructions。

## 3. Hot-batch cost

NO0500 miss 最热的 direct-predicate batches 被 global volatile-copy 削弱：

| Batch | Eligible words | Volatile - plain text | Instructions | Memory | Jumps |
|---:|---:|---:|---:|---:|---:|
| 35 | 37 | +968 | +216 | +72 | -1 |
| 58 | 21 | +875 | +155 | +69 | -3 |
| 21 | 8 | +153 | +27 | +6 | -7 |

这里增加的代码主要来自不再被 outer condition 消除的内部 event equality，以及 local volatile access。global 形态虽然修复
batch 27，却会让占总 miss `55.57%` 的 35/58/21 hit path 重新执行更多 checks，不能只凭 aggregate code size 落地。

## 4. Decision

值传播 root cause gate 通过；`volatile_ref`、noinline 和 global `volatile_copy` 均停止，不修改 production emitter。下一步用
现有 plain/volatile 对象做 per-batch eligible-word-count threshold sweep：稀疏 batches 使用 volatile-copy 避免偶发 cliff，dense
hot batches 保持 direct predicate 获取内部 guard simplification。规则必须基于 emitter 可见的 batch 结构，不能硬编码 batch id；
先同时比较静态 aggregate 与 NO0500 动态 hit/miss 覆盖，再决定是否值得实现。
