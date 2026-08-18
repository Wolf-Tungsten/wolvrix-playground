# A0015 - step-resume r001/t1/s04：resize 胶与标量常量内联

日期：2026-08-18。action 类型：step-resume（trajectory t1, step 4, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t1-s04.md`。本 step 延续 t1
主线 e00018（`--resize-elision --inline-scalar-helpers`），两个候选均未引入
其他轨迹的机制。正式评估严格串行，由任务 evaluator 执行。

## 候选设计与可证伪假设

### c1 `--resize-elision` 扩展到 signed/unsigned 同宽胶

- 分支 `tes/r001/t1/s04-c1`，commit `216e16f`，eval e00023。
- emit-args：`--block-chunk-instructions 3000 --resize-elision
  --inline-scalar-helpers`。
- 机制：在已有无符号同宽 resize 消除之外，统一消除同宽 signed/unsigned
  `resize_value` 胶；宽值和真正改变宽度的转换仍按原规则发射。
- **假设**：signed 胶若位于热路径，消除后应在语义不变的前提下较 t1 主线
  下降至少 2%；若回退，则该胶不是独立一阶成本，或生成代码布局/优化交互
  抵消了静态调用减少。

### c2 `--inline-scalar-constants`

- 分支 `tes/r001/t1/s04-c2`，commit `6307fca`，eval e00024。
- emit-args：`--block-chunk-instructions 3000 --resize-elision
  --inline-scalar-helpers --inline-scalar-constants`。
- 机制：不可写、`<=64` bit 的 `InitKind::Constant` 读取直接发射为掩码
  字面量，绕过 backing-storage 的标量读取；地址获取、`init()` 写入和输入
  端口写入继续使用 backing storage，避免改变可观察写语义。
- **假设**：常量读取胶仍在热路径，内联后应较 t1 主线下降至少 3%；若低于
  1.5%，则常量访问覆盖不足或编译器已吸收主要成本。

### 机制互异性

c1 改变 resize 适配规则，减少同宽 signed/unsigned 转换；c2 改变只读常量
状态的读取发射形态，减少 backing-storage load。两者分别作用于转换胶和状态
读取，且可独立开关，满足 K=2 的机制互异要求。

## 正式评估结果

共同对照为 t1 主线 e00018 = 244.278s（`--resize-elision
--inline-scalar-helpers`）。

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00018 |
|---|---|---|---:|---|---|---:|
| e00023 | c1 signed/unsigned resize elision | ok；ctest 17/17；3 rep difftest 全过 | 1586.4s | 257029 / 256419 / 252756 | **256.419s / 0.90%** | **+4.97% 回退** |
| e00024 | c2 inline scalar constants | ok；ctest 17/17；3 rep difftest 全过 | 1036.3s | 241348 / 242424 / 235763 | **241.348s / 1.49%** | **-1.20%** |

六次计时 rep 均为 `instrCnt=73580`、`cycleCnt=49996`、进程 rc=0，在线
difftest 无 mismatch；两候选 CV 均低于 5% 噪声门。e00023/e00024 的
wolvrix 构建、emit 和 emu 构建均在 2400s 编译预算内。

## 机制分析

### c1：同宽 signed 胶不是独立运行时杠杆

扩展静态消除规则后，Host 中位从 244.278s 回退到 256.419s（+4.97%），
差异远超 c1 的 CV。功能门和回归门均通过，因此不是语义失败；更符合生成
代码布局、指令选择或编译器优化交互带来的负收益。结论是关闭 signed/unsigned
同宽 resize 的独立扩张，不把静态站点数量当作运行时收益代理。

### c2：常量读取内联是稳定弱正，但未达一阶门

e00024 中位较共同主线下降 1.20%，CV 1.49%，低于预设 3% 目标但不是持平或
恶化；相对 c1 快 5.88%。地址和写路径仍走 backing storage，3 rep difftest
通过，说明读取专用内联没有破坏初始化或输入写入语义。当前证据支持将其作为
t1 的弱正 winner 保留，但不应把它升级为新的 >=3% 一阶方向；后续若继续，
应先量化常量读取动态覆盖与生成代码指令数，再决定是否扩大内联边界。

## evaluator 离线依赖复用

本 action 按任务 playbook 的“构建与依赖复用”固定规则执行。e00023/e00024
各自使用独立的 `build/tes/grhsim-am-coremark/evals/<eval-id>/wbuild`、
`emit` 和 `emu_build`，没有复用绑定其他 worktree 绝对路径的 CMake cache 或
对象文件；CMake configure 分别约 4.4s/4.6s 完成。

`evaluator.py` 将 fmt、mimalloc、CLI11、oneTBB、mt-kahypar 的嵌套依赖 URL
重定向到 `wolvrix/build` 已存在的本地 clone，并将 C++ 编译缓存固定到共享
`build/tes/ccache`。因此两个新 eval 目录只隔离候选产物，未联网重新下载依赖；
该长期约定已记录在 [`playbook.md`](../playbook.md) 的“构建与依赖复用”章节，
任务 README 也有入口提示。

## 裁决与 run 影响

winner = **e00024**（score `-241348`），已由 `finish-step` fast-forward 到
`tes/r001/t1/main`（commit `6307fca`）。t1 best 从 e00018 的 244.278s 更新为
241.348s；相对 AM y0 273.103s 累计改善 **11.63%**，相对 gsim 24.688s
仍为 **9.78x**。run best_overall 仍是 t0/e00022 的 230.568s（较 AM y0
**-15.57%**），所以本 step 没有刷新全局 best。

## 对 Phi 下一步的建议

1. 当前 step 的 winner 只提供约 1.2% 弱正，不应单独满足一阶继续门；下一 action
   按状态机轮转到 t2/s04，保持轨迹独立。
2. 若未来重访 t1，先用不计时统计确认常量读取的动态命中率和生成代码负担；不要
   继续扩大 signed/unsigned resize 消除规则。
3. 只有在 restart 或明确组合实验时，才把 e00024 与其他轨迹的 activity guard
   或定向布局组合；本 run 内不跨轨迹回写 proposal。
