# TNO0006 BootROM 兼容适配与 after native 功能门

## 首次失败与原因

after 原始 native binary 已完成全图 C++ 编译，但 10,000 周期 smoke 在第一次提交时失败：guest cycle 587，提交 PC `0x10000000`，指令 `0x74446073`，t0 的 REF/DUT 值分别为 1/0。原日志显示的 trap-event PC 为 0，不能代表本次提交 PC。

冻结的 NEMU 仅导出旧 `difftest_load_flash(path, size)` 接口。上游 DUT 默认 BootROM 已扩展为 6 条指令、24 字节；旧 REF 接收空路径时仍使用其内部的 3 条旧指令。DUT 的首条指令是 `csrrsi x0,mnstatus,8`，REF 却从 `addiw t0,zero,1` 开始。错误来自两端启动 ROM 不一致，不能通过跳过 DiffTest 处理。

用 DUT 的 24 字节 ROM 显式传入旧 REF 后，10k DiffTest 通过。源代码、符号、ROM 字节和独立 loader probe 记录在 [flash ABI audit](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/flash-abi-audit.json)。首次失败的 binary/manifest/log 保存在 `artifacts/kunminghu-v3-grhsim-merge-20261110/after-single-initial/`，没有计入正式性能数据。

## 适配实现与提交

本地 difftest commit `b17a43ad24ae2d137f263d667787d3968505b771` 在已有 merge commit `b58c89454408426c716d90f42676c796d7f96954` 上补充：

- 旧 REF flash API 也接收实际 DUT flash bytes。Linux 使用 memfd 文件路径；其他平台使用临时文件。处理短写、EINTR 和失败，调用结束后自动释放文件。
- 新版 v2 flash API 保持上游路径。
- cycle-limit 输出使用记录的最后提交 PC，避免输出未激活 trap-event 的旧值。

XiangShan commit `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0` 固定此 difftest gitlink；真正的上游合并仍为其父提交 `9d1f24cea2726642bfe04be545f7046f845735ed`。本次仅重编译 harness，复用已冻结 RTL/model；Scala、硬件和完整 checker 没有因失败被裁剪。

## after native 功能结果

最终 binary SHA256：`d62216f60f81b0c0485922913c333997a11dcac0c93d3c3c7bcb8a653637d7f7`，104,473,224 字节。两次运行都使用冻结的 CoreMark/NEMU，默认 DUT ROM，无额外 `--flash` 参数，完整 DiffTest 开启。

| 周期上限 | 最后提交 PC | instrCnt | cycleCnt | Guest cycles | UART |
| --- | --- | ---: | ---: | ---: | --- |
| 10,000 | `0x80001cd8` | 371 | 9,995 | 10,001 | `Running C` |
| 100,000 | `0x80000c1a` | 250,838 | 99,995 | 100,001 | `Running CoreMark for 2 iterations\n` |

原始结果：[after-single-functional.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/after-single-functional.json)。本阶段与其他构建并行，仅作功能门，其时间不用于正式前后性能结论。

## 日志接口兼容

上游日志对 instrCnt/cycleCnt/Host time 使用千位分隔符；UART 使用无缓冲写入，可能出现在有缓冲的启动 banner 前。native/RepCut parser 增加逗号数字解析；native parser 将 banner 前 UART 与正常 UART 区间拼接，排除 placement/codepage 诊断行。真实 10k/100k 日志和回归测试均覆盖这些变化。不会因日志格式而伪造 PC、计数或 workload 输出。

后续 trace 覆盖规则见 [TNO0007](./TNO0007_trace_cycle_coverage_20261110.md)，正式 walltime 另文记录。
