# 主目标推进契约

产出中的机器字段必须独占一行，格式为 `VRT_字段名: 非空值`，不加列表符号或代码围栏。字段之外的说明保持简短。

## 共同行为

- PI 固定原始目标和编号验收项；RA 不得缩减或改写。每步说明本步状态、证据和剩余缺口。
- 第一次工程调用必须尝试完整目标流程，记录真实命令和最早阻塞。辅助工作必须解除具体阻塞并说明何时接回目标。
- 未运行、未完成和失败都不是证伪；已有结论时，用剩余调用做不同的反例搜索、独立复核或完整测试。

## RA_PLAN_STEP

必填：`VRT_PRIMARY_GOAL`、`VRT_SUCCESS_CRITERIA`、`VRT_TARGET_PATH`、`VRT_TASK_KIND`（target/blocker/support/verification）、`VRT_NEXT_TARGET`。第 1 步必须为 target；support 还要写 `VRT_BLOCKER`、`VRT_DECISION_RULE` 和结果对应的下一动作。RA 负责选择方法和任务细节。

## ENG_EXEC

工程师负责在本次调用内尽力完成 RA 目标：编码、运行、定位和修复。遇到普通错误先调查并尝试最小修复、替代验证或缩小复现；不能直接甩回任务。只有实际尝试后仍无法继续，才报告具体阻塞和已尝试动作。

必填：

- `VRT_PRIMARY_PROGRESS`: advanced / narrowed / verified / none
- `VRT_EVIDENCE`: 改动、命令、输入/版本、退出码、日志
- `VRT_REMAINING_GAP`: 完整目标缺口
- `VRT_TARGET_RUN`: attempted / not_run

attempted 还要有 `VRT_TARGET_COMMAND`、`VRT_TARGET_EXIT`、`VRT_TARGET_LOG`（仓库内存在且非空）；not_run 还要有 `VRT_BLOCKER`。日志放 `ptmp/`，不得用静态计数替代运行证据。

## RA_REVIEW

RA 独立核验源码、日志、退出码和验收项，必填 `VRT_PRIMARY_PROGRESS`、`VRT_EVIDENCE_CHECK`、`VRT_NEXT_STEP`、`VRT_TARGET_RUN`。连续两步 none 时，补充 `VRT_FAILURE_SITE`、`VRT_REPAIR_HYPOTHESIS`、`VRT_VALIDATION_COMMAND`，并改变方法。配额未满不得结束方向。
