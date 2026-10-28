# TNO0363：默认运行入口的代码页初始化

日期：2026-10-28。承接 [TNO0362](./TNO0362_grhsim_clean_default_implementation_20261028.md)。

## 修正

默认运行由 `taskset`、可用时的 `numactl`、可用时的 `setarch` 和最终 emu 构成。若给整条命令设置 `LD_PRELOAD`，初始化库会先在这些辅助程序中执行；旧的环境变量一次性标记又会穿过 `exec`，使最终 emu 跳过代码页初始化。

[grhsim32.py](../../scripts/grhsim32.py) 现在将 preload 设置放在所有辅助程序之后，仅作用于 emu。生成的 `emu` launcher 使用相同形式。环境变量标记还引入当前进程的 `AT_RANDOM`，区分同一 PID 中的不同 exec；同一个可执行映像在新的 `dlopen` namespace 中再次加载时仍只初始化一次。没有完整 2 MiB 可执行区的辅助程序在 auto 模式下直接返回，不建立已初始化标记。

这是启动代码的开发期修正，发现时香山全量试跑尚处于静态成本生成，没有性能样本需要撤回。

## 回归

新增两项测试：命令编排测试确认 preload 位于亲和性/ASLR 辅助程序之后；原生运行测试临时编译含较大 text 段的 ELF，经 taskset exec 后在新的 namespace 加载初始化库，验证主程序正常完成、初始化只发生一次且实际处理了可执行页。

单独原生测试观察到 `bytes=2097152, anon_huge=2097152`，主程序输出 `startup ok`。默认流程测试现为 11 项，连同此前相关测试共 42 项通过。该小型回归不替代香山的最终功能和 walltime 结果。
