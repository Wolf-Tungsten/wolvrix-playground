# NO00028：单目标 direct-state 通知内联化

- Node：`direct_notify_20260914_01`。
- 当前阶段：`ACCEPTED`；完整 SV→C++、fresh 编译、100k 等价和六次新旧交替均已通过。
- 根基线：NO00027，根仓库 `4a6b73b8921f32eeabab8c8389c5a98f894b3c22`，GrhSIM 子模块 `010ba1a2de7f2cf594dda5ae727ca72383cba383`；开始时根仓库干净。

## IDEA：理论假设与 profiling 证据

NO00027 的 100k 配置为 `XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2`
、`XS_SIM_MAX_CYCLE=100000`，waveform、commit trace 和 RAM trace 关闭。保留的
对照 emu 末端为 `instrCnt=240349`、`cycleCnt=99996`、guest cycles `100001`、
PC `0x80000c0c`，Host **130.152 s**（NO00027 六次新样本均值）。

本节点重新用同一 Makefile 运行目标执行 gperftools 诊断采样；采样运行 Host
**131.755 s**、退出 0、NEMU 精确通过，profile 为 26,355 个 200 Hz 样本。
`make analyze_grhsim_cpu_profile` 的完整分类为：

| 分类/函数 | 样本 | 占比 |
|---|---:|---:|
| compute task | 18,459 | 70.039841% |
| commit task | 4,712 | 17.878960% |
| evaluator | 734 | 2.785050% |
| `cpu_direct_state_changed` | 483 | 1.832669% |
| `cpu_write_cell<bool,1>` | 333 | 1.263517% |
| `cpu_replicate_words_changed<2,1>` | 274 | 1.039651% |
| `cpu_write_scalar<bool>` | 213 | 0.808196% |

profile 通过样本总数、ELF 映射、task 覆盖和符号边界检查。静态扫描同一生成
model 得到 167,716 个 `cpu_direct_state_changed(begin,count,projection)` 调用，
总计 419,633 个目标项；其中 **101,523** 个调用的 `count=1`。这些 direct commit
调用只访问非 arm 目标（419,633 个目标项中 arm 项为 0），每次都已先比较
`cpu_current != cpu_value`，因此通知只负责置活动标志和 projection 重算标志。

假设是：当前 out-of-line helper 每次单目标通知仍需函数调用、读取
`cpu_targets[begin]`、判断 `arm` 并进入一次循环；对单目标、非 arm 的常见路径，
生成器已经知道常量 `offset/mask/arm`，可将通知变成 header 内联的常量写入，
消除动态表查找、循环和调用边界。它只改变通知实现，不改变状态值、提交顺序、
活动位的 OR 语义或 quiescence projection。预期收益上界受该 helper 的 1.83%
平坦样本限制，目标是 Host **0.5–2%**；若筛选中没有稳定收益或出现任何对拍/
编译回归，则在本节点记录否定并撤销或修正。

## BASELINE 与复现边界

- 输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，SHA-256
  `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 正式比较固定 100k cycles、CPU 2、单线程、无 waveform/commit/RAM trace；正式
  顺序预注册为 `old1/new1/old2/new2/old3/new3`，Host time 为主指标，六次均需
  NEMU PASS 和精确终点。仿真止损线取当前可比 old 的 1.5 倍（约 195 s）；生成
  和编译各用 1800 s 进程树截止。
- profile、筛选日志和临时模型均放在
  `ptmp/no00028_profile_20260914_01/`，插桩运行不进入正式统计。

## IMPLEMENTED：单目标通知专门化

CPU emitter 在 `directCommitBody` 中对 `stateTargets_` 的单目标 range 发射
`cpu_direct_state_changed_one(offset,mask,arm,projection)`；多目标 range 保留
原 helper。新 helper 定义在生成 model header 的 class body 中，保持
`cpu_direct_again |= projection`，再按常量 `arm` 写 `cpu_next_arms[offset]` 或
`cpu_flags[offset] |= mask`。加入 reserved-name 检查，避免输入端口遮蔽 helper。

聚焦 `make test_grhsim_cpu_emit` 已通过：构建和 ASan/UBSan emitter fixture、
宽值/初始化/历史/状态/多时钟差分均通过，CTest **67.92 s**；private-commit
fixture 额外确认单目标通知已发射，reserved-name fixture 覆盖新符号。IR、mapping
和 schedule 未修改。

## VALIDATED：完整路线与正式六次交替

50k 冻结 flat GRH 筛选使用旧模型
`ptmp/no00027_profile_20260914_01/flow-replicate-final2/` 和候选模型
`ptmp/no00028_profile_20260914_01/flow-direct-screen/`。两次均为 50,000 cycles、CPU 2、
单线程、关闭 waveform/commit/RAM trace，并到达
`instrCnt=73580`、`cycleCnt=49996`、guest cycles `50001`、PC `0x80001312`；旧
Host **55.76 s**，候选 **54.98 s**，快 **1.40%**。该筛选只用于确认收益方向，未
进入正式统计。

正式生成从完整 XiangShan SV filelist 重新执行 `make xs_wolf_grhsim_ir`，使用现有
`build/xs/rtl` 和 `testcase/xiangshan/build/generated-src`，设置
`XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0`、`XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0`，
输出 `flow-direct-full`。Make/生成 exit 0，墙钟 **658.01 s < 1800 s**；flat GRH
与 NO00027 对照逐字节相同，SHA-256 均为
`518f41485197156a91ff13df2eacb72f23dd63fec9bbc29fd0a6ffe1b8ace923`。IR checkpoint
经过 fresh-session round-trip，候选 IR 与 NO00027 正式 IR 的 SHA-256 均为
`0229e80c1f4dd1f70d4034017ccb9aa86d2fb5aa2e304685ef21e740d6e21cf5`。

fresh 编译通过 `make xs_wolf_grhsim_ir_build_emu` 完成，`VM_BUILD_JOBS=32`，exit 0，
墙钟 **237.66 s < 1800 s**。候选 emu SHA-256 为
`d3540cf80d0e4b3044d0d57bcee983a3493ce335c4e552bb72ca74b9e66f1912`；NO00027 对照
emu SHA-256 为 `03f21daf2f9577bcada2d4ab8df51117277617eebeb4cb792e8a0e1886b994e2`。
完整候选模型静态发射 **101,523** 个单目标专用通知调用，剩余多目标通知保留旧
helper；对应旧模型没有 `cpu_direct_state_changed_one` 调用。

正式运行预注册为 `old1/new1/old2/new2/old3/new3`，固定输入 SHA-256
`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`、100,000 cycles、
`XS_NUM_CORES=1 XS_EMU_THREADS=1 XS_EMU_CPU=2`，waveform、commit trace 和 RAM trace
关闭。每次通过 `run_xs_wolf_grhsim_ir_emu`，emu 止损为 **195.23 s**，外层 Make
截止为 205 s；六次 Make/emu 均 exit 0，均启用 DIFFTEST/NEMU，未触发截止、没有
mismatch、assertion、BAD TRAP 或补跑。精确终点全部为
`instrCnt=240349`、`cycleCnt=99996`、guest cycles `100001`、PC `0x80000c0c`。

| 顺序 / RUN_ID | Host s | emu 墙钟 s | Make/emu 退出 | 状态 |
|---|---:|---:|---|---|
| old1 / `no00028_direct_old1` | 130.560 | 130.61 | 0/0 | VALID / NEMU PASS |
| new1 / `no00028_direct_new1` | 127.579 | 127.63 | 0/0 | VALID / NEMU PASS |
| old2 / `no00028_direct_old2` | 130.881 | 130.93 | 0/0 | VALID / NEMU PASS |
| new2 / `no00028_direct_new2` | 125.624 | 125.67 | 0/0 | VALID / NEMU PASS |
| old3 / `no00028_direct_old3` | 129.046 | 129.09 | 0/0 | VALID / NEMU PASS |
| new3 / `no00028_direct_new3` | 127.725 | 127.77 | 0/0 | VALID / NEMU PASS |

| Host 统计量 | old | new |
|---|---:|---:|
| 样本数 | 3 | 3 |
| 均值 s | 130.162333 | 126.976000 |
| 样本标准差 s（n−1） | 0.980005 | 1.173140 |
| 最小–最大 s | 129.046–130.881 | 125.624–127.725 |

均值减少 **3.186333 s**，按 `(old_mean-new_mean)/old_mean` 为 **2.447969%**；合并
样本标准差为 **1.080895 s**，old−new Cohen's d 为 **2.947866**。三次新运行均快于
三次旧运行，`max(new)=127.725 < min(old)=129.046`，间隔 **1.321 s**；Mann–Whitney
`U_new=0`（等价 `U_old=9`），六个样本标签分配的单侧精确 p 为 **0.05**，满足本
节点预注册的完全秩分离判据。emu 墙钟均值 old/new 为 **130.210/127.023333 s**，
方向一致；正式性能结论使用 Host time。

完整流程复现时，生成与编译分别使用以下 Makefile 目标和关键参数；所有节点日志、
计时和临时模型均保存在 `ptmp/no00028_profile_20260914_01/`，生成代码、二进制、
profile 和波形不进入提交：

```text
WOLF_ENV_SOURCED=1 PYTHON=$PWD/.venv/bin/python XS_NUM_CORES=1 \
  XS_RTL_BUILD=build/xs/rtl XS_DIFFTEST_GEN_DIR=testcase/xiangshan/build/generated-src \
  XS_GRHSIM_IR_BUILD=ptmp/no00028_profile_20260914_01/flow-direct-full \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/no00028_profile_20260914_01/flow-direct-full/model \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=0 XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 \
  make --no-print-directory xs_wolf_grhsim_ir

WOLF_ENV_SOURCED=1 XS_NUM_CORES=1 VM_BUILD_JOBS=32 XS_EMU_THREADS=1 \
  XS_GRHSIM_IR_BUILD=ptmp/no00028_profile_20260914_01/flow-direct-full \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/no00028_profile_20260914_01/flow-direct-full/model \
  make --no-print-directory xs_wolf_grhsim_ir_build_emu
```

正式运行在这两个目标上固定 `XS_SIM_MAX_CYCLE=100000 XS_EMU_CPU=2 XS_WAVEFORM=0`
`XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_EMU_THREADS=1`，只替换
`XS_GRHSIM_IR_BUILD` 和 `RUN_ID` 以选择 old/new。

## ACCEPTED：节点结论

NO00028 的单目标、非 arm direct-state 通知专门化保持活动位 OR、projection
quiescence 标志、状态比较和提交顺序，只把 emitter 已知的常量 offset/mask/arm
直接写入内联 helper；多目标通知和所有状态值语义不变。聚焦 emitter 的 ASan/UBSan、
宽值、状态、历史、初始化、多时钟差分和 reserved-name 回归已通过；完整 SV→C++、
fresh 编译、六次 100k 对拍及完全秩分离统计均通过。因此本节点判定 **ACCEPTED**。

当前候选正式均值为 **126.976000 s**，相对 NO00027 同窗口旧均值降低 **2.447969%**；
NO00028 只接受该局部收益，不代表整体约 40 s 目标已完成。最终归档顺序为先提交
GrhSIM 子模块，再提交根仓库指针、报告、goal 和索引；生成物、日志、profile 和二进制
继续留在 ptmp。保留实现的最终 GrhSIM 子模块 commit 为
`8b8c990adbeced0a46b2d1cfad5330d165e6ab2d`（`feat(grhsim): inline single-target direct notifications`）。
