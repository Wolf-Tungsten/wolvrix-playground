# ST00000 baseline（根节点）

- 父节点：-
- 状态：trunk
- 代码状态：wolvrix @ `e7d0828`（2026-07-25，`feat(grhsim-am): wire XiangShan GRHSIM-AM emit and emu flow`）
- 创建日期：2026-07-25

## 假设

树搜索起点。以当前默认配置的 grhsim AM 为 baseline，所有优化节点相对此节点或其后代测量增量收益。

## 测量

基准：XiangShan CoreMark 50k（coremark-2-iteration.bin，difftest 开启），`setarch -R` 固定 ASLR + `taskset -c 7` 绑核，机器 corvus01。

| 指标 | grhsim AM | gsim | ratio |
| --- | --- | --- | --- |
| 50k 运行时间 | 4,191,014 ms | 31,932 ms（3 次中位数） | **131.2x** |

正式 baseline（2026-07-25 19:16 重测）：

- gsim × 3：32,285 / 31,726 / 31,932 ms，中位数 31,932 ms，离散 ~1.8%（噪声带 <2%，支持 README 的 ≥2% 有效阈值）；使用 2026-07-13 构建的 gsim baseline emu。
- AM × 1：4,191,014 ms（~69.9 min），使用 2026-07-25 11:50 构建的 AM emu。
- 功能校验：AM instrCnt=73,580 / IPC=1.471718，gsim instrCnt=73,584 / IPC=1.471739，difftest 通过，与历史口径一致。
- 旁证：与 provisional 值（routecheck 4,164,382 ms）偏差 <1%，环境结论一致。

### 历史数据存档（2026-07-25 调查，已被上方正式测量取代）

- AM provisional 来自当日 routecheck 单次运行（4,164,382 ms），无 taskset / fixed-ASLR。
- gsim provisional 来自 2026-07-13 成对重测（33.84s / 33.92s）。
- 同日 routecheck 的 legacy grhsim 为 166,271 ms，与 07-13 的 158.4s 基本吻合。

## 结论

根节点，无结论。2026-07-12 之前的 grhsim 实验历史归档于 `pdocs/grhsim_opt/`（独立体系，本文档不以其为依据）。

## 子节点候选

首批候选已写入 `../TREE.md` 候选池（ST00001–ST00006，2026-07-25），来源：IN-20260725-01/02 + [AN00001](../analysis/AN00001_am_vs_legacy_structure_gap_20260725.md) 结构差距分析。

---

## 节点模板（后续节点复制此节）

```
# STxxxxx 标题

- 父节点：STyyyyy
- 状态：open / in-progress / trunk / branch-alive / pruned-* / parked
- 代码状态：分支 / commit / emit 配置
- 创建日期：YYYY-MM-DD

## 假设
（为什么认为有效，引用 profile 或 INBOX 条目）

## 改动
（代码位置、要点；大段调查/分析数据放 `../analysis/ANxxxxx` 文档并链接）

## 测量
（50k 中位数、vs 父节点增量、vs gsim ratio、环境）

## 结论
（接受 / 剪枝 + 理由；剪枝原因必须写清）

## 子节点候选
（本次暴露的新机会）
```
