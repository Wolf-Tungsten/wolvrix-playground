# TNO0368：重新生成 RTL 后的完整 32 线程流程结果

日期：2026-10-28。承接 [TNO0367](./TNO0367_grhsim_initial_km1_input_drift_20261028.md)。

## 范围与结果

按用户要求重新执行修正后的完整入口：当前 XiangShan Scala 生成 RTL → Verilog 前端 → 固定 memory mem-to-reg → 新六维超图 → 8 份并行初解 → km1 择优 → assignment replay → 完整 preset 发射 → 原始 O3/native 编译 → 32 线程功能与 walltime → 自动迁移提案、核算与排序 → 最终 emu。

流程正常退出，`result.json` 为 `status=pass, selected_seed=7, retained=initial, migration.accepted=false`。没有导入历史 JSON、HGR、assignment 或模型库，也没有加入中途历史身份/执行计划核验。memory 继续采用当前配置固定的三个目标及 row_limit=2；迁移端点由工具选择。

本轮独立输出为 `build/xs/grhsim32_fresh_rtl_20261028/`。RTL 生成确实执行，约用时 457 秒；本次读取该目录下新生成的 RTL。native 工具与求解器源码构建沿用普通依赖缓存，不把依赖缓存视作设计输入。

## 新超图及八份初解

新图含 **301,184 个 ASC、1,320,667 个 piece、584,259 条超边**，六维负载；执行计划为 55,810 个 group。该规模回到此前 counter-print 路线，取代上一轮旧 RTL 的 301,173 个 ASC / 589,150 条超边。这里报告规模，不将规模相同等同于全图逐字节一致的证明。

| seed | 完整 32 分区图 km1 | 容量可行 |
| --- | ---: | --- |
| 0 | 29,739,627 | 是 |
| 1 | 27,853,984 | 是 |
| 2 | 30,073,669 | 是 |
| 3 | 31,842,776 | 是 |
| 4 | 31,675,219 | 是 |
| 5 | 26,949,261 | 是 |
| 6 | 32,902,195 | 是 |
| 7 | **26,547,623** | 是 |

工具按完整图最低可行 km1 选择 seed 7，自动隔离一个超大 ASC。此次最低值回到并低于此前 27,912,141 的量级；求解为并行非确定性流程，不把数值差异全部归因于某一个输入修改，也不以 km1 直接断言 walltime 更快。

## 构建及运行

整条流程在 node030 执行；生成与编译开放全部 384 个可用逻辑核，8 份求解各使用一组 CPU。模型共 **7,877 个 C++ translation unit**，使用 Clang 23 的 `-std=c++20 -O3 -march=native -pthread`，保留 SLP；完成对象可执行段 64 字节对齐、按生成顺序归档及 Difftest harness 链接。

最终运行固定 CPU96–127、32 lanes（Host + 31 worker）、all-spin、preferred NUMA1、ASLR off、代码 THP。C100 smoke 与 8 次 C=100000 均通过 NEMU/功能检查。每次普通长测量的代码页覆盖均为 85,983,232 / 85,983,232 B。

| 普通运行 | 次数 | 进程 walltime 中位数 | Host 中位数 |
| --- | ---: | ---: | ---: |
| 完整生成后的初解测量 | 8 | **12.228265 s** | **12.126000 s** |
| 公开 Make 运行入口复测 | 8 | **12.533217 s** | **12.430500 s** |

两行来自不同时间窗口，不作配对改善计算。它们也没有与恢复版或旧 seed 1 做同窗 AB/BA，因此不声称超过历史最佳线。

## 自动迁移结论

两次 C=100000 cycle trace 采集完成，随后从本轮 raw 图重新提取工作/通信/后端形态账本。trace 中 eval exclusive margin 主要来自 p27、p5，其次 p0；分区编号只作为本轮结果，未写入配置。

工具自动提出并评估 **51 个候选**，严格通信预算下 `eligible_count=0`，因此没有迁移候选进入重建/编译或 AB/BA。本轮最终保留 seed 7 初解，未手工改来源、目的分区或放宽预算来选择迁移。

合计 18 次 C=100000（16 次普通运行、2 次诊断 trace）完成且功能通过；另有 3 次 C100 smoke，包括默认 launcher 的直接启动。诊断 trace 的 walltime 不进入上表。

## 入口和记录

默认 `build/xs/grhsim32` 现为指向本轮独立目录的链接。旧 RTL 那轮输出另存为 `build/xs/grhsim32_old_rtl_20261028/`，未删除。重新生成仍使用 `make xs_grhsim`；重跑当前产物使用 `make run_xs_repcut_grhsim`，运行核由本机默认选择，指定核号仅用于本次性能环境。

主要结果位于本轮目录：

- `selection.json`：八份初解与最终选择。
- `initial/runs/summary.json`：首次 8 次普通计时。
- `rerun-20261028-163403/summary.json`：公开入口复测。
- `migration/ranking.json`、`migration/result.json`：自动提案和未迁移原因。
- `result.json`、`emu`、`emu.bin`、`package`：最终结果及公开产物。

启动、完整日志、退出码及 launcher smoke 位于 `wolvrix/build/artifacts/grhsim32-fresh-rtl-rerun-20261028/`。使用方法见 [默认路线文档](../../docs/grhsim32.md)。本记录为工作树实现的本机结果，不表示代码已经提交或推送远端。

## 后续直接对照 2026-10-28

随后按用户要求完成恢复版与本轮 seed 7 的两轮 fresh AB/BA，16 对合计新线 walltime 慢 9.538%、0/16 获胜。详见 [TNO0369](./TNO0369_grhsim_fresh_seed7_vs_restored_20261028.md)。这项后续同窗比较取代跨窗口秒数推断。
