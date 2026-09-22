# NO00056 GrhSIM-IR 冗余掩码消除与共享预算上探（FAILED，用户人工判定）

**最终状态：FAILED（2026-09-22 用户人工判定，见末节）。全部代码修改已撤销，wolvrix 与 `7b1fd50` 零差异。**

节点目标（2026-09-21 用户调整门）：缩减二进制、缓解 ICache 压力，允许 ≤3% 性能回撤。old 对照：`ptmp/no00055_init_zero_elide_20260922/flow-final`（预注册比较值 **71.309667 s**，NO00055 正式 new 均值，goal.md 已登记）。

## 机制（一句话）

发射端维护的**规范形不变量**——任何可读到的 ≤64 位标量值（cpu_local/boundary/objects 槽位、cached 局部量、常量文本）在写入/产生时已按声明位宽掩码（无符号补零、有符号按存储位宽符号扩展）——使三层运行时掩码成为恒等，全部在发射期静态消除：

1. **M1 恒等 cast 省略**（`cast` lambda）：`grhsim_cast_u64(x, srcW, dstW, false)` 当 `!srcSigned && 0 < srcW ≤ dstW` 时等价于 `x`（`trunc(trunc(x,srcW),dstW)`，srcW ≤ dstW 时第二次截断无操作，第一次因规范形是恒等）。符号源（存储为符号扩展，trunc 承重）与缩窄 cast（dstW < srcW）保留。
2. **M2 自规范 op 的 normalize 省略**（compute 存储点）：`exprSelfCanonical()` 按 op 种类证明表达式结果已处于结果位宽的规范形——槽位载入（state/input/memRead，normalize 幂等）与常量任意符号性均可；计算类仅无符号结果：assign、and/or/xor（操作数 cast 已把各操作数压到结果位宽内）、mux/bitSelect/prioritySelect（臂已 cast）、逻辑运算与全部比较/归约（bool 结果）、slice/shift/div/mod（helper 内部 trunc）、concat/replicate-concat 形（Σ 操作数位宽 ≤ 结果位宽时）。**add/sub/mul（溢出/下溢进高位）、not/xnor（`~` 产生高位垃圾）、1 位 replicate 广播（`0-x` 填全 64 位）一律保留 normalize**。
3. ~~**M2b 存储位宽 normalize 简化**：`type.width == 存储位宽` 时省略 trunc 包装。~~ **v1 冒烟后撤销**：该变换对 .text 无收益（存储型宽度的截断 clang 必然消除），但把"同位置不同 trunc 位宽常量"的可参数化差异变成结构差异，拆散分支形状共享分组（base 1595 组 → v1 1473 组），交互损失超过收益。
4. **M3 字面量折叠**：`literal()` 的 `UINT64_C(v)` 已被 `resize(width)` 掩码，直接发射 `static_cast<T>(UINT64_C(v))`；有符号值在发射期数值符号扩展后以无符号位模式打印（避免 INT64_MIN 字面量陷阱，unsigned→signed 转换为良定义取模）。对全部位宽统一生效，不产生结构分歧。

## 分组交互调试（v1/v2 冒烟，2026-09-22）

- v1（M1+M2+M2b+M3）model .text（clang++ -O3，`size -A` ^.text 总和）：**66,710,234 B**，对 flow-final 66,616,245 **+93,989 B（+0.14%）**——方向错误。
- 三方归因：base（HEAD 7b1fd50 无 P5，同 checkpoint reemit）**66,273,153 B**（srcloc 注释哨兵使分支共享分组 1515→1595 组，HEAD 漂移 −343,092 B）；P5 边际 **+437,081 B**（分组 1595→1473、folded_source_bytes 235.2→175.1 MB、排除组 702→820）。
- v2（撤 M2b，留 M1+M2+M3）：**66,738,461 B（+465,308 vs base）**——M2b 无辜。逐文件分解：块调用数不变的 4,193 文件净 **+324,846 B**（纯 elision 仍然净增长！），调用数变化的 352 文件 +570,996 B。
- 指令流证据（task_819，块调用数不变，+8,505 B）：助记序列整体重排，`mov` 2,759→4,395（+59%），`testb→test`/`cmpb` 消失——掩码不只是冗余 AND，还充当**值域收窄屏障**让 clang 维持字节寄存器分配；微实验（手写 4 语句新旧形）二者逐指令一致，证实增长是大函数内涌现的分配/调度偏移，非局部形态问题。
- 中间结论：**"clang 会自己折掉冗余掩码" 在两个方向都错**——它既不会因载入值无从证明窄而留 AND（所以原以为的"删除即赚"不成立），也会因为掩码携带值域信息而在删除后生成更多 mov（所以实际为负）。v3 变体切分：M1+M3（撤 M2 存储侧 normalize 省略）测量中。

## 方向修正（2026-09-22 晚）：elision 降级为可选子项，主轴改预算上探

- v3（M1+M3，无 M2）：**66,383,007 B**，对 base +109,854 B；分解：块调用不变文件净 −101,566 B（任务级纯收益约 −335K，+534K/−636K 高方差），重分组 +211,420 B——M1+M3 的 .text 纯收益存在但薄（~0.5%），分组扰动仍为正增长。M2（normalize 省略）确认为主要增长源（v2−v3=+355K）。
- **结论：P5 elision 假设证伪**——"冗余"掩码在 -O3 下大多已被 clang 消除，剩余包装携带值域信息参与寄存器分配，删除不赚反亏；且文本均匀化使分支共享组归并、热度求和上升、排除增多。三层子机制全部留档（v1/v2/v3 数据），M2b 已撤销。
- 转向节点移交候选 **分支体共享预算上探**（纯基线 HEAD、reemit 冒烟）：base@5.0 66,273,153 / **base@8.0 65,531,447（−741,706 B，1792 组/排除 505）** / **base@12.0 64,915,671（−1,357,482 B，1973 组/排除 324）**。NO00054 在 5.0 实测回退 +0.74%，裕量存在；回退随预算增长需实测。
- 另确认：reemit 流程可直接 `xs_wolf_grhsim_ir_build_emu` 建 emu（BUILD_DIR 建于 flow 目录内），用于预算筛选。
- **运行时筛选（1 对交替、fadvise 驱逐，指示性）**：b8 new 71.776 vs old 71.287（**+0.69%**）；b12 72.897 vs 71.236（**+2.33%**，逼近 3% 节点预算上限）；v3（M1+M3）71.541 vs 71.102（**+0.62%**，非中性——elision 的 mov 涌现在热路径真实存在）。**elision 全部放弃（代码随后还原），节点主轴定为共享预算再平衡。**
- base old 三次采样 71.102/71.236/71.287 vs flow-final 预注册 71.309667：HEAD（srcloc 哨兵分组）漂移运行时中性，正式门可复用 flow-final 为 old（协议：配置未变复用归档；漂移已实测仅影响分组/.text、不影响运行时）。
- **机制增强尝试（热度按块摊销）**：把多分支块 task 的完整采样份额计入其每个块所在组改为 `hotness / taskBlockCounts[task]` 均摊——结果 **ap@5.0 纳入 2221/2297 组（仅排除 76）、.text 61,624,970（−4.65 MB），但筛选回退 +7.0%**（76.213 vs 71.230）；ap@8.0 排除 0 组、.text 反而 +85K（边际小组折叠净负）。证明 sum 热度虽保守却是回归控制的承重墙；摊销泄压过度。**ap@5.0/ap@8.0 尝试 REJECTED。**
- 纯预算旋钮探测（无代码改动）：base@8.0 65,531,447（−741,706 B、筛选 +0.69%）/ base@12.0 64,915,671（−1,357,482 B、筛选 +2.33% 逼近 3% 预算边缘）。该旋钮仍有少量空间，但收益/回退比已显著劣于 NO00054（+0.74% 换 −6.39 MB）。
- ap@2.5 探针在建 emu 前由用户叫停。

## 最终判定：**FAILED**（2026-09-22 用户人工判定）

- 节点内三条路径均被证据否定：M1/M2/M3 掩码省略（.text 净增长 + 运行时 +0.62% 筛选回退）、热度按块摊销（+7.0% 回归）、预算纯旋钮余量稀薄（8.0 仅 −0.74 MB）。
- 用户指示"不要在泥坑里打滚"，判定节点 FAILED。全部代码修改已撤销：**wolvrix 与 HEAD `7b1fd50`（srcloc 提交）零差异**（elision stash 已丢弃、`cpu_block_share.cpp` 已 checkout 还原）；根仓库无代码改动。
- 保留普查工具 `scripts/grhsim_cast_fold_census.py`（cast 位点分类：1,263,553/1,271,381 = 99.38% 恒等可省略——该池在文本层巨大但已被 clang 与共享机制覆盖）。
- 教训（移交）：① P5 方向关闭——"冗余掩码"在 -O3 下非冗余，删除净亏；② 分支共享的冷排除经济学对文本均匀化敏感（elision 归并组→热度求和升→排除增多），任何大规模文本重写都需重估共享分组；③ 热度 TSV 为 NO00054 时期旧 emu 采样，若继续使用预算旋钮应先刷新热度画像；④ 发射层到顶的结论（NO00046/47）再次复证。
- 当前最佳仍为 NO00055（71.309667 s，对 gsim 1.518363×）；下一节点 old 对照不变：`ptmp/no00055_init_zero_elide_20260922/flow-final`。goal.md 尾部候选清单其余项（管线末端 canonicalize、boundary 写回批量、commit write_cell 形态、常量表跨组去重）保持开放。

## 不变量论证（语义约束链）

- 写入侧全覆盖：compute 存储统一过 `normalize()`（cpu_emit.cpp 存储点）；state 提交经 `cpu_write_scalar`/`cpu_write_cell`/`cpu_stage` 等 helper 内部 `grhsim_trunc_u64(merged,Width)`；init 经 `literal()`/`normalize()`（NO00055 零省略只删“对已零 arena 的零写”，不破坏规范形）；DPI inout/sideCall 输出 normalize；输入在 `eval()` 捕获时 normalize；shadow→objects publish 拷贝的是已规范形字节。无绕过 normalize 的原始poke入口。
- 读取侧 `value()` 只返回四类文本：槽位载入（规范）、cache 局部量（载入副本）、`staticScalars_` 常量（literal 文本，自带掩码/折叠）、readAlias 态载入（规范）。形状共享（NO00053/54）把常量替换为表项载入时保留了原 `grhsim_trunc_u64(...,w)` 包装，规范形不破。
- 有符号值以“按存储位宽符号扩展”为规范形；M1/M2 对符号源与符号结果一律保留原包装，仅 M2b 对“位宽==存储位宽”的符号类型生效（此时符号扩展与 C++ 转换逐位一致）。
- 宽值（>64 位）走字数组 helper，不在本机制范围（normalize 对宽值本就直通）。

## 普查与预期

- flow-final 生成文本：`grhsim_cast_u64` 站点 **1,271,381**，其中可省略（无符号且 srcW ≤ dstW）**1,263,553（99.38%）**；保留：符号源 2,136、缩窄 3,854（另有 1,838 处跨行站点普查脚本未归类）。`static_cast<…>(grhsim_trunc_u64(` normalize 站点 **1,333,678**；`grhsim_slice_dynamic_u64(grhsim_trunc_u64(` 内层冗余截断 **170,782**。
- 梳理文档（`ptmp/cpu_emit_indent_20260921/重复模式梳理_20260921.md` P5）回归上限 ~15 MB（共线特征，宜作上限看）。
- 止损线：仿真达 71.309667×1.5 = **106.96 s** 立即终止记 REGRESSION_KILLED；生成/编译各 1800 s kill-switch。

## 实现（已全部撤销）

- `wolvrix/lib/grhsim/backend/cpu_emit.cpp`：`cast` lambda M1；`normalize()` M2b；`literal()` M3；新增 `exprSelfCanonical()` 白名单判定；compute 存储点按判定跳过 normalize；计数器与 `const_fold_*` 摘要行。**FAILED 判定后全部还原（stash 丢弃 + checkout），wolvrix 与 `7b1fd50` 零差异。**
- `wolvrix/tests/grhsim/test_cpu_emit.cpp`：compact-walk 断言曾更新为新字面量形态，随代码一并还原。
- `wolvrix/lib/grhsim/backend/cpu_block_share.cpp`：热度按块摊销改动，ap@5.0 筛选 +7.0% 后还原。
- 保留普查工具 `scripts/grhsim_cast_fold_census.py`（根仓库，随本报告提交）。

## 结果

### 单测（2026-09-22）

- `make test_grhsim_cpu_emit` 通过（95.3s；全部 ASan/UBSan 行为夹具：bitwise/bit_select/mux_chain/init/startup/compact-walk 等）。

### reemit 冒烟（同 checkpoint 快速通道，2026-09-22）

- 命令：`make reemit_grhsim_ir GRHSIM_REEMIT_MODEL=…/no00055…/flow-final/xiangshan_grhsim_ir.json GRHSIM_REEMIT_FLOW=…/no00056…/flow-reemit` + `COMMIT_COMPACT_WALK=1 COMMIT_MEM_WALK=1 SHAPE_TWIN_SHARE=1 BRANCH_SHAPE_SHARE=1 BRANCH_SHAPE_HOTNESS=…/task_hotness.tsv BRANCH_SHAPE_GROWTH_BUDGET=5.0`（与 flow-final 完全同选项）。
- 发射统计（write 相位）：**cast_elided=2,067,212 / cast_kept=8,699（99.58% 省略）**；**normalize_elided=3,075,876**；normalize_storage=59,908；init 相位 literals=2,573（常量字面量另以 staticScalars_ 形态计入）。
- 文本抽查确认形态：state.read 变为纯槽位拷贝、and/or 去 normalize 包装、concat 链去 normalize、`static_cast<bool>(UINT64_C(0))` 字面量折叠。
- .text 与分组的三方归因见上节"分组交互调试"（本冒烟即 v1：66,710,234 B）；srcloc 注释对 .text 无影响（task_3974 新旧源仅差注释行、同编译器 .text 逐字节一致 289,414 B）。首版冒烟曾误用 `c++`（g++）编译模型致 +22% 假象，后续一律 clang++（与正式 emu 一致）。

### 正式门（未执行——节点 FAILED，见上方判定）
