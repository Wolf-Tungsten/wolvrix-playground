# GrhSIM IR reg-to-mem pass 草案：恢复被标量化的表结构

日期：2026-09-07。状态：设计草案，供评审。本文定义 pass 的目标语义、支持范围、
实现阶段和验收门槛；现有原型与运行证据另见
[实施验证记录](reg-to-mem-validation-20260907.md)，不作为本文设计要求已经完成的声明。

## 1. 目标与位置

新增后端无关的 `grhsim.reg-to-mem` semantic pass，将一组被 SV lowering 拆开的标量状态
恢复为 `core.array` 状态，再把逐行展开的地址译码、优先级选择和广播更新恢复为索引访问。
目标包括 PHR、TAGE useful counters、FTQ 的 Vec-of-Bundle 字段表、RenameTable difftest
table，以及具有相同数据流结构的其他模块。不得按这些模块名实现特例。

`memWriteSeq` 是其中的优先级写优化，不是整个 pass 的范围。完整支持必须同时处理候选
发现、行映射、共享/重复读视图、逐行读写、初始化、复位、掩码和事件历史。

推荐流水线：

```text
GRH flatten / simplify / memory-init-check
  -> lower GRH to GrhSIM core（保持 bridge 的语义转换职责）
  -> grhsim.reg-to-mem
  -> CPU split-phase / event-domains / partition / layout / schedule / emit
```

拟采用 `grhsim.reg-to-mem` semantic pass，在 CPU split-phase 之前调用。基础范围为
two-state、连续行、常量初始化、同构动态写、有序整元素写、同值 fill 和共享索引读。
动态 bit 窗口、重复/重叠视图和同址写融合分阶段扩展；无法压缩的读视图可由固定行
`memRead` 重建，不能因此遗漏其状态用户。合法性与收益分析入口拟为
`grhsim.reg-to-mem-analyze --report <path>`，具体接口须与 pass registry 约定一致。

新路线不调用 legacy GRH `reg-to-mem`，也不依赖 `regToMem.intent.*` 属性。legacy 路线在迁移
期间保留现有入口；删除旧 pass 属于后续独立工作。恢复表是语义表示变换，CPU 的存储布局、
pending cell 和 reader activation 属于后端工作，不放进本 pass。

## 2. 证据与必须覆盖的结构

以下数字来自历史实验，只作为形态和规模依据，不代表当前 grhsim-ir 的实测结果。

| 案例 | 标量化形态及漏识别原因 | 本 pass 的支持目标 |
| --- | --- | --- |
| PHR | 532 个有效槽位、28 个动态写源；逐行优先级链；read 同时用于 packed 动态读和其他逻辑 | 写侧发现、完整读替换、`memWriteSeq`、可选同地址写融合 |
| TAGE usefulCtrs | 历史实例为 64 组 512 行；同一个 concat 有多个 slice 用户；复合 reset、无效尾部 mux | 共享读视图、单点写、整表 `memFill`、复合条件归一化 |
| FTQ Vec-of-Bundle | `entry_i_field` 形式拆成逐字段状态，字段宽度不同；共享索引写 | 逐字段建表，共享索引/守卫，不要求重建 struct 类型 |
| RenameTable | 动态写展开到各行，但 read 直接接逐行 difftest 输出，没有 concat/slice anchor | 独立写侧发现、固定地址读、不可写零行、多个优先级写源 |
| 重复/重叠窗口 | 同一状态出现在多个 concat、回绕视图或局部视图中 | 一份存储、多份显式地址映射，不生成标量镜像 |

证据：

- [PHR 标量化成本](../../grhsim_opt/NO0260_phr_multi_write_scalarization_gap_20260710.md)
- [PHR 优先级分析及后续修订](phr-priority-write-analysis-20260904.md)
- [TAGE shared packed-view](../../grhsim_opt/NO0271_tage_shared_packed_true_merge_20260711.md)
- [FTQ Vec-of-Bundle](../../grhsim_opt/NO0197_ftq_vec_of_bundle_sv_scalarization_rootcause_20260614.md)
- [RenameTable 写侧发现缺口](../../grhsim_opt/NO0288_rename_table_write_only_array_gap_20260711.md)
- [legacy intent 与 storage ownership](../../grhsim_opt/NO0203_reg_to_mem_intent_discovery_refactor_20260618.md)

PHR 旧分析第 4–5 节认为可以完全消除顺序需求，第 7 节已修订为支持 `memWriteSeq`。
本设计以当前 core 方言的有序单 op 语义为准。旧文中 28 → 15 的融合是可尝试的进一步优化，
不是恢复 PHR 的前提，也不能直接把源码中的环形指针不变量当作 IR 已证明事实。

当前 `ptmp/xs_ir_gate67.json` 的已有检查记录中，`phr_157` 的 next-value 实际有 41 层 mux，
update 是分支条件的 OR，部分条件还包含较高优先级地址命中的否定项。这里的 41 是输入
分支数量，28 是历史分析中的逻辑写源数量；两者不能直接等同。matcher 必须先解释每层
分支的有效条件、数据和覆盖关系，再证明冗余分支可消除，不能硬编码预期写源数。

## 3. 设计分层：恢复存储与压缩访问

一个 pass 内分为三层分析和一次提交，不通过隐藏全局状态向其他 pass 传递结果。

1. **发现表候选**：从读和写两侧收集结构证据，建立 `StateId -> row` 映射。
2. **规划合法重写**：首先证明所有状态引用可转为 array 访问，再尝试压缩读写网络。
3. **选择收益明确的候选**：估算消除的译码/选择操作、保留的逐行访问、初始化和活动度成本。
4. **应用与清理**：改写 `S/G/Init`，清除仅被替代路径使用的纯计算及私有历史，验证并失效 mapping。

“写口无法合成一个动态端口”不等于“状态无法恢复为表”。在合法且有收益时，普通
`state.read(q_i)` 可转为 `memRead(table, i)`，普通 `regWrite(q_i)` 可转为固定地址
`memWrite(table, i)`，保留其 data/mask/event/history。动态读或其他写族仍可独立优化。

目标设计替代 legacy 的“未 true merge 则只给 emitter 打 intent”的路径：新模型最终只有一个
真实 array state。若剩余引用无法完整表达、跨 op 写冲突无法证明合法，则整组保持标量。
存在可压缩 indexed read 时，也允许建立 array 并保留固定行写；这类候选报告为
`indexed-read`，不能计为写侧优化成功。

## 4. 候选发现与行映射

### 4.1 读侧入口

识别 `state.read[] -> assign/concat -> sliceArray/sliceDynamic`。支持同一 concat 的多个
用户及 read 的额外用户，不要求 single-user。递归展开嵌套 concat 时保留位偏移与端序；
只有不改变宽度/符号解释的 assign 才能透明穿透。

例如 `concat(q3,q2,q1,q0)` 的低位 lane 对应 row 0，不能按 operand 正序或符号名排序。
`sliceDynamic(packed, index * W)` 仅在乘法的位宽、截断和符号行为可证明等价时转为行索引。
不能把任意动态 bit slice 除以 W 当作等价 indexed read。

### 4.2 写侧入口

从 `regWrite` 的 update、next-value mux、mask 数据流中识别：

```text
guard_i = enable && (address == row_i)
q_i.next = mux(guard_i, data, q_i)
```

按去掉 row 常量后的地址、使能、数据投影、类型和事件结构签名聚类。允许没有任何动态读：
RenameTable 的逐行 output 是普通消费者，不能影响写侧候选发现。

常量相等项必须与跨行变化建立对应，不能把 reset 内部恰巧等于某个 row 的 equality 误认成
地址译码。先统计 guard 在候选行上的覆盖关系，再区分逐行命中、全组广播与其他条件。

### 4.3 同构字段、窗口和缺行

- Vec-of-Bundle 按同类型字段形成独立 `array<field_type,N>`，不同字段可共享 address/enable
  的 SSA value；不因共享索引而强行把不同位宽或不同更新条件的字段拼成一个元素。
- 多维表先选一个可证明的行维度，其余维度作为 bank/field；跨维 flatten 需显式证明 stride、
  行域和位宽，不依赖名字中的数字。
- 同一个 StateId 在重复 concat 中出现多次，只分配一行；读视图另保存 lane 到 row 的映射。
  周期重复可在有证明时用模运算；边缘重复不能误用同一个公式。
- 重叠候选先统一共享状态的行映射。映射兼容且收益明确才合并存储族；否则稳定选择不重叠
  子集。不得让两个 array 拥有同一个原状态。
- 首阶段覆盖连续行及连续偏移域 `[base,base+N)`。缺少 row 0 时须保留地址域检查，不能让
  减去 base 的无符号下溢访问真实行；硬连零 read 保留为常量。
- 任意稀疏行可规划显式地址映射，但默认推迟；不能悄悄补出可写的新状态或按最大地址分配
  巨大数组。名字/source origin 只用于候选提示和报告，不作为合法性证据。

## 5. 写入正规化与目标操作

以下 `table` 均为 `core.array<element_type,N>`。每个写 op 的 object refs 首项为 table，
其后依次为 event 的历史状态；`event_edges` 与末尾 event operands 一一对应。

| 目标 | operands | 使用条件 |
| --- | --- | --- |
| `memWrite` | `enable, address, data, mask, events...` | 一个索引写，mask 与元素同宽 |
| `memWriteSeq` | `enable_0,address_0,data_0,...,enable_K-1,address_K-1,data_K-1,events...` | 同事件、整元素写，有证明的覆盖顺序 |
| `memFill` | `enable, data, events...` | 全表同值整元素更新，data 为元素类型 |
| 固定地址 `memWrite` | 同上，address 为 row 常量 | 无法压缩但可合法保留的逐行更新 |

### 5.1 优先级链恢复

从每行的实际状态转移恢复有效写分支，不能只提取 mux 而丢失 `regWrite.updateCond`。
例如 update 为 U、next 为 `mux(c,d,q_i)` 时，有效写使能为 `U && c`。若 U 在各行的形式
不同，须证明其与提取的地址命中族关系，才能消除 U；无法证明时不压缩该族。

特别处理常见的 `U_i = hit0_i || hit1_i`：若分支 `hitk_i` 蕴含 `U_i`，可以在该分支中
消除 U_i，再提取共享使能 e_k。若把各行不同的 U_i 原样加入写族签名，同构行会被误判为
不同写族；若任意删除 U_i 则可能扩大更新域。分析记录须区分“已证明可消除”和“必须保留”
两种情况。没有 hold fallback 时，还须保留 `U_i && !c0 && !c1 ...` 对应的默认数据更新，
不能仅因某个 OR 项在语法上匹配了 mux 条件就丢弃默认路径。

```text
q_i.next = hit1_i ? d1 : hit0_i ? d0 : q_i
hitk_i = ek && (ak == i)

=> memWriteSeq(table, [(e0,a0,d0), (e1,a1,d1)], events)
```

三元组按低到高优先级排列，同址时后者覆盖；异址时两者均写。不能按 IR op 表顺序推断覆盖
关系，也不能把“if e1 ... else if e0 ...”的全局互斥控制改成允许异址并写。
应区分全局使能排斥和仅由同一行命中引起的排斥。

标量化输入通常为每个 row 复制一套相同写源的译码分支。恢复动态地址时，每个逻辑写源只
生成一个三元组，并用跨 row 的数据/守卫同构性作为前置条件；不能把所有 row 的分支都塞入
sequence，否则它们会写同一动态地址并由最后一个 row 覆盖前面的数据。

跨行分支排序必须有共同的覆盖关系；若各行优先级不一致，只能分成有证明的子组或回退。
已物化的 `!(higher_enable && higher_addr == row)` 可在顺序证明后消除；独立的功能 guard
必须保留。不以 K² 地址冲突网络作为有序整元素多写口的默认表达。

所有 address/data/enable 都在 compute 阶段从旧状态和本轮输入求值；sequence 中后面的 data
不会读取前面的 staged 写入。回读旧表的 read-modify-write 也遵守这一规则。

### 5.2 PHR 支持路径

PHR 的最低验收形态是一个 532 行有效存储域，配套原有读视图及按逻辑写源组织的有序写。
输出三元组数量 K 由实际输入的有效分支及已证明的融合决定，不以历史 28 个写源作为硬上限；
验收要求从逐行复制的 O(N×K) 写译码恢复到 O(K) 索引写，并逐项说明剩余分支。
地址空间比有效行数大时显式限制写域，不从 gsim 的 1024 项物理分配推导语义表深度。

进一步可融合相同地址的默认写和修正写：

```text
(valid, a, low), (valid && taken, a, corrected)
  => (valid, a, mux(taken, corrected, low))
```

两次写之间若有可能别名的第三次写，不能直接跨过它做融合；先证明可交换，或仅融合相邻
写源。对 PHR 的 13 组同址写，经该证明后才可达到 15 个写源。
不同偏移写是否互斥必须从实际指针算术、回绕条件和可达地址域证明；未证明时继续保留
sequence。这样基础恢复不依赖专用的环形指针证明器。

### 5.3 复位、广播和掩码

TAGE 式 `reset || resetUseful` 统一为 group fill 候选，去除同值 mux 等局部冗余；必须证明
所有行的 fill data、条件和 event 等价。reset 优先于普通写时，普通写使能包含 `!reset`，
保证 fill 与其他 op 在同一次 G 中不写同一 bit。

不同初值不妨碍建表。运行期逐行不同 reset data 暂用固定地址写；当前 CPU emitter 不支持
`memAssign`，不得为了压缩 reset 产生端到端无法执行的 op。部分行清零也不能扩大成全表 fill。

`memWriteSeq` 当前没有 mask，第一阶段仅承载全掩码写；一位元素的 mask 可并入 enable。
多位 masked 写可合并成 `memWrite`，前提是跨行 mask 兼容且与其他 op 的写 bit 互斥。
有重叠优先级的 masked 多口不能简单改成以旧值计算 data 的整元素 sequence，否则会丢失
较低优先级写在其他 bit 上的更新。此类候选保留原有优先级选择，或整组回退；扩展 masked
sequence 必须独立定义 schema、verifier 和各后端语义，不作为本版隐式扩展。

## 6. 读访问与共享用户

恢复存储后，每个原 scalar read 都可映射到一个固定行 `memRead`，其原 value 用户（包括
output、DPI 实参、反馈计算和派生时钟）保持连接。不能因存在这些用户就漏掉整个表。
直接以 opaque state 引用状态的未知方言 op 则须有明确重写规则，否则拒绝该组。

动态读优化独立进行：

- 一一对应的 packed lane 选择转为动态 `memRead`；固定 slice 转为固定行读或读后位切片。
- 多个 slice 共享同一 array；不能为每个 anchor 复制状态。
- 未被优化的整表 concat/宽逻辑保留，由固定行读重建；只删除已无用户的 concat 和标量 read。
- repeated/edge-padded view 按第 4 节的 lane 映射访问，不能仅凭物理行数取模。
- mux-tree/one-hot read 可作为第二批 matcher，需保留无命中、多命中、默认值和优先级行为。

当前 `memRead` 要求地址有效，CPU emitter 直接按地址访问。不能先无条件越界读，再在外层
mux 丢弃结果。对 two-state、原越界结果为零的 lane read，可生成：

```text
in_range = index < N
safe_index = mux(in_range, index, 0)
selected = memRead(table, safe_index)
result = mux(in_range, selected, zero)
```

`zero` 与原 result 等宽，N 必须大于零。若原语义是部分越界 bit slice、符号扩展、未知值
传播或其他默认值，应完整重建对应语义；首阶段无法证明时保留原读视图。
四态状态首阶段不转换，不能把 X/Z 地址或条件直接当作 two-state 行为。

`enable_read_rewrite` 仅控制动态读网络压缩。只要决定移除标量状态，所有固定行读的引用
替换就是必需步骤，不能受该开关控制；否则关闭读优化会留下指向已删除状态的引用。

## 7. 合法性与状态转移证明

对每个候选建立局部证明记录，不只做形状匹配。至少验证以下项目：

| 项目 | 必须保持的不变量 |
| --- | --- |
| 类型与所有权 | 每个 scalar 对应唯一 array 行；位宽、signedness、domain 不变 |
| 初态 | 每个原 q_i 的初值等于 table[row_i]；其他状态初值和初始化效果保持 |
| 读闭包 | 所有原状态引用均被替换或明确保留，任意用户读到同一个旧状态 |
| 次态 | 对任意合法输入和事件历史，每行 masked next-state 与原式一致 |
| 写冲突 | 不同 op 写同表时，同轮写 bit 互斥；覆盖关系只存在于单个 sequence 内 |
| 事件 | enable 为假时仍采样 history；边沿列表、事件值及历史初态保持等价 |
| 地址 | 有效行域、截断、负值、回绕、padding、越界行为保持 |
| 副作用 | 不删除或重复执行 system/DPI 等有副作用节点 |

同 CPU event-domain key 不足以证明可以合并写口：它不包含 history 初值。只有各位置的
event/edge 相同、history 初值相同且 history 的更新轨迹等价，才能让多个原写口共享一套
history。首阶段要求被消除的 history 私有、仅由对应事件口维护；有外部读或额外 writer
时保留原事件口，无法表达则拒绝压缩。不能把某个 history 常量初值改成统一零。

不要求整表只有一个时钟：可以保留多个事件域的独立写口，但必须证明跨 op 不冲突。
不同事件集合不能直接塞进一个 `memWriteSeq`；异步 reset 也不能被降为仅时钟采样的 reset。
未知关系采取保守回退，不能仅凭“实际程序不会同时触发”接受。

初始化首阶段覆盖逐行常量，按 row 构造 fill 区间并覆盖全表；连续同值区间可压缩。
随机初始化会改变 RNG 调用顺序、种子作用域和其他状态初值，不能把多个 scalar random
机械改成 array random fill。首阶段遇到随机初始化拒绝该候选；后续需显式保持原调用次序。

证明先采用有界结构归一化（常量、同值 mux、布尔项、地址 equality、宽度明确的投影），
不将通用 SAT/SMT 作为运行依赖。超过证明预算报告原因并回退。

## 8. 实现结构、复杂度与模型修改

拟议文件：`wolvrix/include/grhsim/pass/reg_to_mem.hpp`、
`wolvrix/lib/grhsim/pass/reg_to_mem.cpp`，通过现有 GrhSIM pass registry 注册。
实现遵循当前 C++ `PassKind::SemanticTransform`、`PassResult` 和 `PassManager`，
不照搬早期文档中的返回新模型 Python protocol。

临时结构建议包括：

```text
TableCandidate: elementType, rows(StateId -> row), readViews, writers
ReadView: source value, lane-to-row mapping, consumers, bounds behavior
WriteFamily: enable, address, data, mask, events, priority relations
RewritePlan: replacement states/ops/init, retained accesses, dead candidates, proof reasons
```

一次建立 value def/use、state refs、writer、InitSpec 索引；按结构签名聚类，复用共享 DAG 的
归一化结果。目标成本与输入 DAG 大小及已存在的 N×K 标量化结构近似线性，不再枚举全模型
state 两两组合或 K! 写口排序。对 RenameTable 数百写源采用 DAG 遍历和优先级约束排序，
避免递归展开共享表达式导致指数时间。

模型使用稠密 ID 表和 flat pools，重写须通过受控 rewrite/compact 机制完成，不能直接
擦除旧 state/op：稳定遍历保留实体，生成旧到新 ID 映射，重建
operand/result/objectRef/init 范围，并保留接口、extern declarations 和 origin。
先完成全组 preflight，再批量应用候选；禁止通过 const_cast 或留下无 producer value 绕过模型约束。

无命中返回 `changed=false`，不改变 revision/mapping。有语义变化由 manager 更新 semantic
revision 并使所有旧 backend mappings 失效；压缩 ID 的提交与 mapping 清除必须协调，防止
中间态被旧 mapping 使用。异常路径遵守现有 poison 规则；正常 matcher 拒绝不是失败 mutation。
重复运行应不再改写已恢复数组，输出具有确定性，store/load/store 保持稳定。

清理仅限已证明无用的纯计算节点及被消除写口的私有历史。不能把“无输出用户”当作删除
系统调用的依据，也不能删除仍参与组合计算、派生 event 或可见输出的读路径。

## 9. 收益选择、诊断与后端配合

默认候选阈值暂定 `min_element_count=4`，但不能只有行数阈值：小表多写口可能收益很大，
大表每行独立变化则可能没有收益。记录 N、元素宽度、动态读数、写源 K、消除的比较/mux、
保留固定行读写数、fill 次数、预计新增 guard/地址映射成本。

选择时比较同一候选的三种计划：保持标量、恢复存储并保留固定访问、恢复存储并压缩索引
访问。只计算重写后确实失去全部用户的旧节点，共享 concat/译码仍有用户时不计作消除；
新增 bounds guard、地址映射及重复读按共享后的 DAG 计数。纯粹打包状态、既不减少访问
也不消除计算的候选默认跳过。进一步用后端测量校准 memory read/write、宽数据搬运、
fill 与 reader activation 的权重；无法估计活动度的候选报告不确定项，先通过显式开关评估。
analysis-only 同时输出这些替代计划及选择依据，使阈值调整可复核。

恢复存储的收益不能由“state 数下降”单独证明。整表成为一个 fanout 源可能扩大活动度；
全宽 concat 用户可能仍要求读取全部行。对以固定行读为主的 RenameTable，需独立测量激活
成本；不要把整个表恢复的收益寄托在默认开启昂贵的整表发布上。

历史 [memory staging audit](../../grhsim_opt/NO0663_grhsim_ir_cpu_memory_structure_audit_20260907.md)
记录过整数组 staging 的成本；当前源码已存在 `cpu_stage_cell` 路径，实施时以实际版本验证，
不能把该历史缺陷当作当前事实。测量 cell staging/publish、重复地址写、fill 和 reader fanout。
若需后端修复，单独实现和验收，保持旧状态读取与 NBA 提交语义；wide helper 继续使用
legacy 的 caller-provided buffer 路线，避免热路径的大数组返回值及复制。

拟议参数：`min_element_count`、`enable_read_rewrite`、`enable_write_merge`、
`enable_same_address_fusion`、`analysis_only`、`report`。参数均须有 factory 校验；
analysis-only 应以只读 analysis 模式运行，不为输出报告改变 semantic revision。

analysis-only 也要运行行映射、写优先级、history 和收益的 preflight，输出 `eligible` 或
具体拒绝原因；只有结构发现而未做合法性规划的条目标为 `discovered`。`merged` 专指已
实际提交的变换。尚未实现的选项不得静默接受为有效优化，须在接口或诊断中明确标记。

报告按组输出候选来源、行域、选中/拒绝原因、端口数前后对比、剩余逐行访问、init/event
处理及编译期耗时。汇总拒绝原因至少包括 ownership、row-map、type、update-condition、
write-priority、mask、history、init、out-of-range、unknown-state-user、cost。
常规日志给计数，详细报告按需生成到 `ptmp/`，避免全模型逐行刷日志。

## 10. 分阶段实施与验收

| 阶段 | 内容 | 完成标准 |
| --- | --- | --- |
| A：基础与发现 | rewrite/compact、读写索引、双侧候选、分析报告 | 四类真实结构均可发现；改名不影响结果；analysis-only 不改变模型 |
| B：通用存储恢复 | 常量 init、固定行读写、共享 concat、单索引写、fill | 单状态所有权，所有原用户保留；未压缩访问明确计数 |
| C：优先级写 | update+next 联合解析、跨行写族、history 校验、`memWriteSeq` | PHR 和 RenameTable 消除逐行优先级译码；异址并写/同址覆盖正确 |
| D：覆盖扩展 | packed lane 投影、偏移行域、重复/重叠读视图、同址写融合 | TAGE shared view/复合 reset、FTQ 多字段、PHR 融合有独立回归 |
| E：接入与性能 | XS/HDLBits IR flow 在 CPU mapping 前显式调用 | 端到端功能和结构门槛通过，性能数据支持默认开启 |

A–E 是这次 pass 的完整交付计划；不能把只完成 A 的无操作注册入口视为完成。
暂不覆盖任意稀疏地址、四态变换、随机初始化重排、masked sequence schema 扩展和任意
跨行算法识别（例如所有行都更新的 shift register）。这些情况必须可诊断地保持原语义。

验证分三层：

1. **语义与基础设施测试**：用原 scalar 与转换模型比较 init 及逐次 G 后可见结果；小位宽
   穷举地址/使能/冲突，补充随机事件序列。覆盖多写同址/异址、全局 else-if、反馈读、不同
   history 初值、多时钟/异步 reset、masked overlap、无效地址、非零 base、row0 常量、
   shared/repeated views、额外 output/DPI read、非均匀 init、无命中、拒绝不变、幂等和 JSON。
2. **生成代码回归**：缩小 PHR/TAGE/FTQ/RenameTable 的 SV fixture，与 Verilator 逐步对照；
   检查 `memWriteSeq` 不被 schedule 拆散，读旧状态、同址覆盖和 fill 交互正确。加入 ASan/UBSan
   越界测试。生成宽数据 helper 应检查和 legacy 一致的 buffer/aliasing 策略。
3. **真实模型门槛**：固定同一个未做 legacy reg-to-mem 的 flat GRH checkpoint，比较 pass
   关闭/开启的 IR 计数、生成 C++、编译时间/峰值 RSS、10k/50k 功能结果及固定 CPU 多次计时。
   先证明目标结构减少，再报告 runtime；不能引用历史 gsim profile 代替当前性能测量。

结构验收至少要求：PHR 的逐行写译码变为 O(K) 写源（全表读若保留须单列）；RenameTable
不依赖 read anchor；TAGE 的共享 concat 不阻止 indexed write+fill；FTQ 同构字段形成独立表。
同时统计 fixed reads、array fanout 和 commit 实际成本，避免“操作数减少但总成本增加”。

全部 build/test/install 经项目 Makefile target 执行；缺失工作流先补 target。命令日志、
性能报告和临时工作文件放 `ptmp/`，测试 fixture 放 `wolvrix/tests/grhsim/data/`，
常规测试产物遵循项目 `wolvrix/build/artifacts` 约定。

执行结果集中记录在 [实施验证记录](reg-to-mem-validation-20260907.md)，注明输入 checkpoint、
源码版本、开关配置及日志。不同版本的结构计数和运行结果不能混用；50k cycle 上限通过
也不等同于完整 CoreMark benchmark 完成。本文的阶段表只定义完成标准。

## 11. 后续需要核实的具体问题

- 从当前 flat GRH lower 后的实际 checkpoint 提取四类目标结构，确认现有 simplify/packing
  后的 update、mux、mask 与旧报告形态的差异，确定 matcher 顺序。
- 核实 PHR 相同地址写源之间的别名关系及环形指针域；28 → 15 仅在证明后启用。
- 将现有 compact/rewrite 原型收敛为最小公共 API，使 semantic revision、origin 与失败回滚不
  依赖 pass 私有访问模型内部字段。
- 在当前 CPU emitter 版本测量表状态的 cell staging 和 reader activation，确定收益阈值。
- 落实现有 core verifier 对 memory operands、元素类型、history arity 的检查；全局写互斥
  证明由本 pass 的 plan 负责，不能声称结构 verifier 已自动证明状态转移等价。

后续实施先用实际 IR 校准 A 的双侧候选，再按 B–D 完成真实语义重写；只有通过 E 的端到端
门槛后，才把更多候选作为默认路线的收益依据。
