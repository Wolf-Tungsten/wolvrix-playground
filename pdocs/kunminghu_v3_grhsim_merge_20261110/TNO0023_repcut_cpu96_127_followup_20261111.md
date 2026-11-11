# TNO0023 RepCut GrhSIM CPU96–127 补测

## 冻结构建与运行时 CPU 覆盖

本轮复用 performance 模式下已经完成的 retained binary：before 为 candidate，after 为 initial。配置和构建结果必须都记录 performance=true。原来的构建 CPU 元数据保留；配对 runner 用 --runtime-cpus 96-127 显式覆盖本次运行 affinity，重新确定 NUMA node 1。该 CPU 覆盖不重新 partition、selection、migration 或编译模型。

| 版本 | binary bytes | SHA256 |
| --- | ---: | --- |
| before | 101,037,232 | 8f95d65a4012f52a041948cee8dd6e64c08beb0a212122a831ee26527ce2ec76 |
| after | 118,894,296 | 23a2fe3de33bbc036e3400c7221fc4e4881e2d0a723c779ed799cdabaf7960de |

完整模型与 partition/selection/migration 身份见 [before manifest](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/model-manifests/before-repcut.json) 和 [after manifest](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/model-manifests/after-repcut.json)。历史 [TNO0018](./TNO0018_repcut_primary_paired_walltime_20261110.md)、[TNO0019](./TNO0019_repcut_confirmation_20261110.md) 的 CPU0–31 系列保留，不与本轮样本混合。

## 运行与验收口径

node030、CPU96–127、NUMA1 严格 membind、关闭 ASLR，保留原 performance 流程的 preload/code-page 和线程绑定。运行时 worker_cpus/part_cpus 必须恰为 96–127，实际 32 个线程必须一线程一核，且内存 locality 门通过。记录原始构建 CPU/NUMA 元数据与实际运行配置，避免混淆。

CoreMark、100,000 周期上限、完整 DiffTest/NEMU、8 对 AB/BA；每侧先做 10k smoke、独立 100k DiffTest 检查和预热。每个版本内签名稳定，跨版本共同终止条件、Guest cycles 和 workload 输出一致。正式样本关闭 trace 和模型诊断计数，保留 performance launcher 原有 step timing。无外部 CPU 空闲准入检查。

内部 Host time 与外部 walltime 分别汇总，配对 delta 正数表示 after 更慢，bootstrap 为 seed 20261102、10,000 次。所有失败门记录独立保留并排除于汇总。

本节为运行前记录；结果完成后追加。执行脚本见 [本轮 driver](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/run-followup.py)，完整数据保留在 build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-repcut。

## 增量：8 对正式计时结果

8 对 AB/BA、16 个正式样本全部通过功能与放置门。所有通过门的慢样本均保留；诊断、预热和构建时间不进入统计。正数表示 after 更慢。

| 指标 | before 均值 / 中位数 (s) | after 均值 / 中位数 (s) | 配对 delta 均值 / 中位数 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 18.459 / 18.470 | 17.451 / 17.415 | -5.460% / -5.681% | [-5.841%, -5.011%] |
| 外部 walltime | 18.552 / 18.566 | 17.564 / 17.530 | -5.327% / -5.578% | [-5.708%, -4.882%] |

after 更快 8/8 对。本轮 Host time 区间完全低于零，合并后更快。
这是各 revision 的 DefaultConfig 和所跟踪 DiffTest 的整体比较，不能解释为仿真器后端的隔离优化收益。

| 对（原始索引 + 1） | 顺序 | before Host (s) | after Host (s) | Host delta | before 外部 (s) | after 外部 (s) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | AB | 18.628 | 17.851 | -4.171% | 18.720 | 17.963 |
| 2 | BA | 18.478 | 17.420 | -5.726% | 18.577 | 17.538 |
| 3 | AB | 18.426 | 17.354 | -5.818% | 18.514 | 17.468 |
| 4 | BA | 18.469 | 17.428 | -5.636% | 18.565 | 17.533 |
| 5 | AB | 18.471 | 17.373 | -5.944% | 18.568 | 17.489 |
| 6 | BA | 18.391 | 17.409 | -5.340% | 18.480 | 17.527 |
| 7 | AB | 18.475 | 17.338 | -6.154% | 18.567 | 17.449 |
| 8 | BA | 18.334 | 17.437 | -4.893% | 18.424 | 17.544 |

证据：[summary](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-repcut/summary.json)、[逐对 JSON](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-repcut/pairs.json)、[逐对 CSV](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-repcut/pairs.csv)、[运行 manifest](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-repcut/manifest.json)。
