# TNO0041：向量译码共享输入掩码与局部功能门

日期：2026-11-11（America/Los_Angeles）。前置定位见 [TNO0040](./TNO0040_priority_mux_sinking_cause_20261111.md)。本记录覆盖优化实现与原型；正式重新生成及 8 对性能结果另立文档。

## 优化对象与边界

继续使用 after 原 seed7、Clang 23、完整 DiffTest。不重新分区、不改 RTL、向量指令语义、断言或 DiffTest observer。`part_8/batch_53` 的一个节点用 59 个稳定布尔值反复完成 368 项、每项约 16–26 个字段的 AND 归约；多个向量译码节点具有相同形态。

现有 `scalar_concat_reduction` 省去了完整 concat，但仍逐项生成许多标量 OR/NOT。新选项 `scalar_concat_reduction_masks` 在同一 compute supernode 内把稳定布尔输入打包成一个 `uint64_t`，各归约使用常量掩码比较。AND/NAND 与 OR/NOR 保持既有 consumer 取反契约。每个输出的写入和 change detection 保留。

这是通用 emitter 规则，不匹配香山模块名或指令 opcode，不新增 GRH operation。默认关闭；实验显式设置 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS=1`。实现契约见 [后端说明](../../wolvrix/docs/emit/grhsim-bool-reduction-masks.md)。

接受条件：至少 16 个可复用谓词，每项至少 16 个一位字段，整个族最多 64 个独立输入；输入为 port 或本节点无写入的 Boolean slot，检查 canonical value 与实际 slot 两种写入别名。排除 direct state view、event、内部定义、前置未知副作用。concat 的所有用户必须是本节点稍后的同一归约族；numeric use、混合族、parity、宽度超限等保留原路径。

## 局部功能门

`WOLVRIX_TEST_SCALAR_CONCAT_REDUCTION_MASKS=1` focused test 已通过：

- 默认/off 生成源码一致；只有 3 个满足契约的 fixture 节点触发。
- direct input 与跨节点持久 Boolean slot；16/64/65 输入边界；重复字段与第 63 位。
- numeric output、混合 AND/OR、局部写入和副作用回退。
- 每个版本 12,000 组固定种子数据，含零、全一、walking one/zero，每组重复 eval 两次。
- Clang 23 `-O0/-O3`，ASan/UBSan，使用逐字段 AND/OR/concat 的独立参考值。

日志：[mask-tests.log](../../build/artifacts/repcut-vector-decode-20261111/mask-tests.log)。原 scalar concat reduction 回归单独运行并归档，不使用这些带 sanitizer 的 fixture 计时推导整机收益。

## 冻结生成源码原型

先用独立产物中的受限源码转换确认方向：只接受全部由稳定 Boolean storage alias 构成、无中间写入的 AND 归约，保留原归约位置和后续输出。冻结原 package 不修改。原型转换器与编译/链接命令见 [prototype.py](../../build/artifacts/repcut-vector-decode-20261111/prototype.py)。

46 个 C++ 文件、119 个节点、49,255 个归约触发。相关源文件合计由 112,780,510 B 减至 30,046,665 B；binary 由 119,370,960 B 减至 117,249,232 B。固定原 harness 与其他对象，仅重编译这 46 个对象。

node030、CPU96–127、NUMA1 bind、ASLR off、原 code-page/preload/pinning：双方 10k smoke、100k DiffTest、预热及 2 对诊断运行通过，PC/指令/周期/终止条件/UART 签名相同。诊断 Host 均值 17.0695 → 13.8225 s，逐对均值约 −19.01%。这只有 2 对，且是生成源码原型，不能代替后端正式产物的 8 对验收。外部 walltime 有较明显波动，后续分别报告 Host 与外部 walltime。

原型数据：[summary.json](../../build/xs/repcut-vector-decode-20261111/measure-prototype-r1/summary.json)、[转换范围](../../build/xs/repcut-vector-decode-20261111/prototype/rewrite.json)。首次 driver 因 `external_wall_s` 字段名称写错，在 A 的 smoke 已通过后停止；记录保留于 `measure-prototype/`，未纳入诊断配对。链接脚本最初假设命令记录含 `env`，修正后复用已编对象完成链接；均未改写冻结基线。

后续正式候选必须从冻结的 `partitioned.json` 通过修改后的 emitter 重新生成，并通过源码差异审计、完整 DiffTest 与 8 对 AB/BA 后再判断收益。

## 增量更新 2026-11-11

原 concat reduction 回归和完整 emitter 回归均通过。正式生成与扩展功能门已记录于 [TNO0042](./TNO0042_vector_decode_generated_functional_gate_20261111.md)，8 对正式性能结果见 [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md)。原型数据保留，不替代正式结果。
