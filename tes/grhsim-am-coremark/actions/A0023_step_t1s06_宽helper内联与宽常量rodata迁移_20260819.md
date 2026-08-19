# A0023 - step r001/t1/s06：宽 helper 头文件内联与宽常量 rodata 迁移

日期：2026-08-19。action 类型：step（trajectory t1, step 6, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t1-s06.md`。

本 action 只使用 t1 轨迹的 Φ 节点 `e00030` / `e00018` / `e00001`。共同父节点为
t1/s05 winner `e00030`（Host 中位 230447 ms），继承参数：
`--block-chunk-instructions 3000 --resize-elision --inline-scalar-helpers
--inline-scalar-constants --inline-scalar-constant-storage-elision`。
两个候选分别作用于宽值 word-helper 的调用边界与宽常量的存储表示，机制互异。

## 离线 recon（正式评估前的证据收集，均为 t1 tip e00030 同代码的静态盘点）

对 e00030 的 emit 产物（`build/tes/grhsim-am-coremark/evals/e00030/emit/`）做了
静态站点普查：

- 残余 outlined 宽 word-helper 站点：`insert_words` 129,506、`zero_words`
  43,847、`assign_words` 23,411、`slice_words` 23,322、`replace_window_words`
  12,817、`assign_words_from_scalar` 2,024，合计约 23.5 万；其中
  `insert_words` 源宽 ≤64bit 的退化站点 79,841（对齐 38,183 + 错位 41,658，
  占 61.7%），`zero_words` ≤2 word 站点 23,941，`assign_words` 双方 ≤2 word
  站点 14,729。这是 t1 的 helper 内联轴（e00018 的 531K 标量站点）在宽值层的
  同类残余。
- 宽常量普查（临时探针，emit 期统计，探针代码未进候选）：不可写宽标量常量
  （`InitKind::Constant`、>64bit、非数组）25,654 个、合计 1,643,970 words，
  占 24,304,307-word 可变宽池（约 194MB）的 **6.8%**；其中非零 word 仅
  30,077。init() 的 1,663,331 条宽字面量 store 里约 98.8% 落在这些常量槽上；
  块代码中 742,671 处字面量宽池引用有 56,797（7.6%）指向常量区间。

## 候选设计与可证伪假设

### c1 `--inline-wide-helpers`

- 分支 `tes/r001/t1/s06-c1`，commit `188f6b2`，eval `e00035`。
- 把 `zero_words` / `assign_words` / `assign_words_from_scalar` / `insert_words`
  / `replace_window_words` / `slice_words` 六个宽 word helper 从 runtime TU 的
  out-of-line 定义改为生成头文件内类后的 `inline` 定义（函数体逐字一致），使各
  Block TU 在字面量宽度/偏移的调用点做常量传播并展开小 word 循环。`_detect`
  变体与数组/动态 lane helper 保持 outlined。新增 emitter 单测
  `testInlineWideHelpers`（头文件定义存在、runtime 定义消失、生成模型可编译）。
- 假设：若 t1 tip 上约 23.5 万个宽 helper 跨 TU 调用边界是一阶适配成本，
  头文件内联后 Host 中位较 e00030 降 >=3%；若 <1%，则 helper 边界轴在宽值层
  证伪（e00018 的收益主要来自窄标量层）。

### c2 `--wide-constant-rodata`

- 分支 `tes/r001/t1/s06-c2`，commit `6fe40ab`，eval `e00036`。
- 不可写宽标量常量（`InitKind::Constant`、>64bit、非数组、非端口/非 declared）
  从可变宽池 `wideValues_` 迁入独立零初始化常量池 `wideConstantValues_`：
  存储分配期分流 offset，`wideDataExpr` 单点重定向读取，`init()` 只为迁移常量
  的非零 word 发 store（零 word 由成员 `{}` 初始化覆盖）。AM validator 保证
  instruction 不写常量变量，端口路径因 pin 集排除不受影响。新增 emitter 单测
  `testWideConstantRodata`（常量池声明、非零 word 单 store、块代码读取重定向、
  生成模型可编译）。
- 假设：若宽常量占用的 6.8% 可变池与 1.64M 行 init store 是可收的状态/初始化
  成本（e00030 窄常量瘦身 -4.52% 的宽值层对应），迁移后 Host 中位较 e00030 降
  >=2%；若 <1%，则宽常量层对运行时非一阶（但编译体量收益另计）。
- 实施前 smoke emit（真实模型，非正式评估）实证迁移按设计生效：迁移 25,654 个
  常量 / 1,643,970 words；可变池 24,304,307 -> 22,660,337 words（-6.77%）；
  init() 宽字面量 store 1,663,331 -> 19,361 行（常量池非零 word store 30,077
  行另行发射）；块代码 56,797 处读取重定向到常量池。

## 正式评估结果

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00030 |
|---|---|---|---:|---|---:|---:|
| e00035 | c1 `--inline-wide-helpers` | ok；ctest 17/17；3 rep difftest 全过 | 2091.2s | 229884 / 228935 / 228010 | **228935 / 0.41%** | **-0.66%** |
| e00036 | c2 `--wide-constant-rodata` | ok；ctest 17/17；3 rep difftest 全过 | 563.7s | 229105 / 232901 / 234293 | **232901 / 1.16%** | **+1.06%** |

六次 rep 均 rc=0、`instrCnt=73580`、`cycleCnt=49996`，nemu 在线 difftest 无
mismatch；CV 均低于 5% 噪声门。阶段耗时：e00035 wolvrix 105.8s / emit 63.6s /
emu_build 1757.5s（b38653 所在单 TU `blocks_18_part_5.cpp` 含 8,279 个内联宽
helper 调用，单 TU 编译 ~28min 成为长极点）；e00036 wolvrix 105.1s / emit 64.0s
/ emu_build **230.0s**（较 e00030 的 697.5s **-67%**，init() 瘦身兑现）。

## 机制分析与裁决

**c1 未达假设门（机械 winner）**：-0.66%（CV 0.41%）是亚 1% 弱正，不满足 >=3%。
宽 word-helper 的跨 TU 调用边界在 t1 当前代码布局下不是一阶成本——e00018 的
-9.69% 收益来自窄标量 slice/shift/signed helper 的热路径调用，宽值层的
零/拷贝/拼接 helper 调用开销相对块内计算量可忽略。同时内联把 emu_build 从
697.5s 推到 1757.5s（mega-block TU 超线性膨胀），编译代价与收益严重不成比例。
**宽 helper 内联轴关闭**：后续 t1 候选不应携带 `--inline-wide-helpers`。该 knob
默认 off（emit 不携带即逐字节等价），机械合入 t1/main 与 e00011 先例同类、无害。

**c2 运行时小幅回退、编译侧兑现**：+1.06%（CV 1.16%，reps 229.1/232.9/234.3
递增，有轻微漂移迹象）。6.8% 可变池收缩与 56.8K 处读取重定向未产生运行时收益
——宽常量读取不在热路径，双池反而可能分裂 gather 局部性。**宽常量迁移的
运行时轴关闭**；但 init() 宽 store 从 1.66M 行降到 19K 行使 emu_build 减半以上，
该 knob（默认 off）是未来编译门紧张时的减压选项，可与运行时候选叠加评估。

裁决：winner = **e00035**（score `-228935`），已合入 `tes/r001/t1/main`。
t1 best 从 230.447s 更新为 **228.935s**（较 AM y0 273.103s 累计 **-16.16%**），
仍为 gsim 24.688s 的 **9.27x**，AM/gsim 绝对差距关闭 **17.87%**。
t1 完成 6/8，run 使用 36/48 eval。

对 Φ 下一步的建议：t1 余 2 步（s07、s08）。t1 的两个一阶轴（C++ 调用边界、
常量/状态瘦身）在宽值层均已关闭，窄值层的残余（divmod 内联 -1.64% 为已证
弱正旋钮、可叠加）不足以支撑一阶步进；进一步收益需要动态证据定位。
建议 s07 候选设计前先做 t1 tip 的 per-block runtime-profile recon
（`--runtime-profile` 离线插桩，非计时），按块周期权重找下一个一阶池；
不建议在无前述 recon 的情况下继续堆叠亚 1% emit 微调。

## 依赖复用与评估纪律

正式命令均只调用任务 `evaluator.py`；宽常量普查探针为临时 emit 期统计（独立
recon 目录、不计时、未进候选分支）。每个 eval 的 `wbuild`/`emu_build` 保持
独立，FetchContent 依赖由 evaluator 重定向到 `wolvrix/build` 本地 clone，C++
编译使用共享 `build/tes/ccache`；正式评估全程未联网。
