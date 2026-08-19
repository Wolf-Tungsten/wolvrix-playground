# A0026 - step r001/t0/s07：跨 word 拼接 unroll 与窄标量 helper 内联

日期：2026-08-19。action 类型：step（trajectory t0, step 7, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t0-s07.md`。

本 action 只使用 t0 轨迹的 Φ 节点 `e00033` / `e00022` / `e00004`。共同父节点为
t0/s06 winner `e00033`（Host 中位 216481 ms），继承参数：
`--block-chunk-instructions 3000 --branchy-mux --resize-elision
--init-zero-elision --source-part-activity-guard --source-word-activity-guard
--wide-storage-first-touch --concat-insert-inline`。

## 离线 recon（正式评估前的证据收集）

复用 recon-t0s06 的逐块 execs（e00027 同调度，block id 稳定）对 e00033 emit
产物做站点×块execs 动态加权（`evals/e00033/emit` 全量文本扫描）：

- 残余 outlined `insert_words`/`replace_window_words`：静态 57,610 站
  （insert 56,759 + replace 852），动态 **6.89 亿次**。按形态分：
  窄跨 word（≤64bit 越界）7,896 站/1.12 亿；对齐满字 2,937 站/0.17 亿；
  宽 65-128bit 23,909 站/1.83 亿；129-256bit 8,029 站/0.99 亿；
  >256bit 14,839 站/2.77 亿。按 word 数：≤2w 32,550 站/2.97 亿、
  3-4w 9,074/1.02 亿、5-8w 6,476/0.89 亿、9-16w 4,456/0.91 亿、
  17-32w 4,398/0.92 亿、>32w 656/0.18 亿。
- 全部 outlined helper 动态加权盘点（dyn 亿次）：`slice_value` 424,066 站/
  **19.35 亿**、`index_words` 3.66 亿、`assign_words_detect` 3.58 亿、
  `masked_write_words_detect` 2.51 亿、`slice_words` 2.39 亿、
  `shift_right` 1.80 亿、`shift_words` 1.79 亿、`shift_left` 1.58 亿、
  `divide_value` 1.27 亿、`bitwise_words` 0.77 亿、`zero_words` 4.49 亿次调用
  （动态清零 52.9 亿 word）；`extract_word`/`concat_value`/`resize_value`
  虽 31.9/40.9 亿次但已是头文件 `constexpr`（编译期可内联，非候选）。
- `zero_words` 前导消除推广**离线否决**：对 42,972 个前导做语句组覆盖分析，
  仍可消的前导为 0（e00033 已收完全部全内联可覆盖组；余下 41,860 个前导
  所在的组均仍含 outlined 调用、动态 4.38 亿次）——该轴不独立于 c1，
  只有 c1 类 unroll 落地后才可能有后续覆盖。
- perf 被 kernel 禁（perf_event_paranoid=4，软事件亦不可用），未做采样剖面；
  上述加权盘点替代之。

## 候选设计与可证伪假设

### c1 `--concat-insert-unroll`

- 分支 `tes/r001/t0/s07-c1`，commit `3c6fcfe`，eval `e00039`。
- e00033 只内联单字退化拼接；本候选把落回 outlined 的操作数分三形 unroll：
  (A) 对齐满字（≥128bit、64 对齐、≤8 word）逐 word 直接 store（独占 word，
  参与 zero_words 前导消除）；(B) 窄跨 word（≤63bit、shift+width>64）两句
  OR/RMW；(C) 宽 ≤8 word 逐源 word covered/spill 语句（常量折叠 mask/shift，
  满 covered word 退化直接 store，保守不参与前导消除）；>8 word 保持
  outlined。off 时逐字节等价。新增 emitter 单测（文本形态 + stock/unroll
  双模型逐位比对 harness）。
- 离线冒烟：unroll 命中 aligned 2,525 / crossing 7,029 / wide 37,679 站；
  残余 insert_words 站点 56,763 → 10,379（其中 867 站为 width=64 且 shift≠0
  的越界情形，Case B 显式条件未覆盖；其余为 6k-8kbit 超宽）。
- 假设：残余 6.89 亿次跨 word outlined 拼接调用若是一阶适配成本（调用边界 +
  逐迭代运行时边界检查），unroll 内联后 Host 中位较 e00033 降 >=2%；
  <1% 则拼接调用边界在 e00033 后已非一阶。

### c2 `--inline-scalar-helpers`

- 分支 `tes/r001/t0/s07-c2`，commit `622a552`，eval `e00040`。
- t0 主线窄标量 `slice_value`/`shift_left`/`shift_right`/
  `arithmetic_shift_right`/`signed_value` 仍为「头文件声明 + runtime .cpp
  定义」的跨 TU outlined 调用；本候选把 5 个定义移入生成头文件
  `static constexpr`。off 时逐字节等价。新增 emitter 单测（开/关文本形态 +
  stock/inline 双模型 harness）。
- 离线加权：5 个 helper 静态 534K 站、动态 **22.5 亿次**调用
  （slice_value 19.35 亿为主），是 t0 当前最大 outlined 调用池。
- 假设：窄标量 slice/移位/signed 的跨 TU 调用边界（阻碍常量传播与指令选择）
  是一阶适配成本，头文件内联后 Host 中位较 e00033 降 >=3%；<1.5% 则
  标量 helper 调用边界非一阶。
- 与 c1 机制互异：c1 动宽值 word 内存 splice 的写路径（循环展开/边界检查
  消除），c2 动窄标量 ALU 值计算的读/算路径（constexpr 内联 + 常量传播）；
  两者函数集、代码区、风险面（c1 代码体积、c2 编译预算）均无交叠。

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00033 |
|---|---|---|---:|---|---:|---:|
| e00039 | c1 concat-insert-unroll | ok；ctest 17/17；3 rep difftest 全过 | 604.0s | 213608 / 212386 / 210908 | **212386 / 0.64%** | **-1.89%** |
| e00040 | c2 inline-scalar-helpers | ok；ctest 17/17；3 rep difftest 全过 | 603.3s | 196006 / 194290 / 194792 | **194792 / 0.45%** | **-10.02%** |

e00039/e00040 六 rep 均 rc=0、`instrCnt=73580`、`cycleCnt=49996`，nemu 在线
difftest 无 mismatch；两候选与对照点 e00033 同为 2026-08-19 当日测量，不涉
跨日漂移（A0024 刻度）。e00039 阶段耗时 wolvrix 107.6s / emit 63.6s /
emu_build 267.0s；e00040 为 105.8s / 65.4s / 264.7s。两候选 rep1 的
loadavg_before≈14.5-14.9 为 evaluator 自身 emu_build 刚结束的 1-min
loadavg 滞后尾部（A0006 已定性），CV 均干净。

c1 静态发射变化（emit.log `concat unroll stats`）：aligned 2,525 / crossing
7,029 / wide 37,679 站命中 unroll；残余 `insert_words` 站点
56,763 → 10,379（867 站为 width=64 且 shift≠0 的跨 word 情形，Case B 显式
条件未覆盖；其余为 >8 word 超宽操作数），`replace_window_words` 残余 1 站。

## 机制分析与裁决

**c2 强确认（winner）**：窄标量 slice/移位/signed helper 的跨 TU 调用边界是
t0 当前最大一阶适配胶。5 个 helper 移入生成头文件 `constexpr` 后 Host 中位
**194.792s**，较 e00033 **-10.02%**（CV 0.45%），远超 3% 假设门，是本 run
最大单步收益。收益来源不是 AM schedule 工作量变化，而是 22.5 亿次动态调用
边界的消除与常量传播/指令选择的暴露；编译侧无代价（emu_build 264.7s，较
e00033 的 281.6s 反而略快，compile_s 603.3s，距 2400s 预算裕量充足）。
至此 t0 的「C++ 适配层调用边界」系列已三层确认：扫描调用（source-part/word
guard）、宽拼接写 splice（concat-insert-inline）、窄标量算值 helper。

**c1 弱正未确认**：-1.89% 略低于 2% 假设门、高于 1% 证伪线（三个 rep 均优于
e00033 中位，CV 0.64% 干净）。e00033 收掉单字退化层后，残余跨 word splice
的调用边界是二阶成本：unroll 消除了调用与逐迭代运行时边界检查，但多 word
站点单次调用本已摊薄边界开销，且展开增加代码体积（emu_build 267.0s 中性）。
判「弱正、未达确认门」，旋钮默认 off 留存，可与后续 base 叠加单独复测。
遗留细化点：width=64 且 shift≠0 的 867 个跨 word 站点未覆盖（Case B 可放宽
至 width<=64）。

winner = **e00040**（score `-194792`），已合入 `tes/r001/t0/main`。
t0 best 从 216.481s 更新为 **194.792s**：较 AM y0 273.103s 累计 **-28.67%**，
仍为 gsim 24.688s 的 **7.89x**，AM/gsim 绝对差距关闭 **31.52%**。
t0 完成 7/8，run 使用 40/48 eval。

轨迹独立说明：c2 的候选动机与动态权重证据全部来自本 step 对 t0 自身 emit
产物的站点×块execs 加权 recon（22.5 亿次 outlined 调用为 t0 最大残余池），
登记不引用其他轨迹结果。

对 Φ 下一步的建议：t0 余 1 步（s08），run 余 8 eval。候选方向优先级：
(1) e00040 + `--concat-insert-unroll` 正交叠加（c1 弱正未证伪，组合须独立
评估，不可与 c2 直接相加）；(2) 残余窄标量 helper 下一层
`divide_value`/`modulo_value`（动态 1.27 亿次，本步已量化）；(3) 已量化备查
池：`index_words` 3.66 亿、`assign_words_detect`+`masked_write_words_detect`
等 commit 写侧 detect 族 6.4 亿、`slice_words` 2.39 亿（宽值层，须先离线核
覆盖再定）。t0 编译预算裕量充足（603/2400s），叠加候选无编译门压力。
