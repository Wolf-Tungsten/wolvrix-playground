# TNO0187 RWA landing SimpleTES repin and native control canary

## 1. 阶段目标与结论

[TNO0186](./TNO0186_rwa_wolvrix_landing_implementation_and_provenance_20260727.md)
完成 R/W/A 的 Wolvrix 生产源码、测试和 executable snapshot 后，本阶段把 SimpleTES bench
迁移到该原生默认基线，并实际执行一次无 patch、无 option 的 production control canary。

结论为 `PASS`：

- SimpleTES 已 pin parent `d31118bea0feb563ad09476e1419f0f15aaf574f` 与 Wolvrix
  `16a9f493687a21a5428f1e1327a69834ea60c9f5`；
- 新 control seed 是 schema-v2 `control`，`patch=""`、`enable_options=[]`；
- 旧 `fbe4e1c.../8f6ba14...` checkpoint 在 resume 与 `best_program.txt` seed 两条路径均 fail-close；
- production `options={}` fresh build、focused、100/10k 与 50k 自对照均通过；
- canary 的四个 50k 样本全部通过 quiet-CCD、fixed-ASLR、affinity、NUMA、PMU 和功能审计；
- 本阶段只运行 evaluator control，没有启动 auto research，也没有调用模型生成 candidate。

## 2. 提交与 bench 身份

本阶段实际提交为：

- SimpleTES commit：`b0c7754651c84cd4de5e02aa01bad67fa2c0ae4a`；
- parent pin：`d31118bea0feb563ad09476e1419f0f15aaf574f`；
- Wolvrix pin：`16a9f493687a21a5428f1e1327a69834ea60c9f5`。

bench 代码与环境身份：

| 对象 | SHA-256 |
| --- | --- |
| `evaluator.py` | `0fbdc274d87a3ff115bc8f2a7ec016970cb9124dbd2c2db752602468341414ce` |
| `runtime.py` | `fd3bb81b7295f90aed63ef6a829277563be4093ea26f76be22d6927f36f93f97` |
| `env.sh` | `3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a` |
| control seed digest | `345fe98fbbc4ff3b284117723d9f535b780fc137d4ea3f830540343510a2f41e` |

新 pin 派生出的 evaluator namespace 为：

`/tmp/simpletes-grhsim-simtop-50k/02d8ec0c5cbeb4ef/slot-0`

它与旧 namespace 分离，没有把旧 control cache 或 candidate checkpoint 当作新基线。

## 3. Repin、历史复现与 continuation 边界

SimpleTES 修改覆盖六个文件：

- `datasets/grhsim/simtop_50k/evaluator.py`：更新完整 parent/Wolvrix pin；
- `init_program.txt`：改成 post-RWA 空 control，并记录 R/W/A 已落地、F 未落地；
- `instruction.txt`：candidate patch 改为相对 `wolvrix@16a9f493...`，禁止重复 R/W/A/F；
- `README.md`：要求首次从新空 control 启动，旧 namespace 不得 resume 或 seed；
- `materialize_ablation.py`：历史 RWA 物化固定读取 Wolvrix `8f6ba143...`，不再借用活动 evaluator pin；
- `tests/test_grhsim_bench.py`：补齐新 pin 断言、历史物化身份，以及旧 pin resume/best-seed fail-close。

由此区分两类用途：

1. 新 auto research 只能从 `d31118b.../16a9f49...` control 或同 pin checkpoint 继续；
2. `materialize_ablation.py --compose-rwa` 仍能复现历史消融，但其输出不能 seed 新 namespace。

本阶段没有修改 launcher/runtime schema，也没有自动启动 continuation。

## 4. SimpleTES 功能回归

实际回归结果：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| `tests/test_grhsim_bench.py` | `69/69` | `PASS` |
| SimpleTES full pytest | `141/141`，`17` 条既有 deprecation warnings | `PASS` |
| init program `--validate-only` | `valid=true`、files `0`、options `0` | `PASS` |
| parent gitlink 对 pin | `d31118b` tree 中 Wolvrix=`16a9f49` | `PASS` |
| `git diff --check` | 无错误 | `PASS` |

从 workspace 根目录做过一次 full pytest collection，因该调用目录没有把 SimpleTES 包根放入
`sys.path` 而报 `ModuleNotFoundError: datasets`；它没有运行测试，不计为产品失败。从 SimpleTES 仓库根目录
重跑后的正式结果为 `141/141 PASS`。

## 5. Production 默认生成与 artifact 身份

control canary 使用普通 `options={}` fresh 构建。生成日志显示：

- `commit_exact_event_policy_source=cpp-default`；
- `commit_exact_event_policy_effective=cpp-default`；
- `active_mask_gap_pack_policy_source=cpp-default`，没有用 SimTop 流程额外打开 `targeted-direct`；
- R/W/A 诊断为
  `selected=1, fallback=none, cold_runs=20, cold_guards=46655,`
  `lockstep_groups=2089, lockstep_writes=11799`。

最终 control marker：

- 路径：`/tmp/simpletes-grhsim-simtop-50k/02d8ec0c5cbeb4ef/slot-0/results/control_artifacts.json`；
- marker SHA-256：`9efc276b746f3fac68b38c442080399fb6ea6492751e129d9213f371b105d48e`；
- build-config fingerprint：`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`；
- toolchain fingerprint：`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038`。

| artifact | bytes | SHA-256 |
| --- | ---: | --- |
| generated C++ fingerprint | — | `b55d17026338f4568009ec6659b6913f61070ed9330f939b400bd27e46e7f707` |
| native `emu` | `91,894,296` | `2cea1823cec9ae0da18afc19d3a8e80209da170a7d6338d243cf39c7329f3368` |
| CoreMark image | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| NEMU | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

新 native `emu` 与历史 RWA snapshot 的 bytes 相同，但 generated fingerprint 与 ELF SHA 不同。parent 在旧 pin
到新 pin 之间除文档外只改变 Wolvrix gitlink；生产 `grhsim_cpp.cpp` 又已证明与历史 RWA materialization
逐字节相同。由于 fresh RTL/emit/link 产物仍不能按 SHA 与旧 snapshot 直接等同，后续正式性能没有用“旧 RWA
artifact 等同新 native”的假设搭桥，而是直接测量本节新生成的 native ELF。

## 6. Focused 与 100/10k 功能 gate

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| trusted pybind focused | `29/29` | `PASS` |
| 100-cycle | `instrCnt=0`、`cycleCnt=96`、guest cycles `101`、wall `219 ms` | `PASS` |
| 10k-cycle | `instrCnt=458`、`cycleCnt=9996`、guest cycles `10001`、wall `5,700 ms` | `PASS` |

两个功能 gate 均由 evaluator 用 `setarch x86_64 -R` 执行，并要求 personality 恰为
`00040000`。其日志分别位于新 namespace results 下的 `control_function_100.log` 与
`control_function_10000.log`。

## 7. 50k control canary

canary 是同一 native artifact 的 ABBA 自对照，只验证 production control/runtime readiness，不用于衡量 RWA
相对旧 baseline 的收益。

| 顺序 | role | `Host time spent` |
| ---: | --- | ---: |
| 1 | control | `53,985 ms` |
| 2 | candidate-control | `54,236 ms` |
| 3 | candidate-control | `54,102 ms` |
| 4 | control | `53,684 ms` |

算术均值为：

- control：`53,834.5 ms`；
- candidate-control：`54,169.0 ms`；
- 差值：candidate 慢 `334.5 ms`，即 `-0.621348763%`。

两边是同一 ELF，因此该差值只记录为同物噪声，不作为优化回退，也不触发 BAAB promotion。

运行 placement：

- CCD：`node1:120-127,312-319`；
- measured CPU：`121`；
- SMT sibling：`313`；
- 初始 whole-CCD gate：mean idle `99.75125%`、min idle `98.67%`。

四个样本全部满足：

- `personality=00040000`、单 CPU affinity 正确；
- CPU migrations=`0`，PMU scheduled percent=`100%`；
- binary/NEMU NUMA local ratio=`1.0`；
- 功能签名为 `PC=0x80001312`、`instrCnt=73580`、`cycleCnt=49996`、guest cycles=`50001`；
- 每份 emu log 恰有一个 `Host time spent`。

权威结果：

- `runtime_result_345fe98fbbc4ff3b.json` SHA-256
  `430f297ec3d62a6a507f9ef59797c5f4f119d6a48be7c73446574ea47b0e2ebd`；
- `evaluation_345fe98fbbc4ff3b.json` SHA-256
  `46e427aaf1434c63c10edd4f019beabd57c22110d44fdf65f0282a0b43e16897`。

## 8. 阶段裁决

SimpleTES 已能在 landed RWA 原生默认上建立、验证并运行 control；未来探索可以从新空 control 或同 pin 的
checkpoint 继续。旧 checkpoint fail-close 与历史 materializer 分离都已由测试覆盖。

本阶段不裁决相对旧 baseline 的最终收益。实际 B→native-RWA 的独立 ABBA/BAAB 结果记录在
[TNO0188](./TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)。
