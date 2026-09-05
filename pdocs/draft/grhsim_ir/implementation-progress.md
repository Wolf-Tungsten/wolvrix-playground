# GrhSIM IR 基础架构实现进展

更新时间：2026-09-05

## 当前边界

- 保留 `scripts/wolvrix_xs_grhsim.py`、`emit_grhsim_cpp` 和现有 GRH pass/session 路线，不修改其行为。
- 新路线只执行约定的九个 GRH pass，然后把扁平 GRH 单向 lowering 到独立 GrhSIM IR。
- 本阶段终点是 GrhSIM JSON 的 verify、store、load 和稳定 round-trip，不生成仿真代码。
- GrhSIM semantic pass 原地修改；emit 预留为 `PassKind::Emit`，但本阶段不实现 emitter。

## 本阶段落地

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 独立数据模型 | 完成 | typed ID、字符串 interner、扁平数据池、identity/revision |
| core 方言与 verifier | 完成 | 独立 `DialectRegistry`，覆盖当前 GRH lowering 所需的 core 类型/op/Init |
| GrhSIM pass 基座 | 完成 | 独立 registry/manager、五种 `PassKind`（含 `Emit`），首个 analysis pass 为 `grhsim.verify` |
| GRH lowering | 完成 | 扁平 top、I/O/S/F/G/Init、event history、DPI、可选 provenance |
| JSON load/store | 完成 | 流式 `wolvrix.grhsim.v1`、声明计数预留、原子 store、load 后完整验证 |
| Python/session API | 完成 | lower/pass/pipeline/load/store，独立 model key 空间和完整 key 生命周期 |
| XiangShan 并行路线 | 完成 | 独立脚本、Make target、flat GRH/GrhSIM/round-trip 三类 checkpoint |
| 本阶段验证 | 完成 | C++、Python、损坏 JSON、小 RTL 九 pass 路线和现有 XiangShan 大 checkpoint |

这里的“完成”只表示当前阶段要求的“能从 flat GRH 构造、verify、store、load 并稳定 round-trip”。
规划文档中的 editor、analysis cache、backend mapping verifier、ArtifactSink 和实际 emit pass 仍属于
后续里程碑，不能从本表推断为已实现。

## 已完成验证

- `grhsim-ir-tests`：小型 flat GRH lowering、register/event-history、registry pass、层次拒绝。
- `grhsim-ir-tests`：稳定 store/load/store、坏 format、坏 table count、坏 TypeId、load 后 fresh
  identity/revision。
- Python smoke：真实 SystemVerilog ingest 后完成 lower/verify/store/load/store，并验证 session
  kind/filter/copy/rename/delete 生命周期。
- 新脚本非 resume 路径：严格按约定顺序执行九个 GRH pass，保存 flat GRH，再完成 GrhSIM
  store/load/store 字节级稳定往返。
- XiangShan 现有 flat GRH 检查点（2.9 GB）规模实测：4,981,305 ops、4,677,017 values、
  10,625,734 operands、695,052 states。输出 GrhSIM JSON 为 444 MB，两次 SHA-256 均为
  `5b2494766fbc12030cd919452835bcfd7443a81b7e1f5314499d61dd0e27075c`；总耗时约 39 秒，峰值
  RSS 约 27.0 GiB（包含旧 GRH JSON load 和 lowering 期间双 IR 共存）。
- 全量 CTest：49 项中 47 项通过，包括新增 GrhSIM IR、全部 ingest 和旧 `emit-grhsim-cpp`。
  两项既有 transform 测试稳定失败：`transform-comb-lane-pack`（storage frontier rewrite 断言）和
  `transform-repcut`（partition static feature export 断言）；本次未改动对应实现。

## 已知限制

- CPU/Corvus backend mapping、emit 和 runtime 不在本阶段范围内。
- `PassKind::Emit` 已作为统一 pass 模型的一部分，但当前没有注册实际 emit pass，也不提供
  `build_grhsim`/`emit_grhsim` 基础 API。
- 首版只接受已经完成 XMR resolve、blackbox guard 和 hierarchy flatten 的单个 top。
- 当前 Python `run_grhsim_pipeline` 是基础便利入口；等 semantic/backend mutation pass 落地时，
  需要下沉成一次 native manager 调用，以统一处理 revision、增量验证和 artifact 提交。
