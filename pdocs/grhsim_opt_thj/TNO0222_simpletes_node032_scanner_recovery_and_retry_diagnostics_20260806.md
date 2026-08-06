# TNO0222：SimpleTES node032 dependency scanner 在线恢复与 retry 诊断补强

日期：2026-08-06

## 1. 结论

[TNO0221](./TNO0221_simpletes_node032_postreboot_exact_restart_20260806.md) 恢复的 auto research 并非卡在
whole-CCD admission，而是在 node032 重启后第一次 fresh control build 中稳定失败。直接证据是 evaluator slot 的
`results/control_build.log`：CMake 把 C++20 dependency scanner 缓存为
`CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS-NOTFOUND`，Ninja 每次在扫描 Slang C++ 依赖时以 shell exit `127`
失败，最终 `make py_install` exit `1`。旧 SimpleTES 只在 scheduler 中打印泛化的 retry 文案，因此表面上看不出
build root cause。

本阶段在不停止 launcher/main、不取消当前候选、不清空 evaluator slot 的前提下完成在线恢复：

1. 等待 node032 上已经在进行的 `clang-tools-19` 包安装结束，确认 matching scanner 可执行；
2. 在 evaluator 自身的 slot lock 下，仅重新配置派生 CMake cache，把 scanner 固定为
   `/usr/bin/clang-scan-deps-19`；
3. 让 scheduler 对同一个候选的既有 retry 自然继续，未发送 signal、未重启或另起 SimpleTES instance；
4. 后续 evaluator 已越过原失败点和 Python extension build，进入 fresh SimTop C++ emit；
5. SimpleTES 新增启动前 matching-scanner gate，并把已脱敏、限长的 evaluator root cause 带到 retry 日志。

SimpleTES 修复提交为 `a32116db56d68b03c5944762aca3cca466929e99`。定向回归 `86/86`、全量回归
`254/254` 通过，node032 真实工具链 preflight 也通过。当前 Wolvrix 源码和默认选项没有变化；本阶段尚未产生新的
accepted SimTop 50k walltime、valid evaluation 或性能结论。

## 2. 已证明的 root cause

post-reboot main 从 `17:12:49 +0800` 开始运行；四个 generation 完成后，首个 evaluator 开始构建 control。
从 `17:36:49` 到 `18:10:05`，同一 candidate 共得到 `36` 次：

```text
Retryable evaluation infrastructure outcome; retrying the same candidate in 30s
```

这不是每 30 秒都通过了一次 quiet-CCD survey。失败发生在 fresh control build，尚未创建
`control_artifacts.json`、runtime directory 或 immutable evaluation attempt。slot 中唯一正式结果日志为
`control_build.log`，关键尾部为：

```text
FAILED: [code=127] .../SemanticFacts.cpp.o.ddi
"CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS-NOTFOUND" -format=p1689 -- /usr/bin/clang++ ...
/bin/sh: 1: CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS-NOTFOUND: not found
ninja: build stopped: subcommand failed.
ERROR: Failed building editable for wolvrix
make: *** [Makefile:279: py_install] Error 1
```

node032 当时已有 `/usr/bin/clang++` `19.1.1`，但没有 matching `clang-scan-deps`。CMake fresh configure 仍能生成
Ninja graph，却把 `CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS` 写为 `NOTFOUND`；实际编译到 P1689 dependency-scan
edge 才确定性失败。evaluator 将 control build 的 `InfrastructureError` 标成 retryable，engine 睡眠 `30 s` 后重新
评测同一 candidate；clone/cache 很快复用，所以形成约一分钟一次的无限循环。

资源检查同时排除了磁盘耗尽、内存不足和整个 evaluator 超时。最关键的判别是失败发生在 runtime/CCD admission
之前，因此即使 node032 上存在完全空闲 CCD，也不可能解决这次 retry。

## 3. 在线修复过程

检查时 node032 上已有一个 root-owned apt transaction 正在安装 `clang-tools-19`；本阶段没有并发启动第二个包管理
事务，而是等待原事务正常完成。安装后绝对状态为：

| 项目 | 结果 |
| --- | --- |
| package | `clang-tools-19 1:19.1.1-1ubuntu1~24.04.2` |
| compiler | `/usr/bin/clang++`, major `19` |
| scanner link | `/usr/bin/clang-scan-deps-19` |
| scanner target | `/usr/lib/llvm-19/bin/clang-scan-deps` |
| scanner version | `Ubuntu LLVM version 19.1.1` |

已生成的 CMake cache 不会仅因可执行文件后来出现而自动把 `NOTFOUND` 改写成有效路径。为避免与正在 retry 的
evaluator 并发修改 slot，本阶段用 evaluator 的确切
`/tmp/simpletes-grhsim-simtop-50k/8537675d5cb20e92/slot-0/lock` 获取排他锁，然后只对派生 build tree 执行
CMake reconfigure，并显式设置：

```text
CMAKE_CXX_COMPILER_CLANG_SCAN_DEPS:FILEPATH=/usr/bin/clang-scan-deps-19
```

没有删除 slot、candidate、checkpoint 或 NFS 工作树，也没有改动 control/candidate patch。下一次自然 retry 在
`18:10:05` 后启动；截至本记录取证，最后一条 retry 仍固定在 `18:10:05`，同一 evaluator 已依次越过原来的
Slang dependency scan、editable Python build，并进入 `wolvrix_xs_grhsim.py ... SimTop` emit。launcher/main PID
仍分别为 `18435/21161`，scheduler 保留 `1 active / 3 queued` evaluations。

另用独立临时 build tree 复刻 Makefile 的 `CMAKE_CXX_COMPILER=/usr/bin/clang++` 做 fresh configure；新
`CMakeCache.txt` 自动得到 scanner path，生成的 `CMakeFiles/rules.ninja` 也直接调用
`/usr/bin/clang-scan-deps-19`，没有 `NOTFOUND`。probe tree 和临时日志随后删除。由此同时验证了当前旧 cache 的
在线恢复，以及 future fresh cache 在 package 已安装时的自动发现路径。

## 4. SimpleTES 防复发与可观测性修复

SimpleTES `a32116d` 包含三组互相配套的修改。

### 4.1 launch 前工具链 gate

GrhSIM launcher 在正常启动路径上、Codex capability preflight 和 main spawn 之前 source target `env.sh`，解析
实际 `clang++` major，并要求存在同 major、可执行且能报告版本的 `clang-scan-deps`。若 clang 19 缺 scanner，
launcher 会直接给出：

```text
GrhSIM evaluator toolchain preflight failed: no clang-scan-deps matching clang 19;
install clang-tools-19
```

因此 future fresh launch 会在消耗 provider 请求、生成候选或进入后台 retry loop 之前 fail-close。`--dry-run` 和纯
参数验证仍保持无环境副作用；preflight 只输出 compiler/scanner 路径和 major，不读取或输出 API key。

### 4.2 retry root-cause 日志

GrhSIM evaluator 对 retryable runtime result 与捕获到的 `InfrastructureError` 新增显式
`retry_diagnostic`。该字段先经过现有 credential scrubber；engine 只信任这个显式字段，不把任意 metrics
对象直接打印，并进一步：

- 合并换行与多余空白；
- 最长保留 `512` characters；
- 对 Rich markup 字符转义。

以后日志在原 retry 文案后会附带具体异常，例如 command exit、失败阶段和已截断 output tail。retry budget、同
candidate retry 语义和 `30..300 s` delay 边界均未改变。

### 4.3 对当前实例的生效边界

当前 main 在代码提交之前已经加载旧 `simpletes.engine.core`，所以不能通过原地改文件热替换 engine 的日志格式；
为遵守“不停止当前 auto research”的要求，本阶段没有为获得新日志格式而重启它。在线安装 scanner 与 slot-cache
reconfigure 已直接修复当前 evaluator；完整的 launcher fail-close 和 engine diagnostic 会从下一次正式启动起生效。

## 5. 回归与真实环境验证

| 验证 | 结果 |
| --- | --- |
| changed Python modules `py_compile` | PASS |
| focused engine/GrhSIM bench tests | `86 passed` |
| SimpleTES full tests | `254 passed`, 仅 `24` 条既有 `datetime.utcnow()` deprecation warnings |
| `git diff --check` | PASS |
| node032 real preflight | compiler `/usr/bin/clang++`, scanner `/usr/bin/clang-scan-deps-19`, major `19`, PASS |
| node029 negative preflight | matching scanner 不存在，准确 fail-close 并提示 `install clang-tools-19` |
| node032 fresh CMake clang configure | cache/rules 均自动使用 `/usr/bin/clang-scan-deps-19`，PASS |
| live evaluator | 越过原 dependency scan/build 失败点，进入 fresh SimTop emit |
| current launcher/main | 原 PID `18435/21161` 持续存活，未重启 |
| queue preservation | `1 active / 3 queued`，没有人工取消 |

第一次“全量 pytest”从 workspace 根目录调用时因测试按仓库根解析 `datasets` 而在 collection 阶段得到
`ModuleNotFoundError`，没有执行用例；切到 `SimpleTES/` 仓库根后同一全量套件 `254/254` 通过。这是测试调用
目录勘误，不是产品失败。

## 6. 对既有 retry 归因的边界与勘误

- node029：TNO0220 的旧 `/tmp/.../control_build.log` 仍在，尾部明确完成 archive 并链接 `emu`。因此 node029
  那一段是在 build 后等待 runtime admission，whole-CCD 归因仍成立；node029 目前没有 scanner 并不推翻已经由
  cache/build 产物越过的旧运行事实。
- node032 post-reboot：本记录有完整 `NOTFOUND` build log，`36` 次 retry 的 scanner root cause 已证明，不能再
  归为 CCD。
- node032 pre-reboot：TNO0220 到节点重启之间共有 `777` 次泛化 retry（`02:40:53..16:16:28`）。重启清空了
  node032 本地 `/tmp`，无法恢复该段 control log；相同 fresh slot、相近 cadence 和重启后复现均与 scanner 缺失
  一致，但这里只能记录为强推断，不能提升为已证明事实。

本阶段没有新的 walltime 样本，因此不更新 current best、收益百分比或 Wolvrix 默认决策。后续 evaluator 仍须正常
完成 control/candidate build、功能门禁、whole-CCD fixed-ASLR ABBA+BAAB SimTop 50k，才计入第 `35/64` 个
valid evaluation。
