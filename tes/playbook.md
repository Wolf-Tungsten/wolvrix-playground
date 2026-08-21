# TES action playbook（方法层，任务无关）

每个 action 的通用步骤。命令默认在 playground 仓库根执行；`tesctl.py` =
`python3 tes/tools/tesctl.py`（单任务时省略 `--task`，多任务歧义时加 `--task <task>`）。

**任务契约**：每个任务目录 `tes/<task>/` 自带 `evaluator.py`（评估器）与
`playbook.md`（任务专属操作细节：基线怎么测、候选怎么评估、有哪些旋钮）。
本文件只描述与任务无关的 action 生命周期；具体命令以任务 playbook 为准。

## run-init / baseline

对应 `next` = `run-init`（无活跃 run）或 `baseline`（结构已建、基线未测完）。
一个 run-init action 覆盖整个初始化 + 全部基线测量。

1. 初始化结构（用户在 goal 上下文给了 C/L/K 时用 `--C/--L/--K` 覆盖；restart 时用
   `--base-eval <上一 run>/<最佳 eval>` 同时冻结最佳代码快照与参数表型。可选的
   `--base-commit <最佳 commit>` 只作匹配断言，若与该 eval 的台账 commit 不同会被
   拒绝）：
   `python3 tes/tools/tesctl.py init-run`
   它会：冻结配置到 `tes/<task>/runs/<run>/manifest.json`、在**目标仓库**
   （config `repos.target`）建分支 `tes/<run>/base` 与 `tes/<run>/t0..t(C-1)/main`、
   pin `repos.pin` 声明的只读仓库 commit、登记 `inputs` 清单。
2. 输入指纹：对 manifest `pins.inputs` 的每一项跑 `sha256sum`，把值回填到 manifest
   与 `tes/<task>/state/run.json` 的对应 `pins.inputs[].sha256`
   （这是唯一允许手改 run.json 的场景）。
3. 按**任务 playbook** 的基线流程，使用 init-run 输出及 run.json
   `baseline_eval_ids` 中预留的编号，对 config `baseline_sides` 的每一侧各测一次并登记：
   `python3 tes/tools/tesctl.py record-baseline --side <side> --result <result.json 路径> --insight "<一句话>"`
   eval-id 在任务范围内跨 run 单调续接，不复用旧编号。
4. 在 `tes/<task>/state/insights.md` 追加：各侧基线数值、与既有记录的对照、起点判断。
5. 按 goal.md 固定流程第 3-7 步收口。

## step / step-resume（finish-step 同节）

对应 `next` = `step` / `step-resume` / `finish-step`。

1. `python3 tes/tools/tesctl.py begin-step`（step-resume 跳过此步）。
   产物：proposal `tes/<task>/proposals/<run>-<t>-sNN.md`、候选分支
   `tes/<run>/<t>/sNN-c{1..K}`、目标仓库 worktree `build/tes/<task>/src/e*-*c{1..K}`。
2. 通读 proposal（Φ 选中的历史节点、否决清单、失败摘要）与
   `tes/<task>/state/insights.md`。
3. 设计 **K 个机制互异且都具有实质性能假设**的候选。每个先写下来源 Φ 节点、反馈/
   病灶、局部改动和可证伪预期；不得用原样重测或安慰剂占用候选席位。
4. 对每个候选（严格串行、一次一个）：
   a. 在其 worktree 实施（旋钮类候选不改代码，把旋钮记进假设）。
   b. 提交到候选分支：`git -C <worktree> add -A && git -C <worktree> commit -m "tes(<run>/<t>/sNN): c<k> <假设>"`。
      （无代码改动时用 `--allow-empty` 说明性 commit，保证分支可定位。）
   c. 按**任务 playbook** 的候选评估命令评估（用 begin-step 分配的 eval-id）。
   d. 登记：`python3 tes/tools/tesctl.py record-eval --result <result.json> --hypothesis "<假设>" --insight "<结果一句话>"`
   e. 失败状态（build/emit/ctest/difftest/timeout/compile_timeout 等）同样 record-eval；
      `interference` 表示有外部干扰，排除后重跑该候选（同一 eval-id 覆盖 result.json
      再登记；已登记过的失败记录保留，在 action 笔记里说明重测）。
5. `python3 tes/tools/tesctl.py finish-step`：winner 快移入轨迹主线；全失败则轨迹
   原地消耗一步（预算语义）。
6. action 笔记必须含：K 个候选的假设/结果对比表、winner 裁决、机制分析
   （为什么赢/为什么输）、对 Φ 下一步的建议方向。然后按 goal.md 收口。

## round-summary

对应 `next` = `round-summary`（一轮齐平后触发）。无评估开销。

1. 汇总本轮 C 条轨迹各 step 的 winner 分数与假设（读 `tes/<task>/state/ledger.jsonl`）。
2. 写 action 笔记：跨轨迹对比、哪些机制方向在收敛/发散、是否需要用户调整方向。
3. 可复用结论追加进 `tes/<task>/state/insights.md`（失败模式、已证伪方向、新晋病灶）。
4. `python3 tes/tools/tesctl.py round-summary-done --round <m>`，按 goal.md 收口。

## run-summary

对应 `next` = `run-summary`。无评估开销。

1. 汇总整个 run：各轨迹分数曲线、best_overall、vs 参照基线的差距。
2. 写 `tes/<task>/runs/<run>/summary.md`（含 restart 建议：y0 候选 commit、建议的新
   C/L/K）+ action 笔记；更新 insights.md。
3. `python3 tes/tools/tesctl.py close-run`。
4. 按 goal.md 收口，并在汇报中向用户明确：是否 restart（config 默认 auto=false，
   需用户确认后由下一个 goal 执行 `init-run --base-commit <best>`）。
