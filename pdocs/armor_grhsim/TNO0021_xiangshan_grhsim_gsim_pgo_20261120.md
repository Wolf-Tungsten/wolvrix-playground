# TNO0021：XiangShan 单模型 GrhSIM 和 GSIM 的 PGO 性能

CoreMark 的前 10 万周期，用同一窗口训练后，GrhSIM 开启 PGO 的平均耗时变化为 **-8.73%**，GSIM 为 **-31.56%**。换到未参与训练的 MicroBench 窗口，两者分别为 **-7.41%** 和 **-32.52%**。

## 模拟器运行时间

表中秒数是四次外部 walltime 的算术平均。百分比是同一轮开启相对关闭的耗时变化，再对四轮取平均。每次运行使用同一个周期上限和同一份参考库。[32 次正式运行](./data/TNO0021_xiangshan_pgo_times.csv) · [配对统计](../../build/armor-xs-pgo-v1/summary.json)

| 测量负载 | 模拟器 | PGO 关 | PGO 开 | 同轮耗时变化 | 95% 配对 bootstrap 区间 | 开启更快 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark | GrhSIM | 88.27 s | 80.56 s | -8.73% | [-9.74%, -7.11%] | 4/4 |
| CoreMark | GSIM | 95.48 s | 65.34 s | -31.56% | [-31.77%, -31.33%] | 4/4 |
| MicroBench | GrhSIM | 85.72 s | 79.36 s | -7.41% | [-8.15%, -6.75%] | 4/4 |
| MicroBench | GSIM | 89.62 s | 60.47 s | -32.52% | [-33.22%, -31.66%] | 4/4 |

在四个版本同轮交错的 CoreMark 对照中，以同样 PGO 设置的 GSIM 耗时作分母，GrhSIM 的相对耗时在 PGO 关闭时为 **-7.55%**，开启时为 **+23.28%**。[CoreMark 运行顺序](../../build/armor-xs-pgo-v1/timing/coremark/policy.json)

## 构建和训练

- 设计为 XiangShan `defb18e13` 的单核 `DefaultConfig`。GrhSIM 复用 ARMOR 系列 TNO0017 的默认单模型生成代码，成排累加、eager 阈值 4096、x86 内存 cmov 开启，TNO0020 的三组实验开关关闭。GSIM 使用上游 `a3ecb26`，输入取自同一批 SystemVerilog 导出时保存的 `SimTop.fir`，SHA-256 为 `74e28f0449f50ed9461310858d4cf7d0bcd7b9985d0bbb6f16bcda4fdcf48664`。GSIM 采用 `--supernode-max-size=15 --cpp-max-size-KB=8192`，生成 409 个 C++ 源文件。旧 GSIM 缓存来自同一配置的另一次展开，输入哈希不同，因此本轮重新生成。[生成日志](../../build/armor-xs-pgo-v1/gsim-source/generate.log) · [输入核对](../../build/armor-xs-pgo-v1/fir-identity.json)
- 每个后端的关闭版、插桩版和 profile 回编版使用相同的模型源文件。两边均用 Clang 23.1.2 和 `-O3 -march=native` 编译，PGO 同时覆盖模型和 DiffTest harness。编译机 node029 和计时机 node030 上 Clang 的 native target 均为 `znver4`，115 个目标特性相同。NEMU 参考库为同一份预编译文件。[构建脚本](../../scripts/armor_xs_pgo_build.py) · [编译和输入审计](../../build/armor-xs-pgo-v1/build-identity.json)
- 每个后端用自己的 `-fprofile-generate` 可执行文件单独跑一次 CoreMark 前 10 万周期，seed 0，NEMU DiffTest 开启，训练时关闭轨迹写出。只在训练版加 `-fno-slp-vectorize`，用来避开本机 Clang 23 编译插桩代码的已知错误。各自只合并这一次的 profraw，再以 `-fprofile-use` 重编全部模型和 harness。两组正式可执行文件均启用编译器默认的 SLP，关闭训练插桩、BOLT 和波形。MicroBench 使用同一份 CoreMark profile。表中秒数仅包含运行模拟器的外部 walltime。[GrhSIM 的 profile](../../build/armor-xs-pgo-v1/grhsim/profile/show.log) · [GSIM 的 profile](../../build/armor-xs-pgo-v1/gsim/profile/show.log) · [训练编译器问题记录](./TNO0016_branch_sources_and_eager_logic_20261120.md)
- 正式运行均在 node030，固定 CPU 96、NUMA 1、单线程、ASLR 关闭。每个负载和版本各预热一次。CoreMark 每轮交错测试四个可执行文件，四轮中每个版本在每个位置上各出现一次。MicroBench 在同一颗 CPU 上按后端分开计时，每个后端各四对，交替顺序为关→开、开→关。每次都核对运行终点、线程绑定和 NUMA。配对区间使用固定种子对四个同轮耗时比有放回重采样 10,000 次。[计时脚本](../../scripts/armor_xs_pgo_measure.py) · [逐次原始耗时](./data/TNO0021_xiangshan_pgo_times.csv)

复测可在已有上述冻结输入的 node029 上运行 `python3 scripts/armor_xs_pgo_build.py`，再分别运行 `python3 scripts/armor_xs_pgo_measure.py verify grhsim` 和 `verify gsim`。在 node030 上依次给同一计时脚本传入 `time microbench grhsim`、`time coremark both`、`time microbench gsim`。本轮的运行目录是 `build/armor-xs-pgo-v1/`。[构建身份和结果导出](../../scripts/armor_xs_pgo_results.py)

## 功能核对

已核对编译命令。GrhSIM 的 137 个模型文件和 55 个 harness 文件、GSIM 的 409 个模型文件和 57 个 harness 文件均收到所选的 profile 参数。两种正式构建均无 LLVM 计数插桩段，回编日志中未发现 profile 缺失或不匹配的警告。各后端在两个负载上做了开关间的完整 DiffTest 有效字段比较，训练版另做一次 CoreMark 轨迹核对，该次产生的数据与训练 profile 分开保存。[GrhSIM 核验](../../build/armor-xs-pgo-v1/grhsim/verify/result.json) · [GSIM 核验](../../build/armor-xs-pgo-v1/gsim/verify/result.json)

| 负载 | 模拟器 | 停止 PC | 已提交指令 | 末端架构周期 | 开、关匹配的轨迹记录 |
| --- | --- | --- | ---: | ---: | ---: |
| CoreMark | GrhSIM | `0x80000c1a` | 250,838 | 99,995 | 99,999 |
| CoreMark | GSIM | `0x80000c10` | 250,845 | 99,997 | 99,999 |
| MicroBench | GrhSIM | `0x80000446` | 138,514 | 99,995 | 99,999 |
| MicroBench | GSIM | `0x8000044e` | 138,523 | 99,997 | 99,999 |

两后端在相同 `-C 100000` 参数下都报告 100,001 个 guest cycles，停止位置相差两个架构周期。按提交顺序对比有效提交包的 PC、机器指令和融合数，CoreMark 前 164,997 个包一致，MicroBench 前 109,222 个包一致，均覆盖较短轨迹的全部有效提交包。上述绝对秒数衡量这个固定周期窗口，训练和测量均未运行至固件结束。[跨后端提交序列](../../build/armor-xs-pgo-v1/cross-engine-commit-prefix.json) · [复核脚本](../../scripts/armor_xs_pgo_results.py)
