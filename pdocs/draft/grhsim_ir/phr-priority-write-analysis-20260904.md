# PHR priority write 分析：优先级是数据选择，不是写口顺序（2026-09-04）

记录 GrhSIM IR 设计中关于"多写口优先级"讨论的结论。相关性能证据见
`pdocs/grhsim_opt/NO0260`（PHR）、NO0196/NO0197/NO0199（FTQ）、NO0271（TAGE）、
NO0288（RenameTable）。

## 1. 问题

XiangShan BPU 的 PHR（Path History Register，`phr_0..531` 共 532 项）同一拍有 28 个动态
索引写口。标量化展开后，每个槽位生成一条 28 条件的 if/else-if 链，compute 阶段约
532×28 ≈ 1.5 万次比较（NO0260 实测 batch54 中 13,489 个 `kLogicAnd`，`Phr.sv` 占全部
perf 采样 62.45%）；gsim 对照是数组 + 28 条顺序索引写 + 532 次提交拷贝。这引出设计问题：
GrhSIM IR 是否需要表达写口优先级/顺序？

## 2. 三层形态

Chisel 源码（`testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/history/phr/Phr.scala:134-149`）
对同一地址表达式的刻意两遍写，last-connect-wins：

```scala
when(updateData.valid) {
  for (i <- 1 to PathHashHighWidth) {           // 13 条, ptr+1 .. ptr+13
    phr((phrPtr + i.U).value) := phrLowBits(i - 1)                    // 默认组
  }
  when(updateData.taken) {
    for (i <- 0 until Shamt) {                  // 2 条, ptr-0, ptr-1
      phr((phrPtr - i.U).value) := shiftBits(Shamt - 1 - i)
    }
    for (i <- 1 to PathHashHighWidth) {         // 13 条, 与默认组地址完全相同
      phr((phrPtr + i.U).value) := hashHigh(i - 1) ^ phrLowBits(i - 1) // 修正组
    }
  }
}
```

参数：`Shamt=2`，`PathHashWidth=15`，`PathHashHighWidth=13`（Parameters.scala），
13+2+13=28，与 NO0260 的写口数吻合。

- **标量化 SV**：每个槽位一条 if/else-if 链（链序即优先级，源码最后的写成为链头），
  结构性保证每槽位每拍至多一个赋值生效——优先级已物化为组合选择逻辑。
- **gsim（保留数组）**：28 条顺序索引写 `phr$NEXT[addr_k] = data_k;`，语句顺序天然实现
  last-wins，commit 为整表 532 次拷贝。

## 3. 成本结构

| 形态 | compute | commit |
| --- | --- | --- |
| 直译标量化 SV | 532 段链 × 28 条件 ≈ 14,896 次比较，O(N×k) | 532 次标量写 |
| gsim 数组 + 索引写 | 28 次地址计算 + 28 次 store，O(k) | 532 次顺序拷贝 |

差异本质：标量化形态用软件对全部 (写口, 槽位) 组合逐个求值，模拟了硬件地址译码器；
索引形态把地址直接交给访存硬件，每个写口译码一次。

边界：N（表项数）很小、k 很少时标量化可能反而更优——标量可进机器寄存器、参与
SSA/常量传播/死码消除，数组元素是内存访问且动态下标阻止优化。表示选择应按规模启发式，
属于后端 `DataLayout` 的自由度。

## 4. 关键发现：PHR 的优先级是退化的

冲突的默认组与修正组共享同一地址表达式 `phrPtr + i`，last-wins 等价为一次数据选择：

```scala
phr((phrPtr + i.U).value) := taken ? (hashHigh(i-1) ^ phrLowBits(i-1)) : phrLowBits(i-1)
```

融合后 28 个写口变 15 个（13 条 `ptr+i` + 2 条 `ptr-i`），且两组偏移分别为 +1..+13 和
-0..-1，偏移差最大 14，远小于表长 532，回绕不可能重合——**静态可证互斥**。

结论：PHR 的"写口优先级"从来不是顺序语义，而是同地址上多个数据源的 value 级选择。
在转换（ingest/变换 pass）期把同地址表达式的多次写融合成数据 mux，模型即满足写互斥，
无需任何 IR 级顺序/优先级机制。

## 5. 对 GrhSIM IR 的设计结论

- 不引入 `priority` parameter，不引入 `op_orders` 图级顺序（2026-09-04 讨论后否决并回退）。
  理由：在当前 NBA 式步进语义（读见旧状态、写入次态）下，op 顺序唯一有语义的场合是同状态
  写冲突；而 PHR 实证表明该冲突可在转换期消解为 value 级选择。
- `core` 维持写互斥规则：同一 array 状态的任意两个 `memWrite`/`memFill` 不得在同一次
  `G` 应用中写入同一 bit；`ops` 数组顺序不携带语义。
- 必备的一等能力是动态索引端口 op（`core.state.memRead`/`memWrite`/`memFill`）和
  `core.array` 状态类型；ingest 端需做标量族 re-aggregation（SV 层数组已被 firtool 摊平，
  见 NO0197），否则无数组可保。

## 6. 待查证

- RenameTable（NO0288）的多写口地址各自独立（非同一表达式），冲突时是否存在真实优先级、
  是否同样可消解，需单独查证。若存在真实优先级，在互斥规则下只能消解为"无更高优先级
  同地址写"的显式条件（O(k²) 比较网络，k=写口数），需评估该形态的实际代价。
- 融合变换（同地址表达式写口 → 数据 mux）的通用判定条件和实现位置（ingest 还是独立
  pass）待定。

## 7. 后续（2026-09-05）：结论修订

讨论后决定：有序多写口以单个 op `core.state.memWriteSeq` 表达——operands 每三个一组
（`updateCond, address, data`）构成写口，operand 顺序即覆盖顺序（后者覆盖前者）。该 op
放入 core 方言而非 cpu 方言：其语义（按序应用、同地址覆盖）是后端无关的状态转移定义，
CPU 后端生成为顺序 store（gsim 形态），其他后端可展开为优先级选择逻辑。放在 cpu 方言会
使再向量化后的模型锁死在 CPU 后端。core 的跨 op 写互斥规则维持不变，需要有序覆盖的多
写口收进单个 op 内表达。
