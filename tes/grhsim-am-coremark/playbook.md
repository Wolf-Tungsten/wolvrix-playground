# grhsim-am-coremark 任务 playbook（任务层）

`tes/playbook.md`（方法层）中标注「按任务 playbook」的环节在本文件落地。
评估器：`tes/grhsim-am-coremark/evaluator.py`，两模式：
`run`（候选/AM 基线全流水线）与 `gsim`（现存 emu 协议化计时）。

## 构建与依赖复用（固定前置规则）

- 正式评估必须直接调用本文件给出的 `evaluator.py` 命令；不要手工执行
  `cmake`/FetchContent，也不要为依赖申请联网。
- 候选的 `wbuild` 和 `emu_build` 仍按 `eval-id` 放在
  `build/tes/grhsim-am-coremark/evals/<eval-id>/`，保持候选对象文件和
  `CMakeCache.txt` 隔离。不能把不同 worktree 直接混用 `wolvrix/build`：CMake
  cache 绑定绝对源码路径，强行复用会拒绝配置或引入 stale object。
- 依赖源与编译缓存必须复用：`evaluator.py` 的 `cmake_env_extra()` 会把
  FetchContent 的 fmt、mimalloc、CLI11、oneTBB 及 mt-kahypar 嵌套依赖 URL
  重定向到 `wolvrix/build` 中已有的本地 clone；`build_env_extra()` 将
  `CCACHE_DIR` 固定为共享的 `build/tes/ccache`。因此“新 wbuild”不等于“重新
  下载依赖”或“冷编译”。
- CMake 输出中的 `Fetching dependencies...` 是项目配置阶段的固定提示；只要
  `wolvrix/build` 的本地 clone 完整，配置应在受限网络下完成。若本地 clone
  缺失/损坏，先在正式评估之外修复依赖缓存并记录原因，再运行候选；不要在计时
  流程中临时联网或手工填充新的依赖目录。
- 评估产物保留在 `build/tes/.../evals/` 供审计，默认不删除；清理旧目录需用户
  明确确认。

## 基线流程（run-init action 用）

AM 基线（y0，目标仓库基线 commit 的全流水线）：

```bash
# 注意：worktree 路径必须给绝对路径（git -C wolvrix 下相对路径会落进 wolvrix/ 内部）
git -C wolvrix worktree add "$PWD/build/tes/grhsim-am-coremark/src/base-<run>" tes/<run>/base
cd build/tes/grhsim-am-coremark/src/base-<run> && for m in external/slang external/mt-kahypar external/libfst; do
  git submodule update --init --reference "$OLDPWD/wolvrix/$m" -- "$m"
done && cd "$OLDPWD"
python3 tes/grhsim-am-coremark/evaluator.py run \
  --worktree build/tes/grhsim-am-coremark/src/base-<run> \
  --eval-id <run.json 中为 am 预留的 eval-id> --compile-budget-sec 5400
```

- 冷 ccache 首次全量构建慢，AM 基线允许一次性放宽编译预算到 90min；实测
  `compile_s` 记进 insights.md，之后所有候选一律按 40min 预算执行。
- 评估产物在 `build/tes/grhsim-am-coremark/evals/<eval-id>/`（result.json + 各阶段日志）。

gsim 基线（target，现成二进制的协议化计时）：

```bash
python3 tes/grhsim-am-coremark/evaluator.py gsim \
  --eval-id <run.json 中为 gsim 预留的 eval-id>
```

- 依赖 `build/xs/gsim/gsim-compile/emu`（config `paths.gsim_emu`，gsim master 基线）。不存在则停止并报告用户
  （tes 不自行构建 gsim）。

## 候选实施纪律

变更面约束见 `brief.md`「优化哲学（变更面纪律）」：GRH IR 冻结；优化应体现为
显式 grhsim AM pass；emit 规则变更须随候选同步文档。proposal 与 action 笔记中
应说明候选落在哪个面（pass / 旋钮 / emit 规则），便于归因。

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
  timeout / compile_timeout / parse_fail / interference（外部干扰，排除后重跑）；
  `noisy=true` 表示固定 3 rep 的 CV 超标。
- `compile_s`：编译流程累计墙钟（预算 2400s）；`host_ms.median`：固定 3 rep 中位
  （`score = -median`）。
- 逐阶段日志与 rep 日志都在 `build/tes/grhsim-am-coremark/evals/<eval_id>/`。
