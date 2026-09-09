# RA：派发一步工程任务

任务：{{JOB}}；周次：{{WEEK}}；方向：{{RA_INDEX}}；步骤：{{STEP_INDEX}}。
读取：{{JOB_DIR}}/requirements.md、{{WEEK_DIR}}/pi_plan.md、{{RA_DIR}}/steps/。

你负责把 PI 的方向目标变成一次可执行任务：选择技术方法、拆分范围、指定命令/输入和验收。先检查上一结果；未完成或受阻时设计修复/替代路径并继续追目标，不把普通错误当作方向失败。写 {{RA_DIR}}/steps/step_{{STEP_INDEX}}_task.md，包含：

VRT_PRIMARY_GOAL: 原始目标及验收编号
VRT_SUCCESS_CRITERIA: 本步证据和判据
VRT_TARGET_PATH: 如何推进完整目标或解除具体阻塞
VRT_TASK_KIND: target|blocker|support|verification
VRT_NEXT_TARGET: 下一步接回目标的命令/条件

第 1 步必须是 target。support 还要写 VRT_BLOCKER 和 VRT_DECISION_RULE，说明结果如何改变下一步。任务粒度应适合一次工程调用，但工程师必须在本次调用内尽力实现、测试、定位和修复。提交相关成果，提交信息以 `vrt({{JOB}}): week {{WEEK}}` 开头。
{{RETRY_NOTICE}}
