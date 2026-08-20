# A0042 r002/t1/s03：task 体 outline（守卫密集块瘦身）确认 -10.91% + 同窗安慰剂锚定

- task: grhsim-am-coremark  run: r002  trajectory: t1  step: 3/8
- proposal: [r002-t1-s03.md](../proposals/r002-t1-s03.md)（Φ 选中 e00009、e00001）
- eval 预算：12/32 → 14/32

## 候选与结果

| cand | eval | 机制 | commit | Host 中位 | CV | 门 | compile_s | 裁决 |
|---|---|---|---|---|---|---|---|---|
| c1 | e00013 | `--task-body-outline`：无参 fwrite 冷体坍缩为共享 `task_write_const` helper + DPI String 输入免 per-site `std::string` 拷贝（默认 off 逐字节等价） | `b9a888c` | **375.670s** | 0.07% | 17/17 ctest、3 rep difftest 73580/49996 全过 | 702.1s | **winner** |
| c2 | e00014 | 同窗安慰剂：t1 tip 9d464f3 原样重测（emit_args 同 e00009），无机制变更 | `b30cdbf`（空） | 421.673s | 0.00% | 全过 | 777.6s | 锚点 |

同态对照：**c1 vs c2 = -10.91%**（375.670 vs 421.673，两批 CV≈0）。c2 落快态带
（~415-450s），把本窗锚定为快态；c1 读数低于 t1 tip 全部既有快态读数
（414.867/421.673）约 9.5-10.9%，双态翻转（×1.3-1.4）方向相反、无法吸收该差值
——机制收益确认，非抽签。越 5% 假设门。

## 假设与证伪条件（事先写下）

- c1：b116236 型守卫密集块的冷 task 体（TaskFormatter 构造/ostream 选择/per-site
  `std::string` 拷贝内联）支配块代码体积，i-cache 流式是其 12.63% 池的一阶成本；
  outline 后块代码降 ≥4x，Host 较同窗安慰剂降 ≥5%；<2% 证伪。→ **确认（-10.91%）**。
- c2：无机制假设（锚点席位，先例 A0031/e00048、A0041/e00012）。

## 静态效果实证（e00013 emit vs e00009 emit，同输入图）

- b116236 所在 TU（`grhsim_SimTop_blocks_56_part_2`）：源 143,284→119,313 行
  （9.40MB→7.42MB）；**.o text 3.56MB→0.89MB（-75.0%，4.0x）**，达 ≥4x 假设。
- `task_write_const(` 站点 5,937（其中该 TU 5,874）；TaskFormatter 内联站
  7,235→1,298（残余为带 append 参数的 fwrite，保持内联）；DPI String per-site
  `std::string` 拷贝 6,412→0。
- 全模型 blocks .o text 102.8MB→100.1MB（-2.6%）——收益集中在单块，与池分布一致。

## 机制分析

- recon-t1s02 画像中 b116236 为「同一 4096-bit 宽值的逐 bit extract 锥，~48
  cyc/atom，前端/i-cache 绑定」；本 action 反汇编量化该块 11 个 chunk 合计
  ~3MB 机器码，其中 chunk 7-10 各 ~16 万行反汇编、被 ~6.3k+6.3k 个守卫
  `$display`/`xs_assert_v2` task atom 占据（该块持有全模型 87.8% 的
  TaskFormatter 站点）。冷体内联使每次块执行都要流过 MB 级代码足迹；
  outline 后热路径只剩 fire 条件检查 + 冷调用。
- 本机制正是 A0041 关闭守卫门控轴后预言的唯一残余路线（「只剩 atom 代码瘦身
  一路」）在 t1 内嵌守卫池上的确认；与 t0 的 b90656/90657 整块守卫不同，
  b116236 是 compute 块内嵌 task atom，整块/run 门控不可用，瘦身是唯一入口。
- 未分离归因：fwrite outline 与 DPI String 免拷贝同属一个旋钮、一次评估，
  两子规则各命中 ~5.9k/6.4k 站，无法从本步拆出各自贡献。
- e00009（activity-summary-scan）量级维持不可裁：s02 窗 c1 快态/c2 慢态翻转
  可吸收其名义 -27.8%；本步安慰剂把 **t1 tip 快态带锚定为 414.867/421.673s
  双样本**（s03 首务达成），后续 t1 裁决以同窗锚点为准。

## 对 Φ 下一步的建议

- t1 tip 现为 `b9a888c`，t1 有效 emit_args = config 调度全参数 + resize-elision +
  inline-scalar-helpers + inline-scalar-constants + activity-summary-scan +
  **task-body-outline**（候选必须显式携带全链，`--emit-args` 是整体替换）。
- t1 recon 刷新：outline 后 b116236 的 per-atom 成本与池占比需重测
  （recon-t1s04，离线插桩）；若仍为一阶池，残余在 extract+加法树锥本体
  （宽值 word 本地化/树形变换方向），设计前先看新 per-atom 读数。
- commit 巨块池 29%（b119387 寄存器堆写口阵列）保持 t0 证据下的数据侧 miss
  主导定性，「省指令」轴不 reopen；读数继续只信同窗锚点。
- 双态环境纪律延续：每 step 保留一席锚点/安慰剂；>15% 名义单步收益必须同窗
  corroborate（A0041 教训）；本步 -10.91% 由同窗安慰剂原生 corroborate。
