# 20261004 v2 六阶段架构（V3-M3 终态）性能基线

## 元信息

- 日期：2026-10-04 / 作者：kimi（数据经作者确认）
- wolvrix commit：`66000f6`（V3-M3）/ 根仓 commit：`9d357b8`
- 上游基线记录：无（本目录首条，即全部后续优化的对照基线）
- 性质：这是**基线登记**，不是优化记录——"方案"栏描述当前代码相对 M0 存档的
  全部差异（v2 六阶段架构 + V3 三项工程化），"结果"即当前状态。

## 基线性能（M0 存档，v2 之前的旧六阶段实现）

- 口径：`make benchmark_grhsim_ir`——100k CoreMark 周期、M0 存档
  （`ptmp/sim-refactor-baseline/xs-flow`）与当前构建（`build/xs/grhsim-ir`）
  3+3 交替、页缓存逐出、taskset 定核；全部 6 次运行命中同一期望终点
  （instrCnt=240,349 / cycleCnt=99,996 / 100,001 轮 / 末 PC 0x80000c0c，
  逐拍一致）。
- 数据：M0 宿主时间均值 **85.9s**（85.78 / 86.37 / 85.64，sd 0.39）。
- 数据存档：`ptmp/v3m3_bench/`（preregister / results / summary.json），
  日志 `ptmp/v3_bench.log`。

## 方案（当前代码相对 M0 的全部差异）

- v2 六阶段架构（2026-10-03）：去 eventActiveFlag；sink/非 sink 分类；
  sink 按事件签名聚类（SinkEvent eventActStore 组合门控、SinkEscape 每轮
  逃逸）；三条边界规则。动机是修复 latch-ICG 激活死锁（见
  `pdocs/simulation-model-refactor/grhsim-ir-architecture.md` §2.2），
  性能不是本架构的目标函数。
- V3 三项工程化：激活旗标位图化（M1，-17.3%）；sink 超节点 TU 拆分
  （M2，-2.6%，主要收益在编译侧）；克隆共享计算移入 C 段（M3）。
- 演进链（完整 CoreMark 宿主时间，同机同负载）：v2 791.8s → V3-M1 654.9s
  → V3-M2 637.6s → V3-M3 648.4s（V3 合计 -18%）。

## 结果性能（当前 = V3-M3）

- 宿主时间均值 **223.4s**（222.8 / 223.9 / 223.6，sd 0.56）vs M0 85.9s
  = **2.60× 回退**（cliff_delta=1.0，逐次无重叠）。
- 编译：emit 约 6.7 min（1091 TU / 约 1.5 GB 源码）；clang -O3 -j32 全量
  约 14.5 min。
- 归因（对照 M0 存档口径）——回退几乎全部来自 v2 架构与旧实现的设计差，
  而非 V3 三项：
  1. **"事件即激活"**：{posedge clock} 单签名 sink 簇 88.5k op
     （74,967 寄存器写 + 7,188 系统任务 + 6,365 断言）每 guest 周期整体
     点火、逐 op 查 en；旧数据门控下这些写只在输入变化时运行。
  2. **boundary_fields +33.6%**（683,995→913,245）：sink 操作数全部经
     boundary，每轮比较-store 与激活传播增多。
- 逃逸类成本实测可忽略（409 op，ICG 锁存写为主），v2 计划风险 1 不成立。

## 正确性验证（V3-M3 提交时全绿）

- test_wolvrix 54/57（恰基线三项）；HDLBits 162/162；xs-bugcase 25/25；
  黄金差分 161/161；XS 完整 CoreMark + NEMU difftest HIT GOOD TRAP、
  exit 0，逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291（V2-M5 起不变）。

## 后续

- 优化候选 backlog 见 `README.md`（sink 簇使能锥细分 / 发射器内联 · ThinLTO /
  en 条件静态化）。
