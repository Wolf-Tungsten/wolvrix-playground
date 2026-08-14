# grhsim-am-coremark 任务 playbook（任务层）

`tes/playbook.md`（方法层）中标注「按任务 playbook」的环节在本文件落地。
评估器：`tes/grhsim-am-coremark/evaluator.py`，两模式：
`run`（候选/AM 基线全流水线）与 `gsim`（现存 emu 协议化计时）。

## 基线流程（run-init action 用）

AM 基线（y0，目标仓库基线 commit 的全流水线）：

```bash
git -C wolvrix worktree add build/tes/grhsim-am-coremark/src/base-<run> tes/<run>/base
git -C build/tes/grhsim-am-coremark/src/base-<run> submodule update --init \
  --reference "$PWD/wolvrix/external/slang" -- external/slang   # mt-kahypar / libfst 同理
python3 tes/grhsim-am-coremark/evaluator.py run \
  --worktree build/tes/grhsim-am-coremark/src/base-<run> \
  --eval-id e00001 --compile-budget-sec 5400
```

- 冷 ccache 首次全量构建慢，AM 基线允许一次性放宽编译预算到 90min；实测
  `compile_s` 记进 insights.md，之后所有候选一律按 40min 预算执行。
- 评估产物在 `build/tes/grhsim-am-coremark/evals/e00001/`（result.json + 各阶段日志）。

gsim 基线（target，现成二进制的协议化计时）：

```bash
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id e00002
```

- 依赖 `build/xs/gsim-flat/emu`（config `paths.gsim_emu`）。不存在则停止并报告用户
  （tes 不自行构建 gsim）。

## 候选评估命令（step action 用）

```bash
# 代码修改类候选（worktree 由 begin-step 建好）：
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <worktree> --eval-id <eNNNNN>

# 纯 emit 旋钮候选（不改代码，也要在候选分支留 --allow-empty 说明 commit）：
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <worktree> --eval-id <eNNNNN> \
  --emit-args "--block-chunk-instructions 3000 --max-atoms-per-block 15"
```

旋钮语义见 `wolvrix/docs/grhsim/grhsim-am-pipeline.md` 与
`pdocs/grh-notepad/emit-cost/` 的旋钮实验记录。

## 结果解读速查

- `result.json.status`: ok / build_fail / ctest_fail / emit_fail / difftest_fail /
  timeout / compile_timeout / noisy(ok 但 CV 超标) / interference（外部干扰，排除后重跑）
- `compile_s`：编译流程累计墙钟（预算 2400s）；`host_ms.median`：计时中位（score = -中位）。
- 逐阶段日志与 rep 日志都在 `build/tes/grhsim-am-coremark/evals/<eval_id>/`。
