# TNO0311: XiangShan RepCut ASC split ablation plan

日期：2026-09-14

状态：`PLAN REGISTERED; ISOLATED IMPLEMENTATION IN PROGRESS`。

## 1. 授权与范围

用户要求实际尝试优化 [TNO0305](./TNO0305_xiangshan_repcut_giant_asc_semantics_and_growth_20260914.md)
中的选择条件相关性与逐位写展开，验证是否进一步拆开 giant ASC。本轮不修改生产默认、
不覆盖冻结输入/assignment/ELF，不关闭 memory-read 共置或合法性检查。

## 2. 事前固定四臂

输入统一为 `build/xs/wolf/wolf_emit/xs_wolf.json`，SHA-256
`82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba`。
实验源、库、日志放在 `build/asc_split_20260914/`，不重用旧 run 输出目录。

- O：不改图，只增加观测的 control。
- A：对严格匹配的 AXI pending decrement，把 guard 成立时的动态 last 选择改为对应静态
  last；保留 guard，实际修改计算图而非仅从依赖分析中删边。仅声明经过验证的二态语义范围。
- B：同 memory、地址、事件和写使能下，合并不重叠常量掩码的细粒度写；拒绝未知/冲突掩码
  和无法证明的写优先级。保持 memory symbol/读语义不变。
- AB：先 A 后 B，不加入额外求解器参数或其他语义变换。

## 3. 判定顺序

先做匹配器、负向拒绝与局部等价测试，再用同一 RepCut phase A/B/C 重算全图，允许在
solver 之前结束。比较 ASC 数、最大 sink/comb、full closure weight、memory 分量成员。
不能把减少 sink/op 数但 memory 集合未变称为拆分。ASC 编号可能变化，按 memory symbol
和稳定 sink symbol 比较原 giant 的去向。

O 必须复现已有 301,172 ASC、最大 464,601 comb/26,852 sinks、最大 full closure weight
1,115,421，才能解释候选差异。B 删除写口后需要检查操作数/def-use 完整性，保留 phase-B/C
结构 guard。局部测试通过不等于完整 SoC 功能通过。

若出现有意义的真实拆分，再进行候选分区重建和功能验证；若四臂证明并未拆开，记录负结果、
残留连接原因及代码生成层面的可能收益，不把静态 weight 改善直接推为 Host 加速。
实现记录、结构结果及后续功能/runtime gate 分别另建 TNO。
