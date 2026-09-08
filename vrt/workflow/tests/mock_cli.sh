#!/usr/bin/env bash
# VRT 自测试用的 mock LLM CLI。
# 不读提示词内容，完全由环境变量驱动（由 start-week-job.py 注入的 VRT_* 变量），
# 按各动作的契约写出文件并提交，用于在没有真实 LLM 的情况下验证调度逻辑。
#
# 额外的测试控制变量（由测试驱动设置）：
#   MOCK_DIR               mock 的状态目录（用于 fail-once 标记，必须位于仓库外）
#   MOCK_MAX_STEP          RA_REVIEW 在 step < MOCK_MAX_STEP 时给 continue，否则 done（默认 2）
#   MOCK_VERDICT           固定审查标签，覆盖 MOCK_MAX_STEP（测试提前结论不停止）
#   MOCK_FAIL_ONCE_ACTION  指定动作首次执行时以退出码 1 失败（不产生提交），用于测试重试
#   MOCK_DOUBLE_COMMIT     =1 时 ENG_EXEC 在 ra=1 step=1 产生两次提交，用于测试兜底合并
#   MOCK_BAD_CONTRACT      首次 ENG_EXEC 写 not_run，测试契约重试
set -euo pipefail

MOCK_DIR="${MOCK_DIR:?需要 MOCK_DIR}"
mkdir -p "$MOCK_DIR"

week_dir="vrt/${VRT_JOB}/week_${VRT_WEEK}"
ra_dir="${week_dir}/ra_${VRT_RA_INDEX}"
mkdir -p "$week_dir"

# 模拟合规 AI 的子模块行为：每个 RA 动作先把子模块对齐到与本动作同名的分支
#（不存在则以 base 分支记录的 gitlink 为基点创建）。
align_submodules() {
    for sub in $(git submodule status 2>/dev/null | awk '{print $2}'); do
        [ -d "$sub" ] || continue
        if git -C "$sub" rev-parse --verify --quiet "${VRT_BRANCH}" >/dev/null; then
            git -C "$sub" checkout -q "${VRT_BRANCH}"
        else
            base_link=$(git ls-tree "${VRT_BASE_BRANCH}" -- "$sub" | awk '{print $3}')
            git -C "$sub" checkout -q -b "${VRT_BRANCH}" "$base_link"
        fi
    done
}

commit() {
    git add -A
    git commit -q -m "vrt(${VRT_JOB}): week ${VRT_WEEK} work ${VRT_ACTION} ra ${VRT_RA_INDEX} step ${VRT_STEP_INDEX}"
}

echo "[mock] action=${VRT_ACTION} job=${VRT_JOB} week=${VRT_WEEK} ra=${VRT_RA_INDEX} step=${VRT_STEP_INDEX}"

# 测试可用 MOCK_ACTION_DELAY 放慢每个动作，让 TUI 重绘线程有机会覆盖到各动作状态
sleep "${MOCK_ACTION_DELAY:-0}"

case "${VRT_ACTION}" in
PI_PLAN)
    cat > "vrt/${VRT_JOB}/requirements.md" <<EOF
# ${VRT_JOB} 研究需求

（mock 记录的需求内容）
EOF
    {
        echo "# 第 ${VRT_WEEK} 周研究规划"
        echo
        for i in $(seq 1 "${VRT_R}"); do
            echo "## 方向 ${i}"
            echo "- 目标：mock 方向 ${i}"
            echo "- 理由：mock"
            echo "- 预期产出：mock"
            echo
        done
    } > "${week_dir}/pi_plan.md"
    commit
    ;;
RA_PLAN_STEP)
    align_submodules
    mkdir -p "${ra_dir}/steps"
    cat > "${ra_dir}/steps/step_${VRT_STEP_INDEX}_task.md" <<EOF
# 第 ${VRT_STEP_INDEX} 步任务书（RA ${VRT_RA_INDEX}）
目标：mock 任务 ${VRT_STEP_INDEX}
VRT_PRIMARY_GOAL: mock 原始目标
VRT_SUCCESS_CRITERIA: mock 证明或证伪标准
VRT_TARGET_PATH: mock 目标测试路径
VRT_TASK_KIND: target
VRT_NEXT_TARGET: mock 下一步目标命令
EOF
    commit
    ;;
ENG_EXEC)
    align_submodules
    fail_flag="${MOCK_DIR}/failed_${VRT_ACTION}_${VRT_RA_INDEX}_${VRT_STEP_INDEX}"
    if [ "${MOCK_FAIL_ONCE_ACTION:-}" = "ENG_EXEC" ] && [ ! -f "$fail_flag" ]; then
        touch "$fail_flag"
        echo "[mock] 模拟 ENG_EXEC 首次失败"
        exit 1
    fi
    for sub in $(git submodule status 2>/dev/null | awk '{print $2}'); do
        [ -d "$sub" ] || continue
        echo "step ${VRT_STEP_INDEX} ra ${VRT_RA_INDEX}" >> "$sub/sub_notes.txt"
        git -C "$sub" add -A
        git -C "$sub" commit -q -m "vrt(${VRT_JOB}): week ${VRT_WEEK} sub work ra ${VRT_RA_INDEX} step ${VRT_STEP_INDEX}"
    done
    mkdir -p "${ra_dir}/steps"
    cat > "${ra_dir}/steps/step_${VRT_STEP_INDEX}_result.md" <<EOF
# 第 ${VRT_STEP_INDEX} 步工作成果（RA ${VRT_RA_INDEX}）
VRT_PRIMARY_PROGRESS: mock 主目标进展
VRT_EVIDENCE: mock 目标证据
VRT_REMAINING_GAP: mock 尚缺目标测试
VRT_TARGET_RUN: attempted
VRT_TARGET_COMMAND: make mock-target
VRT_TARGET_EXIT: 0
VRT_TARGET_LOG: ptmp/mock-target-${VRT_RA_INDEX}-${VRT_STEP_INDEX}.log
做了什么：mock；关键数据：mock；结论：mock；遗留问题：无
EOF
    mkdir -p ptmp
    echo "mock target run" > "ptmp/mock-target-${VRT_RA_INDEX}-${VRT_STEP_INDEX}.log"
    sed -i 's/^VRT_PRIMARY_PROGRESS:.*/VRT_PRIMARY_PROGRESS: advanced/' "${ra_dir}/steps/step_${VRT_STEP_INDEX}_result.md"
    if [ "${MOCK_BAD_CONTRACT:-0}" = "1" ] && [ ! -f "${MOCK_DIR}/bad_contract" ]; then
        touch "${MOCK_DIR}/bad_contract"
        sed -i 's/^VRT_TARGET_RUN:.*/VRT_TARGET_RUN: not_run/' "${ra_dir}/steps/step_${VRT_STEP_INDEX}_result.md"
    elif [ "${MOCK_BAD_CONTRACT:-0}" = "1" ]; then
        case "$*" in
            *"首轮缺少完整目标流程"*) echo "[mock] 收到具体契约失败原因" ;;
            *) echo "[mock] 未收到契约失败原因"; exit 1 ;;
        esac
    fi
    commit
    if [ "${MOCK_DOUBLE_COMMIT:-0}" = "1" ] && [ "${VRT_RA_INDEX}" = "1" ] && [ "${VRT_STEP_INDEX}" = "1" ]; then
        echo "补充一行（第二次提交）" >> "${ra_dir}/steps/step_${VRT_STEP_INDEX}_result.md"
        commit
        echo "[mock] 模拟 ENG_EXEC 产生两次提交"
    fi
    ;;
RA_REVIEW)
    align_submodules
    mkdir -p "${ra_dir}/steps"
    max_step="${MOCK_MAX_STEP:-2}"
    if [ "${VRT_STEP_INDEX}" -lt "$max_step" ]; then
        verdict="continue"
    else
        verdict="done"
    fi
    verdict="${MOCK_VERDICT:-$verdict}"
    cat > "${ra_dir}/steps/step_${VRT_STEP_INDEX}_review.md" <<EOF
VRT_VERDICT: ${verdict}

审查依据：mock。对下一步的建议：mock。
VRT_PRIMARY_PROGRESS: advanced
VRT_EVIDENCE_CHECK: mock
VRT_NEXT_STEP: mock 补齐目标证据
VRT_TARGET_RUN: attempted
VRT_TARGET_COMMAND: make mock-target
VRT_TARGET_EXIT: 0
VRT_TARGET_LOG: ptmp/mock-target-${VRT_RA_INDEX}-${VRT_STEP_INDEX}.log
EOF
    commit
    ;;
RA_SUMMARY)
    align_submodules
    cat > "${ra_dir}/report.md" <<EOF
# RA ${VRT_RA_INDEX} 周报
目标/过程/结论/关键数据/经验教训：mock。值得继续：mock。
EOF
    commit
    ;;
PI_FINAL)
    winner="vrt/${VRT_JOB}/week_${VRT_WEEK}/r_1"
    git merge --no-ff "$winner" -m "vrt(${VRT_JOB}): week ${VRT_WEEK} merge ${winner}"
    git submodule update --checkout --force  # 对齐合并后的 gitlink
    cat > "${week_dir}/pi_final_report.md" <<EOF
# 第 ${VRT_WEEK} 周最终报告
优胜方向：方向 1（mock）。落选方向摘要：mock。经验教训：mock。
EOF
    git add -A
    git commit -q -m "vrt(${VRT_JOB}): week ${VRT_WEEK} work PI_FINAL report"
    ;;
*)
    echo "[mock] 未知动作: ${VRT_ACTION}" >&2
    exit 1
    ;;
esac

echo "[mock] 完成 ${VRT_ACTION}"
