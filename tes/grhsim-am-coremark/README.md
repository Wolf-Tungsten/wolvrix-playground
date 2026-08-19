# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（3-rep 中位、绑核、串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- 活跃 run：**r001**（C=3, L=8, K=2，N=48；base `a88e7a2`）
- 基线（2026-08-14，同协议 3-rep 中位）：AM y0 = **273.1s**（e00001，CV 0.39%）；
  gsim target = **24.7s**（e00002，CV 1.5%）；**差距 11.06x**
- 当前 best：**216.5s**（e00033，word guard + wide first-touch + concat-insert
  inline，较 AM y0 **-20.73%**）；仍为 gsim 的 **8.77x**，AM/gsim 绝对差距关闭
  22.76%；t0/t1/t2 步进 **6/6/6**，evals **38/48**
- t2/s06（A0024）：c1 前置离线量化以静态证据关闭 commit 内锥读侧快照形态
  （读侧校准下也仅覆盖 e00019 保护面的 ~2%，低于 3% 门槛，未进正式评估）；
  c1 改为 affinity+init 消零+commit 门控组合，e00037 中位 **257.3s**（CV
  1.0%）；c2 `--tree-atom-fold-max-instr 8` 在 node-aligned 调度下惰性，
  e00038 与 e00019 代码逐字节一致，成为意外安慰剂——**同代码跨日漂移
  ~2.6%**（264.5s→257.6s），e00037 的名义 -2.71% 实为漂移，同日对照仅
  **-0.13%**（组合亚噪声中性）。e00037 按 0.13% 噪声级机械 winner 入
  t2/main（此后携带 init 消零+affinity：运行时中性，emu_build 845s→296s）。
  纪律新刻度：对照点不同日且名义差 <3% 的裁决一律存疑
- t1/s06（A0023）：c1 `--inline-wide-helpers` 将六个宽 word helper（~23.5 万
  静态站点）移入生成头文件内联，e00035 中位 **228.9s**（较 e00030 **-0.66%，
  CV 0.41%**）未达 3% 门——宽值层调用边界非一阶（e00018 收益定位在窄标量层），
  且 emu_build 恶化 697.5→1757.5s（b38653 单 TU ~28min），轴关闭；c2
  `--wide-constant-rodata` 迁移 25,654 个宽常量（1.64M words，池 -6.77%，
  init() 宽 store 1.66M→19K 行）为 **232.9s（+1.06%，CV 1.16%）** 小幅回退，
  运行时轴关闭，但 emu_build **-67%**（697.5→230.0s）兑现编译杠杆（knob 默认
  off，可作未来编译门减压选项）。两候选均 17/17 ctest、3 rep difftest 全过；
  c1 按 step 内分数机械 winner 入 t1/main（t1 best 228.9s）
- t0/s06（A0022）：c1 `--concat-insert-inline` 将单字退化拼接从 outlined
  `insert_words`/`replace_window_words` 调用改为内联 splice（满字对齐退化为
  直接 word store、全 store 时消除死 `zero_words` 前导），消除 9.59 亿次动态
  调用边界，e00033 中位 **216.5s**（较 e00027 **-2.78%，CV 0.35%**），成为
  winner 与新 run best；c2 `--narrow-storage-first-touch` 把窄成员按首触排序
  （span -27.8%、pages -14.9%）反而 **+3.23%**（CV 1.20%）且 emu_build 恶化
  282s→964.5s——窄态 id 序已与数据流局部性对齐，窄态布局轴关闭。两候选均
  17/17 ctest、3 rep difftest 全过
- 第 5 轮小结（A0021）：run best 本轮再降 **3.43%** 至 222.654s，满足 >=3%
  继续条件，不调整 C/L/K、不提前 restart。t0 确认 word guard + first-touch
  可加（activity 剪枝 x 定向 locality 为最强叠加轴）；t1 常量 backing storage
  消除 -4.52% 为本轮最大单步（常量生命周期 read->storage 各层独立可收）；
  t2 commit-input 静态细化四连未改善 e00019、全部关闭。t0/t1 经正交机制收敛到
  222.7s vs 230.4s，是 restart 组合材料；下一 action 为 `r001/t0/s06`
- t2/s05（A0020）：c1 `--commit-input-packed-dirty` 将 2,922 个 commit-gate
  dirty flag 压为 46 个 `uint64_t` word，e00031 中位 **265.3s**（较 t2 best
  e00019 **+0.30%，CV 1.43%**）；c2 `--commit-input-producer-change` 为 20,476
  producer block 加输出快照后为 **285.6s**（较 e00019 **+7.98%，CV 0.33%**）。
  两候选均 17/17 ctest、3 rep difftest 全过且通过编译门；c1 按 step 内分数机械
  winner 入 t2/main，但 t2 best 仍为 e00019，commit-input 的位图压缩/producer
  快照细化均未证明正收益。
- t0/s05（A0018）：c1 将 e00022 的精确 source-word guard 与
  `--wide-storage-first-touch` 正式组合，e00027 中位 **222.7s**（较 e00022
  **-3.43%，CV 0.22%**），成为 winner 与新 run best；c2
  `--source-word-activity-snapshot` 保持 activity relay 语义但为 **235.6s**
  （较 e00022 **+2.19%，CV 0.87%**），证伪“局部 word snapshot 可减少热路径
  成本”。两候选均 17/17 ctest、3 rep difftest 全过，compile_s=606.3/507.6s
- t1/s05（A0019）：c1 `--inline-scalar-divmod-helpers` 将窄标量除法/取模
  helper 放入生成 header，e00029 中位 **237.4s**（vs e00024 **-1.64%，CV
  0.09%**）；c2 `--inline-scalar-constant-storage-elision` 在常量字面量内联后
  删除安全 `v<K>` backing storage 与 init store，e00030 中位 **230.4s**（vs
  e00024 **-4.52%，CV 1.12%**），成为 t1 winner。两候选均 17/17 ctest、3 rep
  difftest 全过，compile_s=1039.3/1032.7s；t1 best 已入 `tes/r001/t1/main`
- t0/s04（A0014）：c2 在 e00015 source-part guard 内按 64-block activity word
  增加精确二级守卫，1,637 个 guard 覆盖 334 个 source 文件，230.6s（vs e00015
  **-6.83%，CV 0.66%**），成为 winner 与新 run best；c1 叠加 wide first-touch
  也取得 239.4s（**-3.27%，CV 0.27%**），确认扫描剪枝与状态 locality 可加。
  两者均 17/17 ctest、3 rep difftest 全过；evaluator 同步改为从现有本地 clone
  复用 FetchContent 依赖并共享 ccache，全新 wbuild 离线 configure 约 4.4-4.5s
- t1/s04（A0015）：c2 `--inline-scalar-constants` 将不可写、<=64 bit 的常量
  读取内联为掩码字面量，e00024 中位 **241.3s**（vs e00018 **-1.20%，CV
  1.49%**），17/17 ctest 与 3 rep difftest 全过，成为 t1 winner；c1 扩展
  signed/unsigned 同宽 resize 胶后回退至 256.4s（**+4.97%**）。两候选均在
  2400s 编译门内；e00024 为稳定弱正但未达 3% 一阶门，run best 仍为 e00022
- t2/s04（A0016）：c1 `--commit-input-sparse` 的全局 dirty-edge 阈值拒绝全部
  2,922 个 commit gate，e00025 为 **271.0s**（较 e00019 **+2.45%**）；c2
  `--wide-state-explode` 将传播边从 240,198 降至 87,298，但 e00026 为
  **271.3s**（**+2.58%**）。两者 17/17 ctest、3 rep difftest 全过，均为回退；
  TES 按 step 内规则将 e00025 合入 t2/main，但 t2 best 仍是 e00019。第 4 轮跨轨迹
  小结已完成，下一 action 为 `r001/t0/s05`
- 第 3 轮小结（A0013）：首次出现重复的一阶适配层收益——source-part activity
  guard **-9.44%**、selective scalar helper inline **-9.69%**；wide first-touch
  **-5.79%** 进一步确认访问顺序驱动的状态 locality。静态全局 affinity 仅
  -1.66%，commit input gate 即使覆盖 91.9% 写站也仅 -1.95%，后续分别转向
  定向布局与动态净收益稀疏化。e00018 compile_s=2006.3s，只余 393.7s 编译门
  裕量，运行时与编译复杂度必须作为双目标；本轮满足 >=3% 继续条件，暂不提前
  restart 或调整 C/L/K
- t2/s03（A0012）：winner c1 `--commit-input-gating` 覆盖 2,922/2,973 个
  commit 块与 91.9% 写站，以 dirty 传播跳过稳定 next 锥，264.5s（vs t2 tip
  **-1.95%，CV 0.74%**）；未达 3% 目标，240,198 条传播边的 store 是主要
  抵消项，已入 t2/main。c2 `affinity + init-zero-elision` 消除 1.78M 个 init
  zero store，把全流水线编译压到 1036.1s 并首次取得 affinity 运行时读数：
  265.2s（**-1.66%，CV 1.20%**），低于 2% 阈值但为弱正；两者 17/17 ctest
  与全部 difftest 全过，中位仅差 0.29%，机械 winner 不代表显著机制差异
- t1/s03（A0011）：winner c2 `--inline-scalar-helpers` 将窄标量 slice/
  移位/signed helper 改为生成 header 内 `constexpr`，244.3s（vs t1 tip
  **-9.69%，CV 1.62%**），3 rep difftest 与 17/17 ctest 全过；至少
  531K 个静态调用站点暴露了跨 TU helper 边界的一阶成本，c2 已入
  t1/main 并刷新 run best。c1 `stateLayout=affinity` 已修正宽 init store
  物理顺序，但正式流水线仍于 2399.1s compile_timeout，无运行时证据
- t0/s03（A0010）：两个候选均越过第 3 轮 3% 门。winner c1
  `--source-part-activity-guard` 247.5s（vs e00010 **-9.44%，CV 0.82%**），
  334 个静态 part 调用以精确 64-bit activity 区间预检，静默时跳过调用与逐 byte
  扫描；c2 `--wide-storage-first-touch` 257.4s（**-5.79%，CV 1.15%**），
  将 Block-touched 宽态跨度压缩 65.66%、page 减少 7.69%，首次确认布局 locality
  是有效运行时轴。两者 ctest 17/17、3 rep difftest 全过；c1 已入 t0/main
- 第 2 轮小结（A0009）：6 候选仍无 ≥5% 一阶收益；t0 弱正组合回到 y0、
  t1 激活恒写 +6.9% 且 preset 摘除 difftest 死锁，粗粒度机械路线关闭；
  t2 守卫事件门控 -1.10% 为唯一干净收益。commit 写站 7.32G compare/
  97.35% idle 是唯一动态大数锚点，但朝代门控仅覆盖 6%，正确形态指向
  commit 内锥状态输入快照检测。第 3 轮候选须先有离线覆盖/成本模型且
  目标 ≥3%，否则不再消耗正式 eval
- t2/s02（A0008）：commit 写站空转实测坐实（`--commit-station-stats` 离线
  插桩：7.32G compares、idle 97.35%）但朝代门控证伪——静态覆盖仅 6%
  （其余写站 next 锥在 commit 块内部），协议中位 +13.5%（噪声日 CV 41.7%，
  rep5≈基线，机制≈中性），路线关闭，正确机制指向 commit 内锥状态输入
  快照检测；**winner c2 `--guard-event-gating` 269.7s（-1.10%，CV 0.88%
  干净窗口）——纯 fatal/fwrite 守卫块（b83400+b26518）按 changedResults_
  事件槽整块门控，negedge 半数触发消除，已入 t2/main**
- t1/s02（A0007）：块间机械首轮触探双证伪——`--branchless-activation` 289.2s
  （+6.9%，条件激活写承力、轴关闭）；`--am-skip-preset-activation` difftest
  死锁（preset→act.b 双激活承力）；winner e00011 机械入 t1/main（语义中性：
  默认 off 开关，emit 不携带即逐字节等价，回退不继承）
- t0/s02（A0006）：`--init-zero-elision` 元杠杆落地（init() 1.82M→4.2 万行，
  runtime.o 572s→14.7s，emu_build -56%，运行时中性）——布局轴前置已备
  （分支 tes/r001/t0/s02-c1 常备）；弱正组合 273.3s 可加性证伪（~1% 级微调
  路线到头）；winner e00010 机械入 t0/main；evaluator parser 修复一处
- t2/s01（A0004）：亲和布局+init修复 再遭 compile_timeout（炸弹是 init()
  182 万行死 store 流本身，98.2% 宽池 store 为字面量 0——方向升级为
  `--init-zero-elision`）；宽态炸开 272.7s 持平证伪（ABTB 族命中但 NO0018
  已吸收其成本，轴关闭）；t2/main 噪声级 adopted c2（+0.13% < CV）
- t1/s01 双攻坚（A0003）：状态亲和布局 compile_timeout（init 写出与布局耦合
  破坏 clang idiom 识别，修复方向已定位、可重测）；resize 胶消除弱正（-0.95%，
  94.1% 静态胶消除仅 ~1% 运行时，胶归一降级非一阶）
- t0/s01 双探针（A0002）：chunk 12000 证伪（+2.2% 回退，跨 chunk 往返非一阶）；
  branchy-mux 弱正（-0.74%，分支轴未否决、非一阶）
- 第 1 轮小结（A0005）：静态 emit 单旋钮空间扫完、收益饱和 ~1%/个；主失败
  模式是编译预算门（2/6）；`--init-zero-elision` 为元杠杆；块间机械
  （调度器/事件/commit）是唯一未触探大轴
- 已知参考点：AM Host 324.0s（emit-cost NO0018 收口，2026-08-14；与 r001 实测 273.1s
  有约 15% 漂移，单点数字注意机器状态/布局影响）
- run-init 备注：evaluator 修了 emu 相对路径 exec bug；金标改为计数窗
  （73584/49998 ±16/±8，覆盖两种 emu 停止点确定性小差）。详见
  [A0001](actions/A0001_run-init_基线与系统校准_20260814.md)

## 本任务构成

- `brief.md` — 常驻任务指令（目标、硬约束、已知机制背景）
- `protocol.md` — 评估协议（Φ 会原样内联进每个 proposal）
- `playbook.md` — 任务专属操作细节（基线流程、候选评估命令、结果解读）
- `config.json` — 默认参数与路径（run-init 冻结）
- `evaluator.py` — 评估器 V：`run`（候选/基线全流水线）与 `gsim`（现存 emu 协议化计时）两模式
- 评估构建规则见 [`playbook.md`](playbook.md)「构建与依赖复用」：候选 `wbuild`/
  `emu_build` 按 eval 隔离，FetchContent 依赖与 `build/tes/ccache` 复用，正式评估
  不联网；不要把新 build 目录误解为重新下载依赖
- `state/` — `run.json`、`ledger.jsonl`（append-only）、`insights.md`
- `actions/` `proposals/` `runs/` — action 笔记、Φ 快照、run 清单/总结
- 评估输入：gsim 导出的 exec-GRH（路径见 config `paths.exec_json`，run-init 记 sha256）

## 快速命令

评估前先遵守上面的“构建与依赖复用”规则：候选 build 目录隔离，FetchContent
依赖和 ccache 复用，不联网、不手工重建依赖。

```bash
python3 tes/tools/tesctl.py status            # 状态
python3 tes/tools/tesctl.py next              # 下一个 action
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <wt> --eval-id eNNNNN
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id eNNNNN
```
