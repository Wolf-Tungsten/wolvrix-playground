# TNO0184 SimpleTES v2 RWA materialization and fresh gate

## 1. 阶段结论

[TNO0183](./TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)
确认 `R/W/A` 有正向信号、`F` 没有可靠端到端收益，但当时只有含 `F` 的 `RWFA`，不能直接把它当成
最终目标组合。本阶段从固定 checkpoint 的 `RW/RWF/RWFA` 三个完整 candidate 机械构造无 `F` 的
`RWA`，没有手工删除或改写任何 hunk。

构造结果满足三条逐字节闭包：

```text
RW + A-only       == RWFA - F-only == RWA
RWA + F-only      == RWFA
RWF + A-only      == RWFA
```

最终 `RWA` 是 `default-path`、零 enable option，只修改 `lib/emit/grhsim_cpp.cpp`。它完成 fresh clone、
严格 patch apply、完整生成/build、focused `29/29`、fixed-ASLR 100-cycle 和 10k-cycle 功能门禁，新的
candidate proof 与 11-file arm snapshot 均已固化。因此该 arm 可以进入独立 50k endpoint gate；本记录
只裁决 materialization/build/function，不用功能测试 walltime 代替正式性能结论。

## 2. 固定输入与版本身份

三个输入节点来自同一 v2 checkpoint：

`SimpleTES/checkpoints/grhsim_simtop_50k/continuation_v2_20260725_090855/2026-07-25/instance-ccad5879/db_state_032443/nodes.json`。

| arm | gen / node | 原 candidate digest | 原 patch SHA-256 |
| --- | --- | --- | --- |
| `RW` | `16` / `9834966321c64b328b41e3726ddd40a5` | `a3b8881df5236ddc2389c60d34e7995fdb0be9c71b13277f98bf47d7f3bd02fb` | `9499f1aa1e7c86962a6bc92413e17c13646c5d8cccd79d1097d59af6e436862d` |
| `RWF` | `22` / `9b8e8a7ff0264c1f9d60c306019b43fb` | `62a6762c78cd8ee6c2b5fdff64c98f8d3680c8345da225194103ebb9a9b33c1f` | `bdaf08c740602d8d5fc323f437ddfc7208800dc113ac8f943eb86e85d5526b50` |
| `RWFA` | `40` / `215a21e29f59451385891d65e7791da6` | `62892528a60b3c889d5c9b4d162b09f2aa49f7a45a1b1ca64240847337b29145` | `fdc4700a8a5525d8103f19a482fe02f1bfa5cbac5e89d147a4f8be26633e75bf` |

固定构建身份：

- parent：`fbe4e1cbbfcf45b52960545377020cb761c3ab25`；
- Wolvrix：`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`；
- 新 SimpleTES materializer commit：`ef6e70c368341c43621369afdbf7d9328bb2c6b4`；
- env SHA-256：`3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a`；
- build-config fingerprint：`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`；
- toolchain fingerprint：`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038`。

materializer 从 pinned Wolvrix Git object 读取基线源码，不读取用户 worktree 中可能存在的本地修改。
基线 `grhsim_cpp.cpp` SHA-256 为
`376fed1c3a1a297abd496ad8a87dc705a2fd9e279e70873a15e060098a5aaf2c`。

## 3. 机械组合与依赖审计

实现使用三份相对 pinned baseline 的完整 patch 分别恢复 `RW/RWF/RWFA` 源码，再执行：

```text
A-only = canonical_diff(RWF, RWFA, context=3)
F-only = canonical_diff(RW, RWF, context=3)
RWA-1  = apply(RW, A-only)
RWA-2  = reverse_apply(RWFA, F-only)
assert RWA-1 == RWA-2
assert apply(RWA-1, F-only) == RWFA
assert apply(RWF, A-only) == RWFA
RWA full patch = canonical_diff(pinned baseline, RWA-1, context=3)
```

canonical diff 固定普通三行上下文以及 `a/lib/emit/grhsim_cpp.cpp`、
`b/lib/emit/grhsim_cpp.cpp` 文件头；不能换成会为 C++ hunk 添加 xfuncname 的 `git diff`，否则字节身份会改变。

| 对象 | SHA-256 | 大小 / 结构 |
| --- | --- | --- |
| `A-only` | `ae1326c870d48d9d21a381d5a4df4affc8976c5143291d8b7ba9c08bc911f862` | `6649 B`，`131` lines，`5` hunks，`+82/-3` |
| `F-only` | `2b65ec79053ac4bd3855d8acf6b95c04f540b4dba8d1e33ab0ad346933c41bf7` | `4421 B`，`71` lines，`4` hunks，`+32/-3` |
| baseline-to-RWA full patch | `2e2969508e3975490f501707724a80e3d4d76a62320bd27f7279f3f1341f14c0` | `15110 B`，`268` lines，`9` hunks，`+172/-12` |
| materialized RWA source | `3739547b0c88676a0c0a4ee9c544f60df01754e2d13a18b81e821d11a6c45e84` | `31322` lines |

`A-only` 和 `F-only` 的 hunk 不重叠。RWA 中 `isNestableAssertionSideEffectPair`、
`nestedAssertionDpicOpId`、`nestFollowingAssertionDpic`、`closesNestedAssertionPair` 等 A 路径符号存在；
`kCommitExactEventColdMemoryFillGuardMinCount`、`isColdSingletonMemoryFillGuard`、
`coldSingletonMemoryFillGuardCount`、`coldLargeMemoryFillGuardRun` 等 F-only 符号均缺席。结合上述三条
byte-exact 闭包，确认 gen40 的 A 不依赖 F 才能 apply 或 build。

## 4. SimpleTES materializer 与回归

`datasets/grhsim/simtop_50k/materialize_ablation.py` 保留原来的单节点精确 materialization，同时新增：

```text
--compose-rwa RW_GEN RWF_GEN RWFA_GEN --wolvrix-repo <repo>
```

该模式要求三个输入均为 zero-option `default-path`、只改目标 C++ 文件；每份 full patch 都在临时目录独立
apply，并把输入 node/digest/patch SHA、A/F/RWA hash 和闭包布尔值写入机器可读报告。materializer 文件
SHA-256 为 `3ba48f4e1fc902209246db30c6298644a3952e5ac53f598496c20c2e68c2982c`。

测试结果：

- materializer 旧精确复制与新 RWA 组合 focused：`2 passed`；
- `tests/test_grhsim_bench.py`：`68 passed`；
- 从 SimpleTES 仓库根运行完整 `pytest -q tests`：`140 passed`，只有 `17` 条既有 UTC deprecation warning；
- 新 candidate `--validate-only`：`valid=true`、mode=`default-path`、options=`{}`、文件集合唯一为
  `lib/emit/grhsim_cpp.cpp`。

阶段提交为 `ef6e70c bench: compose RWA ablation arm mechanically`，包含 materializer 与相应单元测试，
没有改 evaluator、runtime、candidate schema 或 auto-research 调度逻辑。

## 5. Fresh build、功能与 proof gate

fresh evaluator 生成的新 candidate 身份为：

- candidate digest：`600ee91247376203f2162cfcad099e05c629382bb94b4600264cecaf6c5658a3`；
- `candidate.txt` SHA-256：`7a00f0a9db4220ee762e166ee732d422926170f0220bcfef6d70d30c9c07385c`；
- proof ID：`90c0e0cfd4d34c59bf9f28c039b03317`；
- proof SHA-256：`5a20d94e0fb3a3ea7bf27da880527f2f6a0972674342f91c713a75f1a0fa58ab`；
- generated fingerprint：`f28f2a696328175f0fe76e2e16895b44fbe54320506776eb6a5c436674c72077`；
- canonical options：`{}`。

| gate | 绝对结果 | 结论 |
| --- | --- | --- |
| strict clean/apply/build | 完成 O3 生成、编译、链接 | PASS |
| focused | `29/29` | PASS |
| 100-cycle | guest cycle `101`，terminal PC `0`，唯一 Host time `167 ms` | PASS，仅作功能门禁 |
| 10k-cycle | guest cycle `10001`，terminal PC `0x800027c6`，guest instr `458`，唯一 Host time `5466 ms` | PASS，仅作功能门禁 |

proof 同时固定 control generated fingerprint
`9ad3a09d170442b2ea4d2cc1610eede86611ebddf6d49127b4fbee9eba3af989`，以及两边相同的 build-config、
toolchain、env 身份。100/10k 的绝对 walltime 只证明日志和功能路径完整，不用于最终性能口径；最终性能
仍只接受独立 SimTop 50k `Host time spent`。

## 6. RWA arm 固化

ignored artifact 根目录为：

`build/grhsim_simpletes_v2_ablation_20260727/arms/rwa/`。

11-file manifest 中的主要身份为：

| artifact | bytes | SHA-256 |
| --- | ---: | --- |
| `candidate.txt` | `16526` | `7a00f0a9db4220ee762e166ee732d422926170f0220bcfef6d70d30c9c07385c` |
| `candidate_proof.json` | `2619` | `5a20d94e0fb3a3ea7bf27da880527f2f6a0972674342f91c713a75f1a0fa58ab` |
| `emu` | `91894296` | `277bf2fc307e9340b1930b9b495475732347f6f71911d3f9b81c96ab3320a23b` |
| `coremark.bin` | `16712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| `nemu.so` | `567504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

另有 clean/build/focused/function100/function10000 五份日志和 provenance。`SHA256SUMS` 有 `11/11`
条目并通过 `sha256sum --check --strict`；manifest 自身 SHA-256 为
`adda3bf4c9dd07c8a42fbeab3a280261ebb6072107795be4f9a674aecdf7db19`。目录合计 `12` 个文件、
`94003497 B`，排序后全树 checksum-stream SHA-256 为
`009aecf46e69c26f66744787a624128f8349e731ec79ca0f722ec6997bc09676`。

## 7. 后续可继续性

direct artifact-only runner 增加显式 `b-to-rwa` 和 `rw-to-rwa`，但没有把它们加入默认三组相邻 pair；
因此不带 `--pair` 的调用不会意外运行 baseline 或 RWA。runner 已更新 SimpleTES HEAD pin，仍硬锁 evaluator、
runtime、env、proof、manifest、fingerprint 和 artifact bytes，并继续禁止 runtime mapping 带 `repo`。

两次无 emu 预检分别返回：

```text
--pair b-to-rwa  --validate-only -> validation_complete
--pair rw-to-rwa --validate-only -> validation_complete
```

两次都重验相应 snapshot 的 `11/11` 文件。SimpleTES 全套测试通过，evaluator/runtime 未改，trusted slot
已释放；本阶段没有启动 auto research 或新 continuation。下一篇记录独立 50k endpoint，不在本篇提前
决定 A 的最终保留状态。
