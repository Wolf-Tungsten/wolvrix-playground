# A0058 run-summary：r002 收口与 restart 建议（2026-08-21）

对应 `next` = `run-summary`（全部 2 条轨迹已达 L=8 步）。无评估开销。

## 做了什么

汇总 r002 全 run（台账 e00001–e00034、24 个 action、7 轮 round-summary），写
[runs/r002/summary.md](../runs/r002/summary.md)（分数曲线、机制族裁决、测量学
产出、restart 建议），更新 insights.md 与两处 README，随后 `action-done` +
`close-run` 收口。

## 量化结果

- 预算：候选 evals 32/32 恰好耗尽（总 34，含基线 e00001/e00002）；16/16 步走满；
  32 候选全部 ok，零 compile_timeout / 零 difftest_fail。
- 基线：AM y0 619.019s / gsim 46.792s（均慢态窗测量，ratio 全 run 不可裁，
  重锚待用户）；起跑差距名义 13.23x。
- ledger best e00007 261.543s 已 overturn（A0043 三重证据：安慰剂回读
  363.444 = 261.543×1.389 落双态带）。
- **真值 best：t0 tip 295.042s（快态簇锚）/ 301.081s（e00027 同窗确认
  -11.41%）；t1 best 322.762s（e00029 同窗确认 -5.69%）**。对 gsim ≈ 6.3-6.4x，
  目标未达成。

## 机制族裁决（详见 runs/r002/summary.md）

- 确认：scan-branch-hints（t0 -11.41% × t1 -5.69%，r002 最大单步）、task body
  outline 族（t1 -10.91% × t0 -5.91%，闭环关闭）、gsim-aligned 调度点
  （-16.4% × -8.44%，关闭）、wide-mux-chain-fuse（-2.19% × -1.17%，首个可定量
  迁移族、捕获率 ~46% 双侧一致）、concat-insert-inline 迁移（-6.26%）。
  **跨轨迹迁移三连中**；「前端流式主导、省指令无效」判据正向逆用三次成立。
- 证伪关闭：commit 相省指令/省往返/门控类整体（branchless +1.71%、row-merge
  +3.25%、fill-enable-gate +9.1%）；守卫门控；守卫布局；死宽态（新图池 0.46%）。
- 残余开放池：compute 长尾本体 ~52%（双侧）+ commit 相纯数据侧。

## 测量学结论

双态 ×1.3-1.4 抽签在 s08 批内直接检出（同批 rep 295.0/389.2/295.0s，混合
median 为 artifact）；连续漂移 ±5% 样本七点；跨窗读数一律不裁；同窗安慰剂
锚点连续六轮 2/4 席、产出全部裁决基准。提请用户：① rep 级簇分组裁决入
evaluator；② 基线重锚。

## restart 建议（裁决：建议 restart，待用户确认）

- y0 = t0 tip `79719b2d95b91da141c01c74814da25292c1170d`（emit_args = CLI
  默认调度点 + 12 旋钮 + scan-branch-hints）。
- C=2 / L=8 / K=2 维持，K 一席常态化锚点；分工 = 一轨 compute 长尾本体、一轨
  迁移验证 + commit 数据侧。
- 注意：config `restart.max=1` 已消耗，r003 需用户放宽 restart 预算；restart
  前先定基线重锚与簇分组裁决。

## 对下一步的建议

下一 action 预期 = 无（run 收口后 tesloop 停止，等用户裁决 restart）。若用户
批准：先重锚基线（evaluator run/gsim 各一次），再 `init-run --base-commit
79719b2d…`。
