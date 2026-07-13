# NO0413 Local active-word consume probe plan

日期：2026-07-12

## 1. 背景与可比口径

[NO0412](./NO0412_unknown_runtime_frame_attribution_gate_20260712.md) 收尾后，NO0404 同一份
fixed-ASLR、25M-period instruction profile 中尚有一项明确的框架差值：GrhSIM compute dispatch
为 `413` samples，GSim 为 `332` samples，净差 `81` samples，约为 `2.025B` instructions，
占 direct compute instruction excess 的 `3.35%`。

两边生成代码都按一个 byte 管理最多 8 个 active supernode，但局部协议略有不同：

```cpp
// GSim
if (unlikely(activeFlags[word] != 0)) {
    uint8_t oldFlag = activeFlags[word];
    activeFlags[word] = 0;
    if (unlikely(oldFlag & bit)) { /* payload */ }
}

// GrhSIM
std::uint8_t activeWordFlags = supernode_active_curr_[word] & dispatchMask;
if (unlikely(activeWordFlags != 0)) {
    supernode_active_curr_[word] &= ~clearMask;
    if (unlikely(activeWordFlags & bit)) {
        activeWordFlags &= ~bit;
        /* payload */
    }
    supernode_active_curr_[word] |= activeWordFlags;
}
```

这与 [NO0149](./NO0149_ctz_active_dispatch_fresh_c1_c2_c4_dynamic_20260521.md) 的
`ctz + switch` 路线不同。NO0149 已使 CoreMark 50k runtime 回退 `10.50%`，本轮不改变逐 bit
branch dispatch，也不重复该实验。[NO0269](./NO0269_packed_active_flag_scan_20260711.md) 优化的则是
`eval()` 轮末全局 bitmap 空集判定，不是这里的 batch 内 word dispatch。

## 2. 当前样本拆分

GrhSIM 的 `413` 个 dispatch samples 可按生成语句严格拆成：

| 语句角色 | Samples |
| --- | ---: |
| per-supernode bit gate | `220` |
| per-word nonzero gate | `124` |
| active-word load | `32` |
| local per-bit clear | `28` |
| final local-word restore | `7` |
| global clear | `2` |

GSim 对应为 per-supernode bit gate `250`、per-word nonzero gate `78`、其余 active-word
load/clear `4`。因此 GrhSIM 独有且可直接指认的 local clear + final restore 共 `35` samples：

- 占 dispatch 净差 `35 / 81 = 43.21%`；
- 占全部 direct compute `35 / 5590 = 0.626%`。

它本身尚未达到 `1%` compute 门槛，不能仅凭 source 行数直接实现。

## 3. SimTop 静态机会

当前 direct production 的 66 个 compute sources 含 `7,932` 个 active-word blocks：

- `7,932 / 7,932` 均满足 `dispatchMask == clearMask`；
- `7,853` 个为完整 8-bit mask；其余 `79` 个为 batch 边界 partial mask；
- compute batch 0..64 没有任何 `activeWordFlags |= ...` 或 `&activeWordFlags`；
- batch 65 有 `30` 条 same-word local activation，必须保留 mutable 协议；
- 66 个 compute sources 中没有 memory-row helper 通过指针修改 `activeWordFlags`。

对一个 payload 不会写入或取址 `activeWordFlags` 的 block，逐 bit clear 只清除当前已通过的 bit，
不会影响后续不同 bit 的测试；所有 bit 测试结束后 local word 必为 0，末尾 OR 回全局也恒为 no-op。
因此可在不依赖 DAG/fixed-point 推断的前提下，把该 block 局部化简为 immutable consume：

1. 保留入口 global clear、word nonzero gate 和所有逐 bit gate；
2. 删除每个 supernode 内的 `activeWordFlags &= ~bit`；
3. 删除 block 末尾 `supernode_active_curr_[word] |= activeWordFlags`；
4. 只要 block 内出现 local OR、条件 local OR、`&activeWordFlags` 或未知写法，就完整保留旧协议。

## 4. Probe 与门槛

先在 production generated copy 上做 source-to-machine probe，不修改 emitter：

1. 用结构 parser 定位每个 word block，只转换满足上述只读证明的 block；
2. 校验每个被删 clear 与 restore 都属于同一个已证明 block，其他 payload 文本 byte-identical；
3. 先编译 dispatch samples 最高的 `58/62/35/31/41/52` 六个 batch；
4. 若六 batch 没有一致的 O3 static instruction/text 改善，则停止；
5. 若代表 batch 一致改善，再编译 66 个 compute objects，比较完整 batch symbol 的 bytes、static
   instructions、branch/test、load/store、AND/OR、stack operands，并检查 production objects 未被改动。

进入 emitter/runtime 的门槛预声明为：

- 生成 copy 的 66-batch O3 aggregate static instructions 至少下降 `0.5%`，且不能以 branch 数或
  stack/memory operands 明显回增换取；
- 通过 basic-block machine diff 扩展后的既有动态 samples 影响上界至少为 `56/5590 = 1%`
  compute，或者有同等强度的直接机器证据；
- 未达到任一门槛时，记录 negative gate 并停止，不用共享机器跑 SimTop runtime；
- 达到门槛后才实现默认关闭的 emitter option，先过 synthetic、10k/50k 功能，再在 quiet CPU 上做
  fixed-ASLR old/new/old。若机器负载不稳，必须同时重跑 baseline，不使用跨时段绝对时间。

## 5. 后续分支

若 immutable consume 不过门槛，剩余 dispatch 差值主要是 per-word gate `124/78`，而不是局部
bit bookkeeping。下一步应复用 runtime-profile edge/round 计数，把当前 50k 的 word-gate excess
拆成正沿、负沿和 commit 后 fixed-point round；不能再用 `ctz`、盲目合并 active words或跳过负沿
来掩盖真实工作。
