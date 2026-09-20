# TNO0319: XiangShan counter-print isolated-build runbook correction

日期：2026-09-15

状态：`COMPILE PASS; GENERATION RUNNING; NO STRUCTURAL RESULT YET`。

## 1. 与计划的关系

执行 [TNO0318](./TNO0318_xiangshan_counter_print_regeneration_plan_20260915.md)
时修正构建隔离方式，设计修改仍只有 [TNO0317](./TNO0317_xiangshan_perf_print_current_counter_experiment_20260915.md)
的单行 counter 打印。以下失败/中止均保留独立目录，不覆盖结果。

## 2. 三次未进入 RTL 生成的尝试

产物根目录：`build/asc_counter_print_20260915/`。

| 目录 | 结果 | 原因 |
| --- | --- | --- |
| `candidate` | Mill exit 1 | 缓存放在 XiangShan 源树外的父仓库内；版本插件 Git 调用解析到父仓库，无法解析 XiangShan commit。不是 Scala 设计编译失败。 |
| `candidate_v2` | 主动中止，Mill exit 143 | 缓存移入 XiangShan 的独立 build 子目录后开始编译；审计发现 runMain 的 cwd 仍会影响原始 build，故在 generator 启动前停止。RTL 目录为空。 |
| `candidate_v3` | Scala compile exit 0，harness error | 改用 Mill show runClasspath + 独立 cwd JVM；全部 Scala 编译完成。harness 错误地要求 classpath 每项都存在，但 Mill 正常包含不存在的约定资源目录。尚未启动 generator。 |

`candidate_v4` 接受不存在的可选资源目录，仍要求所有 jar 和 classes 存在，
记录 absent_resource_paths；复用 v2 独立缓存，由 Mill 核验增量依赖，启动独立 JVM。

## 3. 隔离修正

- Mill 0.12.15 的新缓存放在 `testcase/xiangshan/build/asc-counter-print-20260915-v2/mill-out`，
  避免版本插件落入父仓库；不复用原 `out`。
- 仅在源 cwd 执行 `show xiangshan.test.runClasspath`，不执行 runMain。
- 解析 PathRef 后直接运行 `top.XiangShanSim`，cwd 固定为新 arm 目录。
  原因：`src/test/scala/top/SimTop.scala` 的 `FileRegisters.write(fileDir="./build")`
  不受 NOOP_HOME 控制。预先创建独立 cwd/build。
- `NOOP_HOME` 指向 arm/noop，隔离 difftest 的 build/generated-src；RTL 指向 arm/rtl。
- 显式固定 GraalVM JDK 21.0.9、firtool 1.135.0、原生成参数；保留 PATH 中源 resources。
- 匹配原 Makefile 的非 XPROP assert 后处理；旧 SimTop 的 Git banner 是注释，不要求复制。

实现脚本：`build/asc_counter_print_20260915/regenerate_rtl.py`。
各 arm 保留 launch.json、mill.log/classpath.json、run.json；实际启动 JVM 的 arm 另有
compile.json 和 generator.log。后续成功构建及结构结果另文记录。

## 4. 同步对照

`control_ingest_v1` 在 node029 对原 `build/xs/rtl/rtl` 重新执行当前安装版
wolvrix_xs_emit 和冻结 overlay 的 phase A/B/C，不覆盖旧 GRH。
candidate_v4 在 node039；均为生成/结构任务，不是性能测量，不能引用其 wall time
推断 Host 仿真速度。若 fresh control 不重现冻结基线，保留 gate failure 并另行分析。
