# A0056 step r002/t0/s08：MemoryFill 使能门控证伪与批内双态首次直接检出（2026-08-21）

- action: step（t0 第 8 步，K=2）
- eval 预算：30/32 → 32/32（含 2 基线口径；候选口径 28/32 → 30/32，余 2 = t1/s08）
- 轨迹归属说明：A0055 曾按「余 2 evals」裁定 s08 给 t1、t0 空转，但该预算口径把 2 个
  基线 eval 计入了候选预算 N=32——r001 A0032 勘误已确立基线不占候选预算。正确口径下
  余 4 候选 eval，t0/s08 与 t1/s08 均可走满。状态机 round-robin（同分按 id）给出 t0，
  本 goal 按 `tesctl next` 执行 t0/s08；t1/s08 由下一 action 执行（余量恰好 K=2），
  A0055 的 t1 优先意图不受损。

## 前置 recon（recon-t0s07：hinted 生产 emu 首次 perf 复测）

A0053/A0055 纪律：残余骨架压缩须 hinted 二进制新 perf recon 定量后再候选。对 e00027
生产 emu（tip b9a671a、13 旋钮、无插桩）全程 perf record（99Hz，27,921 样本，
Host 281.996s、difftest 金标过 73580/49996——快态窗）。符号聚合：**eval_scan_*
自时间 46.61%** / block_*_chunk 29.69% / helper 21.01% / eval_commit_* 0.83% /
eval() 0.15%。annotate 热点 IP 抽查（eval_scan_4_part_3 等）：样本落在内联块体的
shl/and 等 ALU 指令上，序言/位测试链 ~0%——**hints 后跳过链已压出热点，dispatch
骨架轴以直接证据关闭**（A0055「接近关闭」落定）。helper 首位 =
**slice_words_detect 5.49%**（≈15.5s），次位 array_mux_words 4.93%、index_words
2.99%。产物 `build/tes/grhsim-am-coremark/evals/recon-t0s07/`（perf.data、run.log）。

## 候选与假设（事先写下）

- **c1（e00031，`--memory-fill-enable-gate`，79719b2）**：lowering 把 mem.fill 写
  使能折进打包镜像（`merged = mux(cond, packed, readAll(target))`），commit 相
  MemoryFill 逐元素 slice_words_detect 扫描在使能为假时必然空手（镜像与已提交存储
  逐字相等）。当同存储其余 commit 写全在同 Block 更后位置时，`if (cond)` 门控整个
  元素循环消除该数据流（recon-t0s07：slice_words_detect 自时间 5.49% 居 helper
  首位）。假设：Host 中位较同窗安慰剂降 **>=4%**；**<2% 证伪**。
  实施：emitter 计划 + 门控发射（off 逐字节等价）、CLI 旋钮、emitter 单测
  （off/on + oracle harness）、pipeline 文档。离线验证：17/17 ctest；真实设计 off
  emit 与 e00027 全源逐字节一致；on engagement **sites=191 / sibling_writes=1914 /
  elements=41748**，diff 仅 2 个 commit 块源文件、191 处纯门控包裹。
- **c2（e00032，安慰剂锚点，7df5149）**：t0 tip b9a671a 原样 + 同 13 旋钮，
  连续第七轮锚点席位；无机制假设。

## 结果对比

| 候选 | eval | Host 中位 | reps | CV | 裁决 |
|---|---|---|---|---|---|
| c1 机制 | e00031 | **321.922s** | 321922/321918/321927 | 0.0% | 假设证伪 |
| c2 安慰剂 | e00032 | 343.664s（noisy） | 295042/389234/295038/362299/343664 | 12.35% | 锚点 |

两候选 17/17 ctest、difftest 全过（73580/49996）；compile_s 1149.5 / 1135.0s。

## 测量学：批内 per-process 双态首次直接检出（本步最重要发现）

c2 的并行首批 3 rep（绑核 12/13/14 同批起跑）= **295.042 / 389.234 / 295.038s**——
同批混合快/慢态，直接证明双态是 **per-process 抽签**（与 A0036「THP/NUMA 页放置
per-process 运气」残余指向一致），而非整窗翻转；此前批内 CV≈0 只是「三 rep 抽中同
态」的运气。CV 12.35% 触发加测至 5 rep（rep4 362.299 / rep5 343.664，均慢态簇），
median 343.664s 为混合态 artifact、**不作裁决基准**。c2 快态簇 295.042s =
**t0 历史最快读数**（前最快 301.081s）。t0 tip 真值口径更新：快态锚 **295.042s**。

## winner 裁决与机制分析

- **机制裁决：c1 证伪**。双态模型下 c1 的 321.922s（3 rep 全同态）最自洽的读法 =
  门控二进制的快态 = 较未门控快态 295.042s **+9.1% 回退**；任何读法下「降 >=4%」
  的假设均不成立。归因嫌疑：191 处门控分支 + cond 成员冷 load 落在每 eval 触发的
  commit 巨块热路径上，且使能可能近恒真（门控从未跳过、纯增开销）——但 +9.1% 超
  出该开销的合理量级，部分或与漂移连续分量混杂；裁决稳健性不依赖归因：**无收益
  证据、最佳读数偏负，旋钮不携带**。commit 相「条件门控省流量」类首次尝试即败，
  与 A0048/A0050「commit 相省指令/省往返为负」同向，commit 相开放方向进一步收窄。
- **finish-step 机械 winner = e00031（记分板口径）**：c2 的 median 被慢态污染
  （343.664 > 321.922），状态机按 score 快移 c1 入 t0/main。**该合入内容无害**：
  旋钮默认 off，t0 有效 emit_args 不携带 `--memory-fill-enable-gate`，emit 输出与
  旧 tip 逐字节等价（off 等价已实证），回撤零成本。ledger 中 e00031 的 winner/
  committed 标记按 A0039 先例保留并在本条勘误其机制结论为证伪。
- t0 best 仍为 e00007（-261543，抽签读数地位不变）；t0 走完 8/8。

## 对 Φ 下一步的建议

- t1/s08（下一 action，余 2 eval 恰好 K=2）：按 A0055 裁定执行，recon-t1s07
  （hinted 生产 emu perf）先行；本步 recon 方法论可直接复用（perf record @ 生产
  emu + annotate 热点分类）。
- **测量协议必须升级以利用批内双态检出**：rep 级读数按快/慢簇分组比较（同态簇内
  比中位），而不是批 median；5 rep 加测后的混合 median 已证会反转 winner 裁决
  （本步实例）。建议提请用户：evaluator 增加簇感知裁决输出（如分别报告 min/
  快簇中位），或每候选固定 5 rep。
- MemoryFill 门控类勿再投入；commit 相残余开放方向只剩布局/预取（受 194MB 流扫
  带宽约束，历届证据均偏负）。
