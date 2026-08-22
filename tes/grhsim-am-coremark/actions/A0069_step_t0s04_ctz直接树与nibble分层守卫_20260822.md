# A0069 - r003/t0/s04 ctz 直接树与 nibble 分层守卫

## Action 与候选预注册

- 日期：2026-08-22；action：`step`（trajectory `t0`，step 4/8，K=2）。
- proposal：[r003-t0-s04](../proposals/r003-t0-s04.md)；Phi 节点为 `e00057`、
  `e00051`、`e00061`。两个候选均从 t0 tip `3706873` 出发，评估表型保留
  r003 基础 10 开关、`--sys-task-body-outline --scan-branch-hints`，不携带已被
  e00061 证伪的原样 `--scan-active-byte-ctz`。
- `begin-step` 首次因默认沙箱不能写 wolvrix submodule 的 Git 元数据而在创建
  worktree 前失败；幂等重入在获准写 Git 元数据后完整生成 proposal、两个候选
  worktree 和 `e00065/e00066`，没有评估或 eval-id 被重复登记。

### c1 / e00065：ctz + 直接分支树

- 来源与病灶：e00061 的 `ctz + switch` 命中 11,887 个 byte 派发点、93,599 个
  case，ELF `.text` +2.48%、`.rodata` +7.67%，Host 名义回退 9.73%。
- 局部改动：新增默认关的 `--scan-active-byte-tree`。保留 ctz set-bit 枚举与
  逐 bit 清除，但用三层直接条件树和 byte 局部标签派发，不生成 switch/jump table；
  partial-owned mask、空 Block 目标和同 byte 前向 relay 均显式处理。
- 可证伪预期：相对 e00061 Host 至少下降 2%；低于 0.75% 或回退证伪。

### c2 / e00066：低/高 nibble 分层守卫

- 来源与病灶：e00057 证明 branch-hinted 线性测试优于 e00061 的间接稀疏派发，
  但一个活跃 byte 仍最多执行 8 个 Block bit test。
- 局部改动：新增默认关的 `--scan-active-byte-nibble`。在线性 hinted tests 外增加
  低/高 4-bit 直接活动守卫；低组执行产生的同 byte relay 会在高组守卫前重新观察，
  不引入 ctz、间接派发或 jump table。
- 可证伪预期：相对 e00061 Host 至少下降 2%；低于 0.75% 或回退证伪。

## 量化结果

| 候选 | commit | eval / 状态 | compile_s | Host reps (ms) | 中位 / CV | 起跑 loadavg | vs e00061 |
|---|---|---|---:|---|---:|---|---:|
| c1 direct-tree | `aff7f7c257aee41e8905b5298c3ee7f2fac35cad` | e00065 / ok | 1255.3 | 409870 / 409869 / 409866 | 409869 / 0 | 50.13 / 52.25 / 53.24 | +62.81% |
| c2 nibble-guard | `092e3b82e74d5cfe4292cfdeb5a6df9b3fd7bc55` | e00066 / ok, noisy | 1200.8 | 412826 / 412825 / 521718 | 412826 / 14.0% | 49.99 / 52.18 / 53.52 | +63.99% |

两候选均通过 17/17 `ctest -R grhsim`、2400s 编译门和 3 rep nemu difftest；
6 个 rep 均为 `instrCnt=73580`、`cycleCnt=49996`、退出码 0。e00066 的 rep3
比前两 rep 慢 26.38%，按冻结协议标 noisy、仍只用固定 3 rep 中位，不扩增、不重跑。
台账登记 insight 曾把两项 compile_s 手误写成 1248.2/1192.8s；已追加
`kind=correction` 勘误行，正确值以 result.json 的 1255.3/1200.8s 为准。

生产二进制形态：

| eval | 派发/守卫命中 | ELF `.text` | ELF `.rodata` |
|---|---:|---:|---:|
| e00057 hinted linear | - | 96,954,891 | 4,847,828 |
| e00061 ctz+switch | 11,887 switch / 93,599 case | 99,361,815 | 5,219,540 |
| e00065 direct-tree | 11,888 direct-tree | 99,896,097 | 4,846,804 |
| e00066 nibble-guard | 11,624 low + 11,633 high guards | 97,147,400 | 4,847,764 |

direct-tree 消除了 jump-table rodata（较 e00061 -7.14%），但直接分支/标签令
`.text` 反增 0.54%；nibble-guard 的 `.text` 较 e00061 缩小 2.23%、仅比 e00057
大 0.20%，说明两项静态机制都真实落地，不是无效开关。

## 裁决与机制分析

`finish-step` 按 score 机械选择 **c1/e00065**（`-409869`），将 `aff7f7c`
快移入 `tes/r003/t0/main`。e00065 名义比 e00066 快 0.72%，但该差值低于协议可稳健
解释的量级，且 e00066 noisy，不能把机械排名升级为 direct-tree 优于 nibble-guard
的因果结论。

- e00061 起跑 loadavg 仅 1.33/2.98/3.58，本 step 两候选均约 50；e00065 的
  409.869s 又与紧邻的 t1/e00064 409.731s 慢窗吻合。因此相对 e00061 的 63%
  回退主要被宿主窗口混杂，不能全归因于候选机制。
- c1 去掉了 switch rodata，却以更多直接分支 text 交换；当前慢窗没有运行时正证据。
  c2 确实保持接近 e00057 的紧凑二进制，但体积下降也未转化为可隔离的正收益。
- 两项均未达到预注册收益门。扫描残余不再用 ctz 全局枚举、直接树或 nibble 分层的
  原样形态继续消耗席位；保留 e00057 的 branch-hinted 线性扫描作为 t0 历史 best。

t0 历史 best 与全局 best 均保持 **e00057 = 229.429s**，t1 best 保持
**e00056 = 241.956s**；当前 t0 4/8、t1 3/8、evals 16/32，best/gsim =
**5.002x**。

## 对 Phi 下一步的建议

- t0 若再选择扫描邻域，应先有低负载同窗动态证据或新的大成本池；不原样重测
  ctz-switch、direct-tree、nibble-guard，也不以代码体积变化代替运行证据。
- 本 step 进一步说明 loadavg≈50 时不同机制会共同落入约 410s 慢窗；仍按冻结
  3-rep 协议记分，但机制结论必须保守，不以批内 CV=0 推断跨窗口可比。
- 状态机下一 action 为 `r003/t1/s04`。本 action 只作预告，未调用 `begin-step`
  或 evaluator 启动下一 action。
