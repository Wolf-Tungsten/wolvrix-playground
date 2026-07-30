# SimpleTES RWA to gen150 endpoint replication

## 1. 阶段结论

在 [TNO0205](./TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md) 的六项
`final-minus-one` 消融之后，本轮直接复测“六项优化前”的当前默认 RWA 与“六项全部存在”的完整
gen150 endpoint。正式 SimTop 50k pooled walltime 为：

```text
current-default RWA control : 53,747.00 ms
full gen150 candidate       : 51,524.50 ms
absolute reduction          :  2,222.50 ms
relative improvement        :      4.135115%
```

ABBA 为 `53,754.50→51,504.50 ms`，减少 `2,250.00 ms/4.185696%`；BAAB 为
`53,739.50→51,544.50 ms`，减少 `2,195.00 ms/4.084519%`。两个 order 使用完全相同的 node1
CCD `152-159,344-351` 与 CPU `152/344`，收益 gap 为 `0.101177` 个百分点，严格小于此前约定的
`0.25 pp`，因此首轮即成为正式结果，无需继续复测。

这个 endpoint 明确证明六项组合相对 RWA 仍有约 `4.14%` 的端到端收益。它不改变逐项消融结论：
cold assertion 是强正向，inline/constant/shift 是弱正向，而 residual MemoryRead 与 physical
zero-tail 在完整 final 上分别造成小幅回退。endpoint 只能说明“六项整体比 RWA 快”，不能据此把两个
负 marginal 机制判为应保留。

## 2. 两端 artifact 身份

两端共同固定为 parent `d31118bea0feb563ad09476e1419f0f15aaf574f`、Wolvrix
`16a9f493687a21a5428f1e1327a69834ea60c9f5`，且 build-config fingerprint
`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`、toolchain fingerprint
`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038` 完全相同。

| endpoint | generated fingerprint | ELF bytes | ELF SHA-256 |
| --- | --- | ---: | --- |
| current-default RWA | `f28f2a696328175f0fe76e2e16895b44fbe54320506776eb6a5c436674c72077` | `91,894,296` | `29c31618b10e7ae18f986de76888781b9308e69bcd71a45ea38b8c83c56d6221` |
| full gen150 | `ff5888f25297d2285b3715f38cb5f9e6bf8ff51958b28c4986f4c4dd5278ca0b` | `90,873,536` | `7e5ffc22fd309c0fb3fe4f5789591bd6bffaed3e55f2a7fda2e39f58d090ffa9` |

RWA 来自 SimpleTES production evaluator 的 immutable control marker；snapshot 前再次核对 parent 与
Wolvrix tracked worktree 均干净、marker artifact SHA-256 与 gen150 parallel-build summary 内记录的
shared control identity 逐项一致。gen150 是 TNO0204/TNO0205 已验证的 default-path、零 option final。
两端使用逐字节相同的：

- CoreMark image：`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`，`16,712 B`；
- NEMU：`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`，`567,504 B`。

RWA control 与 gen150 均已有 trusted focused `29/29`、fixed-ASLR 100-cycle 和 10k-cycle 功能门禁；
snapshot 的完整 `SHA256SUMS` 在 endpoint 启动前重新验证通过。

## 3. 正式协议与重试

本轮继续使用 `run_pair_sameccd.py`：每个完整 paired attempt 只有一个 `GrhSimRuntime`，ABBA 选定
placement 后，BAAB 必须复用相同 CPU、SMT sibling、whole CCD、NUMA node 和 helper CPU。任一 order
污染就丢弃整个八样本 attempt。

外层 `run_endpoint_until_gap.py` 固定选择“按时间顺序首个 valid、同 CCD 且 order gap 严格小于
`0.25 pp` 的完整 pair”。它不会从多个达标结果中挑收益最大的轮次。

第 1 轮的 paired attempt 1..4 均在运行任何 workload 前报
`no dynamically discovered CCD passed the strict quiet-window gate`，accepted sample 为 `0`。attempt 5
找到 node1 CCD `152-159,344-351`，完整 ABBA+BAAB 一次通过。四个 quiet-window failure 仅作为
基础设施历史保留，没有进入性能均值。

## 4. 正式 walltime 样本

| order | 运行次序 | RWA samples / ms | gen150 samples / ms | RWA→gen150 |
| --- | --- | --- | --- | ---: |
| ABBA | RWA, gen150, gen150, RWA | `53875,53634` | `51477,51532` | `53,754.50→51,504.50 ms`，`+4.185696%` |
| BAAB | gen150, RWA, RWA, gen150 | `53758,53721` | `51484,51605` | `53,739.50→51,544.50 ms`，`+4.084519%` |
| pooled | 四个 RWA + 四个 gen150 | `53875,53634,53758,53721` | `51477,51532,51484,51605` | `53,747.00→51,524.50 ms`，`+2,222.50 ms/+4.135115%` |

RWA spread 为 `241 ms`，即 control mean 的 `0.448397%`；gen150 spread 为 `128 ms`，即 candidate
mean 的 `0.248426%`。pooled `4.135115%` 显著超过预注册可信线
`max(1%, control spread/control mean)=1%`，且两个 order 都为正向，因此是可信 endpoint 收益。

## 5. 八个样本的质量审计

正式八个 sample 全部满足：

- `same_ccd_cpu_across_orders=true`，expected CPU 只有 `152`，CPU migrations 总数为 `0`；
- `setarch x86_64 -R` 生效，process personality 全部为 `00040000`；
- process affinity、resolved executable、pre-gate、continuous monitor gate 全部通过；
- task-clock 与所有 PMU event 的最小 scheduled ratio 均为 `100.0%`；
- binary/NEMU NUMA local-page gate 全部通过；
- guest cycle、terminal PC、功能 signature 全部通过；每个 emu log 恰好一个 `Host time spent`，且与
  result JSON 一致。

因此没有发现 CPU 迁移、ASLR、跨 CCD、NUMA first-touch、PMU multiplexing 或外部负载污染造成的
有效性缺口。

## 6. PMU 解释

正式四个 gen150 sample 相对四个 RWA sample 的均值变化为：

| event | RWA mean | gen150 mean | gen150 相对变化 |
| --- | ---: | ---: | ---: |
| cycles:u | `196,945,776,770.25` | `188,770,993,612.75` | `−4.150779%` |
| instructions:u | `162,370,483,849.75` | `158,917,266,945.75` | `−2.126752%` |
| frontend no-ops | `875,110,520,538.25` | `829,355,646,360.75` | `−5.228468%` |
| frontend-starved | `112,522,368,359.75` | `105,386,623,748.50` | `−6.341623%` |
| backend stalls | `75,004,087,954.00` | `75,017,454,630.00` | `+0.017821%` |

cycles 的 `−4.150779%` 与 walltime 的 `−4.135115%` 高度一致；组合优化减少约 `2.13%` 动态
instructions，更显著地减少 `5.23%/6.34%` 的两类前端空泡，而 backend stalls 基本不变。这与逐项
消融中 cold assertion 主导前端改善、inline/constant 减少动态工作量的观察一致。PMU 仍只作为解释，
headline 与保留判断使用端到端 walltime。

## 7. 与搜索内历史结果对照

checkpoint 搜索内 gen150 曾记录 RWA `52,628.50 ms`、gen150 `50,420.25 ms`，减少
`2,208.25 ms/4.195920%`。本轮独立 fresh endpoint 为 `53,747.00→51,524.50 ms`，减少
`2,222.50 ms/4.135115%`。两次相对收益只差 `0.060805` 个百分点，且方向和量级一致，构成对搜索
结果的强复现。

两次绝对均值来自不同 session/CCD，不能横向相减来解释 `14.25 ms` 的 absolute-delta 差别。本轮
同 CCD direct pair 才是当前正式 endpoint 口径。

同理，六个 leave-one-out marginal 具有交互，不能把 TNO0205 的六个百分比相加来重构本轮
`4.135115%`。若要判断最佳落地子集，仍应直接构造并测试排除 residual MemoryRead/physical
zero-tail 的组合 endpoint。

## 8. Artifact 与 continuation 状态

核心结果 SHA-256：

| artifact | SHA-256 |
| --- | --- |
| RWA snapshot `provenance.json` | `fb54d478fcbcfc20cde4f468d0b9662e8e6d0f46f2bd54c7ab6d482cfac7c1ef` |
| RWA snapshot `SHA256SUMS` | `b51d99e1a9a62a4cf8b5aa62432f41d6b032db1f4764795af81c591bb5a403ca` |
| `snapshot_endpoint_control.py` | `8b58729fff8836224a18d468b119f256130e91d6d289ac9c9d5904738ad6d522` |
| `run_endpoint_until_gap.py` | `0a1f3b22332d3ac482289905c53bd76707412764203a11a90489540751671a29` |
| 正式 `round-1/result.json` | `f2eb55381a05527ad3430d4eaefcdb4808715c6441fe45ec0c5344c92005130a` |
| `results_gap_lt_0p25/summary.json` | `5f7f894c134d3466b1ae0be7f3fcd8bd9abea1d0ac5015ed1da0670ce201dfe8` |
| `driver.log` | `d42131893210046824f1eec2491011d26ee38d113a7b901b6b01792a21b86658` |

上述 artifact 均位于
`build/grhsim_bestpath_ablation_20260731/endpoint_rwa_to_gen150_v1/` 或同级 ablation 工具目录。
endpoint 完成后 runner、emu 和 perf 进程均已退出；本轮没有修改 Wolvrix 或 SimpleTES 源码，也没有
启动新的 auto research，不影响后续从 exact checkpoint 继续探索。

## 9. 增量更新 2026-07-31：RWA 到四项正收益 gen29 endpoint

### 9.1 正式落地口径与阶段结论

在上述完整六项 gen150 endpoint 之后，按后续要求补测“六项优化前”的当前默认 RWA 与“只保留四项
逐项消融正收益机制”的 exact gen29 endpoint。四项机制为：

1. standalone SystemTask 与 standalone `xs_assert_v2` 冷分支 `unlikely`；
2. 小/宽值 runtime helper `GRHSIM_ALWAYS_INLINE`；
3. 常量 MemoryRead row 证明与 always-in-range 临时清零消除；
4. shift/index 越界冷分支 `unlikely`。

本候选不包含 gen68 的剩余动态 MemoryRead 越界 hint，也不包含 gen150 的 targeted small-memory
physical zero-tail。正式 SimTop 50k pooled walltime 为：

```text
current-default RWA control : 53,846.75 ms
four-positive gen29         : 51,629.50 ms
absolute reduction          :  2,217.25 ms
relative improvement        :      4.117704%
```

ABBA 为 `53,763.00→51,591.00 ms`，减少 `2,172.00 ms/4.039953%`；BAAB 为
`53,930.50→51,668.00 ms`，减少 `2,262.50 ms/4.195214%`。两个 order 使用完全相同的 node1 CCD
`144-151,336-343` 与 CPU `144/336`，收益 gap 为 `0.155261 pp`，严格小于 `0.25 pp`，因此首轮正式
pair 即达标，不需要再次复测。

这个结果直接回答落地子集口径：此前 RWA 到四项正收益组合的端到端 walltime 改善为
`2,217.25 ms/4.117704%`，显著为正。完整六项和四项组合相对各自 RWA 的 fresh 收益只差
`0.017410 pp`，不足以跨 session 判断组合优劣；最终只保留四项的依据仍是 TNO0205 中两个末段机制的
严格逐项消融为负，而不是把这 `0.017410 pp` 当作直接 gen29↔gen150 证据。

### 9.2 exact gen29 物化、构建与功能门禁

本轮没有复用搜索期 binary。先对 TNO0204 物化的 exact gen29 candidate 做 production evaluator
`--validate-only`，确认：

- candidate document SHA-256 为
  `f0a4b4e3ebf7d33b8a32a5dded1298171631da32691805aa48256826698cfceb`；
- candidate digest 为
  `caf8435170202ea65250c306e73b1c1cf8da2c680db5fd5b0bb289bf09a15fbe`；
- mode 为 `default-path`，canonical enable options 为 `{}`，唯一修改文件为
  `lib/emit/grhsim_cpp.cpp`；
- patch SHA-256 为
  `6311c22786ebd5a1bc7547cec3e123a8a8d7e9e5e3b8a488ece68d07d4e1dd99`；
- exact materialized source SHA-256 仍为 TNO0204 记录的
  `a42690f9f85300a7f8311e07874329a8f02ae0e7aa870af5474e2f3729fdfb82`。

随后由 evaluator-owned slot 重新清理、应用 patch、生成和编译，并重新运行 trusted gates：focused
`29/29` PASS；100-cycle 到达 guest cycle `101`；10k-cycle 到达 guest cycle `10001`、完成首条指令
和 difftest 初始化，均无错误签名。candidate snapshot 的 11 项 `SHA256SUMS` 全部重新验证通过。

两端仍共同固定为 parent `d31118bea0feb563ad09476e1419f0f15aaf574f`、Wolvrix
`16a9f493687a21a5428f1e1327a69834ea60c9f5`、build-config fingerprint
`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3` 和 toolchain fingerprint
`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038`。

| endpoint | generated fingerprint | ELF bytes | ELF SHA-256 |
| --- | --- | ---: | --- |
| current-default RWA | `f28f2a696328175f0fe76e2e16895b44fbe54320506776eb6a5c436674c72077` | `91,894,296` | `29c31618b10e7ae18f986de76888781b9308e69bcd71a45ea38b8c83c56d6221` |
| four-positive gen29 | `5fc362ab9b7ca26d298bba05fa75427f3e33dae916d743c217abea1583ad69f2` | `90,873,536` | `08d86a90e814f81db9e5d765ef3df61291c91d0e8a326d22ad050a7ae49fcf12` |

两端 CoreMark image 仍逐字节相同，SHA-256 为
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`；NEMU 也逐字节相同，SHA-256
为 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`。因此本轮唯一实验变量是
四项 emitter 优化生成的 C++/emu。

### 9.3 quiet-gate、顺序与正式 walltime 样本

协议与前文完全相同：关闭 ASLR，动态发现 whole CCD，以单个 `GrhSimRuntime` 固定 ABBA 与 BAAB 的
CPU、SMT sibling、CCD、NUMA node 和 helper CPU；外层只接受按时间顺序首个 valid、同 placement 且
order gap 严格小于 `0.25 pp` 的完整八样本 pair。

round 1 的 paired attempt 1..7 均在运行任何 workload 前报
`no dynamically discovered CCD passed the strict quiet-window gate`，每次 accepted sample 都为 `0`。
attempt 8 找到 node1 CCD `144-151,336-343`，固定 CPU `144`、sibling `336`、NUMA node 1、helper
CPU 0，完整 ABBA+BAAB 一次通过。

| order | 运行次序 | RWA samples / ms | gen29 samples / ms | RWA→gen29 |
| --- | --- | --- | --- | ---: |
| ABBA | RWA, gen29, gen29, RWA | `53710,53816` | `51584,51598` | `53,763.00→51,591.00 ms`，`+4.039953%` |
| BAAB | gen29, RWA, RWA, gen29 | `53882,53979` | `51648,51688` | `53,930.50→51,668.00 ms`，`+4.195214%` |
| pooled | 四个 RWA + 四个 gen29 | `53710,53816,53882,53979` | `51584,51598,51648,51688` | `53,846.75→51,629.50 ms`，`+2,217.25 ms/+4.117704%` |

RWA spread 为 `269 ms`，即 control mean 的约 `0.4996%`；gen29 spread 为 `104 ms`，即 candidate
mean 的约 `0.2014%`。pooled `4.117704%` 高于预注册可信线
`max(1%, control spread/control mean)=1%`，且两个 order 均为正向。

### 9.4 八样本有效性与 PMU

正式八个 sample 全部满足：

- expected/allowed CPU 都只有 `144`，跨 order placement 完全相同，CPU migrations 全部为 `0`；
- `setarch x86_64 -R` 生效，process personality 全部为 `00040000`；
- pre-gate、continuous monitor gate、process affinity、resolved executable 和功能审计全部通过；
- task-clock 与全部 PMU event 的 scheduled ratio 均为 `100.0%`；
- binary 与 NEMU 的 NUMA local ratio 全部为 `1.0`；
- guest cycle、terminal PC、signature 和 walltime 唯一性全部通过。

聚合 PMU 为：

| event | RWA mean | gen29 mean | gen29 相对变化 |
| --- | ---: | ---: | ---: |
| cycles:u | `197,274,502,140.25` | `189,224,880,088.50` | `−4.080417%` |
| instructions:u | `162,370,483,928.00` | `158,918,862,764.25` | `−2.125769%` |
| frontend no-ops | `876,348,841,595.75` | `831,548,803,837.50` | `−5.112124%` |
| frontend-starved | `112,749,564,695.25` | `105,729,341,453.25` | `−6.226386%` |
| backend stalls | `75,600,934,541.75` | `75,329,100,152.75` | `−0.359565%` |

cycles `−4.080417%` 与 walltime `−4.117704%` 一致；四项组合同时减少约 `2.13%` instructions 和
`5.11%/6.23%` 两类前端空泡，backend stalls 只有小幅下降。PMU 只用于解释，正式保留口径仍是
端到端 walltime。

### 9.5 与历史 gen29 和完整六项 endpoint 的关系

| session | RWA / ms | candidate / ms | absolute reduction / ms | relative improvement |
| --- | ---: | ---: | ---: | ---: |
| 搜索内历史 gen29 | `53,742.50` | `51,534.50` | `2,208.00` | `4.108480%` |
| 本轮 fresh 四项 gen29 | `53,846.75` | `51,629.50` | `2,217.25` | `4.117704%` |
| 前文 fresh 完整六项 gen150 | `53,747.00` | `51,524.50` | `2,222.50` | `4.135115%` |

fresh gen29 与搜索内历史 gen29 的相对收益只差 `0.009224 pp`，方向和量级高度一致，是对四项组合的
独立强复现。fresh gen29 与 fresh gen150 相对各自 RWA 的收益只差 `−0.017410 pp`，远小于两组各自的
样本 spread 与 order gap；由于两组使用不同时间和 CCD，候选绝对 walltime 与 absolute reduction
不能横向相减归因。当前证据只能说明两种组合的总收益在本协议噪声下不可区分，不能代替同 CCD 的
gen29↔gen150 直接对测。

落地决策仍以 TNO0205 的严格 final-minus-one 结果为准：cold、inline、constant、shift 四项保留；
residual MemoryRead 与 physical zero-tail 不进入正式正收益子集。四项 endpoint 已证明该子集相对
此前 RWA 仍完整保有约 `4.12%` 端到端收益。

### 9.6 Artifact 与 continuation 状态

核心新增 artifact SHA-256：

| artifact | SHA-256 |
| --- | --- |
| exact gen29 candidate document | `f0a4b4e3ebf7d33b8a32a5dded1298171631da32691805aa48256826698cfceb` |
| candidate snapshot `provenance.json` | `c000804564984d45233b3f8d63ae8f865fea777b924510f5a20c71fc202512d6` |
| candidate snapshot `SHA256SUMS` | `700a7ba9ee69a1b2d659aa389ca0c3bb8d8a448c8710ecf825f9f6d32814b18f` |
| `prepare_arm.py` | `ba2cc1f88ceff9542757876c3daf569e6b1a2f36de7c9aab1ff7f3fba75bec13` |
| 正式 `round-1/result.json` | `2c518693b022f2aaa7f98c5d000b1b17755da033dd6c9c3498b116507f5837d2` |
| `results_gap_lt_0p25/summary.json` | `990b548bd173b51f15575944e278ddfe7c798f8c6315d3305fb776084a11542a` |

新增 artifact 位于
`build/grhsim_bestpath_ablation_20260731/endpoint_rwa_to_gen29_v1/`，复用的 RWA immutable snapshot
位于同级 `endpoint_rwa_to_gen150_v1/artifacts/rwa_control/`。本轮仍没有修改 Wolvrix 或 SimpleTES
源码，也没有启动 auto research；构建、runner、emu 与 perf 进程结束后不改变后续 exact checkpoint
continuation 的输入与运行方式。

## 10. 增量更新 2026-07-31：四项 gen29 与六项 gen150 直接对比

### 10.1 为什么需要 direct pair

第 9 节四项 gen29 对 RWA 的 `4.117704%` 与第 1 节六项 gen150 对 RWA 的 `4.135115%` 来自不同
session 和 CCD；二者只差 `0.017410 pp`，但这种 cross-session 差值不能直接回答四项与六项谁更快。
因此本轮以四项 gen29 为 control、六项 gen150 为 candidate，直接运行同 CCD ABBA+BAAB。正收益表示
额外加入 residual MemoryRead 与 physical zero-tail 后六项更快，负收益表示四项更快。

两端在 direct pair 前再次验证各自 11 项 `SHA256SUMS` 全部通过。它们具有相同的 parent、Wolvrix、
build-config、toolchain、CoreMark image 和 NEMU；都是 `default-path`、canonical enable options `{}`，且
ELF 大小恰好同为 `90,873,536 B`。唯一变量仍是 generated C++/ELF 内容：

| endpoint | candidate digest | generated fingerprint | ELF SHA-256 |
| --- | --- | --- | --- |
| four-positive gen29 | `caf8435170202ea65250c306e73b1c1cf8da2c680db5fd5b0bb289bf09a15fbe` | `5fc362ab9b7ca26d298bba05fa75427f3e33dae916d743c217abea1583ad69f2` | `08d86a90e814f81db9e5d765ef3df61291c91d0e8a326d22ad050a7ae49fcf12` |
| full six-item gen150 | `1afdcb97fc009d6a3e656792eeb6f66751952cc2ac6506051cf050348d95efbb` | `ff5888f25297d2285b3715f38cb5f9e6bf8ff51958b28c4986f4c4dd5278ca0b` | `7e5ffc22fd309c0fb3fe4f5789591bd6bffaed3e55f2a7fda2e39f58d090ffa9` |

### 10.2 正式 walltime 结果

round 1 paired attempt 1 在运行 workload 前因没有 whole CCD 通过 strict quiet-window gate 而作废，
accepted sample 为 `0`。attempt 2 找到 node1 CCD `104-111,296-303`，固定 CPU `104`、sibling
`296`、NUMA node 1、helper CPU 0，并在同一 placement 完成两个 order：

| order | 运行次序 | four-item samples / ms | six-item samples / ms | four→six |
| --- | --- | --- | --- | ---: |
| ABBA | four, six, six, four | `51642,51670` | `51634,51584` | `51,656.00→51,609.00 ms`，`+47.00 ms/+0.090987%` |
| BAAB | six, four, four, six | `51798,51724` | `51598,51643` | `51,761.00→51,620.50 ms`，`+140.50 ms/+0.271440%` |
| pooled | 四个 four + 四个 six | `51642,51670,51798,51724` | `51634,51584,51598,51643` | `51,708.50→51,614.75 ms`，`+93.75 ms/+0.181305%` |

ABBA 与 BAAB 都是六项数值更快，order gap 为 `0.180453 pp`，严格小于 `0.25 pp`，因此首轮即是
按预注册选择规则接受的正式 pair，无需继续复测。four-item spread 为 `156 ms`，约占 control mean
`0.3017%`；six-item spread 为 `59 ms`，约占 candidate mean `0.1143%`。

但是 pooled `0.181305%` 明显低于本系列预注册可信线
`max(1%, control spread/control mean)=1%`，并且收益本身与 `0.180453 pp` order gap 几乎同量级。
所以正确结论是：**六项相对四项有方向一致的轻微数值优势，但在当前协议下属于中性差异，不能认定为
可信端到端收益。** 这次 direct pair 不支持把额外两项因性能收益而默认启用。

### 10.3 八样本审计与 PMU

正式八个 sample 全部满足：allowed/expected CPU 只有 `104`；两个 order 使用完全相同的
CCD/CPU/sibling/NUMA/helper placement；CPU migrations 全为 `0`；process personality 全为
`00040000`；pre-gate、continuous monitor、affinity、resolved executable、guest cycle、terminal PC、
signature 和 walltime 唯一性均通过；task-clock 与全部 PMU event scheduled ratio 均为 `100.0%`；
binary/NEMU NUMA local ratio 均为 `1.0`。

六项相对四项的聚合 PMU 为：

| event | four-item mean | six-item mean | six-item 相对变化 |
| --- | ---: | ---: | ---: |
| cycles:u | `189,474,888,901.75` | `189,181,292,508.00` | `−0.154953%` |
| instructions:u | `158,918,862,896.75` | `158,917,267,140.50` | `−0.001004%` |
| frontend no-ops | `832,739,719,160.75` | `831,162,097,043.75` | `−0.189450%` |
| frontend-starved | `105,916,985,545.75` | `105,664,796,321.00` | `−0.238101%` |
| backend stalls | `75,648,031,772.00` | `75,598,625,252.75` | `−0.065311%` |

cycles `−0.154953%` 与 walltime `−0.181305%` 方向和量级一致；instructions 基本不变，两项新增机制只
对应极小的前端与 backend 计数下降。这能解释数值方向，但所有变化都远低于 `1%`，不能把中性结果
升级为可信收益。

### 10.4 与逐项消融及默认决策的关系

TNO0205 在完整 final 上分别移除 residual MemoryRead 和 physical zero-tail 时，两项各自 marginal
均显示加入机制会回退；本轮从 gen29 同时加入两项则数值改善 `0.181305%`。这并非可直接相加的矛盾：
leave-one-out 测的是完整上下文中的单项 marginal，gen29→gen150 测的是两项联合变化，二者可以存在
交互；而三个观测幅度又都处于亚百分比噪声区间。

综合判断保持不变：

- 四项与六项相对 RWA 都有约 `4.12%..4.14%` 的可信总收益；
- 六项 direct 对四项只有 `93.75 ms/0.181305%` 的不可信轻微数值优势，不能构成额外两项默认开启的
  端到端证据；
- 因而正式默认子集仍采用四项正收益机制，residual MemoryRead 与 physical zero-tail 保持排除/关闭。

若未来要重新考虑额外两项，应要求新的独立端点取得超过可信线的可复现收益，而不是依据本轮
`0.181305%` 中性差异晋升。

### 10.5 Direct-pair artifacts

| artifact | SHA-256 |
| --- | --- |
| 正式 `round-1/result.json` | `47a1942273d46008d666ff7696e370dd8cf6f572ec9667f2827d034c916e9c4a` |
| `results_gap_lt_0p25/summary.json` | `71a78fcd02c513189977aed2645d97f426b67094f28d1809e5848015b95a9211` |

direct-pair artifact 位于
`build/grhsim_bestpath_ablation_20260731/endpoint_gen29_to_gen150_v1/`。本轮没有修改 Wolvrix 或
SimpleTES 源码，也没有启动 auto research。
