# A0016 - step-resume r001/t2/s04：稀疏 commit 门控与宽态炸开

日期：2026-08-18。action 类型：step-resume（trajectory t2, step 4, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t2-s04.md`。共同对照为 t2
主线 e00019（Host 中位 264.466s）；两个候选均保持 t2 轨迹独立。

## 评估规则与依赖复用

两个候选均由任务 evaluator 串行执行，使用同一 `-C 50000` 负载、绑核和
difftest 协议。每个 eval 保留自己的 `wbuild`、`emit` 与 `emu_build`，避免
CMake cache 绑定不同 worktree 的绝对源码路径；FetchContent 依赖从
`wolvrix/build` 的本地 clone 读取，C++ 编译缓存共享 `build/tes/ccache`。
e00025/e00026 的首次离线 configure 分别为 4.8s/4.6s，未联网重新获取依赖。

e00025 初次运行暴露了测试夹具问题：packed-activity 单元测试同时打开稀疏
阈值，导致其唯一小 gate 被拒绝并触发旧断言；移除该夹具属性后在同一 eval-id
重跑，17/17 ctest 通过。初次 ctest 失败没有作为性能数据登记，最终结果以修复
后的重跑为准。

## 候选设计与结果

| eval | 候选 | 机制假设 | compile_s | Host reps（ms） | 中位 / CV | 相对 e00019 |
|---|---|---|---:|---|---:|---:|
| e00025 | c1 `--commit-input-sparse` | 按 dirty edge 成本拒绝低净收益 commit gate，保留高净收益 gate | 1007.5s | 271725 / 265956 / 270956 | **270.956s / 1.16%** | **+2.45% 回退** |
| e00026 | c2 `--wide-state-explode` + commit gating | 先压缩宽态传播边，再保留足够 commit gate 动态收益 | 1152.6s | 269910 / 272633 / 271282 | **271.282s / 0.50%** | **+2.58% 回退** |

两候选均 `status=ok`，17/17 ctest 全绿，3 rep 进程均退出码 0、
`instrCnt=73580`、`cycleCnt=49996`，在线 difftest 无 mismatch，CV 未触发
额外测量。e00025 的最终提交为 `f7b1f87`（包含测试夹具修复），e00026 为
`e30df6a`。

## 机制证据与分析

### c1：静态稀疏阈值把门控全部拒绝

完整模型 emit 输出
`min_work_per_edge=4 rejected=2922/162422 dirty_edges=240198`，随后
`gated=0`。也就是说阈值不是挑出一小部分高净收益 gate，而是拒绝了 e00019
的全部 2,922 个 commit gate，候选实际退化为已有的 guard-event gating，因而
丢失 commit 内锥 skip 收益；271.0s 中位较 e00019 回退 2.45%。静态 dirty-edge
总量足以说明传播成本真实存在，但不能用一次全局阈值替代动态 open/skip 净收益。

### c2：宽态炸开降低传播边，但也削弱有效覆盖

wide-state explode 命中 274 个状态、16,818 个元素并回收 4,145 个宽 word；
commit gating 变为 2,165 gate、59,160 writes、87,298 dirty edges（对照
e00019 的 2,922 gate、162,422 writes、240,198 dirty edges）。传播边确实下降，
但 gate 覆盖和可跳过的 next 锥同时下降，生成代码/布局成本也没有被运行时收益
抵消，最终 271.282s 回退 2.58%。因此“减少静态 edge 数”不是该路径的充分收益
代理，宽态炸开与 commit gating 的组合本轮关闭。

## 裁决与后续

按 TES 的 step 内确定性裁决，winner 为 **e00025**（score `-270956`），
`finish-step` 已将 `f7b1f87` fast-forward 到 `tes/r001/t2/main`。这是候选间
相对较优的 winner，但相对既有 e00019 是回退；状态机的 t2 best 仍保持 e00019，
run best 仍为 t0/e00022 的 230.568s，不应把本 step 记为性能进步。

本轮结论：关闭“全局 dirty-edge 稀疏阈值”和“wide-state explode + commit gate”
组合；若未来重访 commit 路线，必须先做按 gate 的动态 open/skip、传播次数和
实际跳过指令数统计，并证明净收益，再消耗正式 eval。第 4 轮三条轨迹现已齐平，
下一 action 交给 `round-summary` 做跨轨迹小结；本 action 不提前启动它。

