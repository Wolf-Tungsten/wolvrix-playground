# run r001 总结（grhsim-am-coremark）

收口日期：2026-08-20。C=3, L=8, K=2，24/24 步全部走满，候选 evals 48/48 恰好耗尽
（另含基线 e00001/e00002，总计 50 eval）。base `a88e7a2`（分支 `tes/r001/base`）。

## 结果总览

- 基线（同协议 3-rep 中位）：AM y0 = **273.103s**（e00001，CV 0.39%）；
  gsim target = **24.688s**（e00002，CV 1.5%）；起跑差距 **11.06x**。
- **best_overall = 194.242s**（e00045，commit `9c0a89db94a3`，t0/main tip）：
  较 AM y0 **-28.89%**，仍为 gsim 的 **7.87x**，AM/gsim 绝对差距关闭 **31.75%**。
- 候选健康度：48 候选中 ok 44、compile_timeout 3（全部倒在 affinity 布局的
  init() 编译耦合，e00005/e00007/e00017）、difftest_fail 1（e00012 preset 摘除
  死锁）；全部 ok 候选 17/17 ctest + 3-rep nemu 逐指令 difftest 全过。

## 轨迹分数曲线（主线 winner 中位，秒）

| step | t0 | t1 | t2 |
|---|---|---|---|
| y0 | 273.103 | 273.103 | 273.103 |
| s01 | 271.095 (e00004) | 270.502 (e00006) | 272.743 (e00008) |
| s02 | 273.258 (e00010) | 289.151 (e00011)† | 269.731 (e00014) |
| s03 | **247.458 (e00015)** | **244.278 (e00018)** | 264.466 (e00019) |
| s04 | **230.568 (e00022)** | 241.348 (e00024) | 270.956 (e00025)† |
| s05 | 222.654 (e00027) | **230.447 (e00030)** | 265.250 (e00031)† |
| s06 | 216.481 (e00033) | 228.935 (e00035)† | 257.300 (e00037)† |
| s07 | **194.792 (e00040)** | 224.038 (e00041) | 255.105 (e00044)† |
| s08 | **194.242 (e00045)** | **218.976 (e00047)** | 254.533 (e00049) |

† = 机械 winner（step 内分数最优但相对前值回退或亚噪声，knob 默认 off 的语义中性
adoption；收益不继承）。

轨迹 best：t0 **194.242s**（-28.89%，gsim 7.87x）；t1 **218.976s**（-19.82%，
8.87x）；t2 **254.533s**（-6.80%，10.31x，机制上自 e00019 起 11 候选无干净同日
改善）。run best 曲线：273.1 → 270.5(r1) → 269.7(r2) → 244.3(r3) → 230.6(r4) →
222.7(r5) → 216.5(r6) → 194.8(r7) → 194.2(r8)。

## 机制族裁决（跨轨迹汇总）

**确认的一阶机制（restart y0 组合材料，按证据强度排序）**：

1. **C++ 适配层调用边界内联（窄标量 helper）——最强族，跨轨迹独立复证**：
   t1 e00018 -9.69% × t0 e00040 -10.02%（均同日干净）。slice/shift/signed 等
   5 个 helper 静态 ~53 万站、动态 22.5 亿次 outlined 调用移入生成头文件
   constexpr。判据（A0030）：内联收益由函数体形态决定而非调用次数——含循环
   多出口的 helper（commit detect、wide word helper）内联反而回退。
2. **Activity 扫描剪枝 × 定向 locality（t0 主线）**：source-part activity
   guard -9.44%（e00015）→ source-word 精确二级守卫 -6.83%（e00022）→
   叠加 wide first-touch -3.43%（e00027，可加性确认）。
3. **宽拼接 splice 内联（t0）**：单字退化 insert 内联 -2.78%（e00033）；
   残余三形 unroll -1.89% 弱正（e00039），helper 内联后复测 -0.28% 关闭（e00045）。
4. **常量/死态瘦身族（t1，收益与体积同向缩放，已收敛）**：常量读取内联 -1.20%
   （e00024）→ 常量 backing storage 消除 -4.52%（e00030）→ 死宽态消除 -2.78%
   （e00041，宽池 -65.7%/122MB）→ 死窄成员消除 -1.36%（e00047，2.68MB）。
5. **commit 侧（t2，弱且部分不可裁）**：guard-event-gating -1.10%（e00014，
   干净）；commit-input-gating 名义 -1.95%（e00019）但跨日读数、同日对照互相
   矛盾（-0.13% vs +2.52%），**不可裁，restart 不得依赖**。

**证伪关闭的轴（48 候选换来的否定结论，勿重开）**：chunk 尺寸（+2.2%）、宽态
炸开、resize 胶扩展、branchless activation（+6.9%，条件激活写承力）、preset
摘除（difftest 死锁，轮次语义承力）、commit 朝代门控/sparse 阈值/位图/producer
快照/读侧快照/动态白名单（7 变体全关）、wide helper 内联（emu_build 1757s 成长
极点）、wide-constant-rodata 运行时、窄态首触布局（+3.23%，id 序已与数据流对齐）、
热度加权布局（热度分布平坦，上限 ~1-2%）、divmod 内联（基线依赖反转）、
commit-detect 内联（+2.80%）、静态 affinity 运行时收益（≤ 噪声底不可裁）。

**编译杠杆（与运行时解耦的元收益，knob 默认 off 可叠加）**：init-zero-elision
（emu_build -56%~-68%）、wide-constant-rodata（-67%）、dead-wide（-68%）。
compile_s 从 ~1200s 降至 ~600s 量级，为后续 run 的编译门留足裕量。

**测量纪律刻度（r001 最重要的方法论产出）**：同夜漂移 <1%、跨日 ~2.6% >
协议 CV（~1%）；对照点不同日且名义差 <3% 的裁决一律存疑；弱正旋钮收益依赖
基线布局，基线变化可翻转符号，旧读数不可继承（divmod 先例）。同日安慰剂
（e00038/e00048）与同日锚点（e00049）应成为后续 run 的常态配置。

## restart 建议

**建议 restart**（config `restart.max=1, auto=false` → 需用户确认后由下一 goal
执行 `init-run --base-commit`）。理由：t0/t1 的最强机制族（适配层内联 ×
扫描剪枝 × 常量/死态瘦身）机制正交但从未组合；组合 y0 的可加收益预期
~-5~-8%（t1 族各层同日干净收益之和），是剩余最确定的收益；t2 的 commit 轴
已以动态证据关闭，搜索空间收敛清晰。

- **y0 候选 commit：`9c0a89db94a3c3e303c2b9daefc2a79fb609fbce`**（t0/main tip，
  best_overall；已含 branchy-mux、resize 胶消除、source-part/word guard、
  wide first-touch、concat-insert-inline、inline-scalar-helpers）。
- **组合材料**：在 y0 上叠加 t1 常量族四旋钮（`--inline-scalar-constants`、
  `--inline-scalar-constant-storage-elision`、`--dead-wide-storage-elision`、
  `--dead-narrow-storage-elision`，机制与 t0 链正交）；编译杠杆
  （`--init-zero-elision` / `--wide-constant-rodata` / affinity）默认 off 可叠加。
  e00019/affinity 的 t2 读数不可裁，不作为 y0 依据。
- **同日校准**：t0 tip 缺同日锚点（t1 侧 e00048、t2 侧 e00049 已备）——r002
  run-init 的 y0 基线测量天然覆盖，勿在 r001 尾巴补测。
- **建议新 C/L/K：C=2, L=8, K=2（N=32）**。r001 三轨迹中 t2 后 5 步无干净
  收益，轨迹多样性边际递减；新 run 一轨迹做组合验证+主线推进、一轨迹探索残余
  轴（轮次语义需边级消费者分析方可再触；helper 内联按函数体形态判据推广），
  K=2 中建议一席常态化为同日校准/安慰剂以维持测量纪律。
- 预算参考：r001 用 48 候选 eval / 6 天；C=2/L=8/K=2 约 32 eval，单 eval
  墙钟 ~1-2h（含编译，compile_s 已因消零杠杆减半）。
