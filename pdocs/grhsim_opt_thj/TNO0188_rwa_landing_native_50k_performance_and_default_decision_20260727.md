# TNO0188 RWA landing native 50k performance and default decision

## 1. 阶段目标与结论

本阶段对实际落地后的 Wolvrix 通用默认生成物执行最终 SimTop 50k 回归。比较两端为：

- `B`：RWA 落地前、默认生成配置的固定 baseline ELF；
- `native-RWA`：Wolvrix `16a9f493687a21a5428f1e1327a69834ea60c9f5` 在普通
  `options={}` 下 fresh 生成的 production ELF。

正式 `Host time spent` walltime 的 pooled 结果为：

`60,881.50 -> 54,088.00 ms`，绝对减少 `6,793.50 ms`，改善 `11.158562%`。

ABBA 与 fresh BAAB 分别改善 `11.135149%` 和 `11.182077%`，方向一致；8/8 accepted 样本的
quiet-CCD、fixed-ASLR、affinity、NUMA、PMU、migration 与功能签名审计全部通过。因此最终状态为
`valid_direction_consistent_positive`，本次 R/W/A 端到端落地回归 `PASS`。

最终默认裁决：**R/W/A 保留在 Wolvrix 通用 C++/Python 生成流程的默认路径；F 继续排除，
`targeted-direct` 继续默认关闭。** 不增加 SimTop 专用开启逻辑。

## 2. 固定代码与 artifact 身份

正式回归固定以下代码身份：

| 对象 | identity |
| --- | --- |
| Wolvrix landing | `16a9f493687a21a5428f1e1327a69834ea60c9f5` |
| parent executable snapshot | `d31118bea0feb563ad09476e1419f0f15aaf574f` |
| SimpleTES repin | `b0c7754651c84cd4de5e02aa01bad67fa2c0ae4a` |
| `evaluator.py` SHA-256 | `0fbdc274d87a3ff115bc8f2a7ec016970cb9124dbd2c2db752602468341414ce` |
| `runtime.py` SHA-256 | `fd3bb81b7295f90aed63ef6a829277563be4093ea26f76be22d6927f36f93f97` |
| `env.sh` SHA-256 | `3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a` |

两端 artifact 为：

| arm | generated fingerprint | `emu` bytes | `emu` SHA-256 |
| --- | --- | ---: | --- |
| `B` | `9ad3a09d170442b2ea4d2cc1610eede86611ebddf6d49127b4fbee9eba3af989` | `91,673,112` | `124fd103f2bf428659123313a5ebeb14bae321ebe6eaea7f5a6625bec6a27dbc` |
| `native-RWA` | `b55d17026338f4568009ec6659b6913f61070ed9330f939b400bd27e46e7f707` | `91,894,296` | `2cea1823cec9ae0da18afc19d3a8e80209da170a7d6338d243cf39c7329f3368` |

两端使用逐字节相同的 CoreMark image 和 NEMU：

- image：`16,712 B`，SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；
- NEMU：`567,504 B`，SHA-256
  `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。

`native-RWA` 来自 [TNO0187](./TNO0187_rwa_landing_simpletes_repin_and_native_control_canary_20260727.md)
记录的新 namespace production control marker，marker SHA-256 为
`9efc276b746f3fac68b38c442080399fb6ea6492751e129d9213f371b105d48e`。历史 RWA artifact 与新 native
虽然 bytes 相同，但 ELF SHA 与 generated fingerprint 不同；因此本阶段没有提前假定二者等价，而是直接测试
实际落地后 fresh 生成的 native ELF。

## 3. 正式协议

headline 只取 SimTop 50k emu log 中唯一的 `Host time spent`：

1. 先执行 ABBA；有效且正向后始终 fresh 执行 BAAB；
2. 每个 order 的 control/candidate 各 `2` 个样本，pooled 为 `4+4`；
3. 每个 attempt 动态选择完整空闲 CCD，同一 order 固定 CCD、CPU 与 SMT sibling；
4. 每个 runtime 用 `setarch x86_64 -R`，并审计 personality 必须恰为 `00040000`；
5. affinity、binary/NEMU NUMA residency、连续 idle monitor、PMU scheduling、CPU migration、功能签名和唯一
   walltime 都是硬门禁；
6. retryable infrastructure attempt 整组丢弃，不把部分 raw 样本拼入 headline；每个 order 上限 `9` 次。

runner 在执行前后重新核对代码 pin、control marker 和所有输入 SHA。其 SHA-256 为
`953f4599653430e71b0759a4ab60dc3bba8093976c31a73daf66cf200d2f9c44`；执行前的 `--validate-only`
和语法检查均通过。

## 4. Attempt 与逐样本结果

### 4.1 被丢弃的纯 infrastructure attempt

ABBA attempt 1 初始选中 `node1:168-175,360-367`、CPU `168` / sibling `360`。初始 admission
通过，但首个样本前 fixed-CCD 复核降到 mean idle `97.5575%`、min idle `69.9%`，未满足阈值；该 attempt
以 `retryable_infra=true` 结束，没有形成有效 group，唯一已产生的 control raw 样本也没有进入任何汇总。

### 4.2 Accepted ABBA

placement 为 `node1:128-135,320-327`、CPU `132` / sibling `324`；初始 whole-CCD gate 为 mean idle
`99.730625%`、min idle `99.0%`。

| 顺序 | arm | `Host time spent` |
| ---: | --- | ---: |
| 1 | B | `61,028 ms` |
| 2 | native-RWA | `54,167 ms` |
| 3 | native-RWA | `54,273 ms` |
| 4 | B | `61,000 ms` |

ABBA 均值为 `61,014.00 -> 54,220.00 ms`，绝对减少 `6,794.00 ms`，改善
`11.135149%`；B/native-RWA spread 分别为 `28/106 ms`。

### 4.3 Accepted fresh BAAB

placement 为 `node0:8-15,200-207`、CPU `8` / sibling `200`；初始 whole-CCD gate 为 mean idle
`99.625%`、min idle `98.33%`。

| 顺序 | arm | `Host time spent` |
| ---: | --- | ---: |
| 1 | native-RWA | `53,870 ms` |
| 2 | B | `60,693 ms` |
| 3 | B | `60,805 ms` |
| 4 | native-RWA | `54,042 ms` |

BAAB 均值为 `60,749.00 -> 53,956.00 ms`，绝对减少 `6,793.00 ms`，改善
`11.182077%`；B/native-RWA spread 分别为 `112/172 ms`。

## 5. Pooled walltime 与审计

| 汇总 | B mean | native-RWA mean | 绝对减少 | 改善 | combined score |
| --- | ---: | ---: | ---: | ---: | ---: |
| ABBA + BAAB | `60,881.50 ms` | `54,088.00 ms` | `6,793.50 ms` | `11.158562%` | `1.1256008727` |

pooled B range/spread 为 `60,693..61,028 ms / 335 ms`，native-RWA 为
`53,870..54,273 ms / 403 ms`。`11.158562%` 同时远高于 `1%` 信任线和 B 的
`0.550249%` spread，且两种 order 的改善只相差约 `0.047` percentage point。

8 个 accepted 样本逐一复核为：

- personality 全部 `00040000`，地址随机化确实关闭；
- affinity 全部精确绑定目标 CPU，CPU migrations 全部为 `0`；
- PMU event 与 task-clock audit 全部通过，关键 event scheduled percent 为 `100%`；
- binary 与 NEMU NUMA local ratio 全部为 `1.0`；
- 功能签名全部为 `PC=0x80001312`、`instrCnt=73580`、`cycleCnt=49996`、guest cycles=`50001`；
- 每份 emu log 恰有一个合法 walltime。

因此性能变化不是由测试镜像、NEMU、ASLR、跨 CPU migration 或失败样本混入造成。

## 6. 与历史 endpoint 的交叉验证和边界

[TNO0185](./TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md) 的历史 materialized
`B -> RWA` pooled 结果是 `60,583.50 -> 53,992.75 ms`，减少 `6,590.75 ms / 10.878787%`。
本次实际 native landing 为 `11.158562%`；两次 fresh endpoint 均双 order 稳定正向，量级一致。

现有正式证据包含 direct `R`、direct `W`、direct `A`、两次 `F`、历史 B→RWA endpoint，以及本次
B→native-RWA final regression。没有把 `RW -> RWA` 写成同 session 正式 walltime：该臂此前只有
validate-only，A 的保留由独立 direct A 与两次无 F endpoint 共同支撑。

## 7. Artifact 完整性

正式目录：

`build/grhsim_rwa_landing_20260727/direct_runs/native_rwa_regression_20260727_234000/`

| 文件 | SHA-256 |
| --- | --- |
| `result.json` | `c5c8856f30feaeae35741d4bbccbe2d797843f5cf7e454fd9f75ba3407a367c4` |
| `provenance.json` | `6fc60982058ba7d870091920b5373941d74941914b7df4edaf6e805f87ec3593` |
| `SHA256SUMS` | `5a029816276b4bdeee437eb595edd0434aecfad414fb3d0ece041a0f92777b2a` |

对 `SHA256SUMS` 执行完整 `sha256sum -c` 后，ABBA 两个 attempts、BAAB、所有 audit、emu log、monitor、
perf CSV、group result、provenance 与最终 result 全部为 `OK`。

## 8. 最终落地与继续研究裁决

本轮闭合后的生产状态是：

- `R/W` 使用既有通用 `commit_exact_event_policy=targeted-cold-layout` C++ 默认；显式 `off` 关闭二者，
  W 只在 R admission 成功的 run 内生效；
- `A` 是独立的通用 C++ 默认，不借用 R/W 或 `targeted-direct` 开关；
- `F` 未进入生产源码；
- `active_mask_gap_pack_policy=targeted-direct` 仍默认关闭；
- Python `None` 与 XS 未设置 override 继续继承 C++ 默认，没有 SimTop 专用打开动作。

代码、fresh/full regression、production canary 与 final 50k 均通过，故 R/W/A 默认开启的最终裁决为
`KEEP`。SimpleTES 已 repin 到该 landed baseline，并对旧 checkpoint fail-close；后续可以从新空 control
继续探索，但本阶段没有自动启动 research。

## 9. 增量勘误 2026-07-28：ABBA attempt 1 失败时点

第 4.1 节“首个样本前 fixed-CCD 复核”表述不准确。实际时序是：attempt 1 已完成第一个 B/control raw
样本，`Host time spent=60,401 ms`；随后在第二个 candidate 样本前的 fixed-CCD 复核中出现 mean idle
`97.5575%`、min idle `69.9%`，整组被标记为 retryable。

该 raw control 功能审计通过，但 attempt result 明确为 `valid=false`、`samples=[]`，没有进入 accepted ABBA、
BAAB 或 pooled headline。此勘误只修正失败时点，不改变 `60,881.50 -> 54,088.00 ms / 11.158562%`
结论、artifact SHA 或默认裁决。
