# A0020 - step-resume r001/t2/s05：commit dirty 位图与 producer 变化门控

日期：2026-08-19。action 类型：step-resume（trajectory t2, step 5, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t2-s05.md`。

本 action 只使用 t2 的 Phi 节点 `e00019`、`e00008`、`e00025`。两个候选均从
t2/s04 mechanical winner `e00025` 的主线 commit `f7b1f87` 出发，继承
`--block-chunk-instructions 3000 --guard-event-gating`；它们分别改变 dirty flag
的存储表示和 dirty 传播的触发条件，不是参数微调。

## 候选设计与可证伪假设

### c1 `--commit-input-packed-dirty`

- 分支 `tes/r001/t2/s05-c1`，commit `cd16577`，eval `e00031`。
- 将 commit-input gate 的一个 `uint8_t` dirty 槽改为每 64 gate 一个 `uint64_t`
  word。同一 producer 的同 word 目标合并为一次 OR mask；gate 以 bit test/clear
  保持各自的首次执行、累积置位和消费时序。选项默认关闭，隐含开启
  `--commit-input-gating`，且有 emitter/CLI 测试与 pipeline 文档。
- 假设：基础 gate 的逐边 byte store 是稳定路径的一部分；按 word 合并传播在不改变
  gate 语义的前提下可降低存储/加载流，较 t2 best e00019 至少快 1%。

### c2 `--commit-input-producer-change`

- 分支 `tes/r001/t2/s05-c2`，commit `7fb3afb`，eval `e00032`。
- producer compute block 执行完后，对合格的窄标量输出做 snapshot compare/update；
  只有至少一个输出真实变化时才给依赖 commit gate 置 dirty。宽值、非标量和不安全
  生产者仍保留基础路径；首次 commit 由 `commitInputValid_ == 0` 无条件放开。
- 假设：大量执行 producer 的输出没有变化；省掉这些无效 dirty 传播后，尽管有快照
  比较，Host 较 e00019 至少快 1.5%。

## 正式评估结果

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00019 |
|---|---|---|---:|---|---:|---:|
| e00031 | c1 packed dirty | ok；ctest 17/17；3 rep difftest 全过 | 1184.8s | 265250 / 259742 / 266972 | **265250 / 1.43%** | **+0.30%** |
| e00032 | c2 producer-change | ok；ctest 17/17；3 rep difftest 全过 | 1175.3s | 285552 / 284147 / 285900 | **285552 / 0.33%** | **+7.98%** |

六次 rep 都是 rc=0、`instrCnt=73580`、`cycleCnt=49996`，nemu 在线 difftest 无
mismatch；两项 CV 都低于 5%，没有追加 rep。两候选也都在 2400s compile budget
内。阶段耗时为：

- e00031：wolvrix build 106.9s，emit 74.9s，emu build 841.5s；
- e00032：wolvrix build 105.8s，emit 70.5s，emu build 837.8s。

## 机制分析与裁决

c1 的生成统计为 2,922 个 gated block、240,198 条 dirty edge、46 个 dirty storage
word、23 个输入 snapshot，保护 440,821 条指令和 162,422 个写点。它确实将 2,922
个 dirty flag 压成 46 个 `uint64_t`，但正式中位比 e00019 慢 0.784s（+0.30%），
小于本次 1.43% CV，不能证明回退；同时也没有证明位图压缩带来正收益。bit
test/clear 和 mask OR 的额外热路径至少没有被同 word store 合并可靠抵消。

c2 的统计为 2,512 个 gated block、20,476 个 producer block、103,125 条 dirty edge
和 67,117 个 snapshot。生成 C++/header 总文本为 1,271,550,969 bytes，比 c1 的
1,266,856,170 bytes 多 4,694,799 bytes。它的静态 dirty edge 数更小，但输出快照的
compare/update 覆盖大量执行 producer，性能反而比 e00019 慢 21.086s。该结果与
snapshot 维护成本压过省下传播相符；静态边数缩减不能替代动态净收益证据或单独证明
因果。

winner = **e00031**（score `-265250`），因为它是本 step 的最高分。`finish-step`
已将 `cd16577` 推进到 `tes/r001/t2/main`；不过 t2 的历史 best 仍为 e00019
（264.466s），没有更新。两种细化都未达到预设收益门，因此关闭 commit-input
位图压缩和 producer-output snapshot 的原样路线。只有在逐 producer/gate 的动态
执行率、真变化率、传播 store 与实际跳过工作量证明存在小而热的高净收益子集时，
t2 才应重新打开该方向。

## 依赖复用与后续

正式评估仅调用任务 `evaluator.py`，严格串行。e00031/e00032 各自保留独立
`wbuild`/`emu_build` 以隔离绑定 worktree 绝对路径的 CMake cache 与对象文件；
FetchContent 从 `wolvrix/build` 的既有本地 clone 复用，C++ 使用共享
`build/tes/ccache`。两次离线 configure 分别为 4.8s 与 4.5s，没有联网下载依赖。

t0/t1/t2 现均为 5/8，状态机给出的唯一下一 action 是第 5 轮 `round-summary`。
本 action 不开始该小结，也不把 t2 的结论注入其他轨迹的当前归因。
