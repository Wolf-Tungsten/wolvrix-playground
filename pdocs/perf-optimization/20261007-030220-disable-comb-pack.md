# 20261007-030220 关闭 comb-pack（默认 no-comb-pack）

## 元信息

- 日期：2026-10-07 / 作者：kimi
- wolvrix commit：`6bcf731`（未变）/ 根仓 commit：`7c459df` + 本项改动
  （`scripts/wolvrix_xs_grhsim_ir.py`、`Makefile`）
- 上游基线记录：`20261007-011318-gsim-vs-grhsim-ir-100k-coremark.md`
  （同日登记的 packed 默认 112.06s 即为本次对照基线）

## 基线性能

- 口径：100k CoreMark 周期、`run_xs_wolf_grhsim_ir_emu`、difftest 开、
  taskset -c 4、3 次（详见上游记录；非 benchmark_grhsim_ir 页缓存逐出口径）。
- 数据（packed 默认）：均值 **112.06 ± 0.76s**（111.423 / 111.841 / 112.905），
  日志 `build/logs/xs/xs_wolf_grhsim_cmp100k_ir_{1,2,3}.log`。

## 优化方案

- 动机：`grhsim.comb-pack`（`wolvrix/lib/grhsim/pass/comb_pack.cpp`，把 4–16 条
  同构组合 lane 打包成 32–1024 位宽逐点逻辑）是静态体积导向优化，在
  数据门控活动驱动架构下方向相反：
  1. **活性合并**：N 条 lane 共享一个宽字，任一 lane 翻转即整字变化、
     compare-store 发布、全部消费者点火重算所有 lane——N 条独立活性轨道
     被焊成一条；
  2. **边界放大**：打包字多生产者聚合 + 大扇出 + 大位宽，更容易成为
     boundary value（compare-store 的单价随宽度上涨）；
  3. **打包/解包是净增功**：pack 的 concat/shift/or 与消费端 slice/mask
     是真实 op，而省下的按位 ALU 功在 64 位字/`_BitInt` 原生宽值下本就免费。
- 假设：关掉 comb-pack 会（a）减少 boundary fields 与发布站点，
  （b）恢复 lane 级活性局部性，（c）静态 op 数上升但动态功下降。
- 改动点（纯配置，不动 pass 本体）：
  - `scripts/wolvrix_xs_grhsim_ir.py`：`--comb-pack` 默认 True → False；
  - `Makefile`：`XS_WOLF_GRHSIM_IR_COMB_PACK ?= 0`，发射命令改为双向显式
    （`=1` 传 `--comb-pack`，否则 `--no-comb-pack`）。
- 风险与回退：语义零风险（packing 是等价变换，解开亦为等价变换）；
  回退 = `XS_WOLF_GRHSIM_IR_COMB_PACK=1`。
- 注意：hdlbits IR 管线（`wolvrix_hdlbits_grhsim.py`）本就不含 comb-pack，
  故 hdlbits 系门槛对本改动不敏感；敏感面是 XS 全流程与 xs-bugcase。

## 结果性能

同口径 3 次（构建于 `build/xs/grhsim-ir-nopack`，试验后已合并为生产默认）：

| 轮次 | packed（基线） | nopack |
|---|---|---|
| 1 | 111.423s | 104.783s |
| 2 | 111.841s | 106.695s |
| 3 | 112.905s | 107.710s |
| 均值 | 112.06s | **105.73s（-5.7%）** |

结构侧（emit 日志对照）：

| 指标 | packed | nopack | 变化 |
|---|---|---|---|
| boundary_fields | 903,370 | 845,231 | -6.4% |
| boundary_value_targets（merge 时） | 2,017,144 | 1,994,233 | -1.1% |
| 超节点数 | 36,386 | 34,256 | -5.9% |
| 每超节点行数 p50 / mean | 144 / 251 | 136 / 250 | 基本不变 |
| TU 数 | 1084 | 1043 | -3.8% |

假设 (a)(c) 成立；粒度假设不成立（超节点大小纹丝不动，comb-pack 不影响
划分形状，只影响边界宽度与活性传播——已排除"靠关 comb-pack 细化粒度"路线）。

- 对 gsim（SN=15，47.06s）的差距：2.38× → **2.25×**。
- 编译：nopack emit+全量编译（-j32）合计 30.5 min，与 packed（28.5 min）同级。

## 正确性门槛（全绿）

1. `make test_wolvrix`：54/57，失败恰为既有基线三项
   （transform-comb-lane-pack / transform-repcut / ingest-write-back-slice
   SEGFAULT），无新增；
2. `make run_all_hdlbits_grhsim_ir_tests`：162/162；
3. `make run_xs_bugcase_grhsim`：25/25；
4. XS 完整 CoreMark + NEMU difftest：`HIT GOOD TRAP` @ pc 0x80001ca0，
   逐拍轨迹 instrCnt=663,688 / cycleCnt=297,291 与黄金一致，
   宿主 311.3s（日志 `build/logs/xs/xs_wolf_grhsim_nopack_full.log`）；
5. `check_sim_refactor_baseline`：**黄金因前序 ptmp 清失而当众重捕**
   （`make capture_sim_refactor_baseline` + check，162 DUT 全匹配；
   注意重捕后黄金出自当前代码，本项校验的是确定性与自洽，
   不再是对 refactor 前旧黄金的回归）。

## 结论

**采纳**：comb-pack 默认关闭。教训记录在案：本条流水线上的 pass 应以
动态激活功而非静态 op 数评判；凡以牺牲活性粒度换静态体积的优化，
在数据门控架构下均为负优化。
