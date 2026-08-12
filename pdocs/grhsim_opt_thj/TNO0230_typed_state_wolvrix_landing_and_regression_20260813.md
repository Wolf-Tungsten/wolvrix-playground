# TNO0230：typed-state 三项优化落地 Wolvrix 默认与回归

日期：2026-08-13

## 1. 结论与术语勘误

本阶段将 TNO0229 消融中确认有端到端收益的完整 endpoint `SBV` 落入
Wolvrix 的通用 GrhSIM C++ emitter，并默认启用。实现没有新增选项，也没有
针对 SimTop、变量名、端口名或 workload 做特判；`targeted-direct` 未被读取、
修改或间接打开。Wolvrix 子模块提交为 `79ec2037b00f2d4894d72785277ebe3f5d37782d`。

这里需要纠正此前容易引起误解的“**四项优化**”说法：实际是 **三项增量机制**，
而不是四种独立优化；四个名称是消融实验的四个 arm/节点：

| 节点 | 含义 |
| --- | --- |
| `B` | 原始 baseline：persistent state 使用旧的 byte/packed 表示 |
| `S8` | 第一项：按字段/类型组织 persistent-state storage；bool 暂仍使用旧 slot 表示 |
| `SB` | 第二项：persistent-state bool 使用 native `bool` |
| `SBV` | 第三项：materialized value bucket 的 bool 也使用 native `bool` |

因此 `B→S8`、`S8→SB`、`SB→SBV` 是三项相邻增量，`B→SBV` 是三项叠加后的
endpoint；“四组实验”只表示四个对比节点/四个 pair，不表示四种优化。

## 2. 源码与 patch 身份

| 项目 | SHA-256/commit |
| --- | --- |
| baseline `lib/emit/grhsim_cpp.cpp` | `7102ba7fde4dd72e4dc7419f1553b61d555482c49f79984c591d78e85b5239a8` |
| landed `lib/emit/grhsim_cpp.cpp` | `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164` |
| audited patch | `d7ec315534865641cd3a3cc2f76ca70cbf77c3c6191ce0688135ca3016a45325` |
| Wolvrix submodule commit | `79ec2037b00f2d4894d72785277ebe3f5d37782d` |

实现要点集中在 `lib/emit/grhsim_cpp.cpp`：为 state declaration 保存独立的
logic slot index，按 scalar kind/宽度生成字段敏感的 storage struct，使用
`logicCppType` 保留原生 bool 类型，并将 value bucket、state reset 和访问表达式
统一切换到 typed object。byte/宽整数的表示保持原有语义；没有改变事件门禁或
`targeted-direct` 的选项契约。

## 3. 构建与功能回归

每条命令均先执行 `source wolvrix-playground-gsim-calibrate-5/env.sh`。在既有
Release/Ninja 构建树 `wolvrix/build-direct-hot-principled-landing-20260801` 上
完成增量重编译，目标 `wolvrix-lib`、`emit-grhsim-cpp` 和
`emit-grhsim-cpp-memory-fill` 均成功。

- emitter focused CTest：`7/7` 通过。
- 全量 CTest：`51/53` 通过；仅有历史已知失败
  `transform-comb-lane-pack` 和 `transform-repcut`，与本次变更无关，其他测试
  没有新增失败。
- SimpleTES GrhSIM bench/runtime：`115 passed`。
- Wolvrix pybind option tests：`22/22` 通过。
- Wolvrix XS wrapper tests：`32/32` 通过。

提交后再次执行的 focused emitter、pybind 和 XS gate 与提交前结果一致。SimTop
候选 artifact 在子模块提交前由同一份 materialized source 构建；source SHA 与
提交后的文件逐字节一致，因此 binary identity 可复核，而不是把提交后的 SHA
事后推断成新 binary。

## 4. SimTop 50k 端到端回归

正式 headline 是 `Host time spent walltime_ms`。node032 负载较低时完成同 CCD
ABBA+BAAB；两种 order 复用完全相同的 CCD、CPU、SMT sibling、helper CPU 和
NUMA node。运行使用 `setarch x86_64 -R`，process personality 为 `00040000`，
CPU affinity 固定在 CPU 120，CCD 为 `node1:120-127,312-319`，NUMA local ratio
为 `1.0`，PMU scheduled percent 为 `100%`，CPU migrations 为 `0`。

| 对比 | control (ms) | landed candidate (ms) | 减少 (ms) | 改善 |
| --- | ---: | ---: | ---: | ---: |
| `B→SBV` pooled ABBA+BAAB | `48,162.50` | `43,434.50` | `4,728.00` | `9.816766%` |

ABBA 为 `48,201.00→43,457.50 ms`（`9.841082%`），BAAB 为
`48,124.00→43,411.50 ms`（`9.792411%`），order gap 为 `0.048671` 个百分点，
低于 `0.25 pp`。四个 candidate sample 为 `43,467/43,448/43,445/43,378 ms`，
四个 control sample 为 `48,131/48,271/48,096/48,152 ms`；所有 sample 的功能
签名、terminal PC、guest cycle、ASLR、affinity、NUMA 和 PMU gate 均通过。

对应 binary identity：control `7bd9f35e2354ab38af601366dc333fdfe381d8fc51b222ad1d0d0f629e02a604`，
candidate `7eed38e8e005e6a99f81e455265b3227036d8cd121fb71f3724c5df65622873f`。
PMU 解释性均值为 cycles `176,216,200,373.25→158,968,483,751.25`
（`-9.787816%`）、instructions `160,743,747,719.25→149,144,963,970.75`
（`-7.215698%`），但默认决策以 walltime 为准。

当前机曾因外部负载使 9 次尝试无法通过 quiet gate；这些尝试没有产生有效
workload sample，随后转移到 node032 完成正式 pair，不计入性能均值。

## 5. 默认决策与 SimpleTES 延续

由于 endpoint 在同 CCD、关闭 ASLR 的 SimTop 50k 上获得 `9.816766%` walltime
改善，三项机制作为 Wolvrix 通用 C++/Python 流程的默认行为保留。没有增加
SimTop 专用开关，也没有把 `targeted-direct` 当作依赖。

SimpleTES 的 evaluator/launcher 使用精确 parent 与 Wolvrix pin，并在身份不符时
fail-closed。已完成的 bench repin commit 为
`40baf938014bb6a382b54a6d282210f3548edfea`（随后仅更新操作说明的
`7181056377ea03fecb9af2f8b9b9492435c76080`），当前 pin 为 parent
`b2fd50a4cac034cea8420835c6869d05cdde670c`、Wolvrix
`79ec2037b00f2d4894d72785277ebe3f5d37782d`。旧 checkpoint 不会被伪装成新
baseline，后续 research 应从新的 typed-state control seed fresh 启动。

repin 后已验证：

- `evaluator.py init_program.txt --validate-only` 通过，返回 `control` seed；
- GPT 5.6 Sol/max、`config.thj.toml`/`auth.thj.json` 的 launcher `--dry-run`
  生成了 `64 proposals/32 valid`、`4` 个 gen workers、`10,800 s` generation
  timeout 的命令，且没有启动模型或 research；
- `tests/test_grhsim_bench.py tests/test_grhsim_runtime.py` 为 `115 passed`。

因此后续 SimpleTES 可以从新 pin 继续，旧 checkpoint 会按身份契约拒绝；本阶段
不自动启动下一轮 research。

## 6. 复现产物

```text
build/grhsim_typed_state_landing_20260813/landing_identity.json
build/grhsim_typed_state_landing_20260813/B_to_SBV_node032/round-1/result.json
build/grhsim_typed_state_landing_20260813/B_to_SBV_node032.ssh.log
```

历史消融的逐样本日志仍保留在 TNO0229 所列目录；TNO0229 中“四个 patch”的
历史措辞按本记录勘误为“四个实验 arm / 三项增量机制”，历史原始数据不覆盖。
