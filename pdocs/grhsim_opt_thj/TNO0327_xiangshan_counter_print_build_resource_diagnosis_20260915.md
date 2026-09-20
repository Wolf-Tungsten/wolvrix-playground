# TNO0327: XiangShan counter-print build resource diagnosis

日期：2026-09-15

状态：`BUILD PROGRESS; NOT HOST PERFORMANCE EVIDENCE`。

## 1. 构建环境与进度

接 [TNO0325](./TNO0325_xiangshan_counter_print_host_ab_ba_plan_20260915.md)。
两臂于北京时间13:17左右启动：A在node031，B在node039；均nice10、16核mask、
solver32线程、native构建jobs16/unit-jobs4。B在813.524s后完成全部模型编译与身份gate。
A的分区输出assignment SHA为
`ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589`，
复现旧closure-aware分法，但JSON回读明显偏慢。

13:34左右，只对本次A父进程778927、emit子进程779010及其已有线程执行taskset：
`112-119,152-159` → `32-39,48-55`。原mask多核被外部任务占用；新mask只是即时
更有空余容量的构建选择，并无独占保证。记录为
`build/asc_counter_host_20260915/A_v1/affinity-update.json`。
未移动其他用户/任务、未改变nice或修改系统全局设置。

## 2. 慢构建的直接观测

13:36:44–47 pidstat三秒均值：A emit进程user10.30%、system89.37%、wait0%、
minor fault29,355.81/s、major fault0/s；进程VmSwap=0，整机available约568GiB。
随后perf对该emit进程采样3s、49Hz，原始数据保留在
`A_v1/emit-slow.perf.data`（159 samples，lost0）。

栈包含`GraphBuilder::addValue → do_huge_pmd_anonymous_page →
__alloc_pages_direct_compact → compact_zone → migrate_pages → copy_page`。
这提供了大页分配触发直接内存整理的证据；不能把全部慢构建都归结为CPU竞争，
也不能据此推断仿真Host变慢。13:38:52已看到`emit split SV`，进程仍正常推进。
未改THP策略、无重新选分区或重试已启动性能样本。

## 3. 测量资源扫描

`build/asc_counter_host_20260915/scans/round03`复查node030/031无四CCD；
round04覆盖全部允许13个节点仍无四CCD；round05于13:35:41找到node030 NUMA0
`0-7,32-47,72-79`、monitor191，连续3×3s含siblings最差平均idle99.3545%、
最差单核97.6589%。该结果仅为瞬时候选，不是预约，实际测量仍需重新admission。

此文只记录构建/资源诊断。Host只取两臂完成构建后，在同一机器、同一组CPU上
按原协议AB/BA启动的仿真计时；不把构建耗时、perf采样或扫描当作性能结果。
