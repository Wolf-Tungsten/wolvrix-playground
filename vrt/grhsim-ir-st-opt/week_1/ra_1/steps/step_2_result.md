# RA1 Step 2 ENGINEER result

执行编号：`week-1-ra-1-step-2-eng-env-and-target-c9a4c84b`

VRT_PRIMARY_PROGRESS: narrowed
VRT_EVIDENCE: 按 B1-c9a4c84b-v2 在本方向入口实现了公共环境入口并真实核验。公共补丁提交为 `aaca3fafe3134f7147f1f3e866cfcb1401c5be35`，其相对共同入口基线的 patch SHA256 为 `3460712b4b4d8efd80a47ed34318670e1c8660767d3bb238fb316fe34a5d20e6`。目标输出覆盖修正后的补丁提交 `3eea16676f73cba5f87364e8959049437de40308`，相对基线完整环境 patch SHA256 为 `955f8b192b97165e32a30e8a55a8d64cf3bdd36d62e3ebf1c7ca6a881018ffa9`。两次提交只含入口 Makefile/环境辅助编排，不含 RA1 emitter/runtime 优化、XiangShan、测试或依赖源码。

## 环境实施与核验

`make -j1 vrt_common_env_prepare SKIP_WOLF_ENV_CHECK=1 VRT_ENV_ROOT=<run>` 与 `make -j1 vrt_common_env_verify ...` 均退出 0，准备 7.47s、核验 2.03s。私有根为 `r_1/ptmp/B1-c9a4c84b-v2/3eea16676f73cba5f87364e8959049437de40308/w1-r1-s2-a-0567b6c-cba9c32-v2-01`。基础 Python3.12 建立 venv；pip/scikit-build-core/packaging/pathspec 固定为 24.0/1.0.3/26.3/1.1.1，wheel 下载、解析报告、锁和 SHA256 均在 `logs/`，`pip check` 退出 0。JDK release/java/modules 和 Mill bootstrap/distribution 均匹配 PI 指纹；Mill `-i --version` 退出 0，输出 0.12.15/JDK 17.0.20，实际子 JVM 为 `/usr/lib/jvm/java-17-openjdk-amd64/bin/java`。

`env.sh` 是 verify 最后发布的纯 unset/export 文件；不重设 HOME。`JAVA_OPTS`/`JAVA_TOOL_OPTIONS` 固定 user.home、java.io.tmpdir、ivy.home，XDG/Coursier/Ivy/PIP/TMP/CCache、venv/skbuild/build/RTL/generated-src/IR/model/emu/log 均指向 run。strace 观察到 Mill probe 写入 `mill-probe`，目标首次尝试发现 XiangShan nested make 会硬编码 `.docker-mill-out`，其实际路径证据触发入口修正；修正后的目标 run 将 `MILL_OUTPUT_DIR=<run>/mill-target` 传入 nested make。旧 `out/`、`testcase/xiangshan/out`、旧 `.docker-mill-out`、主 build/cache 在两次尝试前后均保留，隔离校验为 unchanged=True。进程 observer 记录 Java exe/cwd/cmdline/env、tasks/maps/fds；首次 run 中止时仅向本 run XiangShan cwd 的 Java 发送 INT，之后无残留目标进程。

## 完整目标链尝试

### Run 01（aaca3fa，发现 nested output 覆盖）

命令链由 `ptmp/step2-opening/target-driver.sh` 调用，每阶段经 `make`、tee 并记录 PIPESTATUS。`xs_wolf_grhsim_ir` 退出 2（约 75s）；其真实 Java 子 JVM 为 JDK17，但实际 `MILL_OUTPUT_DIR=.docker-mill-out`，违反 run 隔离，故由工程师安全中止。目标二、三未执行。原始证据在 `.../aaca3.../w1...01/logs/`，包括 `isolation-blocker.log`、`xs_wolf_grhsim_ir.raw.log`、processes JSONL、strace/目录指纹。

### Run 02（3eea166，最早新阻塞）

修正后重新 prepare/verify，目标一命令为 `make -j1 xs_wolf_grhsim_ir ... VRT_OBSERVED=1 MILL_OUTPUT_DIR=<run>/mill-target`，入口 observer 实际执行 `make -j1 xs_wolf_grhsim_ir`；目标一 21:44:34–21:45:41 +08，退出码 2。Mill/JDK major69 已解除，`build.mill` 编译阶段进入 749 tasks；最早新错误为：

```
de.tobiasroeser.mill.vcs.version.VcsVersion.vcsState ...
fatal: bad object 4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6
```

错误发生于 XiangShan `testcase/xiangshan` 的 VcsVersion git 状态计算（Makefile:275 sim-verilog），不是优化代码或 Python/native 构建错误。目标二 `xs_wolf_grhsim_ir_build_emu` 和目标三 `taskset -c 2 make ... run_xs_wolf_grhsim_ir_emu` 按“前一失败不得盲跑”门禁未执行。故 50,000 周期、每1000采样、EMU_THREADS=0、NEMU 对拍、终态和 host emu time 均未测；没有性能候选或排名结论。完整非空 stdout、commands.jsonl、资源/进程观察、生成物清单和 `all.sha256` 位于该 run `logs/`。

## 状态与续接

入口最终 HEAD/tree：`3eea16676f73cba5f87364e8959049437de40308` / `7606970036deb01130b50e92d24b858454615598`，分支 `vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`；`wolvrix` 保持 `cba9c32240f3cd06c5b675968b56046e5b76f818` / `6bcc50560c2fb21f5e000cc521bec5a5e58d8483`，父 gitlink 未变。入口已有用户现场 `?? out/` 保留；新增源码均已提交，档案和 `.runner` 未提交。公共补丁尚未由 RA/PI 冻结，不得由其他方向自行复制或 cherry-pick。

安全续接：下一 ENGINEER 只针对 `bad object 4a6e3da8...` 取证，先经 Makefile 环境入口核查 XiangShan git object/database 是否完整及 baseline commit 可读；不得修订 XiangShan/测试源码、切换共同基线、复制其他方向对象或把未测范围判为证伪。确认依赖检出/对象缺失后交 PM/PI 补齐共同依赖证据，再以新 candidate/run 重新执行同一三目标链。

本方向本步未取得完整目标成绩，不能进入 F07 排名；公共入口提交交 RA 审查后再由 PM/PI 冻结适用关系。
