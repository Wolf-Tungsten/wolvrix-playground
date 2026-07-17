# TNO0102 Stage 17 targeted-direct active-mask gap-pack plan

记录日期：2026-07-17

状态：计划。Stage 17 只把 Stage 16 已验证的 non-table direct zero-hole plan 发到 generated C++；当前没有实现、O3、功能或 SimTop 结果。table lowering 保持原样，待独立 runtime category counter 证明 hotness 后另立阶段。

## 1. 目标与证据

[TNO0100](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) 在 current native-hybrid、commit cap `4096` 上完成 no-mutation production probe。non-table direct global path 的 contiguous write/chunk proxy 为 `653,299`，等价 zero-hole plan 为 `623,294`，静态减少 `30,005/-4.592843%`；candidate 为此额外覆盖 `85,146` 个零 byte。default、explicit-off 与 probe 的全部 generated artifacts byte-exact，planner、validator 与 self-test 均通过；完整回归见 [TNO0101](./TNO0101_stage16_full_regression_gate_20260717.md)。

这组数字足以进入 targeted mutation，但不是 runtime 收益预测。Stage 17 的目标是隔离回答一个问题：只替换 non-table direct active-mask statement encoding，能否在功能等价的同时改善 SimTop 50k。BAE、DAG、supernode 数不会作为硬性前置门槛；最终裁决仍是 current default NO0300、ASLR 关闭下的严格 SimTop 50k。

## 2. Policy 与默认配置

`activeMaskGapPackPolicy` 扩展为三个值：

- `off`：不创建 planner/probe，不改变 Stage 16 前的 production lowering；
- `probe`：运行 planner、validator 与分类统计，但仍发 baseline source；
- `targeted-direct`：只对通过 validator 且 write 数严格少于 baseline contiguous plan 的 non-table direct group 发 zero-hole chunks。

C++ native default 保持 `off`。Python `None` 继续表示不设置 attribute，XS 只在 `WOLVRIX_XS_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY` 显式给值时做 sparse override；没有 XS 专用隐式默认，也不把 low-level `WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY` 回写成高层配置。配置来源日志须能区分 `cpp-default`、`cpp-low-env` 和 `xs-override`。

本阶段完成性能闭环前不修改 native default。若 targeted-direct 在有效双 NUMA 结果中方向一致且超过噪声，再另立 adoption 记录，把默认直接改在 C++ 中；若中性或回退则保持 `off`。这避免脚本层对 XS 暗设默认后与直接 API、其它设计或后续 C++ 默认漂移。

## 3. 冻结不变量

targeted-direct 只允许改变 selected non-table direct active-mask write statements。以下均冻结：

- graph、activity schedule、topological order、supernode 与 active ID；
- compute/commit partition、batch 边界与 batch/function/file order；
- value slot、state layout、active array 大小和字段顺序；
- activation owner 分类、local/global target split 与 target mask；
- conditional expression、wrapper、分支选择和 statement 所在位置；
- direct/table 判定阈值与 baseline table representation；
- deferred direct final、deferred aggregate final、memory-row、seed/initial、commit-range 及其它 excluded path；
- direct-state-read、pure-event bypass 和 commit cap `4096` 等 current native-hybrid 默认配置。

planner 必须继续按 `(writes, hole bytes, stable width/order tie-break)` 选择确定方案。candidate chunk 由首个尚未覆盖的 real entry 锚定，只能使用 `1/2/4/8` byte width；所有 real byte/mask 必须精确覆盖一次，hole byte 的 mask 必须为零，不得产生额外 active bit。array bounds、overlap、anchor、mask、metadata 与含洞 chunk 的 logical 64-byte lane no-cross 均由独立 validator 再检查。validator 失败不得静默采用未验证 candidate；production targeted run 应失败并保留可定位的 invalid 分类。

table 必须在 direct/table 分支确定之后保持 baseline lowering。不能因为 candidate chunk 数减少而把 table 改判成 direct，也不能把不同 condition 或 owner 的 target list 合并。

## 4. 语义与机器级风险

zero-hole chunk 以更宽的 `1/2/4/8` byte RMW helper 合并多个 nonzero byte，中间或尾部 hole 的 mask 为零。按现有 GrhSIM 单线程 `eval()` 契约，这与多个 baseline OR/RMW statement 等价；同一 model instance 不支持并发 `eval()`，因此跨 byte RMW 不引入新的合法并发语义问题。它不引入新的 active bit，也不改变同一 eval 内的 producer/consumer 顺序。本阶段不把这些 helper 宣称为原子操作，也不扩大 runtime 契约。codegen 自身仍可并行：planner 对每个 group 独立计算，统计只通过 mutex 聚合；serial/parallel emit 必须生成 byte-exact source 和确定统计。这与 generated model 的单线程运行契约是两件事。

主要风险包括：

- 更少的 helper 调用可能换成更多或更宽的 load/store，静态 write proxy 未必减少动态 instructions；
- unaligned `memcpy` RMW 可能跨实际 cache line，增加 load/store split 或 store-forwarding 代价；
- planner 的 logical `index/64` lane 只基于数组下标。active array 未经 `alignas(64)` 证明时，它不等于物理 cache-line 边界，no-cross gate 不能被表述为 cache-line-safe；
- 各 activation group 的动态 fire 分布未知，静态减少 `30,005` chunks 可能集中在冷路径；
- compiler inline、constant folding 与 source/function layout 变化可能抵消局部收益。

因此实现后即使 source size 或局部汇编有温和疑点，只要没有明显错误或灾难性膨胀，仍进入功能与 SimTop gate，避免仅靠静态直觉漏掉收益。

## 5. 实现与 focused gate

实现限于复用 Stage 16 已验证的 planner/validator，并在 `targeted-direct` 下把 selected chunks 交给现有 direct unconditional/conditional emitter。不得为 targeted path 新增第二套 mask 规划逻辑。统计增加 selected groups、baseline/candidate writes 与 savings，并与完整 non-table probe totals 对账；table 统计可继续观测，但 source 必须不变。

focused gate 至少覆盖：

1. C++ attribute、low-level env、Python/native binding 与 XS sparse override 接受 `off|probe|targeted-direct`，非法值给出一致诊断；
2. 未设置选项的 C++ native default 与 explicit `off` byte-exact，`probe` 也与它们 byte-exact；
3. targeted fixture 中只有包含合法 zero hole 且 writes 严格下降的 direct group 改变，连续/no-gain group 保持 baseline；
4. 32-entry 及以上 table、conditional wrapper、local-only 与所有 excluded owner 不变；
5. targeted serial/parallel emit 的 artifacts 与归一化统计 byte-exact；每个 group 的局部 planner 结果不得依赖 worker 调度，mutex 聚合不得改变稳定输出顺序；
6. selected source 中逐 byte mask 等价、bounds/lane validator 全过，selected savings 与实际 emitted chunk 数精确对账；
7. 子模块 target build、相关 pybind/XS tests、完整 build 和串行 CTest 不新增失败。

## 6. Production source 与 O3 gate

在同一 fresh current-default checkpoint 生成 default、explicit-off、probe 和 targeted-direct 四套 SimTop：

- default/off/probe 的 artifact manifest、source checksum 与 [TNO0100](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) current native-hybrid source 保持 byte-exact；
- targeted 的 artifact 集合、非 schedule artifacts、batch/file order、函数签名和 frozen conditional/table text 保持不变；
- targeted source diff 只允许 selected direct active-mask statements 从 baseline chunks 变成 validator 批准的 zero-hole chunks；
- production selected counts 必须与 probe 的 non-table `gap_improved` 子集、实际 source diff 和重新扫描结果一致。

随后用完全相同的 O3 flags 构建 default 与 targeted ELF，比较 `.text/.data/.bss/.rodata/.eh_frame`、符号/函数大小、active-mask helper 调用或 inline 汇编、unaligned wider RMW 以及可能的实际 cache-line crossing。logical lane 只作为 planner proxy 单列，不用它替代 ELF/地址级检查。出现 unexplained non-selected source diff、validator failure 或异常的大幅代码膨胀时停止进入 runtime；普通小幅 size 波动保留到 50k 裁决。

## 7. 功能与 SimTop 50k gate

default 与 targeted 先完成 fixed-ASLR 100、10k、50k 功能对照，校验退出状态、cycles、关键输出和既有 compare 口径。功能不等价立即回滚 candidate，不以 perf 继续掩盖 correctness 问题。

性能沿用 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的严格协议：

- 每条命令先 `source env.sh`，并用 `setarch x86_64 -R` 关闭 ASLR；
- 每个 NUMA node 使用 `/dev/shm` 中独立 inode，先在本地 node 完成 ELF page placement；
- 同时使用 `taskset -c <cpu>` 与 `numactl --physcpubind=<cpu> --membind=<node>` 绑定 CPU 和内存；
- 采用镜像物理核，避开 SMT sibling，并在运行前执行 30 秒 whole-node idle gate，运行期间持续监控整个 node；
- default/targeted 在 N0、N1 分别跑平衡 ABBA 与 BAAB，保留每 run 的 perf、wall、gate、affinity、mem policy、inode/hash 和 monitor 证据；
- 以 cycles 为主口径，同时检查 instructions、IPC、frontend/backend、branch/cache/TLB 等已有事件，防止把负载或 page placement 漂移误判为收益。

[TNO0098](./TNO0098_stage7_plus_strict_numa_window_recheck_and_retest_queue_20260717.md) 记录的 N1 whole-node gate 当前仍受外部可迁移负载阻塞。Stage 17 不因此降低 idle/min-CPU/运行期门槛，也不把被污染的 N1 数据纳入结论；N0 可以先取得 interim 数据，但 native default adoption 必须等待有效 N1 对称复测。已完成的 N0 strict balanced 方法与证据格式可参照 [TNO0099](./TNO0099_stage14_native_hybrid_n0_strict_balanced_runtime_20260717.md)。

## 8. Table 后置边界

table 类在 Stage 16 中是三种不同口径：current per-entry table `89,903` writes、contiguous chunk representation proxy `19,942`、zero-hole chunk proxy `17,530`。`89,903 -> 17,530` 同时混入 table representation rewrite 和 gap pack，不能与 direct `653,299 -> 623,294` 相加；同表示 gap-only 机会只能写成 `19,942 -> 17,530`。

Stage 17 不修改 table。后续先以独立、默认关闭且不改变 production 行为的 runtime category counter 统计 table group 的 evaluated/change/hit、condition/reset/cold 分布，再决定是否值得测试 contiguous table rewrite；只有在相同 representation control 已建立后，才能另测 table gap pack。table contiguous 与 table gap 不得同 stage、同 policy 或同 A/B 中混测，否则无法归因。

## 9. 阶段交付与提交

本计划之后的实现、focused/production source gate、O3/功能 gate、严格 NUMA runtime 和 adoption/stop 决策按独立议题新增 TNO，不向本文提前补写结果。代码提交以 Stage 17 targeted-direct 整体为粒度：先提交 `wolvrix` 子模块，再提交父仓 submodule pointer、XS 脚本与对应文档；不为单个计划或单条测试拆碎提交，也不纳入 generated build/perf artifacts。
