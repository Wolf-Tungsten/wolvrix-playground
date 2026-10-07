# 20261007-040954 reg-to-mem 关断试验（负结果，不采纳）

> 性质：**负结果登记**。回答"reg-to-mem 能不能像 comb-pack 一样关掉"——不能，
> 它是承重墙。未改任何代码/默认值。

## 元信息

- 日期：2026-10-07 / 作者：kimi
- wolvrix commit：`6bcf731` / 根仓 commit：`7c459df` + comb-pack 默认关
  （`20261007-030220-disable-comb-pack.md`）
- 对照基线：同日 `20261007-030220` 记录的 nopack 默认 105.73s

## 试验设置

- 变体：`--disable-reg-to-mem`（`XS_WOLF_GRHSIM_IR_REG_TO_MEM=0`，
  comb-pack 保持关），产物 `build/xs/grhsim-ir-nomem/`（试验后已删，
  发射日志 `build/logs/xs/xs_wolf_grhsim_ir_20261007_032809.log`）。
- 测速口径：同 `20261007-011318`（100k CoreMark、difftest 开、taskset -c 4、3 次）。

## 数据

| 轮次 | reg-to-mem on（基线） | off |
|---|---|---|
| 1 | 104.783s | 150.253s |
| 2 | 106.695s | 149.432s |
| 3 | 107.710s | 147.565s |
| 均值 | 105.73s | **149.08s（+41.0%）** |

正确性：三轮终点 instrCnt=240,349 / cycleCnt=99,996 与黄金一致（difftest 开）。

结构侧（off vs on）：

| 指标 | on | off | 变化 |
|---|---|---|---|
| phase_general ops | 3,587,132 | 3,962,973 | +10.5% |
| P_mem ops | 22,553 | 4,006 | 大数组回流 General |
| reg_latch_fields | 104,633 | 186,370 | +78% |
| sink_ops | 128,338 | 197,250 | +54% |
| boundary_fields | 845,231 | 1,034,660 | **+22.4%** |
| 超节点数（nonsink） | 32,159 | 36,572 | +13.7% |
| TU 数 | 1043 | 1165 | +11.7% |

## 结论与机理

**不采纳，reg-to-mem 保持默认开。** 方向与 comb-pack 恰好相反：

- comb-pack 合并**计算**的活性轨道（有害）；reg-to-mem 把大数组**状态**从
  regLatch 双缓冲挪到 P_mem 原位提交（有益）。关掉后数组回到 regLatchStore：
  sink_ops +54%、boundary_fields +22%、reg_latch_fields +78%——每次数组写
  都变成 P_general 的 sink 写 + 整行/整组参与边界发布，activation footprint
  随数组规模放大。
- 判别原则不变：牺牲活性粒度/放大活性足迹换静态体积的，是负优化
  （comb-pack）；把大块状态的提交移出活动图、缩小活性足迹的，是正优化
  （reg-to-mem）。
