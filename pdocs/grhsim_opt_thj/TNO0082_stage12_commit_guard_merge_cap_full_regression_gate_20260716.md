# TNO0082 Stage 12 commit guard merge-cap full regression gate

记录日期：2026-07-16

状态：Stage 12 完整 rebuild 与 CTest `46/48`；activity-schedule、GrhSIM emitter 和全部 ingest 测试通过，失败集合与 Stage 11 完全相同，没有新增回归。

## 1. 命令

所有命令先加载仓库环境：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build -j2
ctest --test-dir wolvrix/build --output-on-failure
```

完整日志：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage12_commit_guard_merge_cap_ctest_20260716.log
```

## 2. 结果

```text
96% tests passed, 2 tests failed out of 48
Total Test time (real) = 389.02 sec
```

本阶段直接相关测试：

```text
transform-activity-schedule  PASS   0.15 sec
emit-grhsim-cpp             PASS 292.79 sec
emit-grhsim-cpp-memory-fill PASS   4.98 sec
```

全部 ingest、GRH、store、基础 emit 和其余 transform suites 通过。

## 3. 既有失败对照

失败仍为：

```text
transform-comb-lane-pack  Expected one packed kAnd for storage frontier rewrite
transform-repcut          expected repcut partition static feature export
```

Stage 11 的完整回归也是 `46/48`，相同测试和相同诊断失败；其余 46 项均通过。因此这两项不是 commit guard two-level coarsening 引入的新回归。

## 4. 阶段闭合

Stage 12 已完成：

- default/explicit `4096` identity 与 focused correctness；
- current-default NO0300 production 结构扫描；
- 三档 full CPP、O3/link 和静态产物检查；
- 100/10k 功能门禁；
- fixed-ASLR 双 socket 50k；
- 完整 rebuild/CTest 与既有失败集合核对。

代码保留高 cap 显式实验能力，默认继续 `4096`。按子模块优先提交实现、测试和公共文档，再提交父仓库 submodule pointer、TNO0078..TNO0082 与 README。
