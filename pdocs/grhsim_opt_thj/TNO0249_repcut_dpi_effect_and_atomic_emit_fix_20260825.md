# TNO0249: RepCut DPI effect and atomic emit fix

日期：2026-08-25

状态：`IMPLEMENTED; FOCUSED REGRESSION PASS; SYSTEM GATE TRACKED SEPARATELY`。

关联记录：[TNO0241](./TNO0241_repcut_dpi_output_schedule_root_cause_20260820.md) 已完成根因闭环，本记录只归档代码修复与局部回归；XiangShan 重新生成、构建及 runtime gate 另见后续独立记录。

## 1. 修复结论

本次修复不依赖 Verilator 偶然生成的任务顺序，而是在 Wolvrix 的三个层次恢复原始 RTL 的 effect 语义：

1. RepCut 把 `kDpicCall`/`kSystemTask` 视为必须执行的 effect anchor；DPI 是否产生可消费结果同时检查 C return、`output` 和 `inout`，不再把 `void DPI(output)` 误判为无结果。
2. SystemVerilog emitter 将 DPI 调用和依赖它的状态提交放入同一个事件过程，并建立显式 `producer -> sink` predecessor；调用结果直接经 `_intm` 供提交使用，不再依赖跨过程连续赋值的后端调度。
3. partitioned package 为确实跨 unit 的 effect result 保留 `early eval -> early publish -> normal eval -> normal update` 能力；如果 RepCut 已将 producer/sink 共置，则该实例保持 normal phase。

因此 TNO0241 中的错误顺序：

```text
reader -> commit -> DPI producer
```

被实现层面的依赖改为：

```text
DPI producer -> dependent state commit
```

## 2. 代码身份与范围

本轮未创建提交，冻结身份如下：

```text
parent HEAD:  26eb27d5b0dd3aa9a14513f309135735f96dd99d
wolvrix HEAD: 79ec2037b00f2d4894d72785277ebe3f5d37782d
```

本修复修改的生产源及最终 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `wolvrix/lib/transform/repcut.cpp` | `71e7c879ca4e7538b640b64027849b444296d528853c53cd7729757f152f987d` |
| `wolvrix/lib/emit/system_verilog.cpp` | `bb8475338f21b4f869ab8f4077e69c7e84222e3bc7058022b8c8955e1b175d85` |
| `wolvrix/lib/emit/verilator_repcut_package.cpp` | `cfb4da10b8be950ebd92a643b6ab10916b608ddc4409c22a74b84d00ac570d1d` |

对应测试扩展：

```text
wolvrix/tests/transform/test_repcut_pass.cpp
wolvrix/tests/emit/test_emit_sv_storage_ports.cpp
wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp
```

工作树原有其他改动没有清理、回退或纳入本修复结论。

## 3. RepCut effect 建模

新的结果判定为：

```text
produces_effect_result =
    hasReturn || !outArgName.empty() || !inoutArgName.empty()
```

执行 anchor 则与结果是否被消费无关：

```text
execution_anchor = kDpicCall || kSystemTask
```

这带来四项约束：

- 无返回值且结果未使用的 DPI/system task 仍恰好保留一次；
- `void DPI(output/inout)` 的 result cone 能被 ASC 收集；
- 同一 effect result 驱动的多个状态 sink 通过 DSU 共置，避免 producer/result 在 RepCut 边界被无约束拆开；
- matching `kDpicImport` 随调用保留，并在最终分区结构上检查 effect producer/consumer 的合法性。

测试同时覆盖有 return、void output、void inout、结果被多个 sink 使用及结果未使用的情况。

## 4. SystemVerilog 原子发射

emitter 先从每个 DPI result 沿受支持的组合链收集状态 sink，再对同一事件域建立显式 predecessor DAG。顺序不再由 GRH operation 创建顺序或容器遍历顺序决定。

当前支持：

- return、`output`、`inout` 及其组合；
- assign、比较、算术/逻辑、mux、concat、replicate、静态/动态/array slice 等受支持的纯组合链；
- register/memory sink 的同事件原子更新；
- 多个 output/inout 参数的 preload、单次 DPI 调用和提交顺序；
- 窄 concat/replicate、动态 slice 与 signed/unsigned value boundary。

当前采用 fail-fast 的边界包括：output/inout result 指向 latch 等未支持的原子 sink、event signal/edge 不一致、结果经不支持的 operation 到达状态、结果进入其他有副作用 operation、无法唯一确定合法状态序列等。这样不会退回到“能发射但顺序未定义”的旧行为。

### 4.1 merged guard 修正

第一次在完整 XiangShan 上发射时，`jtag_tick` 暴露出 sink guard 可以比 DPI guard 更宽：

```systemverilog
if (D)
    temp = jtag_tick(...);
if (reset_guard || D)
    state <= D ? temp : reset_value;
```

这是合法的规范化结果：DPI 未调用时 `_intm` 保持旧值，而 sink 在 reset 分支选择 reset value。故最终检查只要求 DPI 与 sink 属于相同 event signal/edge，不再强制两者 `updateCond` 逐值相等。新增正例让 consumer 先于 DPI op 创建，并验证调用恰好一次且位于 sink 前；event edge 不一致仍为负例。

完整 XiangShan 最终 SV 中，flash 路径已经固定为同一 `posedge` block 内：

```systemverilog
if (cpu$l_simMMIO$flash$DifftestFlash_io_en)
  flash_read(..., _val_9993955_intm);
if (cpu$l_simMMIO$flash$DifftestFlash_io_en)
  cpu$l_simMMIO$flash$DifftestFlash$helper$r_data_1 <= _val_9993955_intm;
```

证据位于：

```text
build/repcut_fix_20260825/generated-v6/xs_wolf_repcut/
  SimTop_repcut_part3.sv:2636887
  SimTop_repcut_part10.sv:619399
```

## 5. partitioned runtime 与线程校验

package emitter 根据跨 unit edge 的 effect provenance 标注 early driver，runtime 顺序为：

```text
input load
early unit eval
early edge publish/update
normal unit eval
normal edge update
```

early effect 指向另一个 early unit 会被拒绝，以避免单个 early phase 内继续形成未排序链。当前 XiangShan 的 DPI producer 与依赖 sink 已被 RepCut 共置，最终 package 为 `0` 个 early unit、`32` 个 normal unit；这说明本例依靠共置和 unit 内原子顺序闭合，early phase 是跨 unit 情形的结构保护，不是本例的隐藏特殊路径。

运行时同时加入严格线程配置：

- `XS_EMU_THREADS` 必须为正整数且可完整转换为 `size_t`；
- 请求值不得超过 `max_parallel`、进程 affinity 可用 CPU 数或生成 package 的能力；
- 日志明确打印 `requested/effective/max_parallel/available_cpus`；
- worker 创建异常会停止并唤醒已启动 worker，再逐个 join，不会在构造失败路径死锁；
- worker wait predicate 同时检查 `stop || hasWork`。

NDEBUG runtime guard 已验证合法 `1/2` 返回 0，负数、超过 partition 数和整数溢出均确定性拒绝。

## 6. 回归结果

最终源上 focused 三项全部通过：

```text
emit-sv-storage-ports             PASS
emit-verilator-repcut-package     PASS
transform-repcut                  PASS
```

merged-guard 生成 fixture 另经 Verilator lint，通过，仅有 `DECLFILENAME`/`UNUSEDSIGNAL` warning。

完整 CTest：`52/53 PASS`，本次可复核运行耗时 `295.80 s`。唯一失败为既有且与本次文件无关的：

```text
transform-comb-lane-pack
[comb-lane-pack-tests] Expected one packed kAnd for storage frontier rewrite
```

日志：

```text
build/repcut_fix_20260825/logs/tests-final/ctest.log
build/repcut_fix_20260825/logs/tests-final/ctest.time
```

用于完整 XiangShan 重新发射的最终 wheel：

```text
build/repcut_fix_20260825/wheelhouse-v5/
  wolvrix-0.1.0-cp312-cp312-linux_x86_64.whl
sha256=2e31061a42768c9e0dd54614d400179a0bdb3ad0fc6fb07c3558a3294d13858c
```

`git diff --check` 通过。XiangShan 五个构建产物、native/partitioned 八配置 C10000 gate 及性能证据不在本文提前下结论。

## 7. 结论边界

- TNO0241 的最小源码修复已实现，并新增了实际 XiangShan 暴露出的 merged-guard 边界。
- 局部测试证明 effect 保留、分区共置、SV 顺序、event fail-fast 和 worker failure 路径；它们不能替代完整 SoC runtime gate。
- 本轮不删除旧失败产物，也不以旧 t2 的偶然正确调度代替修复后验证。
- 是否恢复 [TNO0238](./TNO0238_repcut_thread_scaling_experiment_protocol_20260819.md) 的 1/2/4/8 正式性能矩阵，必须由后续独立功能记录先闭合全部八个配置。

## 8. 增量更新（2026-08-25）

后续 v7 修复波次已完成并单独归档于 [TNO0250](./TNO0250_repcut_dpi_fix_v7_build_and_gate_20260825.md) 与 [TNO0251](./TNO0251_repcut_v7_thread_scaling_results_and_gate_boundary_20260825.md)。本文第 2 节的 `verilator_repcut_package.cpp` hash `cfb4...` 是本记录形成时的中间快照；最终源码 hash 为 `968163525bfd2d6738cb0d1e3d4066c4acb246bc6d8c4e121fb24595832e53f4`，并包含 Normal -> Early 跨 unit fail-fast。原有 focused 结论不变，post-fix 构建、functional gate 和正式性能门禁状态以两篇新记录为准。

## 9. 提交归档（2026-08-26）

修复代码已在 `wolvrix` 子模块提交：

```text
cedf610 fix: preserve DPI effects and atomic RepCut ordering
```

`tests/transform/test_repcut_pass.cpp` 中历史的 `partition_features.jsonl` 文件检查已同步到当前 `PassDiagnostics` 内嵌静态特征统计；该同步不改变运行逻辑，但保留了干净检出下的 RepCut 诊断回归。父仓库提交将记录上述子模块指针及本目录文档，其他工作区改动仍排除在外。
