# 20261006-061729 非 sink 划分 S1/S2 探索记录（语义节点+合并放松）与编译瓶颈解剖

> 探索/测量记录，非采纳项。结构收益实测为真，但所有边界削减变体均违反
> CPP→二进制 30 min 编译闸；瓶颈经 `-ftime-trace` 定位为编译器后端
> （SLPVectorizer + inliner），不在划分本身。编译基线（gsim vs grhsim-ir）
> 与 PCH 实验一并归档在此。工作底稿：`ptmp/grhsim-boundary-explore/NOTES.md`
> （含全部中间数据与任务号）。

## 元信息

- 日期：2026-10-05 ~ 10-06 / 作者：kimi
- wolvrix commit：`66000f6` + 未提交工作树（S1/S2 选项机制、reemit/脚本透传、
  基线测量用 Makefile 诊断目标）
- 上游记录：`20261005-170704-nonsink-semantic-partition-plan.md`（规划）、
  `20261005-111210-compare-count-census.md`（比较次数普查）、
  `20261005-002919-pmem-act-cluster-dead-compare.md`（178.9s 基线模型）

## 实现（已入库的机制，默认全 0 = 完全 legacy 行为）

- `cpu.st.build-general-nodes`：`--semantic-nodes`（S1：DeclProvenance Value
  切片目标值锚定自己的节点，锚点 op 不被下游吸收、节点无 128 帽；未覆盖值
  回退旧锥规则）、`--semantic-node-max-op`（语义锥可选帽，0=无帽）；
- `cpu.st.merge-general-supernodes`：`--coarsen-max-op`（S2：coarsen 合并
  权重帽，0=跟随 maxOps 即 legacy，大值≈无帽）；
- 透传：XS 流 env `XS_WOLF_GRHSIM_IR_SEMANTIC_NODES` /
  `XS_WOLF_GRHSIM_IR_SEMANTIC_NODE_MAX_OP` / `XS_WOLF_GRHSIM_IR_COARSEN_MAX_OP`，
  reemit 流 `GRHSIM_REEMIT_SEMANTIC_NODES` / `_SEMANTIC_NODE_MAX_OP` /
  `_COARSEN_MAX_OP`（Makefile `reemit_grhsim_ir`）；
- 诊断：`make grhsim_tu_trace GRHSIM_TRACE_TU=<模型TU> [GRHSIM_TRACE_FLAGS=...]`
  （单 TU -ftime-trace，落 `ptmp/grhsim-tu-trace/`）；
- 验证：`make build` 绿；`make test_wolvrix` 54/57 恰基线三项，无新增失败；
  pass 文档已同步（`docs/grhsim_ir/passes/build-general-nodes.md` /
  `merge-general-supernodes.md`）。
- S0 顺测：**XS General 相被声明锚定的值 464,858 个**（语义节点可用信息量）。

## 结构结果（reemit 筛查，对照 p1 parity：34,446 超节点 / 2,011,422 边界 /
672,414 publish 站点）

| 配置 | 非 sink 超节点 | 边界值 | publish 静态站点 | CPP→bin（30 min 闸） |
|---|---|---|---|---|
| s1（S1 语义节点，无帽） | 31,510 (-8.5%) | 1,958,628 (-2.6%) | 584,612 (**-13.0%**) | ✗ 25 min 编 38%（外推 3h+） |
| s1c（S1+S2 coarsen 无帽） | 26,884 (-22.0%) | 1,690,551 (**-16.0%**) | 525,853 (**-21.8%**) | ✗ 22 min 编 30%（外推 75-100 min） |
| s1n512（S1+锥帽512） | 31,903 (-7.4%) | 1,981,996 (-1.4%) | 598,635 (-11.0%) | ✗ 24 min 编 47%（外推 ~95 min） |
| s1n512c1024（+coarsen1024） | 26,811 (-22.2%) | 1,821,026 (-9.5%) | 550,506 (-18.1%) | 未编（同趋势） |
| 参考 m256p1（旧划分纯放大） | 17,272 (-49.8%) | 1,714,030 (-14.8%) | 556,858 (-17.2%) | ✗ 60 min 编 52% |
| 参考 m256p1h512（+chunk512） | 同上 | 同上 | 同上 | ✗ 3h37m 编 55%（chunk 救不回） |

要点：① publish 站点收益在各形态下保持较好（-11% ~ -22%），边界值收益被
帽砍掉大半；② **所有形态均违反编译闸**，无一拿到运行时数据（边界削减能否
换来运行时，至今零数据——这是最要紧的未知量）。

## 编译瓶颈解剖（-ftime-trace 实证）

- 慢点集中在非 sink 超节点段 TU（各变体 tu31~tu148 这一百来个文件）；
  sink 段、巨串行、TU 行数分布、函数行数**逐项排除均非瓶颈**（p1 tu112 最大
  函数 1029 行 > s1n512 的 586 行，p1 却 2.8s 编完）。
- trace 对照（s1n512 tu112 vs p1 tu112）：p1 = 2.8s（前端 2.1s 解析为主，
  后端 0.59s）；s1n512 = 43.5s，其中 **SLPVectorizerPass 27.2s（62%）+
  inliner 13.8s**。SLP 向量化器在 publish compare-store 平行长链/concat
  链上超线性。
- 单 TU 加 `-fno-slp-vectorize`：43.5s → **16.3s**（剩余为 inliner）。
- s1c 全模型 SLP-off：早期 66 TU/min（原 15），进大 TU 簇后 ~6/min，
  外推 ~2.5h——**SLP-off 救得了 m256/s1n512 级，救不了 s1c 级（inliner 成
  新瓶颈）**。
- 旗标运行时成本（归因 A/B）：p1 + `-fno-slp-vectorize` 定核 100k 运行
  **179.5s ≈ 生产 178.9s**（终点 instrCnt=240,349 / cycleCnt=99,996 /
  pc=0x80000c0c 一致）——**运行时中性，可入生产**。
- 旗标透传路径（复用要点）：difftest `grhsim.mk:42`
  `GRHSIM_MODEL_CXXFLAGS ?= -std=c++20 -O3`，make 命令行覆盖经 MAKEFLAGS
  透传到模型 make；模型库并行度 `GRHSIM_MODEL_BUILD_JOBS`（=32，env
  VM_BUILD_JOBS）。

## 编译基线（-j32 全量 CPP→二进制，含 harness+链接，2026-10-05 深夜实测）

| 构建 | 模型规模 | wall | CPU |
|---|---|---|---|
| gsim（`build/xs/gsim`） | 329 cpp / 13.83M 行 / 头 489k 行 | **5m41.5s** | 83.4 CPU-min |
| grhsim-ir 改动前（`build/xs/grhsim-ir`） | 1082 cpp / 14.13M 行 / 头 1.04M 行（103MB） | **8m58.2s** | 239.4 CPU-min |
| grhsim-ir + PCH（实验） | 同上 + 184MB .pch | **8m59.6s** | 225.8 CPU-min |

- 单位行数编译 CPU：gsim 6.0 vs grhsim-ir 16.9 CPU-min/M 行 = **2.8×**；
  wall 比 1.58×（grhsim TU 更多、并行度更高）。gsim 平均每 TU 42k 行仅
  ~15s CPU，且其代码亦有深嵌套表达式（`-fbracket-depth=2048`）——差距
  在编译器后端，不在前端解析。
- **PCH 实验（103MB 头、每 TU 恰一个 include、`#pragma once`，实测否决）**：
  头解析 ~2.15s/TU 为真，但 PCH 只省 CPU 5.7%（239.4→225.8 CPU-min），
  **wall 8m58s→8m59s 零变化**。-j32 下众核早已吃饱，墙钟由长尾大 TU 的
  后端时间决定，PCH 不碰尾部。结论：PCH 不值得做；编译加速的杠杆是缩短
  最慢 TU 的后端（SLP-off / inliner 控制 / 超节点尺寸）。

## gsim 对照：代码形态与尺寸免疫（2026-10-06 补）

**形态对比**（gsim 最大文件 SimTop324.cpp 144k 行 vs 我们 s1n512 tu112.cpp
15.8k 行，均 `-ftime-trace`）：

| 维度 | gsim | 我们 |
|---|---|---|
| 全文 `if(` 数 | **9**（全是 activeFlags 超节点门卫） | **1816**（每 publish 一个条件存） |
| helper 调用数 | **0**（inferWidth 归一后原生类型 + 裸运算符） | **4198**（grhsim_* 全包） |
| 编译 | 8.7s（0.061s/千行） | 43.5s（2.75s/千行，45×） |
| SLP / inliner | 0.68s / 1.17s | 27.2s / 13.8s |

gsim 的变化检测是**无分支**的：`bool cond_X$NEXT = next ^ old;` 然后
`activeFlags[i] |= cond << bit;`；每个超节点只有一道
`if(unlikely(activeFlags[i]))` 门卫。我们的每边界值一个
`if (old != new) { store; flag |= bit; }`，TU 级分支上千、小基本块成群。

**尺寸免疫实验**（用户提议）：gsim `--supernode-max-size` 15（生产值，
difftest gsim.mk:28）→ 1024，重新生成 + 编译：

| size | 超节点数 | cpp 文件 | 行数 | 编译 wall（-j32） |
|---|---|---|---|---|
| 15 | 84,787 | 329 | 13.83M | 5m41s |
| 1024 | **2,975**（-96.5%） | 230 | 12.87M | **~7.3 min（+28%）** |

68× 帽放大只换 +28% 编译（部分来自文件变少、并行尾巴变长）——**gsim 的发射
形状对超节点尺寸免疫实锤**。附带实证：生产 gsim 模型本就含 members≈7001 的
超节点（cap 只管最后 DP 打包，when/链等语义合并无帽），与规划文档判断一致。
gsim 生成（firrtl→cpp）约 12.5 min，不在上表。

## 结论与下一步候选

1. S1/S2 的结构收益成立（边界 -16%、publish 站点 -21.8% 于 s1c），但划分侧
   放松与 30 min 编译闸直接冲突；闸的对因在编译器后端，而**后端的病理是
   发射形状造成的**：逐值条件存（分支+小基本块群）喂爆 SLP，逐 op helper
   调用喂爆 inliner。
2. ~~已可用的免费项：生产编译旗标加 `-fno-slp-vectorize`（运行时中性已证，
   179.5s）~~ ——**作者 2026-10-06 否决：不走关 SLP 的路**（绕开症状而非
   修复形状）。
3. 新主线（gsim 形态对齐，编译与运行时双赢候选）：① 变化检测改无分支
   flag 传播（xor 进临时量 + or 进旗标字），消掉 publish 的条件存与分支群；
   ② 宽度归一后裸运算符直发，消灭 grhsim_* helper 调用（需要评估我们
   两态/四态与掩码语义下的等价性）；两者都先小证（单 TU trace + 编译时
   长），再决定大规模改造。
4. 欠账：① 一个"边界削减 + 过闸"变体的运行时数据（m256p1 曾被叫停）；
   ② 动态比较次数普查复测确认收益传导；③ 形态改造后 s1c 重测编译闸。
