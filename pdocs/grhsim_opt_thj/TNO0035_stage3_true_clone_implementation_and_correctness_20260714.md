# TNO0035 Stage 3 true clone implementation and correctness

记录日期：2026-07-14

状态：Stage 3 bounded true local-shared-compute clone 已实现；focused correctness、全量增量构建、Python/XS 参数绑定与独立 review 通过，默认保持关闭，进入 SimTop identity/structure gate。

## 1. 实现与参数

实现保留已有总开关并收紧旧 dormant 默认，同时增加两个预算：

| C++ option | CLI / Python | Default |
| --- | --- | ---: |
| `enableLocalSharedCompute` | `-enable-local-shared-compute` / `enable_local_shared_compute` | `false` |
| `localSharedComputeMaxFanout` | `-local-shared-compute-max-fanout` / `local_shared_compute_max_fanout` | `2` |
| `localSharedComputeMaxWidth` | `-local-shared-compute-max-width` / `local_shared_compute_max_width` | `64` |
| `localSharedComputeMaxClones` | `-local-shared-compute-max-clones` / `local_shared_compute_max_clones` | `4096` |
| `localSharedComputeMaxClonedOpPpm` | `-local-shared-compute-max-cloned-op-ppm` / `local_shared_compute_max_cloned_op_ppm` | `5000` |

两个新 size CLI 均支持分离与 `=` 形式；cloned-op PPM 限制为 `<=1,000,000`。XiangShan 脚本同步提供 `WOLVRIX_XS_GRHSIM_ENABLE_LOCAL_SHARED_COMPUTE` 和 `WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_*`，配置行会打印完整取值。editable `.venv` 已重装，kwargs smoke 产生预期五组参数。

clone hard limit 为：

```text
min(maxClones, floor(baselineComputeOps * maxClonedOpPpm / 1,000,000))
```

乘法使用饱和保护；`maxClones=0` 或 `ppm=0` 都保持 graph 不变。

## 2. True-clone 流程

source clone/refreeze 后先运行一次完整 `buildComputeNodeRewrite` 作为 immutable baseline。开启 Stage 3 时按 baseline topo 稳定扫描 compute op，首版只允许：

- cheap pure allowlist，包含 add/sub、bit/logical/compare/reduce/shift/mux/assign/concat/replicate/static/dynamic slice；明确排除 mul/div/mod、storage/system/DPI/XMR、`kSliceArray` 与 unknown kind；
- 单个 `Logic` result、width `1..64`，非 declared/input/output/inout，无 side effect 或 `regToMem.intent.*` attribute；
- 恰好两个 distinct compute user op，且分属两个 compute node；source owner 必须就是其中一个 consumer node；
- source/original/remote node 均非 indivisible/intent；remote node 的累计 planned add 不超过 cap；
- source 的每个 operand 已经是 remote node local value 或该 node 的既有 boundary input。

最后一条保证 clone 不会为了删除一条 result boundary 又新增 operand boundary。发现阶段按 target node 累计预留容量，并在任何 graph mutation 前深拷贝 kind、operands、attrs、op/result source location 和 result type metadata，避免 span 失效与候选链污染。

apply 为每个 plan 正式创建新 op/value，并改写 remote consumer 的全部对应 operand occurrence；原 op/value 保留，local compute clone 不加入 source clone 的 canonical value map。

## 3. Rebuild 与验证

只要应用至少一个 clone，就重新 `freeze()`，从头构建 `ActivityOpData`、`opClasses` 和 `ComputeRewriteBuild`，最终 export/materialize 只使用 candidate rewrite。验证包括：

- baseline/candidate commit node count、ops 与 input values 完全相同；
- intent op-to-group map 完全相同；
- candidate compute-node cycle split 次数不得增加；
- original/clone 分属两个 node，并分别与 retained/rewritten consumers local；
- 所有非 indivisible compute node 不超过 `maxOpInComputeNode`；
- 后续 materialize 继续执行完整 schedule coverage/topology/fanout rebuild。

关闭总开关时不运行发现、clone 或二次 rebuild；原有 summary 字段 `local_shared_compute_clones_in_compute_nodes` 继续记录实际 clone 数。详细 scanned/eligible/planned/applied、budget 与各类 reject 只写日志，避免改变 default-off stats schema。

## 4. Tests 与 review

focused `transform-activity-schedule` 约 `0.04 s`，覆盖：

- 真正未设置 option 的 default 与显式 `false` schedule identity；
- 正向 true clone、重复构造确定性、original/clone 分别 local，两个 clone result 都无跨 supernode fanout；
- `maxClones=0`、`ppm=0`、width、fanout、side-effect、declared、missing-boundary 与 common-owner reject；
- 多候选共享 target 的累计 cap 只允许一个 clone；
- 与 Kahn/post-DP strict 同时启用后的 shape/topology；
- cloned-op PPM 越界诊断。

全量增量 build PASS。全量 CTest 为 `46/48`：`emit-grhsim-cpp` PASS（`234.22 s`），仅 `transform-comb-lane-pack` 与 `transform-repcut` 失败；两项失败文本与 Stage 2 已在干净基线确认的既有失败相同，不是本阶段新增。

两轮独立只读 review 最终均无 P0/P1，确认 source-owner、strict operand-locality、aggregate cap、template snapshot、canonical map、refreeze/rebuild、commit/intent/cycle split 等关键项闭合。父/子仓 `git diff --check` 与 Python `py_compile` 均通过。

## 5. 保留风险

focused 组合 fixture 可证明 API 共存，但小图上的 Kahn/post-DP 可能没有实际 move；intent/output/sink 与候选链污染主要由实现 guard 和 rebuild validator 覆盖，尚无各自独立 fixture。另一个必须由 SimTop 观察的风险是：result 虽然不超过 64 bit，compare/reduce 的 operands 仍可能很宽，true clone 可能增加 generated expression/code footprint。

因此当前只能进入大图结构与 generated-code gate，不能从单测推断性能；总开关继续默认 `false`。
