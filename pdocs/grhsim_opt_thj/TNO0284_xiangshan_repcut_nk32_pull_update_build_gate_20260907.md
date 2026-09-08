# TNO0284: XiangShan RepCut N=K=32 pull update build gate

日期：2026-09-07

状态：`COPY STRUCTURAL AND BUILD GATES PASS; RUNTIME PENDING AFTER STAGE 2`。

前置：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0281](./TNO0281_xiangshan_repcut_nk32_scheduler_build_gate_20260907.md)、
[TNO0283](./TNO0283_xiangshan_repcut_nk32_ccd_mapping_structural_gate_20260907.md)。

## 1. 精确变更

`runtime/generate_pull.py` 对冻结生成代码使用严格语法解析，保留每一条赋值及 wide
copy 语句原文，按照 destination partition 归入更新函数。所有 eval 完成后才更新，
所有 update 完成后才进入下一 step 的边界不变。五个 top_out 仍由原 source 发布。

生成器同时验证目标唯一、语句 multiset、每目标原始顺序、SV/header 位宽与 wide
word count、顶层输出类型与完整性、计时代码不变。14 个 Python 测试覆盖这些拒绝
路径及解释执行的 push/pull 值一致性；这不是代替真实模型 difftest。

重分组保留全部 5137 次拷贝（1341 wide、3796 scalar），总计 449729 storage bytes/update。
计时 JSON 的旧字段名 `update_push_ns` 为保持 ABI/schema 未改，但 pull 下实际代表
该接收方拥有的输入拷贝及原 source-owned top output；分析器用 update_copy 别名解释。

## 2. 构建

独立源目录：`build/repcut_nk32_opt_20260907/runtime/generated-pull-v1/`。
仅重编 common/update_0，common 重编是为了日志真实标记 update_mode=pull。
class header、其余 wrapper、1422 个模型对象及原编译/链接选项保持冻结身份。

`builds/pull-v1/emu` SHA-256：
`42a8077cd7df2535b4dbf355782cbb3793320a6bb8bf236fc31a14205531b3b7`。
node029 构建与对象审计通过，约 8.285 s，完整来源见该目录 build-manifest.json。
端点结构证据为 generated-pull-v1/pull-copy-audit.json。

## 3. 事前风险

最大单 owner 静态拷贝 payload 从 push 的 part11=39035 bytes，变为 pull 的
part6=120458 bytes；pull 的 part8 也达到 83539 bytes。写入归属更集中可能改善
cache-line 所有权，但也可能使更新长尾更重。没有实测前，不把减少写共享称为既定收益。

阶段三按阶段二实际选定的 runtime/映射做完整 push/pull AB/BA，关注 Host、
global_update wall、关键 owner 计时及 eval 的后继缓存效应，不逐项强行比较同名
partition 的 push 与 pull 时间，因为二者负责的拷贝集合不同。
