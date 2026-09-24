# TNO0332 RepCut backend cost models

日期：2026-09-22。状态：实验性模型开发与机制验证；默认权重不变。

## 1. 背景与讨论结论

承接 [TNO0331](./TNO0331_xiangshan_residual_giant_separator_audit_20260920.md) 的四方案分区权重/eval/update 对照。
本专题集中记录设计、实现、验证和后续数据，不为每个小步骤新开文档。

- 目标是改善每步 eval 的相对计算成本估计，不是精确预测 C++ 字节数、机器指令数、周期或最终 walltime。
- 分区前可以获得操作类型、输入/输出位宽、扇出、ASC/piece 引用关系；候选分区确定后可以按实际闭包计算复制负载。
  C++ 规模要在代码生成后确认，机器码规模要在编译后确认。不能把事后统计作为求解器事前已知的信息。
- 代码规模与 eval 的相关性只能提供诊断线索。初始化代码可能只运行一次，短小 helper 可能遍历很长数组，
  条件活动率、缓存、编译优化及同步等待也会改变执行成本。此前对“较准确预测”的表述没有跨设计验证依据。
- baseline/single00/pair00/combined 来自同一香山设计，128 个分区不是 128 个独立设计样本。
  不随机拆分这些分区作为训练/验证集，不将同设计相关系数当作泛化能力。
- 区分对 RTL 设计过拟合与对 guest 程序/运行区间过拟合。通用默认权重应与设计/程序专用的 profile-guided 调优分开。

## 2. 可扩展架构与边界

保留两个正交选项：

| 选项 | 职责 | 当前值 |
| --- | --- | --- |
| `weight-mode` | ASC/piece 的共享分摊、复制惩罚、闭包 refinement | `baseline` / `closure-aware` |
| `cost-model` | 某个后端下单个 GRH 操作的相对工作量 | `legacy` / 实验性 `verilator-v1` |

成本流向：操作计价 -> piece 成本 -> ASC/共享闭包汇总 -> 求解器顶点权重与 exact closure refinement。
`legacy` 保留既有计算规则与默认行为。`verilator-v1` 显式启用；不自动根据 emitter 切换。
gsim/grhsim 暂未实现，也不作为 Verilator 的别名。未来增加独立、有版本的模型，复用相同的计价接口和图汇总流程，
不在求解器或各调用点散布后端分支；首版不需要动态插件系统。

通信 proxy 算法和 ASC/storage 共置规则不变。注意 closure-aware 的实际边权原本就等于“共享 piece 计算成本 + 通信 proxy”：
切换计算模型会自然改变其中的复制成本项，并非全部边权数值不变。不同模型的绝对 weight 不能直接比较；
只能在同一模型内比较划分负载，跨模型性能仍看相同构建/工作负载下的 walltime。

## 3. 首轮机制依据

本地 `/nfs/home/tanghaojin/verilator` 为 Verilator 5.048；直接核对当前工具链源码，不以香山耗时拟合系数。

| 机制 | 代码依据 | 对模型的约束 |
| --- | --- | --- |
| <=64 bit 原生整数，>64 bit 为 32-bit WData limbs | `include/verilated.h:119`、`verilatedos.h:465` | 64/65 边界独立处理，wide 按 ceil(W/32) |
| wide add/sub 遍历 words 并传递进位 | `verilated_funcs.h:1033` | 按运算结果宽度增长 |
| wide reduction 遍历输入，输出只有 1 bit | `verilated_funcs.h:656,668,735` | 按输入宽度；不能按结果的 1 bit 计费 |
| indexed narrow slice 只读少数相邻 words | `verilated_funcs.h:2182,2195,2217` | 不能按整个输入宽度线性惩罚窄切片 |
| wide shift 遍历整个输出 | `verilated_funcs.h:1929,1998` | 与 narrow slice 分开计价 |
| memory write 为 enable/addr/data/mask/events | `wolvrix/docs/grh/grh-ir.md` | data 在 operand 2；register write data 在 operand 1 |
| 部分/动态 memory mask 可展开逐 bit 写 | `wolvrix/lib/emit/system_verilog.cpp` | 与全一 mask 的整行写区分；动态活动率仍未知 |

旧规则的 reduction 按 result width 计价，memory write 取 operand 1 当作 data；只在新模型修正，legacy 留作对照。
wide multiply 的本地 helper 存在多层进位循环，divide/modulo 有有效位数和数据相关分支，
不能未经验证就统一设成线性/平方函数；首版对这些以及 memory read、DPI/debug 等未覆盖操作显式回退 legacy，报告回退数量。
所有系数只是低自由度的机制启发式，不是已标定周期或跨后端通用常数。

## 4. 验证安排

1. 独立 C++ 单测：64/65 边界、归约输入宽度、窄切片不随输入宽度膨胀、写口操作数/mask、回退、严格选项校验。
2. 同一小图运行默认与显式 legacy，核对 HGR 和分区保持一致；新模型贯穿构图、闭包/refinement 和诊断。
3. 独立 SV 算子矩阵经实际 Verilator 生成，先核对表示/helper 机制；源码字节数不冒充 runtime 数据。
4. 后续才扩展组合结构、memory/mask、多个独立设计和程序区间，按整个设计留出验证。
5. 晋级标准包含长尾低估、最慢分区识别、通信/update 回退及最终 walltime，不能仅靠平均相关性；验证前不改默认模型。

性能实验默认使用用户预留的 node030 CPU96-127，保持 N=K 和当前 all-spin 默认。
整线程 PMU 包含自旋/update，不能除以 step 数冒充分区 eval 指令数。需要计数时须隔离 callback 边界并验证扰动。
本专题目前不引用上一轮非同环境的临时 PMU 尝试作为性能证据。

## 5. 实现与通过的验证（2026-09-22）

第一阶段已完成可扩展接口、可选机制模型和小规模验证，未改变默认分区/运行时配置，未提交 Git，未修改香山 RTL。
功能说明及公式见 [RepCut 功能文档](../../wolvrix/docs/transform/repcut.md#后端计算成本模型)。

### 5.1 代码与入口

- `wolvrix/include/transform/repcut_cost_model.hpp`、`lib/transform/repcut_cost_model.cpp`：
  `estimateRepcutOperationCost(graph, op, model)` 返回相对权重与是否回退 legacy；模型枚举/名称集中定义。
- `repcut.cpp`：构图、共享 piece 成本、闭包 refinement、重建前节点统计使用同一个选定模型。
  stats 新增 `cost_model` 和逐分区 `cost_model_legacy_fallback_op_count`。
  后者是原始节点集的计数，不是运行次数；分区间有复制时同一操作可在多个分区计数。
- C++ pass 接受 `-cost-model=verilator-v1` 或空格写法；Python 接受 `cost_model="verilator-v1"`。
  Make 三个既有 RepCut 入口透传 `XS_REPCUT_COST_MODEL`，默认 `legacy`。
  未定义后端名称严格拒绝，避免把 gsim/grhsim 误当作已支持的模型。
- 新规则不叠加旧扇出乘数；未覆盖操作回退时仍使用完整旧公式。
  register/latch 的部分或动态 mask 暂回退 legacy，等待后端合并行为的探针验证。
  mask 解析支持 sized literal 和 `'0`；`'1`、未知位或不可解析形式暂保守按动态规则处理。
- 新模型使用宽整数累计 piece 成本，超过 uint32 缓存范围时报错；legacy 保留原有累计语义。

启用示例（实际对照应使用独立输出目录，避免覆盖已有 baseline）：

```bash
make build_xs_repcut_verilator XS_REPCUT_WEIGHT_MODE=closure-aware XS_REPCUT_COST_MODEL=verilator-v1
```

本轮构建的 Python 包在 `wolvrix/build/commit-check/python`；未覆盖工作区 `.venv` 中已有安装。
直接调用脚本时可令 `PYTHONPATH` 指向此目录，或按项目流程重新安装；旧安装不认识新参数。

### 5.2 C++ / Python 回归

构建和测试均使用 node030、`taskset -c 96-127`。C++ 为 GCC 13.3 / RelWithDebInfo，实际启用 vendored Mt-KaHyPar。
构建目录：`wolvrix/build/commit-check`。构建时 PATH 包含 `/nfs/home/tanghaojin/LLVM-21.1.5-Linux-X64/bin`。

通过结果：

| 验证 | 结果与范围 |
| --- | --- |
| CTest 相关 6 项 | pass-manager、repcut、cost-model、partition-set、boundary-bundle、partition-count 全过 |
| Python 选项测试 | 当前新构建 native 包，35 项全过；包含模型/weight-mode 四种组合、缺值和非法 token |
| 外层入口 | Make 三个入口与 Python 环境变量选择的默认/覆盖/拒绝行为静态验证通过 |
| 小图模型贯通 | 256-bit fixture，两个 cost-model × 两个 weight-mode 均完成分区、重建与诊断检查 |
| 默认兼容性 | 默认和显式 legacy 的 HGR、原始 solver partition 文件一致；两个既有 HGR 与修改前 SHA256 一致 |

两个既有 HGR 的 SHA256（修改前后相同）：

```text
top_repcut_k2.hgr
a56006302c5c5accbb40d3c7742904e91f05962fe76e6094c77970524c480964
closure_aware/top_closure_aware_repcut_k2.hgr
d92fce68ffca4cbd7e2fa14fb92632d5811128c920c6e2524c80da219fd7f7e7
```

256-bit fixture 的 solver 输入示例（仅证明接线生效，数值大小不代表性能优劣）：

| weight-mode | cost-model | 六个顶点权重 | 唯一共享边权 |
| --- | --- | --- | --- |
| baseline | legacy | 7 / 7 / 7 / 7 / 7 / 7 | 55 |
| baseline | verilator-v1 | 21 / 21 / 21 / 21 / 21 / 21 | 55 |
| closure-aware | legacy | 8 / 8 / 8 / 7 / 7 / 7 | 58 |
| closure-aware | verilator-v1 | 24 / 24 / 24 / 24 / 23 / 23 | 71 |

回归记录：`wolvrix/build/commit-check/Testing/Temporary/LastTest.log`；
小图产物：`wolvrix/build/commit-check/artifacts/repcut_test/cost_{baseline,closure}/{legacy,verilator-v1}/`。
这些是接口/机制检查，不是香山全量重新划分、仿真功能或性能验收。

### 5.3 独立 Verilator 生成探针

脚本：[repcut_verilator_size_probe.py](../../scripts/repcut_verilator_size_probe.py)。
它默认校验 node030，并把自身和 Verilator 子进程固定在 CPU96-127；只运行 `--cc`，不做 C++ 编译和仿真。
本轮工具为 Verilator 5.048。

矩阵：identity/add/reduce_or/static_slice/dynamic_slice/shift × 32/64/65/128/256/1024 bit，共 **36/36 通过**。
slice 的源宽度为标称宽度两倍、输出为标称宽度；这不是“固定 8-bit 输出、逐步加宽输入”的实测。
固定窄输出的规则当前由 helper 源码核实和 C++ 单测覆盖，后续应补对应实际生成/执行探针。

JSON 记录每个用例命令、返回码、版本、affinity、SV/C++ SHA256，以及排除 `__Slow` 后的源码规模。
以下仅计 root-fast C++，不含 facade/symbol-table C++ 或 helper 定义：

| 操作 | 128-bit 字节数 | 1024-bit 字节数 | 解释 |
| --- | --- | --- | --- |
| add | 4,102 | 4,221 | wide helper 的调用点很短，helper 内部 work 随 words 增长 |
| shift | 4,156 | 4,279 | 同样不能从调用点字节数推算 helper 执行成本 |
| dynamic_slice | 6,419 | 18,585 | 本矩阵输出也随宽度增加，不可外推为窄切片成本 |

产物：`build/repcut_cost_model_20260922/verilator_probe/summary.json`，SHA256：
`cb913434995410e5d9fb93c18f3707d0238b0e9a013c47c124a6a48997726657`。
脚本 SHA256：`16e3825a91738d8ca8f3ecac7355c7cf26f71241e01492a812c8e7e3a43cfd34`。

### 5.4 下一步与当前结论

当前可确认：后端模型已独立、默认兼容性样例通过、几个明确的旧计价缺口有机制解释及测试。
**尚不能确认新模型提高权重/eval 相关性或改善最终 walltime。**

后续按以下顺序继续，关键数据仍追加本专题：

1. 扩展固定窄输出切片、write mask、组合结构的独立生成/执行探针；先识别模型系统性低估/高估，不用香山时长反推大量系数。
2. 在固定原分区上对比两种模型的相对排序与长尾误差，区分“计价改善”和“重新分区导致结构改变”。
3. 使用相同输入图、K=N、构建优化和程序区间重做划分/编译/交错 walltime 对照，同时审计 update、复制和通信量。
4. 按独立设计及程序区间留出验证；未知后端有自己的规则与版本，不继承“Verilator 已验证”的结论。

## 6. 固定分区相关性与收益验证（2026-09-22）

### 6.1 固定四组分区重新计价

直接加载原 baseline/single00/pair00/combined 的 `partitioned.json`，调用生产
`estimateRepcutOperationCost` 计算 legacy 与 verilator-v1；没有重新分区或重新采样时间。
性能数据仍为 TNO0331 §7.11 同批八轮、每轮20102 step的 callback eval/update均值之中位数。
所有评分运行在 node030 CPU96-103，运行时测试前评分进程已全部退出。

**同口径比较**：表中两列均是重建后全部操作的成本，使用各 part graph 的局部扇出，
包含边界连接和其他重建新增操作；不是原始 `estimated_node_weight_sum` 或求解器 hyper weight。
固定分区可隔离计价规则变化，但仍只有一个设计的四种结构，不构成跨设计泛化验证。

| 分区方案 | Pearson legacy -> v1 | Spearman legacy -> v1 | 最慢分区的预测排名 legacy -> v1 | 最慢四分区命中率 legacy -> v1 |
| --- | --- | --- | --- | --- |
| baseline | 0.9100 -> 0.8964 | 0.3644 -> 0.6891 | 1 -> 1 | 25% -> 50% |
| single00 | 0.7098 -> 0.7728 | 0.4718 -> 0.7423 | 2 -> 2 | 50% -> 50% |
| pair00 | 0.6690 -> 0.7436 | 0.5026 -> 0.7163 | 2 -> 2 | 50% -> 75% |
| combined | 0.7184 -> 0.7846 | 0.5059 -> 0.8306 | 2 -> 2 | 50% -> 75% |

Pearson 衡量线性关系，Spearman 衡量排序一致性；最慢四分区命中率为权重前四与eval前四集合的交集/4。
去掉各模型权重最大的分区后，baseline 的 Pearson 为0.2763 -> 0.5726，
说明全体0.9左右的Pearson受超大分区明显主导，不能仅看这个数字。

另外剔除 `repcut_in_slice_*` 与 `repcut_out_bundle_*` 两类适配操作，Spearman依次为：

| 方案 | legacy | v1 |
| --- | --- | --- |
| baseline | 0.2801 | 0.6701 |
| single00 | 0.4417 | 0.7335 |
| pair00 | 0.3493 | 0.6957 |
| combined | 0.4051 | 0.8043 |

排序改善并非只来自新增适配成本。剔除两类适配后仍有其他重建新增项和局部扇出变化，
不能称为精确恢复重建前权重。v1回退约占11.2%操作、6.0%权重，主要包括storage/read/constant。

### 6.2 仍未解释好的关键分区

combined 的例子（权重为同一重建后口径）：

| part | legacy | v1 | eval us/step |
| --- | ---: | ---: | ---: |
| 3 | 530,675 | 498,037 | 163.2810 |
| 4 | 702,039 | 674,092 | 142.1655 |
| 20 | 395,252 | 323,824 | 20.8920 |
| 21 | 408,161 | 294,510 | 80.8765 |

三组拆锥方案的最慢分区都仍排第二。part20/21 的真实eval相差3.87倍，v1甚至把part20排得更重，
说明只按操作类型/位宽的静态求和仍缺少重要因素。不能据平均排序改善宣称解决了尾部瓶颈。
下一步应结合后端消除/合并、条件活动率、宽操作实际生成和分区边界上下文定位；
不直接为part3/part21添加专用系数。

完整128分区及按操作类型分解：
[summary.json](../../build/repcut_cost_model_20260922/fixed_partition/summary.json)、
[parts.csv](../../build/repcut_cost_model_20260922/fixed_partition/parts.csv)、
[metrics.csv](../../build/repcut_cost_model_20260922/fixed_partition/metrics.csv)。
目录还保存C++评分工具、Python汇总脚本、逐组CSV和输入SHA记录。
summary SHA256为 `6a34fa078ce69bb21da5057694af5835feb70bb310fce1bd212af03635c1b8f3`。

当前结论是“排序指标普遍改善，但关键长尾误差仍在”；walltime收益须由下面独立重新分区和交错运行验证。

### 6.3 重新分区与两种运行区间的交错验证

本轮 A 为已完成 single00+pair00 拆锥的 combined/legacy，B 为同一输入图的
combined/verilator-v1。不是原始未拆锥 baseline。保持 K=N=32、closure-aware、
imbalance=0.015、32 solver threads 和 deterministic-quality 解析后的 preset。
输入 JSON SHA256 为 `c7b8b36adaf98f8bd794593f0d2f5c18e418f6566dae48edc5fabfb5f8d56e8e`。
新生成器使用与原生产流程一致的 Release 构建；没有根据本轮时间修改 v1 系数。

node030 CPU96-127，NUMA1，ASLR关闭，Host lane9/CPU105，31后台worker，默认all-spin。
两种区间各8对AB/BA交错，每组4对AB、4对BA；每批先各做一次C100初始化检查。
保留全部成功样本，无核空闲门槛、无异常值剔除。仿真期间没有并行编译或评分任务。
共32次正式运行和4次C100全部通过，ELF/image/NEMU运行前后身份一致。

- C10000：PC=`0x800027c6`、instructions=458、cycleCnt=9996、guest cycles=10001、steps=20102。
- C30000：PC=`0x80000442`、instructions=27809、cycleCnt=29996、guest cycles=30001、steps=60102。
- 两种正式区间均启用Difftest，均验证全部32分区计时和runtime配置。

编译公平性单独核对：同一Clang21.1.5/Verilator5.048/linker，common runtime/header、
外层runtime、make源码、生成头文件一致；wrapper均`-O3`，模型fast均`-Os`，slow均无显式`-O`。
新旧fast/slow文件数分别为878/474和899/476；新构建32档案、1352对象全部新生成。
详见[build-fairness-audit.json](../../build/repcut_cost_model_20260922/combined_v1_release/build-fairness-audit.json)。

下表时间为各自8次中位数，变化为8个配对百分比的中位数，不是两列中位数直接相除。

| 指标 | C10000 A -> B | 配对变化 | C30000 A -> B | 配对变化 |
| --- | --- | ---: | --- | ---: |
| 最终walltime/s | 4.400 -> 4.290 | -2.497% | 12.945 -> 12.625 | -2.393% |
| Host/s | 4.2885 -> 4.1920 | -2.248% | 12.8310 -> 12.5215 | -2.359% |
| 全局eval/us/step | 176.613 -> 171.874 | -2.693% | 175.867 -> 170.868 | -2.750% |
| 最慢part eval/us/step | 169.446 -> 163.469 | -3.515% | 166.343 -> 160.469 | -3.601% |
| 全局update/us/step | 28.456 -> 28.492 | +0.116% | 28.626 -> 28.350 | -0.849% |
| 各part update之和/us/step | 392.388 -> 299.880 | -23.633% | 394.720 -> 300.328 | -23.457% |

两批walltime均8/8获胜。C10000配对范围-3.160%至-2.273%，AB/BA中位数分别-2.613%/-2.275%；
C30000范围-2.703%至-1.543%，AB/BA分别-2.547%/-2.283%。收益方向不依赖先后顺序。
callback之和不是关键路径；update之和下降约23%没有转化为同幅全局update改善。
不能据此宣称整个通信阶段快了23%。

### 6.4 实际分区权重相关性、通信与残留瓶颈

这里改用每份分区生成时记录的重建前`estimated_node_weight_sum`，
与本轮同批每part callback eval均值之中位数关联。不同于§6.1的“固定分区双模型重计价”：
本表同时改变了计价模型和分区结构，不能把相关性变化全部归因于计价规则。

| 运行区间 | Pearson A -> B | Spearman A -> B | 最慢part预测排名 A -> B | 最慢四part命中率 A -> B |
| --- | --- | --- | --- | --- |
| C10000 | 0.6484 -> 0.6913 | 0.4076 -> 0.5293 | 2 -> 2 | 50% -> 50% |
| C30000 | 0.6559 -> 0.6978 | 0.4227 -> 0.5392 | 2 -> 2 | 50% -> 50% |

C30000剔除最大权重part后的Pearson为0.5333 -> 0.6645，改善不只来自最大点。
但B中权重第一part3=636320，eval=145.956us；真正最慢part6权重414157，eval=160.469us，
仍有明显长尾排序错误。

`hyper_partition_weight`是共享工作均摊后的求解器负载，不能当线程完整成本。
C30000其Spearman为-0.1074 -> -0.0093，真实最慢part的排名21 -> 20。
求解器将多数part压在窄权重范围，本身也会减弱这种结果侧相关性；
不能单凭这一指标判定分区目标无用，但它显然不足以解释最终时长。

分区归属对账发现：旧part4和新part3都仅含ASC5，其303536个操作、249878个组合操作、
操作类型/宽度分布均相同。权重676199 -> 636320只是模型单位变化，**并非最大逻辑锥缩小**。
旧运行瓶颈part3拥有的ASC被重新安排至新part6（11522个）、part7（3175个）、part5（2495个）等；
其中次大ASC89887进入新part6。不是简单把part3改名。
因此本轮是“重新组合瓶颈周围工作后获得小幅收益”，不是进一步拆开ASC的证据；
边界连接、生成代码布局和CPU映射也随重分区改变，不能把全部收益独立归因于某一项。

| 静态量 | A legacy | B v1 | 变化 |
| --- | ---: | ---: | ---: |
| 跨分区push语句/step | 6541 | 5286 | -19.187% |
| push逻辑bit/step | 3635104 | 3640312 | +0.143% |
| push存储byte/step | 460987 | 460647 | -0.074% |
| 重建前分区操作总量 | 5847048 | 5865442 | +18394 |
| 重建后分区操作总量 | 6176620 | 6184616 | +7996 |
| 重建新增操作 | 329572 | 319174 | -10398 |

字节为生成代码静态存储复制量，按目的端计fanout，不包含cache-line流量或顶层IO。
操作净增量不等于纯计算复制，还可能包含省略/声明；重建后另含适配器。
weighted compute_km1使用不同模型单位，不能用576589 -> 575483声称复制计算下降。
通信字节几乎不变，但语句更少、分布不同，可能影响update；没有PMU证据时不作cache因果结论。

### 6.5 产物与下一轮边界

- C10000：[summary.json](../../build/repcut_cost_model_20260922/interleave8_node030_v1/summary.json)，
  SHA256=`f8788d331f2f8dd7caa93b27953b7ffa41dd549594eb1ded8ddd875b3d90d622`。
- C30000：[summary.json](../../build/repcut_cost_model_20260922/interleave8_node030_c30000_v1/summary.json)，
  SHA256=`733a0b3e5d62176cb460b9b8cd85f511ca3f913715cc4ff6c06e6a605121b7f0`。
- 每批目录保留manifest、全部成功日志/计时、runs/pairs/parts CSV与JSON；
  `partition_analysis/`保留相关性、逐分区权重/时间/通信、最慢四分区和源文件身份。
- 本轮脚本为`scripts/repcut_cost_model_compare.py`；C30000使用`--cycles 30000 --pairs 8`。
  静态/动态关联工具在`build/repcut_cost_model_20260922/analyze_partition_runtime.py`。
- B ELF SHA256=`56b170feecb7bb7be200b563f6a5e8a93483a0e3ae6dee5c871f5d25af537553`；
  A ELF SHA256=`16acc0fa0456699305340bf1687a2c040b0842a70fc52d36cfb5304f34527b68`。

当前可以确认：此combined设计、此工具链和两个嵌套程序区间下，v1有约2.4%的可重复walltime收益。
两种C共享前缀，不是独立workload；尚无跨设计泛化或完整CoreMark完成验证。
不修改legacy默认，不用本批时间为part6拟合专用系数。
下一轮优先研究ASC89887相关的生成/执行行为、条件活动和共享逻辑上下文，
先在独立小设计验证机制，再评估通用规则及尾部预测，避免只优化平均相关性。

### 6.6 新旧分区上的双模型交叉计价

补充加载新分区`partitioned.json`，与§6.1同一评分工具和生产成本API分别计算legacy/v1；
输入SHA256=`8c5f0945520b5ea5ae5f3776aa427af36f7dbca23fd6c159c905af1cb21e3821`，
32个part的操作数均与生成记录吻合。node030 CPU96-103执行，先前全部仿真已结束。
将新旧分区各自固定，分别关联本轮8次时间，隔离“分区变动”对计价比较的干扰。

表中是重建后全部操作口径；每行两种模型使用同一分区、同一时间。

| 分区结构/时间 | Pearson legacy -> v1 | Spearman legacy -> v1 | 最慢预测排名 legacy -> v1 | 最慢四part命中率 legacy -> v1 |
| --- | --- | --- | --- | --- |
| 旧combined/C10000 | 0.7253 -> 0.7962 | 0.5150 -> 0.8376 | 2 -> 2 | 50% -> 75% |
| 旧combined/C30000 | 0.7328 -> 0.8034 | 0.5345 -> 0.8530 | 2 -> 2 | 50% -> 75% |
| 新v1分区/C10000 | 0.4457 -> 0.7464 | 0.2361 -> 0.6012 | 11 -> 2 | 25% -> 50% |
| 新v1分区/C30000 | 0.4518 -> 0.7539 | 0.2368 -> 0.6103 | 11 -> 2 | 25% -> 50% |

C30000扣除两类边界适配操作后，旧结构Spearman为0.4252 -> 0.8240，
新结构为0.1338 -> 0.5323；新结构最慢part排名15 -> 2。
这支持“v1的计价改善不只存在于旧分区”的判断，但仍不是跨workload验证。
v1重分区后相关性绝对值低于旧结构上的0.85也不矛盾：分区结构和权重取值范围都改变了，
且重新均衡后剩余误差更显眼；不能跨行只比较一个相关系数来判断walltime收益。

完整数据：[cross_validation.json](../../build/repcut_cost_model_20260922/fixed_partition/cross_validation.json)、
[cross_validation.csv](../../build/repcut_cost_model_20260922/fixed_partition/cross_validation.csv)，
JSON SHA256=`c1ddd669c75bbdc15e4d616048f04f53551402bbec7aad27ccac0375ade1ef58`。
汇总脚本为`build/repcut_cost_model_20260922/cross_validate_costs.py`，
原始评分为`fixed_partition/new_partition.costs.csv`与对应PASS日志。
本轮至此没有追加基于香山时间拟合的模型系数，默认仍为legacy。

## 7. part6执行热点与窄取位实验（2026-09-22）

### 7.1 排除等待后的动态热点

继续使用§6的combined/v1 ELF和分区，未改变权重、RTL或运行时。
node030 CPU96-127、NUMA1、K=N=32、Host lane9、all-spin；三次C30000
采样均通过原有Difftest签名检查。以199Hz采集用户态cycles/instructions，
将模型函数、初始化、update wrapper、公共库和runtime等待分别归类。
这些运行受采样扰动，不与无采样的AB/BA性能结果混用。

part6在三次采样中eval为165.793/164.827/164.992us，part3为
150.391/149.400/149.701us。part6的四个函数占其模型叶子cycles采样权重约53%：
`ico_sequent__TOP__9`、`ico_sequent__TOP__10`、
`nba_comb__TOP__10`、`nba_comb__TOP__11`。
它们共含4096处128-bit `VL_SHIFTR_WWI`，均围绕两路Difftest rawData取位；
ICO/NBA各2048处。这是生成代码中的出现次数，不能当作每step执行4096次。
这些函数还执行宽临时数组的清零/复制。

另做一次99Hz、CPU99/102限定的DWARF调用栈采样，确认part6的`memset`
直接调用者包括上述四个函数。只看模型叶子会漏掉这些公共库成本；
不能把模型叶子的指令数、IPC直接解释成整个eval的精确PMU计数。
调用栈部分截断，现有证据也不足以独立断言cache miss或频率是主要原因。
这里已将all-spin轮询与模型执行分离，不以整线程CPU利用率定位热点。

静态代码大小同样不能直接预测这一差异：part6 fast C++约78.28MB、
object text约4.12MB；part3分别约120.69MB和5.44MB，反而都更大。
part6四个热点对象text共1625354 bytes，占其fast text约39.5%。

原始证据：
[三轮采样汇总](../../build/repcut_cost_model_20260922/hotspots_v1/analysis.json)、
[调用栈运行记录](../../build/repcut_cost_model_20260922/hotspots_v1_callgraph/manifest.json)、
[生成代码统计](../../build/repcut_cost_model_20260922/hotspot_analysis/static_analysis.json)。
目录保留perf数据、符号/分区CSV、运行日志与脚本。

### 7.2 源头是Difftest逐位切片，不是可删除的打印

源码位于`testcase/xiangshan/src/main/scala/xiangshan/mem/sbuffer/Sbuffer.scala`
的`UIntSlice`（约891行），调用点约954/1025行，受`EnableDifftest`控制。
它用循环逐位构造切片：满足边界条件时取`in(Low + i)`，其余补零。
两路store事件、每路16个slot，把这一结构大量展开；原始Chisel生成的
`candidate_v4/rtl/Sbuffer.sv`中已经存在“128位右移后取bit0”。
因此不是RepCut凭空引入的逻辑，也不是正常存储器的数据通路本身。
这部分构造DiffStoreEvent交给NEMU作差分检查，不能等同于无副作用print而删去。

本轮没有修改香山RTL，也尚未逐节点证明上述所有切片均属于ASC89887。
下一步先消除已证实的宽移位开销，再决定是否需要继续移动ASC或增加权重。
源码示意：

```systemverilog
assign shifted = data >> index; // 128-bit intermediate
assign result = shifted[0];
// Equivalent guarded selection, retaining the complete unsigned index:
assign result = ($unsigned(index) >= 32'd128) ? 1'b0 : data[$unsigned(index)];
```

### 7.3 独立机制探针与保守实现边界

独立小模型测试32/64/65/128/256-bit，无符号逻辑右移后取bit0，与完整索引
越界保护的直接取位比较。每宽度10068组输入、每组64个输出，合计每方案
3221760个输出位均与独立C++参考相符。覆盖全零/全一/交替位、位宽边界及
索引高位；这是两态动态测试，四态另由下面的SVInt测试覆盖。

node030 CPU96、NUMA1、关闭ASLR，相同Clang、模型fast `-Os`、驱动`-O3`，
每项6对AB/BA，每样本100000 eval。表中base在`[0,W-1]`取值，64个lane用
`base+lane`，尾部lane仍可能越界；计时包含驱动开销，不能直接外推香山收益。

| W | 原式ns/eval | 取位ns/eval | 配对加速比 | fast object text原式→取位/bytes |
| --- | ---: | ---: | ---: | ---: |
| 32 | 36.50 | 36.72 | 0.99x | 1858→1925 |
| 64 | 49.17 | 55.62 | 0.89x | 3323→2694 |
| 65 | 199.04 | 83.05 | 2.39x | 20813→4270 |
| 128 | 305.36 | 66.93 | 4.57x | 20429→3370 |
| 256 | 460.85 | 66.38 | 6.88x | 21549→3466 |

128-bit探针的C++文本反而从36494增至94430 bytes，机器码却减少约83.5%。
这进一步否定“直接用生成C++字节数当执行成本”的方案。
完整记录：[summary.json](../../build/repcut_cost_model_20260922/shift_bit_probe/summary.json)。

实现位于`wolvrix/lib/emit/system_verilog.cpp`，只覆盖宽度>64、unsigned Logic、
移位输出等宽、静态bit0切片、数据表达式为简单标识符的情况；不修改图、
分区、权重或runtime。不截断索引，不改算术移位、signed或其他切片。
保留原移位定义供其他使用者引用；无其他使用者时由后端消除。
定向CTest覆盖正例、保守排除项及共享结果，另用Slang SVInt测试65/128/256位
数据、7/13/33位索引、X/Z、越界及高位索引的四态表达式等价。
`emit-sv-shift-low-bit/readmem/storage-ports/top-reachable`四项通过。

真实设计验证使用§6新v1的同一`partitioned.json`直接重新emit，**没有重新分区**；
输入SHA仍为`8c5f0945520b5ea5ae5f3776aa427af36f7dbca23fd6c159c905af1cb21e3821`。
先校验common/header/eval/load/update wrapper完全相同，再全新编译32个模型。
运行结果将在后续小节追加；本节不预先宣称实际walltime收益。

### 7.4 生成器改写的真实设计验证

候选臂在与基线完全相同的`partitioned.json`、C=30000、K=N=32、all-spin和
node030 CPU96-127上完成8对交错AB/BA测试。8对均通过签名检查，候选8/8次
胜出；不重新分区、不改变权重、不改变通信数据或runtime配置。构建公平性审计
通过：工具链、头文件、runtime、构建脚本和输入均相同，只有生成分区SV/filelist
及由此产生的全量编译产物不同。

| 指标 | 基线中位数 | 候选中位数 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host time (s) | 12.6305 | 11.2905 | -10.664% |
| wall elapsed (s) | 12.7350 | 11.3950 | -10.592% |
| 全局 eval (us/step) | 172.3145 | 150.0305 | -12.972% |
| 最大分区 eval (us/step) | 161.9265 | 147.3110 | -9.042% |
| 分区 eval 总和 (us/step) | 1901.3760 | 1790.7035 | -5.834% |
| update push (us/step) | 28.6415 | 28.8680 | +1.100% |

AB和BA方向的Host变化分别为-10.759%和-10.556%，说明收益不是单次运行顺序
造成的。update略有回退，而eval显著下降，符合“消除宽移位执行开销”这一机制，
也排除了把收益误判成线程唤醒或通信优化。

分区级中位数进一步定位了瓶颈转移：基线`part_6` eval为161.927 us，候选
降至66.420 us；候选最慢分区变为`part_3`，147.311 us。`part_3`的预估权重、
分区边界和机器码text均未因本改写发生变化。候选的part_6生成代码中4096处
128-bit宽右移全部消失，fast object text从4,117,409降至3,012,776 bytes
（约-26.8%）；C++源文件字节数反而增加，这是生成器临时表达式减少后代码文本
变化的结果，不能用源文件大小代替执行成本。

本轮结果表明，当前最大ASC未缩小仍可以取得明显walltime收益：瓶颈在ASC内部的
后端代码质量，而非仅在分区数量或静态权重。代价是该规则目前只覆盖已证明安全
的宽度>64、unsigned Logic、等宽LShr后静态bit0切片；尚未作为跨workload的
默认性能承诺。下一步应在第二个设计/仿真器上验证规则的适用性，并观察新瓶颈
`part_3`是否有同类宽操作，再决定是否扩展模式或调整成本模型。

完整产物：[8对C30000交错汇总](../../build/repcut_cost_model_20260922/interleave8_shift_c30000/summary.json)、
[分区级分析](../../build/repcut_cost_model_20260922/interleave8_shift_c30000/partition_analysis/summary.json)、
[构建公平性审计](../../build/repcut_cost_model_20260922/shift_low_bit_v1/build-fairness-audit.json)。

## 8. 新 part_3 后端热点复核与泛化边界（2026-09-22）

### 8.1 part_3 没有复现 part_6 的同类右移热点

对同一份固定 `partitioned.json`，比较宽移位改写前后的两个生成目录：

- 基线：`build/repcut_cost_model_20260922/combined_v1_release/build/package/build/verilated/part_3/`
- 候选：`build/repcut_cost_model_20260922/shift_low_bit_v1/build/package/build/verilated/part_3/`

两边都包含78个C++源文件。`part_3`的关键 helper 出现次数完全一致：

| helper | 次数 |
| --- | ---: |
| `VL_SHIFTL_WWI` | 2360 |
| `VL_SHIFTL_III` | 134 |
| `VL_REDXOR_32` | 2252 |
| `VL_REDXOR_64` | 196 |
| `VL_FWRITEF_NX` | 584 |

没有发现 `VL_SHIFTR_WWI`。最大的几个源文件大小也完全相同，归档文件只差8字节，
说明本次 `shiftedLowBit` 改写没有命中 `part_3`，而不是命中了但收益太小。

抽样生成代码显示，`part_3`中的宽操作主要是类似下面的写入准备：

```cpp
VL_SHIFTL_WWI(70, 70, 32, __Vtemp_2, ... , 7U);
...clientDir...eccArray...Memory__v7 = (1U & (__Vtemp_2[0U] >> 7U));
```

以及对L3 tag/ecc/clientDir等memory写值的宽左移、归约异或和切片。它们的结构是
“先构造待写入的宽值，再取其中的字段”，不是旧 `part_6` 中“宽逻辑右移后只取
bit0”的模式，因此不能直接套用同一条后端规则。静态引用统计也显示它覆盖了
L2/L3 cache、memory port和协议控制逻辑（匿名组合逻辑引用约183887次，L2约112989次，
四个L3 slice各约39700次），最大中间信号宽度仍为65536。`nba_sequent`中的584个
`VL_FWRITEF_NX`来自带条件的Assertion failed诊断路径，不能据此认为运行时正在打印。

结论是：当前新的最大分区瓶颈属于更宽的cache/memory/protocol组合闭包，候选方向应
单独分析宽左移和memory写入值物化，或减少这类组合逻辑的物化范围；不应为了追求
`part_3`的统计命中率而放宽当前右移低位规则。

### 8.2 第二 workload 和其他 emitter 的泛化检查

当前规则在 `wolvrix/lib/emit/system_verilog.cpp` 中是刻意收窄的后端规则，只匹配：
unsigned `Logic`、`kLShr`、源宽度大于64、移位结果与源等宽、后续静态取bit0，且
数据表达式为简单标识符。它不是图级变换，也不应该复制到 `grhsim_cpp.cpp` 或 GSIM
的独立 lowering 路径。

已完成以下验证：

| 范围 | 结果 | 能说明什么 |
| --- | --- | --- |
| `emit-sv-shift-low-bit` focused test | 通过 | 65/128/256位四态语义和保守排除项正确 |
| HDLBits `DUT109` + Verilator | 通过 | 64位顺序左右移不触发该规则，SV路径不回归 |
| HDLBits `DUT109` + GrhSIM | 通过 | GrhSIM路径行为正确，未受到SV专用改写影响 |
| BigComb既有GSIM/GrhSIM bench，另以1000向量重跑 | 通过；GSIM 18.707 ms，GrhSIM 18.820 ms，checksum相同 | 第二个Chisel workload和另一套emitter的语义/链路不回归 |

BigComb的Chisel/SV中确实有127位动态左移，但右移部分是64位，未形成当前规则
需要的“宽于64位逻辑右移后取bit0”正向样例。因此上述跨workload结果是负向
non-regression，不是第二个workload上的性能收益证明。对现有HDLBits、xs-components
和OpenC910代码的扫描也没有找到明确的第二个正向样例。

当前可作出的最强结论是：规则的四态语义已经有正向覆盖，非匹配workload以及
GrhSIM/GSIM没有回归；实际性能收益仍只在XiangShan/Verilator上被证明。若要证明
跨workload的正向泛化，需要再选或构造一个真实的“>64位 unsigned logical right
shift + bit0 select”电路，然后比较启用规则前后的生成代码、编译规模和运行时间。

## 9. `part_3` 第一轮运行时热点分析（2026-09-22）

### 9.1 运行时热点不是一个 helper，而是一个分散的组合闭包

使用固定 `combined_v1_release` binary、C=30000、32线程 all-spin 配置做了三次
低频 PMU 采样，并用其中的 callgraph 采样做函数归因。`part_3` 的 `eval` 为
`149.4/149.7/150.4 us/step`。模型函数本身约占该分区采样周期的66%--69%，
`runtime_dispatch_spin` 约占25%--28%，其余是 wrapper/update 等开销。这说明
`part_3` 的主要瓶颈确实在生成模型，但不能把 all-spin worker loop 的周期误算成
RTL执行时间。

按 `part_3` model samples 排序，前5个函数只占该分区模型样本约26.47%，前10个
约42.06%，前20个约65.41%。稳定出现的函数包括：

```text
VWolviRepCutUnit_part_3___024root___nba_comb__TOP__0
VWolviRepCutUnit_part_3___024root___ico_sequent__TOP__10
VWolviRepCutUnit_part_3___024root___ico_sequent__TOP__0
VWolviRepCutUnit_part_3___024root___nba_sequent__TOP__7
VWolviRepCutUnit_part_3___024root___nba_sequent__TOP__15
```

这些函数分别属于 Verilator 的组合 settle、初始组合和 NBA 状态更新阶段，覆盖
L2/L3 cache、协议状态和 memory port。没有一个名为 `VL_SHIFTL_WWI` 或
`VL_REDXOR_*` 的单独 helper 成为运行时第一热点，因此不应按 helper 出现次数
直接决定优化优先级。

### 9.2 静态代码与动态热点的交叉定位

`part_3` 的静态规模为：303536个operation、249878个组合operation、770056个
fanout、最大宽度65536、54个fast C++文件、约120.69 MB源代码和约5.44 MB
object text。其操作结构中有2641个 `MemoryWritePort`、34393个 `Mux`、1197个
`ReduceXor`，而 `kLShr` 只有66个；这与它不是旧 `part_6` 宽右移热点的判断一致。

宽左移的2360次 `VL_SHIFTL_WWI` 全部集中在四路L3 slice复制的8个
`nba_sequent`函数：

| 函数组 | 每个函数宽左移 | 典型宽度 | 作用 |
| --- | ---: | --- | --- |
| `TOP__20`--`TOP__23` | 303 | 70、300 bit | clientDir 的 ECC/tag memory 写入准备 |
| `TOP__24`--`TOP__27` | 287 | 112、448 bit | selfDir 的 ECC/tag memory 写入准备 |

典型代码先构造70/112/300/448位的 `VlWide` 临时值，再从临时值取一个固定
bit或小字段，写入 `__VdlyVal__`，同时更新 `__VdlyDim0__` 和 `__VdlySet__`。
因此成本形态是“宽临时量物化 + 逐bit延迟memory write”，不是动态右移后取
bit0。8个函数合计约一万多个延迟值写入，且四路L3 slice重复出现。

`ReduceXor` 的静态热点主要位于 `TOP__5`（624次）、`ico TOP__0`（384次）、
`TOP__2`（160次）和 `TOP__15`（128次），但这些函数并不完全等同于动态时间热点。
这再次说明静态 helper 计数适合做候选发现，不适合直接代替运行时成本模型。

### 9.3 当前应优先尝试的方向

第一轮分析把候选收敛为三类，优先级如下：

1. 针对常量宽左移后固定bit/字段提取，尝试在生成器中直接映射到源word或源bit，
   避免先物化完整70/112/300/448位临时量。这个规则必须单独处理四态语义，不能
   直接复用当前的 `LShr -> bit0` 改写。
2. 研究L3 directory memory写入的批量物化，减少逐bit `__VdlyVal__`、维度和set
   标记的重复操作。该方向可能比单纯消灭 `VL_SHIFTL_WWI` 更重要，因为动态
   热点分布在多个大函数中。
3. 为 `ReduceXor`、memory-write staging 和大组合函数分别建立后端成本项，再用
   `part_3` 的运行时数据校准，而不是继续只增加通用 `kShl` 或 `kReduceXor` 的
   静态权重。

本轮没有修改代码，也没有把受外部负载干扰的候选采样纳入证据。原始采样和静态
分析仍保存在：[hotspots_v1 callgraph manifest](../../build/repcut_cost_model_20260922/hotspots_v1_callgraph/manifest.json)、
[hotspots_v1 symbols](../../build/repcut_cost_model_20260922/hotspots_v1/symbols.csv)、
[part static analysis](../../build/repcut_cost_model_20260922/hotspot_analysis/static_analysis.json)。

## 10. 常量左移 memory-write 后端改写（2026-09-22）

### 10.1 命中实际 `part_3` 结构

进一步检查生成前的 GRH 和生成后的 Verilator C++ 后，确认 `part_3` 的 2360 次
`VL_SHIFTL_WWI` 并不是普通的“左移后再取一个显式 slice”节点。真实形态是：

```text
窄 tag/ECC 数据 --kShl(常量移位)--> 宽 memory-row 数据
                                      |
                                      +--> kMemoryWritePort（常量部分写掩码）
```

memory-write 后端原来会对掩码命中的每一位生成
`Memory[address][bit] <= shifted[bit]`。Verilator 因而在每个 bit 的 RHS 中重复
物化完整的宽左移。四个 L3 slice 复制组中的宽度分布是 70、112、300、448 bit，
对应 252、252、960、896 次调用。

### 10.2 实现和保护边界

在 `wolvrix/lib/emit/system_verilog.cpp` 中增加了后端等价改写。对无符号
`Logic`、结果宽度大于 64、源宽度不大于结果宽度、memory 行宽相同、常量且非负
移位量以及简单源标识符的情况，直接按

```text
output_bit[b] = source[b - shift]       (0 <= b-shift < source_width)
output_bit[b] = 1'b0                    (otherwise)
```

生成每个被 mask 的 RHS。这样只消除了宽临时量，不合并 NBA，不改变 enable、地址、
掩码、时钟、写入顺序或 priority。DPI 依赖、动态/未知/有符号移位、截断结果、
完整或动态 mask 均保留旧路径。常量按自身 literal 宽度解析后再按 GRH 移位量宽度
调整，避免 `3'd8` 等截断语义被误判。显式等宽一位 slice 也复用同一位映射；越界
slice 不改写，因为普通静态越界选择是 X，而左移越界是 0。

实现说明补充在 [SystemVerilog emitter 文档](../../wolvrix/docs/emit/system-verilog.md)。

### 10.3 语义和构建验证

- focused emitter 测试通过：`emit-sv-readmem`、`emit-sv-storage-ports`、
  `emit-sv-shift-low-bit`、`emit-sv-top-reachable`、`emit-verilator-repcut-package`。
- `emit-sv-shift-low-bit` 覆盖 7→70、7→112、30→300、28→448 行宽，边界/过量移位、
  X/Z、动态量、有符号源、未知量、源宽大于结果以及重叠 NBA priority。
- 额外的 Verilator emitted-SV probe 执行 1024 个周期，逐行比较所有行，覆盖上述
  四类宽度、禁用写入和同地址重叠写入，结果通过：
  [memory shift probe](../../build/repcut_cost_model_20260922/memory_shift_probe/memory_shift_tb.sv)。
- 固定相同的 partitioned JSON、32 分区 assignment、runtime wrapper、编译器和
  `-Os`/`-O3` 参数重新生成。构建审计通过，工具链、runtime、assignment、编译
  argv/environment 和 wrapper 命令一致：
  [build fairness audit](../../build/repcut_cost_model_20260922/const_shift_part3_v2/build-fairness-audit.json)。

候选输出的 `part_3` fast C++ 从 54 个文件、120,687,873 bytes、1,113,966 行降到
49 个文件、112,494,486 bytes、959,151 行，2360 个 `VL_SHIFTL_WWI` 全部消失。
对应 `part_3` object text 减少 834,117 bytes；没有修改分区 assignment 或通信量
（5286 assignments、3,640,312 logical bits、460,647 storage bytes 均保持不变）。

### 10.4 C=30000、K=N=32 all-spin AB/BA

在 node030 CPU96-127、NUMA1、ASLR disabled、32 lane all-spin 下，以已有
`shift_low_bit_v1` 为 baseline，做 8 对交错 AB/BA；所有 16 次长跑和 C=100 smoke
均通过同一 Difftest signature。完整结果在
[interleave8_const_shift_c30000](../../build/repcut_cost_model_20260922/interleave8_const_shift_c30000/summary.json)。

| 指标 | baseline 中位数 | candidate 中位数 | 配对中位变化 |
| --- | ---: | ---: | ---: |
| Host | 11.174 s | 10.5535 s | -5.47% |
| walltime | 11.280 s | 10.660 s | -5.41% |
| eval | 148.8425 us | 138.397 us | -6.78% |
| max partition eval | 145.2595 us | 135.269 us | -6.69% |
| update | 28.5410 us | 28.4635 us | -0.15% |

候选在 8/8 配对中均获胜；AB 与 BA 的 walltime 中位变化分别为 -5.45% 和 -5.41%。
收益主要来自 `part_3` 的模型 eval，update/通信基本不变。`part_3` 仍是最大 eval
分区，因此下一步应继续检查其剩余的 memory-write staging、归约和大组合函数，不能
把本次“消除宽左移”误认为已经解决整个 ASC 瓶颈。

### 10.5 最终审计补充与口径勘误（2026-09-22）

§10.3 的独立 Verilator probe 实际覆盖 7→70、30→300、28→448 三类宽度；
7→112 的正向覆盖来自 focused test 的四态语义检查，不属于该 probe。
两臂实际编译配置均为 model fast `-Os`、model slow 无显式 `-O`、wrapper `-O3`。
两臂分别编译 1355/1347 个全新模型对象，无对象复用或共享 inode。

上面的 834,117 bytes 是 `part_3` fast object `.text` 的减少量：
5,443,317→4,609,200 bytes（-15.32%）；slow `.text` 另减少 2,778,982 bytes。
其他分区 fast `.text` 合计只减少 19,763 bytes；全工程 fast `VL_SHIFTL_WWI`
为 3349→989，消除的 2360 次全部来自 `part_3`，并非全工程已无宽左移。

§10.4 的功能口径应理解为：两臂 C=100 初始化 smoke 一致；16 次 C=30000
均开启 Difftest 并得到相同的长跑 signature（PC `0x80000442`、27809 条指令、
29996 cycles、60102 steps）。短跑与长跑各自比较，不要求它们的 signature 相同。
表中时间为各臂中位数，百分比为逐对变化的中位数，故不一定等于两列中位数之比。

### 10.6 最新权重与 eval 相关性复核（2026-09-22）

用 §10.4 同批 8 对数据，每个 part 取 8 次 callback eval 均值的中位数，再在
32 个 part 间计算相关性。两臂沿用同一份 `verilator-v1` 分区和权重，主口径仍为
重建前 `estimated_node_weight_sum`，与 §6.4 一致。此次仅重算已有数据，未重新仿真。

| 指标 | 常量左移优化前 | 优化后 |
| --- | ---: | ---: |
| Pearson（线性相关） | 0.7546 | 0.7224 |
| Spearman（排序相关） | 0.5132 | 0.4824 |
| 去掉最大权重 part_3 后 Pearson | 0.2942 | 0.2855 |
| 最慢 part 的权重排名 | 1 | 1 |
| 最慢四个 part 命中率 | 25% | 25% |

本次相关性没有提升。8 次单跑的 Pearson 区间也分别为 0.7522–0.7560 和
0.7195–0.7244；Spearman 为 0.5059–0.5132 和 0.4714–0.4875，方向一致。
相关性下降与 walltime 改善并不矛盾：后端执行成本降低，但固定权重没有随之更新。
权重最大的 `part_3` 仍是最慢分区；若仅把 baseline 的 part_3 时间替换为 candidate
的 135.269 us，其余 31 个 part 时间不变，Pearson 就会降到 0.7206，而 Spearman
仍为 0.5132。这一数值替换检查说明 Pearson 的下降主要来自最大点的时间缩短；
排序相关的变化来自其他分区的顺序变化，不能归因于 part_3 单点。

尾部预测仍明显不足：权重前四为 part_3/6/10/18，实测前四两臂都是
part_3/26/11/7，只命中 part_3。优化后 part_26、part_11、part_7 的 eval
分别为 90.082、89.074、78.188 us，权重排名却是 17、13、14；反之权重第二的
part_6 只有 64.2935 us，实测排名第 9。最大点之外的 Pearson 仅约 0.29，
不能将全体约 0.72 的系数理解为模型已能准确预测各线程时长。

其他口径也没有推翻这一结论：重建后全部操作的 v1 成本 Pearson 为
0.7779→0.7474、Spearman 为 0.5986→0.5630；同一当前分区上的 legacy 重计价
则为 0.5233/0.2045。因此 v1 相对 legacy 的优势仍存在，但最近的后端优化并未
进一步改善其相关性。求解器 `hyper_partition_weight` 的 Spearman 为
0.0125→0.0082，仍不能作为完整线程成本预测。

作为时间线对照，§7 宽右移优化那一批的重建前权重 Pearson 为 0.6980→0.7592，
Spearman 为 0.5671→0.5264，最慢四个命中率从 50% 变成 25%；当时也只是全体
线性相关改善，排序没有改善。跨批次数据不拼接为同批因果对照。

原始日志重新校验和逐分区统计保存在
[最新相关性结果](../../build/repcut_cost_model_20260922/interleave8_const_shift_c30000/partition_analysis/summary.json)、
[correlations.csv](../../build/repcut_cost_model_20260922/interleave8_const_shift_c30000/partition_analysis/correlations.csv)、
[parts.csv](../../build/repcut_cost_model_20260922/interleave8_const_shift_c30000/partition_analysis/parts.csv)。
复核复用 `analyze_partition_runtime.py`，两臂 emission 参数均指向
`combined_v1_release/emit/run.json`；它们的生成输入/assignment 一致性由 §10.3 的
构建审计支持。重建后双模型分数来自既有 `fixed_partition/new_partition.costs.csv`。

## 11. `part_3` memory staging 合并（2026-09-22）

### 11.1 候选定位

在常量左移改写后的 `const_shift_part3_v2` 上继续检查生成代码。`part_3` 仍有
2496 个 partial-mask memory-write block、7904 个选定位宽 NBA；其中 408 个 block
包含连续多位写入，共 5816 bit。按每个原始 `kMemoryWritePort` 的 mask run 统计，
372 个 block、5744 bit 可以在同一个 guard/address/event/order 边界内改为一条
part-select NBA。典型形态是 L3 `tagArray` / ECC 写入：

```systemverilog
// before
Memory[address][0] <= data[0];
Memory[address][1] <= data[1];
// ...
Memory[address][18] <= data[18];

// after
Memory[address][18:0] <= data[18:0];
```

不能跨不同 `kMemoryWritePort`、priority group、动态/未知 mask、DPI 依赖、动态
地址或不同 guard 合并，因为同地址重叠的 NBA 后写优先级是可观察的。常量左移
数据只在连续 run 完全落在 source 范围内时直接映射 source slice，否则退回逐 bit
路径。该规则只改变后端语句形态，不改变 GRH、分区、通信或 runtime 调度。

独立 Verilator probe 对 448-bit memory 的 28-bit 连续写入做了 10000 个随机周期
和初始化/重叠写检查：逐 bit 与 part-select 版本逐周期、逐行比较全部通过。probe
中 root C++ 从 33027 bytes 降到 15829 bytes；这是机制证据，不是 XiangShan
性能数据。

### 11.2 代码和功能门

规则实现在 `wolvrix/lib/emit/system_verilog.cpp` 的 `kMemoryWritePort` 常量 mask
分支，focused fixture 增加了连续 run、shift boundary 和 priority 情况。以下门禁
通过：

```text
emit-sv-readmem
emit-sv-storage-ports
emit-sv-shift-low-bit
emit-sv-top-reachable
emit-verilator-repcut-package
```

冻结同一 partitioned JSON、assignment、all-spin runtime 和编译工具链重新生成
32 个 partition model；C=100 两臂 smoke 均通过。`part_3` 生成结果相对
`const_shift_part3_v2` 为：

| 指标 | v2 | staging candidate | 变化 |
| --- | ---: | ---: | ---: |
| C++ 文件数 | 72 | 68 | -4 |
| C++ 字节 | 167,996,330 | 156,601,307 | -6.78% |
| C++ 行数 | 1,432,455 | 1,363,833 | -4.79% |
| object `.text` | 15,190,628 | 14,972,373 | -1.44% |
| `__VdlyVal` 引用 | 30,540 | 10,600 | -65.28% |
| `__VdlyDim0` 引用 | 37,052 | 11,832 | -68.07% |
| `__VdlySet` 引用 | 10,848 | 10,848 | 0% |

### 11.3 C=30000、K=N=32 all-spin AB/BA

在 node030 CPU96-127、NUMA1、ASLR disabled 下，以 `const_shift_part3_v2` 为
baseline，执行 8 对交错 AB/BA；16 次长跑及两臂 C=100 smoke 均通过 Difftest。
完整结果在
[interleave8_memory_slice_c30000](../../build/repcut_cost_model_20260922/interleave8_memory_slice_c30000/summary.json)。

| 指标 | baseline 中位数 | staging candidate 中位数 | 配对中位变化 |
| --- | ---: | ---: | ---: |
| Host | 10.4875 s | 10.4255 s | -0.61% |
| walltime | 10.595 s | 10.525 s | -0.66% |
| eval | 137.1285 us | 136.1575 us | -0.83% |
| max partition eval | 134.1455 us | 133.4355 us | -0.54% |
| update | 28.593 us | 28.6125 us | -0.13% |
| sum partition eval | 1732.9545 us | 1735.8695 us | +0.14% |

candidate 在 8/8 配对中获胜，walltime 配对变化范围为 -1.13% 至 -0.28%。收益
来自 eval，而不是通信或 update；sum eval 略增说明它主要减少了最大分区的局部
生成/执行开销，而不是减少全部 partition work。与上一轮消除宽左移的约 5.41%
walltime 收益相比，这一项属于小幅但可重复的 staging 优化。

### 11.4 边界和下一步

这项优化已经证明“逐 bit memory staging”是实际成本项，但没有改变 `part_3` 的
结构瓶颈。candidate 的静态审计仍显示最大的函数分为两类：memory/staging-heavy
的 `nba_sequent TOP0/TOP6/TOP7`，以及 reduction/大组合逻辑为主的
`nba_comb TOP8`、`nba_sequent TOP5` 和 `ico TOP8`。其中 `nba_comb TOP8` 约含
18 个 `VL_REDXOR_64`、4 个 `VL_REDXOR_32`，`nba_sequent TOP5` 约含 624 个
`VL_REDXOR_32`，`ico TOP8` 约含 40 个 `VL_COUNTONES_I`。

因此下一项应单独针对 reduction/大组合函数做 source-to-emitted-code 对照和小型
语义 probe；不要把本轮的 part-select NBA 继续扩大到不同 operation 或动态 mask。
原始静态扫描、probe 和构建结果均保留在 `build/repcut_cost_model_20260922/`。

## 12. 当前 v3 的 reduction / 大函数动态定位（2026-09-22）

### 12.1 版本对齐与 §11 勘误

本节只分析 `memory_slice_part3_v3`，其 ELF SHA256 为
`23b5ddd07e9a8ff98b006ab1168b0c2e1d7be4e504d83243a3dc8efb65053107`。
§11.4 引用的函数编号和 helper 数来自此前 `const_shift_part3_v2` 的静态扫描，
不能直接当成 v3 的对应函数。Verilator 会因生成结构变化重新编号函数。

§11.1 的适用边界需更正：同一个 write operation 内的纯动态地址并不阻止连续
mask run 合并；禁止的是跨 operation / 不同地址表达式 / 有副作用的合并。
跨出常量 shift source 的 run 也不必逐 bit 回退：有可用 data identifier 时保留
`data[high:low]`，只有无法安全生成该 slice 时才走逐 bit 路径。
§11.3 的 C=100 是初始化 smoke，通过 runtime 和签名校验；实际 guest 指令的
Difftest 覆盖来自 C=30000，不能将两者的验证深度混为一谈。

本轮补充的 [v3 构建对照审计](../../build/repcut_cost_model_20260922/memory_slice_part3_v3/build-fairness-audit.json)
通过：两臂固定 assignment、工具链、runtime、wrapper `-O3`、model fast `-Os`
和 slow 无显式 `-O`；32 个 model 都有独立的新 object/archive，不复用旧模型。

### 12.2 PMU 与生成机器码的对应

在 node030 CPU96–127、K=N=32、all-spin、C=30000 下完成两轮 `cycles:u` 99 Hz
callgraph 采样，筛选 CPU99 的 part_3 worker。二进制前后 SHA 一致，Difftest 和
60102 steps 签名通过。得到 1590 个 model 样本，按 perf period 加权；忙等待和
update wrapper 另列，不计入下表分母。采样运行时间只用于诊断，不作为 AB 收益。

| 当前 v3 函数 | model cycle 样本占比 | 生成代码 / 机器码证据 |
| --- | ---: | --- |
| `nba_sequent TOP14` | 5.80% | 1639 个 BusPMU latencyRecord 短 if 块；79.32% 本函数样本落在 `je` |
| `nba_sequent TOP6` | 5.48% | 大量 L3 refillBuffer 单 bit commit；98.86% 本函数样本落在 `je` |
| `ico_sequent TOP0` | 5.42% | 384 个 REDXOR32 文本调用，303 个重复参数表达式；编译后有 52 条标量 `setp/setnp` |
| `ico_sequent TOP8` | 4.46% | 40 个 COUNTONES 都处理 2-bit 输入；本函数样本主要是搬移、掩码、移位等 |
| `nba_sequent TOP4` | 3.83% | 360 个 REDXOR32，但还有 659 个 logEndpoint counter 短 if 块；样本主要是 `or/mov` |
| `nba_comb TOP8` | 2.77% | 22 个 REDXOR 文本调用；44 个样本只有 1 个在标量 parity 指令 ±64 bytes 内 |
| `nba_sequent TOP5` | 1.45% | 264 个 REDXOR32；样本主要落在条件检查及分支 |

这些比例属于整个函数，不是 ECC、BusPMU 或 memory 子逻辑的精确时间。
分支指令上样本多，也不能直接解释成 branch misprediction：普通 cycles 采样
存在 skid，前端停顿也可能反映在分支位置。parity 指令邻域只用于筛查，不能覆盖
向量化 parity，也不能由“未采到”证明成本为零。

整体 model 周期样本为 ico 42.46%、nba sequent 39.62%、nba comb 17.55%、
调度及其他 0.38%；前 5 / 10 / 20 个函数分别占 25.37% / 42.18% / 66.09%。
因此当前成本分布较散，不是一个孤立 reduction helper 占据大头。

另做两轮 CPU99 user-space 整段 `perf stat`：IPC 为 1.0074 / 1.0041，
`de_no_dispatch_per_slot.no_ops_from_frontend / (6 * cycles)` 为
48.88% / 48.84%；指令缓存 miss/access 为 39.24% / 39.27%。计数器 multiplex
running 比例均约 83%。这组统计包含 startup、eval、update 和 all-spin 等待，
不是纯 eval 的前端停顿比例；仅支持进一步检查机器码体积和取指成本，不能据此
断言减小函数一定提速。

原始证据：
[v3 profile](../../build/repcut_cost_model_20260922/hotspots_memory_slice_part3/manifest.json)、
[profile 汇总](../../build/repcut_cost_model_20260922/hotspots_memory_slice_part3/analysis.json)、
[机器码与源代码审计](../../build/repcut_cost_model_20260922/reduction_dynamic_v3.json)、
[整段 PMU 计数](../../build/repcut_cost_model_20260922/hotspots_memory_slice_part3/frontend_valid/manifest.json)。

### 12.3 实际功能与后续候选

1. **ECC 编码与检查。** L2 `Directory.scala` 的 `dataCode.encode(tag)` 生成 tag
   校验位；L3 `BaseDirectory.scala` 的 `tagCode.decode(ecc ## tag).error` 检查
   每路 tag。它们属于正常硬件功能。Clang 已合并许多重复 parity，还会自动
   向量化；静态 `VL_REDXOR` 次数不能直接用作可消除的动态工作量。
2. **MSHR 占用计数。** `MSHRCtl.scala` 的完整 `PopCount` 经 Chisel 加法树、
   Verilator 局部识别后，变成八个 2-bit countones 再相加。机器码确实还保留
   这种局部展开，但本轮没有证据说明它占据主要时间。把完整 bit-sum tree
   恢复为一次计数是独立候选；通用 emitter 不能直接用 `$countones` 替代，
   因为原加法遇 X/Z 传播未知，而 `$countones` 只统计确定为 1 的位。
3. **refillBuffer 的重复提交条件。** 一个 beat selector 被复制成 257-bit mask，
   最终却成为许多不同 operation 的单 bit 写入。`nba TOP6` 热点可回溯到
   `slices_2.refillBuffer.Memory__v347` 等 commit guard。下一步应证明相邻写入
   的 guard、address、event、priority 等价，再归一化为整段写入。这超出 §11
   “同一 operation 内合并”的范围，适合独立 normalization / transform，不能
   仅凭 SV 名称相近做合并。
4. **BusPMU 动态索引寄存器表。** `BusPerfMonitor.scala:119` 使用
   `RegInit(VecInit(...RecordEntry))`；动态 source 索引写 timestamp/reqType，
   被展开为每个 entry 的条件赋值。可探索保留 indexed storage 或共享外层
   enable。必须保留复位、同周期读写及 assert 语义，不能直接删掉统计功能。

下一步优先评估第 3 项；第 4 项可作为单独的结构实验。修改权重时应分别考虑
实际保留的 guard/commit 数、标量与宽位向量搬移、以及后端消除后的归约规模，
而不是继续直接增加原始 reduction node 的统一系数。

### 12.4 通用 memory-write 合并变换：先做结构门，再做全量生成（2026-09-22）

本轮将 refillBuffer 的逐 bit 提交抽象为一个与模块、变量名无关的 GRH
变换 `memory-write-coalesce`。它只在同一 memory 的写端口满足以下结构条件时
合并：enable 经过位路由后等价，address 相同，event 操作数和边沿完全相同，
所有写 mask 是已知常量且全局互不重叠，并且 memory 没有 fill、priority 或其他
未知写者。数据通过 slice/concat 重建，不使用 masked-OR，因此保留 X/Z；DPI、
instance、system function 和未知属性均拒绝。ingest 添加的 `svPackedArray.*`
只是布局提示，已按精确白名单作为无副作用元数据接受，不能凭模块或变量名命中。

实现位于 `wolvrix/lib/transform/memory_write_coalesce.cpp`，使用方式和保守边界
已补入 `wolvrix/docs/transform/memory-write-coalesce.md`，测试覆盖多种宽度、四态
enable/data、稀疏 mask、左/右/超宽常量移位、带布局元数据的 concat、幂等性和
不安全输入拒绝。

小型验证已完成：生成的合并前后 Verilog 经过 Verilator 运行 10000 个随机周期，
并与软件参考 memory 比较，包含 read-before-write/NBA 场景，所有 4 行、70 位数据
一致。

冻结的香山分区 IR 首轮诊断如下：

| graph | 写端口前 | 写端口后 | 合并组 | 移除端口 | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| `part_3` | 2641 | 601 | 8 | 2040 | refillBuffer 的 4 个 514-bit memory 均被结构规则覆盖 |
| `part_0` | 240 | 232 | 8 | 8 | 同类但规模较小 |
| 其他可见 memory | 24--769 | 不变 | 0 | 0 | 未满足安全条件，或存在 mask overlap |

该统计只说明生成 IR 的提交点减少，不等价于 walltime 收益；必须完成独立的
全量 Verilator 编译、功能检查和 node030 上的 AB/BA 运行后再保留性能结论。全量
生成期间固定输入、emitter、运行时和通信包装器，后续将以 `memory_slice_part3_v3`
作为基线比较。

### 12.5 全量构建与 C=30000 AB/BA 结果（2026-09-22）

候选在 node030 的 CPU96--127 上完成 32 个分区的独立 Verilator/C++ 编译，构建
manifest、独立对象审计和功能签名均通过。生成 C++ 总字节数从基线的
2,720,117,407 降到 2,713,773,424，减少 6,343,983 字节（约 0.23%）；其中
`part_3` 从 156,601,307 降到 150,272,896 字节（约 4.04%）。

在 C=30000、K=N=32、all-spin、8 对交错 AB/BA 的完整运行中，16 个长跑全部通过
difftest，候选每一对均胜出：

| 指标 | 基线中位数 | 候选中位数 | 配对中位数变化 |
| --- | ---: | ---: | ---: |
| Host | 10.1675 s | 9.4040 s | -7.34% |
| walltime | 10.2700 s | 9.5050 s | -7.27% |
| step | 9.9043 s | 9.1336 s | -7.61% |
| 总 eval | 132.1545 us | 119.2705 us | -9.68% |
| 最大分区 eval | 129.2440 us | 114.7390 us | -11.28% |
| update | 28.4060 us | 28.4565 us | +0.35% |

`part_3` 的平均 eval 从 129.29 us 降到 114.42 us，平均 update 从 10.92 us
变为 10.99 us；通信 assignment、逻辑位和 storage bytes 与基线逐项相同。因此
这次收益与预期机制一致：减少宽 memory staging/commit 的 eval 工作，而不是减少
跨分区通信或 update barrier。实验产物保存在
`build/repcut_cost_model_20260922/memory_coalesce_v5` 和
`build/repcut_cost_model_20260922/interleave8_memory_coalesce_v5_c30000`。

当前结论：该结构规则已显示出稳定且可复现的 XiangShan 收益，但它仍是显式实验
pass，并未改变默认生成 pipeline；后续如纳入默认流程，应先在第二个 workload 或
其他 simulator backend 上复用同一结构门和四态测试，再决定默认启用。

### 12.6 V5 残余热点重采样与下一候选（2026-09-23）

本轮不修改并行进行的 backend-lowered cost manifest 工作，也不重新划分。
固定 `memory_coalesce_v5` 的 ELF，SHA256 为
`f3884e92336848b548b85f58f67f2128fe245113ad890991f27651e8316ee1a9`。
`node030`、CPU96–127、NUMA1、K=N=32、默认 all-spin、fixed-ASLR、C=30000。
先复核 `hotspots_memory_coalesce_v5_part3` 的两轮 99 Hz callgraph，
再在 `hotspots_memory_coalesce_v5_leaf` 补两轮 CPU99 的 997 Hz leaf-IP 采样。
后两轮均通过 difftest，签名同为 PC `0x80000442`、instructions `27809`、
cycles `29996`、guest cycles `30001`、steps `60102`；运行前后 ELF 身份一致。
带采样运行只作诊断，不与历史无采样 walltime 比较。

997 Hz 两轮共有 11,145 个直接落在 `part_3` 模型符号内的样本；按采样 period
加权，`ico_sequent` 为 46.57%、`nba_sequent` 为 31.98%、`nba_comb` 为 21.16%。
最大单函数是 `ico TOP0`（6.20%），其次 `ico TOP10`（5.26%）、`nba TOP12`
（4.87%）、`ico TOP8`（4.70%）。不再是一个宽移位 helper 主导。

以生成 C++、同一 ELF 的反汇编、Clang record layout 和 SV 数据依赖交叉定位：

| 残余区域 | run01 模型采样占比 | run02 模型采样占比 | 合并占比 | 机制证据 |
| --- | ---: | ---: | ---: | --- |
| decoded register table 的逐项提交 | 3.49% | 3.79% | 3.63% | `nba TOP12` 中 1024 个 timestamp 和 1024 个 reqType 写目标；相关 store 跨度 53,975 字节机器码。 |
| 上述表的 packed 候选数据计算 | 2.35% | 2.09% | 2.22% | `ico TOP12` 中 128 个 packed 数组、2304 个 32-bit word 赋值，合计 9 KiB 候选数据；相关 store 跨度 82,827 字节机器码。 |
| 宽 packed 表物化后动态选一项 | 0.70% | 0.65% | 0.68% | `ico TOP0` 物化 768-word 数组，`ico TOP2` 按 `index * 48` 选 48 bit；当前优先级低于前两项。 |

前两行在本设计对应 `BusPerfMonitor.scala:119–135` 的
`RegInit(VecInit(...RecordEntry))`：以请求 source 索引写 timestamp/reqType，
而仿真代码先为全表准备带 reset/enable 的候选数据，再逐项检查更新条件。
SV 中还能看到 `comb-lane-pack` 将多个 lane 的 mux 展开为宽 `and/or/not`
与拼接；`comb_lane_pack.cpp` 的 `PackedBuilder::build` 对 `kMux` 正是这种处理。
这为“源码上只改一项，但 eval 中先算全表”提供了具体解释，不能仅以 C++
文本重复次数推断所有重复表达式都保留到了机器码。

**选择下一项通用候选：guarded register-write 的 lane-local 数据恢复。**
先从已打包的纯 bitwise/concat/replicate 数据闭包中，仅恢复实际 write sink
所消费的静态切片，使各寄存器的数据表达式独立并可由后端下沉到各自写条件中。
例如宽 `packed = {d1,d0} & {{W{g1}},{W{g0}}}` 的写入者只需要第 0 lane 时，
其数据可表示为 `d0 & {W{g0}}`，不必物化完整 packed 结果。
匹配依据为操作类型、位宽、静态切片和 use-def 关系，不匹配 BusPMU、模块名或变量名。

第一阶段只验证该局部结构规则能否减少实际 eager data 计算：保留现有分区、
寄存器集合、写使能、事件、mask、优先级和通信；shared/external users 不能被
误删，DPI/副作用闭包不得内联，不能把四态 bitwise 语义未经证明地改成二态选择。
若生成机器码仍在无条件计算，应停止把“源码变短”视为收益，再评估
decoded register table 恢复为 indexed storage；后者需要额外验证复位、
同周期读写、多写优先级以及对 ASC/分区边界的影响。

前两区域合计约 5.85% 是**本轮 part_3 模型采样的归因**，不是已实现的优化，
不是可全部消除的成本，也不是 walltime 收益预测。leaf 分母排除了 runtime
spin/update wrapper，但不能无 callchain 地归属共享 helper；范围边界有采样
skid，并包含初始化阶段。下一候选仍需独立四态/结构门、生成机器码门和
相同 V5 baseline 的无采样交错 AB/BA，当前没有新的性能提升结论。

复现脚本和明细位于 `build/repcut_cost_model_20260922/`：
`profile_v5_residual_leaf.py`、`analyze_v5_residual_leaf.py`、
`hotspots_memory_coalesce_v5_leaf/{manifest,analysis}.json`。

### 12.7 Indexed register table 候选及 V5 复测（2026-09-23）

§12.6 原先提出 lane-local packed data recovery；实际执行时根据 profile 中更大的
逐项 table commit 占比（3.63%，packed candidate data 为 2.22%），改选已有的通用
`reg-to-mem` 结构 pass：在冻结的
`memory_coalesce_v5` 分区图上，仅对 profile 选中的 `part_3` 恢复可静态识别的
寄存器组为 indexed storage。候选由操作类型、位宽、地址/写条件和 use-def 结构识别，
不依赖模块名或信号名；本图识别出 32 组、共 2,784 个寄存器成员，另有 371 个
候选因结构条件不满足而跳过。该 pass 覆盖 decoded table，也触及多个 L2 table，
因此不是 BusPMU 专用改写。

先以独立小型 Verilator probe 检查 64/8-bit 字段、全行读写、异步复位、禁用写、
越界地址以及旧/新值行为，10,000 cycles 通过。此 probe 是二态验证，不是四态等价
证明。随后用同一个冻结 workload 做全量构建：32 个模型档案、1,323 个对象全部新编译；
65 个分区 SV 文件中只有 `SimTop_repcut_part3.sv` 内容变化，runtime wrappers、
分区 assignment 和 update 通信均保持原样。整包生成 SV 从 1,316,619,889 降至
1,315,611,964 bytes（−1,007,925）；独立 part_3 codegen 审计中 C++ 源码总量从
150,272,896 降至 134,093,424 bytes（约 −10.77%），fast 源码从 96,919,315 降至
87,044,097 bytes（约 −10.19%）。

在 `node030` CPU96–127、NUMA1、K=N=32、默认 all-spin、fixed-ASLR 和 C=30000 下，
完成 8 对无采样 AB/BA 交错测试。每次都启用 Difftest，guest 签名一致；候选 8/8 胜出。
下表中的变化为逐对百分比中位数；A 为原 `memory_coalesce_v5`，B 为仅对 part_3
应用 `reg-to-mem` 的候选。

| 指标 | A 中位数 | B 中位数 | 配对变化 | B 获胜数 |
| --- | ---: | ---: | ---: | ---: |
| Host time (s) | 7.514 | 7.036 | −6.284% | 8/8 |
| wall elapsed (s) | 7.600 | 7.115 | −6.254% | 8/8 |
| 全局 eval (us/step) | 94.534 | 86.469 | −8.552% | 8/8 |
| 最大 part eval (us/step) | 92.590 | 75.622 | −18.335% | 8/8 |
| 分区 eval 总和 (us/step) | 1242.890 | 1220.871 | −1.772% | 8/8 |
| 全局 update (us/step) | 23.304 | 23.286 | +0.189% | 3/8 |

通信完全不变：每步 5,286 assignments、3,640,312 logical bits、460,647 storage
bytes。最大分区仍为 part_3；收益主要来自降低该串行关键路径的 eval 工作，而不是
减少跨分区传输。由此，这个通用 pass 在本 workload 上从代码规模和实际 walltime 两边
都通过了探索性验证，但尚未证明对其他 workload、其他 simulator 或四态语义普遍成立，
因此仍保持显式实验候选，不加入默认 pipeline。

候选的 997 Hz leaf profile 两轮均通过 Difftest，丢样检查为零。sampled `part_3`
热点现已分散：`ico_sequent` 约 49.72%、`nba_sequent` 约 29.12%、`nba_comb` 约
20.93%；最大候选函数约 7.07%，随后约 6.00% 和 5.90%。符号名只能近似归因，变换后
不能把旧 IP 地址直接映射到新代码。当前证据只说明逐项提交热点已经退居次位，剩余
成本转向多个组合求值区域；下一轮应对这些实际热点的生成结构继续筛查通用模式，不能
以 TOP 编号、模块名或信号名作为 pass 条件。采样为诊断运行，包含启动阶段，不替代
无采样 walltime 测试。

相关复现数据位于 `build/repcut_cost_model_20260922/`：
`memory_coalesce_v5_regtable_part3_v2/run.json`、
`memory_coalesce_v5_regtable_part3_v2/build/build-manifest.json`、
`interleave8_v5_regtable_part3_c30000/summary.json`、
`hotspots_memory_coalesce_v5_part3/reg_table_probe/{validation,summary}.json` 和
`hotspots_v5_regtable_part3/{manifest,analysis}.json`。backend-lowered cost manifest
并行工作未修改。

### 12.8 高写端口 indexed table 的代码膨胀及通用门控（2026-09-23）

核对此前全图 `reg-to-mem` 探索产物后，`part_28` 的 SV 从基线 30,398,017 bytes
增至 115,581,285 bytes（+85,183,268，约 3.80 倍）。根因不是 table 有很多状态：
该处 Difftest rename table 只有 32 项、每项 8 bit。Chisel 在
`testcase/xiangshan/src/main/scala/xiangshan/backend/rename/RenameTable.scala:186–194`
对其做 `RegInit(Vec)`、`WireDefault`，并按循环顺序对 `w.addr` 做条件动态写；
输入写口规模由 `RabCommitWidth * MaxUopSize` 决定（同文件第 254–258 行）。当前
生成图中有 511 个有效 `diffWritePorts`（编号 0–510），每个写口都携带独立 enable、
地址和数据。把 32 个标量寄存器恢复为一个动态索引 memory 后，Verilator 前的 SV
必须表示大量“哪个写口命中哪一行”及多个同周期写入的顺序/优先级；一个地址网
`io_diffWritePorts_510_addr` 在该分区 SV 中由 34 次引用增至 545 次。这与“写端口数
远大于表深度”导致的索引/优先级展开相符。表里只有 256 bit 状态，膨胀来自更新逻辑
形状，不是存储容量。

需要区分中间 SV、Verilator 生成 C++ 和最终运行时间。之前把 part_28 Verilator
输出目录的文件总量误记成 `.cpp` 源码量；按完整构建中实际 `.cpp` 文件重算，基线
为 31 个文件、56,931,959 bytes，全图候选为 37 个文件、108,832,701 bytes（约
1.91 倍）。不过 32 个分区的 `.cpp` 总量从 2,713,773,424 降到 2,707,497,750
bytes，且最终全图候选的 C=30000 Host/walltime 更快（见 §12.9）。所以 part_28
的 SV/C++ 膨胀本身不是 walltime 的否决条件，但仍需记录，因为它会影响生成、编译
时间和资源；是否采用最终由端到端仿真结果决定。

最终方案不能按 `part_3`、`part_28` 或 RTL 名称人工开关。part_3-only 是为了建立
profile 目标的隔离 A/B 因果证据，不是可接受的产品选择方式。后续应让 pass 自动扫描
所有寄存器组，按结构估算转换成本/收益，例如表深度、读端口数、独立写端口数、数据
位宽和写优先级链；高 fan-in、预估 lowering 膨胀的候选自动保留原表示，低成本且能
减少实际生成工作的候选才应用。另一条通用路线是把同周期多写口以紧凑循环或分组的
方式降低，同时严格保持端口顺序（同址时后写覆盖前写）、旧值读语义和 reset 行为。
两条路线都要按 simulator backend 分别建成本估计，并通过冲突地址、enable、reset、
X/Z、同周期读写的语义测试；不能把简单增加 SV/C++ 行数当成 Host 结论。

复核数据在 `build/repcut_cost_model_20260922/memory_coalesce_v5_regtable/`：
`run.json`、`package/sv/SimTop_repcut_part28.sv`；完整构建源码在
`memory_coalesce_v5_regtable_resume/build/package/build/verilated/part_28/`，基线源码在
`memory_coalesce_v5/build/package/build/verilated/part_28/`。本候选仍是显式实验产物，
尚未加入默认 pipeline。

### 12.9 全图 reg-to-mem 的 C=30000 walltime 复测（2026-09-23）

用户指出最终应比较 walltime、而非用 SV 体积预先否决候选，因此在同一冻结 V5
分区上复测：基线为 `memory_coalesce_v5`；候选先保持 V5 的
`memory-write-coalesce`，再对全部 33 个 graph 无名称过滤地运行
`reg-to-mem(intent=false)`。pass 报告 375 个转换组，最终有 12 个分区顶层 SV
文件变化；这是结构规则扫描后的自然命中集合，不是手工挑选分区或信号。两边同用
32 partitions / 32 threads、all-spin、C=30000、node030 CPU96–127 和 NUMA node 1。

候选完整重编审计通过：32 个分区 archive、1,313 个分区对象，复用对象为 0；C=100
smoke 及 16 个 C=30000 Difftest 样本全部通过，输入哈希未变。8 组 AB/BA 配对中
候选 8/8 胜出：

| 指标 | V5 中位数 | 全图 reg-to-mem 中位数 | 配对变化 |
| --- | ---: | ---: | ---: |
| Host time | 7.676 s | 6.682 s | -12.14% |
| wall elapsed | 7.760 s | 6.775 s | -11.96% |
| 全局 eval | 97.014 us/step | 81.319 us/step | -15.22% |
| 最大分区 eval | 95.019 us/step | 77.027 us/step | -18.42% |
| 分区 eval 总和 | 1,254.067 us/step | 1,185.283 us/step | -4.85% |
| 全局 update | 23.469 us/step | 23.628 us/step | +0.36% |

静态跨分区通信保持完全一致：5,286 assignments、3,640,312 logical bits、
460,647 bytes。最终二进制为 252,396,376 -> 247,518,744 bytes；干净构建时间
为 167.85 -> 176.50 s。端到端结果说明这次全图转换确实减少了运行时工作，且收益并非
由分区或通信变化带来；part_28 尽管局部生成 C++ 变大，最终 walltime 仍显著改善。
该轮实验没有做外部负载门槛筛选，保留全部通过功能校验的配对样本。

产物：`build/repcut_cost_model_20260922/memory_coalesce_v5_regtable/run.json`、
`memory_coalesce_v5_regtable_resume/build/build-manifest.json`、
`interleave8_global_regtable_c30000_node030/{manifest,summary.json,runs.csv,parts.csv}`。
这是 walltime 探索结果，不代表已决定启用默认 pipeline；后续仍应在第二个 workload
验证功能与收益，并评估高写端口模式带来的编译代价。

### 12.10 Baseline / V5 / 全图 reg-to-mem 三组时空图（2026-09-23）

将首次优化前 baseline、V5-only 与全图 `reg-to-mem` 三组单步分区时间放在同一个
共享横轴的交互图中。pre-V5 baseline 使用 `interleave8_const_shift_c30000` 的
baseline arm；V5-only 与全图候选分别使用最新全图 AB/BA 批次的 baseline/candidate
arm，因此 V5 -> 全图对照直接对应本轮配对实验（walltime -11.96%）。pre-V5 baseline
是较早批次的历史锚点，不是同批三臂实验，不能据它和后两组的跨批次绝对值计算单独的
paired 收益。各臂取 8 次成功运行中每个线程每步均值的中位数。此图是阶段时间重建，
不是事件级 trace；灰色表示未按线程展开的阶段余量，不表示 CPU idle。

- [离线交互式 HTML 时空图](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline/three_stage_timeline.html)
- [SVG 静态图](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline/three_stage_timeline.svg)
- [聚合数据及输入 SHA-256](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline/data.json)
- [每分区明细 CSV](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline/part_durations.csv)
- [生成脚本](../../build/repcut_cost_model_20260922/make_three_stage_v5_global_regtable_timeline.py)

**增量更新（2026-09-24）：HTML 主题与交互对齐。** 三组图对齐既有四组图的浅色
卡片布局、阶段配色、指标卡和 Host lane9 / CPU105 高亮，补齐最长 callback 红框、
最大原始静态权重标记、关键线程筛选、详情悬停/点击固定、完整分区明细、CSV 导出、
1×/2×/4× 缩放与复位。关键线程取当前显示组的并集，所有面板继续共用横轴；内嵌
中文字形以支持离线打开。实测整步中位数、阶段和、历史静态权重及同批 paired 收益
分开标注，未重新仿真，原有三组阶段与分区中位数逐项核对不变。
浏览器检查覆盖 7 种组选择 × 3 个阶段、96 条分区数据、排序/筛选、键盘和点击详情、
CSV 导出及桌面/手机布局；无 JavaScript 错误、无外部网络请求。复验脚本：
[test_three_stage_theme_browser.py](../../build/repcut_cost_model_20260922/test_three_stage_theme_browser.py)。

## 13. 权重与 eval 相关性差的原因及改进路径（2026-09-22）

### 13.1 先区分三个不同问题

当前 `estimated_node_weight_sum` 的定义是分区重建前、Phase A 原始节点的静态
操作成本求和；`eval` 则是重建后 Verilator 模型在当前 guest 区间内执行一整个
step 的时间。两者不是同一个层次的量。当前 candidate 的 C=30000 数据为
Pearson/Spearman = 0.7224/0.4824，去掉 `part_3` 后 Pearson 只有 0.2855；这
说明全体 Pearson 主要回答“最大的分区也确实很大”，不能回答其余分区谁更慢。

还需要把以下两个目标分开：

1. **提高相关性**：让一个成本模型能解释、排序和预测各分区的 eval，便于诊断
   和指导重新划分。
2. **降低 walltime**：直接降低 `max(eval_i + barrier/update_i)`，同时不让通信
   和 update 成本失控。相关性高是有用的证据，但不是 walltime 的充分条件。

### 13.2 为什么原始权重会漏报 `part_26/11/7`

当前数据中实际 eval 前四是 `part_3/26/11/7`，权重前四是 `part_3/6/10/18`，
只命中一个分区；`part_6` 权重第二但 eval 排名第 9，而 `part_26`、`part_11`、
`part_7` 的权重排名分别为 17、13、14。这不是某个分区的偶然噪声，而是模型
遗漏了以下成本：

1. **重建和后端 lowering**：边界适配、port、closure 复制，以及一个 RTL 操作
   最终变成多少个 NBA、guard、临时值、数组索引和 helper 调用，都发生在原始
   权重统计之后。memory staging 的实验已经直接证明：权重不变，后端代码和
   eval 仍可下降。
2. **动态激活率**：静态模型默认所有操作每步以同样代价发生；实际 eval block 的
   guard、clock enable、事件路径和状态依赖会使不同分区的有效工作量不同。当前
   只测一个 guest 区间，不能把某一段的活动率误认为 RTL 固有成本。
3. **代码形状和固定成本**：`ico/nba_comb/nba_sequent` 函数数量、分支、代码布局、
   指令/数据 cache，以及每步的函数调度和 barrier，无法由操作数和平均位宽唯一
   推出。`part_3` 的 PMU 采样显示热点分散在多个函数，而不是一个 reduction helper
   可以解释全部时间。
4. **目标混合**：`hyper_partition_weight` 是共享 ASC/边界工作均摊后的求解器
   负载；它有利于求解器分配共享工作，却不是某个 worker 的完整 eval 成本，因而
   不能用来排序线程运行时间。

### 13.3 推荐的成本模型分层

不要继续给 `kReduceXor`、`kMemoryWritePort` 等原始 op 统一加系数，而应保留
仿真器后端独立的成本模型，并按以下顺序增加信息：

1. **Backend-lowered static cost**：在 emitter 生成代码时同步输出 per-part
   manifest，统计实际 lowering 后的 limb operation、memory write segment/bit、
   reduction/popcount、guard/branch、动态索引、NBA/临时值数量，以及 eval block
   数量和代码体积代理。这个阶段不需要完整编译，也不需要运行 guest。
2. **Rebuilt-graph accounting**：若使用图上的成本，必须在 graph reconstruction
   后重新计价，把边界适配和 closure 复制纳入；原始 Phase-A 权重只保留为求解器
   的粗粒度先验。
3. **Activity calibration**：用短 trace（例如 C=10000）记录 eval block/guard
   的执行或有效更新率，并把成本写成“静态 lowered work × activity + 固定函数/分支
   项”。startup、eval、update 分开校准，避免把一次性初始化混入每步成本。
4. **Backend-specific fitting**：Verilator、gsim、grhsim 使用各自的特征和系数；
   XiangShan 的拟合只能作为训练样本，必须用第二个 workload 或时间区间做留一
   验证，防止把 `part_3` 的形状过拟合成通用规则。

### 13.4 如何把模型用于重新划分

`hyper_partition_weight` 应继续作为共享边/通信的约束或惩罚项，不能直接替代
线程 eval 预测。更实际的流程是：

```text
粗粒度静态分区
    -> 生成 lowered-cost manifest
    -> 预测每个 part 的 eval cost
    -> 只对最大/尾部 part 做 ASC 或允许的局部迁移
    -> 重新检查 max eval、p95 eval、通信和 update
```

优化目标应优先最小化 `max_i(eval_i + barrier/update_i)`，再在通信预算内降低
尾部方差；不应只最小化 Pearson 或平均权重。第一阶段可以完全离线，用已有
`part_3`、`part_26`、`part_11`、`part_7` 的静态生成特征和 C=30000 eval 做
回归/排序对照；只有当 lowered-cost 对去 `part_3` 的相关性明显优于 0.29、并且
top-4 命中率改善后，才值得把它接入 solver 的局部 refine。之后再用短 trace 做
activity 校准，最后以交错 AB/BA 长跑验证 walltime。

本节结论是：当前问题首先是**计价口径和执行口径错位**，其次才是系数没有调好。
下一项应先实现“重建后 backend cost manifest + 离线相关性对照”，暂不改变默认
分区算法；这样可以独立判断静态后端特征能解释多少 `part_26/11/7` 的漏报，再决定
是否需要 profile-guided 局部重划分。相关原始数据见
[`interleave8_const_shift_c30000/partition_analysis`](../../build/repcut_cost_model_20260922/interleave8_const_shift_c30000/partition_analysis/summary.json)、
[`reduction_dynamic_v3.json`](../../build/repcut_cost_model_20260922/reduction_dynamic_v3.json)
和 [`memory_slice_part3_v3`](../../build/repcut_cost_model_20260922/memory_slice_part3_v3/build-fairness-audit.json)。

### 13.5 manifest 的时机和用途澄清

“backend-lowered”不是指必须等完整 Verilator C++ 编译完成。应区分四个时机：

| 层次 | 产生时机 | 能看到什么 | 对分区的作用 |
| --- | --- | --- | --- |
| A. graph cost | 初始求解前 | 原始操作、位宽、fanout | 快速得到第一版 assignment |
| B. emitter manifest | assignment 后、生成 SV 时 | 实际 NBA、memory segment、guard、动态索引、reduction/helper 和 eval block 代理 | 对当前 assignment 做静态评分，并驱动局部 re-cut |
| C. Verilator C++ manifest | `verilator --cc` 后、编译前或编译后 | C++ 函数、行数、`.text`、临时变量和更准确的代码体积 | 校准 B 的系数，定位后端代码形状问题 |
| D. runtime profile | 短跑或长跑时 | 实际 activity、cycles、cache/branch 和每 step 时间 | 校准动态项，并验证最终 walltime |

因此，若只做一次分区、等 C 层生成完再结束，manifest 的确只能用于解释结果；这
不是期望的最终流程。实际应采用一到两轮反馈：

```text
原始图粗分区
  -> B 层 emitter manifest
  -> 预测每个 part 的 eval cost
  -> 只移动 part_3 等尾部中的候选 ASC
  -> 重新生成受影响分区并检查通信
  -> 必要时用 C/D 层校准后再定稿
```

B 层通常可以在 `system_verilog.cpp` 输出 SV 的同时统计，不需要完整链接和长时间
仿真；C 层只需对少量候选 assignment 做一次，用来校准 B 层，而不是让 solver 为
每次尝试都完整编译。需要注意，ASC 移动可能改变边界、guard 合并和 memory staging，
所以受影响分区必须重新生成 manifest，不能简单把旧分区成本线性相加。

如果最终不采用反馈式 re-cut，B/C 层仍有两个实际用途：验证当前权重是否漏掉了
`part_26/11/7` 这类尾部，以及训练下一轮通用的 backend cost 模型；但它们不会
自动改变已经完成的 assignment。

### 13.6 四阶段单步仿真时空图（2026-09-22）

为直观看出三次连续后端优化的阶段工作量，按“第一次优化的 baseline + 后续三次优化”
固定四个版本：

| 阶段 | 实验来源 | 版本含义 |
| --- | --- | --- |
| 第一次优化 baseline | `interleave8_const_shift_c30000` / `baseline` | `shift_low_bit_v1` |
| 优化 1 | `interleave8_const_shift_c30000` / `candidate` | `const_shift_part3_v2` |
| 优化 2 | `interleave8_memory_slice_c30000` / `candidate` | `memory_slice_part3_v3` |
| 优化 3 | `interleave8_memory_coalesce_v5_c30000` / `candidate` | `memory_coalesce_v5` |

四组数据均为 C=30000、K=N=32、all-spin、node030 CPU96--127；每个相邻版本使用
8 对 AB/BA，图中每个阶段和分区取这 8 次运行均值的中位数。结果如下：

| 阶段 | Host | walltime | eval | update | 阶段和 | 同批 paired wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `shift_low_bit_v1` | 11.1740 s | 11.280 s | 148.8425 us | 28.5410 us | 181.5900 us | -- |
| `const_shift_part3_v2` | 10.5535 s | 10.660 s | 138.3970 us | 28.4635 us | 171.0645 us | -5.41% |
| `memory_slice_part3_v3` | 10.4255 s | 10.525 s | 136.1575 us | 28.6125 us | 169.1575 us | -0.66% |
| `memory_coalesce_v5` | 9.4040 s | 9.505 s | 119.2705 us | 28.4565 us | 152.0585 us | -7.27% |

相对第一次优化 baseline、按四个版本跨批次中位数计算，三次优化后的 walltime 分别为
`-5.50%`、`-6.69%`、`-15.74%`，eval 分别为 `-7.02%`、`-8.52%`、`-19.87%`；
update 基本不变。若看每个相邻实验批次内的 paired AB/BA 结果，则三轮 walltime
收益分别是 `-5.41%`、`-0.66%`、`-7.27%`。因此 `memory_coalesce_v5` 并非只有
约 1% 的收益：图中的 `-9.69%` 是两个不同批次中位数的跨批次差，正式的同批对照
数字是 `-7.27%`。HTML 和 PNG 面板同时显示这两种口径。

百分比的精确定义为：对每一对交错运行先计算
`delta_i = 100 * (candidate_i / baseline_i - 1)`，其中 `i` 是同一个 `pair01`--
`pair08`，再对 8 个 `delta_i` 取中位数；负数表示候选更快。以
`memory_coalesce_v5` 为例，8 对 walltime 的 delta 为
`-7.150%、-9.241%、-6.564%、-7.122%、-7.227%、-8.301%、-7.819%、-7.310%`，
中位数是 `-7.268%`，四舍五入为 `-7.27%`。若先取两侧中位数再相除，则是
`100 * (9.505 / 10.270 - 1) = -7.449%`，四舍五入为 `-7.45%`；这是
“中位数之比”，不是本记录采用的 paired 中位数，不能将两者混写。
这张图是按阶段中位数重建的相位对齐图，不是逐事件 trace：灰色部分表示尚未细分的
等待/派发/同步等阶段，不能解释成 CPU 空闲。四个版本共用同一冻结的 32 分区 assignment，
静态权重标记来自第一次优化前的分区分析。四个版本来自三个相邻 AB/BA 对照批次，
不是一次四臂同时运行；因此图用于展示阶段工作量和版本演进，不替代同一批次的 paired
显著性检验。

图表和可复核数据：

- [PNG 时空图](../../build/repcut_cost_model_20260922/four_stage_timeline/four_stage_timeline.png)
- [SVG 时空图](../../build/repcut_cost_model_20260922/four_stage_timeline/four_stage_timeline.svg)
- [交互式 HTML](../../build/repcut_cost_model_20260922/four_stage_timeline/four_stage_timeline.html)
- [分区阶段明细 CSV](../../build/repcut_cost_model_20260922/four_stage_timeline/four_stage_part_durations.csv)
- [完整 JSON 数据及来源 SHA](../../build/repcut_cost_model_20260922/four_stage_timeline/four_stage_timeline_data.json)
- [生成脚本](../../build/repcut_cost_model_20260922/four_stage_timeline.py)

### 12.11 三组数据同批重跑（2026-09-24）

为排除旧批次和二元 AB/BA 先后顺序对三组图的影响，在 node030 CPU96--127、NUMA1、
K=N=32、all-spin、C=30000 上，对 pre-V5 baseline、V5-only、全图 reg-to-mem
执行 12 轮三臂交错运行。每轮使用三个版本的一种循环排列，六种排列各出现两次，
共 36 个长跑；每个样本均通过 Difftest、运行时配置和 60102-step timing 校验。
没有按单点 walltime 删除样本，第 10 轮的共同变慢保留在统计中。

| 指标 | pre-V5 baseline | V5 only | all-part reg-to-mem |
| --- | ---: | ---: | ---: |
| Host time 中位数 | 8.633 s | 7.4855 s | 6.5600 s |
| wall elapsed 中位数 | 8.720 s | 7.570 s | 6.640 s |
| 全局 eval 中位数 | 113.0915 us/step | 94.2080 us/step | 79.5725 us/step |
| 最大分区 eval | 111.2960 us/step | 92.0935 us/step | 75.0785 us/step |
| 分区 eval 总和 | 1253.8645 us/step | 1234.8020 us/step | 1178.1365 us/step |
| 全局 update 中位数 | 23.2820 us/step | 23.3955 us/step | 23.2990 us/step |

以每轮先算 `100*(lhs/rhs-1)`、再取 12 轮中位数：

| 对比 | Host | wall | eval | 最大分区 eval | eval 总和 | update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V5 / baseline | -13.33% | -13.20% | -16.76% | -17.26% | -1.49% | +0.35% |
| all-part / baseline | -24.05% | -23.85% | -29.66% | -32.52% | -6.04% | +0.03% |
| all-part / V5 | -12.42% | -12.23% | -15.53% | -18.53% | -4.67% | -0.36% |

因此新一批数据再次确认：全图 `reg-to-mem` 的收益主要来自 eval，update 基本不变；
它相对 V5 的 walltime 改善约 12.23%，与旧 8 对实验的方向和幅度一致。三个版本
仍使用同一 workload、assignment、通信结构和 all-spin runtime；本轮没有改变代码或
默认 pipeline。

复测原始产物：
`build/repcut_cost_model_20260922/three_way_c30000_node030_20260924/summary.json`、
`runs.json`、`parts.json`。三组新时空图：
[离线交互式 HTML](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline_rerun_20260924/three_stage_timeline.html)、
[SVG](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline_rerun_20260924/three_stage_timeline.svg)、
[数据 JSON](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline_rerun_20260924/data.json)、
[分区 CSV](../../build/repcut_cost_model_20260922/three_stage_v5_global_regtable_timeline_rerun_20260924/part_durations.csv)。
该 HTML 沿用原三组页面的浅色主题、阶段切换、组选择、排序、关键线程筛选、缩放、
悬停/点击详情和 CSV 导出；数据源换成这次 12 轮复测。

**增量修正（2026-09-24）：三组 HTML 显示与完整回归。** 上述新版 HTML 初次生成
时未完成浏览器验收：All parts 的配对结果写在 `paired.contrasts`，模板指标卡仍读取
`paired.metrics.elapsed_s`，导致第三组渲染抛错、页面只留下 Baseline / V5；不是
实验数据缺失或浏览器兼容性问题。现已统一配对数据格式，完整显示三组及 All parts
相对 V5、相对 Baseline 的两张收益卡，并将样本数/同批标签从实际数据生成。
36 次原始运行和各阶段、各分区统计值均未修改，未重新仿真。

严格浏览器回归已通过：默认 3 个面板、96 条分区；7 种组选择 × 3 个阶段、42 种
组选择/排序/筛选组合；配对百分比重算、CSV 数值与顺序、悬停/键盘详情、缩放/复位、
桌面/手机布局均通过，无 JavaScript 错误和外部网络请求。旧 8 次样本口径也通过同一
测试回归；测试按 manifest 检查完整样本数，不通过放宽断言掩盖缺组。复验脚本为
[test_three_stage_theme_browser.py](../../build/repcut_cost_model_20260922/test_three_stage_theme_browser.py)，
本节 HTML 链接不变。

### 12.12 按寄存器组筛选 reg-to-mem（2026-09-24）

在 `RegToMemOptions` 增加默认关闭的 `profitabilityFilter`，CLI/Python 可显式传
`-profitability-filter verilator-v1` / `profitability_filter="verilator-v1"`；
`none` 保持原有行为。只有本次冻结 V5 输入的候选生成脚本显式启用，其他调用不变。
该筛选发生在 true merge 匹配成功、改写图之前，按组计算行数 D、独立写家族 W、
优先级写冲突 P。在无动态读 anchor、会显式展开冲突、且 `P > D*W` 时保留原寄存器组；
拒绝后也不落入 intent 注解。ordered-writes 若能避免显式冲突展开，则不因这条规则拒绝。
这是针对 Verilator 当前 lowering 的保守风险筛选，不是准确的周期成本模型；没有使用
分区、模块或信号名字，也没有改默认 pipeline。

结构验证：全图候选只拒绝 1 组，日志为 `D=32 B=8 W=511 P=130305`，
`D*W=16352`。冻结输入和 runtime wrappers 身份一致；65 个 SV 文件中，筛选版相较
全图版仅 `part28.sv` 不同，且它与 V5 的 `part28.sv` SHA 完全相同；`part3.sv`
与全图版 SHA 完全相同。筛选版相较 V5 仍有 11 个 SV 文件不同。C++ 定向测试覆盖
高冲突拒绝、等号边界保留、低冲突保留、ordered-writes 绕过、默认值和 CLI 解析；
Python 选项测试 5 项通过。构建与 C100 功能检查通过。

在 node030 CPU96--127、NUMA1、K=N=32、all-spin、C=30000 上，执行两批各 8 对
AB/BA（第二批交换 baseline/candidate 标签）；两批共 32 个长跑均通过 Difftest
和 timing 校验，未删样本。以下比较统一以“筛选版 / 全图版”为方向：

| 指标 | 第一批（全图为 baseline） | 第二批（筛选为 baseline） |
| --- | ---: | ---: |
| Host 配对变化 | +1.25% | 约 +0.53%（反向比较折算） |
| wall 配对变化 | +1.22% | 约 +0.57%（反向比较折算） |
| p28 eval 中位数，全图 -> 筛选 | 55.70 -> 36.27 us/step | 54.40 -> 34.76 us/step |
| p3 eval 中位数，全图 -> 筛选 | 88.71 -> 90.62 us/step | 86.81 -> 86.96 us/step |

p28 的局部退化被消除（eval 约降 35%--36%），但 p3 仍是最长 eval 分区，且其
生成 SV 完全相同；总 Host/wall 在两批里没有收益，反而小幅变慢。第一批两版本共同
随时间变慢，p3 时间也随采样波动；因此不能把总量差异直接归因于门控本身。
目前可确认的是“避免 p28 局部退化”，不能宣称“提升整体 walltime”。这也说明按组
成本筛选还需要纳入关键路径和全局资源影响，单纯去掉非关键分区的工作不保证终点更快。

原始产物：[候选生成记录](../../build/repcut_cost_model_20260922/memory_coalesce_v5_regtable_profitability_v1/run.json)、
[第一批对照](../../build/repcut_cost_model_20260922/global_vs_profitability_v1_c30000_20260924/summary.json)、
[反向对照](../../build/repcut_cost_model_20260922/profitability_v1_vs_global_c30000_reverse_20260924/summary.json)。

### 12.13 将验证线收为主线默认并做等价 AB（2026-09-24）

按本节验证线实际使用的顺序，将默认 XiangShan RepCut 入口收敛为：

```text
closure-aware + verilator-v1 repcut
  -> memory-write-coalesce
  -> reg-to-mem(intent=false, profitability_filter=verilator-v1)
  -> emit/package
```

实现位置为 `scripts/wolvrix_xs_repcut.py` 和 Makefile。默认值现在是
`XS_REPCUT_WEIGHT_MODE=closure-aware`、`XS_REPCUT_COST_MODEL=verilator-v1`、
`XS_REPCUT_MEMORY_WRITE_COALESCE=1`、`XS_REPCUT_REG_TO_MEM=1`、
`XS_REPCUT_REG_TO_MEM_PROFITABILITY_FILTER=verilator-v1`。其中 pass 本身的
`RegToMemOptions::profitabilityFilter` 仍保持库级默认 `None`；只有主线 RepCut
入口显式打开 `verilator-v1`，不会改变其它调用方的默认语义。三个开关和两个模型
选项均保留环境变量覆盖，设为 `0` 或切回 `baseline/legacy` 即可复现旧流程。

默认入口在 RepCut 完成后、写出 partitioned JSON 前执行两个 backend pass，因而与
验证线一样作用于完整 32 分区图，而不是只匹配某个模块、信号或手选分区。默认生成
记录的 p28 高冲突组仍为 `D=32, B=8, W=511, P=130305`，门槛拒绝数为 1。

在 node030 CPU96--127、NUMA1、K=N=32、all-spin、C=30000 上，将这次默认生成与
显式传入完全相同选项的验证线产物交错 AB/BA 运行 8 对（16 个长跑）。两边 package
的 65 个 SV 文件 inventory SHA、运行时 wrapper SHA、总字节数均一致；16/16 样本
通过 Difftest 和 60102-step timing 校验。

| 指标 | 显式验证线中位数 | 默认入口中位数 | 默认/验证线配对中位变化 |
| --- | ---: | ---: | ---: |
| Host time | 7.6945 s | 7.6300 s | +0.37% |
| wall elapsed | 7.7800 s | 7.7100 s | +0.33% |
| eval | 93.7475 us/step | 92.7305 us/step | +0.53% |
| update | 27.2260 us/step | 27.1795 us/step | +0.23% |
| 最大分区 eval | 86.9595 us/step | 85.7970 us/step | +0.65% |

AB/BA 方向的 Host 配对中位变化分别为 `+0.37%` 和 `+0.37%`，wall 分别为
`+0.33%` 和 `+0.27%`；默认入口没有引入可分辨的性能回归或额外收益，结果符合
两份生成产物完全一致的预期。原始记录：[默认生成日志](../../build/default_line_ab_20260924/default_generate.log)、
[无覆盖默认生成 run/package](../../build/default_line_ab_20260924/default_noenv/)、
[8 对 AB/BA 汇总](../../build/default_line_ab_20260924/ab_c30000_default_noenv/summary.json)。

**提交范围补充（2026-09-24）：** 上述 AB 使用同一个冻结输入
`asc_separator_combined_20260921/targeted/xs_wolf_mem_to_reg.json`，其中已包含先前
single_00 + pair_00 的选择性 mem-to-reg 结果。本次默认入口的等价性验证从该 JSON
开始，不是从原始 RTL 重新生成全流程；按名称选择 memory 的实验辅助接口、未启用的
`verilator-lowered-v1` 以及 `testcase/xiangshan` 改动均不纳入本次主线提交。
实际无覆盖默认生成日志为
[default_noenv/generate.log](../../build/default_line_ab_20260924/default_noenv/generate.log)；
本节前一个 `default_generate.log` 链接属于较早的显式选项生成，最终表格和 AB 汇总
均采用 `default_noenv` 批次。

提交前对筛选后的源码快照另做独立构建检查：重新编译 7 个受影响实现及 5 个
C++ 定向测试，5/5 通过；Python RepCut / reg-to-mem 选项测试分别 6/6、5/5
通过。快照不含 `verilator-lowered-v1` 和 memory-symbol 定点选择接口；仅复用
未改动的其余对象及外部依赖。验证脚本、命令和日志位于
`build/repcut-default-commit.n0MvoN/verification/`，不提交构建产物。
