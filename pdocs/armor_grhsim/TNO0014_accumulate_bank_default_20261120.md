# TNO0014：XiangShan 单模型 GrhSIM 默认开启成排累加

普通单模型构建现在默认给符合条件的性能计数器生成累加排。提交分组仍为可选项。采用依据是 TNO0013 的同轮对照，单开成排累加将 CoreMark 10 万周期窗口的平均 walltime 从 112.01 秒降至 101.83 秒，配对变化 −9.09%，95% 区间 [−9.52%, −8.69%]。[四组计时](./TNO0013_commit_group_and_accumulate_bank_20261120.md)

## 构建与关闭

- `make xs_wolf_grhsim_emit` 和直接执行 `scripts/wolvrix_xs_grhsim.py` 时，`comb-lane-pack` 先保留候选计数器的写数据。常规简化、`reg-to-mem` 和检查点写出完成后，`accumulate-sink -mode=bank` 在 `activity-schedule` 前改写计数器。[生成入口](../../scripts/wolvrix_xs_grhsim.py)
- `make xs_wolf_grhsim_emit WOLVRIX_XS_GRHSIM_ACCUMULATE_BANK=0` 恢复普通打包和寄存器提交。直接执行生成脚本可设同名环境变量，`grhsim_single_baseline.py` 使用 `--no-accumulate-bank`。声明信号波形模式沿用普通寄存器路径，以保留可观察的中间信号。[选项说明](../../wolvrix/docs/emit/grhsim-accumulate-bank.md)
- Make 自动复用检查点时，开启和关闭分别使用带 `_accumulate_bank` 后缀和原名的文件。显式恢复旧检查点会按图中已有的形态识别计数器。需要复现全部候选时，从 RTL 生成或使用在打包时保留候选的检查点。[Make 入口](../../Makefile) · [八种检查点选择验证](../../build/armor-acc-default-v1/make-checkpoints.json)

## 验证

- 从完整 XiangShan RTL 走正式入口，打包后有 2,793 组、24,066 个根，随后 32,454 个计数器进入累加排，共用两个清零条件。用本轮新写出的检查点和上一轮保留候选的检查点分别从正式入口生成、编译，均得到 32,454 槽，提交分组为关。[从 RTL 生成](../../build/armor-acc-default-v1/xs-emit.log) · [本轮检查点生成](../../build/armor-acc-default-v1/xs-final.log) · [前轮检查点生成](../../build/armor-acc-default-v1/xs-resume.log)
- 两个重新编译的模型各运行 CoreMark 10 万周期、seed 0，DiffTest 开启。每个模型的 99,999 条 DiffTest 记录与冻结的全关基线一致，结束 PC 为 `0x80000c1a`，提交 250,838 条指令。期末 dump 比较包含重复次数的行内容，35,063 行全部匹配，其中 10,045 行非零。本轮新增运行用于验证功能，性能比较采用 TNO0013 的八轮计时。[新检查点模型核对](../../build/armor-acc-default-v1/xs-final/verify/result.json) · [前轮检查点模型核对](../../build/armor-acc-default-v1/xs-resume/verify/result.json)
- 四个计数器的 RTL 用例走正常 Python 入口，默认和显式开启的 C++ 与头文件逐字节相同，均有四个累加槽。关闭后生成一组普通打包，跳过整个打包阶段也能生成累加排。两种检查点恢复和波形模式均有回归覆盖。[入口回归](../../scripts/test_wolvrix_xs_grhsim_options.py) · [运行日志](../../build/armor-acc-default-v1/options-test.log)
- 小用例显式关闭后，17 个 C++、头文件和 Makefile 与变更前的驱动逐字节一致。开启声明信号波形时也做了逐文件对照，默认和显式关闭完全一致。[源码校验](../../build/armor-acc-default-v1/fixture/source-comparisons.json)
- 将不适合累加排的存储和观察者保留为普通寄存器，包括有符号寄存器、已分配 `reg-to-mem` 存储的寄存器以及由 `final` 或无事件系统任务读取的计数器。对同时含清零和保持分支的写端口，清零条件保留对实际分支的判断。累加排与普通模型在四组调度及编译设置下各跑 3,000 个随机激励周期，逐项比较打印结果。[变换测试](../../wolvrix/tests/transform/test_accumulate_sink_pass.cpp) · [模型执行测试](../../wolvrix/tests/emit/test_emit_grhsim_accumulate_bank.cpp) · [CTest 日志](../../build/armor-acc-default-v1/ctest.log)
- `transform-comb-lane-pack` 的历史用例仍在普通寄存器写数据的 `kAnd` 数量断言处失败，诊断与改动前相同。[本轮日志](../../build/armor-acc-default-v1/packing-ctest.log) · [既有失败日志](../../build/armor-acc-v1/transform-comb-lane-pack.log)
