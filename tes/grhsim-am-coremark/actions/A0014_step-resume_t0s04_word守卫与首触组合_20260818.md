# A0014 - step-resume r001/t0/s04：word 守卫与首触组合

日期：2026-08-18。action 类型：step-resume（trajectory t0, step 4, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t0-s04.md`（Phi 仅从 t0 选中
e00015、e00001；候选设计与裁决未使用其他轨迹结果）。本次 resume 前 c1/e00021
已完成并登记，只补做 pending c2/e00022，然后统一 finish-step 收口。

两候选均以 e00015 的 source-part activity guard 为共同父节点，并继承 t0 的
`--branchy-mux --resize-elision --init-zero-elision`。共同正式对照为
e00015 = 247.458s（CV 0.82%）。

## 候选设计与可证伪假设

### c1 `source-part guard + wide-storage-first-touch`（状态布局规则面）

- 分支 `tes/r001/t0/s04-c1`，tip commit `bc29e3b`，worktree
  `build/tes/grhsim-am-coremark/src/e00021-t0-s04c1`，eval e00021。
- emit-args：`--block-chunk-instructions 3000 --branchy-mux --resize-elision
  --init-zero-elision --source-part-activity-guard --wide-storage-first-touch`。
- 机制：保留 e00015 对静默 source part 的控制流跳过，同时把宽 BitVector/Array
  存储按 scheduled Block 首触顺序重排，检验剪掉空扫描后仍实际执行的块是否保留
  状态跨度、cache/page locality 收益。
- **假设**：source-part guard 消除空 part 扫描后，wide first-touch 仍可通过
  收缩实际执行块的宽态跨度/page 足迹独立改善 locality；叠加到 e00015 使 Host
  中位再降 >=3%；<1.5% 则两机制成本重叠或布局收益不可加。

### c2 `--source-word-activity-guard`（activity 扫描规则面）

- 分支 `tes/r001/t0/s04-c2`，tip commit `68b0634`，worktree
  `build/tes/grhsim-am-coremark/src/e00022-t0-s04c2`，eval e00022。
- emit-args：`--block-chunk-instructions 3000 --branchy-mux --resize-elision
  --init-zero-elision --source-part-activity-guard --source-word-activity-guard`。
- 机制：在已经通过 source-part guard 的 `eval_scan_*` / `eval_commit_*` 内，按
  64-block `activeWords_` word 聚合同属 byte chunks；每个 word 先做一次只含本
  source part owned bits 的精确 mask 检查，空 word 直接跳过逐 byte
  snapshot/clear/relay。首尾 partial word 不读取相邻 part，word 静态升序保持
  `act.f` 同轮前向可见，原 byte relay 保持同 word 传播，`act.b` 仍留给下一轮；
  `fullEvaluation` 旁路新 guard。开关默认 off。
- **假设**：e00015 仍会在活跃 source part 内逐 byte 扫描；按 64-block activity
  word 增加精确二级守卫可利用约 5,862/86,381 块每 round 的稀疏性跳过空 word，
  使 Host 中位再降 >=3%；<1.5% 则 part guard 已吸收主要扫描成本。
- CLI、文档、代码生成 oracle 与语义 harness 随 commit 提交。完整 SimTop emit
  生成 **1,637 个精确 word guard，覆盖 334 个 source 文件**；测试 oracle 覆盖
  跨 word、跨 source-part 和 partial mask（如 `0xfff8000000000000`、`0xf`、
  `0xff80000000000000`、`0x3`、`0x4`）。

### 机制互异性

c1 不减少被执行代码的 activity 扫描次数，主要改变宽状态的物理地址局部性；c2
不改变状态布局，主要减少活跃 source part 内部空 word 的动态控制流和逐 byte
适配工作。二者分别作用于数据 locality 与 activity 扫描层级，满足 K=2 机制互异。

## 正式评估结果

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00015 |
|---|---|---|---:|---|---|---:|
| e00021 | c1 guard + first-touch | ok；ctest 17/17；3 rep difftest 全过 | 608.9s | 238923 / 240206 / 239354 | **239.354s / 0.27%** | **-3.27%** |
| e00022 | c2 source-word guard | ok；ctest 17/17；3 rep difftest 全过 | 596.7s | 230568 / 229984 / 232888 | **230.568s / 0.66%** | **-6.83%** |

所有 rep 均为 `instrCnt=73,580`、`cycleCnt=49,996`、进程 rc=0，nemu 在线
difftest 无 mismatch；两项结果均非 noisy，且 compile_s 远低于 2400s 门。
e00022 比 e00021 再快 **3.67%**，但这是两个独立候选的横向比较，不代表已经测量
了 word guard 与 first-touch 的组合。

## 机制分析

### c1：确认 source-part guard 与 first-touch 可加

- e00021 相对共同父节点改善 3.27%，刚越过预设门槛且 CV 仅 0.27%；source-part
  控制流剪枝并未吞掉宽状态 locality 的全部收益。该组合还比 action 前的 run best
  e00018 快 2.02%，因此在 c2 完成前已刷新一次 run best。
- 单独 first-touch 在 e00016 相对 e00010 曾改善 5.79%，叠加 guard 后增量缩到
  3.27%。这与 guard 改变动态热块集合、降低状态访问总量后 locality 余量收窄相容，
  但没有硬件计数器证据，不能把差值完全归因为 cache/TLB 重叠。
- 假设达到 >=3% 门，机制保留；未成为 winner 只因 c2 更快，不构成布局轴证伪。

### c2：确认活跃 part 内的空 word 扫描仍是一阶成本

- source-part guard 只消除“整个 part 都静默”的情况；只要 part 内有一个活动块，
  e00015 仍进入函数并遍历该 part 的每个 activity byte。每 round 约 5,862/86,381
  块活跃（约 6.79%）意味着 part 被打开后仍可能包含大量全空 64-block word。
- 1,637 个 word guard 把这层内部稀疏性显式化，取得 6.83% 增量收益，超过 3%
  假设门两倍以上。它说明 source-part 空扫描并非单一固定调用成本，而是至少有
  part -> word -> byte 三层可收的适配机械。
- 精确 partial mask、同轮前向传播 harness、17/17 ctest 与完整 50k difftest
  共同约束了跨 part/word 边界语义。假设完整成立。

### 两候选裁决

c2 中位比 c1 低 8.786s（3.67%），差距远高于两者 CV；机械裁决与机制裁决一致。
当前负载上，进一步利用 activity 的层内稀疏性比只改善剩余宽状态访问 locality
更有杠杆。两条机制都为正，下一次组合仍需独立正式评估，不能把 6.83% 与 3.27%
直接相加。

## evaluator 离线依赖复用

本 action 暴露了新 `eval-id` 构建目录会让 CMake FetchContent 默认再次访问远端的
基础设施缺陷。候选 worktree 的绝对源码路径不同，不能安全共用 `wolvrix/build`
的 `CMakeCache.txt` 和对象文件；但这不要求重新联网下载依赖。

`evaluator.py` 现将 fmt、mimalloc、CLI11、oneTBB 和 mt-kahypar 的三个嵌套依赖
URL 重定向到 `wolvrix/build` 中已有的本地 clone，并把 wolvrix 编译也接入共享
`build/tes/ccache`。e00021/e00022 在各自全新 wbuild 上分别以 4.5s/4.4s 完成
受限网络环境下的 CMake configure，证明配置已离线复用依赖；候选对象目录仍保持
隔离，避免 stale artifact 污染。既有评估目录未自动删除。

## 裁决与 run 影响

winner = **e00022**（score `-230568`），已 fast-forward 到
`tes/r001/t0/main`（commit `68b0634`），成为新的 t0 best 和 run
best_overall。相对 AM y0 273.103s 累计改善 **15.57%**；相对 gsim 24.688s
仍为 **9.34x**，AM/gsim 绝对差距关闭 **17.12%**。相对 action 前的 run best
e00018 244.278s 改善 **5.61%**。t0 完成 4/8 step，run 已用 22/48 eval。

## 对 Phi 下一步的建议

1. t0 再被选择时，优先正式检验 e00022 word guard + wide first-touch 的组合。
   两者都在同一共同父节点上越过 3% 门且机制正交，但组合假设应保守设为 >=2%，
   并显式允许 locality 收益因扫描减少而衰减。
2. source-word 方向继续细化前，先用不计时 instrumentation 统计每个 guard 的
   open/skip 次数、进入后的有效 byte 数和按 word 热度分布；只有动态净跳过工作
   支持 >=3% 时，才考虑更高层 summary 或连续空 word run guard。
3. 保留精确 owned mask 与 byte relay 语义，不尝试近似 activity 摘除；此前
   preset activation 省略已导致 difftest 死锁，跨轮传播边界不可凭静态稀疏性推断。
4. 状态机下一 action 是 `r001/t1/s04`。本 action 不调用 begin-step；t0 结论不得
   注入 `cross_trajectory=false` 的 t1 proposal，跨轨迹组合仍留到 restart。
