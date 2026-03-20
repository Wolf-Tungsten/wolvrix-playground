# RepCut 使用已安装 mt-kahypar 迁移计划

## 实施状态（2026-03-04）
- M1-M4 已落地到代码：
  - `repcut` Phase-D 已切换为 `mt-kahypar` C API 后端。
  - `-kahypar-path` 参数已移除；新增 `-partitioner` / `-mtkahypar-preset` / `-mtkahypar-threads`。
  - `scripts/wolvrix_xs_repcut.py` 已改为新参数。
  - `transform-repcut` 测试改为基于 `WOLVRIX_HAVE_MT_KAHYPAR` 宏判定是否跳过。
- 构建侧新增：
  - `WOLVRIX_ENABLE_MT_KAHYPAR`（默认 ON）
  - `WOLVRIX_HAVE_MT_KAHYPAR`（自动检测并导出）

## 1. 目标与边界

### 目标
- 将 `repcut` Phase-D 从外部 `KaHyPar` 可执行文件调用，迁移为使用已安装的 `mt-kahypar` C 库。
- 去除运行时对系统 `KaHyPar` 的硬依赖，保留 `hgr` 中间产物与现有诊断风格。
- 保持 Phase-E 以及后续重建逻辑不变（输入仍是 `ascPartition` 向量）。

### 非目标
- 本次不重写 RepCut 的超图构建算法（Phase A/B/C 不改）。
- 不在第一阶段追求与旧 `KaHyPar` 完全一致的 cut 质量，仅保证功能可用+可回归。

## 2. 现状梳理（代码锚点）

- `wolvrix/lib/transform/repcut.cpp:2703` 附近：当前会写 `*.hgr`、`*.kahypar.cfg`、`*.kahypar.log`。
- `wolvrix/lib/transform/repcut.cpp:2757`：通过 `runKaHyParCommand()` 调用 `KaHyPar` 外部进程。
- `wolvrix/lib/transform/repcut.cpp:2798` 之后：从 `*.part*` 文件读取分区结果。
- `wolvrix/include/transform/repcut.hpp:18`：当前仅暴露 `kaHyParPath` 作为后端入口。
- `wolvrix/lib/core/transform.cpp:1091`：CLI 参数解析目前仅支持 `-kahypar-path`。
- `wolvrix/tests/transform/test_repcut_pass.cpp:21`：测试通过 `command -v KaHyPar` 判定是否跳过。

## 3. 迁移方案（推荐：C API 直连）

## 阶段 A：抽象 Phase-D 后端（不改功能）
- 在 `repcut.cpp` 内引入 `PartitionBackend` 抽象（先保留 `KaHyParCliBackend` 现实现）。
- 把“写 hgr / 调分区器 / 取分区向量”收敛为一个接口，Phase-D 主流程只关心：
  - 输入：`HyperGraph`, `partitionCount`, `imbalanceFactor`, `workDir`。
  - 输出：`std::vector<uint32_t> ascPartition` + 诊断信息。
- 目标：先做无行为变化重构，减少后续接入 mt-kahypar 的风险。

## 阶段 B：接入 mt-kahypar C API（主路径）
- 新增 `MtKaHyParBackend`，核心调用链：
  1. `mt_kahypar_initialize()`（`std::call_once` 全局初始化，避免重复初始化）。
  2. `mt_kahypar_context_from_preset(DEFAULT/QUALITY)`。
  3. `mt_kahypar_set_partitioning_parameters(k, epsilon, KM1)`。
  4. `mt_kahypar_read_hypergraph_from_file(hgr, context, HMETIS, &error)`。
  5. `mt_kahypar_partition(...)`。
  6. `mt_kahypar_get_partition(...)` 提取分区数组。
  7. 释放 context/hypergraph/partitioned_hg/error。
- 保留 `writeHyperGraphToHmetis()`，避免改动输入格式；先“写 hgr 再读 hgr”完成最小侵入迁移。
- 如 `keepIntermediateFiles=true`，可选调用 `mt_kahypar_write_partition_to_file()` 以保留调试体验。

## 阶段 C：参数与兼容策略
- `RepcutOptions` 变更（建议）：
  - 新增：`partitioner = "mt-kahypar"`（默认）。
  - 新增：`mtKaHyParPreset = "quality"`（或 `default`，需通过回归决定）。
  - 新增：`mtKaHyParThreads = 0`（0 表示硬件并发）。
  - 保留：`kaHyParPath` 一段时间作为兼容字段（deprecated）。
- CLI 解析（`transform.cpp`）新增：
  - `-partitioner`
  - `-mtkahypar-preset`
  - `-mtkahypar-threads`
- 兼容期内若传 `-kahypar-path`：
  - 输出 warning（已弃用），但不立即报错，方便脚本平滑迁移。

## 阶段 D：构建系统集成
- 目标是链接系统中已安装的 `mtkahypar`（例如 `/usr/lib` 或自定义前缀）。
- CMake 建议：
  - 增加开关：`WOLVRIX_ENABLE_MT_KAHYPAR`（默认 ON）。
  - 优先使用 `find_library(mtkahypar ...)` + `find_path(mtkahypar.h ...)`。
  - 链接成功时定义 `WOLVRIX_HAVE_MT_KAHYPAR=1`。
- 注意事项（必须在计划中显式处理）：
  - `mt-kahypar` 子项目要求 CMake 3.26，而 wolvrix 当前文档是 3.20+。
  - `mt-kahypar` 默认会 `FetchContent` 拉依赖（CLI11 等），对离线/受限网络环境不友好。
- 因此建议先采用“两步构建”：
  1. 通过系统包管理器或独立安装流程安装 `libmtkahypar` 与头文件。
  2. wolvrix 仅做“发现并链接”，不 vendor 内嵌构建 `mt-kahypar`。

## 阶段 E：测试与回归
- 更新 `wolvrix/tests/transform/test_repcut_pass.cpp`：
  - 跳过条件从 `KaHyPar` 可执行变为 `WOLVRIX_HAVE_MT_KAHYPAR`（编译期）+ 运行时可用性检查。
  - 断言从“存在 `.KaHyPar` 风格 part 文件”改为“存在可解析分区结果或后端产物”。
- 新增用例（建议）：
  - `repcut` 在 `mt-kahypar` 不可用时给出明确诊断。
  - `partitionCount`/`imbalanceFactor` 非法值路径。
  - `keepIntermediateFiles` 下产物完整性校验。
- 现有 XiangShan 脚本迁移：
  - `scripts/wolvrix_xs_repcut.py` 去掉 `REPCUT_KAHYPAR_PATH`，改传新参数（`-partitioner/-mtkahypar-*`）。

## 4. 风险与缓解

- 配置语义差异风险：旧 `buildKaHyParConfig()` 与 mt-kahypar preset 不等价。  
  缓解：先固定一个 preset（`quality`），对比关键设计（至少 hdlbits + xs 小样本）观察 QoR/耗时。
- 构建环境风险：`mt-kahypar` 依赖 CMake 3.26 + TBB/hwloc + 可能联网抓依赖。  
  缓解：两步构建、在 README 增加明确依赖说明、CI 上显式缓存/预装依赖。
- 线程与确定性风险：`mt_kahypar_initialize` 与 `set_seed` 是全局语义。  
  缓解：默认固定 seed（可配置），并限制在单进程内只初始化一次。
- 诊断可观测性下降：从外部日志文件切到库调用后日志变少。  
  缓解：统一封装 `mt_kahypar_error_t` 到现有 `repcut phase-d` 错误文案，并保留 hgr/partition 文件选项。

## 5. 里程碑与验收标准

### M1（重构不改行为）
- 完成后端抽象，`KaHyPar` 路径仍可通过现有测试。

### M2（mt-kahypar 主路径打通）
- `repcut` 默认走 mt-kahypar，能够稳定生成 `ascPartition` 并通过 `transform-repcut`。

### M3（脚本/参数切换）
- `scripts/wolvrix_xs_repcut.py` 与 CLI 参数完成迁移，旧参数进入兼容期 warning。

### M4（清理与收尾）
- 文档更新（构建依赖、repcut 参数）。
- 在确认回归稳定后移除 `-kahypar-path` 和旧外部调用代码。

## 6. 建议执行顺序（最小风险）
- 先做 M1（纯重构）再做 M2（新后端），避免“大改+换后端”叠加。
- M2 成功后立刻改测试，再改脚本（M3）。
- 至少跑一轮：`ctest --test-dir wolvrix/build --output-on-failure` + `run_xs_repcut` 小样本。
