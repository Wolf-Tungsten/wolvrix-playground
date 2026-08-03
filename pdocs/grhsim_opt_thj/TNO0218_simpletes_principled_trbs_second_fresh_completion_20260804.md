# TNO0218：SimpleTES 原则化 TRBS 第二轮 fresh research 完成

日期：2026-08-04

## 1. 最终结论

[TNO0217](./TNO0217_simpletes_principled_trbs_gpt_max_second_fresh_launch_20260803.md) 启动的
`instance-44cd457d` 已自然达到 `32/32 valid` 并退出。本轮从原则化 TRBS native 空 control fresh 开始，未
resume、未 seed 上一轮 best；最终找到一个明显强于噪声的通用 typed persistent-state storage candidate。

正式 best 相对当前 baseline 的 SimTop 50k `Host time spent` 为：

`47,620.25 -> 44,582.25 ms`，绝对减少 `3,038.00 ms`，改善 `6.379639%`。

同一 patch/digest 在后续 gen36 被完整复测，结果为：

`47,692.00 -> 44,669.00 ms`，绝对减少 `3,023.00 ms`，改善 `6.338589%`。

两次共 8 个 control 与 8 个 candidate 样本的合并均值为：

`47,656.125 -> 44,625.625 ms`，绝对减少 `3,030.500 ms`，改善 `6.359099%`。

四组 order 都同方向；两次 ABBA/BAAB gap 分别为 `0.017342 pp` 和 `0.164468 pp`，均严格低于
`0.25 pp`。所有正式样本均验证 `personality=00040000`、固定单 CPU affinity、whole-CCD quiet、NUMA
local、PMU、功能签名和 CPU migrations `0`。

该结果已经足够进入独立消融、代码审计与 landing regression，但尚未直接写入 Wolvrix，也尚未裁决默认开启。

## 2. 搜索账目

最终 checkpoint：

`SimpleTES/checkpoints/grhsim_simtop_50k/principled_trbs_gpt56sol_max_fresh2_20260803_030316/2026-08-03/instance-44cd457d/db_state_000359`

运行约从 `2026-08-03 03:03:35 +0800` 持续到 `2026-08-04 00:03:59 +0800`，约 21 小时。最终 metadata：

| 项目 | 绝对值 |
| --- | ---: |
| generation attempts | `40` |
| completed evaluations | `38`，包含 initial control |
| valid generated candidates | `32/32` |
| generation failures / cancellations | `0 / 0` |
| evaluator failures | `0` |
| final best score | `1.06814371190328` |
| final best node | `a55f5c96f68e4dc3815befc2f9f89341`，gen31 |

已完成的 37 个 generated nodes 中，32 个通过 evaluator，5 个为 candidate-level `-inf`：4 个 unified diff
损坏或不能 apply，1 个 candidate build 失败。达到 valid target 时还有 3 个已生成项排在串行 evaluation queue；
它们没有性能结果，不纳入结论。

全部 32 个 valid candidate 都是：

- `candidate_mode=default-path`；
- `enable_options=[]`；
- 仅修改 `lib/emit/grhsim_cpp.cpp`；
- 相对固定 Wolvrix `d3ed9dea975bddf01185dde5c548a69241a09de9` 生成。

32 个 valid 中 pooled walltime 为正的有 14 个、为负的有 18 个；只有 10 个在 ABBA 与 BAAB 都保持正向。
运行中出现过 model-at-capacity、remote compact/capacity 和一次 semantic validation retry，但 exact-thread
continuation/normal retry 全部恢复，最终 engine `generation_failures=0`。

## 3. Initial control 噪声

空 control 的两臂是同一 binary，初始 canary 为 `47,772.00 -> 47,676.00 ms`，表观改善 `96.00 ms /
0.200955%`；control spread 为 `130 ms`，candidate-control spread 为 `80 ms`。该数只记录当前机器噪声，
不是优化收益。每个真实 candidate 都由 evaluator 重新与同轮 control 配对，因此 best 的 `6.36%` 不依赖这组
初始同码差值。

## 4. Best patch 的机制

best 是一个通用 persistent non-memory logic-state 表示重构，不匹配 SimTop 名字、端口名、ValueId 或
benchmark identity，也不借用任何 option：

1. 原 native 表示是一个 `1,066,944 B` 的
   `alignas(uint64_t) std::array<std::byte, kStateLogicStorageBytes>`；
2. candidate 改为 `state_logic_storage_t`，分别为 bool/u8/u16/u32/u64 与各 wide word-count 生成 typed
   `std::array` bucket；
3. `StateDecl` 新增 per-bucket `logicSlotIndex`，旧 byte `slotIndex` 保留给既有 anchor/order/alias metadata；
4. state read/write 与 direct-commit descriptor 使用 typed bucket index，生成直接
   `state_logic_storage_.u64_slots_[index]` 一类表达式；
5. reset 按 typed bucket `std::fill`；memory/reg-to-mem field、schedule、event、guard、activation 和 state
   初始化语义不变。

SimTop emitted bucket 的实际绝对规模为：

| bucket | slots |
| --- | ---: |
| bool / u8 / u16 / u32 / u64 | `97,158 / 49,705 / 10,032 / 3,484 / 47,369` |
| wide words 2/3/4/5/6/8/9/13/64 | `781/97/198/7/2/114/8/8/1` |

按 emitted typed arrays 的标准布局计算，state object payload 为 `590,568 B`，相对旧 `1,066,944 B` 减少
`476,376 B / 44.648641%`。候选证据扫描还记录了 97 个 schedule translation units 中
`1,329,837` 个 state-arena helper references，其中 scalar `1,312,281`、wide `17,556`；typed direct member
引用删除了这些通用 byte-arena ref 表达式，但没有改变 schedule work。

## 5. 两次正式 walltime

candidate identity：

| 对象 | identity |
| --- | --- |
| candidate digest | `0fdabb9858b4a7f9afd1f301f5b7f6f7419f18bb80285fd81025f26afd3bda98` |
| patch SHA-256 | `445c1330f9b7aa601a3d7149282400a6f3606e2f5fdd752be812750a043e823a` |
| control generated fingerprint | `b63d086843de0ed4d7ebe5b78cb727644f7c96019b336f64e3c9fbd9598cfaeb` |
| candidate generated fingerprint | `3d28608a20b69bbdf6863b1bdb70f2441828e4ba378a8ce9b13b89d86696d22b` |
| control emu SHA-256 | `2c087852bdabf911aab02ad72ad1318729041c4890f7cac2405e25ace1f077c2` |
| candidate emu SHA-256 | `7751400f51dff90ecb2f8c68c5c17cacabb44fe43324868dcfcc43a6ec4338ce` |

### 5.1 gen31 best

| order | sequence walltime | control mean | candidate mean | 绝对减少 | 改善 |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `47,858 / 44,824 / 44,710 / 47,786 ms` | `47,822.00` | `44,767.00` | `3,055.00 ms` | `6.388273%` |
| BAAB | `44,379 / 47,483 / 47,354 / 44,416 ms` | `47,418.50` | `44,397.50` | `3,021.00 ms` | `6.370931%` |
| pooled | 4 control / 4 candidate | `47,620.25` | `44,582.25` | `3,038.00 ms` | `6.379639%` |

ABBA placement 为 `node0:48-55,240-247`、CPU `48`/sibling `240`；BAAB 为
`node1:160-167,352-359`、CPU `160`/sibling `352`。order gap 为 `0.017342 pp`。

### 5.2 gen36 exact repeat

| order | sequence walltime | control mean | candidate mean | 绝对减少 | 改善 |
| --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `47,621 / 44,559 / 44,502 / 47,551 ms` | `47,586.00` | `44,530.50` | `3,055.50 ms` | `6.421006%` |
| BAAB | `44,801 / 47,775 / 47,821 / 44,814 ms` | `47,798.00` | `44,807.50` | `2,990.50 ms` | `6.256538%` |
| pooled | 4 control / 4 candidate | `47,692.00` | `44,669.00` | `3,023.00 ms` | `6.338589%` |

ABBA placement 为 `node1:144-151,336-343`、CPU `144`/sibling `336`；BAAB 为
`node0:0-7,192-199`、CPU `0`/sibling `192`。order gap 为 `0.164468 pp`。

gen31 与 gen36 的 candidate digest 和 generated fingerprint 完全相同；它们是同一 patch 的两次 runtime
evaluation，不是两个不同优化。不同 attempt/proof 与四组不同 placement 提供了有价值的复现证据。

## 6. PMU 与静态产物

两次 evaluation 合计 8 个 control / 8 个 candidate 样本的 PMU 均值：

| event | control | candidate | delta |
| --- | ---: | ---: | ---: |
| cycles:u | `174,700,160,237.375` | `163,587,945,871.250` | `-6.360735%` |
| instructions:u | `160,548,350,919.750` | `160,491,737,721.000` | `-0.035262%` |
| frontend no-ops | `757,922,051,687.250` | `716,023,844,134.750` | `-5.528036%` |
| frontend cmask no-dispatch | `96,153,705,628.250` | `89,965,012,768.750` | `-6.436250%` |
| backend stalls | `77,544,774,025.875` | `60,518,649,650.750` | `-21.956508%` |

instructions 几乎不变，但 cycles、frontend 空转和 backend stalls 显著下降，说明主要收益不是删除动态
simulator work，而是 typed layout 改善了别名分析、依赖链、代码布局与访存执行。

静态产物：

| 对象 | control | candidate | delta |
| --- | ---: | ---: | ---: |
| generated directory bytes | `1,527,372,504` | `1,475,972,767` | `-51,399,737 / -3.365239%` |
| emu bytes | `91,094,720` | `88,784,576` | `-2,310,144 / -2.535980%` |
| ELF text | `90,932,121` | `88,626,081` | `-2,306,040 / -2.536002%` |

## 7. 功能与 attribution gate

best 为 one-file default-path、零 options；unpatched current-default、patched native output 和 generated
fingerprint attribution 均通过。candidate proof 发布前完成：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| trusted focused | `29/29` | PASS |
| 100-cycle | instrCnt `0`，cycleCnt `96`，guest cycles `101`，wall `158 ms` | PASS |
| 10k-cycle | instrCnt `458`，cycleCnt `9,996`，guest cycles `10,001`，wall `4,448 ms` | PASS |
| 16 formal 50k samples | personality `00040000`，migration `0` | PASS |

focused log 中有 evaluator Python 环境的既有 `sitecustomize`/`rich` import warning，但 29 tests 全部执行并
PASS。当前还没有执行 landing 所需的 fresh full Wolvrix CTest、完整 pybind/XS regression、针对 typed bucket
边界的新增 emitter tests，故不能直接视为已落地。

## 8. 其他路线

搜索高度集中在 native exact-event lockstep reader-activation union：23 个 proposal、其中 21 个 valid。该 family
虽然静态上可把 projected mask RMW `13,893 -> 5,257`，但 end-to-end 结果在正负之间摆动，最好的 gen32 为
`47,890.25 -> 47,753.25 ms`，减少 `137.00 ms / 0.286071%`，且 order gap `0.466225 pp` 超过正式门槛。
因此不能据此保留或默认开启。

其余 pooled 正向候选：

| gen | 机制 | control -> candidate | 绝对减少 / 改善 | order gap | 当前判断 |
| ---: | --- | --- | --- | ---: | --- |
| 18 | exactly-two-word hot snapshot 改为 register asm barrier | `47,819.75 -> 47,708.50 ms` | `111.25 ms / 0.232644%` | `0.338240 pp` | gap 过大，未确认 |
| 35 | 402-site commit activation member flag localize | `47,660.50 -> 47,577.00 ms` | `83.50 ms / 0.175197%` | `0.190849 pp` | 弱正向、低于 1% |
| 14 | lockstep activation tail union | `47,695.50 -> 47,614.00 ms` | `81.50 ms / 0.170876%` | `0.115415 pp` | family 整体不稳定 |
| 34 | snapshot asm barrier 扩到 singleton | `47,704.50 -> 47,638.25 ms` | `66.25 ms / 0.138876%` | `0.235330 pp` | 弱正向、低于 1% |
| 15 | gated lockstep activation union | `47,563.00 -> 47,503.50 ms` | `59.50 ms / 0.125097%` | `0.195559 pp` | family 整体不稳定 |

MemoryWrite range caching、guard snapshot、bitmap-derived commit summary、division reuse 等路线均未产生稳定正收益。
这些小候选后续若要继续，应该在 typed-storage best 基线上重新组合测量，不能把当前 baseline 上的子 `0.3%`
数字直接相加。

## 9. 下一阶段建议

1. 先对 typed storage 做直接消融，至少拆开 scalar typed buckets、wide buckets、direct ref 表达式和 payload
   layout，确认 `6.36%` 的主要来源；
2. 审计 dual-index 在两个 allocator、direct commit descriptor、wide state、reg-to-mem exclusion、reset 与
   initialization 上的完整性，并补 arbitrary-design/边界测试；
3. 用整理后的 patch 落到 Wolvrix 通用默认候选，跑 fresh full build、CTest、pybind、XS、100/10k 与正式
   same-CCD 50k regression；
4. typed storage 独立闭环后，再测 snapshot asm/local commit flag 等小候选叠加收益。

## 10. 证据哈希

| 对象 | SHA-256 |
| --- | --- |
| final checkpoint `best_program.txt` | `5723e113bb1f9e0c6110153bca609d17d1310b34369a439162b75c4e2f2a3117` |
| final `nodes.json` | `69e5022285e2bde07c23432240a4547ef464b6310093ac676285010570ded211` |
| final `metadata.json` | `c6d3d59050de6715d32deeb86ece60f621daada3f76e1f68f0492a1428aa9996` |
| final score CSV | `4900dfa35f74d8ae3a56e06b3fe02a3e852cda12d6c81b8f1bc4edcf38b271ef` |
| latest candidate proof | `5d6e13e1fad2f8056f471a1aff7b65850348a7495304b2be9eb58bc9e01434a2` |
| gen31 evaluation | `6717d42fc40261eb311c4869763b182d69352c088ae165e8157aeed11bbe5f1a` |
| gen36 repeat evaluation | `c920d1107053c3b789a6aaca88cf3e7cbc27503dff84a511880028b082fbd241` |
