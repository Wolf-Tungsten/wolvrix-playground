# TNO0032　读端数组的否定写冲突归一化

香山保持解码门槛 64，显式开启新规则后，`reg-to-mem` 从目标 194 组中恢复 180 组、9,299 行。原有 696 个真合并全部保留，总数达到 876 组。CoreMark、MicroBench 按各自专属上游求值排出的前 200 组，各转换 51 组。[逐组结果和前 200 组命中清单](./data/TNO0032_conflict_results.json)

## 调度前的证据

关闭新规则、门槛设为 29 时，发现阶段有 1,600 个匹配行、4 个 family、2 个连续候选。新增报告显示，这两个候选各 160 行，分别被组 947、948 占用，对应 ROB 的两个 `exuData` 半组。可确认归属的行数为 320。基线在组内第 1 行、第 0 个分支报告 `common=0 conflicts=1`，两边的差异项包含 `kLogicNot(kOr)` 和 `kLogicNot(kAnd)`。第二个匹配器给出 `no_direct_or_compound_row_guard`。[门槛 29 控制报告和门槛 64 转换报告](./data/TNO0032_conflict_repro.tar.gz)

原有头两次匹配失败后，新规则只重试地址、数据、掩码、事件和边沿均相符而公共项不同的读端候选。将 `!(hit_A(r) || hit_B(r))` 分解成两个否定条件，每项都要证明只有一个选择本行的地址比较，其余使能项逐项保留。这样 `!(valid && addr == r)` 可在写地址 `w` 上实现为 `!(valid && addr == w)`。任一项不能解释便保留整个原谓词。生产选点只依赖图结构。[pass 选项、合法性检查及报告字段](../../wolvrix/docs/transform/reg-to-mem.md)

77 组证明了每个端口的冲突集合完整对应较高优先级写者，可在顺序写模式下省去这些冲突判断。另 103 组保留显式冲突，按原 mux 分支顺序赋予同地址写口优先级。合成电路回归覆盖外部阻塞者与真实写者仅冲突数相等、无法分解的 OR 项、有符号地址、开启与关闭顺序写，以及重叠候选的原端口和所属组。

## 转换范围

| 原先的行间差异 | 组 | 新增转换 | 仍未转换 |
|---|---:|---:|---:|
| 仅公共项不同 | 186 | 180 | 6 |
| 公共项和冲突集都不同 | 8 | 0 | 8 |
| 公共项和数据都不同 | 6 | 0 | 6（在目标 194 组之外） |

180 组中有 100 组来自 FTQ，4 组来自 ROB，其他位置 76 组。按原模型归属，合计每拍覆盖 7,891 / 5,658 次专属上游求值。ROB 具体转换 `exuData` 和 `paddr` 各两个半组。TNO0029 三字段原型中另外四个 `sqIdx`、`lqIdx` 半组仍属 `priority_guard`。[上游求值与共享分摊](./TNO0031_exclusive_write_upstream_20261122.md)

目标中剩余的 14 组包括 904–907、918–921 共八组 ROB 时间戳。重试后第 1 行的公共项和冲突集仍不同。以组 904 为例，报告保留了当前行的 `kNot(kAnd)` 及冲突地址、使能各自的生产操作。可从这些值 ID 核对该行与第 0 行的地址及使能是否等价。每组都有初次拒绝子原因、阻塞值及其操作类型、第二个匹配器结果与独立的重试结果。因重叠跳过的写端候选另含所有写口和当时占用其成员的组 ID。[完整报告与复现包](./data/TNO0032_conflict_repro.tar.gz)

## 写口和整机正确性

逐行取 pre-pass GRH 中真实写口的使能、下一值、掩码和时钟，对照 post-pass GRH 中同一行的所有内存写口，按优先级从低到高构造选中数据。复用 TNO0029 的逐写口校验口径。将共享上游值作为任意位向量输入，用 Z3 检查“使能不同，或使能打开时掩码内数据不同”能否成立。每组 160 行、29 个新端口。`exuData` 为 64 位，`paddr` 为 48 位，共 640 个不等价查询全部为 UNSAT，覆盖 35,840 个有效载荷位。这里的符号证明覆盖这四个 ROB 组。[逐组证明结果](./data/TNO0032_conflict_results.json)

两个 100,001 拍窗口各有 99,999 条 DiffTest 轨迹与基线逐条一致，CoreMark 另外比对了 35,063 行性能计数。完整 MicroBench 于 225,601 guest cycles、326,377 条 guest 指令到达 GOOD TRAP，225,599 条轨迹全部一致。最终规则重放得到的 post-pass GRH 与计时构建所用规则重放的产物逐字节相同，SHA-256 见汇总。[功能记录和检查点摘要](./data/TNO0032_conflict_results.json)

## 配对测量

对照为 TNO0028 的逐站点 PGO 加终端 mux 优化，新版在同一检查点打开冲突归一化并重新进行站点训练和 Clang PGO。CoreMark 训练，MicroBench 留出。node030 上两个负载分别固定物理核 104、120，各换序四轮，每次 100,001 拍。所有接受样本的 PMU 最低运行比例为 99%，SMT 兄弟空闲率为 100%。表中平均耗时变化按轮求比后取平均。[16 个接受样本](./data/TNO0032_conflict_samples.csv)

| 负载 | 基线 → 新版，宿主指令/拍 | 指令变化/拍 | TNO0029 原型参照 | 基线 → 新版，平均秒数 | 配对耗时变化 | 更快轮数 |
|---|---:|---:|---:|---:|---:|---:|
| CoreMark | 3,145,004 → 3,054,227 | −90,777 | −65,721 | 65.274 → 64.761 | −0.78% | 3/4 |
| MicroBench | 2,832,590 → 2,768,738 | −63,852 | −52,622 | 60.264 → 59.188 | −1.78% | 4/4 |

CoreMark 四轮耗时变化范围为 −2.34% 到 +0.07%，MicroBench 为 −2.72% 到 −0.99%。新版每拍分支预测失败分别增加约 690 和 494 次。指令收益来自本轮 180 组和重训后的整个模型。各模块及分支变化对耗时的独立贡献尚未拆分。首次采样的运行目录名含 `mismatch`，原日志解析器误判失败。修复后从头采集了表中 16 个样本，实际错误行仍由回归测试检出。

## 验证与复现

本轮 C++ 全量构建成功。实际运行全部 133 项 CTest，通过 129 项。`emit-grhsim-cpp`、`emit-grhsim-cpp-bool-zero-group-guard` 和 `transform-comb-lane-pack` 复现了已有断言。`grhsim-compiler-compat` 在 Clang 23 的 native change-reduction 用例失败，用提交前 `645eb4f` 的独立测试源码重建，得到同样的 `from=0 to=172 changed=1 flags=0`。最终版的 `transform-reg-to-mem` 单测另行重跑通过。Python 绑定、香山选项、分组归因和运行日志解析测试通过。[全量测试、基线复现日志及命令](./data/TNO0032_conflict_repro.tar.gz)

普通构建保持现有配置。香山流程通过 `WOLVRIX_XS_GRHSIM_REG_TO_MEM_NORMALIZE_WRITE_CONFLICTS=1` 开启新规则。Python pass 参数为 `normalize_write_conflicts=True`。在仓库根目录更新本次使用的工具后，将复现包解到下列目录，按其中的 `REPRODUCE.md` 重放、证明和测量。

```bash
cmake --build build/armor-dispatch-v1/tools -j8 --target wolvrix_python transform-reg-to-mem
case_dir=build/armor-xs-family-mismatch-v1
mkdir -p "$case_dir"
tar -xzf pdocs/armor_grhsim/data/TNO0032_conflict_repro.tar.gz -C "$case_dir"
```

## 2026-11-23 补充核对

TNO0028 基线有 4,352 条终端 mux 链在提交时求值。开启冲突归一化后，同一选项在 TNO0032 计时模型中选中 0 条。原来 2,240 条链的目标已合并为存储器，其余 2,112 条的目标仍是寄存器。表中的指令和墙钟变化包含这项相互作用及 PGO 重训。

7,891 / 5,658 次每拍是按消费者组分摊给新增 180 组的求值量。只计所有相关消费者都已转换的值，上界为 3,004 / 2,392 次每拍（CoreMark / MicroBench）。两种口径都来自旧模型，实际执行次数随新模型的分片和调度改变。
