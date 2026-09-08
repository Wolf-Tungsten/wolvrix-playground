# TNO0285: XiangShan RepCut N=K=32 communication refinement tool gate

日期：2026-09-07

状态：`ISOLATED TOOLS AND SMALL TESTS PASS; FULL CONTROL REPRODUCTION RUNNING; NO CALIBRATED CANDIDATE YET`。

前置：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)、
[TNO0282](./TNO0282_xiangshan_repcut_nk32_measurement_protocol_gate_20260907.md)。

## 1. 隔离导入与快照

公开 RepCut options 没有 assignment 导入/完整 occupancy 导出入口，既有 HGR/stats
不足以复原每个 ASC 的 exact closure。因此在 `build/repcut_nk32_opt_20260907/stage4_analysis/`
生成独立 repcut.cpp 副本，只增加实验环境变量控制的导入/导出，不写生产源或公共 ABI。

复用 `wolvrix/build/skbuild-repcut-weight-mode` 的其余库对象；其原库与当前 installed 库
Build ID 均为 `0e55dd9101dd9abc908f867bd41ed752dc06dfad`。只重编一个 repcut 对象并隔离链接，
入口通过 `/proc/self/maps` 验证确实加载实验库。生产 Python 安装和库不覆盖。

最终 `overlay-v1/libwolvrix-lib.so` SHA：
`6ab4b9b7d9ea7b13d677daf6d44c1d7df7b6ac119a7c0b6ac178b204827cc782`。
`run_stage4.py` SHA：`22156fc656ad34b90733dfa11aadbdb5cf573ea333d50e0fcad8523b421c528e`。
构建中保留首次 PATH 缺 ld.lld 的链接失败，随后恢复原 LLVM PATH；另修正 Ninja shell
转 argv 时 $ORIGIN 的多余转义并仅重新链接。最终库上 7 项真实小图测试重新全部通过。

入口先核验 GRH/assignment SHA，导入时严格检查记录数与 partition ID，跳过 backend
和旧 compute-first refiner。输出小端二进制 CSR、piece nonempty、计算权重、ASC closure、
piece->partition occupancy，以及六项原始 PieceCommStats。空 piece 的 incidence 可以保留，
但 exact load/occupancy 统计必须跳过它，不能把其占位权重计入计算。

7 项集成测试覆盖真实导入、两 arm 单次原图 load、跳过求解/旧后处理、package/flat-SV
逐文件复现、错误库/hash，以及六类非法 assignment。证据 `stage4_analysis/tests-gs6jr7l1/`。
完整 XiangShan control-only 导出已在 node029 启动，独立结果另记，不将小图门当作完整图门。

## 2. 通信校准的单位与限制

`measurement/calibrate_communication.py` 读取完整复核的选定 AB/BA summary，按真实
生成端点及所选 push/pull owner 拟合非负 count + words64 两特征；保留顶层输出拷贝。
12 项单元测试通过。输出训练/留一误差、关键 owner 误差、共线性、两序差异及系数范围。
未通过预定可靠性门时，不导出可用系数；尚未选定 runtime，所以本篇没有真实拟合结果。

必须区分：wrapper 统计为打包后、每个目标的 copy_count；PieceCommStats 的
outSignalCount 是未打包结果，outWords 为 ceil(width/64)，不是 mapping 的 words32。
即使 owner 拟合通过，直接用于 piece 的 packing/fanout 转移也仍是未验证的代理假设，
不是物理带宽、总线流量或精确通信时间。候选必须重新 emit 后核对实际端点并独立实测。

## 3. 外部 whole-ASC 后处理

`refinement/refine_assignment.cpp` 与身份门 `run_refinement.py` 读取导出的快照和通过
owner 校准门的系数，使用 `signal_coeff*outSignalCount + word_coeff*outWords64` 为
piece 通信代价代理；目标为该代价的 KM1，即每 piece 的 `(所触及partition数-1)*代价`。

冻结起始 assignment，不重跑随机求解。按可从源分区移除的通信代理代价排序，每轮
最多 4096 个 ASC 候选，枚举 32 个目的分区；最多 4 轮/64 moves。每次移动必须严格
降低通信代理，随后才按降序计算负载向量/总量打破平局。

硬约束：最大 exact 计算量不超过起始值、复制 load sum 不超过起始值 1%、大于 nominal
target 的 ASC 固定且其 owner 不接收新增计算、不产生空分区。不拆 ASC。最后全量重算
loads/KM1 与增量 occupancy 交叉核验；wrapper 再与导入快照起始指标核验，记录所有输入 SHA。

14 项测试通过，包含通信下降、giant 固定、空 piece、closure 重算、错误 CSR/ID/系数、
输出不覆盖及拒绝不可靠校准。尚未在完整图上生成通信候选；没有静态或性能收益结论。
