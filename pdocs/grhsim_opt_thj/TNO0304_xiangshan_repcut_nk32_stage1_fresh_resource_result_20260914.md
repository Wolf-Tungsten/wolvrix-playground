# TNO0304: XiangShan RepCut N=K=32 stage-1 fresh resource result

日期：2026-09-14

状态：`RESOURCE BLOCKED; ONE LEGACY C100 CANARY PASS; ZERO C10000 LAUNCH; NO PERFORMANCE SELECTION`。

前置：[TNO0303 本轮计划](./TNO0303_xiangshan_repcut_nk32_stage1_fresh_retest_plan_20260914.md)、
[TNO0294 上轮诊断及本日勘误](./TNO0294_xiangshan_repcut_nk32_stage1_scheduler_ab_ba_20260909.md)。

## 1. 冻结身份及本地检查

仍使用 `build/repcut_nk32_opt_20260907/specs/stage1_dispatch.json`，同 ELF 比较
A=legacy、B=pipeline-workers，N=K=32、identity worker mapping、push update。

| 文件 | SHA-256 |
| --- | --- |
| measurement/run_pair.py | `7b50e6d9d7780ecc1785f0ceeedfbc8edb7d6732b94431a1f5a316ff2dad9c48` |
| measurement/analyze_pair.py | `9bbf639f05d5ac99e5418e8e239f785d7032474be77d26384f1bd8e5645c4d47` |
| builds/runtime-v1/emu | `1f57c1e00d6e8339ba0b6eade021cfd463f21baa39b0f6fd64d3949a4de20e94` |

在 measurement 目录执行 `python3 -B -m unittest -q test_measurement test_calibrate_communication`，
47 项通过。未重建模型，未改生产代码、冻结工具或门槛。

## 2. 全节点资源证据

轮询全部 13 个允许节点的两个 NUMA，首轮全扫及定向复扫 33 份，后续全扫 26 份，共
59 份原始三窗口扫描。每窗口 3 秒，物理 CPU 0-95/96-191 及对应 SMT siblings 均纳入。
原始路径位于实验根目录的：

- `measurement/scans/retry_20260914_resource/`
- `measurement/scans/retry_20260914_resource_followup/`

两目录分别通过 `runtime/summarize_resource_scans.py` 对 raw counters 独立重算，汇总为
`raw_verified_summary_final.json`（首目录）与 `raw_verified_summary.json`（后目录）。
首目录汇总 SHA 为 `35861d984584ed57b27a3cf0cc3d227f096897f19ff4f8d10261bd5cf463bd5f`。
工具汇总中的 `quiet_resources_found` 只描述扫描窗口，不代表 runner admission 已通过或有独占资源。

仅 node033 在三个扫描点提供候选；其他节点未提供稳定四 CCD。候选到 header 的实际间隔
分别约 276 秒、40 秒、120 秒（含协调、输入 staging 和身份核验），不能称为同窗口预约。
后两次已缩短衔接，但仍未维持到完整功能门。

## 3. 三次实际配对入口

所有 output tag 前缀为 `stage1-dispatch-retry20260914-node033-`，目录位于实验根 `runs/`。
pair-id 分别以 `pair1/2/3` 结尾，不把不同 CPU mask 的 partial captures 拼为一组。

| tag 后缀 | NUMA | 物理 CPU mask | monitor | admission / launch 结果 |
| --- | ---: | --- | ---: | --- |
| ab1 | 0 | 8-15,56-63,72-79,88-95 | 191 | A C100 四次拒绝，launch=0 |
| ab2 | 0 | 8-15,40-47,56-63,80-87 | 191 | A C100 第二次通过并启动；B C100 四次拒绝 |
| ab3 | 1 | 104-111,144-159,184-191 | 0 | A C100 四次拒绝，launch=0 |

固定 `--policy diagnostic --max-attempts 4 --retry-delay-seconds 5 --timeout-seconds 600`。
ab2/ab3 预先串接同配置 BA 命令，仅前序成功退出时执行；AB 均因 admission 耗尽退出 1，
所以 BA 未开始。总共 14 条 slot attempts，13 条启动前拒绝，1 条 C100 已启动；
C10000 launch=0。没有完整 captured.json 或 AB/BA summary，不调用 analyzer 拼接残缺证据。

ab1 每次 admission min idle 都为 0%，聚合 mean 为 59.523%..86.669%；ab3 每次
min idle 为 0%，mean 为 91.186%..93.143%，明确不满足 98%/95% 原门槛。
ab2/B 四次 mean/min 分别为 `98.711/80.667`、`98.562/94.684`、
`99.268/93.355`、`97.763/95.695`（百分比），均未同时通过两项门槛。

ab2/A C100 启动前 mean/min idle 为 `99.636%/97.333%`，功能、timing 和 runtime-config
检查通过：32 个后台 worker、32 lanes、legacy/push、预期 CPU/partition 对应关系，302 steps。
短 canary 的 Host 为 183 ms，仅作功能记录，不外推 C10000 性能；该入口未完成最终整组
staging 复核，因此不将一个 accepted canary 冒充完整 pair 身份/性能通过。

| attempts.jsonl | SHA-256 |
| --- | --- |
| ab1 | `68b39831b9eeac5ac41c22af5e2c0d8377330dd4aa285bb12ba0453042b5e0a6` |
| ab2 | `43a19874c79522dd9978110c737c7ac5cbc3c95114ab814a69ec5d9449dd3341` |
| ab3 | `4205ccb23470238f3c82889707946007548a634d3bfbba2490c08568ba180d57` |

全部已写 raw、attempts、log、perf、timing、page-placement 和 staging 保留；未覆盖历史结果。
扫描及 runner 进程均已返回，不存在本轮后台性能测量继续运行。

## 4. 测量问题复核及后续边界

本日对旧 AB/BA 再核查，发现两个相互独立的问题，详情已按只追加规则勘误到 TNO0294：

1. 原始 `/proc/stat busy - perf task-clock` 在不同 scheduler 上有正负方向偏差，旧单边门
   不能把全部残差解释成外来工作。继续保留原门，不重抽到 residual 偶然为负；本轮没有
   新长样本，因此也没有关于此问题的新 runtime 结论。
2. 全机 `/proc` 扫描先于 model 页/线程采样，实际采样间隔约 4 秒，使 10 秒左右 legacy
   容易只获得 2 个完整快照。上轮 BA/A 还存在真实 SMT guard 和 foreign task 污染。
   后续若独立实现采样解耦，须单独版本、测试、冻结和新 pair；不能改旧样本或降低 3 次要求。

本轮结论仅为资源阻断，legacy control 保留，不进入 pipeline-host、CCD 映射、pull、
通信校准的正式性能比较。恢复仍需同 NUMA 四个完整 CCD 的持续窗口；已向用户询问
能否协调允许节点中约 10 分钟独占资源，以及是否同意独立准备轻量 page/worker 采样新版本。
本轮尚未实现该新测量器，也没有停止或改动任何其它任务。
