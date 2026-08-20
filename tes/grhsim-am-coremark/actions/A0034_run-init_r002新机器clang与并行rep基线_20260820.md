# A0034 run-init：r002 新机器 restart、clang 工具链与并行 rep 基线（2026-08-20）

类型：run-init（覆盖初始化 + 全部基线测量）。run：**r002**（C=2, L=8, K=2，N=32）。

## 做了什么

1. **环境适配确认（新机器 + 用户两条当场指示）**
   - 用户指示一：restart。y0 = r001 best_overall `9c0a89db94a3`（t0/main tip），
     用户已将 r001 成果并入其主线分支 `grh/tes-grhsim-am` 并自行清理 r001 tes
     分支；本 action 以该 commit 显式 `--base-commit` 初始化 r002。
   - 用户指示二：后续用 **clang** 编译。确认 clang 21.1.8
     （`/home/gaoruihao/download/LLVM-21.1.8-Linux-X64`，PATH 经 `~/.bashrc`）；
     evaluator 的 wolvrix cmake 固定 `clang/clang++`（既有行为），difftest
     Makefile 的 fallback 在 PATH 有 clang 时自动选 `clang++`——全链路 clang -O3，
     无需代码改动，仅需保证评估会话 PATH 含 LLVM。
   - sanity：pin 仓库（reference/gsim `70f2ab1`、testcase/xiangshan `8d96f2b`，
     均较 r001 pin 前移，由用户在新环境重建时更新）、gsim emu 与 post-stats
     JSON 已本机重建、FetchContent 本地 clone 齐、LOCK 空闲、磁盘 1.3T。
   - 输入切换生效：config `inputs` 声明的 post-stats JSON（wolvrix 自解析 SV
     归一化 GRH）取代 r001 的 gsim 导出 exec-GRH，sha256
     `cbd78c0b127dfb3bbbb005d06594242846a9d1cf35944de0720d7cf3031b3246` 已回填
     manifest 与 run.json（run-init 唯一允许的手改）。
2. **`tesctl.py init-run --base-commit 9c0a89db… --C 2 --L 8 --K 2`**：
   分支 `tes/r002/base` + 轨迹主线 `tes/r002/t0/main`、`tes/r002/t1/main`；
   worktree `build/tes/grhsim-am-coremark/src/base-r002`（submodule 引用复用）。
   C/L/K 取 r001 summary 的 restart 建议（2/8/2，N=32；用户当场未另给值）。
3. **协议变更：rep 绑核并行（用户当场指示）**。384 核机器上逐 rep 串行浪费
   墙钟；改为批内并行、每 rep 绑一个独立物理核。改动面：
   - `evaluator.py`：`run_reps` 重写为批次并行（新增 `_run_rep_batch`，每 rep
     `taskset -c eval.rep_cores[j]`、独立 rep 超时杀进程组；干扰守卫移到批次
     起跑前；CV 超标时加测新批次，上限 `max_reps` 不变）；docstring 同步。
   - `config.json`：eval 新增 `"rep_cores": [12, 13, 14]`（同属 socket 0、
     core_id 36/37/38、非 SMT 兄弟；缺省退回 `core` 单核串行语义）。
   - `protocol.md`、`tes/RULES.md`：协议文字同步（批内并行 + 评估间严格串行
     不变）。
   - r002 所有测量（含两条基线）统一用新协议；r001 绝对读数因换机本就不可比。
4. **基线测量**：AM 侧 e00001 首跑在串行 rep1（539.2s）期间遇协议切换，主动
   中止后按新协议同 eval-id 重跑覆盖（首跑留下的单跑读数成为并行抬升的
   对照点，见下）；gsim 侧 e00002 一次通过。

## 量化结果

| 基线 | eval | reps（ms，core） | 中位 | CV | compile_s | 门 |
|---|---|---|---|---|---|---|
| AM（y0 `9c0a89db`） | e00001 | 619067(12) / 619019(13) / 619018(14) | **619.019s** | ~0.0% | 622.3s | ctest 17/17、3 rep difftest 全过（73580/49996） |
| gsim（target，master emu） | e00002 | 46792(12) / 46792(13) / 46791(14) | **46.792s** | ~0.0% | - | 3 rep difftest 全过（73584/49998） |

**起跑差距 619.019 / 46.792 = 13.23x**（r001 旧机为 273.1/24.7 = 11.06x）。

并行协议刻度（同代码、同机）：AM 单跑 539.2s vs 批内 619.0s（+14.8%）；gsim
单跑 39.6s（e99901，协议切换前用户手动串行 smoke）vs 批内 46.8s（+18.1%）。
两侧抬升幅度相近（内存带宽争用机制），同协议下比值裁决有效；批内三核读数
离散 <50ms，CV 比 r001 串行时代（~0.4-1.5%）紧一个量级。

## 裁决与机制分析

- r002 起点确认：y0（含 r001 全部代码级 winner：branchy-mux、resize 胶消除、
  source-part/word activity guard、wide first-touch、concat-insert-inline、
  inline-scalar-helpers）在新机器 + clang + post-stats 输入下功能全绿，
  基线有效。
- 新机器把起跑差距从 11.06x 拉大到 13.23x：AM 侧对单核性能/内存子系统的
  敏感度高于 gsim（AM +126% vs gsim +89%，均对旧机串行读数）。机器更换
  不改变优化方向（r001 机制族均为结构性工作量削减），但绝对目标线整体上移。
- 并行 rep 的均匀抬升是协议常量（~15-18%），不是候选属性；由于 gsim target
  同协议测量，r002 内的 AM/gsim 比值与候选间相对比较均不受影响。
- 编译预算：compile_s 622.3s ≪ 2400s（本次 wolvrix 构建 cache 命中 0.8s；
  冷 wbuild 候选会更高，r001 口径下裕量充足）。emu_build 增量 334.4s。
- 勘误登记：r002 manifest 冻结的 eval 段早于协议变更，无 `rep_cores` 字段，
  以 config.json 现值为准（已记入 insights.md）。

## 对下一步的建议（Φ / 后续 step）

- 下一 action 应为 r002 第一个 step（t0/s01）。按 r001 summary 的组合材料：
  t1 常量族四旋钮（`--inline-scalar-constants`、
  `--inline-scalar-constant-storage-elision`、`--dead-wide-storage-elision`、
  `--dead-narrow-storage-elision`）与 y0 机制正交，是两轨迹共同的近期候选；
  预期可加 ~-5~-8%（r001 同日干净收益之和，新基线上需重证）。
- K=2 中建议一席常态化为同日校准/安慰剂（r001 方法论遗产：跨日漂移 >
  协议 CV，本机并行协议 CV 极紧，需重新标定跨日漂移刻度）。
- 注意新机器的噪声/漂移特征未标定：并行批内 CV≈0 不代表跨日稳定，首批
  跨日对照出现前，<2% 的跨日名义差仍按 r001 纪律存疑。
- brief.md 的 r002 纪律（激进改动许可、突破性导向、显式 pass 化）已开始
  生效，候选设计不限于旋钮微调。
