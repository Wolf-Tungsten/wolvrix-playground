# A0050 step r002/t0/s06：commit 行动态索引 RMW 合并与安慰剂锚点（2026-08-21）

- action: step（t0 第 6 步，K=2）
- eval 预算：22/32 → 24/32

## 前置 recon（recon-t0s05，wide-mux-chain-fuse 后池地图刷新）

复用 e00019 wbuild，t0 现行 12 旋钮 + `--runtime-profile` 重 emit，emu_build 后插桩
单跑 Host **363.735s**（difftest 金标过 73580/49996；同代码非插桩 e00019 读数
335.129s，插桩开销 ~+8.6%）。产物 `build/tes/grhsim-am-coremark/evals/recon-t0s05/`
（block_execs.txt / block_atom.jsonl / emit / run.log）。

关键画像（总账 655.1G → **640.7G rdtsc ticks，-2.20%**——与 e00019 同窗 -2.19% 的
Host 收益精确互证，宽链融合收益的插桩侧独立确认）：

- **b69159 族残余崩塌，链轴关闭**：b69159 153k→24k cyc/exec（-84.4%）、b69158
  77k→12k（-84.7%）、b69157 78k→14k（-82.1%）；族合计 15.4G → 2.5G。按 A0047
  预设判据（cyc/exec 降至 ~40k 以下）**b69159 族不再是池，宽链轴关闭**。
- 角色账：compute 418.9G/65.4% / commit 221.8G/34.6%。top 块：b93159 40.95G
  （6.39%，静态 unit-stride 流）、守卫残余 b90657 20.80G + b90656 17.52G
  （合计 6.0%，瘦身轴已关闭）、b93141 19.36G（3.02%，窄站写口阵列 = t1
  commit-write-branchless 同族形态）、**b93131 族动态索引位 RMW：b93131 6.81G +
  b93130 5.26G + b93132 3.76G ≈ 15.8G（2.47%）**、b83835 8.80G（176k cyc/exec
  持平，extract_word 宽态 gather + 比较归约树）、b93085 7.88G。
- 墙钟/tick 口径：compute 墙钟 269.3s vs 块 tick 折时 174.5s，**t0 侧同样存在
  ~95s（26%）dispatch/扫描骨架无名池**（与 t1 recon-t1s05 的 ~104s 同族；本步
  未触，需归因 recon 后再候选，不宜盲试）。

## 候选与结果

| cand | eval | 机制 | commit | Host 中位 | CV | 门 | compile_s | 裁决 |
|---|---|---|---|---|---|---|---|---|
| c1 | e00023 | `--commit-row-merge`（默认 off 逐字节等价）：commit Block 内严格相邻、共享（内存目标/动态地址/行内 touched word）的 MemoryWrite(Cond)Mask run（≥3，常量掩码单词形态）融合为单次 index_words + 单行 load + 逐事件条件位合并（ST00011 accum 槽逐事件保留）+ 任一触发才单次最终 store，打破 b93131 族动态索引位 RMW 的 store→load 转发链 | `96429a6` | 338.247s | 0.00% | 17/17 ctest、3 rep difftest 73580/49996 全过 | 990.6s（emu_build 627.8s） | **证伪（+3.25% 回退）** |
| c2 | e00024 | 同窗安慰剂：t0 tip 61b5fd6 原样重测（同 12 旋钮），无机制变更 | `ab20b29`（空） | **327.602s** | 0.17% | 全过 | 976.0s | **winner（锚点），已入 t0/main（内容不变）** |

同窗对照：**c1 vs c2 = +3.25% 回退**（338.247 vs 327.602，两批 CV≈0，差值 10.6s
远超噪声）。假设门 ≥1.5% 改善、证伪线 <0.75% → **决定性证伪且为显著回退**。
winner = e00024（安慰剂空 commit ab20b29，t0/main 内容不变）。

## 假设与证伪条件（事先写下）

- c1 假设：b93131 族 CommitEvent 的动态索引位 RMW（同 index 变量、同行基址、同
  word 偏移、逐位掩码递增）在每事件 load-改-store 形态下构成 store→load 转发链
  （b93131 68k cyc/exec ≈ 7.6 cyc/instr 的访存链签名）；同 key 严格相邻 run 融合
  为单次索引 + 单 load + 单 store（N 事件 → 1 次行往返）使 Host 中位较同窗安慰剂
  降 **≥1.5%**（族池 2.47% ticks，预估捕获 30-60%）；**<0.75% 证伪**（批内 CV≈0
  可分辨）。
- c2 无机制假设：连续第四轮锚点席位，为本窗唯一裁决基准。

## 机制面与静态实证

- 机制面 = emit 规则变更（emitter 侧计划，照 wideMuxChainFuse/dynBlend 先例不动
  调度程序），文档条目随候选提交（grhsim-am-pipeline.md `commitRowMerge`）。
- 等价性论据：严格相邻（run 内无任何其他指令）保证两事件间无观察者；逐事件
  `(cur & ~m) | (d & m)` 链与逐事件 load/store 值等价；data/address 命名目标内存
  自身的事件被别名守卫排除；run 必须落在单个发射 chunk 内（chunk-local 命名稳定
  性）。off 时输出与 e00019 产物 **260 个文本文件 cmp 全等**。
- engagement（全模型 on emit）：**runs=120 / events=3084 / blocks=35**（静态可 merge
  站点 3384 的 91%）；b93131 chunk 内 1702 站点全部并入 run。
- 单测（test_cpp_emitter 新 fixture）：4×128-bit 内存上 3 事件同 word-0 run + 1
  word-1 事件，文本级校验融合形态/顺序/stock 无 `rowmerge_`、header/runtime 除
  模型名逐字节一致，**stock/merge 双模型 harness oracle 运行时等价**（含 OOB 地址
  与 cond 全关路径）。ctest 17/17。
- 弃选记录：replicate-1bit → 掩码（`0-(b&1)`）emit 规则候选经微基准证伪——clang
  -O2 已把 ≤54 级 concat 链完全折叠为 test+cmove（5 条指令，与掩码形态同构），
  静态指令数收益为零，未占用评估预算。

## 机制分析（为什么输）

静态形态确切成立（runs=120/events=3084/blocks=35，b93131 族 1702 站点全部并入
run，off 260 文件 cmp 全等，oracle 等价），运行时却显著为负。归因方向：

- **串行化换掉并行化**：融合体把 N 个事件的 RMW 改成单一 `cur` 累加链——每个
  事件的位合并与 change-detect 都依赖前一事件的 `cur`，构成一条长串行依赖链。
  原形态下每事件独立的 load→RMW→store 由 store→load 转发（STLF）服务，事件间
  无寄存器依赖，OOO 可把多事件的转发/合并流水起来；STLF 的 ~5cyc 成本被事件间
  ILP 吸收。融合把「N 次可流水的行往返」换成「1 次行往返 + 长串行 ALU 链」，
  在 68k cyc/exec 的访存链签名块上反而拉长了关键路径。
- **额外控制流**：`rowmerge_any` 标志 + 条件最终 store 引入新分支；change-detect
  从「wnext vs 独立内存 load」变为「wnext vs 链上 cur」，进一步绑定在串行链上。
- 与 t1 A0048 commit-write-branchless（+1.71%）同族互证并加码：**commit 相的
  「省访存往返/省指令」类优化连续两次静态成立、动态为负**——b93159/b93141 族的
  成本不是指令数也不是行往返数，而是 194MB 状态对象上的数据侧 miss/带宽本体。
  **commit 相优化轴整体关闭外推到「行合并/流量合并」类**，残余开放方向不变
  （纯数据侧布局，且受流扫带宽约束）。

## 测量学观察

- 本窗安慰剂（t0 tip 61b5fd6 原样）读数 **327.602s = t0 历史最快**，上窗同代码
  335.129s（e00019）、再上窗 342.632s（e00020 安慰剂）：同代码跨窗漂移样本 +1
  （-2.2% / -4.4%），连续漂移分量再次确认；本窗为快窗。c1 的 +3.25% 回退是在
  快窗内测得，回退方向不受窗口快慢影响（差值 10.6s ≫ 批内噪声）。
- 锚点席位连续第四轮产出唯一裁决基准；t0 tip 真值口径 = 本窗锚点 **327.602s**
  （e00024，内容 = 61b5fd6 + 12 旋钮）。

## 对 Φ 下一步的建议

- t0 tip = `ab20b29`（内容 = `61b5fd6`），t0 有效 emit_args = 12 旋钮（不含
  commit-row-merge）。b93131 族 15.8G（2.47%）经本步证伪后标记为「行合并类
  不可触」；commit 相 34.6% 全部落入已关闭清单（省指令/分支结构/行合并均证伪，
  数据侧 miss 主导定性维持）。
- t0 下一阶开放池只剩：compute 长尾本体（b83835 8.80G extract_word 宽态
  gather、b93085 7.88G）与 **~95s/26% dispatch 骨架无名池**（compute 墙钟
  269.3s vs 块 tick 折时 174.5s，t0 侧首次定量，与 t1 ~104s 同族）。后者是
  全 run 最大单池，建议先做归因 recon（区分扫描骨架/激活簿记/调派胶，激活
  3.7G 次/eval 簿记是首要嫌疑）再设计机制，不宜盲试。
- evals 24/32（余 8 vs 剩余 10 席，末段需单候选 step）。

