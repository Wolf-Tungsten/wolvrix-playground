# RA 1 第 1 步任务书（week-1-ra-1-plan-step-1-c9a4c84b）

VRT_PRIMARY_GOAL: 优化 grhsim-ir 单线程 XiangShan CoreMark 50k 周期仿真性能，并满足编译 <30min；按 PI 规划 F01-F08 完整验收，方向 1 聚焦通用宽值与边界缓冲 emitter/runtime。
VRT_SUCCESS_CRITERIA: 首次工程调用必须真实尝试完整 F05 目标链至成功或最早实际阻塞；若完成，须产生可复核的模型/emu/输入指纹、正确性终点与每 1000 周期采样、单线程进程证据、冷编译计时和原始日志。该步只证明目标流程可达或定位最早阻塞，不替代 F01-F08 最终 A/B 三次排名验收。
VRT_TARGET_PATH: 从 B1-c9a4c84b-v1 的 r_1 独立 worktree 起点推进完整 `make xs_wolf_grhsim_ir` → `make xs_wolf_grhsim_ir_build_emu` → `make run_xs_wolf_grhsim_ir_emu`；本步解除目标流程当前未知的 Mill/Python/构建/运行阻塞，并为后续宽值与边界缓冲候选建立可复现 A 基线。
VRT_TASK_KIND: target
VRT_NEXT_TARGET: 若本步完整链成功，下一步在本方向提交上继续做有依据的宽值/边界缓冲 emitter/runtime 优化并回到同一 F05 命令；若在最早环节失败，保留现场和原始日志，下一步仅针对该具体错误实施 blocker 修复后重新执行同一完整链。

## 假设与边界

方向 1 假设：GrhSIM CPU emitter/runtime 的宽值搬运、partition boundary 和 helper 临时对象复制是 CoreMark 50k 的显著成本；沿 legacy 指针式 ABI、调用方提供输出缓冲和局部 frame/boundary 缓冲改造，可减少复制而保持 compute/commit、history、mask 及多写口顺序。证伪须同时满足完整 50k A/B 对拍、终态和退出状态一致，冷编译 <1800s，且按 F07 配对中位数达到候选 < A×0.99；局部 helper 快、未完成目标、功能不等价或不可重复均不构成证伪/通过。

禁止修改冻结 GRH IR/pass、XiangShan 或测试源码、多线程仿真、按模块名特化；不得 merge/cherry-pick/copy 其他方向实现或生成物。共同基线见 `week_1/baseline.md`（入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a`，wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818`，XiangShan `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`，gsim `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a`）；方向 race 记录见 `week_1/race.md`，隔离证据 TSV SHA256 为 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`。

## 工程操作（本步只由 ENGINEER 执行）

1. 在启动目录 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1` 复核入口、`wolvrix`、父 gitlink、嵌套仓库 HEAD/tree/status；确认 `testcase/xiangshan/ready-to-run` 与 `reference/gsim/ready-to-run` 独立仓库可读且指纹匹配。发现污染/缺失只保留证据上报，不 reset、删除或重建旧现场。构建和日志只写本方向 `ptmp` 或既定方向构建目录。
2. 首次就尝试完整目标流程，不先做静态扫描或局部回归。所有构建/测试/安装只能经 Makefile；实际命令链固定为：
   ```sh
   make xs_wolf_grhsim_ir XS_GRHSIM_IR_BUILD=/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/build/<run_id> VM_BUILD_JOBS=8
   make xs_wolf_grhsim_ir_build_emu XS_GRHSIM_IR_BUILD=/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/build/<run_id> VM_BUILD_JOBS=8
   make run_xs_wolf_grhsim_ir_emu XS_GRHSIM_IR_BUILD=/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/build/<run_id> XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_PROGRESS_EVERY_CYCLES=1000 XS_NUM_CORES=1 XS_EMU_THREADS=1 EMU_THREADS=0 XS_LOG_DIR=/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1/ptmp/logs/<run_id> RUN_ID=<run_id>
   ```
   执行前确认 CPU 2、powersave、串行其他负载；冷缓存编译并记录 `VM_BUILD_JOBS=8`。50k 明确为 50,000 周期窗口。Mill/Python 环境未预验证，必须通过真实目标尝试暴露最早阻塞。
3. 记录每条命令完整 stdout/stderr、退出码、编译起止墙钟和 emu 进程启动至退出计时；原始日志用本方向绝对路径且非空。记录模型、RTL/filelist、emu、输入及生成物 SHA256/来源，进程树/flags 证明无仿真线程并行。成功时记录 1000 周期有序采样、NEMU difftest、终点 PC/trap/instruction/state 及无 mismatch/ABORT/BAD TRAP；失败时记录最早真实错误、残留进程和安全续接动作。
4. 本步不实施优化代码；如目标链成功，仅提交本步结果报告供 RA 审查，后续工程调用再针对宽值/边界路径实施候选。不得改 `baseline.md`、`requirements.md`、`pi_plan.md`、`.runner` 或测试/依赖源码。

## F01-F08 证据交付表

| 验收项 | 本步要求/状态 |
|---|---|
| F01 需求与边界 | 记录允许目录 diff、无禁区修改；本步预期无技术源码改动 |
| F02 共同基线/独立性 | 记录各仓库 HEAD/tree/status、父 gitlink、方向 worktree 与产物来源 |
| F03 输入与流程 | 记录 XiangShan/ready-to-run SHA、真实 Makefile 三段命令、模型/RTL/filelist/emu 指纹 |
| F04 行为正确性 | 若运行到终点，给出每 1000 周期采样、difftest、终态和退出状态；未到达则明确未测 |
| F05 完整单线程目标 | 记录上述绝对路径命令、全部参数、退出码和非空原始日志；成功才算本步目标链完成 |
| F06 编译时限 | 冷缓存、`VM_BUILD_JOBS=8`，从首个 make 到 emu build 完成计时，目标 <1800s |
| F07 可比性能/稳定性 | 本步建立 A 候选单次证据；三次交错 A/B、CPU2、powersave 和 1%/5% 资格仍待后续 |
| F08 交付与复核 | 结果报告、日志、指纹和提交/现场关系齐全，供 RA 独立审查；周末 6/6 调用和周报尚缺 |

## 与完整目标的缺口

本步没有性能优化，也没有三次 A/B、中位数、重复稳定性、候选提交、完整回归闭包或 PI 最终排名。未运行或运行失败不等于假设证伪；下一调用必须围绕记录的具体阻塞或已观察热点推进，并回到完整 50k 命令。构建输出、日志、venv 和可变缓存必须按 `<run_id>` 隔离，不得引用主检出或其他方向可变产物。

## 失败交接

中断/失败时保留 worktree、未提交变更、原始日志和残留进程证据，在 `step_1_result.md` 写明错误命令与整数退出码（或 `interrupted`）、绝对日志路径、最早阻塞位置及安全续接命令；不编造成功、不修改执行器回执、不清理现场。若发现共同基线、依赖版本或测试口径变化，立即报告 PM，暂停候选声明，等待 PI 追加基线后由所有受影响方向重测。
