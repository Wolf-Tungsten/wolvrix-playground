# TNO0424 恒零表消除后的调度扩散证据

两侧均从同一冻结 RTL 重新生成。调度前 GRH、全部生成 C++ 和头文件均与各自冻结参照逐字节相同。阶段导出没有改变结果；详见 `stage-C/export_gate.json` 与 `stage-E/export_gate.json`。

## 首次分歧及扩散

前端净删除 49 个操作、改写 17 个 Mux。进入 activity-schedule 之前，唯一对齐的 4,886,840 个组合/提交操作中有 3,431,517 个拓扑序位置不同；第一处由 DecodeUnitComp 中更早就绪的节点插入引起。位置不同包含整体位移，不能将其等同于那么多个逻辑或依赖发生改变。

`GraphBuilder::freeze` 会将存活操作重新紧凑编号；`cloneSourceUsesForCompute` 将 source 放入以 OperationId 为键的 unordered_set，然后按其迭代顺序创建 clone。两版 source 语义集合完全相同，共 338,629 个、全部唯一匹配，但 338,534 个位置不同。集合一致、遍历不一致是直接记录，不是根据 batch 编号推断。

source clone 完成后，可唯一对齐 6,930,879 个操作，另有 210,454 个无唯一语义指纹的操作保持歧义、不强行对应。共同拓扑序中的 6,927,588 项有 6,352,393 个位置不同。

| 阶段 | E compute node | C compute node | 差值 |
| --- | ---: | ---: | ---: |
| 初次创建 | 1,065,965 | 1,067,452 | +1,487 |
| declared boundary 拆分后 | 1,065,965 | 1,067,452 | +1,487 |
| 第 1 轮环拆分后 | 1,066,179 | 1,067,666 | +1,487 |
| 第 13 轮环拆分后 | 1,067,570 | 1,069,057 | +1,487 |

因此额外节点在初次创建时已经出现。两侧后续拆分数量相同，不能把净增加的 1,487 个节点归因于环拆分。

## 共享归属的直接决策记录

已唯一对齐的共享归属判断中，682,878 次相同，4,835 次不同；3,381 次无法可靠对齐，单独保留。主要变动包括：

- 2,347 次由 E 的吸收成功变成 C 的不是最早消费者。
- 1,360 次反向变化。
- 其余涉及可达性、节点是否已有 common owner、容量等条件；原因记录保留原短路求值顺序。

第一组差异已超出译码模块：L2 MainPipe 的 `mshr_releasedata_s3` 消费 `_perfEvents_T_5`。E 中因为不是最早消费者而分出共享节点，C 中允许吸收。其他变化集中在 DataModule、OthersEntry、ROB、Dispatch、TLB 等。

## 下一步干预边界

实现默认关闭的 `WOLVRIX_RESEARCH_SOURCE_ORDER`：按完整 source 类型、操作数/结果名、位宽、符号及属性验证集合，拒绝缺失、增加、重复或歧义项，只恢复 source 遍历顺序。不会按 OpId 或 batch 编号对应。先做版本重放自身的一致性 gate，再尝试 C 重放 E。

此时尚未确认这条结构链是性能根因。首对独立 PMU 观察到 E 指令数少约 0.5765%，但还需四对、动态执行计数和干预结果。也不能把任何一张结构复现图当作整机性能根因的充分证据。

## 产物

- [早期阶段差分](../../build/xs/decode_constant_investigation_20261104_v1/early_stage_diff.json)
- [逐阶段节点差分](../../build/xs/decode_constant_investigation_20261104_v1/stage-comparison/stage_diff.json)
- [共享归属全部差异](../../build/xs/decode_constant_investigation_20261104_v1/stage-comparison/shared_decisions.json)
- [E 导出一致性](../../build/xs/decode_constant_investigation_20261104_v1/stage-E/export_gate.json)
- [C 导出一致性](../../build/xs/decode_constant_investigation_20261104_v1/stage-C/export_gate.json)
