# TES action playbook

每个 action 的逐步操作。命令默认在 playground 仓库根执行；`<task>` = 任务目录名
（如 `grhsim-am-coremark`），`tesctl.py` = `python3 tes/tools/tesctl.py`
（单任务时省略 `--task`，多任务歧义时加 `--task <task>`）。
任务专属评估器为 `tes/<task>/evaluator.py`，下同。

## run-init / baseline

对应 `next` = `run-init`（无活跃 run）或 `baseline`（结构已建、基线未测完）。
一个 run-init action 覆盖整个初始化 + 全部基线测量。

1. 初始化结构（用户在 goal 上下文给了 C/L/K 时用 `--C/--L/--K` 覆盖；restart 时加
   `--base-commit <上一 run 最佳 commit>`）：
   `python3 tes/tools/tesctl.py init-run`
   它会：冻结配置到 `tes/<task>/runs/<run>/manifest.json`、建 wolvrix 分支
   `tes/<run>/base` 与 `tes/<run>/t0..t(C-1)/main`、pin 三仓库 commit。
2. 输入指纹：`sha256sum build/logs/no0009/gsim_flat_export/SimTop.exec.json`（~3.2GB，
   约 10-30s），把值写入 manifest 与 `tes/<task>/state/run.json` 的
   `pins.exec_json_sha256`（这是唯一允许手改 run.json 的场景）。
3. AM 基线（y0）：
   - `git -C wolvrix worktree add build/tes/<task>/src/base-<run> tes/<run>/base`
     `git -C build/tes/<task>/src/base-<run> submodule update --init --reference .../wolvrix/external/<name>`
     （三个子模块逐个 --reference 主 checkout，避免网络 clone；或直接信赖 tesctl
     begin-step 同款的 ensure_worktree 逻辑——手工建则用同样命令。）
   - `python3 tes/<task>/evaluator.py run --worktree build/tes/<task>/src/base-<run> --eval-id e00001`
     （首次评估预热 ccache，wolvrix 全量构建较慢属正常；全程约 40-60min）
   - `python3 tes/tools/tesctl.py record-baseline --side am --result build/tes/<task>/evals/e00001/result.json --insight "<一句话>"`
4. gsim 基线（target）：
   - `python3 tes/<task>/evaluator.py gsim --eval-id e00002`
   - `python3 tes/tools/tesctl.py record-baseline --side gsim --result build/tes/<task>/evals/e00002/result.json --insight "<一句话>"`
   - 若 `build/xs/gsim-flat/emu` 不存在：停止并报告用户（tes 不自行构建 gsim）。
5. 在 `tes/<task>/state/insights.md` 追加：双基线数值、ratio、与 emit-cost 系列最新
   Host（NO0018: 324.0s）的对照、起点判断。
6. 按 goal.md 固定流程第 3-7 步收口（action 笔记写清 ratio 与差距分解的初步判断）。

## step / step-resume（finish-step 同节）

对应 `next` = `step` / `step-resume` / `finish-step`。核心开销：K × ~40min。

1. `python3 tes/tools/tesctl.py begin-step`（step-resume 跳过此步）。
   产物：proposal `tes/<task>/proposals/<run>-<t>-sNN.md`、候选分支
   `tes/<run>/<t>/sNN-c{1..K}`、worktree `build/tes/<task>/src/e*-*c{1..K}`（含子模块）。
2. 通读 proposal（Φ 选中的历史节点、否决清单、失败摘要）与
   `tes/<task>/state/insights.md`。
3. 设计 **K 个机制互异**的候选，每个先写下可证伪的一句话假设。
4. 对每个候选（严格串行、一次一个）：
   a. 在其 worktree 实施；emit 旋钮类候选不改代码，把旋钮记进假设即可。
   b. 提交到候选分支：`git -C <worktree> add -A && git -C <worktree> commit -m "tes(<run>/<t>/sNN): c<k> <假设>"`。
      （旋钮类候选无代码改动时用 allow-empty 说明性 commit，保证分支可定位。）
   c. 评估：`python3 tes/<task>/evaluator.py run --worktree <worktree> --eval-id <eNNNNN>`；
      旋钮候选加 `--emit-args "<覆盖参数>"`。
   d. 登记：`python3 tes/tools/tesctl.py record-eval --result build/tes/<task>/evals/<eNNNNN>/result.json --hypothesis "<假设>" --insight "<结果一句话>"`
   e. 评估失败（build/emit/ctest/difftest/timeout/interference）同样 record-eval；
      `interference` 表示有外部干扰，排除后用同一 eval-id 重跑评估再登记
      （重复登记同一 eval-id 会被拒绝：先把 result.json 里的新结果准备好再登记一次即可，
      若已登记过失败记录，则保留原记录、在 action 笔记里说明重测结果）。
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

1. 汇总整个 run：各轨迹分数曲线、best_overall、vs target 的 ratio。
2. 写 `tes/<task>/runs/<run>/summary.md`（含 restart 建议：y0 候选 commit、建议的新
   C/L/K）+ action 笔记；更新 insights.md。
3. `python3 tes/tools/tesctl.py close-run`。
4. 按 goal.md 收口，并在汇报中向用户明确：是否 restart（config 默认 auto=false，
   需用户确认后由下一个 goal 执行 `init-run --base-commit <best>`）。
