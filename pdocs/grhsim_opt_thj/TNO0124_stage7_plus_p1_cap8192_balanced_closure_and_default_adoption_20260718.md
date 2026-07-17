# TNO0124 Stage 7+ P1 cap8192 balanced closure and default adoption

记录日期：2026-07-18

状态：N0 BAAB try9 在 fresh independent `/dev/shm` inode、正确 CPU/memory binding、fixed-ASLR 和 whole-node strict protocol 下完整通过。至此 N0/N1 的 ABBA/BAAB 四个独立 SimTop 50k 组全部闭合，walltime 全部同向改善；双 node 等权 headline 为 `74,604.75 -> 74,280.00 ms`，改善 `324.75 ms`（`0.435293999%`）。虽然收益小于 1%，但方向在四组中一致，cycles/instructions 同向下降，且用户明确允许采用稳定的小幅收益，因此 C++ native commit cap default 从 `4096` 改为 `8192`；XS 脚本继续 sparse override，显式 `4096` 保留为 rollback/canonical baseline。

## 1. 对象和对历史结论的更新

本轮对象与 [TNO0118](./TNO0118_stage7_plus_p1_cap8192_corrected_runtime_attempt4_to6_20260717.md) 相同：

```text
A/control:   current C++ native-hybrid, commit cap4096
B/candidate: current C++ native-hybrid, commit cap8192
```

TNO0118 已有 N0 ABBA、N1 ABBA、N1 BAAB 三个有效组，但当时 N0 BAAB 仍缺失，因此“暂留 4096”在当时是正确的阶段性结论。本篇追加最后一个反序组并 supersede 该默认决定；不回写 TNO0118/TNO0119/TNO0120 的历史现场。

最终仍只以 SimTop 50k log 中唯一正 `Host time spent` 作为端到端 headline。cycles、instructions 和 frontend/backend PMU 仅用于检查方向与机制，不能替代 walltime。

## 2. fresh page-local staging 与正确绑定

继续使用 attempt4 的双 node 独立 staging；N0/N1、default/cap8192、coremark/NEMU 共 8 个文件 inode 均不同：

| node | file | inode | bytes | SHA-256 |
| --- | --- | ---: | ---: | --- |
| N0 | `s14_default` | `5398` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N0 | `s14_cap8192` | `5400` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |
| N0 | `coremark.bin` | `5403` | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| N0 | `nemu.so` | `5404` | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| N1 | `s14_default` | `5397` | `93,694,944` | `51b74981b0a23d93dc860e13f82248a3ec0c21153117df3f7889da55be918788` |
| N1 | `s14_cap8192` | `5399` | `93,671,816` | `28e871c4e66598b05659355b8027838f1a5e770beef803ec0434c0ef396bc1f7` |
| N1 | `coremark.bin` | `5401` | `16,712` | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| N1 | `nemu.so` | `5402` | `567,504` | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |

staging 目录：

```text
/dev/shm/tanghaojin_stage7_p1_attempt4_20260717_2153/n0/
/dev/shm/tanghaojin_stage7_p1_attempt4_20260717_2153/n1/
```

提交前重新读取实物得到的持久化 stat/SHA manifest：

```text
build/logs/xs/stage7_cap8192_cpp_default_staging_stat_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_staging_sha256_20260718.log
```

N0 正式 runner 使用：

```text
taskset -c 43 \
  numactl --physcpubind=43 --membind=0 \
  perf stat ... -- \
  setarch x86_64 -R <node-local-emu> ... -C 50000
```

CPU43 是 target，CPU235 是 SMT sibling，CPU191 是 gate/monitor helper。`taskset` 与 `numactl --physcpubind` 双重约束 runner CPU，`numactl --membind=0` 约束匿名/新 fault memory，`setarch x86_64 -R` 关闭 ASLR。`/proc/<pid>/status` 的 `Mems_allowed_list=0-1` 是作业 cpuset allowance，不是当前进程 mempolicy，不能据此判定 membind 失效；实际 placement 由 runner 命令和 `/proc/<pid>/numa_maps` 页计数闭合。

## 3. 为什么早期 N0/N1 会出现大差异

NUMA0 和 NUMA1 的 CPU/内存拓扑本身近似对称，早期巨大差异不能直接归因于 cap 机制的 node-specific 行为。同一 inode/page cache 被跨 node 复用是已经确认的重要污染源：文件映射页已经在先运行的一侧进入 page cache 后，后续进程即使带 `--membind=<other-node>`，也会复用现有 file-backed page；membind 不会自动把共享 page-cache 页迁到另一 node。因此“CPU 绑在 N1”不等于 emu/NEMU 文件页也在 N1，先后顺序可能被误读成 NUMA 不对称。

不过，page cache 单项证据不能证明全部历史反转都只来自这一原因；旧组还混有非镜像 target/sibling、whole-node 外部负载和运行前内存状态等变量。当前协议同时固定镜像拓扑、全 node admission/runtime monitor、fresh inode 和 page placement，才使 N0/N1 具备可比较性。

修正方法是为每个 node 和 variant 创建 fresh independent `/dev/shm` inode，staging copy 本身也在对应 node 上执行 `taskset + numactl --physcpubind + --membind + cp --reflink=never`，然后正式 run 再使用同样的 CPU/memory binding。当前 N0 try9 四样本的 placement 均为：

```text
default emu: 21264 pages on N0, 0 on N1
cap8192 emu: 21260 pages on N0, 0 on N1
NEMU:         115 pages on N0, 0 on N1
```

对应 N1 历史有效组为 `0/21264`、`0/21260` 和 `0/115`。placement gate 直接审计 emu 与 NEMU file-backed 页；CoreMark 保留独立 inode/bytes/SHA，载入后的 guest memory 由 runner 的 membind 约束。本轮协议消除了已知 page-cache 污染并同时控制其它环境变量，不能反向声称所有旧反转只由单一因素造成。后续所有正式性能实验都必须继续使用独立 inode 和 page-local placement gate。

## 4. N0 BAAB try9 admission

正式组目录和 driver log：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/groups/n0/stage14_cap8192_strict_p1_baab_try9/
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_baab_try9_driver_20260718.log
```

启动前 survey raw：

```text
build/logs/xs_perf/page_local_retest_stage7plus_20260716/stage14_cap8192_strict_p1_try9_survey_20260718/n0.log
```

survey 绝对 summary 为 count `192`、mean `99.500625%`、minimum `97.930000%` on CPU4、target CPU43 `99.730000%`、sibling CPU235 `99.270000%`，全部通过。

四次 per-run pre-gate 都在 attempt1 通过：

| sample | whole-node mean/min | target/sibling | gate-to-run gap |
| --- | --- | --- | ---: |
| b1 cap8192 | `99.519427% / 97.800000%@CPU29` | `99.670000% / 99.100000%` | `8 ms` |
| a1 default | `99.421719% / 95.860000%@CPU277` | `99.130000% / 98.900000%` | `7 ms` |
| a2 default | `99.403542% / 96.460000%@CPU256` | `98.560000% / 99.700000%` | `7 ms` |
| b2 cap8192 | `99.496354% / 98.200000%@CPU4` | `99.500000% / 99.670000%` | `7 ms` |

runtime monitor 均覆盖除 target 外的 `191` 个 logical CPUs：

| sample | runtime mean/min |
| --- | --- |
| b1 | `99.497487% / 97.900000%@CPU277` |
| a1 | `99.502304% / 97.400000%@CPU256` |
| a2 | `99.474241% / 97.010000%@CPU256` |
| b2 | `99.490576% / 98.000000%@CPU63` |

四样本的 `run_status` 均为 `0`，placement/monitor/perf/scheduler/function/affinity/walltime 的 `*_ok` 均为 `1`，walltime count 均为 `1`，ASLR personality 均为 `00040000`，migration 均为 `0`。functional signature 均为 `instrCnt=73580`、`cycleCnt=49996`、guest `50001`。

## 5. try9 四样本绝对结果

| sample | variant | wall ms | cycles | instructions | frontend empty | cmask6 | backend | task-clock ms | ctx | emu pages N0/N1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| b1 | cap8192 | `74,398` | `271,928,316,482` | `164,223,367,468` | `1,243,487,555,287` | `161,266,583,227` | `90,613,811,890` | `74,316.23` | `814` | `21,260/0` |
| a1 | default | `74,677` | `273,160,250,628` | `164,521,452,241` | `1,249,481,290,520` | `162,185,420,483` | `91,126,514,076` | `74,649.06` | `862` | `21,264/0` |
| a2 | default | `74,830` | `273,778,251,221` | `164,521,452,125` | `1,253,659,621,069` | `162,846,435,538` | `90,708,035,995` | `74,809.48` | `775` | `21,264/0` |
| b2 | cap8192 | `74,532` | `272,662,992,517` | `164,223,367,483` | `1,247,324,404,952` | `161,906,674,194` | `91,150,426,590` | `74,507.88` | `839` | `21,260/0` |

BAAB wall headline：

```text
default  = (74677 + 74830) / 2 = 74753.5 ms, spread 153 ms
cap8192  = (74398 + 74532) / 2 = 74465.0 ms, spread 134 ms
delta    = -288.5 ms = -0.385935107%
```

同组 PMU 均值：

| metric | default mean | cap8192 mean | delta |
| --- | ---: | ---: | ---: |
| cycles | `273,469,250,924.5` | `272,295,654,499.5` | `-1,173,596,425.0` (`-0.429151146%`) |
| instructions | `164,521,452,183.0` | `164,223,367,475.5` | `-298,084,707.5` (`-0.181182881%`) |
| frontend empty | `1,251,570,455,794.5` | `1,245,405,980,119.5` | `-6,164,475,675.0` (`-0.492539245%`) |
| cmask6 | `162,515,928,010.5` | `161,586,628,710.5` | `-929,299,300.0` (`-0.571820443%`) |
| backend | `90,917,275,035.5` | `90,882,119,240.0` | `-35,155,795.5` (`-0.038667894%`) |

## 6. 四组、双 node balanced headline

| group | default mean | cap8192 mean | delta |
| --- | ---: | ---: | ---: |
| N0 ABBA | `74,788.0 ms` | `74,385.0 ms` | `-403.0 ms` (`-0.538856501%`) |
| N0 BAAB | `74,753.5 ms` | `74,465.0 ms` | `-288.5 ms` (`-0.385935107%`) |
| N1 ABBA | `74,228.5 ms` | `73,808.5 ms` | `-420.0 ms` (`-0.565820406%`) |
| N1 BAAB | `74,649.0 ms` | `74,461.5 ms` | `-187.5 ms` (`-0.251175501%`) |

N0 四样本 balanced 为 default `74,770.75 ms`、cap8192 `74,425.00 ms`，delta `-345.75 ms`（`-0.462413444%`）；raw spread 为 `153/219 ms`。N1 四样本 balanced 为 `74,438.75 -> 74,135.00 ms`，delta `-303.75 ms`（`-0.408053601%`）；raw spread 为 `701/990 ms`。

两个 node 等权 headline：

```text
default  = (74770.75 + 74438.75) / 2 = 74604.75 ms
cap8192  = (74425.00 + 74135.00) / 2 = 74280.00 ms
delta    = -324.75 ms = -0.435293999%
```

每个 variant 各有 8 个 raw 样本，总计 16 个；default 8 样本 spread 为 `776 ms`，cap8192 8 样本 spread 为 `990 ms`。N0/N1 node mean 差分别为 `332/290 ms`。绝对 spread 说明单个小组仍会受机器波动影响，但四个独立顺序组方向一致，避免了只凭某个 node 或某个顺序晋升。

双 node balanced PMU：

| metric | default | cap8192 | delta |
| --- | ---: | ---: | ---: |
| cycles | `272,963,871,692.125` | `271,767,968,092.375` | `-1,195,903,599.750` (`-0.438117906%`) |
| instructions | `164,521,452,328.875` | `164,223,367,665.250` | `-298,084,663.625` (`-0.181182855%`) |
| frontend empty | `1,248,969,936,319.125` | `1,242,550,296,339.125` | `-6,419,639,980.000` (`-0.513994756%`) |
| cmask6 | `162,101,981,019.500` | `161,097,687,173.625` | `-1,004,293,845.875` (`-0.619544462%`) |
| backend | `90,556,987,134.750` | `90,565,881,220.375` | `+8,894,085.625` (`+0.009821534%`) |

wall、cycles、instructions 和 frontend 指标一致支持小幅正收益；backend 近乎中性。采用结论仍由 walltime 决定。

## 7. 默认采用与保持不变的语义

默认值只在 `ActivityScheduleOptions` 的 C++ 定义中改为 `8192`。XS Python/Makefile 不再额外注入同值默认；未设置时日志继续显示 `max_op_in_commit_supernode=cpp-default`，显式环境变量/CLI 仍可覆盖为 `4096` 或其它合法值。

以下 `4096` 不是旧默认残留，而是 canonical layout 契约，全部保持不变：

- `kMaxGuardEventMergeOps = 4096`；
- `baselineMergeLimit = min(requestedCap, 4096)`；
- high-cap 只顺序合并完整、连续的 baseline cluster，不拆分或跨越 locality group；
- atomic guard/ordered write group 仍不可拆；
- `commitLocalityGroupByOp` 和 `commitLocalityGroupOrder` 仍在 high-cap merge 前建立；
- emitter 的 commit state anchor、first-read order 和 value-slot locality 仍基于 canonical 4096 group；
- 显式 `4096` 继续作为 rollback/canonical baseline。

默认 8192 只改变实际 commit execution partition；它不把 canonical group 大小改成 8192，也不在 XS 脚本制造第二个默认来源。

## 8. 实现验证入口

采用提交必须闭合：

```text
focused activity-schedule test: default == explicit 8192
explicit 4096 canonical fixture remains independently checked
XS clean sparse options remain {}
fresh default production == prior explicit-cap8192 production
```

fresh default 预期绝对结构为 `63,709` total supernodes、`63,241` compute supernodes、`468` commit supernodes；`activity_schedule_supernode_stats.json` 预期 SHA-256 为：

```text
6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
```

完成上述 gate 后，再从新 current default 重新生成 terminal pushforward off/strict；TNO0123 的 cap4096 strict ELF 只保留为结构/功能证据，不能直接与新 default 做最终 walltime A/B。

## 9. 实现与 fresh default production 结果

C++ option default 已改为 `8192`，XS Python/Makefile 未增加同值默认。focused fixture 同时运行 default、explicit4096、explicit8192 和 non-multiple high cap6144：default 与 explicit8192 full session byte-identical；explicit4096 继续作为 canonical baseline 验证 locality group/order，cap6144 继续验证只合并完整 baseline cluster。

focused 和配置测试绝对结果：

```text
transform-activity-schedule  1/1 PASS, test 0.20 s, CTest total 0.21 s
pybind activity options      5/5 PASS, 0.001 s
XS sparse options           17/17 PASS, 0.027 s
```

raw log：

```text
build/logs/xs/stage7_cap8192_cpp_default_focused_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_pybind_options_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_xs_options_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_editable_install_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_full_build_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_full_ctest_20260718.log
```

完整 build PASS；串行 full CTest 为 `46/48` PASS、总耗时 `386.66s`。两个失败仍是此前各阶段相同的 `transform-comb-lane-pack` 和 `transform-repcut`，无新增失败。full CTest 之后补强 explicit8192 commit-count 断言，并以上述最终 focused raw 再次通过。

fresh production 从与历史 cap8192 相同的 Stage8 post-stats 恢复，不设置 `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE`：

```text
build/xs_activity_stage23_cap8192_cpp_default_20260718/grhsim/grhsim_emit/
build/logs/xs/xs_wolf_grhsim_build_activity_stage23_cap8192_cpp_default_20260718.log
```

入口日志明确为：

```text
max_op_in_commit_supernode=cpp-default
final_terminal_pushforward_policy=cpp-default
```

这里的 `cpp-default` 是 Makefile `[CMD]` 展示占位符；实际 recipe 在无 override 时省略 `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE` 环境变量，由 C++ option 提供 `8192`。

fresh absolute structure：

| metric | value |
| --- | ---: |
| total supernodes | `63,709` |
| compute supernodes | `63,241` |
| commit supernodes | `468` |
| DAG edges | `527,990` |
| boundary values | `1,000,463` |
| total boundary activation edges | `1,983,326` |
| compute-compute value pairs | `1,721,698` |
| compute-commit value pairs | `261,628` |
| commit input root values | `261,654` |
| commit sink ops | `218,994` |
| commit event-key runs | `468` |
| commit event keys | `450` |

activity pass 用时 `165,267ms`，write C++ `58,742ms`，Python flow 总计 `251,148ms`，exit `0`。

fresh 与 Stage18 explicit-cap8192 artifact 的 `137` 个共同生成文件经 SHA manifest 和 `diff -u` 全部 byte-identical；fresh 目录额外保留本轮 path-bearing `wolvrix_read_args.txt`。两个 137-line manifest 的 SHA-256 均为 `2ba5a60705f0fabb1639e54416ba9f893af9457ad07cf8cc4e02ba0fd6a81d99`，diff raw 为 0 lines：

```text
build/logs/xs/stage7_cap8192_explicit_prior_common_manifest_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_fresh_common_manifest_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_manifest_sha256_20260718.log
build/logs/xs/stage7_cap8192_cpp_default_manifest_diff_20260718.log
```

关键生成统计 SHA-256：

```text
activity_schedule_supernode_stats.json
6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c

grhsim_emit_stats.json
9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

因此无 override 的 C++ default 已机械等价于被四组 walltime 裁决的 explicit cap8192 program；无需把同一个程序再作为另一候选重复解释。下一阶段 terminal pushforward 仍须在这个新 default 上重新生成 strict 侧，因为其 schedule rewrite 会与 8192 commit partition 共同决定最终代码。
