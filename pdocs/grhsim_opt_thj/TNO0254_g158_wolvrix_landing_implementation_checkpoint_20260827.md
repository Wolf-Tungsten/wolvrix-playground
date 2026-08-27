# TNO0254：g158 Wolvrix 落地实现阶段记录

日期：2026-08-27

## 1. 阶段结论

本阶段把冻结的 g158 `default-path` candidate 落入 Wolvrix 的通用
`lib/emit/grhsim_cpp.cpp`。实现默认执行，不增加 Python/Make 选项，也不读取或
修改 `targeted-direct`；它只根据最终 schedule 中的普通 persistent-state 引用
需求和 phase-tagged supernode signature 决定 `state_logic_storage_t` 的字段声明
顺序。没有使用 SimTop 名称、变量名、benchmark 字符串或运行时测量结果。

Wolvrix 子模块已经先于 parent snapshot 提交，提交为：

```text
054c6a7c09b007a12eb36fdb49fcb659a1bfc590
```

父仓库当前工作树的 executable gitlink snapshot 将在本阶段随后提交；parent
commit、SimpleTES repin 和 50k walltime 结果不在本记录中预填，待实际提交/运行后
追加，避免从 patch 内容推断身份。

## 2. 来源和源码身份

冻结 candidate：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/typed_state_gpt56sol_max_fresh2_20260816_182232/2026-08-16/instance-5f0c84e9/db_state_030132/best_program.txt
```

| 项目 | 身份 |
| --- | --- |
| 原始 Wolvrix source（提交前）SHA-256 | `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164` |
| 落地 `lib/emit/grhsim_cpp.cpp` SHA-256 | `0ed757db91f79df795562677d6f22789ad1aa84df818ef43786e8a18f6bdb196` |
| candidate patch SHA-256 | `cf29862adc2441aed4f72d446295fa5e60557872e7b2c59fa7641608371f72a5` |
| candidate document SHA-256 | `4419814848287a43d93fccb26ccd05cc0042b0985b2c0447a2098de413337416` |
| candidate mode/options | `default-path` / `[]` |

提交前的 baseline source 与当前 `cedf610` 中该文件逐字节相同；落地文件的 SHA
来自提交后的实际文件，而不是由 patch 预先推导。子模块中原有的 `.gitignore`
修改和未跟踪 `external/mt-kahypar` 未被纳入提交。

## 3. 实现边界

g158 新增的排序键依次保留：

1. 是否有普通 state reference；
2. direct/read 计数为 `1`、write 计数为 `2` 的需求量；
3. power-of-two demand class；
4. 精确 demand、phase/unit signature 和原始 graph order；
5. 宽/u64、u32、u16、bool/u8 的 physical group。

它只改变 state logic 的物理声明顺序，字段类型、索引、schedule、guard、event 和
materialized value 的语义保持不变。memory state 与 reg-to-mem intent storage
被明确排除在该排序之外。

## 4. 构建和 focused gate

所有命令先执行 `source wolvrix-playground-gsim-calibrate-5/env.sh`。在新建的
Ninja Release 构建树
`wolvrix/build/g158_landing_20260827` 中，以下目标完成了 fresh C++ 编译：

```text
wolvrix-lib
emit-grhsim-cpp
emit-grhsim-cpp-memory-fill
transform-activity-schedule
```

构建结果为 `187/187` steps、exit `0`。随后直接运行三个新构建的测试程序（不把
未构建的历史 CTest target 误算为失败），均 exit `0`：

```text
bin/emit-grhsim-cpp
bin/emit-grhsim-cpp-memory-fill
bin/transform-activity-schedule
```

CTest 清单仍列出 53 个历史 target，其中许多 executable 未在该 focused 构建中
生成；因此本阶段只报告上述实际执行的 focused/function smoke，完整 SimTop
function gate 与前后性能回归留待后续 TNO。

## 5. 后续闭环

下一阶段将：

- 在 parent 中提交指向 `054c6a7` 的 executable snapshot；
- 以当前 baseline 和 landed source 构建同一 RTL/输入的 immutable emu，执行
  fixed-ASLR、同 CCD 的 ABBA+BAAB SimTop 50k，headline 只取 walltime；
- 按真实 parent snapshot 更新 SimpleTES 五个 pin/seed 文件并跑 bench、launcher
  和功能回归；
- 将绝对 walltime、样本、order gap、ELF SHA-256 和最终 parent/SimpleTES commit
  追加到新的记录中。

