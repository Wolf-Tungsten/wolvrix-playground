# TNO0364：独立目录的纯源码构建

日期：2026-10-28。承接 [TNO0363](./TNO0363_grhsim_portable_startup_20261028.md)。

## 方法

将当前 `tools/`、`scripts/`、`config/`、Wolvrix 源码及 Makefile 导出到新的独立目录，排除 `.git`、全部 `build*`、输出目录和已编译 replay 二进制。该目录不含旧 JSON、HGR、assignment、动态库、archive 或 emu。

清除 `CMAKE_PREFIX_PATH`、Boost 定位变量和 `LD_LIBRARY_PATH` 等环境，再用 GCC 13/CMake 从源码配置并构建 `grhsim32_tools`。普通已安装系统依赖仍可被 CMake 发现；这次测试不是容器或另一台物理机器上的测试，也不声称验证了所有发行版。

## 结果

独立目录成功构建全部前端、六维图、assignment replay、context、assignment evaluator、km1 score 和代码页启动库。构建产物位于 `wolvrix/build/artifacts/grhsim32-source-only-current/native-build/`，该目录由开发回归创建，不进入默认生成路线。

香山全量的一键试跑同时继续进行：8 份新求解均满足容量约束，最低完整图 km1 为 39,450,970，工具选择 seed 6。分区 replay 完成，正在发射 32 分区 C++ 包；尚无最终功能或 walltime 结论。

默认命令与依赖说明见 [使用文档](../../docs/grhsim32.md)。这些源码修改仍在当前工作树中，本记录不表示已经提交或发布远端版本。
