# F09：统一 node 构建与按 node 数划分 supernode

状态：2026-10-31，F09.0–F09.5 的旧实现已提交并验收，见
[F09-acceptance.md](F09-acceptance.md)。本页是 F09.6 的当前设计，已实现并通过代表性回归，验收见
[F09.6-acceptance.md](F09.6-acceptance.md)。它取代“op work 切 leaf + 提示 tie-break”和“单 node 超 work 预算
豁免”两种方案。旧代码与测量保留历史含义，不能当作新方案已生效的证据。

## 1. 两层分图，分别负责一件事

**先形成 node，再按 node 数量形成 supernode。**

~~~text
FIRRTL / SV → 普通 GRH ops + 可选 FIRRTL node attrs
→ 普通 simplify / 仿真转换 / phase 与 sink 分离
→ node 构建：有可用 FIRRTL 提示按提示分组，其余按 MFFC 分组
→ 统一 Node DAG：每个 node 的容量计数为 1
→ 按 node 数量划分 supernode
→ 后续局部简化、sink 调度、emit
~~~

node 对两种前端具有相同的分图语义：它是一组当前实际 ops，对外暴露真实
输入、输出与依赖。区别只在于形成 node 的依据。supernode 不需要知道
某个 node 来自 FIRRTL 还是 MFFC，也不以其中 op 数量、位宽加权 work
或源语言换算容量。

不新增 FIRRTL 执行 op 或恢复前端 AST。Node DAG 可以是分图期间的分析
结构，最终沿用 GRH 的实际 leaf/node 与 supernode owner 表达结果。

## 2. simplify 透明性保持不变

node attrs 表达来源关联，不能成为普通优化的作用域或 DontTouch。
跨 node/SV 的 primitive CSE、inline、重关联、折叠、packing、mux/write
normalization 和 DCE 都正常执行。可准确维护的关联随结果维护，不能维护
则丢弃或降级，不保活根、不增加 assign 载体、不恢复被删除的 op。

node 构建发生在上述优化之后；它使用当前图上仍存在的提示，而不是要求
优化后的图恢复成原始源码 node。根不是构建前提；完全折叠为输入/常量、
没有独立执行计算的源名字不凭空计为一个 node。

分图后实际 node owner 继续约束局部 simplify。这是两种前端共同的执行
边界，不是分图前的 source-node 优化屏障。

## 3. 有提示按 FIRRTL，无提示按 MFFC

### 3.1 FIRRTL 提示区域

从当前 ops 的 members 读取可用源关联，同一源 node 的当前计算形成一个
分图 node。按 sourceUnit/circuit/module/instancePath/nodeName 区分身份；
Bundle 的 fieldPath 是类型展平信息，不是 op 容量切分依据。Vector 保留
shape，不按元素数增加 node 个数。

不先按 op work 切 leaf 再尝试拼回提示区域。提示覆盖区域的大小由当前
可用关联决定，不由 max-node-work、op 数上限或后续 supernode 容量决定。
origins 仅供诊断，不用来补造成员。

### 3.2 没有可用提示的区域

对剩余 ops 按 MFFC（最大无扇出锥）构建 node。给定锥根，将只在该锥内
被消费的上游组合计算纳入；仍向锥外扇出的共享 producer 形成边界。输入、
状态/效果、phase 边界及已形成的提示 node 是分析边界。

MFFC 的大小由当前依赖/扇出结构决定，同样不按 op 数量或 work 拆分。
这覆盖纯 SV、FIRRTL 中没有显式 node 的计算、提示丢失的计算和混合区域
的无提示 glue，不伪造源 node 名字。

### 3.3 共享与合法性只在 node 构建层解决

普通 CSE 可以让多个源 node 关联同一个 op。必须在构建统一 Node DAG 时
规范化为每个实际 op 只有一个执行归属；共享部分作为真实边界保留一次，
不能为恢复源码 node 撤销 CSE、自动复制共享计算或传递 union 全部相交集合。

非凸、重叠或跨真实 phase/state/effect 边界的提示，只在冲突处规范化；
无法采用的部分按 MFFC 处理，报告原因。缺根本身不是冲突。合法 node
形成后，supernode 阶段不再读取 members 或自行重划内部 ops。

## 4. 统一 Node DAG 的合约

- 每个需要分组的实际 op 属于唯一 node；非空 node 计数为 1。
- node 可以有多个真实边界输出，不要求一个源根、一个持久槽或一个活动位。
- 节点间边由真实跨 node 的 ValueId 和必要的效果顺序产生；不由属性名字推导。
- Node DAG 与后续 supernode quotient 均须无环；状态、效果、旧值采样和
  writer prerequisite 按现有语义验证。
- FIRRTL 来源、MFFC 来源及源关联只用于构建和诊断，不形成两套调度语义。

源注解、统一 node、supernode 是三个不同概念。源注解可以多对多；统一
node 是实际唯一归属的分图单位；supernode 是若干完整 node 的执行组。

## 5. supernode 容量只按 node 数量

配置表达为 max-supernode-nodes。对任何候选 supernode：

~~~text
size(supernode) = number_of_nodes(supernode)
每个统一 node 的容量权重 = 1
~~~

一个含 180 ops 的 FIRRTL node、一个含 180 ops 的 MFFC node、一个仅含
1 op 的 node，对 supernode 容量都贡献 1。容量为 4 时可容纳 4 个完整
node，第 5 个进入其他 supernode；不因内部 op 多而把某个 node 切成几个。
因此不存在“单 node 超 op/work 预算”的例外分支，也没有两种来源的豁免。

移除 max-node-work 对 node 大小的控制。max-supernode-work 不得静默改名
后沿用原数值，也不得把每 node 的 op work 伪装成 node-count 权重。旧选项
与 checkpoint 需要显式迁移、拒绝或重新生成，不自动折算阈值。

supernode 分组可以考察 Node DAG 的连边、拓扑与真实边界开销，容量/大小
判断始终只计 node 数。旧 bytes 实验中的 firing×op-work 项不进入新分组
决策；op 数、位宽 work 和内部复杂度至多作为诊断统计。

编译器分文件/分函数的源码尺寸限制是独立后端问题，不改变这里的执行
node 边界，也不反向成为拆分 node 或决定 supernode 容量的依据。

## 6. owner、局部简化与 clone

最终 leaf/node owner 表示统一 node，supernode owner 表示其所属执行组。
supernode 分组不顺便融合多个 node 的身份，也不靠 fuse-leaves 改变容量
计数。旧 leaf fusion 开关在新流程中需要撤下或单独重新设计，不能悄悄
影响“一个 node 计一次”的定义。

后续 node 内 simplify 减少 ops 时，每个剩余 node 仍计 1；整个 node 变空
则删除并更新计数。独立 clone 若产生新执行 node，按新 node 计数并重新验证容量、
依赖与调度；node 内局部复制不因多了 op 改变容量。原有 clone 次数等
资源限制单独表达，不能把 op work 上限重新带回 supernode 分组。

优先完成无 clone 的两层分图基线，再恢复可审计的可选 clone。不为提示
新增持久化/发布值；实际跨执行组消费者决定边界与激活。

## 7. 配置、恢复与报告

- firrtl-nodes=off：忽略源提示，全部按 MFFC 形成 node，供对照使用。
- firrtl-nodes=prefer|auto：有可用 FIRRTL 提示按提示形成 node，其余按 MFFC；
  不再仅把提示用于同成本 tie-break。默认 auto；off 保留为显式消融对照。
- 新的 node 构建策略、node-count 分组及 max-supernode-nodes 纳入新的
  config/checkpoint revision；保留 schema 2 的非功能属性语义。
- 报告分别统计源关联、FIRRTL 形成的 node、MFFC node、共享/冲突降级原因、
  每 SN 的 node 数、真实边界与运行计数。op/work 分布仅为诊断。
- 旧 F09 v2 checkpoint 不能只替换配置文本后冒充新 node-count 结果。

属性维护的 64 项上限、分析索引的容量限制是元数据资源约束，与执行 node
大小无关。提示确实丢失时退回 MFFC；不能用 op 数截断 node 伪装元数据降级。

## 8. 验证与收益归因

先验证 node 构建，再验证 supernode 分组，最后验证行为与性能：

1. 同一初始图的标注/去标注普通 simplify 结构一致，跨来源 CSE 不回退。
2. 提示覆盖部分按提示成 node；未覆盖部分及纯 SV 按 MFFC 成 node。
   同时覆盖无根、Bundle/Vector、多实例、共享、非凸、phase/sink 和效果。
3. 对一个 node 改变内部 op 数而保持 node 边界，容量贡献始终为 1；提示
   node 和 MFFC node 都验证，包含旧 work cap 以上的大锥。
4. 固定 Node DAG，以容量 K 测 K/K+1 个 node 的分组；容量判断不读取 op work。
5. 每 op 唯一 owner、quotient 无环、SinkSchedule、真实激活、旧值与独立
   多周期 scoreboard 通过；混合前端、恢复和幂等均通过。
6. 固定同一 split checkpoint 重测 RenameTable/Queue2；按 node 构建与 SN
   分组两层归因，不用旧 v2 的 op-work 结果证明新策略已验收。

F10 负责整机混合输入与差分，F11 负责正式吞吐/构建成本及默认策略。尚无
本方案的运行性能结论。

## 9. 已提交的 F09.0–F09.5（历史）

Wolvrix 7e51d14 / playground 8d31215 已完成 schema 2、soft-node-v2、
simplify 透明性、op 软提示 tie-break、legacy/bytes、fusion/clone 和配置报告。
完整回归 79/79，真实模块证据见 F09-acceptance.md。该提交仍按 op work
形成 leaf/SN，未实现本页的统一 node + node-count supernode。

不重写历史验收数字，也不恢复 F08 的 source-node 普通优化屏障。

## 10. F09.6 推进顺序（已完成）

| 步骤 | 交付 | 退出条件 |
| --- | --- | --- |
| F09.6a 统一 node 构建 | 提示驱动 + 剩余 MFFC；共享规范化、真实边界及 owner 映射 | 覆盖所有实际 ops、归属唯一、无 op 数/work 切分；两前端同一 node 合约 |
| F09.6b Node DAG 分组 | supernode 算法输入改为 Node DAG，容量权重全部为 1 | 按 K/K+1 node 分组；大/小 node 贡献相同，分组不访问内部 op work |
| F09.6c 配置与调度迁移 | max-supernode-nodes、新 revision、恢复拒绝、移除旧 work/fusion 耦合 | 新身份可恢复；旧配置不静默折算；SinkSchedule 与行为通过 |
| F09.6d 生产回归与消融 | Make/Python/mixed、真实 RenameTable/Queue2、可选 clone 验证 | simplify 透明、两层统计完整、实际性能如实记录 |

F09.6a–d 已完成，详见新验收记录。默认 auto/legacy/128 nodes 是该合约的
实现选择；没有基于此宣称吞吐提升。旧 v2 报告保留历史含义，不作新策略证据。
