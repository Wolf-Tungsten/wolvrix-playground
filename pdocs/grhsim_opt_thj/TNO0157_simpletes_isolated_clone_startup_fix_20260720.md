# TNO0157 SimpleTES isolated-clone startup fix

记录日期：2026-07-20

状态：正式 SimpleTES run 启动后暴露并修复两个 deterministic isolated-clone verifier bug。修复后 control clone 已完成 pinned graph、写出 ready marker 并进入 `env.sh`/build 阶段；全套 SimpleTES 回归为 `100 passed`。本记录没有 50k emu 样本或 walltime 结论。

前序 bench/launch gate 见 [TNO0156](./TNO0156_simpletes_auto_research_bench_and_launch_gate_20260720.md)。

## 1. Formal run identity and initial symptom

正式 launcher 使用：

```text
SimpleTES initial bench commit 0589387d3ea2eb9542b29aca9373ad42aa1780bf
instance id                    91f6580e
checkpoint                     SimpleTES/checkpoints/grhsim_simtop_50k/formal_20260720_01
slot namespace                 /tmp/simpletes-grhsim-simtop-50k/240719f63589edae/slot-0
```

初始 control 在以下绝对时间返回 retryable infrastructure：

```text
02:00:45
02:01:25
02:02:05
02:02:45
02:03:49
02:04:54
```

这些 evaluation 都发生在 build/50k 之前，没有生成 accepted sample，不计入 valid-candidate budget。core 按协议每次等待 `30 s` 后重试同一 control；没有生成新 proposal。

## 2. Root cause 1: sourced-env stderr contaminated Git output

`env.sh` 每次 source 都运行 pip。当前宿主的 pip cache warning 写到 stderr；evaluator 的 `_run_sourced` 又把 command stderr 合并到 stdout，所以 `git rev-parse HEAD` 实际返回：

```text
WARNING: ... pip cache ...
b90d20461d276def682f19a28be1fe65a4387eef
```

commit 本身完全正确，但 exact revision verifier 把两行整体与 pinned SHA 比较，产生假 mismatch。修复为 source 阶段固定：

```bash
source "$1" >/dev/null 2>&1
```

随后 exec 的真实 command stdout/stderr 仍按原规则捕获；只静默 `env.sh` 自身 setup chatter。新增测试直接让假 env.sh 向 stderr 写 warning，并确认 machine-readable command stdout 只剩绝对 payload `machine-readable`。

## 3. Root cause 2: uninitialized gitlink inherited parent worktree

XiangShan 的部分 nested gitlink 只有空目录、未初始化独立 `.git`。旧检查使用：

```text
git -C <empty-submodule-dir> rev-parse --is-inside-work-tree
```

Git 会向父目录搜索 metadata，因此在空 gitlink 目录内仍返回 `true`，evaluator 随后错误地尝试 clone 不存在的本地 repository，例如：

```text
testcase/xiangshan/ChiselAIA/Utility
```

修复改用 `rev-parse --show-toplevel`，并要求解析后的 top-level path 与待检查 path 完全一致；返回父 XiangShan root 的空 gitlink 现在被识别为 uninitialized 并按 pinned source graph 跳过。新增单测覆盖“child directory 返回 parent toplevel”必须为 false。

## 4. Fix commit and validation

SimpleTES 独立修复提交：

```text
4e67a830d54a0d16dbb87b43f248687c65055ef4
fix: make isolated submodule cloning robust
```

提交只修改 evaluator 与相应测试，绝对 diff 为 `48 insertions / 5 deletions`。在 source current target `env.sh` 后全套结果：

```text
100 passed, 17 warnings, 3.68 s
git diff --check PASS
```

warning 仍只有既有 `datetime.utcnow()` deprecation。

修复后的正式 retry 在同一 slot 上完成 parent、wolvrix、XiangShan 及实际 initialized nested graph；绝对状态为：

```text
02:09:02  .simpletes-control-ready.json written
02:09:15  isolated control .venv/pyvenv.cfg written
control checkout size at 02:09:53  342 MiB
```

这证明 run 已越过两个 clone failure，进入 source/build 环境。此时 results 目录尚无 control build artifact，accepted 50k sample 数仍为 `0`、绝对 walltime 数仍为 `0`；不能提前形成性能结论。

## 5. Repository decision

- GrhSIM parent/wolvrix 源码和 submodule pointer 未修改；没有 submodule code commit。
- SimpleTES fix 已按独立 startup-fix 粒度提交。
- 后续 control build、100/10k gate、quiet 50k absolute wall 与 candidate 结果另立新 TNO，不追加到本记录。
