# TNO0361：可从新 clone 干净重跑的默认流程

日期：2026-10-28。用户要求将当前流程固化为默认一键入口，随后明确：从 Verilog 干净生成，中间不加入历史产物一致性校验；别人 clone 后应能在自己的机器重跑。

## 范围

默认入口为 `make xs_grhsim`，现有 `make build_xs_repcut_grhsim` 同样转入该流程。生成和编译不限于原性能核，运行时按本机拓扑选择 32 核，不依赖 node030 或固定 CPU 编号。

完整 preset 进入仓库配置；模型采用原始 O3/native，不附加 no-SLP。mem-to-reg 保持当前控制口径，但重新作用于本轮 Verilog；六维权重图、8 份求解、assignment replay、C++ 和 emu 全部重新生成。迁移端点由工具选择，不接受旧标签作为默认输入。

所需原始状态来源、触发分析及六维导出器迁入 `tools/grhsim32/`。多约束求解器从公开固定版本构建，并携带已有 fallback 修正的源码 patch。旧 JSON/HGR、旧 emitter 动态库、旧 solver binary、旧 benchmark analyzer 均不是生成输入。

不运行中间执行计划 gate、历史源码/对象逐字节比较或旧模型哈希核验。最终 emu 生成后进行 NEMU 功能检查、walltime 测量和自动迁移候选的 fresh AB/BA。普通 CMake 依赖缓存与设计中间产物分开。

## 验证计划

编排测试覆盖本机核选择、八份独立求解及 km1 择优、原始模型编译选项、archive 生成顺序和默认 Make 入口。另用新建小型 Verilog fixture 跑原生前端与六维图生成，并实际运行多约束求解。随后从当前 Verilog 开始跑完整新流程；运行结果另立记录。

入口实现：[grhsim32.py](../../scripts/grhsim32.py)，用户文档：[grhsim32.md](../../docs/grhsim32.md)，默认配置：[grhsim32.json](../../config/grhsim32.json)。
