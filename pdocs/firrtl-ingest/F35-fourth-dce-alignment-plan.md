# F35 第四次 DCE 后的全图 Node 对齐

按用户要求在现有结果上收尾，**99.50%** 目标暂停。最后一次完整香山全图采集为第十四轮，第四次 DCE 后的 Node 同名率为 **99.39027%（2,498,583 / 2,513,911）**，剩余 **15,328** 个未匹配节点。15 个生产 pass 均通过耗时门。提交还包含两项经过模块级对照的后续改动，其全图影响尚未测量。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round14-combined.json) · [耗时预算](../../ptmp/firrtl-ingest/F35/measure-tests/round14-combined-timing.json)

## 1. 观察点与交付指标

以香山 `SimTop` 的生产 FIRRTL 流水线为准。GRH 停在第四次 `dead-code-elim#3` 返回后、`grhsim-dialect-translate` 前。GSIM 停在 `RemoveDeadNodes3` 返回后、`graphPartition` 前，该次调用的原生计时身份是 `RemoveDeadNodes#2`。以两端在这个观察点的完整 Node 库存计算：

```text
M = GRH 库存中其全名在 GSIM 库存里至少出现一次的 Node 数
N = GRH 库存中的全部 Node 数
U = N - M
对齐率 = M / N
交付门槛 = M / N ≥ 99.50%
```

沿用 F34 的全名口径，从 `name_path_json` 解码层级路径并以 `.` 连接，进行精确匹配。逐条 GRH Node 计数，GSIM 同名多条只贡献一次命中。无名 Node 计入 `N`，其中 GRH 无名 Node 计入 `U`。另报两端重复名和无名数量，用 Node ID 与谱系处理归因歧义。同名率衡量名称覆盖，改写正确性由受影响的语义回归验证。多时钟、SystemTask 等必要特性保留的 Node 仍按同一口径计分。所有阈值和增量用原始计数计算，报告百分点变化。

F34 历史全图结果为 **85.82406%（2,666,956 / 3,107,469）**，未匹配 **440,513** 个。F35 起点由冻结 GSIM 参考和初始 GRH 全量采集实测得出。若与 F34 存在差异，先记版本、配置、库存和产生差异的边界。
[F34 第四次 DCE 历史汇总](../../ptmp/firrtl-ingest/F34/dce-v3/summary.json) · [F34 逐 pass 采集说明](F34-post-third-dce-alignment-plan.md#逐-pass-node-trace-采集)

## 2. 参考采集与产物保留

沿用 F34 的 `SimTop.fir`、输入清单及语义设置，GRH 继续使用 `init_policy=unknown` 和 `invalid_policy=zero`。GSIM 保持原有语义配置、生产 pass 顺序及各 pass 参数。两端在同一台机器上错峰采集，记录输入清单、文件和二进制 SHA-256、提交、构建参数、CPU 亲和范围及实际线程数。

1. **先采一次 GSIM 全图参考。** 从原始 FIRRTL 输入启动，保留输入到 `Init` 首份 Node 库存的来源证据、`Init` 后每次 pass 的 Node 清单和 trace，直至第四次 DCE。一次运行同时获取各 pass 的原生耗时。首轮大图启动前用小图核验导出、来源追踪、计时和停止点。参考采集成功后校验边界完整性，冻结产物、校验和及计时表。后续迭代只读该参考，从冻结产物重放和查询，GSIM 全图采集只执行这一次。
2. **GRH 从 ingest 开始全量采集。** 建立起点和进入全图复测时，使用同一输入采集 ingest 后的首份模块 Node 清单和全部 15 次生产 pass 调用。两端每次调用保留前后 Node 和连接清单、`evolution.tsv`，以及已有的专项 trace，例如 GRH `hier-flatten` 的 `relocations.tsv`、双端 AliasAnalysis 的迁移 JSONL、GSIM 的 `native-mutations.jsonl`。输入和 `Init`／ingest 的关联需要源声明、表达式、模块实例路径或 lowering 来源证据。用首份库存定位输入分歧，缺失的源到 Node 关联记为证据缺口。
3. **产物放在 `ptmp/firrtl-ingest/F35/`。** `gsim-reference/` 存一份冻结参考，`grh-current/` 存唯一一份 GRH 全量 Node 和 trace。重采前提取旧轮的计数、校验和、样本行、事件片段与耗时，再回收旧全量目录并启动新采集。为核算差异消除量和新增量，临时保留本轮起点的未匹配名称及出现次数，跨轮不可辨认的无名 Node 单列计数。复测对账完成后清理该差异索引及查询、回放临时文件。超时只保留日志、触发记录和必要样本。

实施时复用 F34 的采集和重放逻辑。现有 `capture_f34_pass_trace` 的输出根限制在 F34，且这一路径未接入全前缀实时守卫。正式采集前在 Make 入口接通 F35 输出、输入来源记录、同次 GSIM 原生计时和 GRH 实时守卫，并用小图核验。构建、采集和测试均由项目 Make target 执行。
[F34 采集入口](../../Makefile#L821) · [采集器](../../scripts/capture_f34_pass_trace.py) · [GRH FIRRTL 流水线](../../scripts/wolvrix_xs_grhsim.py#L88) · [GSIM 生产入口](../../reference/gsim/src/main.cpp#L928)

### 一键采集模块或全图

`make f35_capture_both F35_MODULE=<模块名>` 按原始 FIRRTL 模块名提取模块和它的实例依赖。每次模块采集都从提取后的 `isolated.fir` 重新运行 GSIM，再用同一份输入运行 GRH。省略 `F35_MODULE` 即使用原始输入和清单采集全图。仅全图模式可用 `F35_CAPTURE_REFERENCE` 复用冻结的 GSIM 参考，省略该参数会重新采集 GSIM。

```sh
make f35_capture_both PYTHON=.venv/bin/python F35_MODULE=TLBFA_1 \
  F35_CAPTURE_ARGS='--reset-port reset=AsyncReset'

make f35_capture_both PYTHON=.venv/bin/python \
  F35_CAPTURE_REFERENCE=ptmp/firrtl-ingest/F35/gsim-reference
```

使用已构建的 F35 GSIM 和 Wolvrix Python 包。可用 `F35_INPUT`、`F35_MANIFEST` 换输入，用 `F35_GSIM_BINARY`、`F35_PACKAGE` 换引擎构建。模块的独立顶层若有抽象 `Reset` 输入，按原实例的连接指定 `--reset-port NAME=AsyncReset` 或 `--reset-port 'NAME=UInt<1>'`。派生输入中的端口类型修改和原始行号映射会记录在 `extraction.json`。

每次采集默认分配 `ptmp/firrtl-ingest/F35/captures/` 下的独立目录，也可通过 `F35_CAPTURE_OUTPUT` 指定 F35 下的新目录。两端串行执行，提取器流式读取 FIRRTL，派生输入默认上限 64 MiB，可用 `--max-module-bytes` 调整。联合 `summary.json` 列出双端各 15 个 pass 的产物目录，包含 `before/after.nodes.tsv`、`before/after.connections.tsv` 和 `evolution.tsv`。模块模式另外保留 `isolated.fir` 和派生的 `ingest-request.json`，复用参考时联合摘要直接指向已有 GSIM 产物。两倍参考耗时在此入口设有 60 秒下限，便于采集小图。正式全图耗时与节点对齐验收使用 `f35_grh_capture` 和 `compare_f35_alignment`。

从原始 `SimTop.fir` 提取并采集 `TLBFA_1` 用时 30.32 秒。最大单进程 RSS 约 669 MiB，换页计数为 0，产物占盘约 1.7 GiB。[模块采集摘要](../../ptmp/firrtl-ingest/F35/captures/paired-tlbfa-original/summary.json) · [内存记录](../../ptmp/firrtl-ingest/F35/launch/paired-tlbfa-original-memory.log)

## 3. 每轮反向排查

1. **分类。** 在第四次 DCE 后枚举全部 `U` 个差异 Node。按最终 Node 的语义形态、依赖及已有谱系证据给出互斥主类，每类报告数量、`数量 / U` 和较上一成功轮的变化。主类以数量降序排列，另记最早分歧边界和已证实的必要特性子类。分类总数必须等于 `U`。从还有未分析或可修复样本的类中选占比最大的一类，已证实的必要特性项仍留在计数里。
2. **取 3 个代表样本。** 优先覆盖所选类中高频的不同子形态或模块，记录抽样依据和预估覆盖量。以第四次 DCE 后的 GRH 全名和 Node ID 为锚，利用已有的层级展开迁移记录或源位置，找到样本所属的原始 FIRRTL 模块、实例路径和声明。
3. **逐样本先做模块级孤立复现。** 用 `make f35_capture_both F35_MODULE=...` 提取所属模块及其实例依赖，从同一份 `isolated.fir` 重新采集 GSIM 和 GRH。用 `extraction.json` 的行号映射和模块内相对路径把样本对应到局部 Node。多个样本的模块和边界配置相同时，可在同一轮采集中一起查询。

   - **模块级复现原差异。** 把该模块作为调试单位，用双端 pass trace 定位首次实质分歧，核对各自的前驱、代表和消费者。运行 `compare_f35_alignment` 和 `trace_f35_samples` 时，将 `F35_GRH_CAPTURE` 和 `F35_REFERENCE` 指向本次模块采集的 `grh/` 和 `gsim/`，将 `F35_REPORT` 指向模块对账报告。查询时指定局部相对名称。完成必要特性门控后，先用模块采集快速验证每次候选修改。
   - **模块级未观察到原差异。** 若两端在模块内对样本的处理一致、局部差异与全图样本不一致，或隔离后无法对应样本，记录模块级结果，再用已有全图 GRH 产物和冻结 GSIM 参考运行 `trace_f35_samples`，按该样本的全名追查父实例连接、跨层级依赖或全图遍历顺序。模块采集失败时，按证据缺口记录错误，使用已有全图 trace 补查。

   无论在哪个范围追查，都沿原名、替代代表、拆分片段、实例迁移和消费者连接追溯。每个样本记录首次库存分歧、最早实质分歧的 ingest 或 pass 调用、双端边界前后状态、改写或保留理由及最终去留。涉及 `invalidate`、时钟、外部效果等语义时，引用对应声明和 lowering 结果。分别记录 `未出现`、`有原生删除证据` 和 `证据缺失`。

4. **必要特性门控。** 只要 3 个样本中有一个经源文件、依赖和 trace 证实是 GRH 多时钟、SystemTask 等必要特性所要求的保留，本轮提前结束并记录理由，下一轮跳过已证实的 Node 或同一已证实子群，继续排序取样。样本证据只用于其能覆盖的子群。证据不齐时先补齐或在同类重取样，完成门控后再进入修复。
5. **修复和复测。** 修改首次产生实质分歧的 GRH ingest 或前驱 pass，记录修复规则、适用范围和受影响语义回归。对已在模块级复现的样本，先在模块内确认差异消除，再进入全图复测。清理旧 GRH 全量产物后，从同一输入重采 GRH Node 和 trace，继续使用冻结的 GSIM 参考。逐一核验 3 个样本的分歧是否已消除、对应保留或删除是否合法，再核对命中子群的数量和新的 R4 库存。若样本只发生改名、换代表或延后删除，沿谱系确认最终状态并记录原因。
6. **判定。** 语义回归通过、两倍耗时门通过、样本差异消除，且对齐率严格高于本轮起点时，记录为成功并以该候选作为下一轮基线。报告 `M/N`、`U`、百分点变化、原有差异消除量和新增差异量，区分原有未匹配 Node 合法退役和建立同名命中带来的收益。对齐率持平或下降时，记录反例及计数，回到步骤 3 重新核对归因和门控后重试。样本分歧未消除也继续追查。各次尝试都以本轮起点判定，保留每次尝试的结果。全图有效结果达到 99.50% 后结束迭代并报告剩余分类。

## 4. 单 pass 两倍耗时门

对每次有 GSIM 对应调用的 GRH pass，用同次冻结 GSIM 采集中 `scope=pass` 的原生单调时钟耗时 `R` 锁定预算 `2 × R`。按实际职责和调用序号核对下表。表按 GRH 执行顺序排列，GSIM 的 `SplitArray` 先于 `DetectLoop`。

| GRH 调用 | GSIM 边界 | GSIM 原生计时身份 |
| --- | --- | --- |
| `comb-loop-elim#0` | `DetectLoop` | `DetectLoop#0` |
| `split-static-array#0` | `SplitArray` | `SplitArray#0` |
| `dead-code-elim#0` | `RemoveDeadNodes0` | `RemoveDeadNodes#0`（原生计时 `stage=RemoveDeadNodes`） |
| `expr-opt#0` | `ExprOpt` | `ExprOpt#0` |
| `used-bits#0` | `UsedBits` | `{g->usedBits()}#0` |
| `split-nodes#0` | `SplitNodes` | `{g->splitNodes()}#0` |
| `dead-code-elim#1` | `RemoveDeadNodes1` | `RemoveDeadNodes1#0` |
| `constant-analysis#0` | `ConstantAnalysis` | `ConstantAnalysis#0` |
| `dead-code-elim#2` | `RemoveDeadNodes2` | `RemoveDeadNodes#1` |
| `alias-analysis#0` | `AliasAnalysis` | `AliasAnalysis#0` |
| `pattern-detect#0` | `PatternDetect` | `PatternDetect#0` |
| `common-expr#0`（入口 `comm-expr`） | `CommonExpr` | `CommonExpr#0` |
| `dead-code-elim#3` | `RemoveDeadNodes3` | `RemoveDeadNodes#2` |

GRH 的 `xmr-resolve`、`hier-flatten` 涉及 GSIM `Init` 中完成的整图构造职责，缺少一对一独立计时。两者分别记录实测和单独终止时限。GSIM 的 `TopoSort`、`InferAllWidth` 也保留各自计时和 trace，供溯源使用。存在对应调用但参考计时缺失、为零或身份错误时，记录为参考缺口，先核查冻结运行的原始计时和事件，预算核实后再启动对应 GRH pass。

外部守卫监听每次 GRH pass 的单调时钟开始与结束事件。超时门计入生产 pass 的处理和必要的 Node 维护，快照导出、trace 落盘和重放等能在调用外完成的工作单独计时。调用内同步 trace 记录的开销进入本次观测，并注明两端采集设置。**到达 `2 × R` 仍未结束，立即终止该运行的私有进程组并转向该 pass 的性能优化。** 若在检查间隔内返回但原生耗时超过预算，同样判为超时。记录触发时刻、预算、实际耗时、最后完整边界和终止信号；完成耗时等于预算可通过。优化后先跑受影响的语义回归，再从同一输入重试，使用原预算，直到该 pass 回到预算内才恢复对齐迭代。
[现有两倍超时监督逻辑](../../scripts/f33_guard.py) · [GSIM 原生计时实现](../../reference/gsim/src/main.cpp#L290)

## 5. 记录格式

### 5.1 冻结参考与起点（执行时填写一次）

| 项 | 记录内容 |
| --- | --- |
| 输入与语义 | 顶层、源及清单路径和 SHA-256、两端选项和实际线程数 |
| GSIM 冻结参考 | 提交、二进制 SHA-256、Make 参数、运行 ID、目录及清单校验和、采集与重放校验结果 |
| Pass 计时表 | 每次调用的 GSIM 边界和原生计时 ID、GRH 对应调用、原生 `R`、`2 × R`、计时证据位置；未配对阶段注明职责和单独时限 |
| 初始 GRH | 提交或补丁、包指纹、运行 ID、完备性校验、第四次 DCE 库存校验和 |
| F35 起点 | GSIM 库存总数、`M`、`N`、`U`、同名率、两端重复名与无名数、与 F34 历史值的差异 |

### 5.2 每轮一节（执行时复制到本文末尾）

```markdown
## 第 N 轮 · 日期 · 最大差异类别

### 起点与分类

- GSIM 参考 ID、GRH 起始提交与运行 ID、R4 清单校验和、M/N、比例、U。

| 类别 | Node 数 | 占 U | 较上一成功轮变化 | 已证实的必要特性数 | 证据 |
| --- | ---: | ---: | ---: | ---: | --- |

### 三个样本与门控

| 样本全名和 GRH R4 ID | 抽样理由与子群大小 | FIRRTL 模块、实例路径和声明 | 模块级复现结果与采集摘要 | 双端首次库存分歧和首次实质分歧 | 代表或消费者迁移及最终去留 | 门控结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 样本 1 | | | | | | |
| 样本 2 | | | | | | |
| 样本 3 | | | | | | |

- 每个样本注明模块级是否复现。若回到全图，记录原因和全图证据。附上所用范围内从输入到 R4 的查询链，记录双端调用 ID、阶段前后 Node/连接 ID、事件序号或源行。连续未变的边界可合并记录。
- 本轮门控结果、依据和下一轮可跳过的已证实范围。

### 修复、耗时与复测

- 尝试序号、根因边界、修改位置、规则和语义回归结果。
- 已在模块级复现的样本附局部修复前后证据。
- 新 GRH 运行 ID、R4 清单校验和、三样本复测结果、旧产物已提取的证据。

| GRH 调用 | GSIM 计时 ID | 参考 R（秒） | 预算（秒） | 实际（秒） | GRH/GSIM | 结论与证据 |
| --- | --- | ---: | ---: | ---: | ---: | --- |

- 超时附触发记录、最后完整边界、性能原因和复测数据。

| 版本 | 同名 M | GRH 总数 N | 差异 U | 对齐率 | 较起点变化（百分点） | 消除 / 新增差异 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 本轮起点 | | | | | | |
| 本次复测 | | | | | | |

- 结论填写门控提前结束、性能阻塞、归因重试、迭代成功或达到交付门槛，并记录后续动作。
```

## 6. 实施记录

- 执行入口为 `make f35_gsim_build`、`make f35_gsim_reference`、`make f35_grh_capture`、`make compare_f35_alignment` 和 `make trace_f35_samples`。正式输入沿用 F34 R4 的 `SimTop.fir` 与 `F34/alias-full-input/ingest-request.json`，清单 SHA-256 为 `cc7385dd81e921f95dfde78fd089d3f86b681c1b0e056bb0fb3f7bd5a0312969`。`xmr-resolve#0` 与 `hier-flatten#0` 独立时限分别为 180 秒和 300 秒，可通过对应 Make 参数设置。
- 2026-11-24 小图核验。`make test_f35_tools` 通过 12 项。双端各 15 次 pass 的 Node 和连接增量均已独立重放。GRH 超时测试核验了原生耗时和截止时终止私有进程组。用 F34 历史库存复核对账器，复现 85.82406%，其中 428,037 个未匹配 Node 归为赋值，占 97.17%。[工具测试日志](../../ptmp/firrtl-ingest/F35/launch/tool-tests.log) · [历史库存分类](../../ptmp/firrtl-ingest/F35/measure-tests/historical-f34.json)
- 2026-11-24 00:08（UTC+8）启动唯一一次 GSIM 香山全量采集，二进制 SHA-256 为 `b1a7fdee206b08e56adb2c19aa1cd10f4a36b3cf6b80a8c30ba9cfd68a7b9938`，解析使用单线程，CPU 亲和范围为 0–31。该次采集在来源行号精确化补丁前启动，溯源时用实例路径、Node 名称和原始 FIRRTL 文本核对源行。GRH 已排队，冻结完成后按同次原生耗时启动。[GSIM 运行日志](../../ptmp/firrtl-ingest/F35/gsim-reference/gsim.log) · [原生计时](../../ptmp/firrtl-ingest/F35/gsim-reference/native-timing.jsonl)
- 00:43，GSIM 第三次 DCE 返回后在 native journal 回放自校验处退出。对照同一输入的历史快照，760 条时钟依赖从已解析变为未解析，涉及 380 个寄存器当前值和 380 个下一状态。时钟 Node 被删除后，存活寄存器仍持有原时钟引用。采集器现在记录旧边删除及未解析边新增，保留 GSIM 原有行为。原始输入证据和截至 ConstantAnalysis 的 10 次完整 pass 采集已保留。[原始中断日志](../../ptmp/firrtl-ingest/F35/gsim-reference/gsim.log) · [GSIM 原生 trace 回归](../../ptmp/firrtl-ingest/F35/launch/gsim-native-tests.log)
- 00:54，启动 GSIM 缺失尾段补采。进程退出时未留下可恢复的原生图。补采从同一 FIRRTL 重建前缀状态，目标是导出第三次 DCE 至第四次 DCE 的 5 个缺失 bundle。预算表采用前缀的首次采集值和尾段的补采值，保留各进程的原生计时。[尾段运行日志](../../ptmp/firrtl-ingest/F35/gsim-reference/recovery-from-dce-2/gsim.log)
- 第三次 DCE 补采完成，记录 944 条从已解析变为未解析的时钟依赖。随后 AliasAnalysis 回放发现未参加调度的常量也持有被删除的时钟引用。补齐这类引用后，从 AliasAnalysis 补采至第四次 DCE，各 pass 的原生 trace 均通过进程内回放校验。第四次 DCE 库存为 3,612,639 个 Node，使用该尾段开始首轮归因。参考冻结仍需核验两处跨进程衔接，`SplitNodes` 生成的 Node ID 会随运行变化，逐字节比较会在这些行失配。[AliasAnalysis 至第四次 DCE 日志](../../ptmp/firrtl-ingest/F35/gsim-reference/recovery-from-alias-analysis/gsim.log)
- 02:14，冻结 GSIM 参考。第三次 DCE 和 AliasAnalysis 的输入边界分别重映射 7,318 和 7,639 个 Node ID，随后两处的节点、连接、节点详情及位段表完全一致。冻结清单保留映射和各次原生计时；样本回溯跨这两个边界时应用对应映射。[冻结清单](../../ptmp/firrtl-ingest/F35/gsim-reference/frozen.json)

## 第 1 轮 · 2026-11-24 · 赋值节点

### 起点与分类

正式 F35 起点为 **85.84248%（2,667,573 / 3,107,521）**，差异 **439,948** 个。两端均无无名和重名 Node。GRH R4 清单 SHA-256 为 `866b1ef117b939edde2cdc2602c2adad6a5a960b059a2a1b9e1d0d94eeb081af`。抽样时用 F34 的 GRH R4 与 F35 的 GSIM R4 临时对账，得到 85.84185%，其中有 400,876 个未匹配的 `kAssign` 同时具有入边和出边。[正式 F35 起点](../../ptmp/firrtl-ingest/F35/measure-tests/round-1-baseline.json) · [抽样时的临时对账](../../ptmp/firrtl-ingest/F35/provisional-f34-grh-new-gsim.json)

389,502 个未匹配名字最后一次出现在 GSIM `CommonExpr` 输入，占全部差异的 88.53%。这个计数定位了名字消失的边界，修复覆盖量以重采后的对账为准。

| 类别 | Node 数 | 占差异 |
| --- | ---: | ---: |
| 赋值 | 428,037 | 97.29263% |
| Mux | 5,179 | 1.17718% |
| 状态与存储 | 3,162 | 0.71872% |
| 位切片与拼接 | 2,264 | 0.51461% |
| 其他组合逻辑 | 890 | 0.20230% |
| 常量 | 416 | 0.09456% |

### 三个样本与门控

三个名字位于 `cpu.l_soc.socMisc`，FIRRTL 声明都是 `eq(out_bindex, UInt<9>(0h0))`。GSIM 在 `Init` 记录各自的声明，进入 `CommonExpr` 时四个名字都在。GRH 的历史 R2 有四个独立的 `kAssign` 根，R3 共享锚值 `102509` 和操作 `27831`，R4 四个名字全部在册。GSIM 在 `CommonExpr` 选 `_out_T_7`（ID `176100`），记录三个样本的合并和退役。GRH 的首次实质分歧定位于 `common-expr#0` 的 Node 迁移策略，该调用将重复名的锚点与绑定一起迁到共享值，随后 DCE 清理物理计算时这些名字仍有有效锚点。F35 基线 trace 复现这个过程，`60866`、`60868`、`60870` 记录为合并到 `60864`，四个名字都通过第四次 DCE。[FIRRTL 输入](../../build/xs/rtl/rtl/SimTop.fir) · [GSIM Init 来源](../../ptmp/firrtl-ingest/F35/gsim-reference/init-node-origins.tsv) · [GSIM 原生 CommonExpr 事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl) · [GRH 历史 R2、R3](../../ptmp/firrtl-ingest/F34/common-v3/grh)

| 样本 | GRH R4 ID | GRH R2 锚值 | GSIM ID | FIRRTL 声明行 | GSIM 合并、退役事件序号 |
| --- | ---: | ---: | ---: | ---: | --- |
| `cpu.l_soc.socMisc._out_T_1` | 60,864 | 102,509 | 176,094 | 1,000,037 | 22,233、22,234 |
| `cpu.l_soc.socMisc._out_T_3` | 60,866 | 102,511 | 176,096 | 1,000,039 | 22,231、22,232 |
| `cpu.l_soc.socMisc._out_T_5` | 60,868 | 102,513 | 176,098 | 1,000,041 | 22,229、22,230 |

三例为寄存器总线地址解码的组合比较，源操作数来自 `out_bindex` 和零常量。FIRRTL 直接消费者为 `_out_rofireMux_T_3`、`_out_rofireMux_T_7`、`_out_rofireMux_T_11` 及相邻的布尔比较。GRH ingest 中对应 `SoCMisc` 的 `6547`、`6549`、`6551`，`hier-flatten` 将它们迁到表中的 R4 ID。双端从 ingest 到 `pattern-detect` 均保留这四个计算，三例没有触发多时钟或 SystemTask 门控。GRH 第四次 DCE 的直接保留证据是操作 `577150` 对共享锚值 `102509` 的需求，退役样本名称时应继续保留该计算和消费边。[F35 双端样本全路径](../../ptmp/firrtl-ingest/F35/measure-tests/round-1-baseline-samples.json)

### 修复、耗时与复测

- 修改 GRH `common-expr`。在生产 FIRRTL 流程关闭声明保留时，只对同一层级、命名输入集合相同的等价组合节点尝试退役。消费者继续使用原槽位，关联迁到代表节点，源声明记录随计算保留。显式保名、外部端口、状态及有副作用的消费者继续受保护。GSIM 全图的代表选择还受拓扑遍历顺序影响，当前字典序规则只在上述范围内使用，须用全图结果核对代表名称。[实现](../../wolvrix/lib/transform/common_expr.cpp) · [定向回归](../../wolvrix/tests/transform/f34_common_expr.cpp)
- 定向 `transform-f34-common-expr` 回归通过，验证三个重复名退役、代表保留、消费者槽位和输出值。F35 采集和对账工具的 15 项测试通过。[定向回归日志](../../ptmp/firrtl-ingest/F35/common-expr-fix/tests/test.log) · [工具测试日志](../../ptmp/firrtl-ingest/F35/launch/tool-tests.log)
- 01:59，启动修复版香山 GRH 全量采集 `f35-grh-b6f1694210ba4d21badb1c3205fec68b`。跨进程参考衔接核验与本次采集并行，守卫采用对应 GSIM 原生计时，其中 `common-expr#0` 预算为 221.327563 秒。此前仅有 F34 GRH 历史库存，因而新结果出来后先按临时起点对账。[GRH 运行日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-b6f1694210ba4d21badb1c3205fec68b/grh.log) · [原生计时](../../ptmp/firrtl-ingest/F35/recovery-timing.jsonl)
- 首次采集的 `split-static-array#0` 原生耗时为 51.812379 秒，预算为 232.986419 秒。该 pass 返回后，采集器发现一个本轮新建的节点曾失去操作，误用仅面向入口库存的删除汇总规则报错。修正后，pass 内新建的节点通过其实际增量记录，操作删除汇总继续引用入口节点。02:14 从 ingest 重启 GRH `f35-grh-098ed9ee3adf46009b1e62030ccd7a44`，沿用与冻结清单逐字节相同的原生计时。[初次中断日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-b6f1694210ba4d21badb1c3205fec68b/grh.log) · [当前 GRH 日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-098ed9ee3adf46009b1e62030ccd7a44/grh.log)
- 第二次采集的 `split-static-array#0` 耗时 90.832161 秒。采集器随后遇到同一个事务内先创建、后退役的数组成员。这些成员没有快照行，修复后按存活成员输出位段谱系，并保留对其余缺失端点的校验。`grh-semantic-tree` 回归通过，覆盖这两处采集器缺陷。02:26 使用冻结参考重启 GRH `f35-grh-d0bedf11cf4e465eb78f8f9c2e3f3e37`，已串接 R4 对账及三样本复查。[第二次中断日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-098ed9ee3adf46009b1e62030ccd7a44/grh.log) · [采集器回归日志](../../ptmp/firrtl-ingest/F35/grh-exchange-fix/tests/test.log)
- 02:54，15 个 pass 全部通过耗时门。`common-expr#0` 为 111.265276 秒，预算 221.327563 秒。第四次 DCE 为 32.339073 秒，预算 63.012345 秒。首次退役补丁检查的是旧的 `firrtl.nodeSchema`，生产 FIRRTL 使用 `firrtl.semanticNodePolicy`，所以这次全图按原有退役行为运行并形成正式起点。现已修正门控及生产 FIRRTL 的无显式槽位数据引用处理，对应回归通过。[正式起点](../../ptmp/firrtl-ingest/F35/measure-tests/round-1-baseline.json) · [生产形态回归](../../ptmp/firrtl-ingest/F35/common-expr-production/tests/test.log)
- 03:15，已提取基线对账和双端样本证据，并用修正后的生产规则开始重采 `f35-grh-909c20ed5d9c489ba13759d7917254ec`。复测以正式起点计算变化，完成后复查三个退役名称和代表 `_out_T_7`。[复测日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-909c20ed5d9c489ba13759d7917254ec/grh.log)
- 03:44，复测全图对齐率为 **89.20212%（2,656,722 / 2,978,317）**，较起点提高 **3.35965 个百分点**。原有未匹配节点消除 118,353 个，其中赋值 118,204 个、Mux 45 个、位切片与拼接 104 个。新增未匹配名称为零，同名命中净减少 10,851 个，仍需查清这些名字的退役原因。GRH R4 库存 SHA-256 为 `920baee53ba4ededa949d1b14be4b5d454ebc2995ed7c67643884c7273927d18`。[复测对账](../../ptmp/firrtl-ingest/F35/comparison.json)
- 三个样本均由 `common-expr` 合并到 `_out_T_7`（GRH `60870`，GSIM `176100`）。GRH 合并事件位于 `evolution.tsv` 的 4,439,761 至 4,439,763 行。第四次 DCE 后双端均只剩 `_out_T_7`。[GRH 样本记录](../../ptmp/firrtl-ingest/F35/measure-tests/named-consumer-count-samples.json) · [GSIM CommonExpr trace](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl)
- 15 个 pass 均通过耗时门。`common-expr#0` 为 101.601896 秒，预算 221.327563 秒。第四次 DCE 为 32.631700 秒，预算 63.012345 秒。定向回归通过，三个样本差异消除，首轮对齐率提升。剩余 321,595 个未匹配节点，距离 99.00% 目标还有 9.79788 个百分点。[耗时记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-909c20ed5d9c489ba13759d7917254ec/guard.json)

| 复测后类别 | Node 数 | 占差异 | 较起点变化 |
| --- | ---: | ---: | ---: |
| 赋值 | 309,833 | 96.34260% | −118,204 |
| Mux | 5,134 | 1.59642% | −45 |
| 状态与存储 | 3,162 | 0.98322% | 0 |
| 位切片与拼接 | 2,160 | 0.67165% | −104 |
| 其他组合逻辑 | 890 | 0.27675% | 0 |
| 常量 | 416 | 0.12936% | 0 |

三个同名命中回退样本是 `cpu.l_soc.socMisc.busPMU._T_274`、`_T_277` 和 `_T_280`。GRH 的 `common-expr` 分别把它们迁到 `_T_275`、`_T_278` 和 `_T_281`。GSIM 保留了这六个名字，每个节点只有一个下游消费者。以 `_T_274` 为例，FIRRTL 将它用于 `perfCnt_bore_82` 的 probe，将 `_T_275` 用于延迟统计的 Mux。现有 GRH 共享门限按物理操作和物理消费者计数，具名退役继承了这个判断。下一次修订需分别检查具名等价组的大小和不同的下游 Node 数。[GRH 退役与 GSIM R4 同名清单](../../ptmp/firrtl-ingest/F35/measure-tests/matched-loss.tsv) · [FIRRTL 来源](../../build/xs/rtl/rtl/SimTop.fir)

## 第 2 轮 · 2026-11-24 · 赋值节点的必要特性门控

起点为第一轮复测的 **89.20212%（2,656,722 / 2,978,317）**。剩余 321,595 个差异中，赋值为 309,833 个，占 96.34%。其中 267,653 个赋值名称最后出现在 GSIM `CommonExpr` 的输入，占赋值差异的 86.39%。[按 GSIM 最后出现边界分类](../../ptmp/firrtl-ingest/F35/measure-tests/round-1-candidate-with-history.json)

首批样本包括 `intRegion._T_1`、`intBusyTable._tmp_T` 和 `rob._allocatePtrVec_T_3`。`intRegion._T_1` 在 FIRRTL 5,255,850 行定义为复位条件，5,255,854 行用于 `circt_chisel_ifelsefatal`。GRH 将 `Region` 中的 Node `24133` 迁为全图 Node `2730922`。`common-expr` 将其计算迁到共享锚值 `744565`，第四次 DCE 记下 `kSystemTask` 所属 Node `240841` 对该锚值的需求。GSIM `CommonExpr` 将 Node `4048995` 合并到 `40248` 后退役。按必要特性门控提前结束本轮，暂保留这个样本，后续抽样继续排查同类组合逻辑。其他两例进入下一轮重新核对。[GSIM 合并事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl)

## 第 3 轮 · 2026-11-24 · 跨层级与等价前驱的赋值节点

沿用第一轮复测起点。在占比最高的赋值类中，选三个已被 GSIM `CommonExpr` 退役、但仍在 GRH R4 的样本。双端 ingest 记录了各自的源声明。三个 GRH Node 从 `hier-flatten` 到第四次 DCE 使用同一个 ID，GSIM 三个名称也一直保留到 `CommonExpr` 输入，随后退役。GRH 已证明这三组物理计算等价并共享结果，具名退役仍被第一轮的候选限制挡住。[逐 pass 样本 trace](../../ptmp/firrtl-ingest/F35/measure-tests/round-2-samples.json)

| GRH 样本 | FIRRTL 声明行和 ingest Node | GSIM 合并 | GRH 结果 |
| --- | --- | --- | --- |
| `rob._allocatePtrVec_T_3`（`805319`） | 1,922,621，`Rob` 的 `3192` | `926538` → `1944005`（`rob._dispatchNum_T_8`）；两组加法的输入名先归并 | `1819755` 和样本共享值 `3641974`，名称均存活 |
| `intBusyTable._tmp_T`（`2224922`） | 3,141,589，`BusyTable` 的 `211` | `2119111` → `2117300`（`rcTagTable._IntRCTagTable_io_writePorts_0_wen_T`）；两个节点的前驱相同 | 代表 `2218800` 和样本共享值 `10751753`，两名跨层级保留 |
| `page_ldtlb_storage_fa.s2ppn_tmp`（`6545823`） | 7,877,227，`TLBFA_1` 的 `38596` | `6602639` → `6639618`（`page_sttlb_storage_fa.s2ppn_tmp`） | 同组归到值 `29015727`，其中 GSIM 代表对应 GRH `6577841`，两名均存活 |

样本是加法、唤醒使能和页表字段选择。第四次 DCE 的直接需求节点分别为 `allocatePtrVec.value_2`、`_IntRCTagTable_io_writePorts_0_wen_T_3` 和 `entries.ppn_low$NEXT`。现有证据支持保留这些计算和消费关系，并继续核对重复名称的退役条件。此轮修复和复测尚待完成。

按冻结的 GSIM 原生合并事件逐名核对，当前 GRH R4 仍保留 272,627 个被 GSIM `CommonExpr` 直接合并的名字，占全部差异的 84.77%。其中 112,678 个在 GSIM 中合并到另一层级。230,709 个名字与相应的 GSIM 代表名在当前 GRH 图中已经共享同一个结果和位偏移。按全名字典序选择最大名，在这 272,627 个名字对应的合并事件里只有 164,844 个能选中 GSIM 的代表。下一步先修正同一下游 Node 被重复计数的退役门限，再单独验证跨层级和等价前驱的代表选择。[合并事件统计](../../ptmp/firrtl-ingest/F35/measure-tests/gsim-cse-shape.json) · [共享结果对账](../../ptmp/firrtl-ingest/F35/measure-tests/cse-witness/same-rep-values.tsv)

04:44，开始复测第一轮带来的同名命中回退。`common-expr` 的具名退役门限改为按具名等价组及不同的下游语义 Node 计数，物理表达式共享仍按 SSA 操作计数。`transform-f34-common-expr` 和 `grh-semantic-tree` 均通过。本次复测记录三个 `busPMU` 名称是否恢复，以及第一轮的三个 `_out_T_*` 是否仍退役。[定向回归](../../ptmp/firrtl-ingest/F35/named-consumer-count-regression/tests/test.log) · [GRH 复测日志](../../ptmp/firrtl-ingest/F35/launch/grh-20261123T204416017127697.log)

05:15，消费者计数修正的全图结果为 **89.18977%（2,666,700 / 2,989,917）**，比轮次起点下降 **0.01236 个百分点**。同名命中恢复 9,978 个，同时增加 1,622 个未匹配节点，其中赋值 1,617 个、位切片与拼接 5 个。共余 323,217 个差异。这次尝试未达到本轮成功条件。15 个 pass 均通过耗时门，`common-expr` 用时 104.67 秒，预算 221.33 秒，第四次 DCE 用时 33.40 秒，预算 63.01 秒。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/named-consumer-count.json) · [耗时记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-d3926064d3ab42858d583817fcd20137/guard.json)

三例 `busPMU` 名称在 GRH 和 GSIM 的 R4 均保留。第一轮的三个 `socMisc._out_T_*` 仍由 `common-expr` 合并到 `_out_T_7`，两端第四次 DCE 仅保留代表。[GRH R4 样本](../../ptmp/firrtl-ingest/F35/measure-tests/named-consumer-count-focused/grh-r4.tsv) · [GSIM R4 样本](../../ptmp/firrtl-ingest/F35/measure-tests/named-consumer-count-focused/gsim-r4.tsv) · [GRH 合并事件](../../ptmp/firrtl-ingest/F35/measure-tests/named-consumer-count-focused/common-expr-lineage.tsv)

05:38，开始复测跨层级改写。`common-expr` 在整个展开图内按结构等价和相同命名前驱分组。`intBusyTable._tmp_T` 的两个进入边与 `rcTagTable` 代表相同，225 个等价节点共享该前驱集合。组内采用逆序名称确定代表，保留消费者、值和操作数槽位。两项定向测试通过，含跨实例改写和输出校验。ROB 与 TLB 使用不同命名前驱，仍需验证等价前驱与状态写入的处理。此次对账同时记录相对上次尝试的变化，并以本轮起点 89.20212% 判定成功条件。[定向测试](../../ptmp/firrtl-ingest/F35/cross-instance-cse/tests/test.log) · [本次采集日志](../../ptmp/firrtl-ingest/F35/launch/grh-20261123T213830843668685.log)

对已共享锚值的样本组，离线按依赖重建拓扑遍历。`split-static-array` 后可比较的 230,529 对中，209,565 对的 GSIM 代表先于对应重复名，约 90.91%。`common-expr` 入口为 202,232 / 230,273，约 87.82%，三个样本的 GSIM 代表均先于重复名。该实验只比较排序，具名组成员资格和实际全图改写仍须复测。[数组拆分后](../../ptmp/firrtl-ingest/F35/measure-tests/topology-audit/grh-array.log) · [CommonExpr 入口](../../ptmp/firrtl-ingest/F35/measure-tests/topology-audit/grh-cse.log)

06:09，跨层级改写复测为 **91.36034%（2,665,479 / 2,917,545）**，比本轮起点高 **2.15822 个百分点**，比上一尝试高 **2.17057 个百分点**。相比上一尝试，消除 71,151 个未匹配节点，新增未匹配为零，同名命中净少 1,221 个。15 个 pass 均通过耗时门，`common-expr` 为 106.17 秒，第四次 DCE 为 33.00 秒。BusyTable 样本在 `common-expr` 从 `2224922` 合并到 `2218800`，第四次 DCE 后仅保留 GSIM 同名代表。ROB 和 TLB 的两端名称选择仍有分歧，本次结果未满足第三轮全部样本的验收条件。剩余赋值节点 240,411 个，占全部差异 95.38%，其中 198,358 个名字最后出现在 GSIM `CommonExpr` 的输入。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/cross-instance-cse.json) · [样本 R4](../../ptmp/firrtl-ingest/F35/measure-tests/cross-instance-cse-focused/grh-r4.tsv) · [GRH 迁移事件](../../ptmp/firrtl-ingest/F35/measure-tests/cross-instance-cse-focused/common-expr-lineage.tsv) · [耗时记录](../../ptmp/firrtl-ingest/F35/measure-tests/cross-instance-cse-focused/guard.json)

后续尝试在 `common-expr` 入口重建具名拓扑顺序。按拓扑顺序发现结构相同且已知前驱等价的候选，再依据组大小和具名消费者数量决定退役。TLB 的页表值在 GRH 中通过拼接和数组视图写入多条 lane，GSIM 对应展开为八个不同写入节点。该次修改仅在具名消费者门限中计入有完整位宽和边界对齐证据的独立数组 lane，保留原数组写入。新增定向回归覆盖拓扑代表选择、等价前驱、数组 lane 和单个标量消费者中的重复使用，全部通过。[定向回归](../../ptmp/firrtl-ingest/F35/array-consumer-cse/tests/test.log) · [前驱对账](../../ptmp/firrtl-ingest/F35/measure-tests/topology-audit/predecessor-canonical-cohorts.log)

ROB 组在 GSIM 有五个成员。经由子模块数组输入的 `enqPtrGenModule._dispatchNum_T` 在 GRH 多出同类型的无名 `kAssign`，导致加法树分组不同。在 `common-expr` 比较结构时跳过这种无名、同类型的接线，保留具有命名结果、端口或额外操作属性的赋值。最小 FIRRTL 在 GRH 中复现了额外赋值，定向回归检查了不同名等价前驱经过这类接线后仍能按拓扑顺序选出代表，消费者槽位和值均正确。06:20 启动包含拓扑、数组消费者和同类型接线三项修改的全量复测 `f35-grh-d6626f8dd395436d822829f10fa0ae67`。[ROB 最小复现](../../ptmp/firrtl-ingest/F35/rob-shape/sample.fir) · [GRH 结构](../../ptmp/firrtl-ingest/F35/rob-shape/grh.json) · [定向回归](../../ptmp/firrtl-ingest/F35/unnamed-copy-cse/tests/test.log) · [全量运行日志](../../ptmp/firrtl-ingest/F35/launch/grh-20261123T222026469060445.log)

另从 91.36034% 候选的赋值差异中预取 `fpBusyTable.tmp_ld2Cancel_1413`、`_1420`、`_1427`。冻结参考记录 GSIM `CommonExpr` 将 `2235546`、`2235730`、`2235914` 合并至 `4432528`，即 `issueQueueFEX3_FaluFmac.entries.othersEntriesComp_15.common_srcLoadTransCancelVec_2_ld2Cancel_3`。F34 GRH 的 `pattern-detect` 后证据显示，三个样本的一路输入均依赖 GRH `9782017`，这是 `split-nodes` 生成的 `loadDependency_2$1_1`。需在 06:20 运行的 GRH R4 核对三例是否仍保留，再比较该位切片与对应 FIRRTL 声明的结构和命名前驱。[GSIM 合并事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl) · [GRH 历史连接](../../ptmp/firrtl-ingest/F34/common-v3/grh/R2/connections.tsv)

06:51，组合修复通过第三轮验收。第四次 DCE 后同名率 **95.95073%（2,667,487 / 2,780,059）**，较本轮起点高 **6.74861 个百分点**，较上次尝试高 **4.59039 个百分点**。较上次消除 140,166 个未匹配节点，新增 672 个，同名命中净增 2,008 个，R4 余 112,572 个差异。15 个 pass 均通过耗时门，`common-expr` 为 92.34 秒，第四次 DCE 为 32.68 秒。BusyTable `2224922 → 2218800`、ROB `805319 → 1819755`、TLB `6545823 → 6577841` 均与 GSIM 的合并方向一致，最终清单只保留各自同名代表。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse.json) · [GRH 迁移事件](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse-focused/common-expr-lineage.tsv) · [样本 R4](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse-focused/grh-r4.tsv) · [耗时门记录](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse-focused/guard.json)

## 第 4 轮 · 2026-11-24 · 剩余赋值节点

起点 **95.95073%（2,667,487 / 2,780,059）**。剩余 112,572 个差异中，赋值 100,997 个（89.72%）、Mux 5,067 个（4.50%）、状态与存储 3,162 个（2.81%）、位切片与拼接 2,080 个（1.85%）、其他组合逻辑 850 个（0.76%）、常量 416 个（0.37%）。赋值类中，64,496 个名字最后出现在 GSIM `CommonExpr` 输入，14,899 个出现在第四次 DCE 输入，13,049 个出现在 `AliasAnalysis` 输入。[分类与最后出现边界](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse.json)

预取的 `fpBusyTable` 三例中，GRH 已将 `_1413` 与 `_1420` 合并到 `_1427`；余下的 `_1427` 在第四次 DCE 后仍存活。GSIM 代表对应的 GRH `4450576` 也在本次 `common-expr` 合并到另一组代表 `3761855`。后续需比较两组的输入与代表选择。[GRH 样本事件](../../ptmp/firrtl-ingest/F35/measure-tests/unnamed-copy-cse-focused/common-expr-lineage.tsv) · [冻结 GSIM 样本事件](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-context/gsim-common-expr-events.jsonl)

### 三个样本与门控

从起点仍保留的 `cpu.l_soc.core_with_l2.core.backend.inner.ctrlBlock.dispatch.fpBusyTable` 赋值中选三个不同输入位组。GRH 和 GSIM 的来源均为 `SimTop.fir` 的 `BusyTable_1` 组合逻辑。GRH 的 `hier-flatten` 将模块内 ID 迁入 `SimTop`。GSIM 在 `CommonExpr` 中退役三个样本，代表均位于 `cpu.l_soc.core_with_l2.core.backend.inner.fpRegion.issueQueueFEX3_FaluFmac.entries.othersEntriesComp_15`，并在第四次 DCE 后存活。[GRH 来源](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/sources.tsv) · [GSIM 来源](../../ptmp/firrtl-ingest/F35/gsim-reference/init-node-origins.tsv) · [GSIM 合并事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl) · [GSIM R4 库存](../../ptmp/firrtl-ingest/F35/gsim-reference/dce-3/after.nodes.tsv)

| 样本 | FIRRTL 行 | GRH 模块内 → 扁平 ID | GSIM 样本 → 代表 ID | GSIM 代表名的最后一段 |
| --- | ---: | --- | --- | --- |
| `tmp_ld2Cancel_1424` | 3,266,538 | `37654 → 2340340` | `2235836 → 4432477` | `common_srcLoadTransCancelVec_2_ld2Cancel` |
| `tmp_ld2Cancel_1425` | 3,266,564 | `37680 → 2340366` | `2235862 → 4432494` | `common_srcLoadTransCancelVec_2_ld2Cancel_1` |
| `tmp_ld2Cancel_1427` | 3,266,616 | `37732 → 2340418` | `2235914 → 4432528` | `common_srcLoadTransCancelVec_2_ld2Cancel_3` |

三个样本在 GSIM 都从 `Init` 留到 `CommonExpr` 输入。GRH 的 `split-nodes` 生成了供 BusyTable 使用的位切片，IssueQueue 的等价 FIRRTL 声明则另有一个 `kAssign` 封装。以 `_1427` 为例，位切片 `9782017` 与封装的位切片 `4450573` 均依赖 `9589640`。`_1424` 和 `_1425` 的切片分别来自 `9577938`–`9577940` 和 `9581838`–`9581840`。两种形态在 `common-expr` 的具名前驱分组中失配。三个直接样本均为组合取消条件，分歧来自相同位的表示和比较，两端均可保留等价计算及其消费者，因此通过必要特性门控。[双端清单及来源](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection) · [GRH 拆位事件](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-split-event.tsv) · [GRH 三组入口连接](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-retry-input-connections.tsv)

### 修复、耗时与复测

`common-expr` 比较具名前驱时识别从同一来源位读取的直接 `kSliceStatic` 与同类型 `kAssign` 封装切片。原位段绑定和物理分组仍按原有规则处理。`grh-semantic-tree` 与 `transform-f34-common-expr` 定向回归通过。07:14 启动 GRH 全量复测 `f35-grh-dc7e15b1d20e417f900f777faf68f074`，复测使用已冻结的 GSIM 参考。全图结果待采集完成。[定向回归](../../ptmp/firrtl-ingest/F35/static-projection-cse/tests/test.log) · [GRH 运行日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-dc7e15b1d20e417f900f777faf68f074/grh.log)

07:40，首次复测在 `common-expr` 遇到无定义操作的输入值，读其操作类型时中断。修正后另用最小图复现了封装切片与其下游赋值共享同一个表达式键时的自环。封装赋值现在使用独立的根键，下游比较仍可识别同一源切片。补充内部直接输入赋值和自环回归后，两项定向测试通过。07:50 启动复测 `f35-grh-c610e3c0f5e1421090813fe06bdd7712`，沿用已冻结的 GSIM 参考，并串接全图对账和三个样本及代表名的复核。[首次中断日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-dc7e15b1d20e417f900f777faf68f074/grh.log) · [修复后回归](../../ptmp/firrtl-ingest/F35/static-projection-cycle-fix/tests/test.log) · [当前复测](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-c610e3c0f5e1421090813fe06bdd7712/grh.log)

08:20，全图同名率 **95.97721%（2,667,555 / 2,779,363）**，较本轮起点提高 **0.02647 个百分点**。消除 806 个未匹配名，新增 42 个，同名命中净增 68 个。剩余 111,808 个差异，其中赋值 100,233 个（89.65%），63,740 个赋值名称最后见于 GSIM `CommonExpr` 输入。15 个 pass 均通过耗时门，`common-expr` 为 96.99 / 221.33 秒，第四次 DCE 为 32.13 / 63.01 秒。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/static-projection-cse.json) · [耗时记录](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-static-projection-retry-guard.json)

三个 BusyTable 样本仍在 GRH R4。三个 GSIM 代表对应的 GRH 名称分别在 `common-expr` 由 `4450525`、`4450542`、`4450576` 迁移到 `3761804`、`3761821`、`3761855`，三组后续共享值连接到 BusyTable 样本，两个 GRH 名称都留在第四次 DCE 后。样本验收失败。离线重放 69,325 对 GSIM CSE 差异，`split-static-array` 后有 62,910 对先访问 GSIM 代表，`common-expr` 入口为 54,269 对。下一次验证更早的拓扑排名能否修正具名代表选择，并核对已经对齐的节点是否回退。[复测样本](../../ptmp/firrtl-ingest/F35/measure-tests/static-projection-cse-samples.json) · [迁移链](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/retry-busytable-lineage.tsv) · [R4 去留](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-static-projection-retry-r4.tsv) · [数组拆分后排序](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/residual-grh-array-order.log) · [CSE 入口排序](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/residual-grh-cse-order.log)

08:32，启动提早记录拓扑顺序的候选 `f35-grh-7fb53aab55924c43919d383a8fceac40`。`split-static-array` 在完成 FIRRTL 数组转换时保存具名节点的依赖排名。`common-expr` 仍按当前依赖识别等价组，在整组成员都有早期排名时使用它选择代表。新增定向用例覆盖前驱节点退役后遍历顺序改变，检查代表名和三条输出。`make test_f34_passes` 通过 5 项。此候选沿用冻结的 GSIM 参考和第四轮起点对账。[回归](../../ptmp/firrtl-ingest/F35/early-cse-order-regression/tests/test.log) · [当前复测](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-7fb53aab55924c43919d383a8fceac40/grh.log)

09:02，第四次 DCE 后全图同名率为 **96.01315%（2,668,554 / 2,779,363）**，较第四轮起点提高 **0.06242 个百分点**，较上一候选提高 **0.03594 个百分点**。相对本轮起点消除 2,752 个未匹配名，新增 989 个，净减少 1,763 个差异。剩余 110,809 个差异，赋值 99,234 个，占 89.55%。15 个 pass 均通过耗时门，`common-expr` 为 99.34 / 221.33 秒，第四次 DCE 为 31.75 / 63.01 秒。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/early-cse-order.json) · [耗时记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-7fb53aab55924c43919d383a8fceac40/guard.json)

第四次 DCE 后仍保留 `tmp_ld2Cancel_1424`、`_1425`、`_1427`。三个 GSIM 代表名在 GRH 的对应节点 `4450525`、`4450542`、`4450576` 已由 `common-expr` 合并到 `othersEntriesSimp_1` 的 `4416637`、`4416654`、`4416688`。提早记录拓扑顺序改变了 IssueQueue 侧代表，三个 BusyTable 样本的最终去留未变，第四轮仍未通过验收。下一次归因先核对 BusyTable 与 IssueQueue 两组是否进入同一个等价组，再判断代表选择。[最终 Node 清单](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-early-order-r4.tsv) · [GRH 合并事件](../../ptmp/firrtl-ingest/F35/measure-tests/fpBusyTable-projection/grh-early-order-common-expr-lineage.tsv)

09:29，启动候选 `f35-grh-59700418f0e6473985cdf3c5c0786e4d`。本次修正 `split-static-array` 记录的拓扑顺序。原有节点按名称进入工作列表，拆分新增节点按创建顺序追加。对冻结 GSIM 的 398,413 个可比较合并对离线重放，共 389,253 对的 GSIM 代表排在对应重复名之前（97.70%，此前为 94.10%）。三个 BusyTable 样本对应的 GSIM 代表均排在各自 528 个成员首位。仍需用 GRH 的 `common-expr` 事件和 R4 清单验证实际归组、合并及代表去留。[三个样本的排序重放](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/busy-cohorts-grh-split-order.log) · [排序重放汇总](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/all-grh-array-split-order.log)

本次采集同时纳入两项改动。其一，`common-expr` 使用解析后的语义连接，为缺少显式边界行的静态位切片识别来源。其二，`alias-analysis` 沿同类型赋值追到静态索引的寄存器读，核对唯一语义前驱，保留原始读和下标并退役转发名。在 08:32 候选上核实了 809 个唯一前驱候选，其对应的 35 个寄存器代表名在双端 R4 均存在。复测独立核对 AliasAnalysis 迁移和最终去留。包构建成功，继续使用同一份冻结 GSIM 参考。[位切片回归](../../ptmp/firrtl-ingest/F35/resolved-projection-source/tests/test.log) · [索引别名回归](../../ptmp/firrtl-ingest/F35/wrapped-state-alias/tests/test.log) · [809 个别名与代表](../../ptmp/firrtl-ingest/F35/measure-tests/remaining-alias/early-order-single-index-alias-map.tsv) · [本次运行日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-59700418f0e6473985cdf3c5c0786e4d/grh.log)

拆分排序回归直接运行 `split-static-array`，比较 `lanes_2` 和 `lanes_10` 的访问顺序。两者在同一前驱处理后就绪，后创建的 `lanes_10` 先出栈。`make test_f34_passes` 的 5 项回归全部通过，`make test_f35_tools` 的 18 项检查全部通过。[定向回归](../../ptmp/firrtl-ingest/F35/split-order-regression/tests/test.log) · [采集与对账工具检查](../../ptmp/firrtl-ingest/F35/launch/tool-tests.log)

10:00，全图同名率为 **96.07719%（2,669,447 / 2,778,440）**，较本轮起点提高 **0.12645 个百分点**，较上一候选提高 **0.06404 个百分点**。相对本轮起点消除 4,399 个未匹配名，新增 820 个，净减少 3,579 个差异。三个 BusyTable 样本 `2340340`、`2340366`、`2340418` 在 `common-expr` 分别合并到 `4450525`、`4450542`、`4450576`，第四次 DCE 后双端保留同名代表。15 个 pass 均通过耗时门，`common-expr` 为 76.23 / 221.33 秒，第四次 DCE 为 32.63 / 63.01 秒。第四轮通过验收。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/split-creation-order.json) · [合并事件](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/split-creation-order-lineage.tsv) · [R4 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round4-busy-table/split-creation-order-r4.tsv) · [耗时记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-59700418f0e6473985cdf3c5c0786e4d/guard.json)

三处静态索引别名样本 `hitVecT_is_global_32`、`_store_hit_0_eq_T_1`、`_dataWriteQueue_io_enq_bits_rawData_0_T` 均由 GRH `alias-analysis` 迁到源寄存器名，三处代表均保留至 R4。809 个候选名称中有 793 个在 `alias-analysis` 后退役，R4 仍可找到 16 个候选名称。[双端前序证据](../../ptmp/firrtl-ingest/F35/measure-tests/remaining-alias/wrapped-state-baseline-samples.json) · [GRH 合并事件](../../ptmp/firrtl-ingest/F35/measure-tests/remaining-alias/wrapped-state-retest-lineage.tsv) · [R4 剩余候选](../../ptmp/firrtl-ingest/F35/measure-tests/remaining-alias/wrapped-state-retained-r4.tsv)

## 第 5 轮 · 2026-11-24 · 剩余赋值节点

起点为第四轮验收的 **96.07719%（2,669,447 / 2,778,440）**。108,993 个差异中，赋值 97,425 个（89.39%）、Mux 5,060 个、状态与存储 3,162 个、位切片与拼接 2,080 个、其他组合逻辑 850 个、常量 416 个。赋值名称最后出现最多的边界依次为 GSIM `CommonExpr` 输入（61,784 个）、第四次 DCE 输入（14,833 个）、`AliasAnalysis` 输入（12,256 个）。本轮优先取样 `CommonExpr` 输入中的赋值。[起点全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/split-creation-order.json)

### 基线复测与三样本

首次补齐第五轮基线 GRH 采集并对账，R4 同名率为 **96.23770%（2,667,940 / 2,772,240）**，未匹配 104,300 个，其中赋值 92,774 个。相对第四轮候选消除 4,727 个差异名并新增 34 个，比例提高 0.16051 个百分点。GRH 15 个生产 pass 均在双倍耗时预算内完成，峰值 RSS 为 97,923 MiB，没有使用 swap。对账峰值 RSS 为 1,332 MiB，耗时 1 分 53 秒。[基线对账](../../ptmp/firrtl-ingest/F35/measure-tests/round5-current.json) · [基线差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round5-current-unmatched.tsv) · [GRH 守卫](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-44a1ec712d2044629c65aa1c9b1ee11a/guard.json) · [采集内存记录](../../ptmp/firrtl-ingest/F35/launch/grh-resume-memory.log) · [对账内存记录](../../ptmp/firrtl-ingest/F35/launch/compare-round5-current-memory.log)

按最大差异类抽取了 DTLB 命中比较、PTW 地址拼接、译码异常向量三个赋值样本。全路径回溯覆盖 GRH 的 ingest、15 个 pass 和冻结 GSIM 的 Init、生产 pass，确认前两例是有值锚点的一位和三位赋值，第三例为 operation-only 赋值。源证据将 DTLB 例定位到 `SimTop.fir` 第 7,837,114 行，将 PTW 例定位到第 7,152,436 行。译码例关联到 `latchedInst.exceptionVec` 和 `csBundle.exceptionVec` 声明及其逐项连接，需继续沿状态及连接消费者核对其保留要求。回溯耗时 21 分 25 秒，峰值 RSS 为 251 MiB，换页计数为 0。全路径样本文件来自后续替换前的 GRH 运行，保留作基线证据。它不作为当前候选的样本复测结果。[基线样本全路径](../../ptmp/firrtl-ingest/F35/measure-tests/round5-current-samples.json) · [样本回溯内存记录](../../ptmp/firrtl-ingest/F35/launch/samples-round5-current-memory.log)

### 尝试 1 · 双成员赋值名

命名 CSE 审计覆盖 GSIM 66,606 个合并事件。当前 GRH 有 23,757 个合并对具有相同命名前驱但不同赋值锚点，其中 DTLB VMID 命中组是代表缺口样本。将具名等价组的双成员门限放宽到纯 `kAssign` 组，保留其他操作类型的一消费者保护、代表排序、端口保护和状态边界检查。新增最小图回归让两个具名赋值汇入同一个 XOR 消费者，验证双槽位改写和输出语义。F34 pass 回归 5 项通过，F35 工具测试 19 项通过。[CSE 形态审计](../../ptmp/firrtl-ingest/F35/measure-tests/round5-cse-audit/audit.log) · [具名 CSE 实现](../../wolvrix/lib/transform/common_expr.cpp) · [最小图回归](../../wolvrix/tests/transform/f34_common_expr.cpp) · [F34 回归日志](../../ptmp/firrtl-ingest/F35/launch/round5-named-pair-regression.log) · [F35 工具测试](../../ptmp/firrtl-ingest/F35/launch/tool-tests-round5.log)

复测 R4 同名率为 **96.28745%（2,525,253 / 2,622,619）**，未匹配 97,366 个。相对本次候选起点比例提高 0.04975 个百分点，消除 7,313 个差异名并新增 379 个。15 个 pass 全部通过耗时门，CommonExpr 为 87.49 秒，第四次 DCE 为 30.88 秒。峰值 RSS 为 92,949 MiB，没有使用 swap。全图对账峰值 RSS 为 1,304 MiB，耗时 1 分 53 秒。[候选对账](../../ptmp/firrtl-ingest/F35/measure-tests/round5-named-pair.json) · [候选差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round5-named-pair-unmatched.tsv) · [候选守卫](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-afcb7b646a8e4cfda9467edae3595410/guard.json) · [采集内存记录](../../ptmp/firrtl-ingest/F35/launch/grh-round5-named-pair-memory.log) · [对账内存记录](../../ptmp/firrtl-ingest/F35/launch/compare-round5-named-pair-memory.log)

门控仍未通过。替换后全图清单显示 `cpu.l_soc.core_with_l2.core.memBlock.inner.dtlb_ld_tlb_ld.entries.page_ldtlb_storage_fa._hitVec_hit_vmid_hit_T` 和其同输入例 `_hitVec_hit_vmid_hit_T_96` 均留在 GRH R4，且同名 GSIM R4 均不存在。对当前候选 CommonExpr 边界的定向查询也确认二者都仍存活。最初三样本全路径报告属于旧运行，不能证明当前候选的样本状态，后续应在修复后用当前捕获和报告重查。[当前候选三样本查询](../../ptmp/firrtl-ingest/F35/measure-tests/round5-named-pair-focused.json) · [DTLB 对照查询](../../ptmp/firrtl-ingest/F35/measure-tests/round5-named-pair-cse-pairs.json)

### 尝试 2 · 静态索引寄存器读

原始 FIRRTL 第 7,837,114 和 7,857,136 行的两条 VMID 比较都读取 `entries[0].vmid`，并与 `io.csr.hgatp.vmid` 比较。GRH 为同一数组项的两次读取生成独立的 `kRegisterReadArrayPort` 和 ValueId，导致表达式未进入同一等价组。具名比较的读取操作也可能只由表达式节点拥有，存储来源由读取上的语义数据边界标识。[原始 FIRRTL](../../build/xs/rtl/rtl/SimTop.fir#L7837114) · [DTLB 输入证据](../../ptmp/firrtl-ingest/F35/measure-tests/round5-cse-audit/vmid-grh-inputs.tsv)

CommonExpr 已为同一寄存器、相同范围内常量下标和相同逻辑类型的完整索引读取建立结构键。动态索引继续按 ValueId 比较。具名节点退役前检查读取的存储所有权或读取上的语义数据边界。全图采集曾用约 91 GiB 峰值 RSS，本次先用保留数组读形态的跨实例 FIRRTL 小图验证。全图 DTLB 样本门控和 99.00% 交付门槛仍待验证。[CommonExpr 实现](../../wolvrix/lib/transform/common_expr.cpp)

跨实例 FIRRTL 回归确认每个寄存器的三个重复 VMID 比较在 CommonExpr 和 DCE 后保留一个名字。两个实例写入不同数据，逐项检查静态索引 0、静态索引 1 和动态索引读的输出。F34 pass 回归 5 项通过，构建与测试的最大单进程 RSS 为 376 MiB。F35 工具测试 19 项通过，最大单进程 RSS 为 73 MiB。两次测试的换页计数均为 0。[FIRRTL 小图](../../wolvrix/tests/transform/data/f34-common-expr-array-read.fir) · [F34 结果](../../ptmp/firrtl-ingest/F35/round5-static-read-f34/tests/test.log) · [F34 内存记录](../../ptmp/firrtl-ingest/F35/launch/round5-static-read-f34-memory.log) · [F35 结果](../../ptmp/firrtl-ingest/F35/round5-static-read-tools/launch/tool-tests.log) · [F35 内存记录](../../ptmp/firrtl-ingest/F35/launch/round5-static-read-tool-memory.log)

从原始 `SimTop.fir` 流式提取 `TLBFA_1`，对修复前后的库分别运行 15 个生产 pass。修复前的三个名字均保留到第四次 DCE。修复后，`_hitVec_hit_vmid_hit_T`（336）和 `_hitVec_hit_vmid_hit_T_96`（19440）在 CommonExpr 退役，与 GSIM 所选同名的代表 `_w_hit_vec_vmid_hit_T`（38702）保留至第四次 DCE。两次运行峰值 RSS 分别为 535 MiB 和 522 MiB，均无换页。该结果覆盖原始模块内部的运算和消费者，全图仍需核对实例连接及其余两个样本。[修复前记录](../../ptmp/firrtl-ingest/F35/round5-real-dtlb/baseline/result.json) · [修复后记录](../../ptmp/firrtl-ingest/F35/round5-real-dtlb/candidate/result.json) · [修复后内存记录](../../ptmp/firrtl-ingest/F35/round5-real-dtlb/candidate.memory.log)

香山全图采集 `f35-grh-cc9272a9019e4d699857e9a10655f5a5` 耗时 27 分 59 秒。15 个 pass 均通过耗时门，CommonExpr 为 107.70 秒，第四次 DCE 为 30.31 秒。本次直接运行 `f35_grh_capture`，串行完成采集、对账和样本回溯。采集峰值 RSS 为 98.77 GiB，较上次增加约 8.00 GiB。对账耗时 1 分 54 秒，峰值 RSS 为 1,268 MiB。两次定向样本复查峰值各约 43 MiB。各任务换页计数均为 0。[采集守卫](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-cc9272a9019e4d699857e9a10655f5a5/guard.json) · [采集内存](../../ptmp/firrtl-ingest/F35/launch/grh-round5-static-read-memory.log) · [对账内存](../../ptmp/firrtl-ingest/F35/launch/compare-round5-static-read-memory.log) · [样本回溯内存](../../ptmp/firrtl-ingest/F35/launch/samples-round5-static-read-memory.log)

R4 同名率为 **97.23956%（2,510,073 / 2,581,329）**，比本轮基线 96.23770% 提高 **1.00186 个百分点**，比上次候选提高 **0.95211 个百分点**。相对上次候选消除 26,110 个未匹配名称行，新增 0 个，同名命中数减少 15,180 个。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round5-static-read.json) · [差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round5-static-read-unmatched.tsv)

| R4 差异类 | 数量 | 占比 | 较上次候选 |
| --- | ---: | ---: | ---: |
| 赋值 | 59,739 | 83.84% | −26,106 |
| Mux | 5,060 | 7.10% | 0 |
| 状态与存储 | 3,160 | 4.43% | −2 |
| 位切片与拼接 | 2,031 | 2.85% | −2 |
| 其他组合逻辑 | 850 | 1.19% | 0 |
| 常量 | 416 | 0.58% | 0 |

| 样本 | 全图复测结果 |
| --- | --- |
| DTLB VMID 比较 | GRH CommonExpr 将 6507563 和 6526667 合并至 6545929，两条重复名退役，代表 `_w_hit_vec_vmid_hit_T` 保留到 R4，与 GSIM 6602745 同名。 |
| PTW 地址低位拼接 | GRH CommonExpr 将样本 5642836 和 GSIM 同名代表 5644344 的计算共享到 5642692，两条名称均保留至 R4。GSIM 在 CommonExpr 将样本 5729470 合并至 `_v_equal_T_103`（5730979）并退役。 |
| 译码异常向量 | GRH `csBundle.exceptionVec_0_0`（8144190）和 `latchedInst.exceptionVec_0`（9520048）经过 AliasAnalysis 并保留到 R4。GSIM 在 AliasAnalysis 将样本 8303628 作为恒等别名合并至 8303467 并退役。 |

DTLB 已通过样本复测，第五轮整体门控仍未通过。PTW 的差异已缩小到具名退役，译码样本需要核对 operation-only 赋值的连接、状态绑定和位段范围。[CommonExpr 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round5-static-read-focused.json) · [AliasAnalysis 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round5-static-read-alias.json) · [GSIM 原生事件摘录](../../ptmp/firrtl-ingest/F35/measure-tests/round5-current-samples.json)

沿 PTW 地址拼接追溯到重复 OneHot 链的低四位切片。`split-static-array` 前，GRH 节点 5642683、5642827 和 5644335 分别依赖各自的八位拼接。拆分后三者都依赖 `pteidx` 第 0 至 3 位（9109021 至 9109024）。CommonExpr 让三者共享同一个四位值，三个名字均保留至 R4。GSIM 在 CommonExpr 将对应的 5729317 和 5729461 合并至 `v_equal_lo_24`（5730970）。GRH 的命名分组读取显式语义边界，调度使用解析后的连接。两套前驱表示的差异是后续最小图复现的检查点。[GRH 样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round5-static-read-focused.json) · [GSIM 合并事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/evolution.tsv#L2930051)

从原始 FIRRTL 提取 `DecodeUnitComp` 后复现了译码样本。`split-static-array` 后，`csBundle.exceptionVec_0_0`（11164）仍有一位 `kAssign` 锚点。操作 138694 直接把源寄存器读值 151310 赋给锚值 138666。第一次 DCE 移除了该锚点，名称以 operation-only 形式经过 AliasAnalysis 并保留至 R4。R4 所列操作 151468 属于异常向量的另一段打包，节点也仍是低两位打包操作 151465 的所有者。两段打包操作各有 1,495 个语义所有者。源寄存器 `latchedInst.exceptionVec_0`（24164）在 R4 保留一位 `kRegisterReadPort` 锚点。源 FIRRTL 先连接 `csBundle[0]` 与 `latchedInst`，随后单独覆盖异常向量第 2 位。定向采集耗时 2.29 秒，峰值 RSS 为 404 MiB，换页计数为 0。[FIRRTL 模块](../../ptmp/firrtl-ingest/F35/round5-real-decoder/sample.fir#L2023) · [拆分后端点](../../ptmp/firrtl-ingest/F35/round5-real-decoder/split-static-array%230/node-endpoints.tsv#L10970) · [第一次 DCE 后端点](../../ptmp/firrtl-ingest/F35/round5-real-decoder/dead-code-elim%230/node-endpoints.tsv#L10839) · [拆分后赋值](../../ptmp/firrtl-ingest/F35/round5-real-decoder/split-static-array%230/node-details.jsonl#L2121) · [R4 打包操作](../../ptmp/firrtl-ingest/F35/round5-real-decoder/dead-code-elim%233/node-details.jsonl#L385) · [阶段记录](../../ptmp/firrtl-ingest/F35/round5-real-decoder/inspect.log) · [内存记录](../../ptmp/firrtl-ingest/F35/round5-real-decoder/memory.log)

按新的模块优先流程，用同一份独立 `DecodeUnitComp` FIRRTL 重新采集双端。GSIM 在 AliasAnalysis 退役 `csBundle.exceptionVec_0_0`（11428），GRH 将该名称（11164）保留至第四次 DCE，两端均保留 `latchedInst.exceptionVec_0`。该样本的全图差异已在模块内复现，后续可在该模块调试。双端各完成 15 个 pass，耗时 26.42 秒，最大单进程 RSS 为 1.49 GiB，换页计数为 0。[模块采集](../../ptmp/firrtl-ingest/F35/captures/paired-decoder-original/summary.json) · [双端样本回溯](../../ptmp/firrtl-ingest/F35/captures/paired-decoder-original/decoder-samples.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/paired-decoder-original-memory.log)

### 尝试 3 · 译码异常向量的标量别名

在 `split-static-array` 末尾使用仍存在的赋值锚点识别同类型的一位寄存器读别名。仅处理可迁移的数据引用，将共享打包操作的归属留给现有所有者或可追溯的下游消费者。无可观察消费者的纯打包链由下一次 DCE 清除。FIRRTL 回归覆盖整个字段复制、单独覆盖一位和动态选择，检查两种选择下的输出及寄存器源。共通过六项定向回归。[实现](../../wolvrix/lib/transform/split_static_array.cpp#L773) · [回归结果](../../ptmp/firrtl-ingest/F35/decoder-forwarding-tests/tests/test.log)

真实 `DecodeUnitComp` 重采 GSIM 和 GRH，各完成 15 个 pass。`csBundle.exceptionVec_0_0` 在 GRH 的数组拆分完成时退役，两端均将寄存器源 `latchedInst.exceptionVec_0` 保留到第四次 DCE。模块同名数为 2,706，未匹配数由 1,512 降至 17，同名率由 64.15363% 升至 99.37569%。采集耗时 25.53 秒，峰值 RSS 为 1.49 GiB，换页计数为 0。[模块对账](../../ptmp/firrtl-ingest/F35/captures/paired-decoder-forwarding/comparison.json) · [模块采集](../../ptmp/firrtl-ingest/F35/captures/paired-decoder-forwarding/summary.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/decoder-forwarding-paired-memory.log)

香山 GRH 全图复测复用冻结的 GSIM 参考，候选产物存入独立目录供对照。15 个 pass 均通过原耗时门。`split-static-array#0` 用时 90.97 秒，预算 232.99 秒。全图采集用时 28 分 29 秒，峰值 RSS 为 98.48 GiB。对账用时 1 分 54 秒，峰值 RSS 为 1,263 MiB。两步换页计数均为 0。[采集守卫](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-5656c2dc0db34c3aa552ac4647677e54/guard.json) · [采集内存](../../ptmp/firrtl-ingest/F35/launch/grh-round5-decoder-forwarding-memory.log) · [对账内存](../../ptmp/firrtl-ingest/F35/launch/compare-round5-decoder-forwarding-memory.log)

全图 R4 同名率为 **97.29591%（2,510,073 / 2,579,834）**，比尝试 2 提高 **0.05635 个百分点**，比本轮基线提高 **1.05821 个百分点**。退役 1,495 个原未匹配赋值名，新增差异名为 0，同名数保持 2,510,073。全图数组拆分完成时译码别名已退役，寄存器源在双端 R4 存活。DTLB 的两个重复名仍退役且代表名存活，PTW 地址拼接仍有一个重复名保留到 GRH R4，第五轮样本门控仍未通过。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round5-decoder-forwarding.json) · [差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round5-decoder-forwarding-unmatched.tsv) · [样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round5-decoder-forwarding-focused.json)

### PTW 地址拼接的模块级复现

按模块优先流程从原始 SimTop.fir 提取 L2TLB，重新采集 GSIM 与 GRH。复位从原图的 ResetGen.o_reset : AsyncReset 沿 SimTop → XSTile → XSCore → MemBlock → MemBlockInlined → L2TLBWrapper → L2TLB 传递，隔离采集按 reset=AsyncReset 绑定，并加载 ClockGate.sv。双端都完成 15 个 pass。采集耗时 50.17 秒，峰值 RSS 1,554,904 KiB，无换页。模块级 R4 对账为 **82.97395%（28,475 / 34,318）**，未匹配 5,843 个。边界快照分析耗时 16.94 秒，峰值 RSS 45 MiB，无换页。[双端采集摘要](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/summary.json) · [模块对账](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/comparison.json) · [样本复核](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/ptw-samples.json) · [采集资源](../../ptmp/firrtl-ingest/F35/launch/paired-ptw-original-memory.log) · [分析资源](../../ptmp/firrtl-ingest/F35/launch/paired-ptw-analysis-memory.log)

模块双端样本确认当前只剩两个目标名未对齐：GRH R4 保留 ptw_sector_resp_addr_low_lo（6912）和 _ptw_sector_resp_addr_low_T_7（6921），GSIM R4 不含这两个名字。另两个邻近代表 v_equal_lo_24 与 _v_equal_T_103 已分别对齐到 GSIM 节点 78922 和 78931。CommonExpr lineage 中出现了 6921 → 6777 和 6912 → 6768 的 merge 关系，但同一采集的 after.nodes 与 R4 仍包含源 Node，因此这些事件不能解释为目标名称已退役。此处节点 ID 属于模块采集，与旧全图 ID 不可互换。[模块 CommonExpr lineage](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/grh/common-expr%230/L2TLB/evolution.tsv) · [CommonExpr 后节点清单](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/grh/common-expr%230/L2TLB/after.nodes.tsv) · [模块 R4 名称清单](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/grh/R4/nodes.tsv)

被合并的是表达式实现，具名 Node 仍在 CommonExpr 后及 R4 存活。ptw_sector_resp_addr_low_lo 的操作锚值由四个位拼接实现，_ptw_sector_resp_addr_low_T_7 的操作拼接 T_1 与 T_6 两段。当前活动依赖边显示 low 节点消费四个位拆分结果，3-bit 节点消费两个子段。边界探针另记录了语义边界与活动图连接的差别。下一步需定位哪些边界种类参与命名分组及操作 Node 归属，不能把现象归因于单纯的旧拼接前驱。[模块连接快照](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-original/grh/common-expr%230/L2TLB/before.connections.tsv) · [边界探针 JSON](../../ptmp/firrtl-ingest/F35/ptw-boundary-probe/before-common-expr.json)

局部修复尝试沿 anchor 追踪 identity assignment 到等价表达式，并放宽 operation-owned concat 的 named-result 资格。候选的首次版本导致既有 CommonExpr 用例 namedExpressionRetirement 的来源合并断言失败。后续窄化版本仍因退役 Node 时保留 live members 而失败，未能正确迁移 concat/identity-assign 的成员归属。两版候选都已撤销。恢复后的 transform-f34-common-expr 单项回归通过，耗时 13.23 秒，峰值 RSS 525,644 KiB，无换页。没有留下 PTW 逻辑修复，也没有运行全图复测。当前待查点是如何在保留 Node/anchor/语义绑定不变量的前提下处理共享 concat 的 operation ownership。[回归结果](../../ptmp/firrtl-ingest/F35/ptw-common-expr-regression/tests/test.log) · [回归构建日志](../../ptmp/firrtl-ingest/F35/ptw-common-expr-regression/tests/build.log) · [回归资源](../../ptmp/firrtl-ingest/F35/launch/ptw-common-expr-regression-memory.log)

### PTW 地址拼接的结构化前驱复核

使用 F35 模块重放显式加载当前构建库后，确认两个目标都通过 `ordinaryNamedResult` 候选检查并进入拓扑顺序。此前按具名来源节点组成的前驱签名把每个目标分成单节点 cohort。GSIM 的 CommonExpr 轨迹显示，目标 `_ptw_sector_resp_addr_low_T_7` 的两个上游节点都已分别归并到具名等价来源，因此复核重点转到 GRH 命名分组如何表示这些输入。[GSIM CommonExpr 变更](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-l2tlb-current-v2/gsim/common-expr/native-mutations.jsonl) · [L2TLB CommonExpr 前连接](../../ptmp/firrtl-ingest/F35/captures/paired-ptw-l2tlb-current-v2/grh/common-expr%230/L2TLB/before.connections.tsv)

命名 cohort 现在以带值的 `data` 语义边界所引用的结构表达式作为前驱键。无值边界仍用语义节点身份。L2TLB 日志确认原先 219 个不同具名前驱签名归并为同一个 219 节点 cohort，两个目标名都在 CommonExpr 后退役，并继续缺席 R4。修复源码位于 [common_expr.cpp](../../wolvrix/lib/transform/common_expr.cpp)，新增回归覆盖多个具名来源节点引用同一结构输入值的情形，见 [f34_common_expr.cpp](../../wolvrix/tests/transform/f34_common_expr.cpp)。

清理所有临时诊断后，重新构建的动态库 SHA-256 为 `162279523dfc95b2e0f15bb46993dcb581a141e690bac08a45fbe7f96e4f88a6`。最终隔离重放耗时 11.05 秒，峰值 RSS 1,067,924 KiB。CommonExpr 耗时 0.33 秒。两个目标在 pass 前分别为 6912 和 6921，pass 后及 R4 均不存在。[最终模块摘要](../../ptmp/firrtl-ingest/F35/module-repro-ptw-final-verified/summary.json) · [模块启动日志](../../ptmp/firrtl-ingest/F35/launch/module-repro-20261124T204802716363205.log)

`test_f34_passes` 五项测试通过，`transform-f34-common-expr` 目标在加入回归后重新编译并单独通过。此结果只验证 L2TLB 模块样本和 CommonExpr pass。尚未运行全图重放或重新统计第五轮验收指标。[PTW 回归测试日志](../../ptmp/firrtl-ingest/F35/ptw-regression/tests/test.log) · [PTW 回归构建日志](../../ptmp/firrtl-ingest/F35/ptw-regression/tests/build.log)

### PTW 结构化前驱修复的全图复测

使用模块级验证时的动态库 SHA-256 `162279523dfc95b2e0f15bb46993dcb581a141e690bac08a45fbe7f96e4f88a6`，从同一份 SimTop FIRRTL 重采 GRH 全图，复用冻结的 GSIM 参考。15 个生产 pass 全部完成并通过原耗时门，`common-expr#0` 用时 95.41 秒。全图采集耗时 28 分 58 秒，峰值 RSS 95,755,792 KiB，无换页。R4 对账用时 1 分 52 秒，峰值 RSS 1,270,372 KiB。定向样本复查用时 33.79 秒，峰值 RSS 44,836 KiB。[GRH 守卫](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-6c67fe76e8764136af10b620fa2fdf46/guard.json) · [全图采集摘要](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-6c67fe76e8764136af10b620fa2fdf46/summary.json) · [采集资源](../../ptmp/firrtl-ingest/F35/launch/grh-round5-ptw-structural-keys-memory.log) · [对账资源](../../ptmp/firrtl-ingest/F35/launch/compare-round5-ptw-structural-keys-memory.log) · [样本资源](../../ptmp/firrtl-ingest/F35/launch/samples-round5-ptw-structural-keys-memory.log)

R4 同名数为 **2,508,693 / 2,561,121**，未匹配 **52,428**，较此前 69,761 个减少 17,333。相对旧未匹配索引，消除 21,153 行并新增 3,820 行。未匹配类别变化为 assignments 减少 18,414、slices-and-packing 增加 964、muxes 增加 118、constants 减少 1，其余类别不变。99.00% 交付目标未达到。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys.json) · [新未匹配索引](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys-unmatched.tsv)

样本复核确认，PTW 的 `ptw_sector_resp_addr_low_lo`、`ptw_sector_resp_addr_low_lo_1` 和 `_ptw_sector_resp_addr_low_T_7` 均在 GRH CommonExpr 后及 R4 消失，GSIM R4 也没有这三个名称。`_v_equal_T_103`、DTLB 的 `_w_hit_vec_vmid_hit_T` 以及译码源 `latchedInst.exceptionVec_0` 均在 GRH 与 GSIM R4 保留。两个 DTLB 重复名和译码别名 `csBundle.exceptionVec_0_0` 均在两端 R4 缺席。

PTW 样本 `v_equal_lo_24` 不符合预期的代表保留条件。GRH CommonExpr 将节点 5644335 合并到 `v_equal_lo_8`（5643292），GSIM R4 仍保留 `v_equal_lo_24`（5730970）。因此 GRH 的 `v_equal_lo_24` 在 R4 缺失，并新增未匹配名称 `v_equal_lo_8`。本轮虽然提升全图同名率，但样本门控未通过，不能作为第五轮成功基线。下一步应调整具名代表选择以保留 GSIM 对齐的代表，再重跑 F34 CommonExpr 回归、L2TLB 模块复现和全图复测。[样本复查报告](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys-focused.json)

### PTW 源结构与 GRH/GSIM IR 差异

回到 L2TLB 设计，PTW 选择器来自 `pte.pteidx` 的 8 项 one-hot 索引，不是电路接错。`merge_ptwResp_to_sector_ptwResp` 用 `OHToUInt(pte.pteidx)` 选择 entry，并把同一索引转成 `addr_low`；循环中的 `v_equal` 比较当前 entry 的有效位与被选 entry 的有效位。[L2TLB 设计](../../testcase/xiangshan/src/main/scala/xiangshan/cache/mmu/L2TLB.scala#L771) [OneHot 工具](../../testcase/xiangshan/utility/src/main/scala/utility/BitUtils.scala#L128)

FIRRTL lowering 将 8-bit 索引展开为二分归约树。`addr_low` 与 `v_equal` 都从 `pteidx[7:0]` 开始，以 `[7:4]`、`[3:0]` 分组，再合并为 4-bit 值，之后继续生成 2-bit 和最终索引。设计上这是两份 one-hot 转二进制表达式，四个位的含义和顺序相同，物理共享是正确的。不同消费者和下游计算仍使用各自的语义 Node。[隔离 L2TLB FIRRTL](../../ptmp/firrtl-ingest/F35/module-repro-ptw-final-verified/isolated.fir#L99560) [OneHot 降低片段](../../ptmp/firrtl-ingest/F35/module-repro-ptw-final-verified/isolated.fir#L100035)

GRH 把每个名称建成自己的物理操作链。模块重放中，`ptw_sector_resp_addr_low_lo`（6912）和 `v_equal_lo_8`（7377）的 4-bit anchor 都是直接从索引位拼接生成；`v_equal_lo_24`（8420）也有自己的等宽、同类型 concat。`_ptw_sector_resp_addr_low_T_7`（6921）是 3-bit concat，由两个被拆分的子结果组成。结构化前驱键让三种 4-bit 投影和等价 3-bit 拼接分别进入共享 cohort。

GSIM 也识别了同一物理等价关系，但它只共享物理实现并按 `sortedSuper` 中首次遇到的节点保留名称。对 4-bit 低位组，GSIM 把较早的 `v_equal_lo_8`（5729926）合并到后续的 `v_equal_lo_24`（5730970），并把 `ptw_sector_resp_addr_low_lo`（5729461）也合并到 `v_equal_lo_24`。因此两个 addr 名称退役，`v_equal_lo_24` 存活。GSIM 对 3-bit 组把 `_ptw_sector_resp_addr_low_T_7`（5729470）合并到 `_v_equal_T_103`（5730979）。[GSIM CommonExpr 合并事件](../../ptmp/firrtl-ingest/F35/gsim-reference/common-expr/native-mutations.jsonl#L586204)

两边不仅代表名选择不同，低位树的中间节点归并时机也不同。GRH 的节点 `_v_equal_T_32`（5643290）与 `_v_equal_T_96`（5644333）在 CommonExpr 前各有独立的 hi/lo 片段；GRH 将 `v_equal_lo_8`（5643292）与 `v_equal_lo_24`（5644335）先归为同一 4-bit cohort，并保留 5643292。GSIM 则先将 8-bit 根 `_v_equal_T_32`（5729924）与 `_v_equal_T_96`（5730968）归并到 5730968，随后把 `v_equal_lo_8` 归并到 `v_equal_lo_24`。这使 GSIM 后续的 `[3:2]` 与 `[1:0]` 汇总输入也使用已归并的中间代表。GRH 的未共享前驱身份和 GSIM 逐层更新后的代表身份在处理顺序上不同，因此最终可能得到相反的低位代表；它们仍是同一组 `pteidx` 低位上的合法 one-hot 归约计算。

GRH 当前优先使用 `firrtl.commonExprSourceOrder` 最小 rank。全图中 `v_equal_lo_8` 的 rank 早于 `v_equal_lo_24`，因此它反向选择 `v_equal_lo_8` 为代表，令 `v_equal_lo_24` 在 GRH R4 消失。这个全图副作用来自具名代表选择的遍历顺序，与 PTW 物理表达式是否相等无关。另一个表示细节是 GRH 将 split 的 `cat` anchor 保存为 concat 节点并用多个 bit 输入连接该 Node，GSIM 将同一关系编码在 `ExpTree` 的 `OP_CAT`/`OP_BITS` 子树；两边依赖共同的 `pteidx[3:0]`，操作结构均表达相同四位值。[GRH 代表选择](../../wolvrix/lib/transform/common_expr.cpp#L662) [GSIM 拓扑顺序](../../reference/gsim/src/topoSort.cpp#L10) [GSIM 表达式等价与代表合并](../../reference/gsim/src/commonExpr.cpp#L125)

本次差异的结论是：PTW 索引选择逻辑一致。结构层面，FIRRTL 的独立 `OneHot` lowering 产生多个同源 slice 和 concat。IR 层面，GRH 把拆分位片段表示为独立语义节点与活动 dependency edge，并把 split concat anchor 保留为操作，GSIM 将位片段关系表示在 `ExpTree` 的 `OP_CAT`/`OP_BITS` 子树中，按 `sortedSuper` 序逐层传播已选代表。CommonExpr 的分组门槛和逐层归并次序不同，使得等价节点的物理共享合法，但具名代表方向不同。对齐修复需要复现 GSIM 的代表选择与中间表达式传播，同时保留 GRH 的 value、operation 和 binding 不变量。全图采集、R4 对账和样本报告保留在上一节记录的产物中，本轮指标仍属探索性结果。

## 第 6 轮 · 2026-11-25 · 剩余赋值节点

本轮从第五轮最近一次全图 R4 差异索引继续抽样。该起点为 **97.95293%（2,508,693 / 2,561,121）**，未匹配 **52,428** 个，其中赋值 **39,830** 个（占未匹配数 75.97%）。抽样的三个赋值样本分别来自 Sc、DTLB `TLBFA_1` 和 PTW。按用户决定，本轮跳过 PTW 样本，不把第五轮 PTW 的结构分析计作第六轮工作。全图采集及验收状态见本轮末尾。[第五轮全图起点与分类](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys.json) · [第六轮抽样清单](../../ptmp/firrtl-ingest/F35/measure-tests/round6-assignment-samples.json)

### 样本与模块级复现

| 样本 | 局部复现结果 | 当前结论 |
| --- | --- | --- |
| `Sc._s0_biasIdx_T_1`（GRH 全图 R4 ID `544995`） | 从原始 FIRRTL 提取 `Sc` 及实例依赖后，GRH 和 GSIM 都在 `common-expr` 将 `_s0_pathIdx_T_4`（GRH 局部 ID `1299`、GSIM 局部 ID `13266`）并入各自选择的代表。GRH 保留 `_s0_biasIdx_T_1`（`1329`），GSIM 保留 `_s0_pathIdx_T_4`，并退役 `_s0_biasIdx_T_1`。GRH 全图 R4 仍有 `_s0_biasIdx_T_1`，GSIM R4 没有该名，因此差异在 Sc 模块内复现。 | 两个七位 `kAssign` 名称具有相同的 `shr` 表达式。GRH 的样本 Node 仍拥有 slice 与 assign 操作，且有寄存器写消费者。代表迁移与语义 Node、操作和消费者所有权如何协调仍待确认，不能仅凭表达式相同就将保留判为错误。隔离采集用时 23.11 秒，峰值 RSS 497,600 KiB，无 swap。[模块双端采集](../../ptmp/firrtl-ingest/F35/captures/round6-Sc/summary.json) · [Sc 样本对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-Sc-samples-local.json) · [全图样本复核](../../ptmp/firrtl-ingest/F35/measure-tests/round6-Sc-samples.json) · [采集资源](../../ptmp/firrtl-ingest/F35/launch/round6-Sc-memory.log) |
| `TLBFA_1._w_hit_vec_T_42`（GRH 全图 R4 ID `6546024`） | 原始模块双端采集显示 GRH 在 `common-expr` 退役 `_w_hit_vec_T_42`，并保留 `_w_hit_vec_T_1018`；GSIM 在 `common-expr` 和 R4 均保留这两个名称。对原始 `TLBFA_1` 的单 pass 重放也观察到 GRH 退役 `_w_hit_vec_T_42`。 | 模块范围内可复现了该名称的双端差异，但隔离的 `TLBFA_1` 输入没有呈现外层静态数组拆分产生的 lane 结构，不能据此认定全图等价 cohort 或安全的名称退役路径已被复现。双端采集用时 37.44 秒，峰值 RSS 684,256 KiB，无 swap。[模块双端采集](../../ptmp/firrtl-ingest/F35/captures/round6-TLBFA_1/summary.json) · [模块对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-TLBFA_1-comparison.json) · [GRH 单 pass 重放](../../ptmp/firrtl-ingest/F35/module-repro/round6-TLBFA_1-pair/summary.json) · [采集资源](../../ptmp/firrtl-ingest/F35/launch/round6-TLBFA_1-memory.log) |
| `ptw.ptw.resp_pte_r$NEXT` | 本轮按用户决定跳过，没有启动第六轮 PTW 模块采集或样本复核。 | 不纳入第六轮样本门控结论。第五轮 PTW 证据仍保留在第五轮记录中。[第五轮 PTW 样本复核](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys-focused.json) |

Sc 采集的 `Sc` 模块 R4 同名率为 **84.52514%（13,617 / 16,110）**，未匹配 2,493 个。`TLBFA_1` 模块 R4 同名率为 **94.89082%（24,553 / 25,875）**，未匹配 1,322 个。这些分母来自提取后的独立模块图，只能描述模块采集，不能替代香山全图指标。[Sc 模块对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-Sc-comparison.json) · [TLBFA_1 模块对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-TLBFA_1-comparison.json)

### TLBFA 父模块上下文与 CommonExpr 探索

为恢复 `TLBFA_1` 隔离输入缺少的静态数组上下文，使用包含 `TLBFA_1` 实例的 `TlbStorageWrapper_1` 做 CommonExpr 单 pass 重放。该输入的 GRH `split-static-array` 已产生 `_w_hit_vec_T_33_0/_1` 和 `_w_hit_vec_T_1009_0/_1` lane。重放中 `_w_hit_vec_T_42`、`_w_hit_vec_T_1018` 及这些 lane 在 CommonExpr 后和 R4 都仍存在。结果没有证明这两个样本名称在父模块中已退役。节点详情显示多个名称存在重叠的 anchor 或 operation ownership，表达式物理共享也不足以证明语义 Node 的名称和消费者可以安全迁移。[父模块重放摘要](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/summary.json) · [CommonExpr 前快照](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/before-common-expr%230/samples.json) · [CommonExpr 后快照](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/after-common-expr%230/samples.json) · [R4 快照](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/R4/samples.json)

之后对父模块 cohort 和 co-owner 处理做了探索性重放。cohort candidate 与 co-owner 重放仍显示目标名称及拆分 lane 在 CommonExpr 后存活，没有得到可验收的名称退役结果。围绕跨前驱 cohort、多 anchor 和多语义 owner 的扩展候选没有完成对应的定向回归，也没有进行全图验证。此前一次较窄的 cohort pooling 候选通过的 F34 CommonExpr 定向测试只覆盖该候选和已有用例，不能证明后续扩展成立。多 anchor/owner 的安全判定及代表迁移仍是未解决项。[cohort candidate 摘要](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-cohort-candidate/summary.json) · [co-owner 重放摘要](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-coowners/summary.json) · [实验前 CommonExpr 源码快照](../../ptmp/firrtl-ingest/F35/round6-common-expr-before-cohort-experiment.cpp)

实验前快照的 SHA-256 为 `bfae82588f37ff489c6bd60e1d4e003122101b112d2db5d663c81bcf9a61e621`。该阶段的扩展实验停在模块诊断。第五轮全图重采用时 28 分 58 秒，峰值 RSS 95,755,792 KiB（91.32 GiB），供后续安排内存与磁盘空间时参考。[第五轮全图采集资源](../../ptmp/firrtl-ingest/F35/launch/grh-round5-ptw-structural-keys-memory.log)

### Sc 寄存器写数据别名候选 · 2026-11-25

Sc 隔离证据显示 `_s0_pathIdx_T_4` 和 `_s0_biasIdx_T_1` 的七位右移结果已物理共享，但全图对账仍需选择 GSIM 的 path 名作为代表。原候选把 `retainName` 同时用于保护状态消费者和优先选择代表，导致具有寄存器写数据消费者的 bias 名被跳过，未能退役。现按 `firrtl.commonExprSourceOrder` 对完整排名的等价组优先选择最早依赖代表；只有没有完整排名时才优先保留含有状态写入消费者的名称。其余消费者、语义 Node 和操作所有权检查保持有效。

新增 `representativeRetiresDuplicateRegisterDataName` 回归，覆盖两个等价赋值名、GSIM 顺序指定的代表、寄存器写端口的数据/时钟槽位、`RegisterNext` 绑定和语义边界迁移，并验证 DCE 后状态值与输出语义。项目 Make 目标重新编译 `common_expr.cpp` 和 `f34_common_expr.cpp`，`transform-f34-common-expr` 单项回归通过。[实现](../../wolvrix/lib/transform/common_expr.cpp) · [回归](../../wolvrix/tests/transform/f34_common_expr.cpp) · [构建与测试日志](../../ptmp/firrtl-ingest/F35/round6-common-expr-register-writer/tests/build.log) · [测试结果](../../ptmp/firrtl-ingest/F35/round6-common-expr-register-writer/tests/test.log)

F34 的 5 项 pass 回归均通过。第一次 Sc 双端采集加载了旧安装库 `58fd5e51…`，重装后使用候选库 `a4b15cf4…` 重采，双端各完成 15 个 pass。用同一份 `AsyncReset` 隔离 FIRRTL 和候选库分别以 4、10 个 lowering 线程重放，结果一致。两次配置下，path 名与 bias 名的 GRH 排名分别为 `29259`、`29271`。`f35_module_repro` 可通过 `F35_MODULE_REPRO_THREADS` 与采集清单使用相同线程数。[F34 回归](../../ptmp/firrtl-ingest/F35/round6-common-expr-register-writer-full/tests/test.log) · [旧库采集摘要](../../ptmp/firrtl-ingest/F35/captures/round6-Sc-register-writer-candidate-paired/grh/summary.json) · [候选库采集摘要](../../ptmp/firrtl-ingest/F35/captures/round6-Sc-register-writer-installed-paired/summary.json) · [4 线程重放](../../ptmp/firrtl-ingest/F35/module-repro/round6-Sc-register-writer-exact-paired-input/summary.json) · [10 线程重放](../../ptmp/firrtl-ingest/F35/module-repro/round6-Sc-register-writer-10threads-exact-input/summary.json)

Sc 模块样本通过复测。GRH 在 `common-expr#0` 退役 `_s0_biasIdx_T_1`（`1329`），保留 `_s0_pathIdx_T_4`（`1299`）。GSIM 在 `CommonExpr#0` 将 `13312` 合并至同名代表 `13266`。两端 R4 均只保留 path 名。GRH 的 `s1_biasIdx` 写端口 `93046` 将槽位 1 的数据从值 `1329` 迁至 `1299`。操作快照显示使能槽位 `0`、上升沿事件槽位 `2` 和写入顺序均保持原配置。模块 R4 匹配从 **13,617 / 16,110（84.52514%）** 增为 **13,618 / 16,110（84.53135%）**，未匹配减少 1 个。10 线程定向重放耗时 1.69 秒，峰值 RSS 483,384 KiB。全图去留及第六轮对齐率尚待验证。[双端样本复查](../../ptmp/firrtl-ingest/F35/captures/round6-Sc-register-writer-installed-paired/samples.json) · [写端口迁移](../../ptmp/firrtl-ingest/F35/captures/round6-Sc-register-writer-installed-paired/grh/common-expr%230/Sc/evolution.tsv#L1364) · [模块对账](../../ptmp/firrtl-ingest/F35/captures/round6-Sc-register-writer-installed-paired/comparison.json)

### TLB 父模块双端复现

使用 Sc 候选库从 `TlbStorageWrapper_1` 提取同一份 `AsyncReset` FIRRTL，重新采集 GSIM 与 GRH。两端在 CommonExpr 输入均有两个加法节点及四条拆分 lane。GSIM 将 `T42`（`39073`）合并到 `T1018`（`41153`），并将 `T33_0/_1`（`57373`、`57374`）分别合并至 `T1009_0/_1`（`58525`、`58526`）。三个代表均留到 R4。GRH 的六个名称均留到 R4，样本在父模块重现了全图差异方向。采集用时 33.27 秒，峰值 RSS 750,896 KiB，换页计数为 0。[双端采集摘要](../../ptmp/firrtl-ingest/F35/captures/round6-TlbStorageWrapper_1-register-writer/summary.json) · [GSIM 合并谱系](../../ptmp/firrtl-ingest/F35/captures/round6-TlbStorageWrapper_1-register-writer/gsim/common-expr/evolution.tsv#L74505) · [GRH R4 清单](../../ptmp/firrtl-ingest/F35/captures/round6-TlbStorageWrapper_1-register-writer/grh/R4/nodes.tsv#L18747) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round6-TlbStorageWrapper_1-paired-memory.log)

父模块先前的 GRH 定向快照显示，CommonExpr 入口的 `T42` 和 `T1018` 分别拥有单一锚值 `43372`、`45452`，各自的根赋值操作也只有一个所有者。两者同时是上游 `kConcat` 和两层 `kAssign` 操作的共同所有者。这三条操作各有 565 个所有者。`T1018` 的排名 `41597` 早于 `T42` 的 `43235`。具名退役还需要核对上游共同所有权、lane 的前驱键以及两个样本是否能进入同一个具名组。[父模块入口操作详情](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/before-common-expr%230/node-details.jsonl) · [排名与语义边界](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-common-expr/before-common-expr%230/samples.json)

### TLB 共享上游操作的具名退役

CommonExpr 候选检查允许节点包含共享的非根单结果纯操作。该结果可以没有锚点，也可以由同时拥有该操作的其他节点锚定。结果有语义绑定时继续保留原检查。实际退役通过现有批量接口删除重复名的成员关系，其他所有者保留各自的操作与锚点。第一版仅允许无锚点结果，父模块重放退役了 `T42` 并保留 `T1018`，两条 `T33` lane 仍在册。扩展至由其他所有者锚定的结果后，`T42` 和 `T33_0/_1` 都在 CommonExpr 退役，`T1018` 和 `T1009_0/_1` 保留到 R4。第二次定向重放耗时 3.05 秒，峰值 RSS 529,992 KiB。[实现](../../wolvrix/lib/transform/common_expr.cpp) · [第一版重放](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-shared-intermediate/summary.json) · [第二版重放](../../ptmp/firrtl-ingest/F35/module-repro/round6-TlbStorageWrapper_1-shared-anchored/summary.json)

共享操作回归覆盖上游结果无锚点及由其他所有者锚定两种形态，在 CommonExpr 返回时核对剩余操作所有者、锚点与消费者，随后经 DCE 检查三个输出。Sc 回归补验寄存器在上升沿捕获数据和事件未变时保持状态。F34 pass 与语义树共 6 项回归通过，构建和测试耗时 8.56 秒，峰值 RSS 408,008 KiB。[回归实现](../../wolvrix/tests/transform/f34_common_expr.cpp) · [6 项结果](../../ptmp/firrtl-ingest/F35/round6-shared-anchored-tests/tests/test.log) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round6-shared-anchored-tests-memory.log)

### 最终模块复测与全图验证

复核写端口布局后，将完整排名下允许退役的状态消费者限定为寄存器写数据槽位。使能、数组索引和写掩码仍按原规则保留名称，事件槽位继续排除在具名退役候选之外。新增使能名保留断言后，F34 pass 与语义树 6 项测试通过，构建与测试耗时 11.18 秒，峰值 RSS 408,232 KiB，换页计数为 0。双端重采的 GRH 动态库 SHA-256 为 `cf2aff8a4007b4738af98b352b6a3465f08d48ccf7d01f411e25049df8ff5d62`。[回归日志](../../ptmp/firrtl-ingest/F35/round6-writer-data-slot-tests/tests/test.log) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round6-writer-data-slot-tests-memory.log)

| 模块 | 双端 R4 样本 | 模块同名率 | 双端耗时与峰值 RSS |
| --- | --- | ---: | --- |
| `Sc` | 支持 bias 名退役、path 名保留 | 84.65747%（13,618 / 16,086） | 22.43 秒，519,596 KiB，无换页。[对账](../../ptmp/firrtl-ingest/F35/captures/round6-final-Sc/comparison.json) · [采集摘要](../../ptmp/firrtl-ingest/F35/captures/round6-final-Sc/summary.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round6-final-Sc-paired-memory.log) |
| `TlbStorageWrapper_1` | `T42`、`T33_0/_1` 退役，`T1018`、`T1009_0/_1` 保留 | 93.73080%（25,940 / 27,675） | 33.23 秒，751,312 KiB，无换页。[对账](../../ptmp/firrtl-ingest/F35/captures/round6-final-TlbStorageWrapper_1/comparison.json) · [采集摘要](../../ptmp/firrtl-ingest/F35/captures/round6-final-TlbStorageWrapper_1/summary.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round6-final-TlbStorageWrapper_1-paired-memory.log) |

第一次全图采集 `f35-grh-294fc3166bbe4e53a45a1e0f6cdf696f` 最后写入的完整边界为 `xmr-resolve#0`。`hier-flatten#0` 边界导出期间停止更新。同一时间窗的系统日志记录 `systemd-oomd` 于 16:44:15（UTC+8）因持续内存压力终止一个 tmux scope，随后 systemd 报告该 scope 内 17 个进程被杀。另一次重试误将 Python 环境的 `site-packages` 用作 `F35_PACKAGE`。该目录缺少显式包身份清单 `identity.json`，子进程在 ingest 前退出。正式重试改用模块复测时的 Python 环境默认导入。[首次运行记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-294fc3166bbe4e53a45a1e0f6cdf696f/) · [包参数错误日志](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-b3ef17d9a1eb4efda187ea2cf0069cae/grh.log)

正式重试 `f35-grh-cb619578d18d47ed8f4c5394b607ef5a` 复用冻结 GSIM 参考及原预算。17:04:35 写入最后完整边界 `xmr-resolve#0`，随后 `hier-flatten#0` 仅留下前置快照。17:06:16，`systemd-oomd` 因用户服务组的内存压力持续超过 50% 门槛 20 秒并发生内存回收，终止了当时运行 Codex 和采集任务的 tmux scope。systemd 报告该 scope 内 15 个进程被杀，守卫留下的 `running` 状态已失效。`oomd` 对这两次 scope 的内存用量分别报告为 143.9G 和 84.2G，这些值属于 scope 级观测。此次未生成 R4 清单。[系统终止日志](../../ptmp/firrtl-ingest/F35/launch/grh-round6-oomd.log) · [内存观测](../../ptmp/firrtl-ingest/F35/launch/grh-round6-oomd-memory.log) · [最后完整边界](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-cb619578d18d47ed8f4c5394b607ef5a/progress.json)

### 全图采集的内存控制

`make f35_grh_capture_capped` 使用独立 systemd 用户服务运行正式采集。`F35_MEMORY_MAX_BYTES` 默认 112 GiB，依据第五轮 91.32–98.77 GiB 的单进程 RSS 留出余量，同时给 187 GiB 的宿主机保留空间。服务禁用 swap，并核验 cgroup 上限与 `ManagedOOMPreference=omit`。`F35_RESOURCE_REPORT` 记录服务退出状态及 cgroup 峰值，峰值包含进程内存和该组计费的文件缓存。64 MiB 服务预检已通过。[服务预检](../../ptmp/firrtl-ingest/F35/resource-smoke-host/resources.json)

GRH 采集在已关闭的大件快照上执行 `fdatasync` 和 `POSIX_FADV_DONTNEED`，覆盖 ingest 来源清单、层级展开模块快照、各 pass 前后清单与最终 R4。每个文件从 8 MiB 起执行缓存提示，汇总记入 `snapshot_cache_release`，耗时位于原生 pass 计时之外。守卫实时追加已校验的 stage 事件。`make report_f35_timing` 复核完整运行的 15 个原生调用、R4 边界和冻结预算。F35 工具 31 项及 F32 采集契约 23 项均通过。[F35 工具结果](../../ptmp/firrtl-ingest/F35/memory-tests/launch/tool-tests.log) · [历史第五轮预算复审](../../ptmp/firrtl-ingest/F35/measure-tests/round5-ptw-structural-keys-timing.json)

18:08（UTC+8）启动隔离采集 `f35-grh-80ed54ae9deb46e887d7fea1e173b11c`，使用第六轮 Sc 和 TLB 模块复测的 GRH 库、同一 `SimTop` 输入及原 GSIM 冻结预算。服务启动清单已核验内存上限和零 swap。[启动证据](../../ptmp/firrtl-ingest/F35/launch/grh-round6-capped-resources.json.start.json) · [资源报告](../../ptmp/firrtl-ingest/F35/launch/grh-round6-capped-resources.json)

### 受限全图复测结果

隔离采集于 18:37 完成，总耗时 28 分 46.56 秒。cgroup 峰值达到 112 GiB，`memory.events.max` 为 7,421，OOM 和 OOM kill 均为 0，服务退出时 swap 用量为 0。采集对 349 个文件执行缓存释放提示，涉及 190,623,893,251 字节，累计耗时 48.40 秒，无报错。15 个调用均通过冻结预算复审，其中层级展开 75.83 / 300.00 秒、CommonExpr 68.48 / 221.33 秒、第四次 DCE 30.70 / 63.01 秒。对账及样本查询串行执行，耗时 2 分 22.91 秒，峰值 RSS 为 1,264,660 KiB，无换页。[采集清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-80ed54ae9deb46e887d7fea1e173b11c/summary.json) · [逐 pass 预算](../../ptmp/firrtl-ingest/F35/measure-tests/round6-capped-timing.json) · [资源报告](../../ptmp/firrtl-ingest/F35/launch/grh-round6-capped-resources.json) · [对账和样本查询资源](../../ptmp/firrtl-ingest/F35/launch/round6-capped-postprocess-memory.log)

R4 清单 SHA-256 为 `abbbe3b5db386e199526b04baf15f05d0452d7d77ab439d33182f64cce14ec95`。GSIM 库存 3,612,639 个节点，双端均无重名和无名节点。较本轮起点消除 12,356 行未匹配名称，新增 15 行，同名命中净减 7,702，GRH 总数净减 20,043。现有谱系核验覆盖下面两个样本的退役和代表迁移。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-capped.json)

| 类别 | 节点数 | 占 U | 较本轮起点变化 |
| --- | ---: | ---: | ---: |
| 赋值 | 29,217 | 72.88% | −10,613 |
| Mux | 3,548 | 8.85% | −1,630 |
| 状态与存储 | 3,160 | 7.88% | 0 |
| 位切片与拼接 | 2,909 | 7.26% | −86 |
| 其他组合逻辑 | 850 | 2.12% | 0 |
| 常量 | 403 | 1.01% | −12 |

- Sc 的 bias 节点 `544995` 在 CommonExpr 合并到 path 节点 `544965`。两端 R4 均保留 `_s0_pathIdx_T_4` 并退役 `_s0_biasIdx_T_1`。[全图样本谱系](../../ptmp/firrtl-ingest/F35/measure-tests/round6-capped-focused.json)
- 读侧 DTLB 的 `_w_hit_vec_T_42` 与 `_w_hit_vec_T_1018`（`6546024`、`6548104`）一同合并到写侧 DTLB 的 `_w_hit_vec_T_1018`（`6580122`）。两对 lane `9327907` → `9334751`、`9327908` → `9334752` 与读侧原代表 `9329075`、`9329076` 也分别合并到同一写侧 lane。模块复测保留了读侧三个代表名，GSIM 全图也保留这三个名。它们在 GRH 全图 `common-expr#0` 返回时已消失。本轮样本门控仍待通过，后续需核对读写侧的表达式依赖及跨实例代表分组。[全图样本谱系](../../ptmp/firrtl-ingest/F35/measure-tests/round6-capped-focused.json)

剩余赋值中，14,578 个名称最后出现在 GSIM CommonExpr 输入，5,342 个最后出现在 AliasAnalysis 输入，2,654 个最后出现在 PatternDetect 输入。后续抽样以本次差异索引定位这些仍存活的名称。[第六轮差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round6-capped-unmatched.tsv)

### 后续模块排查

`InstrCompact.instrOffset_3_2` 与 `instrOffset_4` 的 FIRRTL 右侧都是 `mux(io.req.rawIsRvc[7], twoFetchInstrOffset[7], twoFetchInstrOffset[8])`，对应原文件第 1,599,762 和 1,599,689 行。独立顶层抽取时，沿父实例的 reset 连接将抽象 `Reset` 绑定为 `AsyncReset`。两端在 CommonExpr 都将 `256` 合并到 `189`，只保留代表名到 R4。模块对账为 3,625 / 3,625，采集耗时 9.98 秒，峰值 RSS 130,632 KiB，无换页。[原始声明](../../build/xs/rtl/rtl/SimTop.fir#L1599762) · [独立模块样本](../../ptmp/firrtl-ingest/F35/captures/round7-InstrCompact-async/samples.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round7-InstrCompact-async-memory.log)

父模块 `Ifu` 复现出全图的名称差异。GSIM 在 CommonExpr 将 `63361` 合并到 `63294`，只保留 `instrCompactor.instrOffset_4`。GRH 也记录 `74190` → `74123`，但两个名称在 CommonExpr 后及 R4 都存活。GRH CommonExpr 入口两条声明分别拥有独立锚点，并引用相同三个数据前驱 `16776`、`87729`、`87730`。两条声明的 `firrtl.commonExprSourceOrder` 均为 0，排序中的未访问原因仍需确认。父模块 R4 为 34,163 / 34,853（98.02026%），双端采集用时 37.19 秒，峰值 RSS 965,284 KiB，无换页。[父模块样本](../../ptmp/firrtl-ingest/F35/captures/round7-Ifu/samples.json) · [锚点与操作所有权](../../ptmp/firrtl-ingest/F35/module-repro/round7-Ifu-ownership/before-common-expr%230/node-details.jsonl) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round7-Ifu-memory.log)

TLB 补充了两个双实例小图。`ld`、`st` 接入同一父数组时，GSIM R4 分别保留 `ld.third` 与 `st.third`，GRH R4 仅保留 `st.third`。另一个小图让两个实例先在 `arrayBit` 取数组动态下标再计算下游标量，GRH 也在 CommonExpr 退役 `ld.arrayBit`。两个图把跨实例退役定位到数组边界身份及该边界向标量消费者的传播。双端采集各约 1.6 秒，峰值 RSS 约 74 MiB，无换页。[直接表达式小图](../../ptmp/firrtl-ingest/F35/tlb-array-boundary-probe/Top.fir) · [标量前驱小图](../../ptmp/firrtl-ingest/F35/tlb-array-boundary-probe/Nested.fir) · [两级双端采集](../../ptmp/firrtl-ingest/F35/tlb-array-boundary-probe/nested/summary.json)

### Ifu 的语义依赖环

按调度使用的已解析 `dependency` 和 `external_binding` 边复放，`split-static-array#0` 返回时调度访问 82,132 / 89,155 个节点，`common-expr#0` 入口时访问 44,546 / 49,558 个节点。两个边界均有一个 63 节点的强连通分量。`instrBoundary.boundary` 因动态消费者 `16826` 保留为一个数组 Node。FIRRTL 从 `boundary[0]` 计算 `_boundary_1_T` 和 `_boundary_1_T_1` 后写入 `boundary[1]`，两个不同数组项被归入同一 Node 后形成语义环。GSIM 在 SplitArray 将其拆为 32 个数组成员。GRH 的环经 `_T_174` 和 `_T_175` 阻塞两条 `instrOffset` 声明。[FIRRTL 复现](../../ptmp/firrtl-ingest/F35/module-repro/round7-Ifu-cycle/isolated.fir#L5780) · [GRH 拆分决策](../../ptmp/firrtl-ingest/F35/captures/round7-Ifu/grh/split-static-array%230/Ifu/evolution.tsv) · [GSIM 拆分谱系](../../ptmp/firrtl-ingest/F35/captures/round7-Ifu/gsim/split/evolution.tsv)

CommonExpr 在原拓扑遍历结束后识别剩余强连通分量。环内名称继续作为独立前驱且不参与具名归并或源排序，环外消费者沿其余依赖继续调度。回归在物理无环的数组快照上构造语义环，核对环内节点、下游代表次序、名称退役及全部 8 组输入的三个输出。定向 Make 回归通过。Ifu 候选模块复测使用库 SHA-256 `9d1ed98141ab70c854a9b5cf262da490ba0b800564476ffae326e1e932beb98d`（含 TLB 边界修改），耗时 10.54 秒，峰值 RSS 583.6 MiB。代表 `74123` 源排序为 83,324，重复节点 `74190` 为 83,325。CommonExpr 退役后者，R4 保留 `instrCompactor.instrOffset_4`，与 GSIM 样本一致。全图结果待复测。[定向回归](../../ptmp/firrtl-ingest/F35/round7-ifu-cycle-tests/tests/test.log) · [Ifu 候选复测](../../ptmp/firrtl-ingest/F35/module-repro/round7-Ifu-cycle-candidate/summary.json)

### TLB 数组边界与组合候选复测

全图中，GSIM 将读写两侧 `valididx` 分别保留为形状 `[8]` 的数组 Node `6562635`、`6625720`，同由寄存器 `6708542` 驱动。GRH 对应 Node 为 `5462380`、`5462693`，同由 `5463226` 驱动。两端各自保留了进入 CommonExpr 的两条命名依赖链。第一版候选把所有数组派生标量的 Node ID 纳入具名分组。在父模块中，同一实例的 `T33_0`（`56959`）和 `T1009_0`（`58127`）分别依赖三组中间标量别名，第一版将它们分在不同组，三个重复名留到 R4。[全图前驱与小图](../../ptmp/firrtl-ingest/F35/tlb-array-boundary-probe/README.md) · [父模块反例](../../ptmp/firrtl-ingest/F35/captures/round6-boundary-TlbStorageWrapper_1/summary.json)

修订后的具名分组保留原有结构键，并加入标量依赖链所引用的数组边界 ID 集合。遇到数组值时，以当前命名边界为起点。修订后真实 TLB 父模块在 R4 退役 `T42`、`T33_0/_1`，保留 `T1018`、`T1009_0/_1`。嵌套小图保留两实例各自的 `arrayBit` 和 `third`，同侧仍可合并重复名。Sc 和 Ifu 各保留 GSIM 同名代表。四个双端模块采集使用同一库 `779189fd44a8769f3f6d67f37d76e20396751d028382effa97794849b38e22c0`，串行耗时 94.74 秒，峰值 RSS 965,128 KiB，无换页。[TLB 小图](../../ptmp/firrtl-ingest/F35/tlb-array-boundary-probe/nested-origin-candidate/summary.json) · [TLB 父模块](../../ptmp/firrtl-ingest/F35/captures/round6-origin-TlbStorageWrapper_1/summary.json) · [Sc 模块](../../ptmp/firrtl-ingest/F35/captures/round6-origin-Sc/summary.json) · [Ifu 模块](../../ptmp/firrtl-ingest/F35/captures/round7-origin-Ifu/summary.json) · [内存记录](../../ptmp/firrtl-ingest/F35/launch/round6-array-origin-modules-memory.log)

### 组合候选全图结果

独立服务于 19:47 启动采集 `f35-grh-2a2753a446eb4003a8e6001c8802971e`，于 20:14 正常退出（UTC+8），总耗时 27 分 36.16 秒。清单核对了上述库的 SHA-256，R4 库存 SHA-256 为 `2327408a0caff38d96768f8c554716026dcb811fb2b2188cf17607dd6be2f0ae`。cgroup 峰值达到 112 GiB，`memory.events.max` 为 3,811，OOM 和 OOM kill 均为 0，swap 上限和退出用量均为 0。对 349 个快照文件执行缓存释放提示，涉及 190,624,399,179 字节，耗时 53.55 秒，无报错。串行后处理耗时 2 分 23.57 秒，峰值 RSS 1,264,104 KiB，无换页。[采集清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-2a2753a446eb4003a8e6001c8802971e/summary.json) · [资源报告](../../ptmp/firrtl-ingest/F35/launch/grh-round6-array-origin-resources.json) · [后处理内存](../../ptmp/firrtl-ingest/F35/launch/round6-array-origin-postprocess-memory.log)

较上次全图复测，同名率提高 0.02932 个百分点，同名数净增 240，GRH 库存净减 513。消除 753 个未匹配赋值名，新增未匹配名为 0。剩余赋值 28,464 个、Mux 3,548 个、状态与存储 3,160 个、位切片与拼接 2,909 个、其他组合逻辑 850 个、常量 403 个。冻结 GSIM 参考包含 3,612,639 个节点，双端无名和重名计数均为 0。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin.json) · [差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin-unmatched.tsv)

15 个原生调用全部通过耗时门。层级展开为 50.71 / 300.00 秒，CommonExpr 为 80.75 / 221.33 秒，第四次 DCE 为 29.47 / 63.01 秒。组合候选的 `grh-semantic-tree` 和 `transform-f34-common-expr` 定向回归均通过。[逐 pass 耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin-timing.json) · [定向回归](../../ptmp/firrtl-ingest/F35/round6-array-origin-tests/tests/test.log)

GRH 在 CommonExpr 结束时已退役 Sc `_s0_biasIdx_T_1`、Ifu `instrCompactor.instrOffset_3_2` 及读侧 DTLB `_w_hit_vec_T_42`、`_w_hit_vec_T_33_0/_1`。Sc `_s0_pathIdx_T_4`、Ifu `instrCompactor.instrOffset_4` 以及 DTLB 读写侧各自的 `_w_hit_vec_T_1018`、`_w_hit_vec_T_1009_0/_1` 均保留至 R4。[样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin-focused.json)

剩余赋值中，13,825 个名称最后见于 GSIM CommonExpr 输入，5,342 个见于 AliasAnalysis 输入，2,654 个见于 PatternDetect 输入。最新对账把 `Sc.t1_bankMask` 列为仍有输出依赖的赋值样本。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin.json) · [Sc 模块采集](../../ptmp/firrtl-ingest/F35/captures/round6-origin-Sc/summary.json)

## 第 7 轮 · 2026-11-25 · 剩余赋值节点

本轮起点为 **98.45176%（2,501,231 / 2,540,565）**，未匹配 39,334 个，其中赋值 28,464 个（72.36%）。先复现 `Sc.t1_bankMask`（全图 ID `546924`），覆盖仍有输出依赖且最后见于 GSIM PatternDetect 输入的赋值样本。PatternDetect 前最后出现的 2,654 个赋值名称包含其他形态，本次只核实 Sc 中匹配的读取。[差异分类](../../ptmp/firrtl-ingest/F35/measure-tests/round6-array-origin.json)

### Sc 单比特读取

FIRRTL 用常量 1 和一位无符号索引执行 `dshl` 得到两位 `t1_bankMask`。GSIM 改写 14 个读取后在 PatternDetect 退役该名。GRH 的 `_T_84` 与 `_T_85` 分别由 `kSliceStatic` 读取 `t1_bankMask[0]` 和 `[1]`，再经各自的 `kAssign` 成为下游 `kAnd` 的输入。两条读取的共同输入 `3258` 由 `kAssign` 将移位结果 `26963` 转接，二者均为两位无符号四态标量。旧匹配器停在该转接，第四次 DCE 后仍有两条依赖保住 `t1_bankMask`。重放耗时 8.28 秒，峰值 RSS 421,332 KiB，无换页。[GRH 操作链](../../ptmp/firrtl-ingest/F35/module-repro/round7-Sc-pattern-baseline/before-pattern-detect%230/node-details.jsonl) · [GSIM 原生改写](../../ptmp/firrtl-ingest/F35/captures/round6-origin-Sc/gsim/pattern-detect/native-mutations.jsonl)

PatternDetect 现在在读取和低位截断两处沿同类型的纯 `kAssign` 查找移位，仍使用已有的位宽、索引和逻辑域校验。改写只替换读取的操作和依赖，DCE 负责清理失去消费者的节点。定向回归同时覆盖多级赋值、截断两侧赋值、四态模式、仍有多位消费者的移位，以及所有索引输入的输出。`make test_f34_passes` 的六项检查通过，峰值 RSS 343,248 KiB，无换页。[实现](../../wolvrix/lib/transform/pattern_detect.cpp) · [测试结果](../../ptmp/firrtl-ingest/F35/round7-pattern-tests/tests/test.log)

组合库 `1013ad6aa29998e45dd16b4ceb81e7203820e414907d349b8d474276a1744a20` 下的 Sc 双端采集确认，GRH 将操作 `117596` 和 `117598` 从读取 `3258` 改为与索引 `3256` 比较，`t1_bankMask` 由后续 DCE 退役，双端 R4 均无该名。模块同名率为 84.66273%（13,618 / 16,085）。双端采集耗时 23.84 秒，峰值 RSS 514,956 KiB，无换页。全图覆盖量和耗时仍待验证。[双端采集](../../ptmp/firrtl-ingest/F35/captures/round7-Sc-pattern-async/summary.json) · [改写记录](../../ptmp/firrtl-ingest/F35/captures/round7-Sc-pattern-async/grh/pattern-detect%230/Sc/evolution.tsv) · [模块对账](../../ptmp/firrtl-ingest/F35/captures/round7-Sc-pattern-async/comparison.json) · [内存记录](../../ptmp/firrtl-ingest/F35/launch/round7-Sc-pattern-async-memory.log)

### iTLB 单比特比较

全图 `page_itlb_storage_fa._T_214`（GRH `726714`）在 GSIM CommonExpr 合并到 `_w_hit_vec_T_980`。冻结参考中指向该代表的 49 条合并记录，有 48 个源名称仍在本轮起点的未匹配索引里。在 `TlbStorageWrapper` 模块复现中，两条读取已在 GRH PatternDetect 改写为同一索引与零的比较。旧的隐式边界仍分别指向两个 one-hot 名称，且 `_w_hit_vec_T_980` 的根赋值还由另外两个节点持有。[模块复现与谱系](../../ptmp/firrtl-ingest/F35/module-repro/round7-itlb-current/README.md)

PatternDetect 移除已失去读取路径的旧边界，保留同一节点仍使用的边界。CommonExpr 允许具有唯一锚点、同类型且由多个节点持有的根赋值接收重复节点的消费者，同时保留该赋值的所有权。组合库 `4018b8b22f78a9eaad05b5a8bde700ade49e3003f45dcf5d8e99c4196c11cb91` 的定向重放在 CommonExpr 退役 `_T_214`，到 R4 仍保留 `_w_hit_vec_T_980`。重放峰值 RSS 为 306,332 KiB，无换页。该库还在 Sc 重放中确认 `t1_bankMask` 退役，峰值 RSS 为 421,876 KiB，无换页。六项组合回归通过。[iTLB 重放](../../ptmp/firrtl-ingest/F35/module-repro/round7-itlb-one-hot-common/summary.json) · [Sc 重放](../../ptmp/firrtl-ingest/F35/module-repro/round7-Sc-combined/summary.json) · [组合回归](../../ptmp/firrtl-ingest/F35/round7-one-hot-common-tests/tests/test.log)

### EntriesLdu 整数组寄存器转接

冻结 GSIM 的 AliasAnalysis 输入与输出之差中，7,023 个名称仍见于本轮起点的 GRH R4，且均有 GSIM 原生 `identity_alias` 合并事件。按 GRH R4 端点筛选，`srcStatus` 下有 468 个 `kAssign` 名称，其中 `psrc` 152 个、`regCacheIdx` 138 个。该计数用于选择样本，具体验收范围由样本的源操作与全图复测确定。[GSIM 合并索引](../../ptmp/firrtl-ingest/F35/measure-tests/round7-alias-merges.tsv) · [GRH R4 端点](../../ptmp/firrtl-ingest/F35/measure-tests/round7-alias-grh-r4-kinds.tsv)

`OthersEntry_108` 的 FIRRTL 直接将 `entryReg` 接到 `io.commonOut.entry.bits`。在父模块 `EntriesLdu` 中，`psrc` 转接是同类型的整数组 `kAssign`（操作 164148），从寄存器读值 161595 转接到 1910。两值为宽 8、形状 `[1]` 的四态逻辑。旧 AliasAnalysis 在整数组规则中将寄存器所有者判为非普通节点，保留该转接名。新规则要求具名源拥有同类型的无下标寄存器读及对应存储声明，只退役转接名，并复用原读取值。定向回归核对转接消费者、寄存器状态成员和读写时序，并在 DCE 前后对照初始化值和上升沿后的值。[FIRRTL 连接](../../build/xs/rtl/rtl/SimTop.fir#L4443565) · [操作详情](../../ptmp/firrtl-ingest/F35/module-repro/round7-EntriesLdu-alias-details/before-alias-analysis%230/node-details.jsonl) · [定向回归](../../ptmp/firrtl-ingest/F35/round7-alias-state-tests/tests/test.log)

定向重放使用库 `a78e4a73354e6cae8e1e4e24a52ad42ab8ccb2d6b94692a373b0a29b1efc87bb`，耗时 3.60 秒，峰值 RSS 600,500 KiB。随后用组合库 `4018b8b22f78a9eaad05b5a8bde700ade49e3003f45dcf5d8e99c4196c11cb91` 复用同一份模块 FIRRTL 与冻结的模块 GSIM 参考。AliasAnalysis 中，GRH 的 `psrc` 和 `regCacheIdx` 分别从 1910 合并到 36534、从 1917 合并到 36541。GSIM 相应为 6182 → 6433、6189 → 6440。两端均在 R4 保留寄存器名并退役两个转接名。模块同名率从 97.62641%（22,745 / 23,298）升至 98.60725%（22,727 / 23,048），剩余差异从 553 降至 321。全图收益与预算仍待验证。[定向重放](../../ptmp/firrtl-ingest/F35/module-repro/round7-EntriesLdu-alias-state-candidate/summary.json) · [双端复测](../../ptmp/firrtl-ingest/F35/captures/round7-EntriesLdu-alias-state-candidate/summary.json) · [R4 样本](../../ptmp/firrtl-ingest/F35/captures/round7-EntriesLdu-alias-state-candidate/samples.json)

### 第七轮全图结果与磁盘清理

隔离采集 `f35-grh-3e368f110eba428cab99fdd303e467b0` 正常退出，用时 27 分 52.61 秒。cgroup 峰值达到 112 GiB，OOM、OOM kill 和 swap 使用量均为 0。CommonExpr 为 85.28 / 221.33 秒，第四次 DCE 为 29.36 / 63.01 秒。全图同名数净增 447，库存净减 3,730，消除 4,177 个未匹配名，新增未匹配名为 0。分类中赋值减少 4,185 个，状态与存储增加 8 个，其余类别计数相同。Sc、iTLB 和 EntriesLdu 的本轮样本以及第六轮复查样本均与 GSIM 的 R4 去留一致。[第七轮归档清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-3e368f110eba428cab99fdd303e467b0/summary.json) · [资源报告](../../ptmp/firrtl-ingest/F35/launch/grh-round7-combined-capped-resources.json) · [AliasAnalysis 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round7-combined-alias.json)

第七轮完成后，归档了第五轮两份和第六轮一份旧采集的清单、运行日志、守卫记录与阶段事件，并回收三份旧全量快照。磁盘可用空间由约 4.2 GiB 升至 505 GiB。第七轮移至 `grh-current/`，同步更新清单和对账报告中的路径。冻结的 GSIM 参考继续保存在 `gsim-reference/`。[历史运行记录](../../ptmp/firrtl-ingest/F35/grh-run-evidence/)

第八轮开始前再清理 41 组旧模块采集的逐 pass 快照，磁盘可用空间由约 505 GiB 升至 560 GiB。保留采集摘要、已引用的样本和谱系，以及第八轮复用的 Sc 输入。第七轮为唯一完整的 GRH 全图采集，冻结的 GSIM 全图参考供后续各轮复用。

## 第 8 轮 · 2026-11-25 · 剩余赋值节点

本轮起点为 **98.61414%（2,501,678 / 2,536,835）**。35,157 个未匹配节点中，赋值 24,279 个，Mux 3,548 个，状态与存储 3,168 个，位切片与拼接 2,909 个，其他组合逻辑 850 个，常量 403 个。GRH 起始运行 `f35-grh-3e368f110eba428cab99fdd303e467b0` 的 R4 库存 SHA-256 为 `e4f543aed28020e1d6b4cebb4fb59f2f6dcd4d593e9b4c29c674669562e97382`。[分类与采样](../../ptmp/firrtl-ingest/F35/measure-tests/round7-combined.json) · [冻结参考](../../ptmp/firrtl-ingest/F35/gsim-reference/frozen.json)

流式连接 R4 未匹配名、GSIM CommonExpr 合并事件和 GRH 前后谱系，得到 14,346 条事件。5,328 条在 GRH 的 CommonExpr 输入同时含原名和代表名，且未记录 GRH 对应合并。Sc 有 2,024 条未记录 GRH 对应合并的事件，覆盖多种表达式。其中动态寄存器数组读的两对复现样本分别比较 `sumAboveThres` 和 `scPred`，每对读取的存储、动态下标及元素类型相同。GRH 双名均留到 R4。GSIM 全图分别记录 `535926 → 534720` 和 `534388 → 534589`。Sc 模块定向重放耗时 1.89 秒，峰值 RSS 约 405 MiB。2,024 条是取样范围，子群覆盖量待按实际改写验证。[差异索引与溯源](../../ptmp/firrtl-ingest/F35/measure-tests/round8-common-cohort-notes.md) · [Sc 模块重放](../../ptmp/firrtl-ingest/F35/module-repro/round8-Sc-common-cohort/summary.json)

### 模块验证

Sc 双端隔离采集沿用 `AsyncReset`。基线的三个样本均存活到 GRH R4。GSIM 在 CommonExpr 分别合并 `18184 → 16978`、`16646 → 16847`、`18793 → 22325`，三个原名均未存活到 R4。GRH CommonExpr 现在使用寄存器存储身份、元素类型及有序索引表达式比较动态元素读，并沿同类型赋值验证读取的存储边界。复测使用同一份 Sc 输入和模块 GSIM 参考，三个原名均在 GRH CommonExpr 退役。[双端基线](../../ptmp/firrtl-ingest/F35/captures/round8-Sc-baseline/samples.json) · [候选谱系](../../ptmp/firrtl-ingest/F35/captures/round8-Sc-candidate/samples.json)

| Sc 样本 | GRH 合并 | GRH / GSIM 的 R4 代表名 |
| --- | --- | --- |
| `_t1_writeThresVec_updated_shouldUpdate_T_432` | `5361 → 4155` | `_t1_writeThresVec_updated_shouldUpdate_T_96` |
| `t1_writeThresVec_updated_scWrong` | `3823 → 4024` | `t1_writeThresVec_updated_scWrong_8` |
| `_newCtr_needUpdate_T_135` | `5970 → 5777` | `_newCtr_needUpdate_T_87` / `_newCtr_needUpdate_T_999` |

Sc 模块同名数维持 13,618，GRH 库存由 16,085 降至 14,125，差异由 2,467 降至 507，同名率由 84.66273% 升至 96.41062%。第三个样本的退役已对齐，代表名仍有差异。GRH 候选采集耗时 6.20 秒，峰值 RSS 515,808 KiB，无换页。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round8-Sc-candidate/comparison.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round8-Sc-candidate-memory.log)

AliasAnalysis 的 `WriteBuffer_4.readValidVec_0_0` 在第七轮库的模块重放中由 `split-static-array` 生成位切片并存活至 R4。候选代码识别来自寄存器子数组、对齐且覆盖完整元素的静态切片，保留原读取和值，同时将消费者的语义依赖迁到寄存器。按原实例连接使用 `AsyncReset` 双端复测，GRH 在 AliasAnalysis 记录 `2035 → 70`，两端 R4 均已退役原名，模块同名率为 100%（1,081 / 1,081）。双端采集耗时 9.39 秒，峰值 RSS 121,260 KiB，无换页。全图索引有 384 个同类候选，实际退役量由全图复查确认。[修复前重放](../../ptmp/firrtl-ingest/F35/module-repro/round8-WriteBuffer_4-alias/summary.json) · [双端复查](../../ptmp/firrtl-ingest/F35/captures/round8-WriteBuffer4-async/samples.json) · [模块对账](../../ptmp/firrtl-ingest/F35/captures/round8-WriteBuffer4-async/comparison.json)

`grh-semantic-tree` 和 `make test_f34_passes` 的五项定向回归均通过。新增回归检查了不同寄存器和不同索引顺序、动态索引越界、完整元素和跨元素切片的行为。第八轮 systemd 预检确认资源限制生效，64 MiB 上限、禁用 swap，采集沿用 112 GiB 上限。[语义交换回归](../../ptmp/firrtl-ingest/F35/round8-common-tests/tests/test.log) · [Pass 回归](../../ptmp/firrtl-ingest/F35/round8-pass-tests/tests/test.log) · [资源预检](../../ptmp/firrtl-ingest/F35/round8-resource-smoke/resources.json)

### 全图复测

22:34（UTC+8）启动 `f35-grh-e05e190b49844597b03edffe622718c0`，复用冻结 GSIM 参考。替换前以对账报告核对第七轮 R4 清单的 SHA-256，归档第七轮清单、阶段事件和守卫记录，再回收旧快照。第八轮采用独立 systemd 用户服务、单线程、112 GiB cgroup 上限、禁用 swap，并在可用磁盘空间低于 100 GiB 时终止。[启动与资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round8-combined.log) · [资源上限验证](../../ptmp/firrtl-ingest/F35/launch/grh-round8-combined-resources.json.start.json)

采集用时 27 分 23.40 秒并正常退出，cgroup 峰值 112 GiB，OOM、OOM kill 和 swap 使用量均为 0。350 个快照文件的缓存释放提示涉及 190,643,645,088 字节，耗时 54.36 秒，无报错。R4 库存 SHA-256 为 `9b108e01a656298a96c84e9f4e49ecf01b479c9a3d70f5e081ad0d22f6a369ba`。计时、对账及 Sc 样本提取串行运行，耗时 2 分 18.74 秒，峰值 RSS 1,263,292 KiB，无换页。[第八轮归档清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-e05e190b49844597b03edffe622718c0/summary.json) · [资源结果](../../ptmp/firrtl-ingest/F35/launch/grh-round8-combined-resources.json) · [后处理内存](../../ptmp/firrtl-ingest/F35/launch/round8-combined-postprocess-memory.log)

15 个 pass 通过耗时门。AliasAnalysis 用时 17.94 / 430.39 秒，CommonExpr 用时 70.12 / 221.33 秒，第四次 DCE 用时 29.33 / 63.01 秒。全图 GRH 库存净减 4,228，同名数净减 503，未匹配名减少 3,725，新增未匹配名为 0。剩余赋值 21,311 个（67.80%）、Mux 3,548 个、状态与存储 3,168 个、位切片与拼接 2,152 个、其他组合逻辑 850 个、常量 403 个。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round8-combined.json) · [耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round8-combined-timing.json)

全图复查与 Sc 模块结果一致。`_t1_writeThresVec_updated_shouldUpdate_T_432` 和 `t1_writeThresVec_updated_scWrong` 退役，双端保留 `_t1_writeThresVec_updated_shouldUpdate_T_96` 和 `t1_writeThresVec_updated_scWrong_8`。`_newCtr_needUpdate_T_135` 在双端退役，GRH R4 仍保留 `_newCtr_needUpdate_T_87`，GSIM R4 则保留 `_newCtr_needUpdate_T_999`。`WriteBuffer_4.readValidVec_0_0` 在全图 AliasAnalysis 记录 `7736583 → 376085`，双端 R4 均无原名。代表选择和达到 99.00% 仍待验证。[Sc 全图样本](../../ptmp/firrtl-ingest/F35/measure-tests/round8-combined-focused.json) · [AliasAnalysis 全图样本](../../ptmp/firrtl-ingest/F35/measure-tests/round8-combined-alias.json)

## 第 9 轮 · iTLB CommonExpr 名称退役

延用第八轮的 **98.75891%（2,501,175 / 2,532,607）** 和 31,432 个未匹配节点作为起点。按用户决定跳过 Sc `_newCtr_needUpdate_T_999` 个案。FIRRTL 将相关更新使能和 `gChange` 与常量 `0` 相与。GRH 在 ConstantAnalysis 清理依赖，第三次 DCE 退役 `_999`。冻结 GSIM 也将写缓冲区断言折叠为 `0`，但第三次 DCE 仍从该断言沿旧依赖标记 `_999` 存活。该差异仍计入全图指标。[FIRRTL 更新使能](../../build/xs/rtl/rtl/SimTop.fir#L1501116) · [GSIM 常量折叠](../../ptmp/firrtl-ingest/F35/gsim-reference/constant-analysis/native-mutations.jsonl#L974324) · [GSIM 保留决定](../../ptmp/firrtl-ingest/F35/gsim-reference/dce-2/evolution.tsv#L4849736)

优先复查 TLBFA。第八轮库存仍有 3,024 个写侧 mux lane 名和 567 个读侧 `ppn_res` 投影名未匹配。`TlbStorageWrapper` 重放中，两组各三个名称在 GRH 共享计算值后都保留至 R4。两组已有源排名均将对应 GSIM 代表排在首位。读侧投影用作寄存器数组读下标，写侧 mux 根操作由 lane 和下游消费者共同持有。定向重放耗时 8.12 秒，峰值 RSS 308,776 KiB，无换页。[样本与首次分歧](../../ptmp/firrtl-ingest/F35/measure-tests/round9-itlb-representatives-notes.md) · [定向重放](../../ptmp/firrtl-ingest/F35/module-repro/round9-itlb-representatives/summary.json)

CommonExpr 允许将寄存器数组读端口的下标迁到等价代表，并同步迁移语义边界。`TlbStorageWrapper` 读侧的 `_ppn_res_T_13` 和 `_113` 在 CommonExpr 退役，双端保留 `_953` 至 R4。隔离模块的同名数维持 11,622，未匹配节点从 885 降到 838，新增差异为 0。定向回归覆盖全部八种选择器输入，包括越界读取。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round9-itlb-read-index/comparison.json) · [读侧样本](../../ptmp/firrtl-ingest/F35/module-repro/round9-itlb-read-index/summary.json) · [回归](../../ptmp/firrtl-ingest/F35/round9-itlb-read-index-tests/tests/test.log)

EnqEntry 的 `_wakeupVec_T_146` 在 SplitNodes 拆分寄存器读后失去原本唯一的来源，AliasAnalysis 因此无法确认转接关系。SplitNodes 现在把原读结果记录的寄存器依赖迁到覆盖同一位段的子节点和切片操作数。`_wakeupVec_T_146`、`_154`、`_162` 在复测中均与 GSIM 一致退役。隔离模块的未匹配节点从 106 降到 60，采集耗时 9.79 秒，峰值 RSS 约 166 MiB，无换页。`make test_f32_split_nodes` 通过。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round9-EnqEntry-candidate/comparison.json) · [三样本复查](../../ptmp/firrtl-ingest/F35/captures/round9-EnqEntry-candidate/samples.json) · [回归](../../ptmp/firrtl-ingest/F35/round9-EnqEntry-tests/split-nodes/tests/test.log)

写侧 mux 的结果只有一个锚点，唯一使用者是下游 mux 的数据输入，且下游节点共同持有原 mux。CommonExpr 退役重复 lane 时将下游的操作归属和语义边界迁到代表。组合库在 iTLB 模块退役 `_w_hit_vec_T_21_0` 和 `_1058_0`，与 GSIM 一致保留 `_997_0`。六个样本均对齐，模块差异从 885 降到 78，新增差异为 0。GRH 模块采集耗时 4.17 秒，峰值 RSS 298,064 KiB。七项回归通过，覆盖归属、边界和 mux 输出。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round9-itlb-mux-trial/comparison.json) · [模块样本](../../ptmp/firrtl-ingest/F35/captures/round9-itlb-mux-trial/samples.json) · [组合回归](../../ptmp/firrtl-ingest/F35/round9-mux-regression/tests/test.log)

### 全图复测

隔离采集 `f35-grh-333edd696a4148a38a2c6e3ae9e51d02` 用时 27 分 23.94 秒并正常退出。cgroup 峰值达到 112 GiB，OOM、OOM kill 和 swap 使用量均为 0。第八轮全量快照在启动前回收，冻结 GSIM 参考继续复用。第九轮 R4 SHA-256 为 `275bf19c02a5f680c8879b15d01e643ddafbb743bd8535806acb95ea38a0fbc6`。串行后处理峰值 RSS 为 1,263,048 KiB，无换页。[第九轮采集清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-333edd696a4148a38a2c6e3ae9e51d02/summary.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round9-combined-resources.json) · [后处理内存](../../ptmp/firrtl-ingest/F35/launch/round9-combined-postprocess-memory.log)

本轮消除 4,121 个未匹配名，新增为 0。库存净减 4,154，同名数净减 33。赋值减少 1,085 个，mux 减少 3,036 个，剩余赋值 20,226、状态与存储 3,168、位切片与拼接 2,152、其他组合逻辑 850、mux 512、常量 403。iTLB 六个样本和 EnqEntry 三个样本的双端 R4 去留均一致。15 个生产 pass 通过耗时门，CommonExpr 为 72.12 / 221.33 秒，第四次 DCE 为 29.95 / 63.01 秒。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round9-combined.json) · [iTLB 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round9-combined-focused.json) · [EnqEntry 样本](../../ptmp/firrtl-ingest/F35/measure-tests/round9-combined-alias.json)

## 第 10 轮 · L3 MSHR 常量下标

起点为 **98.91985%（2,501,142 / 2,528,453）**，未匹配 27,311 个。冻结 GSIM 的 CommonExpr 原生归并和剩余差异名相交，得到 9,493 条事件。2,359 条在 GRH 谱系中方向相反。GRH 谱系也记录值共享，确认名称退役还需核对 pass 前后库存。200 条 Queue1 样本在全图呈反向归并，提取父模块 `AXI4UserYanker` 后双端均保留 `_empty_T`。EnqEntry_12 单元素状态标量化试验消除 11 个旧差异，同时新增 30 个，已撤回并复测原有数组拆分回归。[CommonExpr 索引与 Queue1 复查](../../ptmp/firrtl-ingest/F35/measure-tests/round10-common-cohort-notes.md) · [EnqEntry 试验](../../ptmp/firrtl-ingest/F35/measure-tests/round10-EnqEntry-singleton-notes.md)

`MSHR_64` 的 `_client_shrink_perm_T_5` 和 `_client_shrink_perm_T_10` 都引用 `meta.clients.states[0].state`，下标来自折叠后的 1 位信号。同一数组的两条对照表达式使用 32 位字面量下标 0。四条 GRH 语义依赖都指向 Node 322。在 CommonExpr 输入，原有的表达式键区分下标位宽，两个样本都存活到 R4。GSIM 使用相同坐标并分别保留 `_new_clients_meta_0_state_T` 和 `_x_probe_clients_T_1`。冻结全图索引中有 116 条同名形态，实际退役量待全图核对。[FIRRTL](../../build/xs/rtl/rtl/SimTop.fir#L8474721) · [GRH 操作明细](../../ptmp/firrtl-ingest/F35/module-repro/round10-MSHR64-details/before-common-expr%230/node-details.jsonl) · [全图索引](../../ptmp/firrtl-ingest/F35/measure-tests/round10-common-cohort-with-incoming.tsv)

CommonExpr 对 `kSliceArray` 的已知界内常量下标按无符号坐标编码。动态、未知及越界的下标继续使用原有结构键。定向回归检查不同宽度的相同坐标、不同坐标、动态下标及越界输出，原实现按预期触发新增断言，候选通过全部七项回归。[实现](../../wolvrix/lib/transform/common_expr.cpp) · [修复前回归](../../ptmp/firrtl-ingest/F35/round10-array-cse-regression-before/tests/test.log) · [修复后回归](../../ptmp/firrtl-ingest/F35/round10-array-cse-tests/tests/test.log)

第一次模块采集载入虚拟环境中的旧 GRH 库。随后沿用其 FIRRTL 和 GSIM 模块参考，分别显式载入第九轮全图库和候选库。受控基线为 1,197 / 1,220（98.11475%），候选为 1,196 / 1,217（98.27445%）。未匹配名从 23 降至 21，新增为 0。两个原名均在 GRH CommonExpr 退役，双端保留同名代表至 R4。[受控基线](../../ptmp/firrtl-ingest/F35/captures/round10-MSHR64-controlled-baseline/comparison.json) · [候选对账](../../ptmp/firrtl-ingest/F35/captures/round10-MSHR64-candidate/comparison.json) · [双端样本](../../ptmp/firrtl-ingest/F35/captures/round10-MSHR64-candidate/samples.json)

归档第九轮前额外保留了 11 个全图名称的 CommonExpr 证据。另核实 482 对唤醒逻辑的两个名字在 GRH R4 共用计算值，名称退役资格待模块验证。内联 ClockGate 的 `CK`、`E` 涉及 802 个剩余差异，GRH 将其列为混合语言实例端口，两个引擎的门控实现也有差异。[第九轮样本摘录](../../ptmp/firrtl-ingest/F35/measure-tests/round10-preflight-samples.json) · [唤醒逻辑](../../ptmp/firrtl-ingest/F35/measure-tests/round10-wakeup-bypass-notes.md) · [ClockGate 边界](../../ptmp/firrtl-ingest/F35/measure-tests/round10-clockgate-boundary-notes.md)

### 全图复测

隔离采集 `f35-grh-773c6f1ed3f640b099b2186054cc02d5` 用时 27 分 37.60 秒，正常退出。cgroup 峰值为 112 GiB，OOM、OOM kill 和 swap 用量均为 0。R4 库存 SHA-256 为 `5a8cec31eba408b5bfebf04d79a74ee6a5e6a72b2efdad74f1856f5a0ca9cfea`。串行后处理峰值 RSS 为 1,262,932 KiB。第九轮已在启动前归档清单和必要证据、回收全量快照。[第十轮采集](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-773c6f1ed3f640b099b2186054cc02d5/summary.json) · [资源数据](../../ptmp/firrtl-ingest/F35/launch/grh-round10-index-resources.json) · [后处理资源](../../ptmp/firrtl-ingest/F35/launch/round10-index-postprocess-memory.log)

全图消除 116 个未匹配赋值名，正好覆盖原索引中的 116 个 `_client_shrink_perm` 差异，新增未匹配为 0。同名数净减 61，库存净减 177。剩余赋值 20,110、状态与存储 3,168、位切片与拼接 2,152、其他组合逻辑 850、mux 512、常量 403。三个原名均在两端 R4 退役，三个对应代表均保留。CommonExpr 用时 73.95 / 221.33 秒，第四次 DCE 用时 30.27 / 63.01 秒，共 15 个 pass 通过耗时门。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round10-index.json) · [样本](../../ptmp/firrtl-ingest/F35/measure-tests/round10-index-focused.json) · [耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round10-index-timing.json)

## 第 11 轮 · EnqEntry 唤醒旁路

按用户决定跳过 Sc `_newCtr_needUpdate_T_999` 的代表名分析，其差异仍计入全图指标。第十轮 R4 索引中，254 个实例有 482 个未匹配的 `_hasWakeupIQ_canIssueBypass_T_4/_7/_10`。冻结 GSIM 的 CommonExpr 分别保留组内 `_wakeupByIQWithoutCancel_T/_1/_2`。`EnqEntry_26` 重放复现三对，GRH 双名共享计算值并存活至 R4。每对的七个前驱完全相同，连接快照可以从值所有权解析出前驱，但具名归并只读取显式语义边界，因前驱键为空跳过三对。[诊断与源位置](../../ptmp/firrtl-ingest/F35/measure-tests/round10-wakeup-bypass-notes.md) · [模块基线](../../ptmp/firrtl-ingest/F35/captures/round11-EnqEntry26-baseline/comparison.json)

CommonExpr 从调度使用的连接快照收集所有权解析结果。仅当具名恒等赋值已有正的源排名、没有显式入向边界、全部连接为已解析的数据依赖且前驱没有已知数组边界时，使用前驱的原始 Node ID 构造分组键。沿用原来的操作所有权、使用者与源排名门控。隔离模块复用同一输入和 GSIM 参考，GRH 库 SHA-256 为 `4e432700519a3a5645df72081b42a03cdd3e7113bb3da8b405362410acae809f`。三个旁路原名均在 CommonExpr 退役，双端 R4 保留三个同名代表。模块同名数维持 2,647，未匹配从 84 降至 69，新增为 0。[实现](../../wolvrix/lib/transform/common_expr.cpp) · [模块候选对账](../../ptmp/firrtl-ingest/F35/captures/round11-EnqEntry26-candidate/comparison.json) · [定向重放](../../ptmp/firrtl-ingest/F35/module-repro/round11-EnqEntry26-candidate/summary.json)

定向回归检查完全相同的已解析前驱、不同的前驱、部分未解析的前驱以及通过标量读取访问数组边界。检查具名代表和所有小图输入的输出结果，七项回归通过。[回归代码](../../wolvrix/tests/transform/f34_common_expr.cpp) · [回归日志](../../ptmp/firrtl-ingest/F35/round11-wakeup-pass-tests/tests/test.log)

### 全图验收

隔离采集 `f35-grh-3c9b64184a3b47b5bc1e7c7951744779` 用时 27 分 47.05 秒，正常退出，清单确认载入模块重放使用的 GRH 库。R4 库存 SHA-256 为 `b7940fbb2c1558913015e703925c71ec45c833e81837b8f9d4e505cba2bb3510`。cgroup 内存峰值达到 112 GiB，OOM、OOM kill 和 swap 用量均为 0。串行后处理用时 2 分 16.77 秒，峰值 RSS 为 1,263,152 KiB。第十轮全量快照在启动前回收，归档保留其清单、对账、耗时和样本。全量 GRH 快照只保留当前一轮，冻结 GSIM 参考继续保留。[采集清单](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-3c9b64184a3b47b5bc1e7c7951744779/summary.json) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round11-wakeup-resources.json) · [后处理资源](../../ptmp/firrtl-ingest/F35/launch/round11-wakeup-postprocess-memory.log)

全图消除的 6,140 个未匹配名包括 6,138 个赋值和 2 个位切片与拼接。第十轮共有 2,842 个未匹配名被 GSIM 归并到 `_wakeupByIQWithoutCancel_T` 系列，第十一轮剩 70 个。其中 482 个 `_hasWakeupIQ_canIssueBypass_T_4/_7/_10` 剩 14 个。全图同名数净减 5,472，GRH 库存净减 11,612。两端无名数和重名数均为 0。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round11-wakeup.json)

三个复查的旁路原名在两端 R4 均退役，三个代表名在两端均保留。15 个生产 pass 均通过耗时门，其中 CommonExpr 为 70.55 / 221.33 秒，第四次 DCE 为 29.61 / 63.01 秒。[样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round11-wakeup-focused.json) · [逐 pass 耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round11-wakeup-timing.json)

剩余差异为赋值 13,972 个（66.36%）、状态与存储 3,168 个（15.05%）、位切片与拼接 2,150 个（10.21%）、其他组合逻辑 850 个（4.04%）、Mux 512 个（2.43%）、常量 403 个（1.91%）。Sc `_newCtr_needUpdate_T_999` 对应的代表名差异仍在其中。本轮达到当时的 99.00% 交付门槛。[剩余差异索引](../../ptmp/firrtl-ingest/F35/measure-tests/round11-wakeup-unmatched.tsv)

## 第 12 轮 · 99.50% 目标

第十一轮结果为 99.16338%。若同名数维持 2,495,609，需要至少合法退役 8,515 个未匹配节点才能达到新目标。对账工具使用原始计数比较 `200 × M ≥ 199 × N`，并在新报告中写入 `target_ratio`。33 项 F35 工具测试通过，其中新增用例覆盖恰好达到门槛及略低于门槛的结果。[工具回归](../../ptmp/firrtl-ingest/F35/launch/tool-tests.log)

### DataPath_1 共享寄存器读

在 AliasAnalysis 入口，`debugAllRDataVec_1`（37597）直接复制读值 165300。展开后的端口 `fpRegFile.io.debug_all_rdata_1`（38307）与寄存器节点（48543）共同拥有该读值。端口的显式数据边界已指向寄存器，复制赋值没有自己的入向边界，按所有权得到歧义。基线 AliasAnalysis 退役端口别名及下游 `fpDiffReadData_1`，保留中间复制赋值。GSIM 将两条线网都归并到 `fpRegFile.mem_1`。[GRH 入口明细](../../ptmp/firrtl-ingest/F35/module-repro/round12-DataPath1-details/before-alias-analysis%230/node-details.jsonl) · [GSIM 归并](../../ptmp/firrtl-ingest/F35/captures/round12-DataPath1-baseline/gsim/alias-analysis/native-mutations.jsonl#L2576)

AliasAnalysis 对只有一个自有操作和没有入向边界的同类型标量赋值查验底层寄存器读。寄存器声明必须有唯一语义所有者，读值的其他名字须分别以显式数据边界指向该所有者，并能在同次调用中退役。通过检查后沿用现有的别名迁移。回归验证可退役、来源歧义和受保护的端口别名及其输出。采用同一派生输入及 GSIM 参考时，`DataPath_1` 从 22,361 / 22,616 提升为 22,361 / 22,361，消除 255 个差异，新增为 0。最终候选采集用时 5.89 秒，峰值 RSS 541,708 KiB，换页计数为 0。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round12-DataPath1-shared-register-gated/comparison.json) · [回归](../../ptmp/firrtl-ingest/F35/round12-shared-register-gated-tests/tests/test.log) · [资源记录](../../ptmp/firrtl-ingest/F35/launch/round12-DataPath1-shared-register-gated-memory.log)

### CommonExpr 常量字面量

`MSHR_64` 的两条比较使用三位常量 `3'b1` 和 `3'h1`。CommonExpr 以显式定宽且已知的常量位值构造结构键，并保留逻辑类型及其他属性。模块未匹配数由 21 降到 18，新增为 0，七项 pass 回归通过。采集用时 1.07 秒，峰值 RSS 112,640 KiB，换页计数为 0。[模块对账及诊断](../../ptmp/firrtl-ingest/F35/measure-tests/round12-constant-key/notes.md) · [回归](../../ptmp/firrtl-ingest/F35/round12-constant-key-tests/tests/test.log)

### 全图复测

第十二轮达到 **99.18572%**，较第十一轮提高 0.02234 个百分点。消除 575 个未匹配名，新增 6 个，净减少 569 个。新增项来自 ROB 写回调试信号和 L2 日志端点。三个调试读线网与两个常量比较名在两端 R4 均退役，两个比较的代表名在两端均存活。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round12-combined.json) · [样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round12-combined-focused.json) · [新增差异](../../ptmp/firrtl-ingest/F35/measure-tests/round12-new-differences-cse.json)

受限采集 `f35-grh-06cf3394c2d341eb8b2e20d0d11bb2de` 用时 27 分 45.68 秒，cgroup 峰值 112 GiB，OOM、OOM kill 和 swap 使用量均为 0。R4 库存 SHA-256 为 `0681143a885fb8c1b5524dfa35d716e0a089a474010bf49d5a9ce335ba34b853`。串行后处理用时 2 分 17.91 秒，峰值 RSS 1,155,304 KiB。15 个生产 pass 均在预算内，AliasAnalysis 为 17.90 / 430.39 秒，CommonExpr 为 74.59 / 221.33 秒。上一轮全量快照已回收。[资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round12-combined-resources.json) · [耗时预算](../../ptmp/firrtl-ingest/F35/measure-tests/round12-combined-timing.json)

## 第 13 轮 · 内存节点、左移用位与别名拆分

起点剩 20,486 个未匹配节点。以当前命中数计，需再合法退役 7,947 个未匹配节点才能达到 99.50%。第十一轮证据中，984 个 MPORT 名称对应唯一存储写关系，其中 964 个存储名加 `$NEXT` 后与冻结 GSIM R4 同名。同步读地址流水级另有 959 个名称差异。[内存节点证据](../../ptmp/firrtl-ingest/F35/measure-tests/round12-dce-frontier-notes.md)

已标量化的深度一 CHIRRTL 内存将唯一写端的原有语义节点移动到存储叶的 `$NEXT` 路径，保留实际掩码写操作和存储依赖。在 `Queue1_BundleMap` 的同输入复测中，`ram.tl_state.size$NEXT` 和 `ram.tl_state.source$NEXT` 均对齐，模块达到 22 / 22，语义树与序列化回归通过。采集用时 0.81 秒，峰值 RSS 74,104 KiB，换页计数为 0。[模块复测](../../ptmp/firrtl-ingest/F35/captures/round13-Queue1-BundleMap-next/comparison.json) · [回归](../../ptmp/firrtl-ingest/F35/launch/round13-memory-writer-tests.log)

UsedBits 将定宽左移的低位需求按已知移位量向源值回退。隔离的 `IterBlock_v4` 消除全部 208 个旧差异，出现两个仍受顶层端口位宽约束的取位别名，最终为 2,583 / 2,585。定向回归覆盖有符号输入、动态或未知位移量、超宽位移量及完整结果的可观察性。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round13-IterBlock-v4-shift/comparison.json) · [归因与回归](../../ptmp/firrtl-ingest/F35/measure-tests/round12-iterblock-left-shift-notes.md)

SplitNodes 仅在生产者已有的分段边界与请求一致时，沿具名转接重试源节点拆分。此前 `IssueQueueAluCsrFenceBrhJmp` 的 `age_1.io.enq_0` 拆分会穿过两层具名转接，把六位 `entries._T_100` 强制切成六个子节点。同输入和同 GSIM 参考复测保留原节点到第四次 DCE，模块同名数由 39,064 / 39,288 增至 39,104 / 39,292，消除 36 个旧差异，新增为 0。两项已有回归继续验证拼接源和高位切片可以沿已有边界拆分。新增回归验证下游转接拆分后六位逻辑输出的等价性。模块采集用时 17.65 秒，峰值 RSS 为 1,080,468 KiB，无换页。[基线](../../ptmp/firrtl-ingest/F35/captures/round13-IssueQueueAluCsrFenceBrhJmp-baseline/comparison.json) · [候选](../../ptmp/firrtl-ingest/F35/captures/round13-IssueQueue-alias-source-cuts/comparison.json) · [回归](../../ptmp/firrtl-ingest/F35/launch/round13-alias-source-cuts-tests.log)

同步内存读地址的单级流水线根据 lowering 记录的 Node ID，在层级展开时将 current 和 next 节点命名为读口下的 `$address` 和 `$address$NEXT`。SRAM 复测由 16 / 18 提升到 18 / 18，两个状态节点均与 GSIM 同名。候选采集用时 0.84 秒，峰值 RSS 为 96,264 KiB，无换页。[基线](../../ptmp/firrtl-ingest/F35/captures/round13-SramReadAddress-baseline/comparison.json) · [候选](../../ptmp/firrtl-ingest/F35/captures/round13-SramReadAddress-candidate/comparison.json)

CommonExpr 将已知定宽常量的字面量归一化限定在 `kEq` 和 `kNe` 的操作数。定向回归覆盖等值比较和直接使用常量的具名转接。`MSHR_64` 复测保持 1,193 / 1,211，差异索引没有变化。第十二轮新增的六个全图差异仍待复查。[模块对账](../../ptmp/firrtl-ingest/F35/captures/round13-MSHR64-comparison-constant/comparison.json) · [回归](../../ptmp/firrtl-ingest/F35/launch/round13-comparison-constant-tests.log)

### 全图复测

10 项组合回归与 33 项 F35 工具测试通过。采集 `f35-grh-da001638a2e14b91938e6f04a7020a2c` 于 09:42（UTC+8）启动，固定 GRH 库 SHA-256 为 `549a6dc3336459e37bd74f535b7c989cca6abcb28a9da20a3f1aee63cc3fd373`。服务预检确认 112 GiB 内存上限和零 swap。第十二轮清单已归档，全量 GRH 快照回收后磁盘可用 742 GiB，继续使用冻结 GSIM 参考。[组合回归](../../ptmp/firrtl-ingest/F35/launch/round13-combined-tests.log) · [工具测试](../../ptmp/firrtl-ingest/F35/launch/round13-tools.log) · [服务预检](../../ptmp/firrtl-ingest/F35/launch/grh-round13-combined-resources.json.start.json) · [第十二轮归档](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-06cf3394c2d341eb8b2e20d0d11bb2de/summary.json)

第十三轮全图达到 **99.37901%（2,498,583 / 2,514,196）**，提高 0.19329 个百分点。消除 5,302 个未匹配名，新增 429 个，净减 4,873 个。全图还剩 15,613 个差异，其中赋值 11,980、位切片与拼接 1,783、状态与存储 1,254、常量 401、mux 188、其他组合逻辑 7。两端重名和无名数为 0。新增名中，116 个为 EnqEntry 的 `_T_` 名称，64 个为 `tpDataTable.raw_rdata` 切片。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round13-combined.json) · [新增名称](../../ptmp/firrtl-ingest/F35/measure-tests/round13-introduced-names.txt)

深度一内存写端和同步读地址样本都以原 GRH Node ID 对齐。IssueQueue 双端均保留 `entries._T_100`，左移样本双端均保留 `csa_3.sum_10`。第十二轮新增的六个 ROB 调试和 L2 端点名称在两端 R4 均已退役。[本轮样本](../../ptmp/firrtl-ingest/F35/measure-tests/round13-combined-focused.json) · [六个样本复核](../../ptmp/firrtl-ingest/F35/measure-tests/round13-round12-new-differences-recheck.json)

隔离采集耗时 28 分 45.42 秒，cgroup 峰值 112 GiB，OOM、OOM kill 和 swap 用量均为 0。R4 库存 SHA-256 为 `f5cabc3197a2749e5bad5994e6333fb75e010b3df17c9833f5b6805e2cebf890`。15 个 pass 通过耗时门，SplitNodes 为 183.03 / 263.54 秒，CommonExpr 为 81.01 / 221.33 秒，第四次 DCE 为 30.28 / 63.01 秒。串行后处理耗时 3 分 10.25 秒，峰值 RSS 为 1,150,660 KiB，零换页。[资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round13-combined-resources.json) · [逐 pass 耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round13-combined-timing.json) · [后处理资源](../../ptmp/firrtl-ingest/F35/launch/round13-combined-postprocess-memory.log)

## 第 14 轮 · 静态取位别名与数组派生表达式

AliasAnalysis 在来源与取位范围均可验证时，将静态切片的消费者迁移到原具名值。对于读操作、寄存器声明及唯一前驱均可核对的标量寄存器读，也可将读操作归还声明节点。CommonExpr 使用解析后的标量前驱 Node ID 识别重复拼接，并沿用具名表达式的归并条件和源排名。定向回归覆盖取位偏移、读操作归属、数组来源和输出语义。第十四轮组合回归 10 项通过。[AliasAnalysis 模块复测](../../ptmp/firrtl-ingest/F35/measure-tests/round14-alias-notes.md) · [CommonExpr 模块复测](../../ptmp/firrtl-ingest/F35/measure-tests/round14-common-expr-notes.md) · [组合回归](../../ptmp/firrtl-ingest/F35/launch/round14-combined-tests.log)

全图同名率为 **99.39027%（2,498,583 / 2,513,911）**，较第十三轮提高 0.01127 个百分点。消除 285 个旧差异，新增为零。剩余 15,328 个差异中，赋值 11,910 个、位切片与拼接 1,568 个、状态与存储 1,254 个、常量 401 个、Mux 188 个、其他组合逻辑 7 个。DecodeStage 的 `decode.finalDecodedInst.exceptionVec_5_11` 和 EnqEntry 的 `_hasWakeupIQ_canIssueBypass_T_4` 在双端退役，EnqEntry 两端均保留 `_wakeupByIQWithoutCancel_T`。`renamePipeDispatch.io.out.bits.exceptionVec_5_7` 仍留在 GRH 全图。此前跳过的 Sc `_newCtr_needUpdate_T_999` 个案仍按全图口径计分。[全图对账](../../ptmp/firrtl-ingest/F35/measure-tests/round14-combined.json) · [样本复查](../../ptmp/firrtl-ingest/F35/measure-tests/round14-combined-focused.json)

采集 `f35-grh-94992627fe874539a82127f234e00eeb` 耗时 28 分 59.94 秒，cgroup 峰值 112 GiB，OOM、OOM kill 和 swap 用量均为 0。15 个 pass 均通过两倍耗时门。R4 库存 SHA-256 为 `0901076b462695bf46734b79b5d1a057a61818c0944ad2e47b3212d707dd2820`。全图保留本轮 `grh-current/` 和冻结的 `gsim-reference/`。第十三轮全量已回收，保留其清单与对账。[资源记录](../../ptmp/firrtl-ingest/F35/launch/grh-round14-combined-resources.json) · [逐 pass 耗时](../../ptmp/firrtl-ingest/F35/measure-tests/round14-combined-timing.json) · [第十三轮归档](../../ptmp/firrtl-ingest/F35/grh-run-evidence/f35-grh-da001638a2e14b91938e6f04a7020a2c/summary.json)

## 收尾提交中的模块级改动

- SplitNodes 在静态取位来源明确、转接的其余读取均可归到刚生成的切片、且分段满足现有成本条件时，重试上游拆分。`SRAMTemplate_289` 的同名数由 278 / 439 增至 342 / 423，消除 80 个旧差异，新增为零。[模块复测](../../ptmp/firrtl-ingest/F35/measure-tests/round15-sram-split-notes.md)
- CommonExpr 在依赖有来源证据、标量转接最终复制同一 SSA 值且代表独占根赋值操作时，可归并共享转接，并迁移仍存活的消费者边界。`EntriesFaluFmacFcvtFcmpF2v` 派生图的同名数保持 38,054，GRH 总数从 38,482 降至 38,476，消除 6 个旧差异，新增为零。[模块复测](../../ptmp/firrtl-ingest/F35/measure-tests/round15-common-expr-notes.md)

折叠寄存器读的试验保留为本地草稿。它通过四项定向回归，两个派生图分别减少两个差异和保持原计数。[草稿与复测](../../ptmp/firrtl-ingest/F35/measure-tests/round15-folded-register-draft/)

收尾版本通过 14 项 Wolvrix 组合回归、33 项 F35 工具测试及 2 项 GSIM 语义交换测试。[Wolvrix 回归](../../ptmp/firrtl-ingest/F35/close-wolvrix/tests/test.log) · [工具测试](../../ptmp/firrtl-ingest/F35/launch/tool-tests.log) · [GSIM 回归](../../ptmp/firrtl-ingest/F35/launch/gsim-close-tests.log)
