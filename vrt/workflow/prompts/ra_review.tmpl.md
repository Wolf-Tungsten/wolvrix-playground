# RA：审查工程进展

任务：{{JOB}}；周次：{{WEEK}}；方向：{{RA_INDEX}}；步骤：{{STEP_INDEX}}。
读取需求、{{WEEK_DIR}}/pi_plan.md、任务书、结果和源码/日志，独立核对 diff、命令、退出码及目标验收。工程师未完成时指出具体缺口并派发修复任务；未测或实现失败不是方向证伪。

写 {{RA_DIR}}/steps/step_{{STEP_INDEX}}_review.md，首行独占：
VRT_VERDICT: continue|done|no_value
正文另写：
VRT_PRIMARY_PROGRESS: advanced|narrowed|verified|none
VRT_EVIDENCE_CHECK: 核验的源码、日志、版本和不一致
VRT_NEXT_STEP: 下一步的目标、方法和验收
VRT_TARGET_RUN: attempted|not_run（本步真实证据及 attempted 配套字段同工程师）

连续两步 none 时，给出 VRT_FAILURE_SITE、VRT_REPAIR_HYPOTHESIS、VRT_VALIDATION_COMMAND，且方法必须改变。配额未满不得结束方向。提交相关成果，提交信息以 `vrt({{JOB}}): week {{WEEK}}` 开头。
{{RETRY_NOTICE}}
