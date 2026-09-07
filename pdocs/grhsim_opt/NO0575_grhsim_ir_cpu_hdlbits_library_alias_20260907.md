# NO0575 GrhSIM IR CPU HDLBits Library Alias

- 日期：2026-09-07
- 前置：[NO0573](./NO0573_grhsim_ir_cpu_port_names_20260907.md)

第三轮 IR HDLBits 全量已通过 001–118，119 的参数化顶层生成
`libgrhsim_top_module__p_A__0__B__1.a`。稳定头文件别名已存在，但原 GrhTB Makefile
通过生成 Makefile 的 `LIB :=` 变量寻找真实库，新 CPU Makefile 尚未提供该变量，
导致链接时报找不到 `-lgrhsim_top_module`。日志 `ptmp/grhsim_ir_hdlbits_all3.log`。

CPU 生成 Makefile 现提供与 legacy 一致的 `LIB := lib<actual-model>.a`，all 和归档
规则统一引用此变量，复用 GrhTB 已有的库复制别名路径。没有更改模型/符号/测试判据，
没有另写手工链接命令。`make py_install` 安装成功，日志
`ptmp/grhsim_cpu_library_alias_install.log`。

第四轮全量 IR HDLBits 正在运行，日志 `ptmp/grhsim_ir_hdlbits_all4.log`；另以既有
legacy Makefile 路线复验参数化 119，确保新增 backend 选项不破坏默认脚本行为。
在各自退出码和完成范围明确前，不宣称 162/162 或全量 legacy 通过。

## 验证结果

第四轮 IR 全量 162/162 GrhTB 通过，最终退出 0；119 参数化异步复位也通过。
legacy 119 的库别名/链接成功但运行断言失败，另验 legacy 001 成功，不能将前者
计为 legacy 功能通过。完整结果及事件域统计见
[NO0576](./NO0576_grhsim_ir_cpu_hdlbits_full_gate_20260907.md)。
