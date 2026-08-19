# A0030 step r001/t0/s08：拼接 unroll 新基线复测 与 commit 写侧 detect helper 内联

- task: grhsim-am-coremark  run: r001  trajectory: t0  step: 8/8（t0 末步）  K=2
- proposal: `proposals/r001-t0-s08.md`（Φ 选中 e00040/e00027/e00015/e00001）
- 基线参照：t0 main = e00040（194.792s，**8-19 测量**）；AM y0 = 273.103s；gsim = 24.688s
- 评估日期：2026-08-20（两候选同日、同机、串行；与 e00040 的对照为**跨日**，
  按 A0024/A0025 刻度同代码跨日漂移 ~2.6%，名义差 <3% 的跨日裁决存疑）

## 候选设计与可证伪假设

### c1 `--concat-insert-unroll` 新基线复测（eval e00045）

A0026 的遗留旋钮：e00039 在 e00033 基线上测得 -1.89%（低于 2% 假设门、高于 1%
证伪线，未确认），当时明确「旋钮默认 off 留存，可与新 base 叠加复测」。本步将
3c6fcfe cherry-pick 到 e00040（622a552）之上（4 文件冲突，均为两旋钮相邻位置，
取并存；syntax-only 自检通过），emit_args = e00040 基组 + `--concat-insert-unroll`。

- 假设：残余跨 word 拼接（静态 56,762 站、动态 ~6.8 亿次 outlined 调用）三形内联
  （对齐满字直存/窄跨 word 双语句/≤8word 宽 unroll）叠加到 inline-scalar-helpers
  新基线后，若 splice 调用边界仍是一阶成本，Host 中位较 e00040 降 ≥2%；<1% 证伪。

### c2 `--inline-commit-detect-helpers`（eval e00046，新旋钮）

t0 自有 recon（A0026 块execs×文本站点动态加权盘点）中最大的残余 outlined 池：
commit 写侧 5 个 detect helper——`masked_write_words_detect`（2,506 站）/
`assign_words_detect`（3,573 站）/`dynlane_write_words_detect`（359 站）/
`slice_words_detect`（1 站）/`array_write_scatter_detect`（0 站），合计静态
6,439 站、动态 ~6.4 亿次调用。新旋钮（默认 off）将其从「头文件声明 + runtime
类外定义」改为头文件类内 inline 定义（函数体逐字搬运，`std::min` 改写为三元
表达式避免给头文件新增 `<algorithm>`）；off 逐字节等价（emitter fixture 覆盖）。

- 假设：若 commit 写站 changed 检测的跨 TU 调用边界是一阶成本，Host 中位较
  e00040 降 ≥2%；<1% 证伪。
- 变更面：emit 规则（生成代码形态），文档随候选同步（pipeline.md 新增条目）。

## 结果对比

| cand | eval | commit | Host 中位 | reps | CV | vs e00040(跨日) | vs 同日对方 | compile_s | 门 |
|---|---|---|---|---|---|---|---|---|---|
| c1 | e00045 | `9c0a89d` (s08-c1) | 194.242s | 194242/195032/191523 | 0.95% | **-0.28%** | — | 616.5s | 17/17 ctest、3 rep difftest 全过（73580/49996） |
| c2 | e00046 | `11cbbb9` (s08-c2) | 200.251s | 200251/199361/201073 | 0.43% | **+2.80%** | +3.09% | 623.6s | 17/17 ctest、3 rep difftest 全过（73580/49996） |

## 裁决

- **c1 证伪**：-0.28% 低于 1% 证伪线（且对照跨日、亚 CV）。标量 helper 内联
  （e00040 -10.02%）收掉最热的适配胶层后，残余 splice 调用边界已非一阶——
  e00039 在旧基线上的 -1.89% 未在新基线上复现，**拼接 unroll 轴在 t0 关闭**
  （旋钮默认 off 留存于主线代码，emit 不携带即逐字节等价）。
- **c2 证伪（回退）**：+2.80%（跨日读数，幅度恰在漂移刻度边缘）；同日对照
  c2 比 c1 慢 **+3.09%**，超过跨日漂移刻度，回退为同日实信号。**commit 写站
  detect 调用边界非一阶，detect 内联轴关闭**。
- **winner = e00045**（step 内最高分），已合入 `tes/r001/t0/main`。属噪声级
  机械 adoption（先例 e00008/e00031/e00044）：concatInsertUnroll 默认 off，
  回撤零成本。t0 best 读数更新为 194.242s（名义），机制意义上 t0 止步于
  e00040 的 194.792s 量级。

## 机制分析

- **c2 为什么回退（信息量最大）**：与 e00040 的标量 helper 内联（-10.02%）对照
  极有教学价值——两者同为「消跨 TU 调用边界」，结果相反。差异在函数体形态：
  标量 helper 是几句算术的叶函数（内联后暴露常量传播，体比调用序列还小）；
  detect helper 是**含循环与多出口的函数体**，铺进全部 334 个 blocks TU
  （最热单 TU 2,200 站），每个 commit 写站复制一份循环体——icache/分支预测
  局部性代价超过调用边界收益。结论：**内联收益由函数体形态决定，不由动态
  调用次数决定**；含循环的 outlined helper 不是内联候选，残余 outlined 池中的
  `slice_words`/`index_words`（同为循环体）按同一判据关闭，不再正式评估。
- **c1 为什么微弱**：e00033 已收掉单字退化层（9.59 亿次），e00040 的标量内联
  又压低了每轮求值的绝对成本基数；残余多字 splice 站点单次调用摊薄后，
  边界开销占比跌入噪声。适配胶「按调用边界逐层剥离」路线在 t0 的收益曲线
  明确收敛：-9.44%（part guard）→ -6.83%（word guard）→ -2.78%（单字 splice）
  → -10.02%（标量 helper）→ 残余层均 <1%。
- **编译侧**：两候选 compile_s 616.5/623.6s（emu_build 281.8/284.5s vs e00040
  264.7s，+6~7%），detect 内联未造成 e00035 式单 TU 编译爆炸，预算裕量充裕。

## 对 Φ 下一步的建议

- **t0 已走满 8/8**。evals 46/48，余 2 eval；t1/s08 与 t2/s08 各需 K=2（共 4），
  run 将在预算耗尽处提前收口（A0025 已预告）。建议把余 2 eval 让给
  **restart 前的同日校准重测**（A0025 纪律：e00040/e00033/e00019 等关键对照点
  多为跨日读数，定 y0 前须同日重测），而非开无证据新机制。
- t0 关闭清单更新：拼接 unroll（e00045）、commit detect 内联（e00046）、
  循环体宽 helper 内联（按 c2 判据推断关闭 slice_words/index_words）。
- restart y0 组合材料不变（A0029）：t0 扫描剪枝+宽态首触+标量 helper 内联
  × t1 常量内联+常量存储消除+死宽态消除，机制正交。

## 产物与复现

- 评估产物：`build/tes/grhsim-am-coremark/evals/e00045/`、`.../e00046/`
  （result.json + 各阶段日志）。
- 候选分支：`tes/r001/t0/s08-c1`（`9c0a89d`）、`tes/r001/t0/s08-c2`（`11cbbb9`）。
- 文档：wolvrix `docs/grhsim/grhsim-am-pipeline.md` 新增
  `inlineCommitDetectHelpers` 条目（c2），`concatInsertUnroll` 条目随 c1
  cherry-pick 合入主线。
- 正式评估命令见任务 playbook；emit_args 分别为 e00040 基组 +
  `--concat-insert-unroll` / `--inline-commit-detect-helpers`。
