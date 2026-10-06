# YYYYMMDD-hhmmss <优化题目>

> 从本模板复制为 `YYYYMMDD-hhmmss-<短题>.md` 填写（hhmmss = 创建时刻）；写不出来的章节就是还没做，不许留空话。

## 元信息

- 日期 / 作者：
- wolvrix commit / 根仓 commit：
- 上游基线记录：（链接到作为对照的前一条记录）

## 基线性能

- 机器与负载：（CPU 型号、核数、定核方式、同期干扰）
- benchmark 命令与口径：（标准口径 `make benchmark_grhsim_ir`；偏离须说明）
- 指标定义：（宿主时间 / guest 周期 / 编译时间，单位与测量方法）
- 数据：均值 ± sd，逐次原始值；日志与 summary 的 `ptmp/` 路径

## 优化方案

- 动机：基线中哪一项成本、占比证据（profile/census 数据路径）
- 假设：为什么认为能省、预计省多少
- 改动点：pass / emit / runtime，文件级清单
- 风险与回退：语义风险点、回退开关或还原方式

## 结果性能

- 同口径数据 + 对比表（基线 vs 本轮，逐次原始值）
- 编译时间影响（全量 TU 构建前后）
- 结论：采纳 / 回退 / 部分采纳（附理由）

## 正确性验证

- [ ] `make test_wolvrix`（恰基线三项，无新增失败）
- [ ] `make run_all_hdlbits_grhsim_ir_tests` 162/162
- [ ] `make run_xs_bugcase_grhsim` 25/25
- [ ] `make check_sim_refactor_baseline` 161/161
- [ ] XS 完整 CoreMark + NEMU difftest：HIT GOOD TRAP / exit 0 /
      逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291（或有意重钉并说明）
- 日志路径（`ptmp/`）：

## 后续

- 遗留问题 / 新发现的成本项 / 下一步候选
