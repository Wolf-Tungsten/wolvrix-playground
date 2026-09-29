# GRHSIM IR 仿真模型重构

## 定义状态集合 S

- I 输入
- S_reg 寄存器状态
- S_mem 存储器状态
- S_latch 锁存器状态

## 定义输出集合 O

O 包含所有输出信号

## 模型总览

将整个仿真模型更加精细的拆分成6个阶段 P：

- P_input：检测输入变动
- P_event：以 S 为起点，计算所有事件信号的逻辑锥
- P_general：组合op，reg/mem/latch 的 read op，reg/latch 的 write op，dpi/系统调用 op，内部划分多个超节点
- P_mem：mem 的 write op
- P_publish：实现 non-block-assign，判断是否到达不动点
- P_output：以 S 为起点，计算所有输出信号的逻辑锥；执行 time-slot 语义的系统任务

调度方法：

eval() {
    P_input();
    for(i = 1...MAX_ROUND) { // 每次循环称为一个 round
        P_event();
        P_general();
        P_mem();
        fixedPoint = P_publish();
        if(fixedPoint) break;
    }
    P_output();
}

关键内存布局：

- 所有 reg/latch 状态排布在 RegLatchStore 结构体中，语义上包含 S_reg 和 S_latch；仿真类持有 regLatchStore 和 regLatchStoreNext 两个实例，后者作为前者实现 NBA 写入的影子状态；
- 所有 mem 状态排布在 MemStore 结构体中，语义上包含 S_mem，仿真类持有 memStore 一个实例；
- I 和 所有跨越超节点的边界信号排布在 BoundaryValueStore 结构体中，仿真类持有 boundaryValueStore 一个实例；

- EventStore 结构体按与 EventActStore 相同的 (event, edge) 去重聚类枚举排布边沿检测历史值，每个 edgeDet 一个 prev 槽位（一个 event 信号可挂多个 edgeDet，各自的 prev 互不干扰）；仿真类持有 prevEventStore 一个实例，用于对比新旧检测事件边沿；event 信号的当前值只是 P_event 阶段的临时量，edgeDet 用完即弃，不出阶段、不持久化；
- 所有 (event, edge) 去重聚类后排布在 EventActStore 结构体中，每个bit表示一个事件边沿是否发生；仿真类持有 eventActStore 实例；eventActStore 每轮 P_event 覆盖重算、不粘滞：某 bit 仅在对应边沿被检出的当轮为 1；
- eventActiveFlag：uint8 数组，长度等于 P_general 超节点数量，每一bit表示一个超节点是否被事件激活；由 P_event 每轮根据当轮 eventActStore 重建，脉冲式（仅在检出边沿的当轮有效）；对下游不含事件 op 的超节点视为常 1（豁免，直接不做边沿检测）；
- dataActiveFlag，dataActiveFlagNext：uint8 数组，长度等于 P_general 超节点数量，每个bit表示一个超节点是否被数据激活；dataActiveFlag 为粘滞语义：置位后跨 round、跨 eval 保留，直到对应超节点真正点火时清除；
- timeslotTriggerFlag：uint8 数组，长度等于 P_output 中带事件门控的 time-slot 系统任务数量，每一bit表示对应任务在本 eval 内是否已被触发；由 P_event 检出对应边沿时按静态映射置位，eval 级粘滞（round 间不重建、不随 eventActStore 覆盖而失效），P_output 消费后清除；无事件的 time-slot 任务不占位（走历史值判定）；

## 分阶段说明

### P_input

从仿真类边界装载输入到 boundaryValueStore 中，检测激活，更新 dataActiveFlag；

注意，输入的clk等纯事件信号不更新 dataActiveFlag，而是在 P_event 中检测边缘；"纯事件信号"的判定标准是信号只用作 op 的 event 操作数；rst 这类信号在 GRH IR 图结构中同时出现在 en 信号合成路径里（如异步复位写值的 mux 选择端），属于数据使用者，其变化照常经 P_input 置位 dataActiveFlag，因此多次异步复位不会被 && 门控吞掉；

### P_event

将所有以 S 为起点，以所有带事件操作数的 op（含 P_general 与 P_mem 中的 mem 写、事件触发 system task/DPI 等）的 event 操作数为终点的**事件逻辑锥**提取出来，在该阶段集中计算；P_mem 的 event 操作数同样由 P_event 统一检测，P_mem 自身只读 eventActStore；

锥体构建采用复制+剥离：把事件锥所需的 op 复制进 P_event，自包含计算，不依赖 P_general 的 boundary 输出（P_event 在 round 内先于 P_general 执行，而 P_general 的门控又依赖 P_event 的产物，复用会成环）；事件锥理论上不会很大——时钟树/复位树上不会挂很多操作，大概率是从某个 reg 读出后做简单布尔操作——每轮重算代价可接受；

GRHSIM IR 扩展一个 edgeDet op，用于检测边沿。IR 形态：

- 操作数：event 当前值（P_event 事件锥的末端值）；
- 参数：edge 类型枚举（posedge / negedge / both 双边沿），编码沿用现状 event_edges 参数并补 both；4-state 下边沿判定沿用 SV 规则，prev 槽位按此存足宽编码；
- 产物绑定：lowering 时先做 (event, edge) 去重聚类，每个聚类项生成一个 edgeDet，静态分配 eventActStore 的 bit 下标与 prevEventStore 的槽位下标，作为 op 的 attribute；edgeDet 不产 data value，执行即写 eventActStore 对应 bit 并更新自己的 prev 槽位；
- 同一 event 信号可以挂多个 edgeDet（例如同一 rst，有的消费者检测上升沿、有的检测下降沿），各自独占 prev 槽位、互不干扰；
- prevEventStore 各槽位 init 为对应 event 信号的 init 值，上电首个 eval 不报边沿；
- edgeDet 对比后立刻更新 prev 为新值，避免重复检测；因此下一轮 P_event 对同一事件看到的是 新值-新值，不再产生边沿；配合 eventActStore 每轮覆盖重算，同一边沿只在被检出的当轮可见（脉冲式，不粘滞）；同一 eval 内事件信号跨 round 翻转会产生多个边沿（glitch 时钟下同 eval 可能多次写同一 reg），与 event-driven 仿真行为一致，接受、不额外约束；

P_event 向后续阶段除了提供 eventActStore，还更新 eventActiveFlag，后文介绍更新规则；

### P_general

按超节点划分的仿真图主体，剥离**事件逻辑锥**、**输出逻辑锥**、mem 写入 op（只剥离op不剥离逻辑锥），划分超节点；

事件锥/输出锥的剥离方式是复制+剥离：锥体复制到 P_event/P_output 后，P_general 侧仅为事件或输出服务的 op 删除——所有关联事件的 op 已改从 eventActStore 读取事件判断，原用于计算事件信号的 op 在 general 侧不再需要；但如果某段逻辑同时在数据通路和事件通路上，数据通路那份必须保留（两侧各算各的，同一 round 内读同一 S 快照，结果一致）；

和现有模型的最大改进是 reg/latch 的 write op 合入超节点，动机是实现边界消减；

P_general 中的 reg/latch/mem read op 从 regLatchStore 和 memStore 读取输入；

P_general 中的 reg/latch write op 写入 regLatchStoreNext，等到 P_publish 阶段再集中提交，实现 non-blocking assign 效果；

P_general 中的 reg/latch write op 写入时做变化检测：新值与 regLatchStore 中的当前可见值比较，真变化才对下一round的激活写入 dataActiveFlagNext（不变则 publish 对该 reg 是无操作，无需唤醒读者）；检测放在写 op 侧是因为写 shadow 时天然能看到旧值；

部分位写（bit-select）与同一 reg 多写者的合并基准一律是 regLatchStoreNext（本轮已累计的写入）：写 op 读出 next 中的当前内容、合并本 op 的位段后写回；"每轮开始时 regLatchStoreNext == regLatchStore"这一不变式由 P_publish 的全量拷贝天然维持，无需额外同步；

P_general 中所有关联事件的 op 的事件判断都从 eventActStore 中读取，不自行重复计算；

P_general 中超节点 i 的点火条件为 eventActiveFlag[i] && dataActiveFlag[i]（两个数组长度均等于超节点数量）：

-  eventActiveFlag，由 P_event 在检出边沿的当轮置位（随当轮 eventActStore 一并重建，脉冲式），根据当前超节点影响的（注意不仅是当前超节点包含的，还需要根据逻辑锥从sink倒追）含事件op计算，包括P_general的和P_mem中的，反应朴素的动机是，“如果最终影响的寄存器写入根本不更新，则整个逻辑锥不必计算”；下游不含任何事件 op 的超节点（例如只汇入 latch write 的锥）豁免事件门控，eventActiveFlag 视为常 1（直接不做边沿检测）；

- dataActiveFlag，由输入变动、前驱超节点、上一轮 P_publish置位，反应非事件的数据流更新，朴素想法是输入不更新则不需要求解；粘滞语义：超节点因事件门控未满足而未点火时，其置位保留（跨 round、跨 eval），直到真正点火时清除；

- P_event 检出边沿时不置位 dataActiveFlag：若某 eval 中数据变化但无边沿，锥入口超节点的 dataActiveFlag 置位会残留下来；待边沿到来的 eval，锥上超节点在同一 round 内按拓扑序逐级点火、从 S 重算整条锥，因此不存在陈旧值；数据锥为纯常量的边沿写（如 posedge clk 下 q<=0）在初次点火后不再有点火来源，但此时重写也是无操作，跳过不影响正确性；

P_general 超节点之间的边界数据通过 boundaryValueStore 传递；

P_general 超节点计算时，对后续超节点的激活记录在 dataActiveFlag 里；

超节点激活后，立刻清除自己的 eventActiveFlag 和 dataActiveFlag 位。

残留置位的典型案例：寄存器 A 的输出接寄存器 B 的输入，某个 posedge 上 A 更新，publish 将 B 所在超节点的 dataActiveFlag 置位；此后的 round 中 eventActStore 已无该边沿，B 的超节点因 eventActiveFlag=0 不点火，置位残留至下一个 posedge 才被消费——这正符合 NBA 语义（B 在下一个沿才采样 A 的新值）。

超节点划分的事件域约束：

- 若超节点完全不含带事件操作数的 op（纯组合 op、latch write），则不受事件域约束：它点火时会把激活传播给所有后继超节点，不会在 sink 处搁浅；
- 若超节点含有带事件操作数的 op（reg write、事件触发的 system task/DPI 等），则：
  1. 所有这些 op 的事件集合必须完全相等（canonical event key，含边沿方向，即一个时钟域）；子集也不行——多个事件对单个 op 是 or 关系，集合外边沿触发的点火会让事件集合较小的 op 的 guard 不通过、写不执行，而标志位已被清除，其待提交更新被覆盖丢失；
  2. 该超节点内所有 op（包括组合 op）向下游传递影响到的所有带事件 op，也必须属于同一事件集合；否则 eventActiveFlag 是按"当前超节点影响的所有含事件 op"从 sink 倒追计算的，下游其他域的边沿会触发本超节点点火、清掉标志位，而本超节点自己的写 op 因边沿未发生并未执行，更新丢失；

动机：dataActiveFlag 是超节点粒度的粘滞位，超节点一点火即清除；点火与写 op 执行必须严格同域，清除才安全。注意约束只限制本超节点向下游的影响范围：从其他域流入的数据（reg/latch/mem read 直接读 S，天然自由；前驱组合超节点的 boundary 输入也只是数据）不受限制。（现有后端 cpu.st.form-event-domains 已在按 canonical event key 聚类写口，划分超节点时复用同一 key 即可。）

超节点划分沿用现有 node→supernode 合并框架（单消费锥吸收、coarsen、DP 分段、规模上限），在其上加两条规则：①reg/latch write op 作为可合并 op 参与划分，不再独立成 commit 相位；②事件域约束作为合并禁止条件——合并候选 op 时检查其扇出传递闭包，凡是能到达异域带事件 op 的不得并入。

### P_mem

不分超节点，从 eventActStore 和 boundaryValueStore 获取数据，执行 mem 写入，是原地更新。全部四种 mem 写类 op（memWrite / memFill / memAssign / memWriteSeq）都在 P_mem；带事件操作数的由 P_event 统一检测、本阶段只读 eventActStore 门控；不带事件操作数的每轮都执行，靠变化检测兜底。所有 mem 写 op 做 cell 级变化检测：写入前与 memStore 当前内容比较，无变化则不写、不置 dataActiveFlagNext——无事件写 op 靠它保证收敛，也避免同值重复写唤醒读者。

mem 写 op 不进超节点的原因有二：

1. 避免 P_publish 阶段对 mem 做大规模双缓冲拷贝（memStore 单实例、原地更新）；
2. 保持"本轮读旧值"语义：原地写若发生在 P_general 中间，同轮靠后超节点里的 memRead 会读到新值，破坏与 reg 写一致的 NBA 语义；集中到 P_general 之后，同轮所有 memRead 看到的都是上一轮结束时的 mem 状态。

P_mem 内各 mem 写 op 自带 eventAct 门控，按静态优先级依次原地写；多个被激活的写 op 同地址相撞时，优先级靠后的覆盖先写的。

P_mem 执行时更新 dataActiveFlagNext，激活规则按读者地址形态区分：

- 地址为静态常量的 memRead：精确判断，仅当本次写地址与该读地址相等（重叠）时才激活其所在超节点；
- 地址为动态的 memRead：不做判断，保守激活其所在超节点。

### P_publish

实现 NBA、防止循环激活的关键；

fixedPoint = dataActiveFlagNext 为全 0；

P_publish 将 dataActiveFlagNext 并入 dataActiveFlag（并入而非覆盖：dataActiveFlag 中未被消费的置位——即被事件门控拦下的超节点——保留，跨 round、跨 eval 持续有效，直到超节点真正点火时清除；因此 eval 结束时不存在激活丢失）；

清空 dataActiveFlagNext；

P_publish 将 regLatchStoreNext 无条件全量 memcpy 到 regLatchStore 中（reg 和 latch 都是，不做 dirty 跳过，换取实现简单；该拷贝同时维持"每轮开始时 next == current"的不变式，供写 op 以 next 为合并基准）；

eventActiveFlag 无需在此清理，下一轮 P_event 会根据当轮 eventActStore 覆盖重建；

返回 fixedPoint。

### P_output

将所有以 S 为起点，以输出为终点的**输出逻辑锥**提取出来，在该阶段集中计算，形成 eval 的输出；同样采用复制+剥离：输出锥所需 op 复制进 P_output，自包含从 S 计算，每个 eval 在到达不动点后计算一次；暂不做跳过机制，每个 eval 无条件全量计算（理论上输出锥很小，后续有需要再加激活门控）。

$monitor / $strobe 类 time-slot 语义的系统任务也挪到本阶段，收敛后执行一次，对齐 IEEE"time slot 末只报一次"的语义；其参数锥与输出锥同等处理，复制进 P_output 从 S 自包含计算：

- 无事件的（如连续监测的 $monitor）：靠保存的历史值做"较上一 time slot 是否变化"判定（沿用现状 demonitor 的历史机制），变化才报；
- 带事件门控的（如 always @(posedge clk) 块内的 $strobe）：触发条件在 round 内由 eventActStore 给出，但 eventActStore 每轮覆盖、到 eval 末已不可见，因此这类 op 的触发记录由 timeslotTriggerFlag 承载（见关键内存布局）——P_event 检出对应边沿时按静态映射置位，eval 级粘滞，P_output 消费后清除；
- always_comb 里的 $display 等仍留在 P_general：delta-cycle 内重复触发符合 IEEE 语义，无需特殊处理。

### 初始化

init 时将 dataActiveFlag 全量置位（全脏）：上电后首个 eval 让整个图全量求值一遍，之后靠正常的变化传播收敛；否则第一个事件边沿到来时，从未有过数据变化的锥（如常量锥）不会点火。同时 regLatchStoreNext 的初始内容与 regLatchStore 一致，维持"每轮开始时 next == current"的不变式。





