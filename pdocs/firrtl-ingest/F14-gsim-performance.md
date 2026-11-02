# F14：GSIM FIRRTL→C++ 性能基线

建立日期：2026-11-02。

状态：已完成。使用现有 GSIM `compile` Make 目标，将冻结的香山
`SimTop.fir` 直接转换为 GSIM C++ 模型。该阶段只测 FIRRTL→C++ 生成，
不包含生成 C++ 的编译、链接或 emu 运行。

## 输入、工具和配置

- FIRRTL：`ptmp/xs/rtl/rtl/SimTop.fir`，1,671,325,062 bytes。
- FIRRTL SHA-256：
  `cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a`。
- GSIM 源版本：`a3ecb26`；实际复用的预构建二进制 SHA-256：
  `e0c81e2b3fb22c18c0eba2e2aee5a47cf8c9430508a1a45eba5813c1f54c05a3`。
- `dutName=default-xiangshan`，使用该配置的默认
  `--supernode-max-size=2` 和 `--cpp-max-size-KB=8192`。
- 生产入口：
  `make --no-print-directory -C reference/gsim compile`，并覆写
  `FIRRTL_FILE`、`BUILD_DIR`、`WORK_DIR` 和 `GEN_CPP_DIR` 到独立试跑目录。

第一次调用因 Make 尝试重建 GSIM 而缺少系统 `gmp.h`，在 4.654 秒退出；
正式计时复用了已存在的 GSIM 二进制，并将 `GSIM_OBJS` 置空以跳过工具重建。
该准备失败不计入 FIRRTL→C++ 结果。

## 结果

| 指标 | 数值 |
| --- | ---: |
| 外层 Make/监督器墙钟 | **778.590 s（12 分 58.6 秒）** |
| GSIM `/usr/bin/time` elapsed | 776.16 s（12 分 56.2 秒） |
| GSIM 内部 `Timer.main().total` | 758.455 s（12 分 38.5 秒） |
| 进程最大 RSS | 106,753,048 KiB，约 101.8 GiB |
| 生成 C++ 文件 | 244 个 |
| C++ 文件总大小 | 2,456,873,139 bytes（约 2.46 GB） |
| 模型目录总大小 | 2,565,377,923 bytes（约 2.57 GB） |
| 退出码 | 0 |

GSIM 日志显示解析阶段为 5.213 秒，初始化为 71.278 秒，最终 C++ emitter
为 18.361 秒；完整阶段合计以内部 `Timer.main()` 为准。生成目录还包含
`SimTop.h`、supernode 统计和成员清单。

## 边界和与 GrhSIM 的关系

本次是 GSIM 直接读取 FIRRTL 的生成基线，没有经过 GrhSIM 的 FIRRTL/mixed
ingest、GRH flatten/simplify、checkpoint、`grh-to-grhsim` 或 harness 合并。
因此它相对 F13 的 GrhSIM 整机 40 分钟试跑只能作为路径级参考，不能解释为
严格的端到端 A/B 加速比。F13 的 GrhSIM 试跑在 2400 秒时仍未生成 C++；
本次 GSIM 在 778.590 秒完成 FIRRTL→C++。

## 证据

- `ptmp/gsim-firrtl/full40m/run.json`：输入身份、实际命令、外层计时和退出码。
- `ptmp/gsim-firrtl/full40m/driver.log`：完整 GSIM 输出及 `/usr/bin/time`。
- `ptmp/gsim-firrtl/full40m/build/gsim.log`：GSIM 阶段计时。
- `ptmp/gsim-firrtl/full40m/build/default-xiangshan/model/`：生成的 C++ 模型。
