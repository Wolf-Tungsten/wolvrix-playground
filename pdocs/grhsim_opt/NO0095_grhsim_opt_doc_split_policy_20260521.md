# NO0095: GrhSIM Opt 文档拆分规范

Date: 2026-05-21

## 背景

`NO0093_essent_mffc_activity_schedule_plan_20260518.md` 已经承载了过多 ESSENT/MFFC 设计、实验和复测记录，继续追加会降低检索效率，也会让单个实验的结论不够清晰。

## 规则

- `NO0093` 冻结为 ESSENT/MFFC 主线历史索引，不再追加新实验正文。
- 后续每个独立实验、诊断、A/B、runtime 复测、root-cause snapshot 都在 `pdocs/grhsim_opt` 下新建一个 `NOxxxx_*.md`。
- 新文档编号按目录中当前最大 `NOxxxx` 递增；不要在规则文档里写死下一编号。
- 新文档应尽量短，只记录本步骤的动机、配置、命令口径、关键数据、结论和下一步。
- 若复用已有产物，必须写清楚是 no-fresh 还是 fresh emit，避免把 emit 变量和 runtime 变量混在一起。
- XiangShan runtime 数据必须标明是否带 difftest；当前性能定位默认要求带 difftest。

## 当前接续

- 已按拆分规则将 `NO0093` 后续流水账拆到独立 `NOxxxx_*.md` 文档，并在 `README.md` 维护索引。
- 后续新增记录只看 `README.md` 末尾的“当前下一个可用记录编号”，不要继续写入 `NO0093`，也不要把多个后续实验合并进同一篇长文档。
- 如果一个任务同时包含实现、结构验收、runtime 验收和诊断，应按阶段拆成多篇记录；每篇只保留本阶段的动机、口径、关键数据、结论和下一步。
