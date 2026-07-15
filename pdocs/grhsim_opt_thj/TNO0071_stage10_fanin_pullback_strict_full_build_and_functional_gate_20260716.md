# TNO0071 Stage 10 fanin pullback strict full build and functional gate

记录日期：2026-07-16

状态：Stage 10 strict 完成 full C++ emit、O3/link 与 fixed-ASLR 100/10k 功能门禁；结构结果精确复现、功能 PASS，进入 NUMA0/NUMA1 quiet 50k A/B/A。

## 1. Full emit 复现

从与 structure scan 相同的 canonical post-reg checkpoint 恢复，显式锁定 current-default NO0300 的其余生成配置，仅开启：

```text
final_fanin_pullback_policy=strict
max_node_ops=8
max_value_width=64
min_gain=3
max_moves=4096
max_moved_op_ppm=5000
```

full emit 再次得到：

```text
exact eligible / selected / applied  84 / 84 / 84
moved ops                            262
projected / actual BAE gain          254 / 254
supernodes                           63726
DAG edges                            528622
total BAE                            1983669
compute pairs                        1721444
compute-commit pairs                 262225
validators                           all true
```

stats SHA256 仍为 `133ad4da5abf7e93202ccb466cd4940c3a81f8abe8d1bb0b82b076a1a6478520`，与 structure scan 记录一致。activity-schedule 用时 177.922 秒，C++ emit 54.047 秒，脚本总计 260.777 秒。

## 2. Generated C++ 静态对比

控制组是 Stage 7 fresh rollback，即仓库当前 NO0300 默认生成配置。两边均为 117 个 schedule translation unit、155 个 C++/header/Makefile 文件。

| Metric | NO0300 control | Stage 10 strict | Delta |
| --- | ---: | ---: | ---: |
| generated source bytes | `1,377,541,137` | `1,377,525,922` | `-15,215` (`-0.001104%`) |
| generated C++ lines | `13,904,899` | `13,905,049` | `+150` (`+0.001079%`) |
| schedule `.cpp` count | `117` | `117` | `0` |

84 个局部 move 改动 83 个生成文件的 hash，但未改变 batch/file 数。源码 byte 小幅减少而行数微增，量级不足以预判 runtime。

## 3. O3 与 ELF

使用 XiangShan difftest GrhSIM O3 标准构建参数，117 个 schedule unit 编译、archive 与最终 link 全部 PASS。

| Metric | NO0300 control | Stage 10 strict | Delta |
| --- | ---: | ---: | ---: |
| ELF bytes | `94,768,184` | `94,772,280` | `+4,096` (`+0.004322%`) |
| `.text` bytes | `94,592,303` | `94,597,551` | `+5,248` (`+0.005548%`) |
| `.data` bytes | `9,368` | `9,368` | `0` |
| `.bss` bytes | `14,688` | `14,688` | `0` |

候选 emu SHA256：

```text
7ee3d3d59db975aae5ac61a6139583039cea649923f38d496a48f0eb5bc30706
```

`.text` 的轻微增加属于 layout 变化，不能用静态大小否决；继续 50k 实测。

## 4. Fixed-ASLR 功能门禁

两轮均使用 `setarch x86_64 -R`、CoreMark image 与 NEMU diff：

| Gate | Guest cycles | cycleCnt | instrCnt | PC | Result |
| --- | ---: | ---: | ---: | --- | --- |
| 100 | `101` | `96` | `0` | `0x0` | PASS |
| 10k | `10001` | `9996` | `458` | `0x800027c6` | PASS |

没有 diff mismatch、assert 或异常退出。原始产物：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage10_fanin_strict_full_emit_20260716.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage10_fanin_strict_o3_20260716.log
build/logs/xs_perf/activity_stage10_fanin_strict_20260716/strict_func_100.log
build/logs/xs_perf/activity_stage10_fanin_strict_20260716/strict_func_10000.log
build/xs_activity_stage10_fanin_strict_20260716/grhsim/grhsim-compile/emu
```

## 5. 决定

full build 与功能门禁闭合，strict 保持默认关闭并进入正式性能裁决。考虑 Stage 7/8 的 socket 方向反转，分别在 NUMA0 与 NUMA1 执行相邻 NO0300 控制包夹的 quiet A/B/A；不使用跨 socket 平均值决定默认。
