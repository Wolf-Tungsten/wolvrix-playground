# TNO0208 Four-positive SimpleTES repin and native 50k

## 1. 阶段目标与最终结论

[TNO0207](./TNO0207_four_positive_wolvrix_landing_and_regression_20260731.md) 已将四项优化落入 Wolvrix
通用默认源码。本阶段完成三件事：

1. 把 SimpleTES bench 从旧 RWA executable pin 迁移到 landed four-positive pin；
2. 用 patch 为空、options 为空的 production control fresh 生成真实 native 默认 ELF，并通过功能 canary；
3. 用同 CCD、关闭 ASLR 的完整 ABBA+BAAB 比较旧 RWA 与实际 landed native-four。

最终正式 SimTop 50k Host time spent 为：

53,749.25 -> 51,575.00 ms，绝对减少 2,174.25 ms，改善 4.045173%。

被选中的第二轮 ABBA/BAAB 分别改善 4.066901% 和 4.023443%，order gap 只有
0.043458 percentage point，严格低于 0.25 pp 门槛。功能、whole-CCD quiet、fixed-ASLR、affinity、
NUMA、PMU 和 migration 审计全部通过。

最终裁决为 KEEP：四项继续作为 Wolvrix 通用 C++/Python 默认；不增加 SimTop 专用开启，不借用或默认开启
targeted-direct。SimpleTES 已能从新的空 control 继续研究，但本阶段没有启动 auto research。

## 2. SimpleTES repin 身份

固定身份如下：

| 对象 | identity |
| --- | --- |
| Wolvrix landed default | fd12d83f5150cc98540ed3e8f2af3b79f8054da0 |
| parent executable snapshot | de37459cdd210794fa5d7423e6f32c145cf71261 |
| SimpleTES repin commit | de12067713618cd30c266d95684355c0816b94d0 |
| grhsim_cpp.cpp SHA-256 | a42690f9f85300a7f8311e07874329a8f02ae0e7aa870af5474e2f3729fdfb82 |
| evaluator.py SHA-256 | ee87ecb3f101414575f30007a32d2c91ad7eabfe187ca47befc21db9e96c5c37 |
| runtime.py SHA-256 | fd3bb81b7295f90aed63ef6a829277563be4093ea26f76be22d6927f36f93f97 |
| env.sh SHA-256 | 3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a |
| new empty-control digest | 87c4e574878b47fe045475c798a462b6a5ac1f5ee1bb2a5df106796ca81a22bf |

repin 修改五个文件：evaluator.py、init_program.txt、instruction.txt、bench README 和
tests/test_grhsim_bench.py。新 instruction 明确 candidate patch 相对 fd12d83... 生成，并禁止重复提出四项
已落地机制以及已关闭的 residual MemoryRead/physical zero-tail。旧 pre-RWA 与旧 RWA pin/checkpoint
不能作为新 namespace 的 resume 或 seed。

验证结果：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| focused bench pytest | 80/80，4.12 s | PASS |
| SimpleTES full pytest | 245/245，9.36 s，24 条既有 deprecation warnings | PASS |
| init program validate-only | valid=true，files=0，options=0 | PASS |
| parent tree gitlink | de37459... tree 中 Wolvrix=fd12d83... | PASS |
| launcher dry-run | 完整命令成功组装，未执行模型或 research | PASS |
| git diff --check | 无错误 | PASS |

最初一次 unittest 调用因模块路径歧义收集到 0 个产品测试；随后使用正确的直接脚本和仓库根执行方式取得
上述正式结果。该调用发现不计为产品失败。

## 3. Production 空 control 与默认来源

新 pin 派生出的独立 evaluator namespace 为：

/tmp/simpletes-grhsim-simtop-50k/0a352faa944d52d7/slot-0

它没有复用旧 namespace 的 build cache。production control 的 patch 为空、enable_options 为空，
fresh evaluator 总耗时 2,524.2628 s。生成日志确认：

- active_mask_gap_pack_policy_source/effective=cpp-default；
- commit_exact_event_policy_source/effective=cpp-default；
- 没有 SimTop wrapper 或 targeted-direct 为四项额外打开 option；
- 四项直接来自 fd12d83... 的通用 emitter 默认。

control marker 和主要产物：

| 对象 | bytes | SHA-256 / fingerprint |
| --- | ---: | --- |
| control_artifacts.json | 1,360 | 8844885e64b58d7cef0cd057cfbb49328c40f9b2a35ee42e606591f6e1dba097 |
| generated C++ fingerprint | — | d36378e381f03a28723109b14d5dee636e204d141c4992df5675657c6e390cc4 |
| native emu | 90,873,536 | ba8cd1458a9e31f966b6e63d454173d9338a3d2f68515d3238ff002da2328d21 |
| CoreMark image | 16,712 | c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e |
| NEMU | 567,504 | 094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e |

production 功能 gate：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| trusted focused | 29/29 | PASS |
| 100-cycle | instrCnt=0，cycleCnt=96，guest cycles=101，wall=176 ms | PASS |
| 10k-cycle | instrCnt=458，cycleCnt=9996，guest cycles=10001，wall=5,433 ms | PASS |

同一 landed ELF 的 50k canary 样本为 control 51,664/51,726 ms、candidate-control
51,780/51,663 ms；均值 51,695.0 -> 51,721.5 ms，差 -26.5 ms / -0.051262%。两臂逐字节相同，
该差只作为噪声与 runtime readiness 记录。canary 固定 node0:0-7,192-199、CPU 0 / sibling 192，所有
ASLR、whole-CCD、affinity、NUMA、PMU、0 migration 与功能门禁通过。

canary 权威结果：

- runtime result SHA-256：91b995510bbcaa9cd1d8a3a349d38e7a20cd98aca2d8064b752cf97b814a5e21；
- evaluation SHA-256：3b1e36b466ffad042365c71a15313ec50f2ae2403ff5b6da52a0e8c692ff5694。

## 4. 正式比较对象与协议

正式端点为：

| arm | code identity | generated fingerprint | emu bytes | emu SHA-256 |
| --- | --- | --- | ---: | --- |
| RWA control | parent d31118b / Wolvrix 16a9f49 | f28f2a696328175f0fe76e2e16895b44fbe54320506776eb6a5c436674c72077 | 91,894,296 | 29c31618b10e7ae18f986de76888781b9308e69bcd71a45ea38b8c83c56d6221 |
| native four | parent de37459 / Wolvrix fd12d83 | d36378e381f03a28723109b14d5dee636e204d141c4992df5675657c6e390cc4 | 90,873,536 | ba8cd1458a9e31f966b6e63d454173d9338a3d2f68515d3238ff002da2328d21 |

两端使用相同 CoreMark image 与 NEMU，哈希见第 3 节。headline 只取 emu log 唯一的
Host time spent walltime：

1. 每轮都完整执行 ABBA 和 BAAB，各 order 中 control/candidate 各两个样本；
2. 同一轮的两个 order 必须固定同一完整 CCD、measured CPU 和 SMT sibling；
3. 每个样本前检查 whole-CCD quiet，并持续监视目标 CCD；
4. 所有 runtime 使用 setarch x86_64 -R，personality 必须为 00040000；
5. affinity、NUMA residency、PMU scheduling、CPU migration、功能签名和唯一 walltime 都是硬门禁；
6. 只有完整有效且 ABBA/BAAB improvement gap 严格小于 0.25 pp 的轮次可以成为正式结果。

## 5. Round 1：有效但因 order gap 丢弃

placement 固定 node0:24-31,216-223、CPU 24 / sibling 216。

| order | sequence walltime (ms) | control mean | native-four mean | 改善 |
| --- | --- | ---: | ---: | ---: |
| ABBA | 53,758 / 51,616 / 51,684 / 53,670 | 53,714.0 | 51,650.0 | 3.842574% |
| BAAB | 51,476 / 53,731 / 53,810 / 51,482 | 53,770.5 | 51,479.0 | 4.261630% |

该轮 pooled 为 53,742.25 -> 51,564.50 ms，绝对减少 2,177.75 ms，改善 4.052212%。所有功能和
运行审计有效，两个 order 也确实使用同一 CCD/CPU；但 order gap=0.419057 pp，大于 0.25 pp，故不能作为
正式结果。脚本没有挑选其中较好 order，而是换空闲 CCD 重跑完整 pair。

## 6. Round 2：正式选中结果

placement 固定 node0:72-79,264-271、CPU 72 / sibling 264。

| order | sequence walltime (ms) | control mean | native-four mean | 绝对减少 | 改善 |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | 53,810 / 51,675 / 51,455 / 53,692 | 53,751.0 | 51,565.0 | 2,186.0 ms | 4.066901% |
| BAAB | 51,520 / 53,760 / 53,735 / 51,650 | 53,747.5 | 51,585.0 | 2,162.5 ms | 4.023443% |
| pooled | control 4 samples / candidate 4 samples | 53,749.25 | 51,575.00 | 2,174.25 ms | 4.045173% |

order gap 为 0.043458 pp，因此第二轮是第一组严格满足门槛的完整 pair。headline 使用 pooled 八个样本，
没有混入 Round 1。

selected PMU 算术均值也与 walltime 方向一致：

| event | RWA control | native four | delta |
| --- | ---: | ---: | ---: |
| cycles:u | 197,007,249,017.00 | 189,024,874,113.75 | -4.051818% |
| instructions:u | 162,370,518,557.75 | 158,921,729,969.75 | -2.124024% |
| frontend no-ops | 875,316,869,548.25 | 830,213,474,369.25 | -5.152808% |
| frontend cmask no-dispatch | 112,559,192,641.75 | 105,522,984,291.75 | -6.251118% |
| backend stalls | 75,023,421,240.25 | 75,614,128,250.00 | +0.787363% |

八个正式样本均满足 personality=00040000、精确单 CPU affinity、CPU migrations=0、PMU scheduled
percent=100%、binary/NEMU NUMA local ratio=1.0、完整功能签名与唯一 walltime。初始 whole-CCD gate
16 个逻辑 CPU 的 mean/min idle 均为 100%。

## 7. Artifact 完整性

native snapshot：

build/grhsim_bestpath_ablation_20260731/landing_rwa_to_native_four_v1/artifacts/landed_native_default

- provenance.json SHA-256：
  fd7d8da4e2198815aa212e3dfb07c711ff5177e0432d55dc18e7c5c4b536574b；
- SHA256SUMS SHA-256：
  034d2ffe40d04f1366e95c2a66e6f70961ecd58b8937257713f52ab297bb6872；
- 对 emu、CoreMark、NEMU、source marker 和 provenance 执行 sha256sum -c，全部 OK。

正式结果目录：

build/grhsim_bestpath_ablation_20260731/landing_rwa_to_native_four_v1/results_gap_lt_0p25

| 文件 | SHA-256 |
| --- | --- |
| summary.json | a181c76fa478ba9db6b987e05f17741121aceae0f774f531c68d788877159209 |
| round-1/result.json | 8390aab756dbf488114351d30ded5e83ced2156b53f872b64b44961240b621f5 |
| round-2/result.json | 19e992c0169bd8466ca4fb95706d462cb504f75566238907b6c50d8dadcc7195 |

## 8. 默认与继续探索裁决

相对旧 RWA 的实际 landed native default 有 2,174.25 ms / 4.045173% 的稳定端到端 walltime 收益，
且方向在 ABBA/BAAB 一致，远高于 order gap。因此四项保持通用默认开启。

SimpleTES 已 repin 到新的 post-four empty control，并通过 focused/full、validate-only、production build、
功能 canary 和 launcher dry-run。后续研究必须以 fd12d83... 为 patch 基线，不再重复这四项，也不把
residual MemoryRead 或 physical zero-tail 当作已默认机制。离线 dry-run 只验证启动链；本阶段没有创建
正式 research instance、没有调用模型，也没有擅自继续 auto research。
