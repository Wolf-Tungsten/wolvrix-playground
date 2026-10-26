# 单个原调用与原图调用顺序的语义决定

2026-10-25，用户明确选择：**采用单个原调用语义，明确记录与旧实现的差异**。

同日，用户进一步选择：**保留原图调用顺序，记录旧调度差异**。

## 目标契约

- DPI op 保留原调用身份；提取 Event/Output 锥不得克隆该调用。
- 跨区消费者读取原调用已产生的 held sample；Output 不为获得结果再调用一次 DPI。
- 无数据依赖的独立调用保留原图调用顺序；不得为复刻旧分区调度的排序而交换调用。
- `grhsim.effectPolicy=single-original-call` 为目标语义。它不等于“每个 eval 恰好调用一次”：原 guard、事件和 General 收敛轮次仍决定原调用何时执行。
- 不修改冻结旧日志；报告保留原始 outputs/states/ordered effects 差异，并区分已批准与未解决项。

## 已确认的旧行为差异

冻结 `dpi_bit_abi` 在 General 与 Output 各调用一次。新路线保留一个原调用及共享结果。三次 init epoch、每次两次有效 eval，共六条 effects 记录由两个完全相同的调用变成一个；实参、原始返回值、output 参数及模型输出仍逐项比较。

`compare_remove_grhsim_ir.py --effect-policy single-original-call` 只将上述 fixture 中精确的“两个相同调用 → 一个相同调用”归类为已批准。新增 `single-original-call-source-order` 在此基础上，另接受 `dpi_smoke`/`dpi_smoke_tu` 中精确的 `[dbl, inc] → [inc, dbl]`，要求两个调用的 kind、实参、返回值及其他记录字段完全一致。这不是任意 effects 排序豁免，不适用于其他 fixture、增减调用或参数/结果变化。原始 `equal` 仍反映严格新旧相等性；另以 `accepted` 表示所选策略下是否还存在未解决差异。CLI 默认 `strict`；Make 的迁移入口显式选择 `single-original-call-source-order`，设置 `REMOVE_GRHSIM_IR_EFFECT_POLICY=strict` 可复查完整严格比较。

初次比较中冻结 `dpi_smoke`/TU 的同沿顺序与 falling-edge free-call 差异单列为未解决；第一次决定没有批准它们。随后修复 Event 脉冲清零激活及每 eval 无条件唤醒所有 external op 两处错误，次数/触发已与冻结观测一致；[修复后历史报告](../../ptmp/remove-grhsim-ir/r5-observations-triggerfix/comparison.json)中两份 smoke fixture 各剩六条同沿调用顺序差异：旧为 dbl→inc，新为原调用顺序 inc→dbl。第二次决定明确批准该独立调用排序差异；历史报告的 accepted=false 原样保留，新策略结果另存，不回填旧报告。两种函数预算、三次 init、无变化 eval、反沿与数据变化的独立生成执行反例均通过。

R5/R6 仍未完成；最新 emitter、XS 执行及正式性能门禁继续执行。单个原调用不允许以脉冲清零、无输入变化或额外收敛轮次为由凭空增加调用。

## 证据保存

- 初次严格失败：`ptmp/remove-grhsim-ir/r5-observations/comparison.json`，保留原样。
- 按新决定重跑：`ptmp/remove-grhsim-ir/r5-observations-single-call-v1/`。
- 分类规则负例：`make test_remove_grhsim_ir_tooling`。
- 两项决定下的最新重比：`ptmp/remove-grhsim-ir/r5-observations-source-order/comparison.json`，8 fixture、168 记录、18 条已批准原始差异，`equal=false`、`accepted=true`、未解决项 0；inputs/outputs/states 无差异。工具规则与反例 12 项通过。

本决定只改变已批准的调用语义验收项，不放宽数组、状态、调度、输出或性能门槛。
