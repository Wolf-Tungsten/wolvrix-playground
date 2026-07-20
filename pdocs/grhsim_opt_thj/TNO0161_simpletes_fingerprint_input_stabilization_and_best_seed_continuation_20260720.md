# TNO0161 SimpleTES fingerprint input stabilization and best-seed continuation

记录日期：2026-07-20

状态：已在 SimpleTES commit `c7f0cef` 中修复上一轮 default-off fingerprint 假拒绝的
输入根因，并新增从旧 instance `best_program.txt` 启动 fresh bounded search 的正式入口。
production control 绝对清点得到 `2,103` 个固定生成输入，即 `2,097` 个 RTL `.sv/.v` 与
`6` 个 XiangShan difftest generated-source 文件；evaluator 现在先做 manifest，再把 control
输入复制为 candidate 私有、byte-exact snapshot，并在 unpatched-same-options、disabled 和
enabled 三个阶段后复核。SimpleTES 全套回归为 `110 passed`。本文冻结在 continuation
启动前的阶段边界，不含新 instance、build、50k walltime 或性能结论；实际启动与后续结果
另立新 TNO。

上一轮正式搜索、best weak-positive signal 与假拒绝证据见
[TNO0160](./TNO0160_simpletes_first_formal_search_results_and_default_decision_20260720.md)。

## 1. Root cause refinement

上一轮 generation `15` 重复了最佳补丁，但 disabled build 与 cached control 的 generated
C++ fingerprint 不同；`17` 个 schedule CPP 中出现临时 value ID 与等价 boolean operand
排序漂移。TNO0160 在输出边界确认了 fresh emit 非 byte-deterministic，但当时尚未区分
GrhSIM emitter 自身和其上游输入。

后续审计定位到更早的输入边界：

- control cache 的 checkout 已完成一次 XiangShan elaboration，含未被 Git 跟踪的 RTL 与
  difftest generated sources；
- 每个 candidate 从 pinned repository graph 建立新 clone，这些 build products 不随 Git
  clone 复制；
- candidate 随后独立再生成一份上游输入，可能产生不同的临时 value 编号或等价表达式顺序；
- 旧 gate 最终比较 control/candidate generated C++ 的 byte fingerprint，却没有先证明两边
  消费的是同一份 HDL/difftest 输入，因此会把上游 fresh-generation drift 错判成候选在
  disabled 状态下改变 codegen。

因此本次修复不归一化 generated C++、不忽略 17 个差异文件，也不放宽 default-off gate。
它把 attribution 的前提向前推进到“先固定并证明生成输入完全一致”，从而仍可保留严格的
byte-exact output fingerprint。

## 2. Fixed generation-input set

evaluator 固定枚举两个 input roots：

```text
build/xs/rtl/rtl/**/*.sv
build/xs/rtl/rtl/**/*.v
testcase/xiangshan/build/generated-src/**/*
```

production control 的绝对清点为：

| root | selection | absolute files |
| --- | --- | ---: |
| `build/xs/rtl/rtl` | regular `.sv` and `.v` only | `2,097` |
| `testcase/xiangshan/build/generated-src` | all regular files | `6` |
| total | fixed generation inputs | `2,103` |

六个 difftest generated-source 文件为：

```text
DifftestMacros.svh
difftest-dpic.cpp
difftest-dpic.h
difftest-query.h
difftest-state.h
difftest_profile.json
```

`build/xs/rtl/rtl/SimTop.sv` 与
`testcase/xiangshan/build/generated-src/DifftestMacros.svh` 被设为 required sentinels；root
缺失、root/file 是 symlink、发现非 regular file、路径逃逸或 required file 缺失都作为
retryable infrastructure error 拒绝。RTL root 中 `.fir` 和 file-list metadata 不进入
manifest；它们不是 GrhSIM 此路径消费的固定 HDL 输入。

## 3. Manifest and private-copy contract

`generation_input_fingerprint` 使用 versioned domain
`simpletes-grhsim-generation-input-v1`。文件先按 repository-relative POSIX path 稳定排序，
manifest hash 纳入绝对文件数，并对每个文件纳入 path length、path bytes、file size 和完整
content bytes。因此同内容不同路径、同路径不同大小或任一 byte drift 都会改变 fingerprint。

candidate clone 建立后、任何 candidate emit 前，evaluator 执行以下 staging：

1. 从 cached control 枚举并 fingerprint 全部 `2,103` 个 input；
2. 在 candidate checkout 中创建对应目录并以 `copy2` 逐文件复制；destination 必须原先
   不存在且不是 symlink；
3. 若 source/destination 位于同一 device，则要求 inode 不同，证明不是 hardlink 或共享
   文件；
4. 复制后重新 fingerprint control 和 candidate，两者都必须等于 staging 前的 expected
   manifest。

这既确保 candidate 消费与 control byte-exact 相同的 elaboration snapshot，也确保后续
candidate build/patch 无法通过共享 inode 修改 cached control。manifest 本身只保存 digest
语义，不把 2,103 个大文件复制进 checkpoint 或版本库。

## 4. Three-stage drift verification

修复后的 candidate pipeline 顺序固定为：

```text
candidate clone
  -> stage private control generation-input snapshot
  -> unpatched + same-options emit
  -> verify manifest unchanged
  -> apply candidate patch
  -> patched disabled build/tests/function gate
  -> verify manifest unchanged
  -> patched enabled build/tests/function gate
  -> verify manifest unchanged
  -> existing attribution/default-off fingerprints and ABBA/BAAB runtime
```

三个显式 phase label 分别为：

```text
after the unpatched same-options emit
after the default-off candidate build
after the enabled candidate build
```

任一阶段发生 input drift 都返回 `InfrastructureError`，不会把结果计为 valid candidate，
也不会把输入污染误判为性能结果。原有 hard gates 保持不变：disabled generated C++/header
仍须与 current-default byte-identical；enabled 仍须不同于 current-default 和 unpatched
same-options；最终仍只由通过 fixed-ASLR/CCD/NUMA/PMU/功能审计的 SimTop 50k walltime 裁决。

## 5. Best-seed continuation entry

上一轮已经用满 `16` 次 proposal budget，不能通过 `--resume` 扩大旧 checkpoint 的 chain
预算。launcher 新增 `--init-program`，允许以先前完整 marked candidate 文档作为新 instance
的 initial node；default 仍是 dataset 自带的 no-op `init_program.txt`。

本轮选定 seed 为：

```text
path
SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01/2026-07-20/instance-91f6580e/db_state_161238/best_program.txt

bytes                       12,293
file type                   regular, non-symlink
candidate digest            842fb6de071cbe880c582b00e0ce653fd1a907662b2b2b942d1459436a418e19
changed files               lib/emit/grhsim_cpp.cpp
enable option               active_mask_gap_pack_policy=targeted-table-contiguous
validate-only               PASS
```

该 seed 是 TNO0160 中合并 wall `74,237.50 -> 73,998.25 ms`、弱正向
`239.25 ms / 0.322276478%` 的候选。新 instance 会重新评价 seed initial node；initial
evaluation 不消耗 proposal slot 或 valid-candidate slot。seed 只提供搜索起点，不代表补丁已
采用，也不继承上一轮 walltime 作为新 instance 分数。

launcher 拒绝 symlinked seed，并把 resolved regular-file path 显式传给 SimpleTES core。
如果一个 best-seeded run 之后只是 graceful stop、尚未用满自己的预算，则 resume 时仍须
重复相同 `--init-program` 参数；本轮则明确不 resume 已耗尽预算的 `91f6580e`。

## 6. Validation and commit

SimpleTES 提交为：

```text
c7f0cef7b69e14de890f9b46cbb86d942a787a26
fix: stabilize GrhSIM candidate attribution and seed continuation
```

绝对 diff 为 `5 files changed, 402 insertions, 11 deletions`，涉及 evaluator、launcher、bench
README/instruction 和 focused tests。测试覆盖：input 选择与 required sentinel、FIR 排除、
HDL drift 检出、symlink/missing 拒绝、private inode copy、三个 phase 的 pipeline 顺序、显式
best seed、symlink seed 拒绝和 default seed。

source target `env.sh` 后全套 SimpleTES tests 的绝对结果为：

```text
110 passed, 17 warnings in 3.53 s
```

`17` 个 warning 仍是既有 `datetime.utcnow()` deprecation。该 commit 只改变 SimpleTES bench
与验证基础设施，没有修改 wolvrix source、C++ defaults 或父仓库 submodule pointer。

## 7. Fresh continuation contract and stage boundary

计划以 fresh instance 启动，而不是 resume `91f6580e`：

```text
initial program             prior best digest 842fb6de071cbe88...
fresh instance              yes
resume old checkpoint       no
pinned parent               b90d20461d276def682f19a28be1fe65a4387eef
pinned wolvrix              f17e90e14c3ad70a3ee93f7c6540e13dae54940a
API config                  ~/.codex/config.mjy.toml
API auth                    ~/.codex/auth.mjy.json
model / reasoning           gpt-5.6-sol / ultra
selector / chains           rpucg / 4
gen / eval workers          1 / 1
new proposal budget         16
new valid-candidate target  8
```

API key 内容继续只由 launcher/backend 安全读取，不写入本文、argv、日志或 checkpoint。
测量契约继续使用动态空闲 CCD、固定 target CPU、ASLR 关闭、NUMA-local first-touch、PMU 与
zero-migration audit、ABBA screen 和正向后的 BAAB promotion；headline 仍是 SimTop 50k
`Host time spent` walltime。

本文的阶段截止点尚未执行 continuation launcher，因此此处的新 instance id、accepted
control/candidate、绝对 50k walltime 和相对性能变化均为 `0`。启动动作、初始 seed
re-evaluation、任何 infrastructure 修正和后续 candidate 结果应分别在后续 TNO 增量归档，
不得回写本文形成性能结论。
