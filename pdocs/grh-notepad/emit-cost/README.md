# emit-cost 专题索引

主题：同图（exec-GRH）emit 单位成本归因与修复——AM 引擎 vs gsim 引擎在同一图上的单位求值成本差（~21x，8.66 ns/instr vs 0.42 ns/non-ref enode）；方法为因子瀑布归因（消融定价）+ 按序修复，difftest 逐位一致为硬约束。源自 supernode-align NO0017 D 层判定（调度无罪、emit 不良）。

管理规则见 [../RULES.md](../RULES.md)。

## 记录索引

| 编号 | 标题 | 日期 | 内容摘要 |
|---|---|---|---|
| [NO0001](NO0001_同图emit单位成本归因与修复_20260810.md) | 同图 emit 单位成本归因与修复（开题） | 2026-08-10 | 开题：~21x 单位成本瀑布分解框架；H1（-O0 巨文件，块 27357 每周期激活）升头号嫌疑；Phase A 卫生/仪器（局部化上限、-O1 对等、逐块计时、opmix）→ B 消融（fold 帽、分支式 when、簿记、布局、微基准）→ C 修复；阶段目标破 10x |
| [NO0002](NO0002_三层结构量化对齐_20260810.md) | 三层结构量化对齐（enode↔instr / node↔atom / supernode↔compute block） | 2026-08-10 | **已对齐**：L1 0.80x / L2 0.95x（fold 帽=2）/ L3 0.98x（max-atoms=9）三层同时达标；对齐模型 465.8s 与未对齐 464.6s 持平 → 分区形状对运行时证伪，16.8x 差距锁定为纯 emit 形态 |
| [NO0003](NO0003_flatten图单一对象对齐_20260810.md) | flatten 图单一对象对齐（gsim when 展开增强 + 导出/导入/指标同图） | 2026-08-10 | 立项：flattenNodes 保留 when 骨架且默认关 → gsim 分区/指标用树形图、AM 消费导出扁平图，三方对象不同一（cross 残差 1.5x 因子的来源）；方案=flattenNodes 增加 when→mux 展开（fallback 语义对齐 exporter：REG_DST hold=ref(reg.src)、其他零基链式），导出/导入/指标全部落到同一张 flatten 图 |
| [NO0004](NO0004_enode到instr映射矩阵对齐_20260810.md) | enode→instr 映射矩阵对齐（gsim flatten 图 → grhsim am） | 2026-08-10 | **已收口**：导入段闭合差 0（25 类计算 op 1:1）；gsim 侧根 enode 口径勘误后真值 5,021,459，计算膨胀 1.442x→**1.113x**（Insert 融合 -204k instr，slice_static -204,111 / concat -106,549）；矩阵逐格机制定位行号；修复 emitter 宽路径未清窗 + 枚举区间分派遗漏两 bug；difftest 73,580/49,996 逐位一致 |
| [NO0005](NO0005_enode逐类全量映射矩阵_20260811.md) | enode 逐类全量映射矩阵（含 REF/常量，导入过程口径） | 2026-08-11 | **已收口**：导出器仪器化实测（非推断）45 类 enode × 33 列全量矩阵；AM 34 列闭合残差全 0；同图复核 op 总量 5,423,255 三方一致；总量 14.79M enode→5.30M instr 三段分解（REF→操作数、常量→常量变量、真计算 1.270x 逐机制定位）；NO0004 全部遗留残差实测闭合；§6 增量发现（待立项）：向量寄存器 when 骨架翻译不良——功能式 mux 链应译 mask 写，宿主 2,280 个 REG_DST 实测确认，收益上界 ~76 万 compute ops，语义扩展清单就绪 |
| [NO0006](NO0006_node到atom构造性对齐_20260811.md) | node↔atom 构造性对齐（战略转向：gsim node 结构导出 → AM atom 直建） | 2026-08-11 | **已实施（P1–P3）**：exporter 全 op 戳 node_id（白名单仅 kConstant/kRegisterReadPort），AM 按 node 直建 atom（optimize/fold 该路径默认关闭）；L2 构造对齐达成（严格 compute 口径 0.9995x、dup=0、残差逐类列账）；边对账 recall 99.2%；L3 块数匹配 0.956x 后 cross 1.656x——残余差距首次干净隔离在分区算法层（mergeWhen 在 flatten 图上语义分裂为块数偏差首因）；§9/§10 勘误与订正已并入 |
