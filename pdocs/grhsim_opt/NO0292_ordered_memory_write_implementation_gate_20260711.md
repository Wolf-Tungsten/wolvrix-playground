# NO0292 Ordered memory-write implementation gate

日期：2026-07-11

## 1. 目标

[NO0290](./NO0290_rename_table_write_only_fresh_regression_20260711.md) 的 write-only true-merge 功能正确，但用显式同地址冲突保护把三组 RAT lowering 放大为近二次网络。[NO0291](./NO0291_ordered_memory_write_contract_plan_20260711.md) 因而规划显式 ordered-write contract。本阶段完成实现与 synthetic gate；尚未据此声称 SimTop 静态规模或 runtime 已改善。

## 2. IR 与 lowering

`kMemoryWritePort` 新增两个可选属性：

- `memoryWrite.priorityGroup`：有序写组；
- `memoryWrite.priority`：组内优先级，`0` 最高。

同组端口按 priority 从大到小执行，最高优先级端口最后写入。reg-to-mem 的 `enableOrderedWrites` 默认关闭；开启后，strict true-merge 仍保留 writer 自身 enable、common terms、storage domain guard、data、mask、event 与 reset lowering，但不再物化 pairwise address-conflict guard，而是在生成的 memory write 上写入连续 priority。

CLI/Python 增加 `-ordered-writes`、`-no-ordered-writes` 与 `ordered_writes=`。XiangShan GrhSIM flow 默认设置：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES=1
```

可设为 `0` 回退到显式冲突保护路径。

## 3. 调度与 emitter 契约

activity-schedule 在构图前校验：

- 两个属性必须成对出现，且只能用于 `kMemoryWritePort`；
- group 非空，priority 非负、唯一且连续；
- 同组端口必须指向同一 memory，并具有相同 event family。

同组 writes 被视为不可拆分的 commit 单元，按 priority 降序排列。该保证同时覆盖默认 guard-event bucket 路径，以及 `commitGuardEventBuckets=false`、commit size cap 小于组大小的路径。

SystemVerilog emitter 同样在一个 sequential block 内按 priority 降序输出，避免该 IR 只有 GrhSIM emitter 能保持正确语义。GRH 规范已补充属性约束、碰撞语义和两端口示例。

## 4. Synthetic 结果

65 writers、4 个实际 row、缺失 row 0、packed reset 的 write-only synthetic 在 ordered mode 下得到：

```text
kMemoryWritePort = 65
kEq              = 4 * 65 = 260
priority group   = 1
priorities       = [0, 65)
```

`kEq=260` 只保留输入 scalar decoder 中已有的 row equality，没有新增 `65 * 64 / 2` 级别的 pairwise conflict equality。既有非 ordered synthetic 仍覆盖显式冲突 fallback。

额外执行门禁覆盖：

- 同地址两个 enabled writers：priority `0` 的数据获胜；
- 不同地址两个 enabled writers：两次写入都生效；
- SV emitter：低优先级语句位于高优先级语句之前；
- activity-schedule：关闭 guard bucket 且 `maxOpInCommitSupernode=1` 时，两写组仍不拆分且顺序正确。

## 5. 验证

执行命令均先 `source env.sh`：

```text
cmake --build wolvrix/build -j8 --target \
  transform-reg-to-mem transform-activity-schedule \
  emit-sv-storage-ports emit-grhsim-cpp

ctest --test-dir wolvrix/build \
  -R '^(transform-reg-to-mem|transform-activity-schedule|emit-sv-storage-ports|emit-grhsim-cpp)$' \
  --output-on-failure
```

初次定向回归四项全部通过：

```text
emit-sv-storage-ports       PASS   0.05 s
emit-grhsim-cpp             PASS 145.36 s
transform-activity-schedule PASS   0.03 s
transform-reg-to-mem        PASS   0.15 s
```

补充 atomic chunk case 后，`transform-activity-schedule` 再次通过（`0.05 s`）。

## 6. 下一 gate

下一阶段从同一 pre-reg-to-mem checkpoint 生成 SimTop 静态结果，重点核对三组 RAT 的 `priority_conflicts`、graph ops、compute/commit supernodes、generated C++ 和最终 text。只有静态规模至少消除 NO0290 的明显回退，才进入 fresh 10k/50k 与固定 CPU old/new/old runtime gate。
