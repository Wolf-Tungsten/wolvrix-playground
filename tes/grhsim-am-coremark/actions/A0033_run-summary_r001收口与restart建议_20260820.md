# A0033 run-summary r001 — run 收口与 restart 建议

日期：2026-08-20。action 类型 run-summary（无评估开销）。触发条件：三轨迹 8/8
全部走满、候选 evals 48/48 恰好耗尽（`next` 裁决 run-summary）。

## 做了什么

- 汇总全 run 50 条 eval 记录（48 候选 + 2 基线），写
  [`../runs/r001/summary.md`](../runs/r001/summary.md)：各轨迹分数曲线、
  best_overall、vs 基线差距、机制族裁决、restart 建议。
- insights.md 追加 run 级结论；任务 README 速览与 tes/README.md 索引更新；
  `close-run` 收口 r001（status=completed）。

## 量化结果（run 级）

- 基线：AM y0 273.103s（e00001）/ gsim 24.688s（e00002），起跑差距 11.06x。
- **best_overall = 194.242s**（e00045，commit `9c0a89db94a3`，t0/main tip）：
  较 AM y0 **-28.89%**，仍为 gsim **7.87x**，AM/gsim 绝对差距关闭 **31.75%**。
- 轨迹 best：t0 194.242s（-28.89%）/ t1 218.976s（-19.82%）/ t2 254.533s
  （-6.80%）。run best 曲线：273.1 → 270.5 → 269.7 → 244.3 → 230.6 → 222.7 →
  216.5 → 194.8 → 194.2（秒）。
- 候选健康度：ok 44 / compile_timeout 3（均为 affinity×init() 编译耦合）/
  difftest_fail 1（preset 摘除死锁）；全部 ok 候选 17/17 ctest + 3-rep
  difftest 全过。

## 机制分析（run 级收敛）

- 最强机制族 = **C++ 适配层调用边界内联**（t1 e00018 -9.69% × t0 e00040
  -10.02%，跨轨迹独立复证）+ **activity 扫描剪枝 × wide first-touch**
  （-9.44%/-6.83%/-3.43% 可加链，t0）+ **常量/死态瘦身族**（t1，-1.20%/
  -4.52%/-2.78%/-1.36%，与体积同向缩放后收敛）。三族机制正交、从未组合。
- t2 commit 轴 7 变体以动态证据全关；e00019 名义 -1.95% 与 affinity 收益
  在协议分辨率下不可裁（两轮同日实验互相矛盾），不作 restart 依据。
- 方法论产出：同夜漂移 <1%、跨日 ~2.6% > 协议 CV；弱正旋钮收益依赖基线
  布局、旧读数不可继承；同日安慰剂/锚点应常态化。编译杠杆（init 消零 /
  wide-constant-rodata / dead-wide）使 compile_s ~1200s→~600s。

## 裁决：restart 建议

**建议 restart**（auto=false，需用户确认）。y0 候选 commit =
`9c0a89db94a3c3e303c2b9daefc2a79fb609fbce`（t0/main tip），叠加 t1 常量族
四旋钮（机制正交，预期可加 ~-5~-8%）；建议新 C/L/K = 2/8/2（N=32），K=2
中一席常态化同日校准。t0 tip 同日锚点缺失由 r002 run-init 基线测量天然覆盖。
详见 runs/r001/summary.md「restart 建议」。

## 对下一步的建议

- 用户确认 restart 后，下一 goal 执行
  `python3 tes/tools/tesctl.py --task grhsim-am-coremark init-run --base-commit 9c0a89db94a3c3e303c2b9daefc2a79fb609fbce`
  （如需覆盖 C/L/K 加 `--C 2 --L 8 --K 2`）。
- 若不 restart：r001 已收口，wolvrix 侧 `tes/r001/t0/main`（194.2s 配置）可作
  为 emit 优化成果合入开发主线的候选（属用户开发决策，tes 不动）。
