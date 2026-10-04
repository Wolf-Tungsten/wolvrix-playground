# 20261005 P_mem act 聚类 + 死 compare-store 删除

## 元信息

- 日期：2026-10-05 / 作者：kimi
- wolvrix commit：`66000f6` + 未提交工作树（V3-M3 + A1 机制 + memEnableBits +
  本项改动）
- 根仓 commit：`1b94a8d` + 未提交工作树
- 上游基线记录：`20261004-pmem-enable-bitmap.md`（204.1s）；
  顶层基线 `20261004-v3-sixphase-baseline.md`（V3-M3，223.4s）

## 基线性能

- 机器与负载：AMD Ryzen 9 7950X3D（32 线程），单核定核 `taskset -c 2`，
  无同期干扰任务。
- benchmark 命令与口径：标准口径 `make benchmark_grhsim_ir`（3+3 交替、
  页缓存逐出、定核）；old = memEnableBits 版构建归档
  （`ptmp/grhsim-ir-pmem-act-20261005/old-flow`，204.1s 那版），
  new = `ptmp/grhsim-ir-pmem-act-20261005/new-flow`（本项）。
- 指标定义：宿主时间（emu 自报 Host time spent，100k CoreMark 周期）。
- 数据：old 均值 **204.11s**（204.556/204.024/203.761，sd 0.41，
  见 `ptmp/grhsim-ir-memenable-bitmap/bench/`）。

### 动机证据（2026-10-04 对 memEnableBits 版模型的普查）

1. **死 compare-store**：`publishBoundary`/`publishDpiResult` 的
   `if(slot!=v){slot=v;<fanout/hook>}` 中，fanout 与 hook 皆空的站点
   202,875 / 869,692（23.3%）——变化事件无人消费（P_mem/P_event/P_output
   均无条件执行，不经 dataActiveFlag 激活），compare 是纯开销，且把
   load→比较→分支依赖链放在发布路径上。
2. **P_mem 逐端口重复 act 守卫**：22,641 个写口每个都重读
   `eventActStore`；其中时钟 act(0,0) 一个就覆盖 11,566 口。端口体只读
   eventActStore（P_event 在本轮独占写），同守卫段合并判断精确等价。

## 优化方案

- 假设：①死 compare 删除把 23.3% 发布站点从"load+cmp+分支+条件写"降为
  一次无条件 store，收益落在 P_general；②act 聚类把每 chunk 的 act 判断从
  每端口一次降为每段一次，收益落在 P_mem。两项合计预期 1~4%。
- 改动点（均在 `wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`）：
  - `publishBoundary` / `publishDpiResult` / 宽值 concat 与宽值直达路径：
    `supernodeFanout_[v]` 为空且无位图 hook → 发射无条件 store。
  - `memChunkFn` 二级分组：外层按 act 守卫文本的极大连续段，段首一次
    `if(guard)`；内层沿用 enable 位图 run 聚合。`emitMemWrite` 增加
    `actHoisted` 参数，段内端口不再发射各自的 act 守卫。
  - 顺序保障：两级分组都不重排端口——计划优先级序严格保持。
  - 测试：新增 `memActClusterDeadCompareTest`（行为序列 + act 守卫计数 +
    无条件 store 断言）；顺带修复 `memEnableBitmapTest`/`memReaderGatingTest`
    里 substr 第二参数误用为位置的切片 bug。
  - 文档：`wolvrix/docs/grhsim_ir/backends/cpu.md` 补 act 聚类与死
    compare 删除两段。
- 明确不做（评审结论：语义不干净）：恒 1 端口的 data 脏位门控、恒 1 端口
  退化纯 store、读者激活上移到生产端。
- 风险与回退：死 compare 删除改变的是"写是否执行"的频率而非字段值，
  dumpState/waveform/收敛语义均不可观测；act 聚类为纯代码移动。回退：
  git 还原（本项无运行时开关）。

## 结果性能

- 同口径数据（`make benchmark_grhsim_ir`，3+3 交替、页缓存逐出、定核 CPU 2，
  全部 6 次命中期望终点 240349/99996/100001/0x80000c0c；
  `ptmp/grhsim-ir-pmem-act-20261005/bench/`）：

  | | old（memEnableBits 版） | new（本项） |
  |---|---|---|
  | 逐次宿主时间 (s) | 203.266 / 203.442 / 203.992 | 178.818 / 178.842 / 179.173 |
  | 均值 ± sd (s) | 203.567 ± 0.379 | 178.944 ± 0.198 |

  **改进 12.10%**（rank gate 通过：max(new) < min(old)；cliff_delta=-1.0；
  one-sided exact p=0.05）。对 V3-M3 累计：223.4s → 178.9s（-19.9%）；
  对 M0 差距：2.38× → 2.08×。
- 分项归因（perf 复测，`ptmp/grhsim-ir-phase-perf-20261004/perf-20261005.data`，
  172,263 样本，同一归因脚本；绝对时间 = 占比 × 各自均值）：

  | 阶段 | 前（204.1s 版）占比 | 后（178.9s 版）占比 | 绝对时间变化 | 归属 |
  |---|---|---|---|---|
  | P_general | 92.12% | 92.44% | 188.0s → 165.4s（**-22.6s**） | 死 compare 删除 |
  | P_mem | 3.57% | 2.97% | 7.3s → 5.3s（**-2.0s**） | act 聚类 |
  | P_publish | 2.88% | 3.06% | 5.9s → 5.5s | 不变（占比被动上升） |
  | P_event | 0.88% | 0.91% | 1.8s → 1.6s | 不变 |
  | 模型外 | 0.50% | 0.56% | 1.0s → 1.0s | 不变 |

  绝对时间交叉验证：-22.6 + -2.0 ≈ -25.2s = 总差（204.1→178.9）✓。
  死 compare 删除的收益（~11pp）远超预估，主因除依赖链缩短外还有代码体积
  收缩带来的前端取指改善。
- 编译时间影响：TU 数不变（1082）；生成代码总行数下降（202,875 个
  compare-store 退化为单行 store，P_mem 守卫行数减少 ~1.1 万）。
- 结论：**采纳**（无运行时开关；回退 = git 还原）。

## 正确性验证

- [x] `make test_wolvrix`：54/57，恰基线三项（transform-comb-lane-pack /
      transform-repcut / ingest-write-back-slice SEGFAULT），无新增失败；
      新增 `memActClusterDeadCompareTest`（行为 + act 守卫计数 + 无条件
      store 断言）通过
- [x] `make run_all_hdlbits_grhsim_ir_tests` 162/162（exit 0）
- [x] `make run_xs_bugcase_grhsim` 25/25
- [x] `make check_sim_refactor_baseline` 161/161 逐 eval 一致
- [x] XS 完整 CoreMark + NEMU difftest：HIT GOOD TRAP、exit 0，
      逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291 一致
      （`ptmp/grhsim-ir-pmem-act-20261005/full/`，Host 527.6s@CPU4）
- 日志路径：`ptmp/grhsim-ir-pmem-act-20261005/{bench,smoke,full}`、
  `ptmp/grhsim-ir-phase-perf-20261004/perf-20261005.data`（复测采样）
- 说明：benchmark 的 old/new 流目录在 `ptmp/grhsim-ir-pmem-act-20261005/`；
  采纳后已把 new-flow 的 model/ 与 emu 同步回默认工作目录
  `build/xs/grhsim-ir`（100k 复测端点一致）。

## 后续

- 六阶段占比（本项后）：P_general 92.4% / P_publish 3.1% / P_mem 3.0% /
  P_event 0.9% / P_output+P_input <0.1%。下一大头只剩 P_general：
  sink 簇与 3.6 万小超节点长尾（见
  `20261004-pmem-enable-bitmap.md` 的 perf 解剖）。
- P_publish 的 529KB 每轮 memcpy（~3%）与 scan 的字扫描（P_general 内
  ~4.7pp）是已知小项；每 eval 轮数仍待 WOLVRIX_GRHSIM_PERF=1 实测。
- 评审明确不做（语义不干净）：恒 1 端口 data 脏位门控、恒 1 端口退化
  纯 store、读者激活上移生产端。
