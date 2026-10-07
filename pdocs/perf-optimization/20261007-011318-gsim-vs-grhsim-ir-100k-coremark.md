# 20261007-011318 gsim vs grhsim-ir 100k CoreMark 同机对照

> 性质：**双侧对照登记**，不是优化记录。登记默认流程产物（gsim SN=15 非 PGO
> vs grhsim-ir 六阶段默认非 PGO）在 100k CoreMark 口径下的性能差距，作为
> 超节点粒度/结构对齐工作的背景锚点。

## 元信息

- 日期：2026-10-07 / 作者：kimi
- wolvrix commit：`6bcf731` / 根仓 commit：`7c459df`
- 上游基线记录：`20261004-075148-v3-sixphase-baseline.md`（IR 单侧 M0 对照基线）；
  PGO 口径双侧基线见 `Makefile:484-485`（IR 55.864s / gsim 27.376s）

## 被测产物（均为默认流程，无手工拼参数）

- **gsim**：`make xs_gsim_emu`。模型 `build/xs/gsim/gsim-compile/model/`
  （329 个 `SimTop*.cpp`，gen 日志确认 `SuperNodeMaxSize=15`，即仓库 XS 流程默认
  `XS_GSIM_SUPERNODE_MAX_SIZE=15`；产物复用 2026-10-05 生成、make 判定未过期）。
  emu `build/xs/gsim/gsim-compile/emu`（55.6MB）。
- **grhsim-ir**：`make xs_wolf_grhsim_ir_emu XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=build/xs/grhsim-ir/model`
  （EMIT_CPP_DIR 为流程设计变量，其余全默认：`--cpu-target-batch-count 0`、
  semantic-nodes=0、max-op-in-compute-supernode=128）。模型
  `build/xs/grhsim-ir/model/`（1084 TU），emit 10.5s；ingest+emit+全量编译
  （clang -O3 -j32）合计 28.5 min。emu `build/xs/grhsim-ir/emu/grhsim-compile/emu`（233MB）。

## benchmark 命令与口径

- 命令：`make run_xs_gsim_emu` / `make run_xs_wolf_grhsim_ir_emu`，共同变量
  `XS_SIM_MAX_CYCLE=100000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_COMMIT_TRACE=0
  XS_RAM_TRACE=0 XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=1 XS_EMU_CPU=4`。
- 负载：`ready-to-run/coremark-2-iteration.bin`，`-C 100000` 周期截断。
- difftest：`--diff riscv64-nemu-interpreter-so` **双侧同开**（Makefile 默认
  `XS_EMU_DIFF_ARGS`）。
- 定核：`taskset -c 4`（Makefile 默认 `XS_EMU_PREFIX` 机制）；3+3 交替。
- **偏离标准口径说明**：标准口径 `make benchmark_grhsim_ir` 是 IR 单侧新旧对照
  工具（build_var 切换两套 IR 构建），不适用于 gsim-vs-IR 跨模拟器对比；本次
  未逐出页缓存。双侧完全同条件，对**相对比值**影响中性；绝对值不与
  `benchmark_grhsim_ir` 历史记录直接可比。

## 数据

宿主时间（emu 自报 `Host time spent`）：

| 轮次 | gsim（SN=15） | grhsim-ir |
|---|---|---|
| 1 | 46.960s | 111.423s |
| 2 | 47.111s | 111.841s |
| 3 | 47.100s | 112.905s |
| **均值 ± sd** | **47.06 ± 0.08s** | **112.06 ± 0.76s** |

**差距：grhsim-ir 比 gsim 慢 2.38×**（112.06 / 47.06）。

日志：`build/logs/xs/xs_gsim_cmp100k_gsim_{1,2,3}.log`、
`build/logs/xs/xs_wolf_grhsim_cmp100k_ir_{1,2,3}.log`（因 ptmp 已于当日清空，
且未走 benchmark 脚本，数据未落 ptmp）。

## 正确性与访客侧终点

- 两侧全程 NEMU difftest 无 mismatch，均在 100k 周期截断处正常退出。
- 访客侧终点（第 1 次）：

| | instrCnt | cycleCnt | 末 PC |
|---|---|---|---|
| gsim | 238,550 | 99,998 | 0x80000b40 |
| grhsim-ir | 240,349 | 99,996 | 0x80000c0c |

  grhsim-ir 与既有期望终点（instrCnt=240,349 / cycleCnt=99,996 / PC 0x80000c0c）
  逐拍一致；gsim 的终点差异是 gsim 自身调度语义的已知特征，非错误。

## 与 PGO 口径基线对照

| 口径 | gsim | grhsim-ir | 比值 |
|---|---|---|---|
| 本次（非 PGO） | 47.06s | 112.06s | 2.38× |
| `Makefile:484-485`（PGO 构建） | 27.376s | 55.864s | 2.04× |

两种构建口径下差距同量级（2.0–2.4×），PGO 对两侧的绝对加速不同但**比值结构稳定**。

## 备注（结构背景，当日测量）

- 超节点数量（当日产物实测）：grhsim-ir P_general **36,386** 个
  （merge 日志：非 sink 34,289 + sink 系约 2,097；emit 后 `sn_*` 函数 36,386 个
  wrapper + 17 个 SupernodePart helper）；gsim（SN=15）**84,643** 个
  （`SimTop_supernode_stats.json`）。数量差约 **2.3×**。
- 每超节点生成行数（中位数）：grhsim-ir 144 行（mean 251、p90 450、p99 854、
  max 839,425=单签名 sink 巨簇含跨 TU helper）；gsim 77 行（mean 157、
  p99 1,362、max 64,880）。
- S1（`--semantic-nodes`）/ S2（`--coarsen-max-op`）机制已在 `6bcf731` 落地为
  可选开关，默认关闭；s1c 无帽配置编译闸固有违约（见
  `20261006-061729-nonsink-partition-s1s2-exploration.md`、
  `20261006-101609-bitint-wide-value.md`），未成为默认。
