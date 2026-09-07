# NO0573 GrhSIM IR CPU Port Names

- 日期：2026-09-07
- 来源：[NO0572](./NO0572_grhsim_ir_cpu_hdlbits_entry_20260907.md) 的 HDLBits 032。

## Cause and Fix

032 有合法 SV 输入 `cpu_overheated`，CPU emitter 原先拒绝一切 cpu_ 前缀公开端口，
产生不必要的支持缺口。改为检查实际生成的字段/方法/类型名及 cpu_at：init/eval、
存储/调度成员、按模型实际生成的 cpu_task_N/cpu_init_N/cpu_helper_N_M 等。
其他 cpu_ 名称允许使用；输出发布和输入读取显式使用 this->，避免 eval 的 cpu_round /
cpu_again 局部变量遮蔽同名公开端口。DPI 的 compute/event 策略保持不变。

## Tests

扩展 startup fixture，输入 cpu_overheated 与输出 cpu_again/cpu_round 在原有 768
样本中核对；六个真实生成成员冲突继续在输出文件写出前拒绝。第一轮测试自身复用了
已有 `init` 测试目录，造成“未创建目录”断言误报，修为独立 reserved_ 前缀目录。
此失败日志保留在 `ptmp/grhsim_cpu_port_names_test.log`，没有因此改动后端语义。

第二轮 `make test_grhsim_cpu_emit` 全套退出 0，23.68 秒；日志
`ptmp/grhsim_cpu_port_names_test2.log`，详细输出 `ptmp/grhsim_cpu_port_names_details.log`。
原有多时钟、scalar/wide/wide-state Verilator 与 ASan/UBSan 初始化/调用回归均通过。
项目绑定安装成功，第三次 HDLBits 全量测试已越过 032 并继续运行，日志
`ptmp/grhsim_ir_hdlbits_all3.log`，不提前记为 162/162。
