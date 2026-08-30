# TNO0261：SimpleTES post-g158 gen38 best node030 可靠性复测

日期：2026-08-30

## 1. 阶段结论

本阶段在 node030 对扩容前的 post-g158 generation 38 best 做了 fresh 构建和
同 CCD/CPU schema-v3 `ABBA+BAAB` 复测。正式 SimTop 50k walltime 为：

```text
ABBA control / candidate  43,539.00 / 43,003.50 ms
ABBA improvement          535.50 ms / 1.229931785%

BAAB control / candidate  43,469.00 / 42,914.50 ms
BAAB improvement          554.50 ms / 1.275621707%

pooled control            43,504.00 ms
pooled candidate          42,959.00 ms
pooled improvement        545.00 ms / 1.252758367%
order gap                 0.045689922 pp
```

因此裁决为：

- gen38 patch 的端到端正收益可以复现；
- 历史 `+2.223038246%` 的精确幅度没有复现，node030 正式结果低
  `0.970279879 pp`，即低 `43.646567%`；
- 当前最合适的复测 headline 是 `+1.252758367%`，不能继续把单组
  `+2.223038246%` 当作稳健收益；
- 本阶段只回答可靠性，不执行 landing、默认开启或研究 baseline 切换。

运行中的 `128 generations / 64 valid` auto research 没有被停止或重启。
复测使用独立 slot root；最后核对时 launcher/main 仍存活，生产树最新持久化状态为
`66 attempts / 54 evaluations / 48 valid`，best 仍是本候选。

## 2. 冻结候选身份

本次对象不是已经落地的 g158 本体，而是以 g158 为 baseline 的后续搜索 best。
来源和身份如下：

```text
source checkpoint:
SimpleTES/checkpoints/grhsim_simtop_50k/
  g158_native_mirrored_gpt56sol_max_fresh_20260827_195900/
    2026-08-27/instance-9733393b/db_state_223640

generation / chain     38 / 3
node id                6de5b2426b1a49ec9c762d5dafb6a94d
candidate digest       e04bcaa5660bdb801115320c7d9101310357b1641998d03d5df36c3125e85cd5
candidate mode         default-path
enable options         []
best_program SHA-256   49e8efeffd805d4a4d0aa6d30712f9ee87f12c76438722d4f589247283ae6750
patch SHA-256          f0000783cb75e01cc9126252fdaf6cac5c32edd6f5310459033625e482f2e4ce
parent pin             6e2436e37286264e9f03f114d14d81bae4ed313b
Wolvrix pin            054c6a7c09b007a12eb36fdb49fcb659a1bfc590
proof id               d12da2b2c0a54713ad0f41b1c6d12fea
proof SHA-256          7b7fd44879802cb056bd6645518f09904a93c55844fb11077ce95e94afa5c8bc
```

候选保留此前结构化 hot input seed 的连续 chunk 写入收缩，并把 full-clear compute
word 中 selected input 缺失不超过两个 dispatch bit 的已覆盖 entry guard 标为
likely。它不增加 SimTop 名字匹配或 enable option，也不改变仿真语义。

相关上下文见 [TNO0256](./TNO0256_g158_landing_native_50k_walltime_regression_20260827.md)、
[TNO0258](./TNO0258_simpletes_control_bias_invalidation_and_mirrored_protocol_fix_20260827.md)、
[TNO0259](./TNO0259_simpletes_corrected_fresh_restart_initial_control_20260827.md) 和
[TNO0260](./TNO0260_simpletes_g158_mirrored_budget128_valid64_resume_launch_20260830.md)。

## 3. Fresh 构建与功能门禁

复测没有重放 node032 搜索时的旧 ELF。evaluator 从冻结 pins 和默认生成配置建立
fresh control/candidate，候选 patch 只应用到 candidate。产物身份为：

| 项目 | control | candidate |
| --- | --- | --- |
| generated fingerprint | `e4e8fa8e47cc2412...` | `ed066ddae63b68a0...` |
| ELF bytes | `83,517,504` | `83,693,560` |
| ELF SHA-256 | `1c3170f87fa961f6e21c86d89de5d13320a6a1283a9b2dbf9c5c919dbee810c8` | `401c76c22310f4f50b96842253ba1be201dc1530ae97b3f8204e3efa11d3ea3b` |

两边共同的 build-config fingerprint 为
`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`，
toolchain fingerprint 为
`7669097de01707e2fab9a40ae7b308617c33dece545dcc5a6e0d38be217b98bc`。
node032 原搜索的 generated/ELF identity 与本表不同，因此这是真正 fresh rebuild；
随后所有 node030 runtime-only retry 则严格复用本表两份 ELF 和同一 proof。

功能门禁全部通过：

| gate | control | candidate |
| --- | ---: | ---: |
| focused emitter tests | `29/29` | `29/29` |
| SimTop `C=100` | PASS | PASS |
| SimTop `C=10000` | PASS | PASS |
| final `C=50000` signature/guest-cycle/terminal-PC | `4/4` PASS | `4/4` PASS |

## 4. 测量协议与并发隔离

每条构建和运行命令均先 source `wolvrix-playground-gsim-calibrate-5/env.sh`。性能
协议保持 [TNO0258](./TNO0258_simpletes_control_bias_invalidation_and_mirrored_protocol_fix_20260827.md)
定义的 schema-v3 口径：

- headline 是 emu 的 `Host time spent` walltime；
- 单个原子组固定 `A,B,B,A,B,A,A,B`，ABBA/BAAB 使用同一 CCD、同一 CPU；
- 通过 `setarch x86_64 -R` 关闭 ASLR，八个样本 personality 均为 `00040000`；
- 每个样本均检查 whole-CCD pre/continuous-load、affinity、NUMA、PMU、功能签名；
- 仅接受双 order 同向且 order gap `<0.25 pp` 的完整组；不补测、不跨组拼接；
- runtime-only retry 重新校验 proof、pins、generated/build/toolchain fingerprint 和
  control/candidate binary/image/NEMU SHA，禁止 clone、patch、emit 或 rebuild。

正式组 placement 为：

```text
host        node030
CCD         node1:136-143,328-335
CPU/sibling 137 / 329
helper CPU  0
NUMA node   1
entry gate  mean/min idle 99.938125% / 99.67%
```

auto research 使用默认 `/tmp/simpletes-grhsim-simtop-50k/.../slot-0`，本复测使用
`/tmp/simpletes-grhsim-gen38-retest-node030-20260830/.../slot-0`。两者不共享 clone、
artifact、lock 或结果；同机负载碰撞由上述严格门禁判废。

## 5. 历史 `+2.223038%` 的完整上下文

历史搜索在最终 accepted 前已有三个完整但 order gap 不合格的组。以下均为
`A,B,B,A,B,A,A,B` 原始 walltime；前三组与最终组之间发生过 candidate 重编译，
因此只能作为搜索历史诊断，不能声称四组 bit-identical：

| 组 | raw walltime (ms) | ABBA control→candidate | BAAB control→candidate | pooled control→candidate | gap |
| --- | --- | --- | --- | --- | ---: |
| prior-1 reject | `46452,46092,46287,45771,43546,43899,43788,43300` | `46111.50→46189.50` (`-0.169155%`) | `43843.50→43423.00` (`+0.959093%`) | `44977.50→44806.25` (`+171.25 ms/+0.380746%`) | `1.128248 pp` |
| prior-2 reject | `43739,43305,43359,43669,43264,43658,43596,42998` | `43704.00→43332.00` (`+0.851181%`) | `43627.00→43131.00` (`+1.136911%`) | `43665.50→43231.50` (`+434.00 ms/+0.993920%`) | `0.285730 pp` |
| prior-3 reject | `42955,42348,42611,42601,42496,43101,42894,42273` | `42778.00→42479.50` (`+0.697789%`) | `42997.50→42384.50` (`+1.425664%`) | `42887.75→42432.00` (`+455.75 ms/+1.062658%`) | `0.727876 pp` |
| accepted | `47452,45111,43868,43463,42029,42684,43411,42067` | `45457.50→44489.50` (`+2.129462%`) | `43047.50→42048.00` (`+2.321854%`) | `44252.50→43268.75` (`+983.75 ms/+2.223038%`) | `0.192392 pp` |

历史 accepted 虽然 wall order gap 通过，但 control/candidate spread 分别达到
`4,768/3,082 ms`。其 pooled cycles 只减少 `1.316892%`，而由 cycles/wall
估算的 candidate 有效频率高 `0.926748%`；cycles 的 ABBA/BAAB 收益 gap 又达到
`1.756510 pp`。这些信号说明 `+2.223038%` 中混入了明显的频率/时序偏置。

## 6. node030 所有正式完整组

fresh evaluator 先执行 `9` 次 runtime attempt，其中 `3` 次形成完整组但 gap
不合格，`6` 次被基础设施门禁中止。随后 runtime-only 复用同一 ELF：前 `26`
次中有 `2` 个完整 gap reject、`24` 个基础设施 reject，第 `27` 次正式通过。
两轮合计 `36` 次 attempt：`30` 次基础设施拒绝、`5` 次完整 gap 拒绝、`1` 次
accepted。只有下表六组是 immutable JSON 认定的完整组；写出 emu walltime 但最终
monitor/pre gate 失败的 partial 组不在表内。两轮 evaluator 总用时
`12,234.797915 s`（`3 h 23 min 54.798 s`）；基础设施拒绝的 partial 组中共有
`54` 个已完成但最终未入组的样本。

| 组 | raw walltime (ms) | ABBA control→candidate | BAAB control→candidate | pooled control→candidate | gap |
| --- | --- | --- | --- | --- | ---: |
| fresh-2 reject | `43341,43066,42897,43467,42955,44242,43292,42961` | `43404.00→42981.50` (`+0.973413%`) | `43767.00→42958.00` (`+1.848425%`) | `43585.50→42969.75` (`+615.75 ms/+1.412740%`) | `0.875012 pp` |
| fresh-3 reject | `43540,43302,43024,43432,43054,43667,43532,42988` | `43486.00→43163.00` (`+0.742768%`) | `43599.50→43021.00` (`+1.326850%`) | `43542.75→43092.00` (`+450.75 ms/+1.035190%`) | `0.584082 pp` |
| fresh-7 reject | `43994,42460,42548,42502,42272,42934,42758,42455` | `43248.00→42504.00` (`+1.720311%`) | `42846.00→42363.50` (`+1.126126%`) | `43047.00→42433.75` (`+613.25 ms/+1.424606%`) | `0.594185 pp` |
| retry-9 reject | `42002,41369,41132,41300,41296,42531,42491,40744` | `41651.00→41250.50` (`+0.961562%`) | `42511.00→41020.00` (`+3.507328%`) | `42081.00→41135.25` (`+945.75 ms/+2.247451%`) | `2.545766 pp` |
| retry-15 reject | `42635,42475,42119,43303,43062,42776,42572,42132` | `42969.00→42297.00` (`+1.563918%`) | `42674.00→42597.00` (`+0.180438%`) | `42821.50→42447.00` (`+374.50 ms/+0.874561%`) | `1.383480 pp` |
| retry-27 PASS | `43491,43044,42963,43587,42986,43527,43411,42843` | `43539.00→43003.50` (`+1.229932%`) | `43469.00→42914.50` (`+1.275622%`) | `43504.00→42959.00` (`+545.00 ms/+1.252758%`) | `0.045690 pp` |

六组分别固定在 CPU/CCD `134/node1:128-135,320-327`、
`127/node1:120-127,312-319`、`104/node1:104-111,296-303`、
`155/node1:152-159,344-351`、`184/node1:184-191,376-383` 和
`137/node1:136-143,328-335`；每组内部的 ABBA/BAAB 从未跨 CPU 或 CCD。

六个完整组的 pooled 方向全部为正，中位数为 `+1.332749%`；唯一另一个
`>2%` 组正是 gap 最大的 `retry-9`。该表支持“方向为正”，但同时否定“2.2%
是稳定中心”。

## 7. 正式组 PMU 与运行门禁

正式组的 pooled PMU 为：

| 指标 | control | candidate | candidate 变化 |
| --- | ---: | ---: | ---: |
| walltime | `43,504.00 ms` | `42,959.00 ms` | `-545.00 ms / +1.252758%` |
| cycles | `157,336,284,391.25` | `155,420,594,159.25` | `+1.217577%` |
| retired instructions | `148,670,618,125.25` | `148,195,389,418.00` | `+0.319652%` |
| backend stalls | `53,980,783,582.25` | `53,289,271,441.50` | `+1.281034%` |
| task-clock | `43,517.73 ms` | `42,971.07 ms` | `~+1.256178%` |
| cycles/task-clock effective frequency | `3.615453 GHz` | `3.616866 GHz` | candidate `+0.039092%` |

control/candidate wall spread 仅为 `176/201 ms`（`0.404561%/0.467888%`）；八个样本
均为单 CPU、零 migration、PMU scheduled `100%`、NUMA local ratio `1.0`，pre 和
continuous monitor gate 全部通过。cycles `+1.217577%` 与 wall `+1.252758%`
吻合，而有效频率差只有 `0.039092%`，本轮没有历史 accepted 的约 `0.93%`
candidate 频率优势。

## 8. 可靠性裁决与边界

把历史和 node030 的十个完整组仅作为诊断样本观察，pooled gain 中位数为
`+1.157708%`；去掉两个 `>2%` 且分别伴随异常 spread/order gap 的组后，其余
八组均值为 `+1.054647%`。order-gap reject 组不是正式性能结果，这些统计不能
替代最终 PASS，但解释了为什么 node030 的 `+1.252758%` 比原 `+2.223038%`
更符合重复测量中心。

最终边界是：

- 正收益方向可靠：node030 同一 fresh ELF 的六个完整组全部为正，正式组也通过；
- `+2.223038%` 幅度不可靠：它没有在低 spread、低频率差的正式复测中重现；
- 当前候选仍只是 research best，不因本复测自动 landing 或默认启用；
- 后续如要落地，仍应先做候选内部优化的消融，再以当前默认 Wolvrix 为 control
  做 fresh 前后功能和 SimTop 50k walltime 回归。

## 9. 可复核证据

NFS evidence root：

```text
build/gen38_node030_retest_20260830/
```

主要文件 SHA-256：

```text
fresh_eval.log
  a35624a1ad768c52c8ba670c16e18e02c240042a7803e41f595d6cdc1c92219a
runtime_retry_1.log
  2fcc788805fd3ba7475245f6c42dbbe1b0b0248bed1c708ff9f863e4b9567880

accepted_01788103779520559120/runtime_result.json
  f0a56ab76064b05836b434dd5d37283858f93d4a7af9a4f10cf80d3e693a89ed
accepted_01788103779520559120/evaluation.json
  4bf23014e579162638e7301de6409ddf362d8ea63b1713549d64f17cc5ed1aa2
accepted_01788103779520559120/complete.json
  d6b4ae0b9251edf6c599029f460d1a25f30c075e53e4b9233a06830b0c82d383
accepted_01788103779520559120/candidate_proof_e04bcaa5660bdb80.json
  7b7fd44879802cb056bd6645518f09904a93c55844fb11077ce95e94afa5c8bc
accepted_01788103779520559120/control_artifacts.json
  dbf33cd42f7e9dc1f1aecf4f167853c0c3b525a5561b1f7054e5dc5b54a70fb7
```

历史 g158 本体的独立 fresh 复测可回查
[TNO0248](./TNO0248_simpletes_g158_node030_fresh_sameccd_retest_20260825.md)；不要把
本篇 post-g158 gen38 的结果误写成 g158 landing 本身的收益。
