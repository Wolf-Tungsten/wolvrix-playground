# TNO0022 单核 GrhSIM CPU96 补测

## 冻结构建与测量口径

本轮复用 [TNO0020](./TNO0020_completion_and_artifact_manifest_20261110.md) 归档的 before/after native GrhSIM binary，作为新的独立 8 对 AB/BA 系列。历史 [TNO0015](./TNO0015_native_paired_walltime_20261110.md) 保留，不合并或覆盖旧样本。

| 版本 | binary bytes | SHA256 |
| --- | ---: | --- |
| before | 79,340,032 | 54d08d3930f65aa7cb88eade13ab11d270640cec1cb9b3675aa0fd272380ad71 |
| after | 104,473,224 | d62216f60f81b0c0485922913c333997a11dcac0c93d3c3c7bcb8a653637d7f7 |

两侧对应 XiangShan 77ed568fc / defb18e13、完整 DiffTest。配置、RTL、schema、生成 C++ 和工具链身份见 [before manifest](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/model-manifests/before-single.json) 与 [after manifest](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/model-manifests/after-single.json)。本轮不重新生成或编译模型。

node030、单线程 CPU96、NUMA1 严格 membind、关闭 ASLR；运行时验证线程数、实际 CPU affinity、personality 和私有 executable/library/anonymous-state 内存 locality。使用本轮冻结的 CoreMark/NEMU，输入哈希见 [TNO0021](./TNO0021_gsim_paired_walltime_20261111.md)。正式样本关闭 trace/诊断，不做外部 CPU 空闲准入检查。

每侧依次通过 10k smoke、两组独立 100k DiffTest trace 检查、预热，再执行 8 对 AB/BA。跨版本只比较共同终止条件、Guest cycles 和 workload 输出；每个版本内部要求功能签名稳定。统计分别报告内部 Host time 和外部 walltime，使用 seed 20261102 的 10,000 次配对 bootstrap。

本节为测量前的冻结记录；性能和功能结果在完成后追加。执行命令见 [本轮 driver](../../build/artifacts/kunminghu-v3-gsim-followup-20261111/run-followup.py)，完整数据保留在 build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single。

## 增量：功能与放置门通过

两侧 10k smoke 通过。seed 0/1 的两组 100k 独立 NEMU DiffTest、trace 非空/单调/末周期覆盖检查全部通过。每侧两个 seed 的签名一致：

| 版本 | 最后提交 PC | instrCnt | cycleCnt | Guest cycles | 每组 trace records |
| --- | --- | ---: | ---: | ---: | ---: |
| before | 0x80000cde | 238,535 | 99,996 | 100,001 | 100,000 |
| after | 0x80000c1a | 250,838 | 99,995 | 100,001 | 99,999 |

两侧均以 cycle-limit 结束，UART 为 Running CoreMark for 2 iterations（后接换行）。CPU96、单线程、NUMA1 locality 与 ASLR 检查通过。上述诊断运行不计入 walltime 配对统计。

原始验证：[seed 0](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/trace-s0.json)、[seed 1](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/trace-s1.json)。正式 8 对计时另行追加结果。

## 增量：8 对正式计时结果

8 对 AB/BA、16 个正式样本全部通过功能与放置门。所有通过门的慢样本均保留；诊断、预热和构建时间不进入统计。正数表示 after 更慢。

| 指标 | before 均值 / 中位数 (s) | after 均值 / 中位数 (s) | 配对 delta 均值 / 中位数 | bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Host time | 110.579 / 110.975 | 145.329 / 144.085 | +31.459% / +29.542% | [+28.719%, +35.527%] |
| 外部 walltime | 110.628 / 111.025 | 145.393 / 144.148 | +31.460% / +29.542% | [+28.721%, +35.525%] |

after 更快 0/8 对。本轮 Host time 区间完全高于零，合并后更慢。
这是各 revision 的 DefaultConfig 和所跟踪 DiffTest 的整体比较，不能解释为仿真器后端的隔离优化收益。

| 对（原始索引 + 1） | 顺序 | before Host (s) | after Host (s) | Host delta | before 外部 (s) | after 外部 (s) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | AB | 111.240 | 144.153 | +29.587% | 111.290 | 144.215 |
| 2 | BA | 109.809 | 144.783 | +31.850% | 109.858 | 144.847 |
| 3 | AB | 110.711 | 142.867 | +29.045% | 110.759 | 142.931 |
| 4 | BA | 111.964 | 144.989 | +29.496% | 112.011 | 145.054 |
| 5 | AB | 112.037 | 144.018 | +28.545% | 112.085 | 144.080 |
| 6 | BA | 109.508 | 158.396 | +44.643% | 109.557 | 158.460 |
| 7 | AB | 107.335 | 141.350 | +31.691% | 107.382 | 141.417 |
| 8 | BA | 112.031 | 142.076 | +26.818% | 112.078 | 142.138 |

证据：[summary](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/summary.json)、[逐对 JSON](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/pairs.json)、[逐对 CSV](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/pairs.csv)、[运行 manifest](../../build/xs/kunminghu-v3-gsim-followup-20261111/grhsim-single/manifest.json)。
