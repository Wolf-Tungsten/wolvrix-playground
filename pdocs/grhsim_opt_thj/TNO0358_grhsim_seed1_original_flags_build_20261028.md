# TNO0358：seed 1 原始编译选项构建检查

日期：2026-10-28。执行 [TNO0357](./TNO0357_grhsim_seed1_original_flags_runbook_20261028.md)。

## 结果

node030 CPU0–383、384 个并行编译任务完成全部 7719 个模型对象，包含对齐、重归档及 harness 链接共 141.920 秒。模型选项为 `-std=c++20 -O3 -march=native -pthread`，没有 `-fno-slp-vectorize`，没有启用任何自动回退。

- 每个源文件的 SHA256 与 seed 1 no-SLP 构建记录一致，编译沿用原始源码及头文件绝对路径。
- 7719 个 archive 成员的名称与顺序逐项等于原 seed 1 archive。
- 最终 ELF 的 7116 个 compute 入口全部 64-byte 对齐。
- 最终 emu：97660752 B，SHA256 `7b1210860cc764e1cdaf3cc2789662e1e26a7b28b166d2f7d6f0fd83a76ab516`。
- archive：128975208 B，SHA256 `5b6c7e43756670b8eece1d4a43decd39a03b019aa30eaa432f727df5a06dccb9`。

新旧 ELF 的文件大小不能直接视作运行成本；性能由随后的 fresh AB/BA 判断。既有 Clang 23 兼容保护保留，本次仅按用户要求构建独立的原始选项对照。

## 产物

- [构建身份、选项、成员顺序及对齐](../../build/grhsim_seed1_original_flags_20261028/build.json)。
- [逐对象命令与源文件身份](../../build/grhsim_seed1_original_flags_20261028/objects/)。
- [链接日志](../../build/grhsim_seed1_original_flags_20261028/harness.log)、[驱动日志](../../build/grhsim_seed1_original_flags_20261028/driver.log)。
- [原始选项 emu](../../build/grhsim_seed1_original_flags_20261028/harness/grhsim-compile/emu)。
