# SimpleTES B native fresh build regression

## 构建来源与输入

接续 [B 实现记录](./TNO0296_simpletes_b_native_landing_20260909.md) 和
[SimpleTES 交接](./TNO0297_simpletes_b_native_baseline_handoff_20260909.md)，
本轮在 node032 从当前 pre-B 源码分别全新构建 base 与 base+B。
两份独立 clone 顺序准备后并行构建；冻结目录为：

```text
build/grhsim_b_landing_20260909/run_node032_v1/
  frozen/
  base/repo/
  base_B/repo/
  snapshots/base/
  snapshots/base_B/
```

base parent 为 `4d59a0e15c7d47d7dfb7abeea4624530393db895`，
base Wolvrix 为 `6a895c9375b029e0a65e7512dfcf0fbbc2c0007a`。
B 在这份来源上使用实际冻结的生产 emitter 与新增测试，之后源码提交
`94109bc` 不改变这些文件内容。构建 provenance 如实记录“旧 commit 加实际
B 文件修改”，不把尚未产生的 commit 写成构建来源。

实际冻结身份：

| 内容 | SHA-256 |
| --- | --- |
| base emitter | `0ed757db91f79df795562677d6f22789ad1aa84df818ef43786e8a18f6bdb196` |
| base+B emitter | `4d1aaff4b647ed3e064335d80762253666572fef2e0c1bebc574c1035768d051` |
| 实际生产 diff | `5751e584861f0eaa137d9053eb4cf4d1796688bffc874a2a53a84b6cc5d8a00f` |
| 固定 generation input | `0c63c3180527dd97382c69781d0042637758dfed5ed4c601cd6195fa07379545` |
| 冻结 evaluator | `2259d4d3e1f5e4c88527d01d521afbd7ae89101eceeb62b99578b510a505dcec` |
| 冻结 runtime | `78b3940db9b5ae3f3eff9b711f2a525564baf6b77317b214a82253c97f7a98cd` |
| 构建 harness | `4bcbe70115274c85acb4c79a05a55536ae340386c56f2f04c10f9ad34b69483f` |

冻结 RTL/生成输入来自既有消融目录的 `work_v1/A/candidate`，仅复制输入文件，
不使用该 arm 的 emitter、JSON resume 或二进制。实际核对 2,114 个冻结文件
的 SHA manifest，通过完整 RTL 读取、图变换、调度与 C++ 生成。

## 已完成的生成与代码差异检查

使用 clang 19.1.1，双方普通模型 `CXXFLAGS=-std=c++20 -O3`，无 PGO/BOLT
选项；每份模型 make 4 jobs、native build 8 jobs。两份实际 CMakeCache 均为
`WOLVRIX_ENABLE_MT_KAHYPAR=OFF`、`WOLVRIX_ENABLE_LIBFST=OFF`，这些是
构建时可选库配置，GrhSIM 生成 option 为 `{}`，没有额外启用优化的配置覆盖。
双方 resume、stats、waveform、perf 都关闭，完整 build-config/toolchain
指纹在产物完成后再次核对。

双方 comb-lane-pack 均得到 4,159 个 group，comb-loop-elim 均为 0 个环，
reg-to-mem 均处理 4,318 组；调度输入均为 6,990,363 ops、10,150,909
topo edges。生成总耗时分别为 1,296.166 / 1,309.105 秒；这些是构建耗时，
不作为最终仿真性能指标。

完整比较双方生成 `.cpp/.hpp`：恰好 57 个文件不同，仅有 2,074 行
`unlikely(activeWordFlags...)` 改为 `GRHSIM_LIKELY(activeWordFlags...)`，
以及 header 新增的 3 行宏定义，其余新增/删除行数量为 0。
base 的该 likely guard 数为 0，base+B 为 2,074。
没有混入 A 的 seed-mask packing、C 的 clear suppression 或其他代码改动。

双方已有默认优化统计相同：direct-state-read 为 75,830 reads；
direct-hot-input-event 为 applied=1、selected=0、covered=76；
commit-exact-event 为 targeted-cold-layout、cold_guards=46,655。

本条记录形成时，两份模型均有 132 个编译对象，正在并行编译。
二进制 SHA/大小、100/10k 功能结果与最终构建身份核验在实际完成后追加。

## 构建与功能门禁完成

两份构建全部成功，harness exit 0，`build_summary.json` 已产生；全部编译
进程结束后才启动正式性能组。双方 pybind 均为 `Ran 32 tests / OK`。
固定 ASLR 的 100/10k 功能检查均通过，personality 为 `00040000`，无 NEMU
mismatch、assert/fatal 或非零退出状态。

| 项目 | base | base+B |
| --- | ---: | ---: |
| 构建及门禁耗时 | 2,173.204 s | 2,192.376 s |
| ELF 文件大小 | 83,521,600 bytes | 83,624,000 bytes |
| 100-cycle 功能 Host walltime | 327 ms | 264 ms |
| 10k-cycle 功能 Host walltime | 4,402 ms | 3,934 ms |

ELF 增加 102,400 bytes（100 KiB，约 +0.1226%）。100-cycle 两边计数均为
instr=0 / cycle=96 / guest=101；10k-cycle 均为 instr=458 / cycle=9996 /
guest=10001。上述短程 walltime 只是功能门禁记录，未按正式同 CCD
ABBA+BAAB 协议测量，不能据此计算或宣称 B 的性能收益。

实际产物身份：

| 内容 | base | base+B |
| --- | --- | --- |
| emu SHA-256 | `44bec9cf27f45e947af38a54a0e9e7b541ad96949c20a147062d7f457f89a6d7` | `d3a0bcb2a3cde45c06d5c38b424832bff8286aada34ad81735136844aac5597c` |
| generated fingerprint | `1dba3cab6d75b860539f6104f6319297b63e754a84f3bf534fc70b7ae38c9b69` | `083210b9a6fbf67ae379917f83d4975d702d94e742a5960fd2900d678345fce7` |

双方相同的完整身份：

- build config：`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`；
- native config：`ab2119b7d9b4bae4f85c868971af16d42ffe9bc43bee9b72aa044fa40b51b4a4`；
- toolchain：`7669097de01707e2fab9a40ae7b308617c33dece545dcc5a6e0d38be217b98bc`；
- coremark.bin：`c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`（16,712 bytes）；
- nemu.so：`094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e`（567,504 bytes）。

实际默认生成参数核验包括 maxops=108、split=True/108、batch=2048/8192/64、
cpp=1、emit parallel=4、storage aliases=0；commit maxops、guard buckets、
active-mask-gap-pack、commit-exact-event 均使用 cpp-default。
完整构建日志中没有 profile generation/use、llvm-profdata、llvm-bolt 或
perf2bolt 命令，ELF 也无 llvm_prf/.bolt sections。

日志与 manifest 随 `snapshots/{base,base_B}/logs` 一同冻结。性能测试使用
这两份新快照，结果与完整八项稳定性审计另行记录。
