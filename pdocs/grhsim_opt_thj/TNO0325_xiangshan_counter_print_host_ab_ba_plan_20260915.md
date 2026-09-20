# TNO0325: XiangShan counter-print Host AB/BA plan

日期：2026-09-15

状态：`PLAN; SYMMETRIC PARTITION BUILD AND HOST CAPTURE`。

## 1. 固定比较对象

用户要求实测 [TNO0323](./TNO0323_xiangshan_counter_print_asc_split_result_20260915.md)
单行counter-print修改的Host收益。A为原RTL的fresh-ingest control，B为counter-print候选；
输入分别使用TNO0322/TNO0323冻结的GRH，SHA为
`5de21ed7ea9fabe1c457608cc05de6f9be0ba4bb5f8f48c8ddc0c8a87bfa751a` /
`16d4febf66cf3b1a38afe5c87e0d1fa973620600d2326eaaae6ca628ea1ab73c`。

N=K=32；legacy调度、push更新、identity worker-to-part映射。两臂都重新执行同参数
RepCut并从空目录编译全部32个模型，不使用仅relink wrapper的构建入口。
closure-aware、epsilon0.015、quality→deterministic-quality、seed0固定；求解器显式32线程，
不同于历史threads0自动值，但本轮两臂一致、不与历史绝对值配对，也不sweep seed/preset。
生产安装库固定，不使用在solver前返回的ASC观测overlay。

## 2. 构建与功能

复用经审计的stage4_build/build_full.py：Clang21.1.5与同一Verilator、原wrapper无额外-O，
runtime-v1模板但显式legacy/push；独立model objects、source/tool/ELF身份、生成端口与
通信copy审计。两臂使用各自生成的difftest helper与flat SV，不覆盖旧RTL/GRH/package。
新根目录`build/asc_counter_host_20260915/`。

完整输入/输出manifest、exit code、日志和runbook修正分阶段保留。先通过C100 canary，
再进入C10000；保留原difftest、终止PC、guest cycles/instructions、steps与timing记录核验。
打印C而非C+E是明确实验语义差异，不把perf日志数字相等作为gate。
重生成附带的Git标记与打印组顺序差异沿用TNO0321披露，不声称严格单因素日志全序等价。

## 3. Host测量协议

直接使用冻结measurement/run_pair.py与analyze_pair.py，继承
[TNO0282](./TNO0282_xiangshan_repcut_nk32_measurement_protocol_gate_20260907.md)。
仅在node029-node034、node036-node042扫描，同NUMA四个完整CCD，计算核每核一个SMT
thread；审计siblings，monitor不占目标CCD，保留page-local staging及page/worker gate。
历史node031预约不自动假定今天仍有效，扫描不是独占保证。

固定先AB后BA；每序先两臂C100再两臂C10000。CPU/NUMA/monitor/spec/工具/pair-id一致。
原diagnostic policy；仅未launch的admission允许最多4次、间隔5秒、timeout600秒。
不因已启动样本慢、残差或资源判定而单臂重抽；资源失败保留并另记，不修改门槛。

主指标Host和total step wall；辅助看eval max/phase、update phase/worker、PMU、copy字节。
pooled先平均primitive totals再算比率，两序都改善才称方向一致。完整质量判定随结果报告；
CPU accounting不闭合仍披露，不将其自动等同外部负载，也不把−20.83%静态权重直接当提速。
本轮只报告实测，不自动把breaking修改或新分法设为生产默认。
