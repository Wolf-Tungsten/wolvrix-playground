# GRHSIM IR 仿真模型重构

## 定义状态集合 S

- I 输入
- S_reg 寄存器状态
- S_mem 存储器状态
- S_latch 锁存器状态

这些集合描述逻辑状态及其行为；优化可以折叠、合并、打包或数组化状态，最终物理存储归属按优化后的规模、连续性和更新代价决定。保持仿真行为等价，允许改变源 RTL 的状态表示。

## 定义输出集合 O

O 包含所有输出信号

## 优化与代码生成约束（2026-10-01 作者补充）

1. **生成 C++ 必须分 TU 并行编译**：整核代码按函数和规模分批生成多个 translation unit，初始化和过大的阶段函数也需受控拆分；生成完整源文件清单，经项目 Makefile 并行编译、链接。当前整核单文件生成方案需要替换，多 TU 属于可交付要求。
2. **declaredSymbol 贯穿两侧 IR 流水线**：GRH IR 的 `simplify` 保留 `declaredSymbol` 及相关声明来源信息，lower 到 GrhSIM IR 后继续维护，用于指导状态同族识别、数组及高维结构恢复、打包等优化和最终命名。折叠、合并或拆分后保留来源到新状态、位段或数组索引的映射；优化等价性由数据流、事件和读写关系保证。
3. **GrhSIM IR 采用分而治之的优化顺序**：先在尚未分区的全图上执行 `reg-to-mem`、`comb-pack` 等优化，充分利用全图的优化空间，再做全图 `simplify`；第一轮分解形成 `P_event`、`P_general`、`P_output` 三个计算分区，各分区独立 `simplify`；第二轮分解只在 `P_general` 内划分 supernode，构建活动度调度。全图优化和分区化简完成后再生成最终 CPU mapping。
4. **性能优先，提供优化后状态的可读性**：允许折叠、合并和改变状态形态，数组是合法 IR 类型，并鼓励恢复高维数组。`regLatchStore` 承载零碎状态，以 next/current 和 publish 整块拷贝实现 NBA；`memStore` 承载大块连续状态，在独立阶段更新，避免大规模内存拷贝并实现 NBA。具名字段与来源映射服务于阅读和调试，布局可随优化改变。

目标构建顺序：

```text
GRH simplify（保留 declaredSymbol）
  -> lower GrhSIM IR（携带声明来源）
  -> 全图 reg-to-mem / comb-pack 等优化
  -> 全图 simplify
  -> 第一轮分解：P_event / P_general / P_output
  -> 各计算分区独立 simplify
  -> 第二轮分解：P_general supernode + 活动度调度
  -> 最终存储布局 / 静态表 / 执行计划
  -> 多 TU C++ emit / 并行编译 / 链接
```

两轮分解的含义分别是计算分区和 General 内部 supernode 划分。`P_input`、`P_mem`、`P_publish` 仍是执行阶段，以下六阶段 eval 顺序继续适用。大块连续状态的写入独立进入 `P_mem`，其参数在原地更新前完成计算与采样，保持同轮计算读取旧状态的 NBA 效果。

## 模型总览

> **架构调整（2026-10-03）**：保留六阶段框架，做两处激活语义调整——
> ① 全面移除 `eventActiveFlag` 机制：超节点按 sink / 非 sink 分两类激活——
> **非 sink 超节点**（非 sink，含带事件的非 sink op，如事件触发的 DPI/系统调用
> 返回值）以 `dataActiveFlag` 点火（数据通路置位 + P_event 检出边沿时按静态映射
> 置位少量此类超节点）；**sink 超节点**（sink 类型）带事件的以 `eventActStore`
> 组合门控点火、无事件的 sink 走逃逸机制（每个 round 无条件激活），且 sink
> 超节点内部不再重复事件判断（聚类保证同签名，只查 en、地址等逻辑）；
> ② `P_general` 划分超节点时，sink op（reg/latch/mem 写、无返回值的事件触发
> 调用等）**按事件签名聚类**形成 sink 超节点，**不与非 sink 超节点合并**，
> 非 sink 超节点也不向 sink 超节点传递 dataActiveFlag 激活；`P_mem` 的 mem 写
> 作为从 sink 中按存储类属剥离的大状态写，共享同一套事件签名聚类与两级点火
> 规则（eventActStore 组合门控 / 每轮逃逸）。
> 调整动机与旧双重门失效的原理分析见
> `pdocs/NO00029-grhsim-ir-icg-activation-deadlock-20261003.md`。

将整个仿真模型更加精细的拆分成6个阶段 P：

- P_input：检测输入变动
- P_event：以 S 为起点，计算所有事件信号的逻辑锥；检出边沿即写 eventActStore（当轮脉冲），sink 超节点直接经 eventActStore 组合门控感知
- P_general：组合 op，优化后状态的 read op，归入 regLatchStore 的状态 write op，DPI/系统调用 op；分区内 simplify 后再划分多个超节点（非 sink op 合并成非 sink 超节点——含带事件的非 sink op；sink op 按事件签名聚类成sink 超节点，两类不互并）
- P_mem：归入 memStore 的大块连续状态 write op
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

以下布局针对优化后的状态表示；源 RTL 的 reg/mem/latch 声明用于追溯来源，最终 store 按规模、连续性和更新代价归类。小数组或打包字可留在 regLatchStore；从标量寄存器恢复的大块连续数组可进入 memStore。

- 零碎状态排布在 RegLatchStore 结构体中；仿真类持有 regLatchStore 和 regLatchStoreNext 两个实例，后者作为前者实现 NBA 写入的影子状态；允许折叠、合并及打包，并保留来源映射；
- 大块连续状态排布在 MemStore 结构体中，允许数组及恢复出的高维数组；仿真类持有 memStore 一个实例，独立阶段更新，避免将整块存储纳入 publish 拷贝；
- I 和 所有跨越超节点的边界信号排布在 BoundaryValueStore 结构体中，仿真类持有 boundaryValueStore 一个实例；

- EventStore 结构体按与 EventActStore 相同的 (event, edge) 去重聚类枚举排布边沿检测历史值，每个 edgeDet 一个 prev 槽位（一个 event 信号可挂多个 edgeDet，各自的 prev 互不干扰）；仿真类持有 prevEventStore 一个实例，用于对比新旧检测事件边沿；event 信号的当前值只是 P_event 阶段的临时量，edgeDet 用完即弃，不出阶段、不持久化；
- 所有 (event, edge) 去重聚类后排布在 EventActStore 结构体中，每个bit表示一个事件边沿是否发生；仿真类持有 eventActStore 实例；eventActStore 每轮 P_event 覆盖重算、不粘滞：某 bit 仅在对应边沿被检出的当轮为 1；
- dataActiveFlag，dataActiveFlagNext：uint8 数组，长度等于 P_general 超节点数量，每个bit表示一个非 sink 超节点是否被数据激活；置位来源：数据通路（输入变动、前驱非 sink 超节点发布、P_publish 并入、状态写变化检测置位）与 P_event 静态映射（检出边沿时置位少量含事件非 sink op 的非 sink 超节点）；旗标在所属超节点点火时清除，sweep 按拓扑序保证挂旗即消费，因此 P_publish 开始时 dataActiveFlag 必然全 0（见 P_publish 不变式）；仅非 sink 超节点消耗本数组，sink 超节点不消耗——它们以 eventActStore 组合门控或每轮逃逸激活点火；
- timeslotTriggerFlag：uint8 数组，长度等于 P_output 中带事件门控的 time-slot 系统任务数量，每一bit表示对应任务在本 eval 内是否已被触发；由 P_event 检出对应边沿时按静态映射置位，eval 级粘滞（round 间不重建、不随 eventActStore 覆盖而失效），P_output 消费后清除；无事件的 time-slot 任务不占位（走历史值判定）；

## 分阶段说明

### P_input

从仿真类边界装载输入到 boundaryValueStore 中，检测激活，更新 dataActiveFlag；

注意，输入的clk等纯事件信号**不经 P_input 更新** dataActiveFlag，而是在 P_event 中检测边缘、写入 eventActStore：sink 超节点经 eventActStore 组合门控直接感知边沿，无需 flag 中转；含事件非 sink op 的**少量非 sink 超节点**则由 P_event 按静态映射置位 dataActiveFlag（见 P_event 产物）；"纯事件信号"的判定标准是信号只用作 op 的 event 操作数；rst 这类信号在 GRH IR 图结构中同时出现在 en 信号合成路径里（如异步复位写值的 mux 选择端），属于数据使用者，其变化照常经 P_input 置位 dataActiveFlag，因此多次异步复位不会被门控吞掉；

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

P_event 的产物除 eventActStore 外有二：P_output 的 timeslotTriggerFlag 静态映射置位；以及按静态映射（edgeDet 聚类 → 含该事件非 sink op 的非 sink 超节点）置位的**少量非 sink 超节点 dataActiveFlag**——事件非 sink op 的边沿执行通道。sink 超节点对边沿的感知不经过任何 flag 数组——它们在本轮 P_general 中直接读取 eventActStore 组合门控点火，因此该映射只覆盖非 sink 超节点。

### P_general

第一轮分解后，仿真图主体剥离**事件逻辑锥**、**输出逻辑锥**、归入 memStore 的写入 op（只剥离 op 不剥离参数逻辑锥）；先对该计算分区独立 simplify，第二轮分解再划分超节点；

事件锥/输出锥的剥离方式是复制+剥离：锥体复制到 P_event/P_output 后，P_general 侧仅为事件或输出服务的 op 删除——所有关联事件的 op 已改从 eventActStore 读取事件判断，原用于计算事件信号的 op 在 general 侧不再需要；但如果某段逻辑同时在数据通路和事件通路上，数据通路那份必须保留（两侧各算各的，同一 round 内读同一 S 快照，结果一致）；

归入 regLatchStore 的状态 write op 作为带事件 op 按事件签名聚类成sink 超节点（划分规则见下文），不与非 sink 超节点合并；

P_general 中优化后的状态 read op 按最终存储归属从 regLatchStore 和 memStore 读取输入；

P_general 中归入 regLatchStore 的状态 write op 写入 regLatchStoreNext，等到 P_publish 阶段再集中提交，实现 non-blocking assign 效果；

P_general 中归入 regLatchStore 的状态 write op 写入时做变化检测：新值与 regLatchStore 中的当前可见值比较，真变化才对下一round的激活写入 dataActiveFlagNext（不变则无需唤醒读者）；检测放在写 op 侧是因为写 shadow 时天然能看到旧值；

归入 regLatchStore 的状态发生部分位写（bit-select）或多写者写入时，合并基准一律是 regLatchStoreNext（本轮已累计的写入）：写 op 读出 next 中的当前内容、合并本 op 的位段后写回；"每轮开始时 regLatchStoreNext == regLatchStore"这一不变式由 P_publish 的全量拷贝天然维持，无需额外同步；

P_general 中所有关联事件的 op 的事件判断都从 eventActStore 中读取，不自行重复计算；

P_general 的点火条件按超节点类型分两类（分类轴心即 sink / 非 sink 的结构属性，事件只是点火方式的来源）：

- **非 sink 超节点**（非 sink，可合并）：体内全部是有返回值的 op，包括带事件的非 sink op（事件触发的系统调用/DPI 调用且有返回值）。点火条件为 `dataActiveFlag[i]`，置位来源两类：
  1. 数据通路：输入变动、前驱非 sink 超节点发布、上一轮 P_publish 并入（含状态写变化检测置位），朴素想法是输入不更新则不需要求解；
  2. P_event：检出边沿时按静态映射（edgeDet 聚类 → 含该事件非 sink op 的非 sink 超节点）置位——覆盖面很小，仅含事件非 sink op 的超节点；这是事件非 sink op 在边沿当轮得以执行的通道（否则数据静默期其返回值/副作用丢失），体内逐 op 的 eventActStore guard 决定哪些 op 实际执行；
- **sink 超节点**（sink 类型，签名聚类，不与非 sink 超节点合并）：体内全部是无返回值的 sink op（reg/latch/mem 写、无返回值的事件触发调用等），绝大多数带事件。点火条件按签名分两小类：
  1. **带事件 sink**：`eventActStore` 组合门控——签名内任一 act 当轮置位即点火；不消耗 dataActiveFlag（数据变化而无边沿的点火只会让全部 guard 求假，零提交、纯浪费）；
  2. **无事件 sink**（如数据门控的 latch 写）：**逃逸机制——每个 round 无条件激活**。电平敏感语义要求逐轮求值其门控条件（如 `~clk` 窗口内 latch 必须透明）；写侧变化检测兜底，无变化不置 dataActiveFlagNext，收敛不受影响；

超节点点火后立刻清除自己的 dataActiveFlag（sink 超节点无此项）；sweep 按拓扑序保证挂旗即被消费，不存在"置位却点不了火"的残留（旧双重门的拦下残留已随 eventActiveFlag 移除而消失），因此 P_publish 开始时 dataActiveFlag 必然全 0、eval 结束时不存在激活丢失。

事件携带 op 的**逐 op 门控**分两界处理：非 sink 超节点内的事件 op 保留逐 op `eventActStore[act]` 判断（其点火不区分是否因事件而来，无边沿的点火不得让事件 op 执行）；**sink 超节点内部不再重复事件判断**——聚类已保证全节点同签名，节点级点火条件（eventActStore 组合门控，或逃逸常活）已覆盖事件维度，体内 op 只求值 en、地址、数据等逻辑条件。这就是移除 eventActiveFlag 之后 NBA 语义与"不丢写"的全部保障：

- guard-skipped write 不会发生：写提交的唯一时机是边沿当轮，与旧双重门一致；
- NBA 采样不变：边沿当轮所有读看到的都是 pre-publish 状态（读 S 直读 regLatchStore，读 boundary 读本轮已按拓扑序刷新的组合值）；同 eval 后续 round 中 eventActStore 覆盖重算后边沿不再可见，写不会重复提交；
- 组合输出不再被事件门控滞留：数据一变即发布，下游读到的是活值（旧双重门把组合输出也押在事件上，是 NO00029 死锁的根因）；
- 纯常量锥的边沿写（如 posedge clk 下 q<=0）：边沿本身就是点火来源——每个 posedge 当轮 eventActStore 置位，sink 超节点逐沿运行提交，不存在"点火来源枯竭"问题；

NBA 的跨拍采样案例：寄存器 A 的输出接寄存器 B 的输入，某个 posedge 上 A 更新，publish 将 B 的组合锥（非 sink 超节点）的 dataActiveFlag 置位；B 的组合部分本轮即重算并发布（下游立即看到活值），B 所在 sink 超节点的写因当轮 eventActStore 无边沿不提交；下一个 posedge 到来的 eval，eventActStore 当轮置位，sink 超节点直接点火、从当前 S 与已刷新的 boundary 重算并提交——B 在下一个沿采样 A 的新值，与 NBA 语义一致。

P_general 超节点之间的边界数据通过 boundaryValueStore 传递；

P_general 超节点计算时，对后续超节点的激活记录在 dataActiveFlag 里，但仅指向**非 sink 超节点**——非 sink 超节点不向 sink 超节点传递 dataActiveFlag 激活：sink 的点火不依赖它（带事件的靠 eventActStore 组合门控、无事件的每轮逃逸常活），其操作数新鲜度由拓扑序点火与 boundary 值的持久性保证；

超节点划分规则（2026-10-03 起替代原事件域约束）：

- op 按 sink / 非 sink 分两类归置：
  1. **非 sink op**（有返回值的 op，包括带事件的非 sink op——事件触发且有返回值的系统调用/DPI 调用同属此类）：归入**非 sink 超节点**——沿用现有 node→supernode 合并框架（单消费锥吸收、coarsen、DP 分段、规模上限），只在非 sink 超节点之间合并；
  2. **sink op**（无返回值的写类 op：reg/latch/mem 写、无返回值的事件触发调用等）：按**事件签名**聚类——事件签名 = 该 op 的 event_acts 集合（canonical event key，含边沿方向；空签名自成一类）——同签名的 sink op 聚成一个 **sink 超节点**；**sink 超节点不与非 sink 超节点合并**，组合生产者永远独立成节点，经 boundaryValueStore 向其供数；
- 旧版"事件域约束"（同超节点事件集合必须相等、下游影响不得跨域）由构造保证：聚类 key 即签名，天然同域；非 sink 超节点即便含事件 op，其逐 op guard 各自正确，无丢写问题；
- 各类型超节点的点火方式随此划分确定（详见上文点火条件）：非 sink 超节点 dataActiveFlag（数据源 + P_event 静态映射）、带事件的 sink 超节点 eventActStore 组合门控、无事件的 sink 超节点每个 round 逃逸激活；
- sink 超节点的 op 操作数全部经 boundary 或 S 直读取得；同一 round 内按拓扑序非 sink 超节点先于 sink 超节点点火，保证边沿当轮读到的是新鲜值；
- 以边界流量换取结构性安全：使能锥与 sink 写在构造上不可能同节点，NO00029 的激活自锁环无法形成；事件签名沿用 canonical event key（现有 cpu.st.form-event-domains 的 key 可直接复用）。

### P_mem

大块连续状态经优化归入 memStore 后，其写入在本阶段集中处理，包括由标量寄存器恢复出的数组写入。mem 写 op 本质上是**从 P_general 的 sink 中按存储类属进一步剥离的大状态写**：与 sink 超节点同一套事件签名聚类（canonical event key 复用）与两级点火规则——带事件的写簇以 eventActStore 组合门控（簇级一次判断即可；簇内 op 与 sink 超节点同界，不再重复事件判断，只查 en、地址、数据等逻辑），不带事件的写簇走逃逸（每轮执行、变化检测兜底）。写入规范化为四种 mem 写类 op（memWrite / memFill / memAssign / memWriteSeq），从 eventActStore 和 boundaryValueStore 获取已采样的写入参数，执行原地更新。所有 mem 写 op 做 cell 级变化检测：写入前与 memStore 当前内容比较，无变化则不写、不置 dataActiveFlagNext——无事件写 op 靠它保证收敛，也避免同值重复写唤醒读者。

mem 写 op 不进超节点的原因有二：

1. 避免 P_publish 阶段对 mem 做大规模双缓冲拷贝（memStore 单实例、原地更新）；
2. 保持"本轮读旧值"语义：原地写若发生在 P_general 中间，同轮靠后超节点里的 memRead 会读到新值，破坏与 reg 写一致的 NBA 语义；集中到 P_general 之后，同轮所有 memRead 看到的都是上一轮结束时的 mem 状态。

P_mem 内各写簇在其 eventActStore 门控当轮内按静态优先级依次原地写；多个被激活的写 op 同地址相撞时，优先级靠后的覆盖先写的。

P_mem 执行时更新 dataActiveFlagNext，激活规则按读者地址形态区分：

- 地址为静态常量的 memRead：精确判断，仅当本次写地址与该读地址相等（重叠）时才激活其所在超节点；
- 地址为动态的 memRead：不做判断，保守激活其所在超节点。

### P_publish

实现 NBA、防止循环激活的关键；

fixedPoint = dataActiveFlagNext 为全 0；

P_publish 将 dataActiveFlagNext 并入 dataActiveFlag。**关键不变式：P_publish 开始时 dataActiveFlag 必然全 0**——sweep 按拓扑序逐个消费旗标（非 sink 超节点见旗即点火并清零），不存在逆拓扑的 Active 直接置位：非 sink 发布者的 fanout 只指向非 sink 消费者且边全顺拓扑（C2 序号是组合 DAG 的拓扑序，mapping 校验强制 producer 先执行）；逆向（回边）信息流只来自 sink 超节点与 P_mem 的状态写，而这些一律经 dataActiveFlagNext 走跨 round 通道，从不直接写 Active。因此"并入"与"覆盖"在此处天然等价，取 OR 仅是实现便利；旧的"防覆盖丢残留"动机（双重门拦下的 eventGated 残留）已随 eventActiveFlag 移除而消失——跨 round、跨 eval 的激活传递全部由"状态写 → dataActiveFlagNext → 并入 → 下轮 sweep 消费"承担；

清空 dataActiveFlagNext；

P_publish 将优化后零碎状态的 regLatchStoreNext 无条件全量 memcpy 到 regLatchStore 中（不做 dirty 跳过，换取实现简单；该拷贝同时维持"每轮开始时 next == current"的不变式，供写 op 以 next 为合并基准）；大块连续状态已在 P_mem 更新，memStore 不参与此拷贝；

eventActStore 的当轮脉冲由下一轮 P_event 覆盖重建，无需在此清理；

返回 fixedPoint。

### P_output

将所有以 S 为起点，以输出为终点的**输出逻辑锥**提取出来，在该阶段集中计算，形成 eval 的输出；同样采用复制+剥离：输出锥所需 op 复制进 P_output，自包含从 S 计算，每个 eval 在到达不动点后计算一次；暂不做跳过机制，每个 eval 无条件全量计算（理论上输出锥很小，后续有需要再加激活门控）。

$monitor / $strobe 类 time-slot 语义的系统任务也挪到本阶段，收敛后执行一次，对齐 IEEE"time slot 末只报一次"的语义；其参数锥与输出锥同等处理，复制进 P_output 从 S 自包含计算：

- 无事件的（如连续监测的 $monitor）：靠保存的历史值做"较上一 time slot 是否变化"判定（沿用现状 demonitor 的历史机制），变化才报；
- 带事件门控的（如 always @(posedge clk) 块内的 $strobe）：触发条件在 round 内由 eventActStore 给出，但 eventActStore 每轮覆盖、到 eval 末已不可见，因此这类 op 的触发记录由 timeslotTriggerFlag 承载（见关键内存布局）——P_event 检出对应边沿时按静态映射置位，eval 级粘滞，P_output 消费后清除；
- always_comb 里的 $display 等仍留在 P_general：delta-cycle 内重复触发符合 IEEE 语义，无需特殊处理。

### 初始化

init 时将 dataActiveFlag 全量置位（全脏）：上电后首个 eval 让整个图全量求值一遍，之后靠正常的变化传播收敛；否则第一个事件边沿到来时，从未有过数据变化的锥（如常量锥）不会点火。同时 regLatchStoreNext 的初始内容与 regLatchStore 一致，维持"每轮开始时 next == current"的不变式。


