# A0011 - step-resume r001/t1/s03：亲和布局重测与标量 helper 内联

日期：2026-08-16。action 类型：step-resume（trajectory t1, step 3, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t1-s03.md`（Phi 仅从 t1 选中
e00006、e00011）。本 action 恢复已由 begin-step 建好但尚无候选完成的 step，
因此跳过 begin-step，只补做 c1/c2 实施、提交、串行评估与裁决。候选设计
只使用 t1 轨迹内的历史，未注入 t0/s03 或 t2 结果。两候选都继承 t1
主线的 `--resize-elision`；主线 commit 中的 `branchlessActivation` 开关保持
默认 off，本次未启用。

## 候选设计与可证伪假设

### c1 `--state-layout affinity` - 状态按 Block 引用亲和性聚簇（emit 布局规则面）

- 分支 `tes/r001/t1/s03-c1`（tip commit `76f5c74`），worktree
  `build/tes/grhsim-am-coremark/src/e00017-t1-s03c1`，eval e00017。
- emit-args：`--block-chunk-instructions 3000 --resize-elision --state-layout
  affinity`。
- 机制：在 t1 当前主线上重建 s01/c1 的亲和布局。持久状态按静态
  Block 引用最多的 primary Block 分组，热组优先，同步重排标量成员声明和
  `wideValues_` offset；`changedResults_` 密集下标不变。为避免 affinity
  置换使百万级宽池 store 失去单调性，`init()` 中仅字面量的宽状态按最终
  物理 offset 发射；含随机初始化的变量保持 VariableId 相对顺序，不改变随机流
  到变量的映射。
- **假设**：物理 offset 顺序发射能恢复 affinity 的编译门，状态局部性再使
  Host 中位较 t1 主线降低至少 2%；若仍超 40min 预算，则在 t1 内关闭
  当前 affinity 实现路线。
- `stateLayout=id` 仍是默认且输出不变；CLI、文档、确定性、成员/宽池不变式、
  初始化顺序和生成模型 oracle 测试随 commit 提交。GRH IR 和 AM IR 语义未改变。

### c2 `--inline-scalar-helpers` - 窄标量 helper 头文件内联（emit 规则面）

- 分支 `tes/r001/t1/s03-c2`（tip commit `deb4c37`），worktree
  `build/tes/grhsim-am-coremark/src/e00018-t1-s03c2`，eval e00018。
- emit-args：`--block-chunk-instructions 3000 --resize-elision
  --inline-scalar-helpers`。
- 机制：将窄标量 `slice_value`、`shift_left`、`shift_right`、
  `arithmetic_shift_right` 和 `signed_value` 的定义从 runtime TU 移入生成
  header，以 `constexpr` 定义使每个 Block TU 可在调用点做常量传播与
  内联。除法、取模以及宽值/数组 helper 仍 outlined，避免把大循环复制到海量
  调用点。冻结 CoreMark 模型静态覆盖 424,064 个 slice 与 107,130 个
  逻辑移位站点，另有少量 signed/算术移位站点。
- **假设**：若这些跨 TU 标量 helper 调用位于热路径，消除外联调用并暴露
  常量参数后，Host 中位较 t1 主线下降至少 3%。
- 开关默认 off，off 时仍发射原 runtime 定义。CLI、文档、头文件/runtime 定义
  位置和生成模型编译测试随 commit 提交；helper 语义未改变。

### 机制互异性

c1 不改变指令形状或 helper 调用，只重排持久状态物理布局，主要目标是
cache/TLB 局部性；c2 不重排任何状态，只消除窄标量跨 TU 调用边界，主要目标
是调用开销和编译器跨调用点优化。两者的数据面、动态成本与可失败方式均不同。

## 正式评估前证据

- 两候选的 focused `grhsim-am-cpp-emitter` 测试通过，冻结 XiangShan exec-GRH
  均成功发射 5,340,930 条 scheduled instruction 和 328 个 artifact；
  正式 evaluator 随后对两者均完整执行 17 项 grhsim ctest。
- c1 生成 `init()` 中有 1,663,331 个直接宽池 store，静态检查无 offset
  逆序；103MB runtime TU 的独立 `-O3` 预检最终在约 26min 后产出 7.0MB
  object。该预检只证明 TU 可终止，不代替评估器的 40min 全流水线门。
- c2 大模型 header 包含上述 5 个标量定义，runtime TU 不再包含它们的
  外联定义；宽 helper、除法和取模定义保持 outlined。

## 正式结果

共同对照为 t1 轨迹 best e00006 = 270.502s（`--resize-elision`）。

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00006 |
|---|---|---|---:|---|---|---:|
| e00017 | c1 affinity state layout | **compile_timeout**；ctest 17/17、emit 已过；未进入 difftest | 2399.1s（emu_build 1611.0s 未完成） | - | - | 无运行时证据 |
| e00018 | c2 inline scalar helpers | **ok**；ctest 17/17；3 rep difftest 全过 | 2006.3s（emu_build 1229.6s） | 243140 / 250541 / 244278 | **244.278s / 1.62%** | **-9.69%** |

e00018 的所有 rep 均为 `instrCnt=73,580`、`cycleCnt=49,996`、进程 rc=0，
nemu 在线 difftest 无 mismatch；e00017 因编译门失败，没有 Host 计时或功能门读数。

e00017 首次启动在受限沙箱中于 CMake FetchContent 阶段因 DNS 禁止立即
`build_fail`，尚未编译候选代码；随即在获批网络环境下以同一 eval-id 从头
执行正式流水线，只登记后者的终态结果。两次正式候选均使用独立冷
build dir，CMake configure 分别为 463.9s 与 453.3s，设置成本量级对称，
并且按协议纳入 2400s 总预算。

## 机制分析

### c1：发射顺序修复成立，但全流水线编译门仍失败

- 物理 offset 单调性和独立 runtime.o 完成证明新顺序规则按设计工作，
  但 26min 单 TU 仍是病态成本；叠加 Wolvrix build、17 项 ctest、emit、其他
  生成 TU 与 link 后，正式流水线无法在 40min 内产出 emu。
- 本结果只否决当前 affinity + 百万级显式 init store 的可采纳性，不否决
  状态 locality 的运行时机制，因为候选从未进入 difftest 或 Host 计时。
- 按 proposal 的可证伪边界，t1 内关闭该 affinity 实现路线；若在 restart 后
  重开，必须先用结构性 init 消除或等价方案将全流水线编译成本拉出风险区，
  不再只调整显式 store 顺序。

### c2：确认，跨 TU 标量 helper 是一阶热路径

- 9.69% 改善远高于本机约 2% 的谨慎裁决带，CV 1.62% 且三次 difftest
  全过，假设的 3% 门槛完整成立。两候选的 AM instruction/schedule 计数完全
  一致，收益来自 C++ 生成代码边界，不是更少的 AM 工作量。
- 至少 531,194 个静态 slice/逻辑移位站点使原 runtime TU 外联调用成为
  密集适配胶。把小 helper 定义暴露给 Block TU 后，调用开销、常量 width/start
  传播与周边表达式合并可同时发生。本次无反汇编/动态站点计数，不把
  9.69% 进一步强行分配给其中某一子机制。
- compile_s 2006.3s 只剩 393.7s 协议裕量。当前的选择性边界是承力设计：
  宽值、数组、除法与取模的大 helper 仍应 outlined；后续内联扩张必须同时给出
  调用点覆盖和生成代码/编译预算模型。

## 裁决与 run 影响

winner = **e00018**（score `-244278`），已 fast-forward 到
`tes/r001/t1/main`（commit `deb4c37`）。它同时成为新的 t1 best 和
run best_overall：

- 相对 t1 旧 tip e00006 270.502s 改善 **9.69%**；
- 相对旧 run best e00015 247.458s 改善 **1.29%**；
- 相对 AM y0 273.103s 改善 **10.55%**；
- 相对 gsim 24.688s 仍为 **9.89x**，AM/gsim 绝对差距关闭 **11.60%**。

t1 完成 3/8 step，run 进度为 t0/t1/t2 = 3/3/2，已用 18/48 eval。
后续 t1 候选必须继承 `--resize-elision --inline-scalar-helpers`，否则不是从
当前轨迹 winner 继续。

## 对 Phi 下一步的建议

1. 未来再回到 t1 时，优先将 scalar helper 收益拆成 slice 与 shift/signed
   子族的静态/动态覆盖，再决定是否需要独立正式候选；未有覆盖证据前不
   扩张到大 helper。
2. t1 内将当前 affinity 布局实现标记为编译预算失败，不再为 store
   顺序微调消耗评估。只有 restart 阶段可结合跨轨迹的 init 消除知识重新建模。
3. 下一 action 是 `r001/t2/s03`。`cross_trajectory=false` 下，下一 proposal
   必须只使用 t2 轨迹历史，不得将本次 scalar-helper 结论注入其候选设计。
